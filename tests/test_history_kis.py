from __future__ import annotations

from contextlib import contextmanager, nullcontext
from pathlib import Path

import httpx
import pytest
from history_helpers import CODES, END, START, job
from test_market_data_application import (
    TrackingMockTransport,
    _token_response,
    _write_synthetic_credentials,
)
from test_market_data_client import (
    ACCOUNT_NUMBER,
    APP_KEY,
    APP_SECRET,
    FIRST_TOKEN,
    SECOND_TOKEN,
    FakeClock,
    StubTokenManager,
    _access_token,
    _api_error,
    _credentials,
    _full_page,
    _row,
    _success,
)

from phalanx.domain.market_data import DailyBar
from phalanx.kis.auth import KIS_TOKEN_URL
from phalanx.kis.market_data_client import (
    KisCurrentPriceClient,
    KisDailyPriceClient,
    KisRequestPacer,
)
from phalanx.market_data.errors import InvalidMarketDataStockCodeError
from phalanx.market_data.history.application import production_history_reader
from phalanx.market_data.history.provider import KisHistoryReader


def test_alphanumeric_end_to_end_reuses_client_oauth_pacing_and_pages(tmp_path: Path) -> None:
    service, view, _ = job(tmp_path)
    credentials = tmp_path / "config" / "credentials.env"
    _write_synthetic_credentials(credentials)
    clock = FakeClock()
    pacing = KisRequestPacer(monotonic=clock.monotonic, sleep=clock.sleep)
    requests: list[tuple[str, str, float]] = []
    token_calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls
        if str(request.url) == KIS_TOKEN_URL:
            token_calls += 1
            return _token_response(request)
        params = request.url.params
        code = params["FID_INPUT_ISCD"]
        requests.append((code, params["FID_INPUT_DATE_2"], clock.now))
        assert params["FID_COND_MRKT_DIV_CODE"] == "J"
        assert params["FID_PERIOD_DIV_CODE"] == "D"
        assert params["FID_ORG_ADJ_PRC"] == "0"
        assert params["FID_INPUT_DATE_1"] == "20260801"
        assert request.headers["tr_id"] == "FHKST03010100"
        if code == "005930" and params["FID_INPUT_DATE_2"] == "20260831":
            return _full_page(request, _row("20260820"))
        return _success(request, _row("20260805", close_price="110.0010"))

    transport = TrackingMockTransport(respond)

    def factory():
        return production_history_reader(
            credentials_path=credentials,
            token_cache_path=tmp_path / "tokens" / "token.json",
            transport=transport,
            request_pacer=pacing,
        )

    result = service.run(view.job.job_id, factory)
    assert result.complete
    assert requests == [
        ("005930", "20260831", 0),
        ("005930", "20260819", 1.1),
        ("0001A0", "20260831", 2.2),
    ]
    assert token_calls == 1
    assert clock.sleeps == [1.1, 1.1]
    assert transport.was_closed
    bars = service.repository.read_bars(view.job.job_id, "0001A0")
    assert bars[0].stock_code == "0001A0"
    assert DailyBar.model_validate_json(bars[0].model_dump_json()) == bars[0]
    assert result.symbols[0].result.row_count == 2


@pytest.mark.parametrize(
    "code",
    ["0001a0", "0001A", "00001A0", " 0001A0", "0001A0\n", "\uff10\uff10\uff10\uff11A0", 5930],
)
def test_bad_daily_identifiers_are_rejected_before_token_or_http(code: object) -> None:
    tokens = StubTokenManager()

    def forbidden(request: httpx.Request) -> httpx.Response:
        pytest.fail("invalid identifier reached network")

    with (
        httpx.Client(transport=httpx.MockTransport(forbidden)) as client,
        pytest.raises(InvalidMarketDataStockCodeError),
    ):
        KisDailyPriceClient(_credentials(), tokens, client=client).fetch_daily_bars(
            code, START, END
        )
    assert tokens.get_calls == 0


def test_current_price_contract_does_not_gain_alphanumeric_support() -> None:
    tokens = StubTokenManager()
    from phalanx.domain.market_data import CurrentPriceMarket

    with pytest.raises(InvalidMarketDataStockCodeError):
        KisCurrentPriceClient(_credentials(), tokens).fetch_current_price(
            "0001A0", CurrentPriceMarket.KRX
        )
    assert tokens.get_calls == 0


@pytest.mark.parametrize(
    ("failure", "attempt_count", "common", "expected_code"),
    [
        ("authentication", 2, True, "AUTHENTICATION_FAILED"),
        ("forbidden", 1, True, "AUTHENTICATION_FAILED"),
        ("rate_limit", 1, True, "RATE_LIMIT_EXHAUSTED"),
        ("http_500", 1, False, "KisMarketDataHttpError"),
        ("api", 1, False, "KIS_API_SYNTHETIC_UNSUPPORTED"),
        ("parsing", 1, False, "MissingMarketDataFieldError"),
        ("conflict", 1, False, "KisMarketDataProtocolError"),
    ],
)
def test_kis_failures_are_sanitized_and_common_errors_stop_remaining_calls(
    tmp_path: Path, failure: str, attempt_count: int, common: bool, expected_code: str
) -> None:
    service, view, _ = job(tmp_path)
    seen: list[str] = []
    secrets = (APP_KEY, APP_SECRET, ACCOUNT_NUMBER, FIRST_TOKEN)

    def respond(request: httpx.Request) -> httpx.Response:
        code = request.url.params["FID_INPUT_ISCD"]
        seen.append(code)
        if code == "0001A0":
            return _success(request, _row("20260805"))
        if failure == "authentication":
            return httpx.Response(401, request=request)
        if failure == "forbidden":
            return _api_error(request, msg_cd="FORBIDDEN", msg1=" ".join(secrets), status_code=403)
        if failure == "rate_limit":
            return _api_error(request, msg_cd="EGW00201", msg1=" ".join(secrets))
        if failure == "http_500":
            return _api_error(request, msg_cd="SYNTHETIC_FAILURE", msg1=" ".join(secrets))
        if failure == "api":
            return _api_error(
                request, msg_cd="SYNTHETIC_UNSUPPORTED", msg1=" ".join(secrets), status_code=200
            )
        if failure == "parsing":
            return _success(request, {"stck_bsop_date": "20260805"})
        return _success(request, _row("20260805"), _row("20260805", close_price="111"))

    @contextmanager
    def factory():
        with httpx.Client(transport=httpx.MockTransport(respond)) as http_client:
            yield KisHistoryReader(
                KisDailyPriceClient(
                    _credentials(),
                    StubTokenManager(),
                    client=http_client,
                    request_interval_seconds=0,
                    rate_limit_max_retries=1,
                )
            )

    result = service.run(view.job.job_id, factory)
    assert seen == ["005930"] * attempt_count + ([] if common else ["0001A0"])
    assert result.symbols[0].error_code == expected_code
    assert result.symbols[1].status == ("pending" if common else "completed")
    assert all(secret not in result.model_dump_json() for secret in secrets)


@pytest.mark.parametrize("status_code", [200, 500])
def test_alpha_token_refresh_uses_existing_bounded_logic(tmp_path: Path, status_code: int) -> None:
    service, view, _ = job(tmp_path)
    calls: list[str] = []
    tokens = StubTokenManager((_access_token(FIRST_TOKEN), _access_token(SECOND_TOKEN)))
    authorization: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        code = request.url.params["FID_INPUT_ISCD"]
        calls.append(code)
        authorization.append(request.headers["authorization"])
        if code == "0001A0" and calls.count(code) == 1:
            return _api_error(request, msg_cd="EGW00123", msg1="expired", status_code=status_code)
        return _success(request, _row("20260805"))

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        reader = KisHistoryReader(
            KisDailyPriceClient(
                _credentials(),
                tokens,
                client=client,
                request_interval_seconds=0,
            )
        )
        result = service.run(view.job.job_id, lambda: nullcontext(reader))
    assert result.complete
    assert calls == [*CODES, "0001A0"]
    assert authorization == [f"Bearer {FIRST_TOKEN}"] * 2 + [f"Bearer {SECOND_TOKEN}"]
    assert len(tokens.invalidated) == 1


@pytest.mark.parametrize("status_code", [200, 500])
def test_repeated_expiry_records_authentication_failure_and_stops_then_resumes(
    tmp_path: Path, status_code: int
) -> None:
    from history_helpers import Reader

    service, view, _ = job(tmp_path)
    calls: list[str] = []
    tokens = StubTokenManager((_access_token(FIRST_TOKEN), _access_token(SECOND_TOKEN)))

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.params["FID_INPUT_ISCD"])
        return _api_error(request, msg_cd="EGW00123", msg1="expired", status_code=status_code)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        reader = KisHistoryReader(
            KisDailyPriceClient(_credentials(), tokens, client=client, request_interval_seconds=0)
        )
        failed = service.run(view.job.job_id, lambda: nullcontext(reader))
    assert calls == [CODES[0]] * 2
    assert tokens.get_calls == 2
    assert len(tokens.invalidated) == 1
    assert failed.symbols[0].status == "failed"
    assert failed.symbols[0].error_code == "AUTHENTICATION_FAILED"
    assert failed.symbols[0].attempts[0].error_code == "AUTHENTICATION_FAILED"
    assert failed.symbols[0].result is None
    assert failed.symbols[1] == view.symbols[1]
    assert service.repository.load(view.job.job_id) == failed

    recovered = Reader()
    partial = service.run(view.job.job_id, recovered.factory)
    assert recovered.calls == [CODES[1]]
    assert partial.symbols[0] == failed.symbols[0]
    complete = service.run(view.job.job_id, recovered.factory, retry_failed=True)
    assert recovered.calls == [CODES[1], CODES[0]]
    assert complete.complete
    assert complete.symbols[1] == partial.symbols[1]
    assert [a.outcome for a in complete.symbols[0].attempts] == ["failed", "completed"]


def test_persisted_api_error_codes_and_messages_mask_all_secrets(tmp_path: Path) -> None:
    service, view, _ = job(tmp_path)

    def respond(request: httpx.Request) -> httpx.Response:
        return _api_error(
            request,
            msg_cd=APP_KEY,
            rt_cd=APP_SECRET,
            msg1=f"{FIRST_TOKEN} {ACCOUNT_NUMBER} " + "x" * 2000,
            status_code=200,
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        reader = KisHistoryReader(
            KisDailyPriceClient(
                _credentials(),
                StubTokenManager(),
                client=client,
                request_interval_seconds=0,
            )
        )
        result = service.run(view.job.job_id, lambda: nullcontext(reader))
    assert result.counts["failed"] == 2
    serialized = result.model_dump_json()
    assert all(
        secret not in serialized for secret in (APP_KEY, APP_SECRET, FIRST_TOKEN, ACCOUNT_NUMBER)
    )
    assert result.symbols[0].error_code == "KIS_API_[REDACTED]"
    assert len(result.symbols[0].error_message) < 1000


@pytest.mark.parametrize("code", ["0001a0", "0001A0\n", "0001A0 ", "0001A", 5930])
def test_daily_bar_rejects_unmodified_invalid_codes(code: object) -> None:
    from history_helpers import bar
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        bar(code)
