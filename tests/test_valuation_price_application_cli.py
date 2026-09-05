from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from rich.console import Console
from typer.testing import CliRunner

import phalanx.cli as cli
import phalanx.market_data.application as application
from phalanx.config import ConfigError
from phalanx.domain import CurrentPriceMarket
from phalanx.kis.auth import KIS_TOKEN_URL
from phalanx.kis.errors import KisAuthError
from phalanx.kis.market_data_client import (
    KIS_CURRENT_PRICE_URL,
    KisRateLimitCallback,
    KisRateLimitNotification,
    KisRequestPacer,
)
from phalanx.market_data.application import ValuationPriceResult, run_production_valuation_prices
from phalanx.market_data.errors import MarketDataError
from phalanx.portfolio.private_json_storage import PrivateJsonStorageError

START = datetime(2026, 9, 5, 0, 0, 0, tzinfo=UTC)
CODES = ("000270", "000660")
PRICES = ("108000.25", "201000.12345678901234567890123456789")
APP_KEY = "synthetic-valuation-app-key"
APP_SECRET = "synthetic-valuation-app-secret"
TOKEN = "synthetic-valuation-token"
ACCOUNT_NUMBER = "12345678-01"


class SyntheticQuotes:
    """Exercise the real credential, OAuth, current-price and service graph with fake I/O."""

    def __init__(self, directory: Path) -> None:
        self.credentials_path = directory / "config" / "credentials.env"
        self.credentials_path.parent.mkdir(mode=0o700)
        descriptor = os.open(self.credentials_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(
                f"PHALANX_KIS_APP_KEY={APP_KEY}\n"
                f"PHALANX_KIS_APP_SECRET={APP_SECRET}\n"
                f"PHALANX_KIS_ACCOUNT_NUMBER={ACCOUNT_NUMBER}\n"
            )
        self.token_cache_path = directory / "cache" / "kis-access-token.json"
        self.elapsed_microseconds = 0
        self.sleeps: list[float] = []
        self.requests: list[httpx.Request] = []
        self.get_times: list[int] = []
        self.failure_code: str | None = None
        self.rate_limit_code: str | None = None
        self.final_delay_microseconds = 100_000
        self.notifications: list[KisRateLimitNotification] = []
        self.transport = httpx.MockTransport(self.handle)
        self.pacer = KisRequestPacer(monotonic=self.monotonic, sleep=self.sleep)

    def clock(self) -> datetime:
        return START + timedelta(microseconds=self.elapsed_microseconds)

    def monotonic(self) -> float:
        return self.elapsed_microseconds / 1_000_000

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.elapsed_microseconds += round(seconds * 1_000_000)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method == "POST":
            assert str(request.url) == KIS_TOKEN_URL
            return httpx.Response(
                200,
                json={
                    "access_token": TOKEN,
                    "token_type": "Bearer",
                    "access_token_token_expired": "2099-12-31 23:59:59",
                },
            )
        assert request.method == "GET"
        assert str(request.url).split("?")[0] == KIS_CURRENT_PRICE_URL
        assert request.url.params["FID_COND_MRKT_DIV_CODE"] == "J"
        assert set(request.url.params) == {"FID_COND_MRKT_DIV_CODE", "FID_INPUT_ISCD"}
        code = request.url.params["FID_INPUT_ISCD"]
        self.get_times.append(self.elapsed_microseconds)
        self.elapsed_microseconds += self.final_delay_microseconds if code == CODES[1] else 100_000
        if code == self.failure_code:
            return httpx.Response(500, text=f"synthetic upstream failure {APP_SECRET}")
        if code == self.rate_limit_code:
            return httpx.Response(429, json={"rt_cd": "1", "msg_cd": "EGW00201"})
        return httpx.Response(
            200,
            json={
                "rt_cd": "0",
                "msg_cd": "SYNTHETIC_SUCCESS",
                "msg1": "synthetic success",
                "output": {"stck_shrn_iscd": code, "stck_prpr": PRICES[CODES.index(code)]},
            },
        )

    def run(
        self,
        stock_codes: tuple[str, ...] = CODES,
        *,
        max_acquisition_span_seconds: int = 60,
        output_path: Path | None = None,
        rate_limit_callback: KisRateLimitCallback | None = None,
    ) -> ValuationPriceResult:
        return run_production_valuation_prices(
            stock_codes,
            max_acquisition_span_seconds=max_acquisition_span_seconds,
            output_path=output_path,
            credentials_path=self.credentials_path,
            token_cache_path=self.token_cache_path,
            transport=self.transport,
            request_pacer=self.pacer,
            rate_limit_callback=rate_limit_callback,
            clock=self.clock,
        )

    def install_cli(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cli, "run_production_valuation_prices", self.run)
        monkeypatch.setattr(
            cli,
            "_console",
            lambda *, stderr=False: Console(
                stderr=stderr,
                width=240,
                color_system=None,
                markup=False,
                highlight=False,
            ),
        )


@pytest.fixture
def quotes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SyntheticQuotes:
    def fail_home(cls: type[Path]) -> Path:
        raise AssertionError("real credential/cache lookup is forbidden")

    monkeypatch.setattr(Path, "home", classmethod(fail_home))
    return SyntheticQuotes(tmp_path)


def _arguments(*extra: str) -> list[str]:
    return [
        "market-data",
        "valuation-prices",
        "--stock-code",
        CODES[0],
        "--stock-code",
        CODES[1],
        *extra,
    ]


def test_production_shares_http_oauth_and_pacing_and_reuses_token_cache(
    quotes: SyntheticQuotes, monkeypatch: pytest.MonkeyPatch
) -> None:
    client_factory = httpx.Client
    clients: list[httpx.Client] = []

    def record_client(*args: Any, **kwargs: Any) -> httpx.Client:
        client = client_factory(*args, **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(application.httpx, "Client", record_client)
    result = quotes.run()

    assert result.saved_path is None
    assert result.max_acquisition_span_seconds == 60
    assert result.bundle.stock_codes == CODES
    assert result.bundle.valuation_prices == tuple(Decimal(price) for price in PRICES)
    assert result.bundle.market is CurrentPriceMarket.KRX
    assert [request.method for request in quotes.requests] == ["POST", "GET", "GET"]
    assert len(clients) == 1 and clients[0].is_closed
    assert quotes.get_times == [0, 1_100_000]
    assert quotes.sleeps == [1.0]
    assert result.bundle.acquisition_span == timedelta(microseconds=1_200_000)
    assert result.bundle.observations[1].request_started_at == (
        START + timedelta(microseconds=100_000)
    )
    assert stat.S_IMODE(quotes.token_cache_path.stat().st_mode) == 0o600

    reverse = quotes.run(tuple(reversed(CODES)))
    assert reverse.bundle.stock_codes == tuple(reversed(CODES))
    assert sum(request.method == "POST" for request in quotes.requests) == 1
    assert len(clients) == 2 and all(client.is_closed for client in clients)


@pytest.mark.parametrize(
    "codes",
    [
        (),
        [],
        ("000270", "000270"),
        ("000270", "bad"),
        ("00027",),
        (" 000270",),
        ("\uff10" * 6,),
        (270,),
    ],
)
def test_application_rejects_all_bad_codes_before_credentials_or_http(
    codes: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("invalid input reached credentials or networking")

    monkeypatch.setattr(application, "load_kis_credentials", forbidden)
    monkeypatch.setattr(application.httpx, "Client", forbidden)
    output = tmp_path / "uncreated" / "prices.json"
    with pytest.raises(MarketDataError):
        run_production_valuation_prices(codes, output_path=output)
    assert not output.parent.exists()


@pytest.mark.parametrize("seconds", [0, -1, True, 1.5, "60", 10**30])
def test_application_rejects_bad_collection_limit_before_credentials_or_http(
    seconds: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("invalid span reached credentials or networking")

    monkeypatch.setattr(application, "load_kis_credentials", forbidden)
    monkeypatch.setattr(application.httpx, "Client", forbidden)
    with pytest.raises(MarketDataError):
        run_production_valuation_prices(CODES, max_acquisition_span_seconds=seconds)


def test_cli_saves_complete_exact_decimal_bundle_and_preserves_existing_file(
    quotes: SyntheticQuotes, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    quotes.install_cli(monkeypatch)
    output = tmp_path / "prices" / "result.json"
    args = _arguments("--max-acquisition-span-seconds", "60", "--output", str(output))
    result = CliRunner().invoke(cli.app, args)

    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    for expected in (
        "READ ONLY",
        "종목코드",
        "가격 (KRW)",
        "시장",
        "KRX",
        "요청 관측시각",
        "응답 관측시각",
        "2026-09-05 09:00:00 KST",
        "2026-09-05 09:00:01.200000 KST",
        "108,000.25",
        "실제 체결시각이 아닙니다",
    ):
        assert expected in result.stdout
    assert result.stdout.index(CODES[0]) < result.stdout.index(CODES[1])
    original = output.read_bytes()
    saved = json.loads(original)
    assert saved["schema_version"] == "1"
    assert saved["stock_codes"] == list(CODES)
    assert saved["currency"] == "KRW" and saved["market"] == "KRX"
    assert saved["max_acquisition_span_seconds"] == 60
    assert saved["acquisition_span_microseconds"] == 1_200_000
    assert saved["request_started_at"] == START.isoformat()
    assert saved["received_at"] == (START + timedelta(microseconds=1_200_000)).isoformat()
    assert [row["stock_code"] for row in saved["observations"]] == list(CODES)
    assert [row["current_price"] for row in saved["observations"]] == list(PRICES)
    assert saved["observations"][1]["request_started_at"] == "2026-09-05T00:00:00.100000Z"
    assert saved["observations"][1]["received_at"] == "2026-09-05T00:00:01.200000Z"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert stat.S_IMODE(output.parent.stat().st_mode) == 0o700
    for secret in (APP_KEY, APP_SECRET, TOKEN, ACCOUNT_NUMBER):
        assert secret.encode() not in original
        assert secret not in result.output

    second = CliRunner().invoke(cli.app, args)
    assert second.exit_code == cli.ExitCode.MARKET_DATA_STORAGE
    assert "이미 존재합니다" in second.stderr
    assert output.read_bytes() == original


def test_cli_without_output_uses_default_limit_and_does_not_call_storage(
    quotes: SyntheticQuotes, monkeypatch: pytest.MonkeyPatch
) -> None:
    quotes.install_cli(monkeypatch)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("--output was not requested")

    monkeypatch.setattr(application, "store_private_json_bytes", forbidden)
    result = CliRunner().invoke(cli.app, _arguments())
    assert result.exit_code == 0, result.output
    assert "수집 허용시간: 60초" in result.stdout
    assert "저장 경로" not in result.stdout


@pytest.mark.parametrize(
    ("arguments", "code"),
    [
        ([], 2),
        (["--stock-code", "000270", "--stock-code", "000270"], 60),
        (["--stock-code", "000270", "--stock-code", "bad"], 60),
        (["--stock-code", "000270", "--max-acquisition-span-seconds", "0"], 2),
        (["--stock-code", "000270", "--max-acquisition-span-seconds", "-1"], 2),
        (["--stock-code", "000270", "--max-acquisition-span-seconds", "1.5"], 2),
    ],
)
def test_cli_invalid_inputs_never_access_credentials_or_network(
    arguments: list[str], code: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("invalid CLI input reached credentials or HTTP")

    monkeypatch.setattr(application, "load_kis_credentials", forbidden)
    monkeypatch.setattr(application.httpx, "Client", forbidden)
    result = CliRunner().invoke(cli.app, ["market-data", "valuation-prices", *arguments])
    assert result.exit_code == code, result.output


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("failure", ["read", "span"])
def test_cli_mid_query_failure_and_span_overrun_never_save_partial_results(
    quotes: SyntheticQuotes,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    existing: bool,
    failure: str,
) -> None:
    quotes.install_cli(monkeypatch)
    output = tmp_path / "prices" / "result.json"
    if existing:
        output.parent.mkdir()
        output.write_bytes(b"existing user result\n")
    if failure == "read":
        quotes.failure_code = CODES[1]
        args = _arguments("--stock-code", "005930", "--output", str(output))
    else:
        args = _arguments("--max-acquisition-span-seconds", "1", "--output", str(output))
    result = CliRunner().invoke(cli.app, args)

    assert result.exit_code == cli.ExitCode.MARKET_DATA, result.output
    assert "현재가 조회 오류" in result.stderr
    assert (CODES[1] if failure == "read" else "수집 허용시간") in result.stderr
    assert APP_SECRET not in result.output
    assert "가격 (KRW)" not in result.stdout
    assert [
        request.url.params["FID_INPUT_ISCD"]
        for request in quotes.requests
        if request.method == "GET"
    ] == list(CODES)
    if existing:
        assert output.read_bytes() == b"existing user result\n"
        assert list(output.parent.iterdir()) == [output]
    else:
        assert not output.parent.exists()


@pytest.mark.parametrize(("extra_microseconds", "expected_code"), [(0, 0), (1, 60)])
def test_acquisition_span_limit_is_inclusive_to_the_microsecond(
    quotes: SyntheticQuotes,
    monkeypatch: pytest.MonkeyPatch,
    extra_microseconds: int,
    expected_code: int,
) -> None:
    quotes.final_delay_microseconds = 900_000 + extra_microseconds
    quotes.install_cli(monkeypatch)
    result = CliRunner().invoke(cli.app, _arguments("--max-acquisition-span-seconds", "2"))
    assert result.exit_code == expected_code, result.output


def test_rate_limit_callback_is_connected_without_real_waiting(
    quotes: SyntheticQuotes, monkeypatch: pytest.MonkeyPatch
) -> None:
    quotes.rate_limit_code = CODES[1]
    original = cli.render_rate_limit_notification

    def notify(notification: KisRateLimitNotification, console: Console) -> None:
        quotes.notifications.append(notification)
        original(notification, console)
        # Stop at the callback boundary before the production 61-second retry wait.
        raise RuntimeError("synthetic callback interruption")

    monkeypatch.setattr(cli, "render_rate_limit_notification", notify)
    quotes.install_cli(monkeypatch)
    result = CliRunner().invoke(cli.app, _arguments())
    assert result.exit_code == cli.ExitCode.MARKET_DATA
    assert len(quotes.notifications) == 1
    assert quotes.notifications[0].stock_code == CODES[1]
    assert "KIS 호출 제한: 000660" in result.stdout
    assert "61초 후 재시도" in result.stdout
    assert "synthetic callback interruption" not in result.output


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (ConfigError("synthetic-sensitive-config"), 10),
        (KisAuthError("synthetic-sensitive-auth"), 20),
        (PrivateJsonStorageError("synthetic-sensitive-storage"), 66),
        (RuntimeError("synthetic-sensitive-unexpected"), 70),
        (KeyboardInterrupt(), 130),
    ],
)
def test_cli_failure_categories_hide_arbitrary_details(
    error: BaseException, expected_code: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: Any, **kwargs: Any) -> ValuationPriceResult:
        raise error

    monkeypatch.setattr(cli, "run_production_valuation_prices", fail)
    result = CliRunner().invoke(cli.app, _arguments())
    assert result.exit_code == expected_code
    assert "synthetic-sensitive" not in result.output
    assert "Traceback" not in result.output


def test_cli_help_lists_repeated_codes_default_limit_and_optional_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COLUMNS", "160")
    result = CliRunner().invoke(
        cli.app, ["market-data", "valuation-prices", "--help"], terminal_width=160
    )
    assert result.exit_code == 0
    for expected in ("--stock-code", "--max-acquisition-span-seconds", "--output", "60", "KRX"):
        assert expected in result.stdout
