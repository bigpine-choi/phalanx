from __future__ import annotations

import json
import os
import stat
from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest

from phalanx.application import (
    AccountSnapshotApplication,
    AccountSnapshotResult,
    run_production_snapshot,
)
from phalanx.domain import (
    AccountPosition,
    AccountSnapshot,
    AccountSummary,
    ApiPageEvidence,
    SnapshotEvidence,
)
from phalanx.kis.errors import KisBalanceHttpError
from phalanx.snapshots import SnapshotStorageError

SEOUL = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 8, 29, 12, 0, 0, tzinfo=SEOUL)
FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "kis"
APP_KEY = "synthetic-application-app-key"
APP_SECRET = "synthetic-application-app-secret"
ACCOUNT_NUMBER = "44332211-01"
ACCESS_TOKEN = "synthetic-application-access-token"


class FakeBalanceReader:
    def __init__(self, snapshot: AccountSnapshot, calls: list[str]) -> None:
        self.snapshot = snapshot
        self.calls = calls

    def fetch_balance(self) -> AccountSnapshot:
        self.calls.append("fetch")
        return self.snapshot


class FailingBalanceReader:
    def fetch_balance(self) -> AccountSnapshot:
        raise KisBalanceHttpError("synthetic safe query failure")


class RecordingSnapshotWriter:
    def __init__(
        self,
        expected_snapshot: AccountSnapshot,
        saved_path: Path,
        calls: list[str],
    ) -> None:
        self.expected_snapshot = expected_snapshot
        self.saved_path = saved_path
        self.calls = calls

    def save(self, snapshot: AccountSnapshot) -> Path:
        assert snapshot is self.expected_snapshot
        self.calls.append("save")
        return self.saved_path


class UnexpectedSnapshotWriter:
    def save(self, snapshot: AccountSnapshot) -> Path:
        raise AssertionError(f"unexpected partial snapshot save: {snapshot.account_number_masked}")


class FailingSnapshotWriter:
    def save(self, snapshot: AccountSnapshot) -> Path:
        raise SnapshotStorageError("synthetic safe storage failure")


class TrackingMockTransport(httpx.MockTransport):
    def __init__(self, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        super().__init__(handler)
        self.was_closed = False

    def close(self) -> None:
        self.was_closed = True
        super().close()


def _snapshot(*, empty: bool = False) -> AccountSnapshot:
    position = AccountPosition(
        stock_code="SYNTHAPP",
        product_name="Synthetic Application Equity",
        holding_quantity=Decimal("12.5000"),
        sellable_quantity=Decimal("10.2500"),
        purchase_amount=Decimal("1234567890.1234"),
        evaluation_amount=Decimal("1300000000.5678"),
        profit_loss=Decimal("65432110.4444"),
    )
    return AccountSnapshot(
        account_number_masked="4433****-**",
        query_started_at=NOW,
        query_completed_at=NOW + timedelta(seconds=1),
        summary=AccountSummary(
            deposit_total=Decimal("1000000.50"),
            securities_evaluation_amount=Decimal("1300000000.5678"),
            purchase_amount_total=Decimal("1234567890.1234"),
            evaluation_amount_total=Decimal("1300000000.5678"),
            profit_loss_total=Decimal("65432110.4444"),
            total_assets=Decimal("1301000001.0678"),
            net_assets=Decimal("1301000001.0678"),
        ),
        positions=() if empty else (position,),
        zero_quantity_balances=(),
        evidence=SnapshotEvidence(
            pages=(
                ApiPageEvidence(
                    received_at=NOW + timedelta(seconds=1),
                    http_status=200,
                    tr_cont="",
                    ctx_area_fk100="",
                    ctx_area_nk100="",
                    rt_cd="0",
                    msg_cd="SYNTHETIC_SUCCESS",
                    msg1="synthetic success",
                    response_body_sha256="a" * 64,
                ),
            )
        ),
    )


def _load_fixture(name: str) -> dict[str, Any]:
    loaded = json.loads((FIXTURE_DIRECTORY / name).read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _write_synthetic_credentials(path: Path) -> None:
    path.parent.mkdir(mode=0o700, parents=True)
    path.parent.chmod(0o700)
    contents = (
        f"PHALANX_KIS_APP_KEY={APP_KEY}\n"
        f"PHALANX_KIS_APP_SECRET={APP_SECRET}\n"
        f"PHALANX_KIS_ACCOUNT_NUMBER={ACCOUNT_NUMBER}\n"
    ).encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, contents)
    finally:
        os.close(descriptor)


def _token_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "access_token": ACCESS_TOKEN,
            "token_type": "Bearer",
            "access_token_token_expired": "2099-12-31 23:59:59",
        },
        request=request,
    )


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat(follow_symlinks=False).st_mode)


def test_application_fetches_before_saving_and_returns_complete_result(tmp_path: Path) -> None:
    snapshot = _snapshot()
    calls: list[str] = []
    saved_path = tmp_path / "saved.json"
    application = AccountSnapshotApplication(
        FakeBalanceReader(snapshot, calls),
        RecordingSnapshotWriter(snapshot, saved_path, calls),
    )

    result = application.run()

    assert result == AccountSnapshotResult(snapshot=snapshot, saved_path=saved_path)
    assert calls == ["fetch", "save"]


def test_query_failure_never_calls_snapshot_writer() -> None:
    application = AccountSnapshotApplication(
        FailingBalanceReader(),
        UnexpectedSnapshotWriter(),
    )

    with pytest.raises(KisBalanceHttpError):
        application.run()


def test_storage_failure_returns_no_success_result() -> None:
    application = AccountSnapshotApplication(
        FakeBalanceReader(_snapshot(), []),
        FailingSnapshotWriter(),
    )

    with pytest.raises(SnapshotStorageError):
        application.run()


@pytest.mark.parametrize("page_count", (1, 2))
def test_production_factory_connects_mock_oauth_balance_and_storage_without_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    page_count: int,
) -> None:
    credentials_path = tmp_path / "config" / "credentials.env"
    token_cache_path = tmp_path / "cache" / "kis-access-token.json"
    snapshot_directory = tmp_path / "data" / "snapshots"
    _write_synthetic_credentials(credentials_path)
    page1 = _load_fixture(
        "balance_single_page.json" if page_count == 1 else "balance_multi_page_1.json"
    )
    page2 = _load_fixture("balance_multi_page_2.json")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return _token_response(request)
        balance_request_number = sum(item.method == "GET" for item in requests)
        if page_count == 2 and balance_request_number == 1:
            return httpx.Response(200, json=page1, headers={"tr_cont": "M"}, request=request)
        return httpx.Response(
            200,
            json=page1 if page_count == 1 else page2,
            headers={"tr_cont": ""},
            request=request,
        )

    transport = TrackingMockTransport(handler)

    def fail_home(cls: type[Path]) -> Path:
        raise AssertionError("all production paths are injected for this test")

    monkeypatch.setattr(Path, "home", classmethod(fail_home))

    result = run_production_snapshot(
        credentials_path=credentials_path,
        token_cache_path=token_cache_path,
        snapshot_directory=snapshot_directory,
        transport=transport,
    )

    assert result.saved_path.is_file()
    assert result.saved_path.parent == snapshot_directory
    assert result.snapshot.page_count == page_count
    assert [request.method for request in requests] == ["POST"] + ["GET"] * page_count
    assert transport.was_closed
    assert token_cache_path.is_file()
    assert _mode(token_cache_path.parent) == 0o700
    assert _mode(token_cache_path) == 0o600
    assert _mode(snapshot_directory) == 0o700
    assert _mode(result.saved_path) == 0o600
    serialized = result.saved_path.read_text(encoding="utf-8")
    for secret in (APP_KEY, APP_SECRET, ACCOUNT_NUMBER, ACCESS_TOKEN, "44332211"):
        assert secret not in serialized


def test_production_query_failure_creates_no_snapshot_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credentials_path = tmp_path / "config" / "credentials.env"
    token_cache_path = tmp_path / "cache" / "kis-access-token.json"
    snapshot_directory = tmp_path / "data" / "snapshots"
    _write_synthetic_credentials(credentials_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return _token_response(request)
        return httpx.Response(500, content=b"synthetic failure", request=request)

    monkeypatch.setattr(
        Path,
        "home",
        classmethod(lambda cls: (_ for _ in ()).throw(AssertionError("unexpected home access"))),
    )

    with pytest.raises(KisBalanceHttpError):
        run_production_snapshot(
            credentials_path=credentials_path,
            token_cache_path=token_cache_path,
            snapshot_directory=snapshot_directory,
            transport=httpx.MockTransport(handler),
        )

    assert not snapshot_directory.exists()
