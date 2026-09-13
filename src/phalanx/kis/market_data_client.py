"""Read-only KIS domestic-stock current and adjusted daily-price retrieval."""

from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Protocol

import httpx

from phalanx.config import KisCredentials
from phalanx.domain import CurrentPriceMarket, CurrentPriceObservation, DailyBar
from phalanx.kis.auth import KIS_REAL_BASE_URL, AccessToken
from phalanx.kis.errors import (
    KisAuthError,
    KisMarketDataApiError,
    KisMarketDataAuthenticationError,
    KisMarketDataHttpError,
    KisMarketDataProtocolError,
    KisMarketDataRateLimitError,
    KisMarketDataTimeoutError,
)
from phalanx.kis.market_data_parsing import (
    parse_current_price_observation,
    parse_daily_bars_page,
)
from phalanx.market_data.errors import (
    InvalidMarketDataStockCodeError,
    InvalidValuationPriceRequestError,
    UnsupportedCurrentPriceMarketError,
)
from phalanx.market_data.validation import (
    validate_daily_date_range,
    validate_daily_stock_code,
    validate_market_data_stock_code,
)

KIS_DAILY_PRICE_PATH = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
KIS_DAILY_PRICE_URL = f"{KIS_REAL_BASE_URL}{KIS_DAILY_PRICE_PATH}"
KIS_DAILY_PRICE_TR_ID = "FHKST03010100"

# Official sample pinned at b4e6249714418aa57833d1cbbbced39cbcc5b125:
# https://github.com/koreainvestment/open-trading-api/blob/b4e6249714418aa57833d1cbbbced39cbcc5b125/examples_llm/domestic_stock/inquire_price/inquire_price.py
KIS_CURRENT_PRICE_PATH = "/uapi/domestic-stock/v1/quotations/inquire-price"
KIS_CURRENT_PRICE_URL = f"{KIS_REAL_BASE_URL}{KIS_CURRENT_PRICE_PATH}"
KIS_CURRENT_PRICE_TR_ID = "FHKST01010100"

_CUSTOMER_TYPE = "P"
_DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_DEFAULT_MAX_PAGES = 100
_KIS_DAILY_PAGE_LIMIT = 100
_DEFAULT_REQUEST_INTERVAL_SECONDS = 1.1
_DEFAULT_RATE_LIMIT_WAIT_SECONDS = 61.0
_DEFAULT_RATE_LIMIT_MAX_RETRIES = 3
_RATE_LIMIT_MESSAGE_CODE = "EGW00201"
_TOKEN_EXPIRED_MESSAGE_CODES = frozenset({"EGW00123"})
_MAX_ERROR_FIELD_CHARACTERS = 500
_CURRENT_PRICE_MAX_ATTEMPTS = 3
_CURRENT_PRICE_MESSAGE_CODE_PATTERN = re.compile(r"^[A-Z0-9_]{1,32}$")
_OMITTED_ERROR_FIELD = "[OMITTED]"

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


class _TokenManager(Protocol):
    def get_access_token(self) -> AccessToken: ...

    def invalidate_if_current(self, token: AccessToken) -> bool: ...


PageFingerprint = tuple[tuple[date, Decimal, Decimal, Decimal, Decimal, int], ...]


@dataclass(frozen=True, slots=True)
class _KisErrorMetadata:
    rt_cd: str | None = None
    msg_cd: str | None = None
    msg1: str | None = None


@dataclass(frozen=True, slots=True)
class _KisCurrentPriceEnvelope:
    rt_cd: str
    msg_cd: str


@dataclass(frozen=True, slots=True)
class KisRateLimitNotification:
    """Secret-free progress data emitted immediately before a rate-limit wait."""

    stock_code: str
    attempt_number: int
    max_attempts: int
    wait_seconds: float


type KisRateLimitCallback = Callable[[KisRateLimitNotification], None]


class KisRequestPacer:
    """Enforce a shared minimum interval immediately before KIS requests."""

    def __init__(
        self,
        *,
        minimum_interval_seconds: float = _DEFAULT_REQUEST_INTERVAL_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not callable(monotonic):
            raise TypeError("monotonic must be callable")
        if not callable(sleep):
            raise TypeError("sleep must be callable")
        self._minimum_interval_seconds = _validate_wait_seconds(
            "minimum_interval_seconds",
            minimum_interval_seconds,
        )
        self._monotonic = monotonic
        self._sleep = sleep
        self._last_request_at: float | None = None

    def wait_before_request(self) -> None:
        """Wait only for the unelapsed portion of the request interval."""

        now = self._monotonic()
        if self._last_request_at is not None:
            remaining = self._minimum_interval_seconds - (now - self._last_request_at)
            if remaining > 0:
                self._sleep(remaining)
                now = self._monotonic()
        self._last_request_at = now


class KisCurrentPriceClient:
    """Fetch one KRX current-price observation through the fixed KIS REST API.

    An injected ``httpx.Client`` remains owned by its caller. When no client is
    injected, a short-lived client is closed around the complete operation.
    """

    def __init__(
        self,
        credentials: KisCredentials,
        token_manager: _TokenManager,
        *,
        client: httpx.Client | None = None,
        timeout: httpx.Timeout | float = _DEFAULT_TIMEOUT,
        clock: Clock = _utc_now,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        request_interval_seconds: float = _DEFAULT_REQUEST_INTERVAL_SECONDS,
        request_pacer: KisRequestPacer | None = None,
        rate_limit_wait_seconds: float = _DEFAULT_RATE_LIMIT_WAIT_SECONDS,
        rate_limit_callback: KisRateLimitCallback | None = None,
    ) -> None:
        if not callable(clock):
            raise TypeError("clock must be callable")
        if not callable(sleep):
            raise TypeError("sleep must be callable")
        if rate_limit_callback is not None and not callable(rate_limit_callback):
            raise TypeError("rate_limit_callback must be callable")
        self._credentials = credentials
        self._token_manager = token_manager
        self._client = client
        self._timeout = timeout
        self._clock = clock
        self._sleep = sleep
        self._request_pacer = request_pacer or KisRequestPacer(
            minimum_interval_seconds=request_interval_seconds,
            monotonic=monotonic,
            sleep=sleep,
        )
        self._rate_limit_wait_seconds = _validate_wait_seconds(
            "rate_limit_wait_seconds",
            rate_limit_wait_seconds,
        )
        self._rate_limit_callback = rate_limit_callback

    def fetch_current_price(
        self,
        stock_code: str,
        market: CurrentPriceMarket,
    ) -> CurrentPriceObservation:
        """Fetch one exact current price, failing closed outside the KRX contract."""

        if type(stock_code) is not str:
            raise InvalidMarketDataStockCodeError(
                "Current-price stock_code must be exactly six ASCII digits."
            )
        validated_code = validate_market_data_stock_code(stock_code)
        if type(market) is not CurrentPriceMarket:
            raise InvalidValuationPriceRequestError("market must be a CurrentPriceMarket instance.")
        if market is not CurrentPriceMarket.KRX:
            raise UnsupportedCurrentPriceMarketError(market)
        if self._client is not None and self._client.params:
            raise KisMarketDataProtocolError(
                "The injected KIS current-price client must not define default query parameters."
            )

        request_started_at = self._now("current-price request start")
        if self._client is not None:
            return self._fetch_observation(
                self._client,
                stock_code=validated_code,
                market=market,
                request_started_at=request_started_at,
            )
        with httpx.Client() as client:
            return self._fetch_observation(
                client,
                stock_code=validated_code,
                market=market,
                request_started_at=request_started_at,
            )

    def _fetch_observation(
        self,
        client: httpx.Client,
        *,
        stock_code: str,
        market: CurrentPriceMarket,
        request_started_at: datetime,
    ) -> CurrentPriceObservation:
        authentication_retry_used = False

        for attempt_number in range(1, _CURRENT_PRICE_MAX_ATTEMPTS + 1):
            token = self._get_access_token()
            response = self._send_request(client, token=token, stock_code=stock_code)
            response_body = response.content
            response_received_at = self._now("current-price response receipt")

            if response.status_code == 401:
                authentication_retry_used = self._retry_authentication_or_raise(
                    token=token,
                    authentication_retry_used=authentication_retry_used,
                    attempt_number=attempt_number,
                    message=(
                        "The KIS current-price request remained unauthorized after "
                        "bounded reauthentication."
                    ),
                )
                continue

            is_success = 200 <= response.status_code < 300
            payload = (
                self._decode_json(response_body)
                if is_success
                else self._try_decode_json(response_body)
            )
            envelope = self._parse_envelope(payload, required=is_success)

            if self._is_expired_token_response(envelope):
                authentication_retry_used = self._retry_authentication_or_raise(
                    token=token,
                    authentication_retry_used=authentication_retry_used,
                    attempt_number=attempt_number,
                    message=(
                        "KIS rejected the current-price token after bounded reauthentication."
                    ),
                )
                continue

            if self._is_rate_limit_response(envelope):
                if attempt_number >= _CURRENT_PRICE_MAX_ATTEMPTS:
                    raise KisMarketDataRateLimitError(
                        self._format_http_error(
                            "The KIS current-price rate-limit retry limit was exhausted",
                            response.status_code,
                            envelope,
                            token,
                        )
                    )
                if self._rate_limit_callback is not None:
                    self._rate_limit_callback(
                        KisRateLimitNotification(
                            stock_code=stock_code,
                            attempt_number=attempt_number,
                            max_attempts=_CURRENT_PRICE_MAX_ATTEMPTS,
                            wait_seconds=self._rate_limit_wait_seconds,
                        )
                    )
                self._sleep(self._rate_limit_wait_seconds)
                continue

            if not is_success:
                raise KisMarketDataHttpError(
                    self._format_http_error(
                        "The KIS current-price request failed",
                        response.status_code,
                        envelope,
                        token,
                    )
                )

            if envelope is None:
                raise AssertionError("a successful current-price response must have an envelope")
            if envelope.rt_cd != "0":
                raise KisMarketDataApiError(
                    rt_cd="non-success",
                    msg_cd=_safe_current_price_message_code(
                        envelope.msg_cd,
                        self._sensitive_values(token),
                    ),
                    msg1="Provider message omitted.",
                )

            if response_received_at.astimezone(UTC) < request_started_at.astimezone(UTC):
                raise KisMarketDataProtocolError(
                    "The current-price response receipt preceded the request start."
                )

            return parse_current_price_observation(
                payload,
                stock_code=stock_code,
                market=market,
                request_started_at=request_started_at,
                received_at=response_received_at,
            )

        raise AssertionError("the bounded current-price retry loop did not terminate")

    def _send_request(
        self,
        client: httpx.Client,
        *,
        token: AccessToken,
        stock_code: str,
    ) -> httpx.Response:
        headers = {
            "authorization": f"Bearer {token.access_token.get_secret_value()}",
            "appkey": self._credentials.app_key.get_secret_value(),
            "appsecret": self._credentials.app_secret.get_secret_value(),
            "tr_id": KIS_CURRENT_PRICE_TR_ID,
            "custtype": _CUSTOMER_TYPE,
        }
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": stock_code,
        }
        failure: KisMarketDataHttpError
        try:
            self._request_pacer.wait_before_request()
            response = client.get(
                KIS_CURRENT_PRICE_URL,
                headers=headers,
                params=params,
                timeout=self._timeout,
                follow_redirects=False,
            )
        except httpx.TimeoutException:
            failure = KisMarketDataTimeoutError("The KIS current-price request timed out.")
        except httpx.HTTPError:
            failure = KisMarketDataHttpError(
                "The KIS current-price request failed before a response was received."
            )
        else:
            return response
        raise failure

    def _retry_authentication_or_raise(
        self,
        *,
        token: AccessToken,
        authentication_retry_used: bool,
        attempt_number: int,
        message: str,
    ) -> bool:
        if authentication_retry_used or attempt_number >= _CURRENT_PRICE_MAX_ATTEMPTS:
            raise KisMarketDataAuthenticationError(message)
        self._invalidate_token(token)
        return True

    def _get_access_token(self) -> AccessToken:
        failure: KisMarketDataAuthenticationError
        try:
            token = self._token_manager.get_access_token()
        except KisAuthError:
            failure = KisMarketDataAuthenticationError(
                "A KIS access token could not be obtained safely for current-price data."
            )
        else:
            return token
        raise failure

    def _invalidate_token(self, token: AccessToken) -> None:
        failure: KisMarketDataAuthenticationError
        try:
            self._token_manager.invalidate_if_current(token)
        except KisAuthError:
            failure = KisMarketDataAuthenticationError(
                "The rejected current-price token could not be invalidated safely."
            )
        else:
            return
        raise failure

    @staticmethod
    def _decode_json(response_body: bytes) -> object:
        failure: KisMarketDataProtocolError
        try:
            payload = json.loads(response_body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            failure = KisMarketDataProtocolError(
                "The KIS current-price response was not valid JSON."
            )
        else:
            return payload
        raise failure

    @staticmethod
    def _try_decode_json(response_body: bytes) -> object | None:
        try:
            decoded: object = json.loads(response_body)
            return decoded
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None

    @staticmethod
    def _parse_envelope(
        payload: object | None,
        *,
        required: bool,
    ) -> _KisCurrentPriceEnvelope | None:
        if not isinstance(payload, dict) or any(not isinstance(key, str) for key in payload):
            if required:
                raise KisMarketDataProtocolError(
                    "The KIS current-price response envelope was invalid."
                )
            return None
        rt_cd = payload.get("rt_cd")
        msg_cd = payload.get("msg_cd")
        if (
            not isinstance(rt_cd, str)
            or not rt_cd.strip()
            or not isinstance(msg_cd, str)
            or not msg_cd.strip()
        ):
            if required:
                raise KisMarketDataProtocolError(
                    "The KIS current-price response envelope was invalid."
                )
            return None
        return _KisCurrentPriceEnvelope(rt_cd=rt_cd, msg_cd=msg_cd)

    @staticmethod
    def _is_expired_token_response(envelope: _KisCurrentPriceEnvelope | None) -> bool:
        if envelope is None or envelope.rt_cd == "0":
            return False
        return envelope.msg_cd in _TOKEN_EXPIRED_MESSAGE_CODES

    @staticmethod
    def _is_rate_limit_response(envelope: _KisCurrentPriceEnvelope | None) -> bool:
        return (
            envelope is not None
            and envelope.rt_cd != "0"
            and envelope.msg_cd == _RATE_LIMIT_MESSAGE_CODE
        )

    def _sensitive_values(self, token: AccessToken) -> tuple[str, ...]:
        return (
            self._credentials.app_key.get_secret_value(),
            self._credentials.app_secret.get_secret_value(),
            self._credentials.account_number.get_secret_value(),
            self._credentials.cano,
            token.access_token.get_secret_value(),
        )

    def _format_http_error(
        self,
        prefix: str,
        status_code: int,
        envelope: _KisCurrentPriceEnvelope | None,
        token: AccessToken,
    ) -> str:
        secrets = self._sensitive_values(token)
        suffix = (
            f", msg_cd={_safe_current_price_message_code(envelope.msg_cd, secrets)}"
            if envelope is not None
            else ""
        )
        return f"{prefix} (HTTP {status_code}{suffix})."

    def _now(self, event: str) -> datetime:
        value = self._clock()
        if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
            raise KisMarketDataProtocolError(f"The {event} clock value must be timezone-aware.")
        return value


class KisDailyPriceClient:
    """Fetch adjusted daily bars through the fixed real KIS quotation API."""

    def __init__(
        self,
        credentials: KisCredentials,
        token_manager: _TokenManager,
        *,
        client: httpx.Client | None = None,
        timeout: httpx.Timeout | float = _DEFAULT_TIMEOUT,
        max_pages: int = _DEFAULT_MAX_PAGES,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        request_interval_seconds: float = _DEFAULT_REQUEST_INTERVAL_SECONDS,
        request_pacer: KisRequestPacer | None = None,
        rate_limit_wait_seconds: float = _DEFAULT_RATE_LIMIT_WAIT_SECONDS,
        rate_limit_max_retries: int = _DEFAULT_RATE_LIMIT_MAX_RETRIES,
        rate_limit_callback: KisRateLimitCallback | None = None,
    ) -> None:
        if type(max_pages) is not int or max_pages < 1:
            raise ValueError("max_pages must be a positive integer")
        if not callable(sleep):
            raise TypeError("sleep must be callable")
        if rate_limit_callback is not None and not callable(rate_limit_callback):
            raise TypeError("rate_limit_callback must be callable")
        if type(rate_limit_max_retries) is not int or rate_limit_max_retries < 1:
            raise ValueError("rate_limit_max_retries must be a positive integer")
        self._credentials = credentials
        self._token_manager = token_manager
        self._client = client
        self._timeout = timeout
        self._max_pages = max_pages
        self._sleep = sleep
        self._request_pacer = request_pacer or KisRequestPacer(
            minimum_interval_seconds=request_interval_seconds,
            monotonic=monotonic,
            sleep=sleep,
        )
        self._rate_limit_wait_seconds = _validate_wait_seconds(
            "rate_limit_wait_seconds",
            rate_limit_wait_seconds,
        )
        self._rate_limit_max_retries = rate_limit_max_retries
        self._rate_limit_callback = rate_limit_callback

    def fetch_daily_bars(
        self,
        stock_code: str,
        start: date,
        end: date,
    ) -> tuple[DailyBar, ...]:
        """Fetch a complete inclusive range and return bars oldest first."""

        validated_code = validate_daily_stock_code(stock_code)
        validated_start, validated_end = validate_daily_date_range(start, end)
        if self._client is not None:
            return self._fetch_all_pages(
                self._client,
                validated_code,
                validated_start,
                validated_end,
            )
        with httpx.Client() as client:
            return self._fetch_all_pages(
                client,
                validated_code,
                validated_start,
                validated_end,
            )

    def _fetch_all_pages(
        self,
        client: httpx.Client,
        stock_code: str,
        start: date,
        end: date,
    ) -> tuple[DailyBar, ...]:
        bars_by_date: dict[date, DailyBar] = {}
        seen_pages: set[PageFingerprint] = set()
        requested_end_dates: set[date] = set()
        current_end = end

        for page_number in range(1, self._max_pages + 1):
            if current_end in requested_end_dates:
                raise KisMarketDataProtocolError(
                    "The KIS daily-price end-date cursor did not advance."
                )
            requested_end_dates.add(current_end)

            page = self._fetch_page(
                client,
                stock_code=stock_code,
                start=start,
                end_cursor=current_end,
            )
            if not page:
                return _sorted_bars(bars_by_date)

            fingerprint = _page_fingerprint(page)
            if fingerprint in seen_pages:
                raise KisMarketDataProtocolError(
                    "The KIS daily-price response repeated an identical page."
                )
            seen_pages.add(fingerprint)

            for bar in page:
                if not start <= bar.trade_date <= end:
                    continue
                existing = bars_by_date.get(bar.trade_date)
                if existing is not None and existing != bar:
                    raise KisMarketDataProtocolError(
                        "The KIS daily-price response returned conflicting bars for one date."
                    )
                bars_by_date[bar.trade_date] = bar

            oldest_date = min(bar.trade_date for bar in page)
            if oldest_date <= start:
                return _sorted_bars(bars_by_date)
            try:
                next_end = oldest_date - timedelta(days=1)
            except OverflowError:
                raise KisMarketDataProtocolError(
                    "The KIS daily-price cursor could not move before the oldest date."
                ) from None
            if next_end >= current_end:
                raise KisMarketDataProtocolError(
                    "The KIS daily-price end-date cursor did not move into the past."
                )
            if len(page) < _KIS_DAILY_PAGE_LIMIT:
                return _sorted_bars(bars_by_date)
            if page_number >= self._max_pages:
                raise KisMarketDataProtocolError(
                    "The KIS daily-price response exceeded the configured page limit."
                )
            current_end = next_end

        raise AssertionError("the bounded daily-price pagination loop did not terminate")

    def _fetch_page(
        self,
        client: httpx.Client,
        *,
        stock_code: str,
        start: date,
        end_cursor: date,
    ) -> tuple[DailyBar, ...]:
        authentication_retry_used = False
        rate_limit_attempts = 0
        while True:
            token = self._get_access_token()
            response = self._send_request(
                client,
                token=token,
                stock_code=stock_code,
                start=start,
                end_cursor=end_cursor,
            )
            response_body = response.content
            if response.status_code == 401:
                if not authentication_retry_used:
                    self._invalidate_token(token)
                    authentication_retry_used = True
                    continue
                raise KisMarketDataAuthenticationError(
                    "The KIS daily-price request remained unauthorized after reauthentication."
                )

            is_success = 200 <= response.status_code < 300
            payload = (
                self._decode_json(response_body)
                if is_success
                else self._try_decode_json(response_body)
            )
            metadata = _parse_error_metadata(payload)
            if metadata.msg_cd == _RATE_LIMIT_MESSAGE_CODE:
                rate_limit_attempts += 1
                if rate_limit_attempts >= self._rate_limit_max_retries:
                    raise KisMarketDataRateLimitError(
                        self._format_http_error(
                            "The KIS daily-price rate-limit retry limit was exhausted",
                            response.status_code,
                            metadata,
                            token,
                        )
                    )
                if self._rate_limit_callback is not None:
                    self._rate_limit_callback(
                        KisRateLimitNotification(
                            stock_code=stock_code,
                            attempt_number=rate_limit_attempts,
                            max_attempts=self._rate_limit_max_retries,
                            wait_seconds=self._rate_limit_wait_seconds,
                        )
                    )
                self._sleep(self._rate_limit_wait_seconds)
                continue
            # KIS can report token expiry as HTTP 500. Share the 401 retry
            # allowance before classifying an unsuccessful status as an HTTP error.
            if self._is_expired_token_response(payload):
                if not authentication_retry_used:
                    self._invalidate_token(token)
                    authentication_retry_used = True
                    continue
                raise KisMarketDataAuthenticationError(
                    "KIS rejected the renewed token for the daily-price request."
                )
            if not is_success:
                raise KisMarketDataHttpError(
                    self._format_http_error(
                        "The KIS daily-price request failed",
                        response.status_code,
                        metadata,
                        token,
                    ),
                    status_code=response.status_code,
                )

            secrets = self._sensitive_values(token)
            try:
                return parse_daily_bars_page(
                    payload,
                    stock_code=stock_code,
                    sensitive_values=secrets,
                )
            except KisMarketDataApiError as error:
                # Stored diagnostics need the same bounded masking on every field,
                # including provider error codes echoed into a job's error_code.
                raise KisMarketDataApiError(
                    rt_cd=_sanitize_error_field(error.rt_cd, secrets),
                    msg_cd=_sanitize_error_field(error.msg_cd, secrets),
                    msg1=_sanitize_error_field(error.msg1, secrets),
                ) from None

    def _send_request(
        self,
        client: httpx.Client,
        *,
        token: AccessToken,
        stock_code: str,
        start: date,
        end_cursor: date,
    ) -> httpx.Response:
        headers = {
            "authorization": f"Bearer {token.access_token.get_secret_value()}",
            "appkey": self._credentials.app_key.get_secret_value(),
            "appsecret": self._credentials.app_secret.get_secret_value(),
            "tr_id": KIS_DAILY_PRICE_TR_ID,
            "custtype": _CUSTOMER_TYPE,
        }
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": stock_code,
            "FID_INPUT_DATE_1": start.strftime("%Y%m%d"),
            "FID_INPUT_DATE_2": end_cursor.strftime("%Y%m%d"),
            "FID_PERIOD_DIV_CODE": "D",
            "FID_ORG_ADJ_PRC": "0",
        }
        try:
            self._request_pacer.wait_before_request()
            return client.get(
                KIS_DAILY_PRICE_URL,
                headers=headers,
                params=params,
                timeout=self._timeout,
            )
        except httpx.TimeoutException:
            raise KisMarketDataTimeoutError("The KIS daily-price request timed out.") from None
        except httpx.HTTPError:
            raise KisMarketDataHttpError(
                "The KIS daily-price request failed before a response was received."
            ) from None

    def _get_access_token(self) -> AccessToken:
        try:
            return self._token_manager.get_access_token()
        except KisAuthError:
            raise KisMarketDataAuthenticationError(
                "A KIS access token could not be obtained safely for market data."
            ) from None

    def _invalidate_token(self, token: AccessToken) -> None:
        try:
            self._token_manager.invalidate_if_current(token)
        except KisAuthError:
            raise KisMarketDataAuthenticationError(
                "The rejected market-data token could not be invalidated safely."
            ) from None

    @staticmethod
    def _decode_json(response_body: bytes) -> object:
        try:
            return json.loads(response_body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise KisMarketDataProtocolError(
                "The KIS daily-price response was not valid JSON."
            ) from None

    @staticmethod
    def _try_decode_json(response_body: bytes) -> object | None:
        try:
            decoded: object = json.loads(response_body)
            return decoded
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None

    @staticmethod
    def _is_expired_token_response(payload: object) -> bool:
        if not isinstance(payload, dict) or payload.get("rt_cd") == "0":
            return False
        message_code = payload.get("msg_cd")
        return isinstance(message_code, str) and message_code in _TOKEN_EXPIRED_MESSAGE_CODES

    def _sensitive_values(self, token: AccessToken) -> tuple[str, ...]:
        return (
            self._credentials.app_key.get_secret_value(),
            self._credentials.app_secret.get_secret_value(),
            self._credentials.account_number.get_secret_value(),
            self._credentials.cano,
            token.access_token.get_secret_value(),
        )

    def _format_http_error(
        self,
        prefix: str,
        status_code: int,
        metadata: _KisErrorMetadata,
        token: AccessToken,
    ) -> str:
        secrets = self._sensitive_values(token)
        details: list[str] = []
        if metadata.msg_cd is not None:
            details.append(f"msg_cd={_sanitize_error_field(metadata.msg_cd, secrets)}")
        if metadata.msg1 is not None:
            details.append(f"msg1={_sanitize_error_field(metadata.msg1, secrets)}")
        suffix = f", {', '.join(details)}" if details else ""
        return f"{prefix} (HTTP {status_code}{suffix})."


def _validate_wait_seconds(field_name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a finite nonnegative number")
    validated = float(value)
    if not math.isfinite(validated) or validated < 0:
        raise ValueError(f"{field_name} must be a finite nonnegative number")
    return validated


def _parse_error_metadata(payload: object | None) -> _KisErrorMetadata:
    if not isinstance(payload, dict):
        return _KisErrorMetadata()
    return _KisErrorMetadata(
        rt_cd=_optional_error_field(payload.get("rt_cd")),
        msg_cd=_optional_error_field(payload.get("msg_cd")),
        msg1=_optional_error_field(payload.get("msg1")),
    )


def _optional_error_field(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _sanitize_error_field(value: str, secrets: tuple[str, ...]) -> str:
    sanitized = value
    for secret in sorted(set(secrets), key=len, reverse=True):
        if secret:
            sanitized = sanitized.replace(secret, "[REDACTED]")
    sanitized = " ".join(sanitized.split())
    if len(sanitized) > _MAX_ERROR_FIELD_CHARACTERS:
        return sanitized[:_MAX_ERROR_FIELD_CHARACTERS] + "..."
    return sanitized


def _safe_current_price_message_code(value: str, secrets: tuple[str, ...]) -> str:
    sanitized = _sanitize_error_field(value, secrets)
    if _CURRENT_PRICE_MESSAGE_CODE_PATTERN.fullmatch(sanitized) is None:
        return _OMITTED_ERROR_FIELD
    return sanitized


def _page_fingerprint(page: tuple[DailyBar, ...]) -> PageFingerprint:
    return tuple(
        sorted(
            (
                bar.trade_date,
                bar.open_price,
                bar.high_price,
                bar.low_price,
                bar.close_price,
                bar.volume,
            )
            for bar in page
        )
    )


def _sorted_bars(bars_by_date: dict[date, DailyBar]) -> tuple[DailyBar, ...]:
    return tuple(bars_by_date[trade_date] for trade_date in sorted(bars_by_date))


__all__ = [
    "KIS_CURRENT_PRICE_PATH",
    "KIS_CURRENT_PRICE_TR_ID",
    "KIS_CURRENT_PRICE_URL",
    "KIS_DAILY_PRICE_PATH",
    "KIS_DAILY_PRICE_TR_ID",
    "KIS_DAILY_PRICE_URL",
    "KisCurrentPriceClient",
    "KisDailyPriceClient",
    "KisRateLimitCallback",
    "KisRateLimitNotification",
    "KisRequestPacer",
]
