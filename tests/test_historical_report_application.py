from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

import phalanx.portfolio.application as portfolio_application
from phalanx.domain import AlignedReturnMatrix, DailyBar, KoreanStock, StockMarket
from phalanx.kis.market_data_client import KisRateLimitCallback, KisRequestPacer
from phalanx.market_data.service import StockDailyBars
from phalanx.portfolio.errors import HistoricalReportStockOrderError

START = date(2026, 1, 1)
END = date(2026, 1, 31)


def _bar(stock_code: str, trade_date: date, close_price: str) -> DailyBar:
    close = Decimal(close_price)
    return DailyBar(
        stock_code=stock_code,
        trade_date=trade_date,
        open_price=close,
        high_price=close,
        low_price=close,
        close_price=close,
        volume=1000,
    )


def _histories() -> tuple[StockDailyBars, ...]:
    samsung = KoreanStock("005930", "삼성전자", StockMarket.KOSPI)
    hynix = KoreanStock("000660", "SK하이닉스", StockMarket.KOSPI)
    dates = (date(2026, 1, 2), date(2026, 1, 3), date(2026, 1, 4))
    return (
        StockDailyBars(
            samsung,
            tuple(
                _bar("005930", value, close)
                for value, close in zip(dates, ("100", "110", "121"), strict=True)
            ),
        ),
        StockDailyBars(
            hynix,
            tuple(
                _bar("000660", value, close)
                for value, close in zip(dates, ("200", "180", "198"), strict=True)
            ),
        ),
    )


def test_production_report_fetches_universe_once_and_passes_shared_kis_hooks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[date, date]] = []
    rendered_stocks: list[tuple[KoreanStock, ...]] = []
    saved_payloads: list[tuple[str, Path]] = []
    output = tmp_path / "historical.html"
    pacer = KisRequestPacer(monotonic=lambda: 0.0, sleep=lambda seconds: None)

    def callback(notification: object) -> None:
        pass

    def fake_universe_runner(
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
        calls.append((start, end))
        assert rate_limit_callback is callback
        assert request_pacer is pacer
        return _histories()

    def fake_render(analysis: object, stocks: tuple[KoreanStock, ...]) -> str:
        rendered_stocks.append(stocks)
        return "<!doctype html><p>synthetic report</p>"

    def fake_save(html: str, output_path: Path) -> Path:
        saved_payloads.append((html, output_path))
        return output_path

    monkeypatch.setattr(
        portfolio_application,
        "run_production_universe_market_data",
        fake_universe_runner,
    )
    monkeypatch.setattr(portfolio_application, "render_historical_report_html", fake_render)
    monkeypatch.setattr(portfolio_application, "save_historical_report", fake_save)

    result = portfolio_application.run_production_historical_report(
        START,
        END,
        output,
        rate_limit_callback=callback,
        request_pacer=pacer,
    )

    assert calls == [(START, END)]
    assert tuple(stock.stock_code for stock in result.stocks) == ("005930", "000660")
    assert result.analysis.stock_codes == ("005930", "000660")
    assert rendered_stocks == [result.stocks]
    assert saved_payloads == [("<!doctype html><p>synthetic report</p>", output)]
    assert result.saved_path == output


def test_production_report_rejects_stock_name_order_mismatch_before_render_or_save(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        portfolio_application,
        "run_production_universe_market_data",
        lambda *args, **kwargs: _histories(),
    )
    monkeypatch.setattr(
        portfolio_application,
        "build_aligned_return_matrix",
        lambda histories: AlignedReturnMatrix(
            stock_codes=("000660", "005930"),
            dates=(date(2026, 1, 3), date(2026, 1, 4)),
            values=(
                (Decimal("-0.1"), Decimal("0.1")),
                (Decimal("0.1"), Decimal("0.1")),
            ),
        ),
    )

    with pytest.raises(HistoricalReportStockOrderError, match="순서"):
        portfolio_application.run_production_historical_report(
            START,
            END,
            tmp_path / "unused.html",
        )
