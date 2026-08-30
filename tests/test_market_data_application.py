from __future__ import annotations

import os
import stat
from collections.abc import Callable
from datetime import date
from pathlib import Path

import httpx
import pytest

from phalanx.kis.auth import KIS_TOKEN_URL
from phalanx.kis.market_data_client import (
    KIS_DAILY_PRICE_URL,
    KisRateLimitNotification,
    KisRequestPacer,
)
from phalanx.market_data.application import (
    run_production_daily_market_data,
    run_production_universe_market_data,
)
from phalanx.market_data.errors import (
    InvalidMarketDataRangeError,
    InvalidMarketDataStockCodeError,
)
from phalanx.universe.repository import JsonUniverseRepository
from phalanx.universe.service import UniverseService

APP_KEY = "synthetic-market-application-key"
APP_SECRET = "synthetic-market-application-secret"
ACCOUNT_NUMBER = "44332211-01"
ACCESS_TOKEN = "synthetic-market-application-token"
START = date(2026, 8, 1)
END = date(2026, 8, 31)


class TrackingMockTransport(httpx.MockTransport):
    def __init__(self, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        super().__init__(handler)
        self.was_closed = False

    def close(self) -> None:
        self.was_closed = True
        super().close()


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


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


def _daily_response(request: httpx.Request, stock_code: str) -> httpx.Response:
    close_price = "72000" if stock_code == "005930" else "80000"
    return httpx.Response(
        200,
        json={
            "rt_cd": "0",
            "msg_cd": "SYNTHETIC_SUCCESS",
            "msg1": "synthetic success",
            "output1": {},
            "output2": [
                {
                    "stck_bsop_date": "20260801",
                    "stck_oprc": close_price,
                    "stck_hgpr": close_price,
                    "stck_lwpr": close_price,
                    "stck_clpr": close_price,
                    "acml_vol": "1000",
                }
            ],
        },
        request=request,
    )


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat(follow_symlinks=False).st_mode)


def test_production_universe_uses_one_existing_oauth_graph_and_active_stocks_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credentials_path = tmp_path / "config" / "credentials.env"
    token_cache_path = tmp_path / "cache" / "kis-access-token.json"
    universe_path = tmp_path / "data" / "universe.json"
    _write_synthetic_credentials(credentials_path)
    universe = UniverseService(JsonUniverseRepository(universe_path))
    universe.add_stock("005930", "삼성전자", "KOSPI")
    universe.add_stock("035720", "카카오", "KOSPI")
    universe.disable_stock("035720")
    universe.add_stock("035900", "JYP Ent.", "KOSDAQ")
    requests: list[httpx.Request] = []
    clock = FakeClock()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            assert str(request.url) == KIS_TOKEN_URL
            return _token_response(request)
        assert str(request.url).split("?", maxsplit=1)[0] == KIS_DAILY_PRICE_URL
        return _daily_response(request, request.url.params["FID_INPUT_ISCD"])

    transport = TrackingMockTransport(handler)

    def fail_home(cls: type[Path]) -> Path:
        raise AssertionError("all production paths are injected for this test")

    monkeypatch.setattr(Path, "home", classmethod(fail_home))

    results = run_production_universe_market_data(
        START,
        END,
        credentials_path=credentials_path,
        token_cache_path=token_cache_path,
        universe_path=universe_path,
        transport=transport,
        request_pacer=KisRequestPacer(
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        ),
    )

    assert [result.stock.stock_code for result in results] == ["005930", "035900"]
    assert all(len(result.bars) == 1 for result in results)
    assert [request.method for request in requests] == ["POST", "GET", "GET"]
    assert [
        request.url.params["FID_INPUT_ISCD"] for request in requests if request.method == "GET"
    ] == ["005930", "035900"]
    assert sum(request.method == "POST" for request in requests) == 1
    assert clock.sleeps == [1.1]
    assert transport.was_closed
    assert token_cache_path.is_file()
    assert _mode(token_cache_path.parent) == 0o700
    assert _mode(token_cache_path) == 0o600
    assert sorted(path.name for path in tmp_path.rglob("*.json")) == [
        "kis-access-token.json",
        "universe.json",
    ]


def test_production_universe_shares_pacing_and_requests_each_of_nine_stocks_once(
    tmp_path: Path,
) -> None:
    credentials_path = tmp_path / "config" / "credentials.env"
    token_cache_path = tmp_path / "cache" / "kis-access-token.json"
    universe_path = tmp_path / "data" / "universe.json"
    _write_synthetic_credentials(credentials_path)
    universe = UniverseService(JsonUniverseRepository(universe_path))
    stocks = (
        ("000660", "SK하이닉스", "KOSPI"),
        ("005930", "삼성전자", "KOSPI"),
        ("006400", "삼성SDI", "KOSPI"),
        ("035720", "카카오", "KOSPI"),
        ("035900", "JYP Ent.", "KOSDAQ"),
        ("051910", "LG화학", "KOSPI"),
        ("068270", "셀트리온", "KOSPI"),
        ("105560", "KB금융", "KOSPI"),
        ("207940", "삼성바이오로직스", "KOSPI"),
    )
    for stock_code, name, market in stocks:
        universe.add_stock(stock_code, name, market)

    clock = FakeClock()
    requested_codes: list[str] = []
    request_times: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return _token_response(request)
        requested_codes.append(request.url.params["FID_INPUT_ISCD"])
        request_times.append(clock.monotonic())
        return _daily_response(request, request.url.params["FID_INPUT_ISCD"])

    results = run_production_universe_market_data(
        START,
        END,
        credentials_path=credentials_path,
        token_cache_path=token_cache_path,
        universe_path=universe_path,
        transport=TrackingMockTransport(handler),
        request_pacer=KisRequestPacer(
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        ),
    )

    expected_codes = [stock_code for stock_code, _, _ in stocks]
    assert [result.stock.stock_code for result in results] == expected_codes
    assert requested_codes == expected_codes
    assert len(requested_codes) == len(set(requested_codes)) == 9
    assert request_times == pytest.approx([index * 1.1 for index in range(9)])
    assert clock.sleeps == pytest.approx([1.1] * 8)


def test_production_daily_connects_rate_limit_callback_to_client(
    tmp_path: Path,
) -> None:
    credentials_path = tmp_path / "config" / "credentials.env"
    token_cache_path = tmp_path / "cache" / "kis-access-token.json"
    _write_synthetic_credentials(credentials_path)
    requests: list[httpx.Request] = []
    notifications: list[KisRateLimitNotification] = []

    class CallbackObserved(RuntimeError):
        pass

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return _token_response(request)
        return httpx.Response(
            500,
            json={
                "rt_cd": "1",
                "msg_cd": "EGW00201",
                "msg1": "synthetic rate limit",
            },
            request=request,
        )

    def notify(notification: KisRateLimitNotification) -> None:
        notifications.append(notification)
        raise CallbackObserved

    transport = TrackingMockTransport(handler)

    with pytest.raises(CallbackObserved):
        run_production_daily_market_data(
            "000660",
            START,
            END,
            credentials_path=credentials_path,
            token_cache_path=token_cache_path,
            transport=transport,
            rate_limit_callback=notify,
        )

    assert [request.method for request in requests] == ["POST", "GET"]
    assert notifications == [
        KisRateLimitNotification(
            stock_code="000660",
            attempt_number=1,
            max_attempts=3,
            wait_seconds=61.0,
        )
    ]
    assert transport.was_closed


@pytest.mark.parametrize(
    ("stock_code", "start", "end", "expected_error"),
    (
        ("5930", START, END, InvalidMarketDataStockCodeError),
        ("005930", END, START, InvalidMarketDataRangeError),
    ),
)
def test_production_daily_rejects_invalid_request_before_credentials_or_http(
    stock_code: str,
    start: date,
    end: date,
    expected_error: type[Exception],
) -> None:
    def unexpected(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected request: {request.method}")

    with pytest.raises(expected_error):
        run_production_daily_market_data(
            stock_code,
            start,
            end,
            credentials_path=Path("/does/not/exist"),
            token_cache_path=Path("/does/not/exist"),
            transport=httpx.MockTransport(unexpected),
        )
