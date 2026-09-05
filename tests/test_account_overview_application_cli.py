from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from rich.console import Console
from typer.testing import CliRunner

import phalanx.account_overview_application as application
import phalanx.account_overview_storage as storage
import phalanx.cli as cli
from phalanx.account_overview import AccountOverviewError
from phalanx.account_overview_application import AccountOverviewResult, OverviewProgress
from phalanx.config import ConfigError
from phalanx.domain.account_overview import AccountOverview
from phalanx.kis.auth import KIS_TOKEN_URL
from phalanx.kis.client import KIS_BALANCE_URL
from phalanx.kis.errors import KisAuthError, KisBalanceHttpError
from phalanx.kis.market_data_client import KIS_CURRENT_PRICE_URL, KisRequestPacer
from phalanx.market_data.errors import CurrentPriceObservationReadError
from phalanx.portfolio.private_json_storage import (
    PrivateJsonAlreadyExistsError,
    PrivateJsonStorageError,
)

START = datetime(2026, 9, 5, tzinfo=UTC)
CODES = ("000660", "000270")
APP_KEY = "synthetic-overview-key"
APP_SECRET = "synthetic-overview-secret"
TOKEN = "synthetic-overview-token"
ACCOUNT = "12345678-01"


class SyntheticAccount:
    def __init__(self, home: Path) -> None:
        self.home = home
        credentials = home / ".config" / "phalanx" / "credentials.env"
        credentials.parent.mkdir(parents=True, mode=0o700)
        descriptor = os.open(credentials, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(
                f"PHALANX_KIS_APP_KEY={APP_KEY}\n"
                f"PHALANX_KIS_APP_SECRET={APP_SECRET}\n"
                f"PHALANX_KIS_ACCOUNT_NUMBER={ACCOUNT}\n"
            )
        self.output_directory = home / ".local" / "share" / "phalanx" / "account-overviews"
        self.elapsed = 0
        self.balance_delay = 1_000_000
        self.quote_delay = 250_000
        self.requests: list[httpx.Request] = []
        self.events: list[OverviewProgress] = []
        self.fail_quote: str | None = None
        self.fail_balance = False
        self.two_pages = False
        self.changed_summary = False
        self.balance_pages_read = 0
        self.pacer = KisRequestPacer(monotonic=lambda: self.elapsed / 1_000_000, sleep=self.sleep)
        self.payload: dict[str, Any] = {
            "rt_cd": "0",
            "msg_cd": "SYNTHETIC",
            "msg1": "Synthetic account only",
            "ctx_area_fk100": "",
            "ctx_area_nk100": "",
            "output1": [
                {
                    "pdno": code,
                    "prdt_name": f"합성종목 {i}",
                    "hldg_qty": str(quantity),
                    "ord_psbl_qty": str(quantity),
                    "pchs_amt": str(amount),
                    "evlu_amt": str(amount),
                    "evlu_pfls_amt": "0",
                }
                for i, (code, quantity, amount) in enumerate(
                    zip(CODES, (1, 3), (200, 300), strict=True)
                )
            ],
            "output2": [
                {
                    "dnca_tot_amt": "50",
                    "scts_evlu_amt": "500",
                    "pchs_amt_smtl_amt": "500",
                    "evlu_amt_smtl_amt": "500",
                    "evlu_pfls_smtl_amt": "0",
                    "tot_evlu_amt": "550",
                    "nass_amt": "550",
                }
            ],
        }

    def sleep(self, seconds: float) -> None:
        self.elapsed += round(seconds * 1_000_000)

    def clock(self) -> datetime:
        return START + timedelta(microseconds=self.elapsed)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url).split("?")[0]
        if request.method == "POST":
            assert url == KIS_TOKEN_URL
            return httpx.Response(
                200,
                json={
                    "access_token": TOKEN,
                    "token_type": "Bearer",
                    "access_token_token_expired": "2099-12-31 23:59:59",
                },
            )
        assert request.method == "GET"
        if url == KIS_BALANCE_URL:
            self.elapsed += self.balance_delay
            self.balance_pages_read += 1
            if self.fail_balance:
                return httpx.Response(500, text=APP_SECRET)
            payload = json.loads(json.dumps(self.payload))
            if self.two_pages:
                first = self.balance_pages_read == 1
                payload["output1"] = payload["output1"][:1] if first else payload["output1"][1:]
                if first:
                    payload["ctx_area_fk100"] = "SYNTHETIC-FK"
                    payload["ctx_area_nk100"] = "SYNTHETIC-NK"
                elif self.changed_summary:
                    payload["output2"][0]["nass_amt"] = "551"
                return httpx.Response(200, json=payload, headers={"tr_cont": "M" if first else ""})
            return httpx.Response(200, json=payload, headers={"tr_cont": ""})
        assert url == KIS_CURRENT_PRICE_URL
        assert request.url.params["FID_COND_MRKT_DIV_CODE"] == "J"
        code = request.url.params["FID_INPUT_ISCD"]
        self.elapsed += self.quote_delay
        if code == self.fail_quote:
            return httpx.Response(500, text=APP_SECRET)
        return httpx.Response(
            200,
            json={
                "rt_cd": "0",
                "msg_cd": "SYNTHETIC",
                "msg1": "Synthetic quote only",
                "output": {
                    "stck_shrn_iscd": code,
                    "stck_prpr": "210.125" if code == CODES[0] else "110",
                },
            },
        )

    def run(self, **kwargs: Any) -> AccountOverviewResult:
        kwargs.setdefault("progress_callback", self.events.append)
        return application.run_production_account_overview(
            transport=httpx.MockTransport(self.handle),
            request_pacer=self.pacer,
            clock=self.clock,
            **kwargs,
        )

    def install_cli(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cli, "run_production_account_overview", self.run)
        monkeypatch.setattr(
            cli,
            "_console",
            lambda *, stderr=False: Console(
                stderr=stderr, width=220, color_system=None, markup=False, highlight=False
            ),
        )


@pytest.fixture
def account(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SyntheticAccount:
    home = tmp_path / "synthetic-home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return SyntheticAccount(home)


def test_real_production_graph_shares_client_and_token_then_saves_complete_private_json(
    account: SyntheticAccount,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients: list[httpx.Client] = []
    original_client = httpx.Client

    def tracked_client(**kwargs: Any) -> httpx.Client:
        client = original_client(**kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(application.httpx, "Client", tracked_client)
    result = account.run()
    assert len(clients) == 1 and clients[0].is_closed
    assert [request.method for request in account.requests] == ["POST", "GET", "GET", "GET"]
    assert [request.url.params["FID_INPUT_ISCD"] for request in account.requests[2:]] == list(CODES)
    assert account.events == [
        OverviewProgress("balance"),
        OverviewProgress("prices", 2),
        OverviewProgress("saving", 2),
    ]
    assert result.saved_path.parent == account.output_directory
    payload = result.saved_path.read_bytes()
    assert AccountOverview.model_validate_json(payload) == result.overview
    assert len(list(account.output_directory.glob("*.json"))) == 1
    assert stat.S_IMODE(result.saved_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(account.output_directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(account.output_directory.parent.stat().st_mode) == 0o700
    for secret in (APP_KEY, APP_SECRET, TOKEN, ACCOUNT, str(account.home)):
        assert secret.encode() not in payload
    assert not (account.output_directory.parent / "snapshots").exists()


def test_balances_from_all_pages_are_used(account: SyntheticAccount) -> None:
    account.two_pages = True
    result = account.run()
    assert result.overview.snapshot.page_count == 2
    assert [position.stock_code for position in result.overview.positions] == list(CODES)
    assert [r.method for r in account.requests] == ["POST", "GET", "GET", "GET", "GET"]


def test_changed_balance_summary_fails_before_quotes_or_storage(account: SyntheticAccount) -> None:
    account.two_pages = account.changed_summary = True
    with pytest.raises(AccountOverviewError) as caught:
        account.run()
    assert caught.value.code == "inconsistent_snapshot"
    assert len(account.requests) == 3
    assert not account.output_directory.exists()


def test_empty_account_does_not_query_prices(account: SyntheticAccount) -> None:
    account.payload["output1"] = []
    result = account.run()
    assert [r.method for r in account.requests] == ["POST", "GET"]
    assert result.overview.positions == ()
    assert account.events == [OverviewProgress("balance"), OverviewProgress("saving", 0)]


def test_unsupported_holding_rejects_the_whole_price_request(account: SyntheticAccount) -> None:
    account.payload["output1"][1]["pdno"] = "SYNTHETIC"
    with pytest.raises(AccountOverviewError) as caught:
        account.run()
    assert caught.value.code == "unsupported_holding"
    assert len(account.requests) == 2
    assert not account.output_directory.exists()


@pytest.mark.parametrize("seconds", [0, -1, True, "60", 0.5, 10**30])
def test_invalid_limit_rejected_before_credentials_or_http(
    account: SyntheticAccount,
    monkeypatch: pytest.MonkeyPatch,
    seconds: int,
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("must validate before I/O")

    monkeypatch.setattr(application, "load_kis_credentials", forbidden)
    monkeypatch.setattr(application.httpx, "Client", forbidden)
    with pytest.raises(AccountOverviewError):
        account.run(max_observation_span_seconds=seconds)
    assert account.requests == []


@pytest.mark.parametrize("failure", ["balance", "first_quote", "second_quote", "total_span"])
def test_failed_refresh_never_displays_or_saves_partial_overview(
    account: SyntheticAccount,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    if failure == "balance":
        account.fail_balance = True
    elif failure == "first_quote":
        account.fail_quote = CODES[0]
    elif failure == "second_quote":
        account.fail_quote = CODES[1]
    else:
        account.balance_delay = 4_000_000
    account.install_cli(monkeypatch)
    result = CliRunner().invoke(
        cli.app, ["account", "overview", "--max-observation-span-seconds", "3"]
    )
    assert (
        result.exit_code
        == {"balance": 30, "first_quote": 60, "second_quote": 60, "total_span": 65}[failure]
    )
    assert "계좌·시세 통합 현황 · READ ONLY" not in result.output
    assert "저장 경로" not in result.output
    assert not account.output_directory.exists()
    assert APP_SECRET not in result.output
    if failure == "first_quote":
        assert len(account.requests) == 3


def test_no_arguments_cli_refreshes_and_saves_without_file_or_stock_options(
    account: SyntheticAccount,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account.install_cli(monkeypatch)
    result = CliRunner().invoke(cli.app, ["account", "overview"])
    assert result.exit_code == 0, result.output
    for text in (
        "증권사 순자산",
        "주문가능현금",
        "미제공",
        "주식 내 비중",
        "손익 아님",
        "합성종목 0",
        "210.125",
        "저장 경로",
    ):
        assert text in result.output
    assert result.output.index(CODES[0]) < result.output.index(CODES[1])
    for secret in (APP_KEY, APP_SECRET, TOKEN, ACCOUNT):
        assert secret not in result.output


def test_store_collision_preserves_existing_file(
    account: SyntheticAccount, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    overview = account.run().overview
    monkeypatch.setattr(storage.secrets, "token_hex", lambda length: "synthetic")
    store = storage.JsonAccountOverviewStore(tmp_path / "collision")
    saved = store.save(overview)
    before = saved.read_bytes()
    with pytest.raises(PrivateJsonAlreadyExistsError):
        store.save(overview)
    assert saved.read_bytes() == before


def test_unsafe_default_directory_is_rejected_without_writing_through_symlink(
    account: SyntheticAccount,
    tmp_path: Path,
) -> None:
    other = tmp_path / "unrelated"
    other.mkdir()
    account.output_directory.parent.mkdir(parents=True, mode=0o700)
    account.output_directory.symlink_to(other, target_is_directory=True)
    with pytest.raises(PrivateJsonStorageError):
        account.run()
    assert list(other.iterdir()) == []


@pytest.mark.parametrize(
    "error, code",
    [
        (ConfigError("synthetic secret"), 10),
        (KisAuthError("synthetic secret"), 20),
        (KisBalanceHttpError("synthetic secret"), 30),
        (CurrentPriceObservationReadError(CODES[0], 0), 60),
        (PrivateJsonStorageError("synthetic secret"), 66),
        (RuntimeError("synthetic secret"), 70),
        (KeyboardInterrupt(), 130),
    ],
)
def test_safe_error_categories(
    error: BaseException, code: int, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail() -> AccountOverviewResult:
        raise error

    assert cli.run_cli_account_overview(fail) == code
    captured = capsys.readouterr()
    assert "synthetic secret" not in captured.out + captured.err
    assert "저장 경로" not in captured.out


def test_help_and_invalid_option_do_not_touch_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(**kwargs: Any) -> AccountOverviewResult:
        raise AssertionError("no work expected")

    monkeypatch.setattr(cli, "run_production_account_overview", forbidden)
    runner = CliRunner()
    assert runner.invoke(cli.app, ["account", "overview", "--help"]).exit_code == 0
    assert (
        runner.invoke(
            cli.app, ["account", "overview", "--max-observation-span-seconds", "0"]
        ).exit_code
        == 2
    )
