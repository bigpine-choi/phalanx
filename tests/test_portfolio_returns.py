from __future__ import annotations

from datetime import date
from decimal import ROUND_DOWN, ROUND_UP, Decimal, getcontext, setcontext
from pathlib import Path

import pytest

from phalanx.domain import DailyBar, KoreanStock, StockMarket
from phalanx.market_data.service import StockDailyBars
from phalanx.portfolio.errors import (
    DuplicateDailyBarDateError,
    DuplicateReturnStockCodeError,
    EmptyReturnUniverseError,
    EmptyStockHistoryError,
    InsufficientCommonObservationsError,
    InsufficientStockObservationsError,
    InvalidMinimumObservationsError,
    ReturnStockCodeMismatchError,
    UnsortedDailyBarsError,
)
from phalanx.portfolio.returns import build_aligned_return_matrix

ROOT = Path(__file__).resolve().parents[1]


def _stock(stock_code: str) -> KoreanStock:
    return KoreanStock(stock_code, f"종목 {stock_code}", StockMarket.KOSPI)


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


def _history(
    stock_code: str,
    *observations: tuple[date, str],
) -> StockDailyBars:
    return StockDailyBars(
        _stock(stock_code),
        tuple(_bar(stock_code, trade_date, close) for trade_date, close in observations),
    )


def test_builds_exact_simple_returns_with_input_order_as_columns() -> None:
    first = date(2026, 8, 3)
    second = date(2026, 8, 4)
    third = date(2026, 8, 5)
    histories = (
        _history("000660", (first, "200"), (second, "180"), (third, "198")),
        _history("005930", (first, "100"), (second, "110"), (third, "121")),
    )

    matrix = build_aligned_return_matrix(histories)

    assert matrix.stock_codes == ("000660", "005930")
    assert matrix.dates == (second, third)
    assert matrix.values == (
        (Decimal("-0.1"), Decimal("0.1")),
        (Decimal("0.1"), Decimal("0.1")),
    )


def test_uses_only_common_dates_without_forward_fill_and_compares_same_intervals() -> None:
    first = date(2026, 8, 3)
    non_common = date(2026, 8, 4)
    third = date(2026, 8, 5)
    fourth = date(2026, 8, 6)
    histories = (
        _history(
            "005930",
            (first, "100"),
            (non_common, "200"),
            (third, "300"),
            (fourth, "330"),
        ),
        _history("000660", (first, "50"), (third, "75"), (fourth, "60")),
    )

    matrix = build_aligned_return_matrix(histories)

    assert matrix.dates == (third, fourth)
    assert non_common not in matrix.dates
    assert matrix.values == (
        (Decimal("2"), Decimal("0.5")),
        (Decimal("0.1"), Decimal("-0.2")),
    )


def test_rejects_a_bar_whose_stock_code_does_not_match_its_universe_stock() -> None:
    history = StockDailyBars(
        _stock("005930"),
        (
            _bar("000660", date(2026, 8, 3), "100"),
            _bar("000660", date(2026, 8, 4), "110"),
        ),
    )

    with pytest.raises(ReturnStockCodeMismatchError, match=r"005930.*000660"):
        build_aligned_return_matrix((history,))


def test_rejects_duplicate_universe_stock_codes() -> None:
    observations = ((date(2026, 8, 3), "100"), (date(2026, 8, 4), "110"))

    with pytest.raises(DuplicateReturnStockCodeError, match="005930"):
        build_aligned_return_matrix(
            (_history("005930", *observations), _history("005930", *observations))
        )


@pytest.mark.parametrize(
    ("bars", "expected_error"),
    (
        (
            (
                _bar("005930", date(2026, 8, 3), "100"),
                _bar("005930", date(2026, 8, 3), "110"),
            ),
            DuplicateDailyBarDateError,
        ),
        (
            (
                _bar("005930", date(2026, 8, 4), "110"),
                _bar("005930", date(2026, 8, 3), "100"),
            ),
            UnsortedDailyBarsError,
        ),
    ),
)
def test_rejects_duplicate_or_reverse_ordered_daily_bars(
    bars: tuple[DailyBar, ...],
    expected_error: type[Exception],
) -> None:
    with pytest.raises(expected_error):
        build_aligned_return_matrix((StockDailyBars(_stock("005930"), bars),))


def test_rejects_an_empty_universe() -> None:
    with pytest.raises(EmptyReturnUniverseError, match="비어"):
        build_aligned_return_matrix(())


def test_rejects_an_empty_stock_history() -> None:
    with pytest.raises(EmptyStockHistoryError, match="005930"):
        build_aligned_return_matrix((StockDailyBars(_stock("005930"), ()),))


def test_rejects_a_stock_with_too_few_observations() -> None:
    with pytest.raises(InsufficientStockObservationsError, match=r"1개.*2개"):
        build_aligned_return_matrix((_history("005930", (date(2026, 8, 3), "100")),))


def test_rejects_too_few_common_close_observations() -> None:
    histories = (
        _history(
            "005930",
            (date(2026, 8, 3), "100"),
            (date(2026, 8, 4), "110"),
        ),
        _history(
            "000660",
            (date(2026, 8, 4), "200"),
            (date(2026, 8, 5), "220"),
        ),
    )

    with pytest.raises(InsufficientCommonObservationsError, match=r"1개.*2개"):
        build_aligned_return_matrix(histories)


def test_supports_an_injected_minimum_common_observation_count() -> None:
    observations = (
        (date(2026, 8, 3), "100"),
        (date(2026, 8, 4), "110"),
        (date(2026, 8, 5), "121"),
    )

    matrix = build_aligned_return_matrix(
        (_history("005930", *observations),),
        minimum_common_observations=3,
    )

    assert matrix.dates == (date(2026, 8, 4), date(2026, 8, 5))


def test_injected_minimum_applies_to_each_stock_history() -> None:
    with pytest.raises(InsufficientStockObservationsError, match=r"2개.*3개"):
        build_aligned_return_matrix(
            (
                _history(
                    "005930",
                    (date(2026, 8, 3), "100"),
                    (date(2026, 8, 4), "110"),
                ),
            ),
            minimum_common_observations=3,
        )


@pytest.mark.parametrize("minimum", (1, 0, -1, True, 2.5))
def test_rejects_invalid_minimum_observation_counts(minimum: object) -> None:
    with pytest.raises(InvalidMinimumObservationsError, match="2 이상의 정수"):
        build_aligned_return_matrix((), minimum_common_observations=minimum)  # type: ignore[arg-type]


def test_decimal_results_do_not_depend_on_the_process_global_context() -> None:
    history = _history(
        "005930",
        (date(2026, 8, 3), "3"),
        (date(2026, 8, 4), "4"),
    )
    original_context = getcontext().copy()
    try:
        getcontext().prec = 3
        getcontext().rounding = ROUND_DOWN
        low_precision_result = build_aligned_return_matrix((history,)).values
        assert getcontext().prec == 3
        assert getcontext().rounding == ROUND_DOWN

        getcontext().prec = 80
        getcontext().rounding = ROUND_UP
        high_precision_result = build_aligned_return_matrix((history,)).values
        assert getcontext().prec == 80
        assert getcontext().rounding == ROUND_UP
    finally:
        setcontext(original_context)

    assert low_precision_result == high_precision_result
    assert low_precision_result[0][0] == Decimal(
        "0.3333333333333333333333333333333333333333333333333"
    )


def test_return_calculation_core_has_no_infrastructure_or_numeric_library_dependency() -> None:
    sources = (
        ROOT / "src" / "phalanx" / "domain" / "portfolio.py",
        ROOT / "src" / "phalanx" / "portfolio" / "errors.py",
        ROOT / "src" / "phalanx" / "portfolio" / "returns.py",
    )
    combined = "\n".join(path.read_text(encoding="utf-8") for path in sources)

    forbidden = (
        "httpx",
        "numpy",
        "pandas",
        "phalanx.kis",
        "repository",
        "rich",
        "scipy",
        "sklearn",
        "typer",
    )
    assert all(dependency not in combined for dependency in forbidden)
