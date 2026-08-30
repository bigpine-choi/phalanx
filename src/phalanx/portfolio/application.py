"""Production assembly for aligned returns over read-only universe market data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx

from phalanx.domain import AlignedReturnMatrix, HistoricalUniverseAnalysis, KoreanStock
from phalanx.kis.market_data_client import KisRateLimitCallback, KisRequestPacer
from phalanx.market_data.application import run_production_universe_market_data
from phalanx.market_data.service import StockDailyBars
from phalanx.portfolio.errors import HistoricalReportStockOrderError
from phalanx.portfolio.performance import analyze_historical_universe
from phalanx.portfolio.report_storage import save_historical_report
from phalanx.portfolio.reporting import render_historical_report_html
from phalanx.portfolio.returns import build_aligned_return_matrix


@dataclass(frozen=True, slots=True)
class HistoricalReportResult:
    """Completed, safely persisted historical universe report."""

    analysis: HistoricalUniverseAnalysis
    stocks: tuple[KoreanStock, ...]
    saved_path: Path


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


def run_production_historical_report(
    start: date,
    end: date,
    output_path: Path,
    *,
    credentials_path: Path | None = None,
    token_cache_path: Path | None = None,
    universe_path: Path | None = None,
    transport: httpx.BaseTransport | None = None,
    rate_limit_callback: KisRateLimitCallback | None = None,
    request_pacer: KisRequestPacer | None = None,
) -> HistoricalReportResult:
    """Fetch once, analyze, render, and atomically store one read-only report."""

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
    matrix = build_aligned_return_matrix(histories)
    stocks = _stocks_in_matrix_order(histories, matrix)
    analysis = analyze_historical_universe(matrix)
    html = render_historical_report_html(analysis, stocks)
    saved_path = save_historical_report(html, output_path)
    return HistoricalReportResult(
        analysis=analysis,
        stocks=stocks,
        saved_path=saved_path,
    )


def _stocks_in_matrix_order(
    histories: tuple[StockDailyBars, ...],
    matrix: AlignedReturnMatrix,
) -> tuple[KoreanStock, ...]:
    stocks = tuple(history.stock for history in histories)
    if tuple(stock.stock_code for stock in stocks) != matrix.stock_codes:
        raise HistoricalReportStockOrderError(
            "종목코드·종목명 순서가 수익률 행렬 열 순서와 일치하지 않습니다."
        )
    return stocks


__all__ = [
    "HistoricalReportResult",
    "run_production_aligned_returns",
    "run_production_historical_report",
]
