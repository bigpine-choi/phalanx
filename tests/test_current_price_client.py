from __future__ import annotations

import traceback
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from pydantic import SecretStr

from phalanx.config import KisCredentials
from phalanx.domain import CurrentPriceMarket
from phalanx.kis.auth import AccessToken
from phalanx.kis.errors import (
    InvalidMarketDataNumericFieldError,
    InvalidMarketDataResponseStructure,
    KisAuthError,
    KisMarketDataApiError,
    KisMarketDataAuthenticationError,
    KisMarketDataHttpError,
    KisMarketDataProtocolError,
    KisMarketDataRateLimitError,
    KisMarketDataTimeoutError,
    MarketDataDomainInvariantError,
)
from phalanx.kis.market_data_client import (
    KIS_CURRENT_PRICE_PATH,
    KIS_CURRENT_PRICE_TR_ID,
    KIS_CURRENT_PRICE_URL,
    KisCurrentPriceClient,
    KisRateLimitNotification,
)
from phalanx.market_data.errors import (
    InvalidMarketDataStockCodeError,
    InvalidValuationPriceRequestError,
    UnsupportedCurrentPriceMarketError,
)

APP_KEY = "synthetic-current-price-app-key"
APP_SECRET = "synthetic-current-price-app-secret"
ACCOUNT_NUMBER = "87654321-01"
FIRST_TOKEN = "synthetic-current-price-token-one"
SECOND_TOKEN = "synthetic-current-price-token-two"
STARTED_AT = datetime(2026, 9, 3, 9, 0, 0, tzinfo=UTC)
RECEIVED_AT = STARTED_AT + timedelta(seconds=2)

Handler = Callable[[httpx.Request], httpx.Response]
ClientFactory = Callable[[Handler], httpx.Client]


class StubTokenManager:
    def __init__(
        self,
        tokens: tuple[AccessToken, ...] | None = None,
        *,
        events: list[str] | None = None,
    ) -> None:
        self.tokens = tokens or (_access_token(FIRST_TOKEN),)
        self.current_index = 0
        self.get_calls = 0
        self.invalidated: list[AccessToken] = []
        self.events = events

    def get_access_token(self) -> AccessToken:
        self.get_calls += 1
        if self.events is not None:
            self.events.append("token")
        return self.tokens[self.current_index]

    def invalidate_if_current(self, token: AccessToken) -> bool:
        self.invalidated.append(token)
        current = self.tokens[self.current_index]
        if token.access_token.get_secret_value() != current.access_token.get_secret_value():
            return False
        if self.current_index + 1 < len(self.tokens):
            self.current_index += 1
        return True


class FailingTokenManager(StubTokenManager):
    def get_access_token(self) -> AccessToken:
        self.get_calls += 1
        raise KisAuthError(f"secret token failure {APP_SECRET}")


class SequenceClock:
    def __init__(self, *values: object, events: list[str] | None = None) -> None:
        self.values = list(values)
        self.calls = 0
        self.events = events

    def __call__(self) -> Any:
        if self.events is not None:
            self.events.append("clock")
        value = self.values[self.calls]
        self.calls += 1
        return value


class RecordingPacer:
    def __init__(self, events: list[str] | None = None) -> None:
        self.calls = 0
        self.events = events

    def wait_before_request(self) -> None:
        self.calls += 1
        if self.events is not None:
            self.events.append("pacer")


@pytest.fixture
def client_factory() -> Iterator[ClientFactory]:
    clients: list[httpx.Client] = []

    def create(handler: Handler) -> httpx.Client:
        client = httpx.Client(transport=httpx.MockTransport(handler))
        clients.append(client)
        return client

    yield create

    for client in clients:
        if not client.is_closed:
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


def _payload(
    *,
    stock_code: object = "005930",
    current_price: object = "70000.10",
    rt_cd: object = "0",
    msg_cd: object = "SYNTHETIC_SUCCESS",
    msg1: object = "synthetic success",
) -> dict[str, object]:
    return {
        "rt_cd": rt_cd,
        "msg_cd": msg_cd,
        "msg1": msg1,
        "output": {
            "stck_shrn_iscd": stock_code,
            "stck_prpr": current_price,
        },
    }


def _response(
    request: httpx.Request,
    *,
    status_code: int = 200,
    payload: object | None = None,
) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=_payload() if payload is None else payload,
        request=request,
    )


def _client(
    http_client: httpx.Client,
    token_manager: StubTokenManager | None = None,
    **kwargs: object,
) -> KisCurrentPriceClient:
    return KisCurrentPriceClient(
        _credentials(),
        token_manager or StubTokenManager(),
        client=http_client,
        clock=kwargs.pop(
            "clock",
            SequenceClock(STARTED_AT, RECEIVED_AT, RECEIVED_AT, RECEIVED_AT),
        ),
        request_pacer=kwargs.pop("request_pacer", RecordingPacer()),
        **kwargs,
    )


def _exception_surfaces(error: BaseException) -> str:
    pending = [error]
    seen: set[int] = set()
    surfaces: list[str] = []
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        surfaces.extend((str(current), repr(current), repr(current.args)))
        surfaces.extend(getattr(current, "__notes__", ()))
        surfaces.extend(traceback.format_exception(current))
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
    return "\n".join(surfaces)


def test_client_uses_exact_fixed_read_only_krx_contract(
    client_factory: ClientFactory,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response(request)

    token_manager = StubTokenManager()
    observation = _client(
        client_factory(handler),
        token_manager,
    ).fetch_current_price("005930", CurrentPriceMarket.KRX)

    assert observation.stock_code == "005930"
    assert observation.current_price == Decimal("70000.10")
    assert observation.market is CurrentPriceMarket.KRX
    assert observation.request_started_at == STARTED_AT
    assert observation.received_at == RECEIVED_AT
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert str(request.url).split("?", maxsplit=1)[0] == KIS_CURRENT_PRICE_URL
    assert request.url.scheme == "https"
    assert request.url.host == "openapi.koreainvestment.com"
    assert request.url.port == 9443
    assert request.url.path == KIS_CURRENT_PRICE_PATH
    assert request.content == b""
    assert request.headers["authorization"] == f"Bearer {FIRST_TOKEN}"
    assert request.headers["appkey"] == APP_KEY
    assert request.headers["appsecret"] == APP_SECRET
    assert request.headers["tr_id"] == KIS_CURRENT_PRICE_TR_ID == "FHKST01010100"
    assert request.headers["custtype"] == "P"
    assert dict(request.url.params) == {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": "005930",
    }
    assert token_manager.get_calls == 1


@pytest.mark.parametrize(
    "default_params",
    (
        {"caller_default": "synthetic-query-secret"},
        {"FID_COND_MRKT_DIV_CODE": "NX"},
    ),
)
def test_injected_client_query_defaults_fail_before_runtime_side_effects(
    default_params: dict[str, str],
) -> None:
    token_manager = StubTokenManager()
    clock = SequenceClock(AssertionError("clock must not run"))
    pacer = RecordingPacer()
    requests: list[httpx.Request] = []

    def unexpected(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise AssertionError("transport must not run")

    with httpx.Client(
        transport=httpx.MockTransport(unexpected),
        params=default_params,
    ) as http_client, pytest.raises(KisMarketDataProtocolError) as captured:
        _client(
            http_client,
            token_manager,
            clock=clock,
            request_pacer=pacer,
        ).fetch_current_price("005930", CurrentPriceMarket.KRX)

    assert token_manager.get_calls == 0
    assert clock.calls == 0
    assert pacer.calls == 0
    assert requests == []
    surfaces = _exception_surfaces(captured.value)
    for raw_name, raw_value in default_params.items():
        assert raw_name not in surfaces
        assert raw_value not in surfaces


def test_query_defaults_mutated_after_construction_are_checked_on_every_fetch() -> None:
    requests: list[httpx.Request] = []
    token_manager = StubTokenManager()
    clock = SequenceClock(STARTED_AT, RECEIVED_AT, AssertionError("clock must not run"))
    pacer = RecordingPacer()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response(request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        current_price_client = _client(
            http_client,
            token_manager,
            clock=clock,
            request_pacer=pacer,
        )
        current_price_client.fetch_current_price("005930", CurrentPriceMarket.KRX)
        http_client.params = {"late_default": "synthetic-late-query-secret"}

        with pytest.raises(KisMarketDataProtocolError) as captured:
            current_price_client.fetch_current_price("005930", CurrentPriceMarket.KRX)

    assert len(requests) == 1
    assert token_manager.get_calls == 1
    assert clock.calls == 2
    assert pacer.calls == 1
    surfaces = _exception_surfaces(captured.value)
    assert "late_default" not in surfaces
    assert "synthetic-late-query-secret" not in surfaces


def test_redirect_is_not_followed_when_injected_client_enables_redirects() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                302,
                headers={"location": "https://redirect.invalid/should-not-be-called"},
                request=request,
            )
        return _response(request)

    with (
        httpx.Client(
            transport=httpx.MockTransport(handler),
            follow_redirects=True,
        ) as http_client,
        pytest.raises(KisMarketDataHttpError),
    ):
        _client(http_client).fetch_current_price("005930", CurrentPriceMarket.KRX)

    assert len(requests) == 1
    assert str(requests[0].url).split("?", maxsplit=1)[0] == KIS_CURRENT_PRICE_URL


@pytest.mark.parametrize(
    ("include_msg1", "msg1"),
    (
        pytest.param(False, None, id="absent"),
        pytest.param(True, 7, id="non-string"),
        pytest.param(True, f"provider echoed {APP_SECRET}", id="secret-bearing"),
    ),
)
def test_success_ignores_untrusted_msg1(
    include_msg1: bool,
    msg1: object,
    client_factory: ClientFactory,
) -> None:
    payload = _payload(msg1=msg1)
    if not include_msg1:
        del payload["msg1"]

    observation = _client(
        client_factory(lambda request: _response(request, payload=payload))
    ).fetch_current_price("005930", CurrentPriceMarket.KRX)

    assert observation.current_price == Decimal("70000.10")
    surfaces = observation.model_dump_json() + repr(observation)
    assert APP_SECRET not in surfaces


def test_timing_wraps_token_pacing_and_complete_http_acquisition(
    client_factory: ClientFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    clock = SequenceClock(STARTED_AT, RECEIVED_AT, events=events)
    pacer = RecordingPacer(events)
    token_manager = StubTokenManager(events=events)
    decode_json = KisCurrentPriceClient._decode_json
    parse_envelope = KisCurrentPriceClient._parse_envelope

    def recording_decode_json(response_body: bytes) -> object:
        events.append("json")
        return decode_json(response_body)

    def recording_parse_envelope(payload: object | None, *, required: bool) -> Any:
        events.append("envelope")
        return parse_envelope(payload, required=required)

    monkeypatch.setattr(
        KisCurrentPriceClient,
        "_decode_json",
        staticmethod(recording_decode_json),
    )
    monkeypatch.setattr(
        KisCurrentPriceClient,
        "_parse_envelope",
        staticmethod(recording_parse_envelope),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        events.append("http")
        return _response(request)

    observation = _client(
        client_factory(handler),
        token_manager,
        clock=clock,
        request_pacer=pacer,
    ).fetch_current_price("005930", CurrentPriceMarket.KRX)

    assert events == ["clock", "token", "pacer", "http", "clock", "json", "envelope"]
    assert observation.request_started_at == STARTED_AT
    assert observation.received_at == RECEIVED_AT


@pytest.mark.parametrize("market", (CurrentPriceMarket.NXT, CurrentPriceMarket.INTEGRATED))
def test_non_krx_market_is_rejected_before_all_runtime_side_effects(
    market: CurrentPriceMarket,
    client_factory: ClientFactory,
) -> None:
    token_manager = StubTokenManager()
    clock = SequenceClock(AssertionError("clock must not run"))
    pacer = RecordingPacer()
    http_calls = 0

    def unexpected(request: httpx.Request) -> httpx.Response:
        nonlocal http_calls
        http_calls += 1
        raise AssertionError(f"unexpected request: {request.method}")

    with pytest.raises(UnsupportedCurrentPriceMarketError) as captured:
        _client(
            client_factory(unexpected),
            token_manager,
            clock=clock,
            request_pacer=pacer,
        ).fetch_current_price("005930", market)

    assert captured.value.market is market
    assert token_manager.get_calls == 0
    assert clock.calls == 0
    assert pacer.calls == 0
    assert http_calls == 0


def test_invalid_market_type_is_typed_and_side_effect_free(
    client_factory: ClientFactory,
) -> None:
    token_manager = StubTokenManager()
    clock = SequenceClock(AssertionError("clock must not run"))
    pacer = RecordingPacer()

    with pytest.raises(InvalidValuationPriceRequestError, match="CurrentPriceMarket"):
        _client(
            client_factory(lambda request: _response(request)),
            token_manager,
            clock=clock,
            request_pacer=pacer,
        ).fetch_current_price("005930", "KRX")  # type: ignore[arg-type]

    assert token_manager.get_calls == 0
    assert clock.calls == 0
    assert pacer.calls == 0


def test_invalid_stock_code_is_rejected_before_market_and_all_side_effects(
    client_factory: ClientFactory,
) -> None:
    token_manager = StubTokenManager()
    clock = SequenceClock(AssertionError("clock must not run"))
    pacer = RecordingPacer()

    with pytest.raises(InvalidMarketDataStockCodeError):
        _client(
            client_factory(lambda request: _response(request)),
            token_manager,
            clock=clock,
            request_pacer=pacer,
        ).fetch_current_price("5930", CurrentPriceMarket.NXT)

    assert token_manager.get_calls == 0
    assert clock.calls == 0
    assert pacer.calls == 0


def test_stock_code_str_subclass_is_rejected_before_all_runtime_side_effects(
    client_factory: ClientFactory,
) -> None:
    class StockCode(str):
        pass

    token_manager = StubTokenManager()
    clock = SequenceClock(AssertionError("clock must not run"))
    pacer = RecordingPacer()
    http_calls = 0

    def unexpected(request: httpx.Request) -> httpx.Response:
        nonlocal http_calls
        http_calls += 1
        raise AssertionError(f"unexpected request: {request.method}")

    with pytest.raises(InvalidMarketDataStockCodeError):
        _client(
            client_factory(unexpected),
            token_manager,
            clock=clock,
            request_pacer=pacer,
        ).fetch_current_price(StockCode("005930"), CurrentPriceMarket.KRX)

    assert token_manager.get_calls == 0
    assert clock.calls == 0
    assert pacer.calls == 0
    assert http_calls == 0


@pytest.mark.parametrize(
    "clock",
    (
        SequenceClock(STARTED_AT.replace(tzinfo=None)),
        SequenceClock(STARTED_AT, RECEIVED_AT.replace(tzinfo=None)),
        SequenceClock(RECEIVED_AT, STARTED_AT),
        SequenceClock("not-a-datetime"),
    ),
)
def test_invalid_clock_values_fail_with_protocol_error(
    clock: SequenceClock,
    client_factory: ClientFactory,
) -> None:
    with pytest.raises(KisMarketDataProtocolError, match=r"clock|preceded"):
        _client(
            client_factory(lambda request: _response(request)),
            clock=clock,
        ).fetch_current_price("005930", CurrentPriceMarket.KRX)


def test_backward_clock_across_dst_fold_is_rejected_by_instant(
    client_factory: ClientFactory,
) -> None:
    new_york = ZoneInfo("America/New_York")
    request_started_at = datetime(2026, 11, 1, 1, 15, tzinfo=new_york, fold=1)
    received_at = datetime(2026, 11, 1, 1, 45, tzinfo=new_york, fold=0)
    assert received_at.astimezone(UTC) < request_started_at.astimezone(UTC)

    with pytest.raises(KisMarketDataProtocolError, match="preceded"):
        _client(
            client_factory(lambda request: _response(request)),
            clock=SequenceClock(request_started_at, received_at),
        ).fetch_current_price("005930", CurrentPriceMarket.KRX)


def test_rate_limit_twice_then_success_uses_one_receipt_clock_per_get(
    client_factory: ClientFactory,
) -> None:
    requests: list[httpx.Request] = []
    sleeps: list[float] = []
    notifications: list[KisRateLimitNotification] = []
    clock = SequenceClock(
        STARTED_AT,
        STARTED_AT + timedelta(milliseconds=500),
        STARTED_AT + timedelta(seconds=1),
        RECEIVED_AT,
    )
    pacer = RecordingPacer()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) <= 2:
            return _response(
                request,
                status_code=429,
                payload=_payload(
                    rt_cd="1",
                    msg_cd="EGW00201",
                    msg1=f"never retain {APP_SECRET}",
                ),
            )
        return _response(request)

    observation = _client(
        client_factory(handler),
        clock=clock,
        request_pacer=pacer,
        sleep=sleeps.append,
        rate_limit_wait_seconds=7.5,
        rate_limit_callback=notifications.append,
    ).fetch_current_price("005930", CurrentPriceMarket.KRX)

    assert observation.current_price == Decimal("70000.10")
    assert observation.request_started_at == STARTED_AT
    assert observation.received_at == RECEIVED_AT
    assert observation.received_at - observation.request_started_at == timedelta(seconds=2)
    assert len(requests) == 3
    assert pacer.calls == 3
    assert sleeps == [7.5, 7.5]
    assert notifications == [
        KisRateLimitNotification("005930", 1, 3, 7.5),
        KisRateLimitNotification("005930", 2, 3, 7.5),
    ]


def test_rate_limit_exhaustion_is_three_gets_two_waits_and_never_exposes_msg1(
    client_factory: ClientFactory,
) -> None:
    requests: list[httpx.Request] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response(
            request,
            status_code=429,
            payload=_payload(
                rt_cd="1",
                msg_cd="EGW00201",
                msg1=f"secret {APP_SECRET} {FIRST_TOKEN}",
            ),
        )

    with pytest.raises(KisMarketDataRateLimitError) as captured:
        _client(
            client_factory(handler),
            sleep=sleeps.append,
            rate_limit_wait_seconds=4,
        ).fetch_current_price("005930", CurrentPriceMarket.KRX)

    assert len(requests) == 3
    assert sleeps == [4.0, 4.0]
    message = str(captured.value)
    assert "msg_cd=EGW00201" in message
    assert "msg1" not in message
    assert APP_SECRET not in message
    assert FIRST_TOKEN not in message


def test_http_500_exact_rate_limit_code_retries_within_shared_budget(
    client_factory: ClientFactory,
) -> None:
    requests: list[httpx.Request] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return _response(
                request,
                status_code=500,
                payload=_payload(rt_cd="1", msg_cd="EGW00201"),
            )
        return _response(request)

    observation = _client(
        client_factory(handler),
        sleep=sleeps.append,
        rate_limit_wait_seconds=3,
    ).fetch_current_price("005930", CurrentPriceMarket.KRX)

    assert observation.current_price == Decimal("70000.10")
    assert len(requests) == 2
    assert sleeps == [3.0]


def test_http_500_exact_expired_code_renews_authentication_at_most_once(
    client_factory: ClientFactory,
) -> None:
    token_manager = StubTokenManager((_access_token(FIRST_TOKEN), _access_token(SECOND_TOKEN)))
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response(
            request,
            status_code=500,
            payload=_payload(rt_cd="1", msg_cd="EGW00123"),
        )

    with pytest.raises(KisMarketDataAuthenticationError):
        _client(client_factory(handler), token_manager).fetch_current_price(
            "005930", CurrentPriceMarket.KRX
        )

    assert len(requests) == token_manager.get_calls == 2
    assert len(token_manager.invalidated) == 1


@pytest.mark.parametrize(
    "payload",
    (
        _payload(
            rt_cd="1",
            msg_cd="SYNTHETIC_UNKNOWN",
            msg1="EGW00123 EGW00201 retry token rate limit",
        ),
        {"rt_cd": "1", "msg1": "EGW00123 EGW00201"},
    ),
    ids=("unknown-code-with-retry-looking-msg1", "missing-code"),
)
def test_http_500_unknown_or_missing_code_is_terminal(
    payload: object,
    client_factory: ClientFactory,
) -> None:
    token_manager = StubTokenManager((_access_token(FIRST_TOKEN), _access_token(SECOND_TOKEN)))
    requests: list[httpx.Request] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response(request, status_code=500, payload=payload)

    with pytest.raises(KisMarketDataHttpError) as captured:
        _client(
            client_factory(handler),
            token_manager,
            sleep=sleeps.append,
        ).fetch_current_price("005930", CurrentPriceMarket.KRX)

    assert type(captured.value) is KisMarketDataHttpError
    assert len(requests) == 1
    assert token_manager.invalidated == []
    assert sleeps == []


def test_http_500_malformed_json_is_terminal(client_factory: ClientFactory) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500, content=b"not-json", request=request)

    with pytest.raises(KisMarketDataHttpError):
        _client(client_factory(handler)).fetch_current_price(
            "005930", CurrentPriceMarket.KRX
        )

    assert len(requests) == 1


def test_combined_auth_and_rate_limit_retries_share_one_three_get_budget(
    client_factory: ClientFactory,
) -> None:
    token_manager = StubTokenManager((_access_token(FIRST_TOKEN), _access_token(SECOND_TOKEN)))
    requests: list[httpx.Request] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(401, request=request)
        if len(requests) == 2:
            return _response(
                request,
                payload=_payload(rt_cd="1", msg_cd="EGW00201"),
            )
        return _response(request)

    observation = _client(
        client_factory(handler),
        token_manager,
        sleep=sleeps.append,
        rate_limit_wait_seconds=3,
    ).fetch_current_price("005930", CurrentPriceMarket.KRX)

    assert observation.current_price == Decimal("70000.10")
    assert len(requests) == 3
    assert [request.headers["authorization"] for request in requests] == [
        f"Bearer {FIRST_TOKEN}",
        f"Bearer {SECOND_TOKEN}",
        f"Bearer {SECOND_TOKEN}",
    ]
    assert len(token_manager.invalidated) == 1
    assert sleeps == [3.0]


@pytest.mark.parametrize(
    ("sequence", "expected_error", "expected_invalidations", "expected_sleeps"),
    (
        pytest.param(
            ("auth", "rate", "rate"),
            KisMarketDataRateLimitError,
            1,
            [2.0],
            id="auth-rate-rate",
        ),
        pytest.param(
            ("rate", "rate", "auth"),
            KisMarketDataAuthenticationError,
            0,
            [2.0, 2.0],
            id="rate-rate-auth",
        ),
    ),
)
def test_terminal_mixed_retries_never_expand_the_shared_three_get_budget(
    sequence: tuple[str, str, str],
    expected_error: type[Exception],
    expected_invalidations: int,
    expected_sleeps: list[float],
    client_factory: ClientFactory,
) -> None:
    token_manager = StubTokenManager((_access_token(FIRST_TOKEN), _access_token(SECOND_TOKEN)))
    requests: list[httpx.Request] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        reason = sequence[len(requests)]
        requests.append(request)
        status_code = (500, 429, 500)[len(requests) - 1]
        msg_cd = "EGW00123" if reason == "auth" else "EGW00201"
        return _response(
            request,
            status_code=status_code,
            payload=_payload(rt_cd="1", msg_cd=msg_cd),
        )

    with pytest.raises(expected_error):
        _client(
            client_factory(handler),
            token_manager,
            sleep=sleeps.append,
            rate_limit_wait_seconds=2,
        ).fetch_current_price("005930", CurrentPriceMarket.KRX)

    assert len(requests) == token_manager.get_calls == 3
    assert len(token_manager.invalidated) == expected_invalidations <= 1
    assert sleeps == expected_sleeps
    assert len(sleeps) <= 2


def test_exact_expired_code_reauthenticates_once_and_msg1_words_never_do(
    client_factory: ClientFactory,
) -> None:
    token_manager = StubTokenManager((_access_token(FIRST_TOKEN), _access_token(SECOND_TOKEN)))
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return _response(
                request,
                payload=_payload(rt_cd="1", msg_cd="EGW00123", msg1="expired"),
            )
        return _response(request)

    _client(client_factory(handler), token_manager).fetch_current_price(
        "005930", CurrentPriceMarket.KRX
    )
    assert len(requests) == 2
    assert len(token_manager.invalidated) == 1

    guessed_token_manager = StubTokenManager(
        (_access_token(FIRST_TOKEN), _access_token(SECOND_TOKEN))
    )
    guessed_requests: list[httpx.Request] = []

    def guessed_handler(request: httpx.Request) -> httpx.Response:
        guessed_requests.append(request)
        return _response(
            request,
            payload=_payload(
                rt_cd="1",
                msg_cd="SYNTHETIC_NOT_AUTH",
                msg1="EGW00123 token expired unauthorized",
            ),
        )

    with pytest.raises(KisMarketDataApiError):
        _client(client_factory(guessed_handler), guessed_token_manager).fetch_current_price(
            "005930", CurrentPriceMarket.KRX
        )
    assert len(guessed_requests) == 1
    assert guessed_token_manager.invalidated == []


@pytest.mark.parametrize("kind", ("http-401", "expired-code"))
def test_authentication_is_retried_only_once(
    kind: str,
    client_factory: ClientFactory,
) -> None:
    token_manager = StubTokenManager((_access_token(FIRST_TOKEN), _access_token(SECOND_TOKEN)))
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if kind == "http-401":
            return httpx.Response(401, request=request)
        return _response(
            request,
            payload=_payload(rt_cd="1", msg_cd="EGW00123", msg1="ignored"),
        )

    with pytest.raises(KisMarketDataAuthenticationError):
        _client(client_factory(handler), token_manager).fetch_current_price(
            "005930", CurrentPriceMarket.KRX
        )

    assert len(requests) == 2
    assert token_manager.get_calls == 2
    assert len(token_manager.invalidated) == 1


def test_third_attempt_auth_failure_does_not_expand_combined_budget(
    client_factory: ClientFactory,
) -> None:
    token_manager = StubTokenManager((_access_token(FIRST_TOKEN), _access_token(SECOND_TOKEN)))
    requests: list[httpx.Request] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return _response(request, payload=_payload(rt_cd="1", msg_cd="EGW00201"))
        if len(requests) == 2:
            return httpx.Response(401, request=request)
        return _response(
            request,
            payload=_payload(rt_cd="1", msg_cd="EGW00123", msg1="ignored"),
        )

    with pytest.raises(KisMarketDataAuthenticationError):
        _client(
            client_factory(handler),
            token_manager,
            sleep=sleeps.append,
            rate_limit_wait_seconds=2,
        ).fetch_current_price("005930", CurrentPriceMarket.KRX)

    assert len(requests) == 3
    assert len(token_manager.invalidated) == 1
    assert sleeps == [2.0]


@pytest.mark.parametrize("status_code", (400, 403, 429, 500))
def test_non_allowlisted_http_error_is_not_retried_and_never_exposes_msg1(
    status_code: int,
    client_factory: ClientFactory,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response(
            request,
            status_code=status_code,
            payload=_payload(
                rt_cd="1",
                msg_cd=f"SYNTHETIC-{APP_KEY}",
                msg1=f"secret {APP_SECRET} {FIRST_TOKEN} {ACCOUNT_NUMBER}",
            ),
        )

    with pytest.raises(KisMarketDataHttpError) as captured:
        _client(client_factory(handler)).fetch_current_price("005930", CurrentPriceMarket.KRX)

    assert len(requests) == 1
    message = str(captured.value)
    assert "msg_cd=[OMITTED]" in message
    assert "msg1" not in message
    for secret in (APP_KEY, APP_SECRET, FIRST_TOKEN, ACCOUNT_NUMBER, "87654321"):
        assert secret not in message


def test_nonzero_api_envelope_is_not_retried_and_never_retains_provider_msg1(
    client_factory: ClientFactory,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response(
            request,
            payload=_payload(
                rt_cd="9",
                msg_cd=f"SYNTHETIC-{APP_KEY}",
                msg1=f"secret {APP_SECRET} {FIRST_TOKEN} {ACCOUNT_NUMBER}",
            ),
        )

    with pytest.raises(KisMarketDataApiError) as captured:
        _client(client_factory(handler)).fetch_current_price("005930", CurrentPriceMarket.KRX)

    assert len(requests) == 1
    assert captured.value.rt_cd == "non-success"
    assert captured.value.msg_cd == "[OMITTED]"
    assert captured.value.msg1 == "Provider message omitted."
    for secret in (APP_KEY, APP_SECRET, FIRST_TOKEN, ACCOUNT_NUMBER, "87654321"):
        assert secret not in str(captured.value)


@pytest.mark.parametrize("status_code", (200, 500))
def test_untrusted_response_metadata_is_omitted_from_every_exception_surface(
    status_code: int,
    client_factory: ClientFactory,
) -> None:
    raw_message_code = f"EGW00201\r\nauthorization: Bearer {FIRST_TOKEN}" + "X" * 600
    raw_provider_message = f"raw msg1 {APP_KEY} {APP_SECRET} {ACCOUNT_NUMBER}"
    payload = _payload(
        rt_cd="9",
        msg_cd=raw_message_code,
        msg1=raw_provider_message,
    )

    with pytest.raises((KisMarketDataApiError, KisMarketDataHttpError)) as captured:
        _client(
            client_factory(
                lambda request: _response(
                    request,
                    status_code=status_code,
                    payload=payload,
                )
            )
        ).fetch_current_price("005930", CurrentPriceMarket.KRX)

    surfaces = _exception_surfaces(captured.value)
    assert "[OMITTED]" in surfaces
    for forbidden in (
        raw_message_code,
        raw_provider_message,
        APP_KEY,
        APP_SECRET,
        ACCOUNT_NUMBER,
        FIRST_TOKEN,
        "authorization",
        "FID_INPUT_ISCD",
        KIS_CURRENT_PRICE_URL,
    ):
        assert forbidden not in surfaces


@pytest.mark.parametrize(
    "payload",
    (
        [],
        {"rt_cd": "0", "msg_cd": None, "output": {}},
        {"rt_cd": 0, "msg_cd": "OK", "output": {}},
        {"rt_cd": "", "msg_cd": "OK", "output": {}},
    ),
)
def test_success_http_response_requires_strict_envelope_once(
    payload: object,
    client_factory: ClientFactory,
) -> None:
    with pytest.raises(KisMarketDataProtocolError, match="envelope"):
        current_price_client = _client(
            client_factory(lambda request: _response(request, payload=payload))
        )
        current_price_client.fetch_current_price("005930", CurrentPriceMarket.KRX)


def test_invalid_json_is_protocol_failure_without_body_disclosure(
    client_factory: ClientFactory,
) -> None:
    secret_body = f"not json {APP_KEY} {APP_SECRET} {FIRST_TOKEN}".encode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=secret_body, request=request)

    with pytest.raises(KisMarketDataProtocolError) as captured:
        _client(client_factory(handler)).fetch_current_price("005930", CurrentPriceMarket.KRX)

    assert secret_body.decode() not in str(captured.value)
    assert APP_SECRET not in str(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_response_stock_code_mismatch_is_not_retried(client_factory: ClientFactory) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response(request, payload=_payload(stock_code="000660"))

    with pytest.raises(InvalidMarketDataResponseStructure):
        _client(client_factory(handler)).fetch_current_price("005930", CurrentPriceMarket.KRX)

    assert len(requests) == 1


@pytest.mark.parametrize(
    ("current_price", "expected_error"),
    (
        ("not-a-price", InvalidMarketDataNumericFieldError),
        ("0", MarketDataDomainInvariantError),
    ),
)
def test_invalid_current_price_value_is_never_retried(
    current_price: str,
    expected_error: type[Exception],
    client_factory: ClientFactory,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response(request, payload=_payload(current_price=current_price))

    with pytest.raises(expected_error):
        _client(client_factory(handler)).fetch_current_price("005930", CurrentPriceMarket.KRX)

    assert len(requests) == 1


@pytest.mark.parametrize("failure", ("timeout", "transport"))
def test_transport_failures_are_typed_secret_safe_and_not_retried(
    failure: str,
    client_factory: ClientFactory,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout(
                f"timeout {request.url} {FIRST_TOKEN}",
                request=request,
            )
        raise httpx.ConnectError(f"connect {request.url} {APP_SECRET}", request=request)

    expected = KisMarketDataTimeoutError if failure == "timeout" else KisMarketDataHttpError
    with pytest.raises(expected) as captured:
        _client(client_factory(handler)).fetch_current_price("005930", CurrentPriceMarket.KRX)

    assert len(requests) == 1
    for secret in (FIRST_TOKEN, APP_SECRET, KIS_CURRENT_PRICE_URL):
        assert secret not in str(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_token_failure_is_typed_safe_and_never_reaches_http(
    client_factory: ClientFactory,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response(request)

    token_manager = FailingTokenManager()
    with pytest.raises(KisMarketDataAuthenticationError) as captured:
        _client(client_factory(handler), token_manager).fetch_current_price(
            "005930", CurrentPriceMarket.KRX
        )

    assert requests == []
    assert APP_SECRET not in str(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_injected_client_remains_caller_owned(client_factory: ClientFactory) -> None:
    http_client = client_factory(lambda request: _response(request))

    _client(http_client).fetch_current_price("005930", CurrentPriceMarket.KRX)

    assert not http_client.is_closed


def test_internal_client_is_closed_after_complete_operation(
    client_factory: ClientFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owned_client = client_factory(lambda request: _response(request))
    monkeypatch.setattr("phalanx.kis.market_data_client.httpx.Client", lambda: owned_client)

    KisCurrentPriceClient(
        _credentials(),
        StubTokenManager(),
        clock=SequenceClock(STARTED_AT, RECEIVED_AT),
        request_pacer=RecordingPacer(),
    ).fetch_current_price("005930", CurrentPriceMarket.KRX)

    assert owned_client.is_closed


def test_internal_client_is_closed_after_failure(
    client_factory: ClientFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owned_client = client_factory(
        lambda request: _response(
            request,
            status_code=500,
            payload=_payload(rt_cd="1", msg_cd="SYNTHETIC_FAILURE"),
        )
    )
    monkeypatch.setattr("phalanx.kis.market_data_client.httpx.Client", lambda: owned_client)

    with pytest.raises(KisMarketDataHttpError):
        KisCurrentPriceClient(
            _credentials(),
            StubTokenManager(),
            clock=SequenceClock(STARTED_AT, RECEIVED_AT),
            request_pacer=RecordingPacer(),
        ).fetch_current_price("005930", CurrentPriceMarket.KRX)

    assert owned_client.is_closed
