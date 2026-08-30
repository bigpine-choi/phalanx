from __future__ import annotations

import math
from dataclasses import replace
from decimal import ROUND_DOWN, ROUND_UP, Decimal, getcontext, setcontext

import numpy as np
import pytest

from phalanx.domain import (
    ConstrainedErcBoundFlag,
    ConstrainedErcSolverConfig,
)
from phalanx.portfolio.constrained_erc import (
    reconcile_decimal_weights,
    solve_constrained_erc,
)
from phalanx.portfolio.errors import (
    ConstrainedErcBisectionConvergenceError,
    ConstrainedErcCcdConvergenceError,
    ConstrainedErcInfeasibleBoundsError,
    ConstrainedErcInvalidCovarianceError,
    ConstrainedErcLambdaBracketError,
    ConstrainedErcReconciliationError,
)

_QUANTUM = Decimal("0.000000000001")


def _stock_codes(count: int) -> tuple[str, ...]:
    return tuple(f"{index + 1:06d}" for index in range(count))


def _identity(count: int) -> tuple[tuple[float, ...], ...]:
    return tuple(
        tuple(1.0 if row == column else 0.0 for column in range(count)) for row in range(count)
    )


def _covariance(
    volatilities: tuple[float, ...],
    correlations: tuple[tuple[float, ...], ...],
) -> tuple[tuple[float, ...], ...]:
    return tuple(
        tuple(
            correlations[row][column] * volatilities[row] * volatilities[column]
            for column in range(len(volatilities))
        )
        for row in range(len(volatilities))
    )


def _unbounded(count: int) -> tuple[Decimal, ...]:
    return tuple(Decimal(1) for _ in range(count))


def _normalized_inverse_volatility(
    volatilities: tuple[float, ...],
) -> tuple[float, ...]:
    inverse = tuple(1.0 / value for value in volatilities)
    total = sum(inverse)
    return tuple(value / total for value in inverse)


def test_identity_covariance_produces_equal_risky_weights() -> None:
    target = solve_constrained_erc(_identity(6), _stock_codes(6))

    assert tuple(float(value) for value in target.reconciled_weights) == pytest.approx(
        (1.0 / 6.0,) * 6,
        abs=1.1e-12,
    )
    assert sum(target.reconciled_weights, Decimal(0)) == Decimal(1)
    assert max(target.reconciled_weights) - min(target.reconciled_weights) <= _QUANTUM
    assert (
        target.diagnostics_after_reconciliation.bound_flags == (ConstrainedErcBoundFlag.FREE,) * 6
    )


def test_diagonal_covariance_produces_inverse_volatility_weights() -> None:
    volatilities = (0.10, 0.15, 0.20, 0.25, 0.30)
    covariance = tuple(
        tuple(
            volatilities[row] ** 2 if row == column else 0.0 for column in range(len(volatilities))
        )
        for row in range(len(volatilities))
    )

    target = solve_constrained_erc(
        covariance,
        _stock_codes(5),
        upper_bounds=_unbounded(5),
    )

    assert tuple(float(value) for value in target.reconciled_weights) == pytest.approx(
        _normalized_inverse_volatility(volatilities),
        abs=1.1e-12,
    )


def test_constant_correlation_preserves_inverse_volatility_solution() -> None:
    volatilities = (0.10, 0.15, 0.20, 0.25, 0.30)
    correlation = 0.35
    correlations = tuple(
        tuple(1.0 if row == column else correlation for column in range(5)) for row in range(5)
    )

    target = solve_constrained_erc(
        _covariance(volatilities, correlations),
        _stock_codes(5),
        upper_bounds=_unbounded(5),
    )

    assert tuple(float(value) for value in target.reconciled_weights) == pytest.approx(
        _normalized_inverse_volatility(volatilities),
        abs=1.1e-12,
    )


def test_positive_covariance_scaling_does_not_change_weights() -> None:
    volatilities = (0.10, 0.15, 0.20, 0.25, 0.30)
    correlations = tuple(
        tuple(1.0 if row == column else 0.25 for column in range(5)) for row in range(5)
    )
    covariance = _covariance(volatilities, correlations)
    scaled = tuple(tuple(value * 17.0 for value in row) for row in covariance)
    bounds = _unbounded(5)

    original = solve_constrained_erc(
        covariance,
        _stock_codes(5),
        upper_bounds=bounds,
    )
    changed_scale = solve_constrained_erc(
        scaled,
        _stock_codes(5),
        upper_bounds=bounds,
    )

    assert changed_scale.reconciled_weights == original.reconciled_weights
    assert changed_scale.raw_float_weights == pytest.approx(
        original.raw_float_weights,
        abs=2e-12,
    )


def test_asset_permutation_is_equivariant_with_bounds_and_covariance() -> None:
    volatilities = (0.15, 0.20, 0.25, 0.30, 0.10)
    correlations = (
        (1.00, 0.10, 0.40, 0.50, 0.50),
        (0.10, 1.00, 0.70, 0.40, 0.40),
        (0.40, 0.70, 1.00, 0.80, 0.05),
        (0.50, 0.40, 0.80, 1.00, 0.10),
        (0.50, 0.40, 0.05, 0.10, 1.00),
    )
    covariance = np.asarray(_covariance(volatilities, correlations), dtype=np.float64)
    lowers = tuple(map(Decimal, ("0.20", "0.20", "0.05", "0.10", "0.25")))
    uppers = tuple(map(Decimal, ("0.30", "0.30", "0.15", "0.20", "0.35")))
    codes = _stock_codes(5)
    permutation = (4, 2, 0, 3, 1)

    original = solve_constrained_erc(
        covariance,
        codes,
        lower_bounds=lowers,
        upper_bounds=uppers,
    )
    permuted = solve_constrained_erc(
        covariance[np.ix_(permutation, permutation)],
        tuple(codes[index] for index in permutation),
        lower_bounds=tuple(lowers[index] for index in permutation),
        upper_bounds=tuple(uppers[index] for index in permutation),
    )
    restored: list[Decimal | None] = [None] * 5
    for permuted_index, original_index in enumerate(permutation):
        restored[original_index] = permuted.reconciled_weights[permuted_index]

    assert tuple(restored) == original.reconciled_weights


def test_repeated_solve_is_fully_deterministic() -> None:
    covariance = tuple(
        tuple((row + 1.0) ** 2 if row == column else 0.0 for column in range(6)) for row in range(6)
    )

    first = solve_constrained_erc(covariance, _stock_codes(6))
    second = solve_constrained_erc(covariance, _stock_codes(6))

    assert second == first


def test_solver_result_is_independent_of_process_decimal_context() -> None:
    covariance = _identity(6)
    original_context = getcontext().copy()
    try:
        getcontext().prec = 4
        getcontext().rounding = ROUND_DOWN
        low_context = solve_constrained_erc(covariance, _stock_codes(6))
        assert getcontext().prec == 4
        assert getcontext().rounding == ROUND_DOWN

        getcontext().prec = 80
        getcontext().rounding = ROUND_UP
        high_context = solve_constrained_erc(covariance, _stock_codes(6))
        assert getcontext().prec == 80
        assert getcontext().rounding == ROUND_UP
    finally:
        setcontext(original_context)

    assert high_context == low_context


def test_low_volatility_asset_binds_cap_and_free_assets_keep_equal_rc() -> None:
    volatilities = (0.01, 0.10, 0.11, 0.12, 0.13, 0.14)
    covariance = tuple(
        tuple(volatilities[row] ** 2 if row == column else 0.0 for column in range(6))
        for row in range(6)
    )

    target = solve_constrained_erc(covariance, _stock_codes(6))
    diagnostics = target.diagnostics_after_reconciliation
    contributions = diagnostics.absolute_risk_contributions
    free_contributions = contributions[1:]
    budget = 1.0 / 6.0
    upper_q = contributions[0] - target.lambda_value * budget

    assert target.reconciled_weights[0] == Decimal("0.200000000000")
    assert diagnostics.bound_flags[0] is ConstrainedErcBoundFlag.UPPER
    assert diagnostics.bound_flags[1:] == (ConstrainedErcBoundFlag.FREE,) * 5
    assert max(free_contributions) - min(free_contributions) < 2e-12
    assert upper_q <= 1e-12
    assert diagnostics.normalized_max_kkt_residual <= 1e-10
    assert sum(contributions) == pytest.approx(diagnostics.portfolio_volatility, abs=1e-14)


def test_singular_perfect_positive_correlation_covariance_is_supported() -> None:
    volatilities = (0.10, 0.20, 0.30, 0.40, 0.50)
    covariance = tuple(tuple(left * right for right in volatilities) for left in volatilities)

    target = solve_constrained_erc(
        covariance,
        _stock_codes(5),
        upper_bounds=_unbounded(5),
    )

    assert tuple(float(value) for value in target.reconciled_weights) == pytest.approx(
        _normalized_inverse_volatility(volatilities),
        abs=1.1e-12,
    )
    assert target.expected_portfolio_volatility > 0


def test_valid_negative_correlation_psd_covariance_is_supported() -> None:
    count = 6
    correlation = -0.10
    covariance = tuple(
        tuple(1.0 if row == column else correlation for column in range(count))
        for row in range(count)
    )

    target = solve_constrained_erc(covariance, _stock_codes(count))

    assert tuple(float(value) for value in target.reconciled_weights) == pytest.approx(
        (1.0 / count,) * count,
        abs=1.1e-12,
    )
    assert target.expected_portfolio_volatility == pytest.approx(
        math.sqrt((1.0 + (count - 1) * correlation) / count),
        abs=1e-13,
    )


@pytest.mark.parametrize(
    "covariance, stock_codes",
    (
        (((1.0, 0.0),), _stock_codes(2)),
        (((1.0, float("nan")), (float("nan"), 1.0)), _stock_codes(2)),
        (((1.0, 0.50), (0.10, 1.0)), _stock_codes(2)),
        (((1.0, 2.0), (2.0, 1.0)), _stock_codes(2)),
        (((0.0, 0.0), (0.0, 1.0)), _stock_codes(2)),
        (_identity(2), ("000001", "000001")),
    ),
)
def test_invalid_covariance_or_stock_order_is_rejected(
    covariance: tuple[tuple[float, ...], ...],
    stock_codes: tuple[str, ...],
) -> None:
    with pytest.raises(ConstrainedErcInvalidCovarianceError):
        solve_constrained_erc(covariance, stock_codes)


def test_default_twenty_percent_cap_is_infeasible_below_five_assets() -> None:
    with pytest.raises(ConstrainedErcInfeasibleBoundsError, match="실행 불가능"):
        solve_constrained_erc(_identity(4), _stock_codes(4))


@pytest.mark.parametrize(
    "keyword, value",
    (
        ("risk_budgets", (Decimal("0.1"),) * 5),
        ("risk_budgets", (Decimal("0.2"),) * 4),
        ("lower_bounds", (Decimal("-0.1"),) + (Decimal(0),) * 4),
        ("upper_bounds", (Decimal("0.2"),) * 4),
        (
            "upper_bounds",
            (Decimal("0.1"), Decimal("0.2"), Decimal("0.2"), Decimal("0.2"), Decimal("0.2")),
        ),
    ),
)
def test_invalid_budgets_and_bounds_are_typed_failures(
    keyword: str,
    value: tuple[Decimal, ...],
) -> None:
    with pytest.raises(ConstrainedErcInfeasibleBoundsError):
        solve_constrained_erc(
            _identity(5),
            _stock_codes(5),
            **{keyword: value},
        )


def test_quantized_strict_positivity_can_make_bounds_infeasible() -> None:
    config = ConstrainedErcSolverConfig(weight_quantum=Decimal("0.3"))

    with pytest.raises(ConstrainedErcInfeasibleBoundsError, match="quantum"):
        solve_constrained_erc(
            _identity(5),
            _stock_codes(5),
            upper_bounds=_unbounded(5),
            config=config,
        )


def test_five_assets_at_twenty_percent_cap_is_allowed_all_bound_degeneracy() -> None:
    target = solve_constrained_erc(_identity(5), _stock_codes(5))

    assert target.reconciled_weights == (Decimal("0.200000000000"),) * 5
    assert (
        target.diagnostics_after_reconciliation.bound_flags == (ConstrainedErcBoundFlag.UPPER,) * 5
    )
    assert target.diagnostics_after_reconciliation.free_asset_rc_dispersion is None
    assert target.all_assets_bound_degeneracy is True


def test_ccd_exhaustion_raises_without_fallback() -> None:
    config = ConstrainedErcSolverConfig(maximum_ccd_sweeps=1)
    covariance = tuple(
        tuple((row + 1.0) ** 2 if row == column else 0.0 for column in range(6)) for row in range(6)
    )

    with pytest.raises(ConstrainedErcCcdConvergenceError):
        solve_constrained_erc(covariance, _stock_codes(6), config=config)


def test_bisection_exhaustion_raises_without_fallback() -> None:
    config = ConstrainedErcSolverConfig(maximum_bisection_iterations=1)
    volatilities = (0.01, 0.10, 0.11, 0.12, 0.13, 0.14)
    covariance = tuple(
        tuple(volatilities[row] ** 2 if row == column else 0.0 for column in range(6))
        for row in range(6)
    )

    with pytest.raises(ConstrainedErcBisectionConvergenceError):
        solve_constrained_erc(covariance, _stock_codes(6), config=config)


def test_lambda_bracket_exhaustion_raises_without_fallback() -> None:
    config = ConstrainedErcSolverConfig(
        maximum_bracket_expansions=1,
        bracket_expansion_factor=1.0001,
    )
    volatilities = (0.01, 0.10, 0.11, 0.12, 0.13, 0.14)
    covariance = tuple(
        tuple(volatilities[row] ** 2 if row == column else 0.0 for column in range(6))
        for row in range(6)
    )

    with pytest.raises(ConstrainedErcLambdaBracketError):
        solve_constrained_erc(covariance, _stock_codes(6), config=config)


def test_decimal_reconciliation_uses_registration_order_for_positive_ties() -> None:
    result = reconcile_decimal_weights(
        (0.375, 0.375, 0.375),
        (Decimal(0),) * 3,
        (Decimal(1),) * 3,
        quantum=Decimal("0.25"),
    )

    assert result == (Decimal("0.50"), Decimal("0.25"), Decimal("0.25"))


def test_decimal_reconciliation_uses_reverse_registration_order_for_removal() -> None:
    result = reconcile_decimal_weights(
        (0.5, 0.5, 0.5),
        (Decimal(0),) * 3,
        (Decimal(1),) * 3,
        quantum=Decimal("0.25"),
    )

    assert result == (Decimal("0.50"), Decimal("0.25"), Decimal("0.25"))


def test_decimal_reconciliation_skips_assets_without_upper_bound_slack() -> None:
    result = reconcile_decimal_weights(
        (0.375, 0.375, 0.375),
        (Decimal(0),) * 3,
        (Decimal("0.25"), Decimal(1), Decimal(1)),
        quantum=Decimal("0.25"),
    )

    assert result == (Decimal("0.25"), Decimal("0.50"), Decimal("0.25"))


def test_decimal_reconciliation_rejects_a_positive_weight_below_quantum() -> None:
    with pytest.raises(ConstrainedErcReconciliationError, match="quantum"):
        reconcile_decimal_weights(
            (1e-13, 0.5, 0.5),
            (Decimal(0),) * 3,
            (Decimal(1),) * 3,
        )


def test_richard_roncalli_four_asset_log_barrier_regression() -> None:
    volatilities = (0.10, 0.15, 0.20, 0.30)
    correlations = (
        (1.00, 0.50, 0.50, 0.50),
        (0.50, 1.00, 0.50, 0.50),
        (0.50, 0.50, 1.00, 0.75),
        (0.50, 0.50, 0.75, 1.00),
    )

    target = solve_constrained_erc(
        _covariance(volatilities, correlations),
        _stock_codes(4),
        upper_bounds=(Decimal("0.30"),) * 4,
    )
    weights = tuple(float(value) for value in target.reconciled_weights)

    assert weights == pytest.approx((0.30, 0.30, 0.24, 0.16), abs=2e-10)
    assert weights[2:] != pytest.approx((0.2457, 0.1543), abs=1e-4)
    assert target.expected_portfolio_volatility == pytest.approx(0.1397819731, abs=2e-11)
    assert target.diagnostics_after_reconciliation.bound_flags == (
        ConstrainedErcBoundFlag.UPPER,
        ConstrainedErcBoundFlag.UPPER,
        ConstrainedErcBoundFlag.FREE,
        ConstrainedErcBoundFlag.FREE,
    )


def test_richard_roncalli_table_six_box_constraint_regression() -> None:
    volatilities = (0.15, 0.20, 0.25, 0.30, 0.10)
    correlations = (
        (1.00, 0.10, 0.40, 0.50, 0.50),
        (0.10, 1.00, 0.70, 0.40, 0.40),
        (0.40, 0.70, 1.00, 0.80, 0.05),
        (0.50, 0.40, 0.80, 1.00, 0.10),
        (0.50, 0.40, 0.05, 0.10, 1.00),
    )
    lowers = tuple(map(Decimal, ("0.20", "0.20", "0.05", "0.10", "0.25")))
    uppers = tuple(map(Decimal, ("0.30", "0.30", "0.15", "0.20", "0.35")))

    target = solve_constrained_erc(
        _covariance(volatilities, correlations),
        _stock_codes(5),
        lower_bounds=lowers,
        upper_bounds=uppers,
    )
    diagnostics = target.diagnostics_after_reconciliation
    weights = tuple(float(value) for value in target.reconciled_weights)
    contributions = diagnostics.absolute_risk_contributions

    assert weights == pytest.approx(
        (0.2289, 0.2000, 0.1169, 0.1042, 0.3500),
        abs=5e-5,
    )
    assert diagnostics.bound_flags == (
        ConstrainedErcBoundFlag.FREE,
        ConstrainedErcBoundFlag.LOWER,
        ConstrainedErcBoundFlag.FREE,
        ConstrainedErcBoundFlag.FREE,
        ConstrainedErcBoundFlag.UPPER,
    )
    assert contributions[0] == pytest.approx(contributions[2], abs=2e-12)
    assert contributions[0] == pytest.approx(contributions[3], abs=2e-12)
    assert contributions[1] > contributions[0]
    assert contributions[4] < contributions[0]
    assert target.expected_portfolio_volatility == pytest.approx(0.1214, abs=5e-5)
    assert diagnostics.normalized_max_kkt_residual <= 1e-10


def test_ill_conditioned_valid_spd_does_not_stick_at_warm_start_tolerance() -> None:
    size = 8
    generator = np.random.default_rng(811)
    samples = generator.normal(size=(size, size))
    raw = samples @ samples.T
    volatilities = np.exp(generator.normal(-2, 1, size))
    diagonal = np.sqrt(np.diag(raw))
    correlation = raw / np.outer(diagonal, diagonal)
    covariance = correlation * np.outer(volatilities, volatilities)

    target = solve_constrained_erc(covariance, _stock_codes(size))

    assert sum(target.reconciled_weights, Decimal(0)) == Decimal(1)
    assert all(Decimal(0) < weight <= Decimal("0.20") for weight in target.reconciled_weights)
    assert target.weight_sum_residual_before <= 1e-12
    assert target.diagnostics_after_reconciliation.normalized_max_kkt_residual <= 1e-10


def test_solver_configuration_exhaustion_cases_do_not_mutate_defaults() -> None:
    original = ConstrainedErcSolverConfig()
    changed = replace(original, maximum_ccd_sweeps=1)

    assert original.maximum_ccd_sweeps == 10_000
    assert changed.maximum_ccd_sweeps == 1
