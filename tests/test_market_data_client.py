from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest
from pydantic import SecretStr

from phalanx.config import KisCredentials
from phalanx.kis.auth import AccessToken
from phalanx.kis.errors import (
    KisMarketDataApiError,
    KisMarketDataAuthenticationError,
    KisMarketDataHttpError,
    KisMarketDataProtocolError,
    KisMarketDataRateLimitError,
    KisMarketDataTimeoutError,
)
from phalanx.kis.market_data_client import (
    KIS_DAILY_PRICE_PATH,
    KIS_DAILY_PRICE_TR_ID,
    KIS_DAILY_PRICE_URL,
    KisDailyPriceClient,
    KisRateLimitNotification,
    KisRequestPacer,
)
from phalanx.market_data.errors import (
    InvalidMarketDataRangeError,
    InvalidMarketDataStockCodeError,
)

APP_KEY = "synthetic-market-data-app-key"
APP_SECRET = "synthetic-market-data-app-secret"
ACCOUNT_NUMBER = "87654321-01"
FIRST_TOKEN = "synthetic-market-data-token-one"
SECOND_TOKEN = "synthetic-market-data-token-two"
START = date(2026, 8, 5)
END = date(2026, 8, 10)

Handler = Callable[[httpx.Request], httpx.Response]
ClientFactory = Callable[[Handler], httpx.Client]


class StubTokenManager:
    def __init__(self, tokens: tuple[AccessToken, ...] | None = None) -> None:
        self.tokens = tokens or (_access_token(FIRST_TOKEN),)
        self.current_index = 0
        self.get_calls = 0
        self.invalidated: list[AccessToken] = []

    def get_access_token(self) -> AccessToken:
        self.get_calls += 1
        return self.tokens[self.current_index]

    def invalidate_if_current(self, token: AccessToken) -> bool:
        self.invalidated.append(token)
        current = self.tokens[self.current_index]
        if token.access_token.get_secret_value() != current.access_token.get_secret_value():
            return False
        if self.current_index + 1 < len(self.tokens):
            self.current_index += 1
        return True


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def client_factory() -> Iterator[ClientFactory]:
    clients: list[httpx.Client] = []

    def create(handler: Handler) -> httpx.Client:
        client = httpx.Client(transport=httpx.MockTransport(handler))
        clients.append(client)
        return client

    yield create

    for client in clients:
        client.close()


def _credentials() -> KisCredentials:
    return KisCredentials(
        app_key=APP_KEY,
        app_secret=APP_SECRET,
        account_number=ACCOUNT_NUMBER,
    )


def _access_token(value: str) -> AccessToken:
    return AccessToken(
        access_token=SecretStr(value),
        token_type="Bearer",
        expires_at=datetime(2099, 1, 1, tzinfo=UTC),
    )


def _row(
    trade_date: str,
    *,
    open_price: str = "100",
    high_price: str = "120",
    low_price: str = "90",
    close_price: str = "110",
    volume: str = "1000",
) -> dict[str, str]:
    return {
        "stck_bsop_date": trade_date,
        "stck_oprc": open_price,
        "stck_hgpr": high_price,
        "stck_lwpr": low_price,
        "stck_clpr": close_price,
        "acml_vol": volume,
    }


def _success(request: httpx.Request, *rows: object) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "rt_cd": "0",
            "msg_cd": "SYNTHETIC_SUCCESS",
            "msg1": "synthetic success",
            "output1": {},
            "output2": list(rows),
        },
        request=request,
    )


def _full_page(request: httpx.Request, *rows: object) -> httpx.Response:
    if not rows or len(rows) > 100:
        raise AssertionError("a synthetic full page needs between 1 and 100 rows")
    padded_rows = list(rows)
    padded_rows.extend([rows[-1]] * (100 - len(padded_rows)))
    return _success(request, *padded_rows)


def _api_error(
    request: httpx.Request,
    *,
    msg_cd: str,
    msg1: str,
    status_code: int = 500,
    rt_cd: str = "1",
) -> httpx.Response:
    return httpx.Response(
        status_code,
        json={"rt_cd": rt_cd, "msg_cd": msg_cd, "msg1": msg1},
        request=request,
    )


def test_request_pacer_runs_first_request_immediately_and_waits_only_remaining_time() -> None:
    clock = FakeClock()
    pacer = KisRequestPacer(monotonic=clock.monotonic, sleep=clock.sleep)

    pacer.wait_before_request()
    assert clock.sleeps == []

    clock.now += 0.4
    pacer.wait_before_request()
    assert clock.sleeps == pytest.approx([0.7])

    clock.now += 1.2
    pacer.wait_before_request()
    assert clock.sleeps == pytest.approx([0.7])


def test_client_uses_exact_fixed_read_only_kis_contract(
    client_factory: ClientFactory,
) -> None:
    requests: list[httpx.Request] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _success(request, _row("20260805"))

    token_manager = StubTokenManager()
    result = KisDailyPriceClient(
        _credentials(),
        token_manager,
        client=client_factory(handler),
        sleep=sleeps.append,
    ).fetch_daily_bars("005930", START, END)

    assert len(result) == 1
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert str(request.url).split("?", maxsplit=1)[0] == KIS_DAILY_PRICE_URL
    assert request.url.scheme == "https"
    assert request.url.host == "openapi.koreainvestment.com"
    assert request.url.port == 9443
    assert request.url.path == KIS_DAILY_PRICE_PATH
    assert request.content == b""
    assert request.headers["authorization"] == f"Bearer {FIRST_TOKEN}"
    assert request.headers["appkey"] == APP_KEY
    assert request.headers["appsecret"] == APP_SECRET
    assert request.headers["tr_id"] == KIS_DAILY_PRICE_TR_ID == "FHKST03010100"
    assert request.headers["custtype"] == "P"
    assert dict(request.url.params) == {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": "005930",
        "FID_INPUT_DATE_1": "20260805",
        "FID_INPUT_DATE_2": "20260810",
        "FID_PERIOD_DIV_CODE": "D",
        "FID_ORG_ADJ_PRC": "0",
    }
    assert token_manager.get_calls == 1
    assert sleeps == []


def test_client_filters_range_sorts_and_preserves_exact_decimals(
    client_factory: ClientFactory,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _success(
            request,
            _row("20260810", close_price="110.25"),
            _row("20260808", close_price="108.125"),
            _row("20260804", close_price="104.5"),
        )

    bars = KisDailyPriceClient(
        _credentials(),
        StubTokenManager(),
        client=client_factory(handler),
    ).fetch_daily_bars("005930", START, END)

    assert [bar.trade_date for bar in bars] == [date(2026, 8, 8), date(2026, 8, 10)]
    assert [bar.close_price for bar in bars] == [Decimal("108.125"), Decimal("110.25")]


def test_client_pages_backwards_deduplicates_and_filters_out_of_range_rows(
    client_factory: ClientFactory,
) -> None:
    requested_end_dates: list[str] = []
    request_times: list[float] = []
    clock = FakeClock()

    def handler(request: httpx.Request) -> httpx.Response:
        request_times.append(clock.monotonic())
        end_cursor = request.url.params["FID_INPUT_DATE_2"]
        requested_end_dates.append(end_cursor)
        if end_cursor == "20260810":
            return _full_page(request, _row("20260810"), _row("20260809"))
        if end_cursor == "20260808":
            return _full_page(
                request,
                _row("20260809"),
                _row("20260808"),
                _row("20260807"),
            )
        assert end_cursor == "20260806"
        return _success(
            request,
            _row("20260806"),
            _row("20260805"),
            _row("20260804"),
        )

    bars = KisDailyPriceClient(
        _credentials(),
        StubTokenManager(),
        client=client_factory(handler),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    ).fetch_daily_bars("005930", START, END)

    assert requested_end_dates == ["20260810", "20260808", "20260806"]
    assert request_times == pytest.approx([0.0, 1.1, 2.2])
    assert clock.sleeps == pytest.approx([1.1, 1.1])
    assert [bar.trade_date for bar in bars] == [date(2026, 8, day) for day in range(5, 11)]


def test_client_stops_after_one_short_page_without_a_duplicate_http_request(
    client_factory: ClientFactory,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _success(
            request,
            *(_row(f"202608{day:02d}") for day in range(10, 5, -1)),
        )

    bars = KisDailyPriceClient(
        _credentials(),
        StubTokenManager(),
        client=client_factory(handler),
    ).fetch_daily_bars("005930", START, END)

    assert len(bars) == 5
    assert len(requests) == 1


def test_client_rejects_an_identical_repeated_page(client_factory: ClientFactory) -> None:
    clock = FakeClock()

    def handler(request: httpx.Request) -> httpx.Response:
        return _full_page(request, _row("20260810"), _row("20260809"))

    with pytest.raises(KisMarketDataProtocolError, match="repeated an identical page"):
        KisDailyPriceClient(
            _credentials(),
            StubTokenManager(),
            client=client_factory(handler),
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        ).fetch_daily_bars("005930", START, END)


def test_client_rejects_a_cursor_that_does_not_move_into_the_past(
    client_factory: ClientFactory,
) -> None:
    calls = 0
    clock = FakeClock()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return _full_page(request, _row("20260810"), _row("20260808"))
        return _success(request, _row("20260809", close_price="111"))

    with pytest.raises(KisMarketDataProtocolError, match="did not move into the past"):
        KisDailyPriceClient(
            _credentials(),
            StubTokenManager(),
            client=client_factory(handler),
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        ).fetch_daily_bars("005930", START, END)

    assert calls == 2


def test_client_enforces_a_bounded_maximum_page_count(
    client_factory: ClientFactory,
) -> None:
    calls = 0
    clock = FakeClock()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        trade_date = "20260810" if calls == 1 else "20260808"
        return _full_page(request, _row(trade_date))

    with pytest.raises(KisMarketDataProtocolError, match="configured page limit"):
        KisDailyPriceClient(
            _credentials(),
            StubTokenManager(),
            client=client_factory(handler),
            max_pages=2,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        ).fetch_daily_bars("005930", START, END)

    assert calls == 2


def test_client_returns_empty_history_for_an_empty_output2(
    client_factory: ClientFactory,
) -> None:
    bars = KisDailyPriceClient(
        _credentials(),
        StubTokenManager(),
        client=client_factory(lambda request: _success(request)),
    ).fetch_daily_bars("005930", START, END)

    assert bars == ()


def test_client_rejects_conflicting_duplicate_trading_dates(
    client_factory: ClientFactory,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _success(
            request,
            _row("20260805"),
            _row("20260805", close_price="111"),
        )

    with pytest.raises(KisMarketDataProtocolError, match="conflicting bars"):
        KisDailyPriceClient(
            _credentials(),
            StubTokenManager(),
            client=client_factory(handler),
        ).fetch_daily_bars("005930", START, END)


@pytest.mark.parametrize(
    "stock_code",
    ("5930", " 005930", "005930 ", "\uff10\uff10\uff15\uff19\uff13\uff10"),
)
def test_client_rejects_invalid_code_before_http(
    client_factory: ClientFactory,
    stock_code: str,
) -> None:
    def unexpected(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected request: {request.method}")

    with pytest.raises(InvalidMarketDataStockCodeError):
        KisDailyPriceClient(
            _credentials(),
            StubTokenManager(),
            client=client_factory(unexpected),
        ).fetch_daily_bars(stock_code, START, END)


def test_client_rejects_reversed_range_before_http(client_factory: ClientFactory) -> None:
    def unexpected(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected request: {request.method}")

    with pytest.raises(InvalidMarketDataRangeError):
        KisDailyPriceClient(
            _credentials(),
            StubTokenManager(),
            client=client_factory(unexpected),
        ).fetch_daily_bars("005930", END, START)


@pytest.mark.parametrize("status_code", (400, 403, 429, 500))
def test_client_converts_http_errors_without_leaking_response_body(
    client_factory: ClientFactory,
    status_code: int,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            content=f"echo {APP_SECRET} {ACCOUNT_NUMBER}".encode(),
            request=request,
        )

    with pytest.raises(KisMarketDataHttpError) as captured:
        KisDailyPriceClient(
            _credentials(),
            StubTokenManager(),
            client=client_factory(handler),
        ).fetch_daily_bars("005930", START, END)

    assert APP_SECRET not in str(captured.value)
    assert ACCOUNT_NUMBER not in str(captured.value)


def test_client_retries_rate_limit_without_callback_and_preserves_existing_behavior(
    client_factory: ClientFactory,
) -> None:
    requests: list[httpx.Request] = []
    clock = FakeClock()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return _api_error(
                request,
                msg_cd="EGW00201",
                msg1="synthetic rate limit",
            )
        return _success(request, _row("20260805"))

    bars = KisDailyPriceClient(
        _credentials(),
        StubTokenManager(),
        client=client_factory(handler),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        rate_limit_wait_seconds=7.5,
    ).fetch_daily_bars("005930", START, END)

    assert len(bars) == 1
    assert len(requests) == 2
    assert clock.sleeps == [7.5]


def test_client_calls_rate_limit_callback_immediately_before_sleep(
    client_factory: ClientFactory,
) -> None:
    requests: list[httpx.Request] = []
    notifications: list[KisRateLimitNotification] = []
    events: list[str] = []
    request_times: list[float] = []
    clock = FakeClock()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        request_times.append(clock.monotonic())
        if len(requests) <= 2:
            return _api_error(
                request,
                msg_cd="EGW00201",
                msg1=f"rate limited {APP_SECRET} {FIRST_TOKEN}",
            )
        return _success(request, _row("20260805"))

    def notify(notification: KisRateLimitNotification) -> None:
        events.append("callback")
        notifications.append(notification)

    def record_sleep(seconds: float) -> None:
        events.append(f"sleep:{seconds:g}")
        clock.sleep(seconds)

    bars = KisDailyPriceClient(
        _credentials(),
        StubTokenManager(),
        client=client_factory(handler),
        sleep=record_sleep,
        monotonic=clock.monotonic,
        rate_limit_callback=notify,
    ).fetch_daily_bars("000660", START, END)

    assert len(bars) == 1
    assert events == ["callback", "sleep:61", "callback", "sleep:61"]
    assert notifications == [
        KisRateLimitNotification(
            stock_code="000660",
            attempt_number=1,
            max_attempts=3,
            wait_seconds=61.0,
        ),
        KisRateLimitNotification(
            stock_code="000660",
            attempt_number=2,
            max_attempts=3,
            wait_seconds=61.0,
        ),
    ]
    assert request_times == [0.0, 61.0, 122.0]
    assert len(notifications) == 2
    notification_text = repr(notifications[0])
    assert APP_SECRET not in notification_text
    assert FIRST_TOKEN not in notification_text
    assert ACCOUNT_NUMBER not in notification_text


def test_client_raises_dedicated_error_after_rate_limit_attempts_are_exhausted(
    client_factory: ClientFactory,
) -> None:
    requests: list[httpx.Request] = []
    clock = FakeClock()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _api_error(
            request,
            msg_cd="EGW00201",
            msg1="synthetic rate limit",
        )

    with pytest.raises(KisMarketDataRateLimitError) as captured:
        KisDailyPriceClient(
            _credentials(),
            StubTokenManager(),
            client=client_factory(handler),
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        ).fetch_daily_bars("005930", START, END)

    assert len(requests) == 3
    assert clock.sleeps == [61.0, 61.0]
    message = str(captured.value)
    assert "HTTP 500" in message
    assert "msg_cd=EGW00201" in message
    assert "msg1=synthetic rate limit" in message


def test_client_honors_injected_rate_limit_attempt_bound(
    client_factory: ClientFactory,
) -> None:
    requests: list[httpx.Request] = []
    clock = FakeClock()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _api_error(
            request,
            msg_cd="EGW00201",
            msg1="synthetic rate limit",
        )

    with pytest.raises(KisMarketDataRateLimitError):
        KisDailyPriceClient(
            _credentials(),
            StubTokenManager(),
            client=client_factory(handler),
            sleep=clock.sleep,
            monotonic=clock.monotonic,
            rate_limit_max_retries=1,
        ).fetch_daily_bars("005930", START, END)

    assert len(requests) == 1
    assert clock.sleeps == []


def test_client_does_not_retry_a_different_json_http_500_error(
    client_factory: ClientFactory,
) -> None:
    requests: list[httpx.Request] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _api_error(
            request,
            msg_cd="SYNTHETIC_OTHER_ERROR",
            msg1="synthetic ordinary failure",
        )

    with pytest.raises(KisMarketDataHttpError) as captured:
        KisDailyPriceClient(
            _credentials(),
            StubTokenManager(),
            client=client_factory(handler),
            sleep=sleeps.append,
        ).fetch_daily_bars("005930", START, END)

    assert len(requests) == 1
    assert sleeps == []
    message = str(captured.value)
    assert "HTTP 500" in message
    assert "msg_cd=SYNTHETIC_OTHER_ERROR" in message
    assert "msg1=synthetic ordinary failure" in message


def test_client_keeps_non_json_http_500_error_generic(
    client_factory: ClientFactory,
) -> None:
    requests: list[httpx.Request] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500, content=b"synthetic non-json failure", request=request)

    with pytest.raises(KisMarketDataHttpError) as captured:
        KisDailyPriceClient(
            _credentials(),
            StubTokenManager(),
            client=client_factory(handler),
            sleep=sleeps.append,
        ).fetch_daily_bars("005930", START, END)

    assert len(requests) == 1
    assert sleeps == []
    assert str(captured.value) == "The KIS daily-price request failed (HTTP 500)."
    assert "synthetic non-json failure" not in str(captured.value)


def test_client_masks_every_secret_in_json_http_error_metadata(
    client_factory: ClientFactory,
) -> None:
    cano = ACCOUNT_NUMBER.split("-", maxsplit=1)[0]

    def handler(request: httpx.Request) -> httpx.Response:
        return _api_error(
            request,
            rt_cd=APP_SECRET,
            msg_cd=f"SYNTHETIC-{APP_KEY}",
            msg1=f"{APP_SECRET} {FIRST_TOKEN} {ACCOUNT_NUMBER} {cano}",
        )

    with pytest.raises(KisMarketDataHttpError) as captured:
        KisDailyPriceClient(
            _credentials(),
            StubTokenManager(),
            client=client_factory(handler),
        ).fetch_daily_bars("005930", START, END)

    message = str(captured.value)
    assert "HTTP 500" in message
    assert "[REDACTED]" in message
    assert "rt_cd" not in message
    for secret in (APP_KEY, APP_SECRET, FIRST_TOKEN, ACCOUNT_NUMBER, cano):
        assert secret not in message


def test_client_converts_timeout_without_leaking_request_details(
    client_factory: ClientFactory,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(
            f"timeout for {request.url} with {FIRST_TOKEN}",
            request=request,
        )

    with pytest.raises(KisMarketDataTimeoutError) as captured:
        KisDailyPriceClient(
            _credentials(),
            StubTokenManager(),
            client=client_factory(handler),
        ).fetch_daily_bars("005930", START, END)

    assert FIRST_TOKEN not in str(captured.value)
    assert KIS_DAILY_PRICE_URL not in str(captured.value)


def test_client_reauthenticates_once_after_401(client_factory: ClientFactory) -> None:
    requests: list[httpx.Request] = []
    clock = FakeClock()
    token_manager = StubTokenManager((_access_token(FIRST_TOKEN), _access_token(SECOND_TOKEN)))

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(401, request=request)
        return _success(request, _row("20260805"))

    bars = KisDailyPriceClient(
        _credentials(),
        token_manager,
        client=client_factory(handler),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    ).fetch_daily_bars("005930", START, END)

    assert len(bars) == 1
    assert [request.headers["authorization"] for request in requests] == [
        f"Bearer {FIRST_TOKEN}",
        f"Bearer {SECOND_TOKEN}",
    ]
    assert len(token_manager.invalidated) == 1


def test_client_fails_after_one_unauthorized_retry(client_factory: ClientFactory) -> None:
    clock = FakeClock()
    token_manager = StubTokenManager((_access_token(FIRST_TOKEN), _access_token(SECOND_TOKEN)))

    with pytest.raises(KisMarketDataAuthenticationError):
        KisDailyPriceClient(
            _credentials(),
            token_manager,
            client=client_factory(lambda request: httpx.Response(401, request=request)),
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        ).fetch_daily_bars("005930", START, END)

    assert token_manager.get_calls == 2


@pytest.mark.parametrize("first_status", [200, 401, 500])
@pytest.mark.parametrize("second_status", [200, 401, 500])
def test_client_shares_one_reauthentication_between_401_and_expiry_codes(
    client_factory: ClientFactory, first_status: int, second_status: int
) -> None:
    tokens = StubTokenManager((_access_token(FIRST_TOKEN), _access_token(SECOND_TOKEN)))
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert len(requests) <= 2, "reauthentication must be bounded across response types"
        status = (first_status, second_status)[len(requests) - 1]
        if status == 401:
            return httpx.Response(status, request=request)
        return _api_error(request, msg_cd="EGW00123", msg1="expired", status_code=status)

    with pytest.raises(KisMarketDataAuthenticationError):
        KisDailyPriceClient(
            _credentials(), tokens, client=client_factory(handler), request_interval_seconds=0
        ).fetch_daily_bars("005930", START, END)
    assert tokens.get_calls == 2
    assert tokens.invalidated == [tokens.tokens[0]]
    assert [r.headers["authorization"] for r in requests] == [
        f"Bearer {FIRST_TOKEN}",
        f"Bearer {SECOND_TOKEN}",
    ]


@pytest.mark.parametrize("expiry_status", [200, 500])
def test_client_token_refresh_does_not_reset_rate_limit_attempts(
    client_factory: ClientFactory, expiry_status: int
) -> None:
    tokens = StubTokenManager((_access_token(FIRST_TOKEN), _access_token(SECOND_TOKEN)))
    clock = FakeClock()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert len(requests) <= 3
        if len(requests) == 2:
            return _api_error(request, msg_cd="EGW00123", msg1="expired", status_code=expiry_status)
        return _api_error(request, msg_cd="EGW00201", msg1="rate limit")

    with pytest.raises(KisMarketDataRateLimitError):
        KisDailyPriceClient(
            _credentials(),
            tokens,
            client=client_factory(handler),
            request_interval_seconds=0,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
            rate_limit_max_retries=2,
        ).fetch_daily_bars("005930", START, END)
    assert len(requests) == 3
    assert tokens.invalidated == [tokens.tokens[0]]
    assert clock.sleeps == [61.0]


def test_client_rejects_invalid_json(client_factory: ClientFactory) -> None:
    with pytest.raises(KisMarketDataProtocolError, match="not valid JSON"):
        KisDailyPriceClient(
            _credentials(),
            StubTokenManager(),
            client=client_factory(
                lambda request: httpx.Response(200, content=b"not-json", request=request)
            ),
        ).fetch_daily_bars("005930", START, END)


def test_client_propagates_sanitized_kis_error_response(
    client_factory: ClientFactory,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "rt_cd": "1",
                "msg_cd": "SYNTHETIC_REJECTED",
                "msg1": f"rejected {APP_SECRET}",
                "output2": [],
            },
            request=request,
        )

    with pytest.raises(KisMarketDataApiError) as captured:
        KisDailyPriceClient(
            _credentials(),
            StubTokenManager(),
            client=client_factory(handler),
        ).fetch_daily_bars("005930", START, END)

    assert APP_SECRET not in str(captured.value)


def test_injected_http_client_remains_caller_owned(client_factory: ClientFactory) -> None:
    http_client = client_factory(lambda request: _success(request, _row("20260805")))

    KisDailyPriceClient(
        _credentials(),
        StubTokenManager(),
        client=http_client,
    ).fetch_daily_bars("005930", START, END)

    assert not http_client.is_closed


@pytest.mark.parametrize("max_pages", (0, -1, True, 1.5))
def test_client_rejects_invalid_max_page_limit(max_pages: object) -> None:
    with pytest.raises(ValueError, match="max_pages"):
        KisDailyPriceClient(
            _credentials(),
            StubTokenManager(),
            max_pages=max_pages,  # type: ignore[arg-type]
        )
