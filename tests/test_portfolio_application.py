from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

import phalanx.portfolio.application as portfolio_application
from phalanx.domain import DailyBar, KoreanStock, StockMarket
from phalanx.kis.market_data_client import (
    KisRateLimitCallback,
    KisRequestPacer,
)
from phalanx.market_data.service import StockDailyBars

START = date(2026, 8, 1)
END = date(2026, 8, 31)


def _bar(trade_date: date, close_price: str) -> DailyBar:
    close = Decimal(close_price)
    return DailyBar(
        stock_code="005930",
        trade_date=trade_date,
        open_price=close,
        high_price=close,
        low_price=close,
        close_price=close,
        volume=1000,
    )


def test_production_returns_reuses_one_universe_read_and_preserves_kis_hooks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    credentials_path = tmp_path / "credentials.env"
    token_cache_path = tmp_path / "token.json"
    universe_path = tmp_path / "universe.json"
    transport = httpx.MockTransport(
        lambda request: pytest.fail(f"unexpected HTTP request: {request.url}")
    )
    pacer = KisRequestPacer(monotonic=lambda: 0.0, sleep=lambda seconds: None)
    calls: list[tuple[date, date]] = []

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
        assert credentials_path == tmp_path / "credentials.env"
        assert token_cache_path == tmp_path / "token.json"
        assert universe_path == tmp_path / "universe.json"
        assert transport is not None
        assert rate_limit_callback is callback
        assert request_pacer is pacer
        stock = KoreanStock("005930", "삼성전자", StockMarket.KOSPI)
        return (
            StockDailyBars(
                stock,
                (
                    _bar(date(2026, 8, 3), "100"),
                    _bar(date(2026, 8, 4), "110"),
                ),
            ),
        )

    monkeypatch.setattr(
        portfolio_application,
        "run_production_universe_market_data",
        fake_universe_runner,
    )

    matrix = portfolio_application.run_production_aligned_returns(
        START,
        END,
        credentials_path=credentials_path,
        token_cache_path=token_cache_path,
        universe_path=universe_path,
        transport=transport,
        rate_limit_callback=callback,
        request_pacer=pacer,
    )

    assert calls == [(START, END)]
    assert matrix.stock_codes == ("005930",)
    assert matrix.values == ((Decimal("0.1"),),)
