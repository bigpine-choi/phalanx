"""Production assembly for read-only KIS daily market-data workflows."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx

from phalanx.config import load_kis_credentials
from phalanx.domain import DailyBar
from phalanx.kis import KisTokenManager
from phalanx.kis.market_data_client import (
    KisDailyPriceClient,
    KisRateLimitCallback,
    KisRequestPacer,
)
from phalanx.market_data.service import MarketDataService, StockDailyBars
from phalanx.market_data.validation import (
    validate_daily_date_range,
    validate_market_data_stock_code,
)
from phalanx.universe.repository import JsonUniverseRepository
from phalanx.universe.service import UniverseService

_APPLICATION_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


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

    validated_code = validate_market_data_stock_code(stock_code)
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
    "run_production_daily_market_data",
    "run_production_universe_market_data",
]
