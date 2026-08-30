"""Production assembly for aligned returns over read-only universe market data."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx

from phalanx.domain import AlignedReturnMatrix
from phalanx.kis.market_data_client import KisRateLimitCallback, KisRequestPacer
from phalanx.market_data.application import run_production_universe_market_data
from phalanx.portfolio.returns import build_aligned_return_matrix


def run_production_aligned_returns(
    start: date,
    end: date,
    *,
    minimum_common_observations: int = 2,
    credentials_path: Path | None = None,
    token_cache_path: Path | None = None,
    universe_path: Path | None = None,
    transport: httpx.BaseTransport | None = None,
    rate_limit_callback: KisRateLimitCallback | None = None,
    request_pacer: KisRequestPacer | None = None,
) -> AlignedReturnMatrix:
    """Fetch the active universe exactly once, then calculate pure Decimal returns."""

    histories = run_production_universe_market_data(
        start,
        end,
        credentials_path=credentials_path,
        token_cache_path=token_cache_path,
        universe_path=universe_path,
        transport=transport,
        rate_limit_callback=rate_limit_callback,
        request_pacer=request_pacer,
    )
    return build_aligned_return_matrix(
        histories,
        minimum_common_observations=minimum_common_observations,
    )


__all__ = ["run_production_aligned_returns"]
