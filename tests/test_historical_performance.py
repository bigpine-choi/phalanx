from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import date
from decimal import ROUND_DOWN, ROUND_UP, Decimal, getcontext, setcontext
from pathlib import Path

import pytest

from phalanx.domain import AlignedReturnMatrix
from phalanx.portfolio.errors import (
    InsufficientPerformanceObservationsError,
    InvalidHistoricalUniverseAnalysisError,
    InvalidPerformanceReturnError,
)
from phalanx.portfolio.performance import analyze_historical_universe

ROOT = Path(__file__).resolve().parents[1]


def _matrix(
    stock_codes: tuple[str, ...],
    rows: tuple[tuple[Decimal, ...], ...],
    *,
    dates: tuple[date, ...] | None = None,
) -> AlignedReturnMatrix:
    selected_dates = dates or tuple(date(2026, 1, day + 2) for day in range(len(rows)))
    return AlignedReturnMatrix(stock_codes, selected_dates, rows)


def test_stock_compounding_and_equal_weight_buy_and_hold_are_not_daily_rebalanced() -> None:
    analysis = analyze_historical_universe(
        _matrix(
            ("005930", "000660"),
            (
                (Decimal("1"), Decimal("0")),
                (Decimal("-0.5"), Decimal("0")),
            ),
        )
    )

    assert analysis.stock_growth_factors == (
        (Decimal("2"), Decimal("1")),
        (Decimal("1.0"), Decimal("1")),
    )
    assert analysis.stock_metrics[0].total_return == Decimal("0.0")
    assert analysis.stock_metrics[1].total_return == Decimal("0")
    assert analysis.baseline_growth_factors == (Decimal("1.5"), Decimal("1.0"))
    assert analysis.baseline_daily_returns == (
        Decimal("0.5"),
        Decimal("-0.33333333333333333333333333333333333333333333333333"),
    )
    assert analysis.baseline_metrics.total_return == Decimal("0.0")
    daily_rebalanced_final_growth = (Decimal("1") + Decimal("0.5")) * (
        Decimal("1") - Decimal("0.25")
    )
    assert daily_rebalanced_final_growth == Decimal("1.125")
    assert analysis.baseline_growth_factors[-1] != daily_rebalanced_final_growth


def test_annualized_return_sample_volatility_sharpe_sortino_and_calmar() -> None:
    analysis = analyze_historical_universe(
        _matrix(
            ("005930",),
            ((Decimal("0.1"),), (Decimal("-0.1"),)),
        )
    )
    metrics = analysis.stock_metrics[0]

    assert metrics.observation_count == 2
    assert metrics.total_return == Decimal("-0.01")
    assert metrics.annualized_volatility == Decimal(
        "2.2449944320643648313502492393899295810536118846672"
    )
    assert metrics.sharpe_ratio == Decimal("0E+48")
    assert metrics.sortino_ratio == Decimal("0E+49")
    assert metrics.max_drawdown == Decimal("-0.1")
    assert metrics.calmar_ratio == Decimal("-7.1813930445953616659910057625758861975800188768282")


def test_drawdown_starts_with_peak_one_and_tracks_summary_statistics() -> None:
    analysis = analyze_historical_universe(
        _matrix(
            ("005930",),
            ((Decimal("-0.1"),), (Decimal("0.2"),)),
        )
    )
    metrics = analysis.stock_metrics[0]

    assert analysis.baseline_growth_factors == (Decimal("0.9"), Decimal("1.08"))
    assert analysis.baseline_drawdowns == (Decimal("-0.1"), Decimal("0"))
    assert metrics.max_drawdown == Decimal("-0.1")
    assert metrics.positive_day_ratio == Decimal("0.5")
    assert metrics.best_daily_return == Decimal("0.2")
    assert metrics.worst_daily_return == Decimal("-0.1")


def test_monthly_baseline_returns_compound_daily_returns() -> None:
    dates = (date(2026, 1, 30), date(2026, 1, 31), date(2026, 2, 2))
    analysis = analyze_historical_universe(
        _matrix(
            ("005930",),
            ((Decimal("0.1"),), (Decimal("0.2"),), (Decimal("-0.1"),)),
            dates=dates,
        )
    )

    assert tuple(value.month for value in analysis.monthly_baseline_returns) == (
        date(2026, 1, 1),
        date(2026, 2, 1),
    )
    assert tuple(value.value for value in analysis.monthly_baseline_returns) == (
        Decimal("0.32"),
        Decimal("-0.1"),
    )


def test_correlation_preserves_stock_order_and_marks_zero_variance_cells_none() -> None:
    analysis = analyze_historical_universe(
        _matrix(
            ("035900", "005930", "000660"),
            (
                (Decimal("0.1"), Decimal("0.3"), Decimal("0.1")),
                (Decimal("0.2"), Decimal("0.2"), Decimal("0.1")),
                (Decimal("0.3"), Decimal("0.1"), Decimal("0.1")),
            ),
        )
    )

    assert analysis.stock_codes == ("035900", "005930", "000660")
    assert analysis.correlation_matrix == (
        (Decimal("1"), Decimal("-1"), None),
        (Decimal("-1"), Decimal("1"), None),
        (None, None, None),
    )


def test_undefined_ratios_are_none_instead_of_zero_or_infinity() -> None:
    analysis = analyze_historical_universe(
        _matrix(
            ("005930",),
            ((Decimal("0.1"),), (Decimal("0.1"),)),
        )
    )
    metrics = analysis.stock_metrics[0]

    assert metrics.sharpe_ratio is None
    assert metrics.sortino_ratio is None
    assert metrics.max_drawdown == 0
    assert metrics.calmar_ratio is None
    assert analysis.correlation_matrix == ((None,),)


def test_requires_two_returns_and_rejects_nonpositive_growth_factors() -> None:
    one_observation = _matrix(("005930",), ((Decimal("0.1"),),))
    invalid_return = _matrix(
        ("005930",),
        ((Decimal("-1"),), (Decimal("0.1"),)),
    )

    with pytest.raises(InsufficientPerformanceObservationsError, match="최소 2개"):
        analyze_historical_universe(one_observation)
    with pytest.raises(InvalidPerformanceReturnError, match="-1보다 커야"):
        analyze_historical_universe(invalid_return)


def test_analysis_is_frozen_and_rejects_dimension_or_nonfinite_corruption() -> None:
    analysis = analyze_historical_universe(
        _matrix(
            ("005930",),
            ((Decimal("0.1"),), (Decimal("-0.1"),)),
        )
    )

    with pytest.raises(FrozenInstanceError):
        analysis.dates = ()
    with pytest.raises(FrozenInstanceError):
        analysis.baseline_metrics.total_return = Decimal("0")
    with pytest.raises(InvalidHistoricalUniverseAnalysisError, match="행 수"):
        replace(analysis, stock_growth_factors=analysis.stock_growth_factors[:1])
    with pytest.raises(InvalidHistoricalUniverseAnalysisError, match="유한한 양"):
        replace(
            analysis,
            baseline_growth_factors=(Decimal("NaN"), Decimal("1")),
        )
    with pytest.raises(InvalidHistoricalUniverseAnalysisError, match="상관계수"):
        replace(analysis, correlation_matrix=((Decimal("Infinity"),),))


def test_performance_results_are_independent_of_global_decimal_context() -> None:
    matrix = _matrix(
        ("005930", "000660"),
        (
            (Decimal("0.123456789"), Decimal("-0.023456789")),
            (Decimal("-0.076543211"), Decimal("0.176543211")),
            (Decimal("0.033333333"), Decimal("0.011111111")),
        ),
    )
    original = getcontext().copy()
    try:
        getcontext().prec = 4
        getcontext().rounding = ROUND_DOWN
        low_context = analyze_historical_universe(matrix)
        assert getcontext().prec == 4
        assert getcontext().rounding == ROUND_DOWN

        getcontext().prec = 80
        getcontext().rounding = ROUND_UP
        high_context = analyze_historical_universe(matrix)
        assert getcontext().prec == 80
        assert getcontext().rounding == ROUND_UP
    finally:
        setcontext(original)

    assert low_context == high_context


def test_performance_core_has_no_infrastructure_or_rendering_dependencies() -> None:
    sources = (
        ROOT / "src" / "phalanx" / "domain" / "performance.py",
        ROOT / "src" / "phalanx" / "portfolio" / "performance.py",
    )
    combined = "\n".join(path.read_text(encoding="utf-8") for path in sources).lower()

    for forbidden in (
        "httpx",
        "numpy",
        "pandas",
        "phalanx.kis",
        "plotly",
        "repository",
        "rich",
        "scipy",
        "sklearn",
        "typer",
    ):
        assert forbidden not in combined
