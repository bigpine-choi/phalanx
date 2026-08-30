from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from phalanx.domain import DailyBar, KoreanStock, StockMarket
from phalanx.market_data.service import StockDailyBars
from phalanx.portfolio.allocation_data import build_aligned_price_panel
from phalanx.portfolio.errors import (
    AllocationStockCodeMismatchError,
    DuplicateAllocationBarDateError,
    DuplicateAllocationStockCodeError,
    EmptyAllocationStockHistoryError,
    EmptyAllocationUniverseError,
    InsufficientAllocationObservationsError,
    InvalidAlignedPricePanelError,
    UnsortedAllocationBarsError,
)


def _stock(stock_code: str) -> KoreanStock:
    return KoreanStock(stock_code, f"종목 {stock_code}", StockMarket.KOSPI)


def _bar(
    stock_code: str,
    trade_date: date,
    open_price: str,
    close_price: str,
) -> DailyBar:
    opening = Decimal(open_price)
    closing = Decimal(close_price)
    return DailyBar(
        stock_code=stock_code,
        trade_date=trade_date,
        open_price=opening,
        high_price=max(opening, closing),
        low_price=min(opening, closing),
        close_price=closing,
        volume=1000,
    )


def _history(
    stock_code: str,
    *observations: tuple[date, str, str],
) -> StockDailyBars:
    return StockDailyBars(
        _stock(stock_code),
        tuple(_bar(stock_code, *observation) for observation in observations),
    )


def test_aligns_common_open_and_close_dates_without_fill_and_preserves_registration_order() -> None:
    first = date(2026, 1, 2)
    missing_from_second = date(2026, 1, 5)
    third = date(2026, 1, 6)
    fourth = date(2026, 1, 7)
    histories = (
        _history(
            "000660",
            (first, "200", "210"),
            (missing_from_second, "999", "999"),
            (third, "220", "230"),
            (fourth, "240", "250"),
        ),
        _history(
            "005930",
            (first, "100", "101"),
            (third, "102", "103"),
            (fourth, "104", "105"),
        ),
    )

    panel = build_aligned_price_panel(histories, minimum_common_observations=3)

    assert panel.stock_codes == ("000660", "005930")
    assert panel.dates == (first, third, fourth)
    assert missing_from_second not in panel.dates
    assert panel.open_prices == (
        (Decimal("200"), Decimal("100")),
        (Decimal("220"), Decimal("102")),
        (Decimal("240"), Decimal("104")),
    )
    assert panel.close_prices == (
        (Decimal("210"), Decimal("101")),
        (Decimal("230"), Decimal("103")),
        (Decimal("250"), Decimal("105")),
    )


def test_rejects_empty_universe_and_empty_stock_history() -> None:
    with pytest.raises(EmptyAllocationUniverseError, match="비어"):
        build_aligned_price_panel(())
    with pytest.raises(EmptyAllocationStockHistoryError, match="005930"):
        build_aligned_price_panel((StockDailyBars(_stock("005930"), ()),))


def test_rejects_duplicate_stock_codes_and_bar_code_mismatch() -> None:
    observations = (
        (date(2026, 1, 2), "100", "101"),
        (date(2026, 1, 5), "102", "103"),
    )
    with pytest.raises(DuplicateAllocationStockCodeError, match="005930"):
        build_aligned_price_panel(
            (_history("005930", *observations), _history("005930", *observations))
        )

    mismatch = StockDailyBars(
        _stock("005930"),
        (
            _bar("000660", date(2026, 1, 2), "100", "101"),
            _bar("000660", date(2026, 1, 5), "102", "103"),
        ),
    )
    with pytest.raises(AllocationStockCodeMismatchError, match=r"005930.*000660"):
        build_aligned_price_panel((mismatch,))


@pytest.mark.parametrize(
    ("bars", "error_type"),
    (
        (
            (
                _bar("005930", date(2026, 1, 2), "100", "101"),
                _bar("005930", date(2026, 1, 2), "102", "103"),
            ),
            DuplicateAllocationBarDateError,
        ),
        (
            (
                _bar("005930", date(2026, 1, 5), "102", "103"),
                _bar("005930", date(2026, 1, 2), "100", "101"),
            ),
            UnsortedAllocationBarsError,
        ),
    ),
)
def test_rejects_duplicate_and_reverse_ordered_bars(
    bars: tuple[DailyBar, ...],
    error_type: type[Exception],
) -> None:
    with pytest.raises(error_type):
        build_aligned_price_panel((StockDailyBars(_stock("005930"), bars),))


def test_rejects_too_few_common_observations() -> None:
    histories = (
        _history(
            "005930",
            (date(2026, 1, 2), "100", "101"),
            (date(2026, 1, 5), "102", "103"),
        ),
        _history(
            "000660",
            (date(2026, 1, 5), "200", "201"),
            (date(2026, 1, 6), "202", "203"),
        ),
    )

    with pytest.raises(InsufficientAllocationObservationsError, match=r"1개.*2개"):
        build_aligned_price_panel(histories)


@pytest.mark.parametrize("minimum", (1, 0, -1, True, 2.5))
def test_rejects_invalid_minimum_common_observations(minimum: object) -> None:
    with pytest.raises(InvalidAlignedPricePanelError, match="2 이상의 정수"):
        build_aligned_price_panel((), minimum_common_observations=minimum)  # type: ignore[arg-type]
