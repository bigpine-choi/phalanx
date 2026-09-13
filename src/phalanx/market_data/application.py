"""Production assembly for read-only KIS daily and current market-data workflows."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx

from phalanx.config import load_kis_credentials
from phalanx.domain import CurrentPriceMarket, DailyBar, ValuationPriceBundle
from phalanx.kis import KisTokenManager
from phalanx.kis.market_data_client import (
    KisCurrentPriceClient,
    KisDailyPriceClient,
    KisRateLimitCallback,
    KisRequestPacer,
)
from phalanx.market_data.errors import InvalidValuationPriceRequestError
from phalanx.market_data.service import MarketDataService, StockDailyBars, ValuationPriceService
from phalanx.market_data.validation import (
    validate_daily_date_range,
    validate_daily_stock_code,
    validate_market_data_stock_code,
)
from phalanx.portfolio.private_json_storage import store_private_json_bytes
from phalanx.universe.repository import JsonUniverseRepository
from phalanx.universe.service import UniverseService

_APPLICATION_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


@dataclass(frozen=True)
class ValuationPriceResult:
    """A complete validated bundle, acquisition limit and optional persisted path."""

    bundle: ValuationPriceBundle
    max_acquisition_span_seconds: int
    saved_path: Path | None = None

    def to_json_bytes(self) -> bytes:
        """Keep exact Decimal prices and observation times without credential evidence."""

        payload = self.bundle.model_dump(mode="json")
        span = self.bundle.acquisition_span
        payload.update(
            schema_version="1",
            market=self.bundle.market.value,
            request_started_at=self.bundle.request_started_at.isoformat(),
            received_at=self.bundle.received_at.isoformat(),
            max_acquisition_span_seconds=self.max_acquisition_span_seconds,
            acquisition_span_microseconds=(
                (span.days * 86400 + span.seconds) * 1_000_000 + span.microseconds
            ),
            observation_time_basis="client_request_start_and_response_receipt",
        )
        return (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            + "\n"
        ).encode("utf-8")


def _validate_valuation_price_inputs(
    stock_codes: tuple[str, ...], max_acquisition_span_seconds: int
) -> timedelta:
    """Reject the entire request before constructing the credential/HTTP graph."""

    if type(stock_codes) is not tuple or not stock_codes:
        raise InvalidValuationPriceRequestError("종목코드를 한 개 이상 지정해야 합니다.")
    for stock_code in stock_codes:
        if type(stock_code) is not str:
            raise InvalidValuationPriceRequestError("종목코드는 공백 없는 6자리 숫자여야 합니다.")
        validate_market_data_stock_code(stock_code)
    if len(stock_codes) != len(set(stock_codes)):
        raise InvalidValuationPriceRequestError("중복 종목코드는 허용하지 않습니다.")
    if type(max_acquisition_span_seconds) is not int or max_acquisition_span_seconds <= 0:
        raise InvalidValuationPriceRequestError("수집 허용시간은 양의 정수 초여야 합니다.")
    try:
        return timedelta(seconds=max_acquisition_span_seconds)
    except OverflowError:
        raise InvalidValuationPriceRequestError(
            "수집 허용시간이 지원 범위를 벗어났습니다."
        ) from None


def _utc_now() -> datetime:
    return datetime.now(UTC)


def run_production_valuation_prices(
    stock_codes: tuple[str, ...],
    *,
    max_acquisition_span_seconds: int = 60,
    output_path: Path | None = None,
    credentials_path: Path | None = None,
    token_cache_path: Path | None = None,
    transport: httpx.BaseTransport | None = None,
    rate_limit_callback: KisRateLimitCallback | None = None,
    request_pacer: KisRequestPacer | None = None,
    clock: Callable[[], datetime] = _utc_now,
) -> ValuationPriceResult:
    """Fetch ordered KRX observations through one OAuth/HTTP graph, then optionally save."""

    maximum_span = _validate_valuation_price_inputs(stock_codes, max_acquisition_span_seconds)
    credentials = load_kis_credentials(credentials_path)
    with httpx.Client(transport=transport, timeout=_APPLICATION_TIMEOUT) as http_client:
        token_manager = KisTokenManager(
            credentials,
            cache_path=token_cache_path,
            client=http_client,
            timeout=_APPLICATION_TIMEOUT,
        )
        service = ValuationPriceService(
            KisCurrentPriceClient(
                credentials,
                token_manager,
                client=http_client,
                timeout=_APPLICATION_TIMEOUT,
                rate_limit_callback=rate_limit_callback,
                request_pacer=request_pacer,
                clock=clock,
            )
        )
        bundle = service.fetch_valuation_price_bundle(
            stock_codes,
            market=CurrentPriceMarket.KRX,
            maximum_acquisition_span=maximum_span,
        )
    result = ValuationPriceResult(bundle, max_acquisition_span_seconds)
    if output_path is None:
        return result
    saved_path = store_private_json_bytes(output_path, result.to_json_bytes())
    return ValuationPriceResult(bundle, max_acquisition_span_seconds, saved_path)


def run_production_daily_market_data(
    stock_code: str,
    start: date,
    end: date,
    *,
    credentials_path: Path | None = None,
    token_cache_path: Path | None = None,
    transport: httpx.BaseTransport | None = None,
    rate_limit_callback: KisRateLimitCallback | None = None,
    request_pacer: KisRequestPacer | None = None,
) -> tuple[DailyBar, ...]:
    """Build the fixed real-account read-only graph for one stock."""

    validated_code = validate_daily_stock_code(stock_code)
    validated_start, validated_end = validate_daily_date_range(start, end)
    credentials = load_kis_credentials(credentials_path)
    with httpx.Client(transport=transport, timeout=_APPLICATION_TIMEOUT) as http_client:
        token_manager = KisTokenManager(
            credentials,
            cache_path=token_cache_path,
            client=http_client,
            timeout=_APPLICATION_TIMEOUT,
        )
        service = MarketDataService(
            KisDailyPriceClient(
                credentials,
                token_manager,
                client=http_client,
                timeout=_APPLICATION_TIMEOUT,
                rate_limit_callback=rate_limit_callback,
                request_pacer=request_pacer,
            )
        )
        return service.fetch_daily_bars(validated_code, validated_start, validated_end)


def run_production_universe_market_data(
    start: date,
    end: date,
    *,
    credentials_path: Path | None = None,
    token_cache_path: Path | None = None,
    universe_path: Path | None = None,
    transport: httpx.BaseTransport | None = None,
    rate_limit_callback: KisRateLimitCallback | None = None,
    request_pacer: KisRequestPacer | None = None,
) -> tuple[StockDailyBars, ...]:
    """Build one shared OAuth/HTTP graph and sequentially read active stocks."""

    validated_start, validated_end = validate_daily_date_range(start, end)
    credentials = load_kis_credentials(credentials_path)
    universe_service = UniverseService(JsonUniverseRepository(universe_path))
    with httpx.Client(transport=transport, timeout=_APPLICATION_TIMEOUT) as http_client:
        token_manager = KisTokenManager(
            credentials,
            cache_path=token_cache_path,
            client=http_client,
            timeout=_APPLICATION_TIMEOUT,
        )
        service = MarketDataService(
            KisDailyPriceClient(
                credentials,
                token_manager,
                client=http_client,
                timeout=_APPLICATION_TIMEOUT,
                rate_limit_callback=rate_limit_callback,
                request_pacer=request_pacer,
            ),
            universe_service,
        )
        return service.fetch_active_universe(validated_start, validated_end)


__all__ = [
    "ValuationPriceResult",
    "run_production_daily_market_data",
    "run_production_universe_market_data",
    "run_production_valuation_prices",
]
