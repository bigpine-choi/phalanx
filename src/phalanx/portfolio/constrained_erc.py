"""Deterministic box-constrained log-barrier equal-risk solver."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, ROUND_FLOOR, Context, Decimal, localcontext

import numpy as np
from numpy.typing import NDArray

from phalanx.domain import (
    CONSTRAINED_ERC_SOLVER_VERSION,
    ConstrainedErcBoundFlag,
    ConstrainedErcKktDiagnostics,
    ConstrainedErcSolverConfig,
    ConstrainedErcTarget,
    CovarianceScenario,
    CovarianceScenarioKind,
    DynamicRiskModelConfig,
    scenario_policy_id,
)
from phalanx.portfolio.dynamic_risk_model import repair_numerical_psd
from phalanx.portfolio.errors import (
    ConstrainedErcBisectionConvergenceError,
    ConstrainedErcCcdConvergenceError,
    ConstrainedErcDegenerateVarianceError,
    ConstrainedErcInfeasibleBoundsError,
    ConstrainedErcInvalidCovarianceError,
    ConstrainedErcKktValidationError,
    ConstrainedErcLambdaBracketError,
    ConstrainedErcReconciliationError,
    RiskModelError,
)

FloatMatrix = NDArray[np.float64]

_DECIMAL_PRECISION = 50
_DEFAULT_UPPER_BOUND = Decimal("0.20")
_ZERO = Decimal(0)
_ONE = Decimal(1)
_FLOAT_TINY = float(np.finfo(np.float64).tiny)
_SYMMETRY_RELATIVE_TOLERANCE = 1e-10
_SYMMETRY_ABSOLUTE_TOLERANCE = 1e-15


@dataclass(frozen=True, slots=True)
class _InnerSolution:
    weights: FloatMatrix
    sweeps: int


@dataclass(frozen=True, slots=True)
class _OuterSolution:
    weights: FloatMatrix
    lambda_value: float
    total_ccd_sweeps: int
    bisection_iterations: int
    bracket_expansions: int


class ConstrainedErcSolver:
    """Solve the registered log-barrier formulation without post-hoc normalization."""

    def __init__(
        self,
        config: ConstrainedErcSolverConfig | None = None,
        *,
        psd_config: DynamicRiskModelConfig | None = None,
    ) -> None:
        self.config = ConstrainedErcSolverConfig() if config is None else config
        self.psd_config = DynamicRiskModelConfig() if psd_config is None else psd_config
        if not isinstance(self.config, ConstrainedErcSolverConfig):
            raise ConstrainedErcInvalidCovarianceError("ERC solver 설정 타입이 올바르지 않습니다.")
        if not isinstance(self.psd_config, DynamicRiskModelConfig):
            raise ConstrainedErcInvalidCovarianceError("ERC PSD 설정 타입이 올바르지 않습니다.")

    def solve(
        self,
        covariance: tuple[tuple[float, ...], ...] | NDArray[np.float64],
        stock_codes: tuple[str, ...],
        *,
        risk_budgets: tuple[Decimal, ...] | None = None,
        lower_bounds: tuple[Decimal, ...] | None = None,
        upper_bounds: tuple[Decimal, ...] | None = None,
        scenario_kind: CovarianceScenarioKind = CovarianceScenarioKind.LONG_RUN_LEDOIT_WOLF,
        as_of_date: date = date.min,
    ) -> ConstrainedErcTarget:
        """Return one validated raw-float and exact-Decimal constrained solution."""

        matrix = _validated_covariance(covariance, stock_codes, self.psd_config)
        budgets, lowers, uppers = _validated_constraints(
            len(stock_codes),
            risk_budgets,
            lower_bounds,
            upper_bounds,
            self.config.weight_quantum,
        )
        budget_values = np.asarray(tuple(float(value) for value in budgets), dtype=np.float64)
        lower_values = np.asarray(tuple(float(value) for value in lowers), dtype=np.float64)
        upper_values = np.asarray(tuple(float(value) for value in uppers), dtype=np.float64)
        outer = _solve_outer(
            matrix,
            budget_values,
            lower_values,
            upper_values,
            self.config,
        )
        raw_weights = tuple(_clean_float(value) for value in outer.weights.tolist())
        before = _validate_and_diagnose(
            matrix,
            outer.weights,
            budget_values,
            lower_values,
            upper_values,
            outer.lambda_value,
            self.config,
            require_outer_sum=True,
        )
        reconciled = reconcile_decimal_weights(
            raw_weights,
            lowers,
            uppers,
            quantum=self.config.weight_quantum,
        )
        reconciled_float = np.asarray(
            tuple(float(value) for value in reconciled),
            dtype=np.float64,
        )
        after = _validate_and_diagnose(
            matrix,
            reconciled_float,
            budget_values,
            lower_values,
            upper_values,
            outer.lambda_value,
            self.config,
            require_outer_sum=True,
        )
        maximum_error = max(
            abs(float(value) - raw) for value, raw in zip(reconciled, raw_weights, strict=True)
        )
        return ConstrainedErcTarget(
            policy_id=scenario_policy_id(scenario_kind),
            scenario_kind=scenario_kind,
            as_of_date=as_of_date,
            stock_codes=stock_codes,
            risk_budgets=budgets,
            lower_bounds=lowers,
            upper_bounds=uppers,
            covariance_fingerprint=fingerprint_covariance(stock_codes, matrix),
            lambda_value=_clean_float(outer.lambda_value),
            raw_float_weights=raw_weights,
            reconciled_weights=reconciled,
            diagnostics_before_reconciliation=before,
            diagnostics_after_reconciliation=after,
            reconciliation_max_error=_clean_float(maximum_error),
            weight_sum_residual_before=_clean_float(abs(sum(raw_weights) - 1.0)),
            weight_sum_residual_after=abs(_decimal_sum(reconciled) - _ONE),
            ccd_sweeps=outer.total_ccd_sweeps,
            bisection_iterations=outer.bisection_iterations,
            bracket_expansions=outer.bracket_expansions,
            solver_config_fingerprint=fingerprint_solver_config(self.config),
            all_assets_bound_degeneracy=all(
                flag is not ConstrainedErcBoundFlag.FREE for flag in after.bound_flags
            ),
        )

    def solve_scenario(
        self,
        scenario: CovarianceScenario,
        *,
        as_of_date: date,
        risk_budgets: tuple[Decimal, ...] | None = None,
        lower_bounds: tuple[Decimal, ...] | None = None,
        upper_bounds: tuple[Decimal, ...] | None = None,
    ) -> ConstrainedErcTarget:
        """Solve one named dynamic-risk scenario without mixing covariances."""

        if not isinstance(scenario, CovarianceScenario):
            raise ConstrainedErcInvalidCovarianceError(
                "ERC scenario 입력은 CovarianceScenario여야 합니다."
            )
        return self.solve(
            scenario.annualized_covariance,
            scenario.stock_codes,
            risk_budgets=risk_budgets,
            lower_bounds=lower_bounds,
            upper_bounds=upper_bounds,
            scenario_kind=scenario.kind,
            as_of_date=as_of_date,
        )


def solve_constrained_erc(
    covariance: tuple[tuple[float, ...], ...] | NDArray[np.float64],
    stock_codes: tuple[str, ...],
    *,
    risk_budgets: tuple[Decimal, ...] | None = None,
    lower_bounds: tuple[Decimal, ...] | None = None,
    upper_bounds: tuple[Decimal, ...] | None = None,
    scenario_kind: CovarianceScenarioKind = CovarianceScenarioKind.LONG_RUN_LEDOIT_WOLF,
    as_of_date: date = date.min,
    config: ConstrainedErcSolverConfig | None = None,
    psd_config: DynamicRiskModelConfig | None = None,
) -> ConstrainedErcTarget:
    """Functional entry point for deterministic constrained risk budgeting."""

    return ConstrainedErcSolver(config, psd_config=psd_config).solve(
        covariance,
        stock_codes,
        risk_budgets=risk_budgets,
        lower_bounds=lower_bounds,
        upper_bounds=upper_bounds,
        scenario_kind=scenario_kind,
        as_of_date=as_of_date,
    )


def reconcile_decimal_weights(
    raw_weights: tuple[float, ...],
    lower_bounds: tuple[Decimal, ...],
    upper_bounds: tuple[Decimal, ...],
    *,
    quantum: Decimal = Decimal("0.000000000001"),
) -> tuple[Decimal, ...]:
    """Floor then allocate exact quanta by deterministic largest remainder."""

    with localcontext(Context(prec=100)):
        return _reconcile_decimal_weights(
            raw_weights,
            lower_bounds,
            upper_bounds,
            quantum=quantum,
        )


def _reconcile_decimal_weights(
    raw_weights: tuple[float, ...],
    lower_bounds: tuple[Decimal, ...],
    upper_bounds: tuple[Decimal, ...],
    *,
    quantum: Decimal,
) -> tuple[Decimal, ...]:

    if (
        not isinstance(raw_weights, tuple)
        or not raw_weights
        or len(raw_weights) != len(lower_bounds)
        or len(raw_weights) != len(upper_bounds)
    ):
        raise ConstrainedErcReconciliationError(
            "Decimal reconciliation 입력 차원이 종목 수와 일치하지 않습니다."
        )
    if not isinstance(quantum, Decimal) or not quantum.is_finite() or quantum <= 0:
        raise ConstrainedErcReconciliationError(
            "Decimal reconciliation quantum은 양의 유한한 값이어야 합니다."
        )
    if any(
        type(value) is not float or not math.isfinite(value) or value <= 0 for value in raw_weights
    ):
        raise ConstrainedErcReconciliationError(
            "Decimal reconciliation raw weight는 양의 유한한 float여야 합니다."
        )

    decimal_raw = tuple(Decimal.from_float(value) for value in raw_weights)
    if any(value < quantum for value in decimal_raw):
        raise ConstrainedErcReconciliationError(
            "양의 raw weight가 weight quantum보다 작아 0으로 만들 수 없습니다."
        )
    floors: list[Decimal] = []
    maximums: list[Decimal] = []
    remainders: list[Decimal] = []
    for raw, lower, upper in zip(decimal_raw, lower_bounds, upper_bounds, strict=True):
        if (
            not isinstance(lower, Decimal)
            or not lower.is_finite()
            or not isinstance(upper, Decimal)
            or not upper.is_finite()
            or lower < 0
            or upper <= lower
        ):
            raise ConstrainedErcReconciliationError(
                "Decimal reconciliation bounds가 올바르지 않습니다."
            )
        minimum = max(
            quantum,
            (lower / quantum).to_integral_value(rounding=ROUND_CEILING) * quantum,
        )
        maximum = (upper / quantum).to_integral_value(rounding=ROUND_FLOOR) * quantum
        floored = (raw / quantum).to_integral_value(rounding=ROUND_FLOOR) * quantum
        floored = min(max(floored, minimum), maximum)
        if minimum > maximum:
            raise ConstrainedErcReconciliationError(
                "bounds 안에 strictly positive Decimal quantum을 배치할 수 없습니다."
            )
        floors.append(floored)
        maximums.append(maximum)
        remainders.append(raw - floored)

    residual = _ONE - sum(floors, _ZERO)
    quotient = residual / quantum
    if quotient != quotient.to_integral_value():
        raise ConstrainedErcReconciliationError(
            "Decimal 합계 residual을 weight quantum 단위로 표현할 수 없습니다."
        )
    steps = int(abs(quotient))
    if residual > 0:
        order = tuple(sorted(range(len(floors)), key=lambda index: (-remainders[index], index)))
        _distribute_positive_quanta(floors, maximums, order, quantum, steps)
    elif residual < 0:
        minimums = [
            max(
                quantum,
                (lower / quantum).to_integral_value(rounding=ROUND_CEILING) * quantum,
            )
            for lower in lower_bounds
        ]
        reverse_order = tuple(
            sorted(range(len(floors)), key=lambda index: (remainders[index], -index))
        )
        _remove_negative_quanta(floors, minimums, reverse_order, quantum, steps)

    result = tuple(floors)
    if sum(result, _ZERO) != _ONE:
        raise ConstrainedErcReconciliationError(
            "Decimal reconciliation 뒤 목표비중 합계를 정확히 1로 맞추지 못했습니다."
        )
    if any(
        value <= 0 or value < lower or value > upper
        for value, lower, upper in zip(result, lower_bounds, upper_bounds, strict=True)
    ):
        raise ConstrainedErcReconciliationError(
            "Decimal reconciliation 결과가 positivity 또는 bounds를 위반합니다."
        )
    return result


def fingerprint_solver_config(config: ConstrainedErcSolverConfig) -> str:
    """Fingerprint every fixed numerical setting and solver version."""

    payload = {
        "solver_version": config.solver_version,
        "weight_quantum": _decimal_text(config.weight_quantum),
        "coordinate_change_tolerance": config.coordinate_change_tolerance.hex(),
        "normalized_kkt_tolerance": config.normalized_kkt_tolerance.hex(),
        "outer_sum_tolerance": config.outer_sum_tolerance.hex(),
        "maximum_ccd_sweeps": config.maximum_ccd_sweeps,
        "maximum_bisection_iterations": config.maximum_bisection_iterations,
        "maximum_bracket_expansions": config.maximum_bracket_expansions,
        "bracket_expansion_factor": config.bracket_expansion_factor.hex(),
    }
    return _fingerprint(payload)


def fingerprint_covariance(stock_codes: tuple[str, ...], covariance: FloatMatrix) -> str:
    """Fingerprint the exact ordered float64 matrix consumed by the solver."""

    return _fingerprint(
        {
            "stock_codes": list(stock_codes),
            "annualized_covariance_float64_hex": [
                [float(value).hex() for value in row] for row in covariance.tolist()
            ],
        }
    )


def fingerprint_consumed_covariance(
    covariance: tuple[tuple[float, ...], ...] | NDArray[np.float64],
    stock_codes: tuple[str, ...],
    *,
    psd_config: DynamicRiskModelConfig | None = None,
) -> str:
    """Fingerprint the exact matrix after the shared PSD quality boundary."""

    selected_psd_config = DynamicRiskModelConfig() if psd_config is None else psd_config
    if not isinstance(selected_psd_config, DynamicRiskModelConfig):
        raise ConstrainedErcInvalidCovarianceError("ERC PSD 설정 타입이 올바르지 않습니다.")
    return fingerprint_covariance(
        stock_codes,
        _validated_covariance(covariance, stock_codes, selected_psd_config),
    )


def _validated_covariance(
    covariance: tuple[tuple[float, ...], ...] | NDArray[np.float64],
    stock_codes: tuple[str, ...],
    psd_config: DynamicRiskModelConfig,
) -> FloatMatrix:
    if (
        not isinstance(stock_codes, tuple)
        or not stock_codes
        or len(set(stock_codes)) != len(stock_codes)
    ):
        raise ConstrainedErcInvalidCovarianceError(
            "ERC covariance 종목 순서는 비어 있지 않고 중복이 없어야 합니다."
        )
    try:
        matrix = np.asarray(covariance, dtype=np.float64, order="C")
    except (TypeError, ValueError, OverflowError):
        raise ConstrainedErcInvalidCovarianceError(
            "ERC covariance를 유한한 float64 행렬로 변환하지 못했습니다."
        ) from None
    size = len(stock_codes)
    if matrix.shape != (size, size) or not np.all(np.isfinite(matrix)):
        raise ConstrainedErcInvalidCovarianceError(
            "ERC covariance 차원은 종목 순서와 일치하는 유한한 정사각 행렬이어야 합니다."
        )
    scale = max(float(np.max(np.abs(matrix))), _FLOAT_TINY)
    symmetry_tolerance = max(
        _SYMMETRY_ABSOLUTE_TOLERANCE,
        _SYMMETRY_RELATIVE_TOLERANCE * scale,
    )
    if float(np.max(np.abs(matrix - matrix.T))) > symmetry_tolerance:
        raise ConstrainedErcInvalidCovarianceError("ERC covariance는 대칭이어야 합니다.")
    if np.any(np.diag(matrix) <= 0):
        raise ConstrainedErcInvalidCovarianceError(
            "ERC covariance 대각원소는 strictly positive여야 합니다."
        )
    try:
        repaired, _ = repair_numerical_psd(matrix, psd_config)
    except RiskModelError as error:
        raise ConstrainedErcInvalidCovarianceError(
            "ERC covariance가 기존 PSD 수치 품질 정책을 통과하지 못했습니다."
        ) from error
    if np.any(np.diag(repaired) <= 0):
        raise ConstrainedErcInvalidCovarianceError(
            "PSD 검사 뒤 ERC covariance 대각원소는 strictly positive여야 합니다."
        )
    result = np.asarray(repaired, dtype=np.float64, order="C")
    result.setflags(write=False)
    return result


def _validated_constraints(
    size: int,
    risk_budgets: tuple[Decimal, ...] | None,
    lower_bounds: tuple[Decimal, ...] | None,
    upper_bounds: tuple[Decimal, ...] | None,
    quantum: Decimal,
) -> tuple[tuple[Decimal, ...], tuple[Decimal, ...], tuple[Decimal, ...]]:
    budgets = _equal_decimal_budgets(size) if risk_budgets is None else risk_budgets
    lowers = tuple(_ZERO for _ in range(size)) if lower_bounds is None else lower_bounds
    uppers = (
        tuple(_DEFAULT_UPPER_BOUND for _ in range(size)) if upper_bounds is None else upper_bounds
    )
    for label, values in (
        ("risk budgets", budgets),
        ("lower bounds", lowers),
        ("upper bounds", uppers),
    ):
        if (
            not isinstance(values, tuple)
            or len(values) != size
            or any(not isinstance(value, Decimal) or not value.is_finite() for value in values)
        ):
            raise ConstrainedErcInfeasibleBoundsError(
                f"ERC {label} 차원과 유한성이 종목 수와 일치해야 합니다."
            )
    if any(value <= 0 for value in budgets) or _decimal_sum(budgets) != _ONE:
        raise ConstrainedErcInfeasibleBoundsError(
            "ERC risk budgets는 양수이고 Decimal 합계가 정확히 1이어야 합니다."
        )
    if any(
        lower < 0 or upper <= 0 or lower >= upper
        for lower, upper in zip(lowers, uppers, strict=True)
    ):
        raise ConstrainedErcInfeasibleBoundsError(
            "ERC bounds는 각 종목에서 0 <= lower < upper여야 합니다."
        )
    if _decimal_sum(lowers) > _ONE or _decimal_sum(uppers) < _ONE:
        raise ConstrainedErcInfeasibleBoundsError(
            "ERC bounds 합계가 위험자산 목표비중 1을 포함하지 않아 실행 불가능합니다."
        )
    quantized_minimum = sum(
        (
            max(
                quantum,
                (lower / quantum).to_integral_value(rounding=ROUND_CEILING) * quantum,
            )
            for lower in lowers
        ),
        _ZERO,
    )
    quantized_maximum = sum(
        ((upper / quantum).to_integral_value(rounding=ROUND_FLOOR) * quantum for upper in uppers),
        _ZERO,
    )
    if quantized_minimum > _ONE or quantized_maximum < _ONE:
        raise ConstrainedErcInfeasibleBoundsError(
            "ERC bounds 안에서 quantum 단위의 strictly positive 합계 1을 만들 수 없습니다."
        )
    return budgets, lowers, uppers


def _equal_decimal_budgets(size: int) -> tuple[Decimal, ...]:
    context = Context(prec=_DECIMAL_PRECISION)
    with localcontext(context):
        equal = _ONE / Decimal(size)
    if size == 1:
        return (_ONE,)
    leading = tuple(equal for _ in range(size - 1))
    with localcontext(Context(prec=100)):
        return (*leading, _ONE - sum(leading, _ZERO))


def _solve_outer(
    covariance: FloatMatrix,
    budgets: FloatMatrix,
    lowers: FloatMatrix,
    uppers: FloatMatrix,
    config: ConstrainedErcSolverConfig,
) -> _OuterSolution:
    equal_weights = np.full(len(budgets), 1.0 / len(budgets), dtype=np.float64)
    initial_variance = float(equal_weights @ covariance @ equal_weights)
    if not math.isfinite(initial_variance) or initial_variance <= 0:
        raise ConstrainedErcDegenerateVarianceError(
            "equal-weight feasible scale의 포트폴리오 분산이 양수가 아닙니다."
        )
    lambda_upper = math.sqrt(initial_variance)
    total_sweeps = 0
    bracket_expansions = 0
    warm_start: FloatMatrix | None = None
    upper_solution: _InnerSolution | None = None
    for expansion in range(config.maximum_bracket_expansions + 1):
        upper_solution = _solve_inner(
            covariance,
            budgets,
            lowers,
            uppers,
            lambda_upper,
            config,
            warm_start=warm_start,
        )
        total_sweeps += upper_solution.sweeps
        weight_sum = float(np.sum(upper_solution.weights))
        if weight_sum >= 1.0 - config.outer_sum_tolerance:
            bracket_expansions = expansion
            break
        if expansion == config.maximum_bracket_expansions:
            raise ConstrainedErcLambdaBracketError(
                "허용된 확장 횟수 안에 합계 1을 포함하는 positive lambda 상단을 찾지 못했습니다."
            )
        warm_start = upper_solution.weights
        lambda_upper *= config.bracket_expansion_factor
        if not math.isfinite(lambda_upper) or lambda_upper <= 0:
            raise ConstrainedErcLambdaBracketError("lambda bracket 상단이 유한한 양수가 아닙니다.")
    if upper_solution is None:
        raise ConstrainedErcLambdaBracketError("positive lambda bracket을 생성하지 못했습니다.")

    upper_sum = float(np.sum(upper_solution.weights))
    if abs(upper_sum - 1.0) <= config.outer_sum_tolerance:
        return _OuterSolution(
            weights=upper_solution.weights,
            lambda_value=lambda_upper,
            total_ccd_sweeps=total_sweeps,
            bisection_iterations=0,
            bracket_expansions=bracket_expansions,
        )

    lambda_lower = 0.0
    current = upper_solution
    for iteration in range(1, config.maximum_bisection_iterations + 1):
        lambda_middle = (lambda_lower + lambda_upper) / 2.0
        if not math.isfinite(lambda_middle) or lambda_middle <= 0:
            raise ConstrainedErcBisectionConvergenceError(
                "outer bisection이 positive finite lambda를 만들지 못했습니다."
            )
        current = _solve_inner(
            covariance,
            budgets,
            lowers,
            uppers,
            lambda_middle,
            config,
            warm_start=None,
        )
        total_sweeps += current.sweeps
        weight_sum = float(np.sum(current.weights))
        if abs(weight_sum - 1.0) <= config.outer_sum_tolerance:
            return _OuterSolution(
                weights=current.weights,
                lambda_value=lambda_middle,
                total_ccd_sweeps=total_sweeps,
                bisection_iterations=iteration,
                bracket_expansions=bracket_expansions,
            )
        if weight_sum < 1.0:
            lambda_lower = lambda_middle
        else:
            lambda_upper = lambda_middle
    raise ConstrainedErcBisectionConvergenceError(
        "outer bisection이 허용 반복 횟수 안에 목표비중 합계 1로 수렴하지 않았습니다."
    )


def _solve_inner(
    covariance: FloatMatrix,
    budgets: FloatMatrix,
    lowers: FloatMatrix,
    uppers: FloatMatrix,
    lambda_value: float,
    config: ConstrainedErcSolverConfig,
    *,
    warm_start: FloatMatrix | None,
) -> _InnerSolution:
    if not math.isfinite(lambda_value) or lambda_value <= 0:
        raise ConstrainedErcCcdConvergenceError("CCD lambda는 strictly positive여야 합니다.")
    if warm_start is None:
        diagonal_values = np.diag(covariance)
        unconstrained_scale = np.sqrt(lambda_value * budgets / diagonal_values)
        weights = np.minimum(
            np.maximum(unconstrained_scale, np.maximum(lowers, _FLOAT_TINY)), uppers
        )
    else:
        weights = np.asarray(warm_start, dtype=np.float64).copy()
        if weights.shape != budgets.shape or not np.all(np.isfinite(weights)):
            raise ConstrainedErcCcdConvergenceError(
                "CCD warm start 차원 또는 유한성이 올바르지 않습니다."
            )
        weights = np.minimum(np.maximum(weights, np.maximum(lowers, _FLOAT_TINY)), uppers)

    for sweep in range(1, config.maximum_ccd_sweeps + 1):
        maximum_change = 0.0
        for index in range(len(weights)):
            marginal_vector = covariance @ weights
            variance = float(weights @ marginal_vector)
            if not math.isfinite(variance) or variance <= 0:
                raise ConstrainedErcDegenerateVarianceError(
                    "CCD feasible candidate의 포트폴리오 분산이 양수가 아닙니다."
                )
            sigma = math.sqrt(variance)
            diagonal_entry = float(covariance[index, index])
            cross_term = float(marginal_vector[index] - diagonal_entry * weights[index])
            barrier_term = lambda_value * float(budgets[index]) * sigma
            discriminant = cross_term * cross_term + 4.0 * diagonal_entry * barrier_term
            if not math.isfinite(discriminant) or discriminant <= 0:
                raise ConstrainedErcCcdConvergenceError(
                    "CCD coordinate root 판별식이 양의 유한한 값이 아닙니다."
                )
            square_root = math.sqrt(discriminant)
            if cross_term >= 0:
                denominator = cross_term + square_root
                root = 2.0 * barrier_term / denominator
            else:
                root = (-cross_term + square_root) / (2.0 * diagonal_entry)
            if not math.isfinite(root) or root <= 0:
                raise ConstrainedErcCcdConvergenceError(
                    "CCD coordinate의 positive root를 안전하게 계산하지 못했습니다."
                )
            updated = min(max(root, float(lowers[index])), float(uppers[index]))
            if not math.isfinite(updated) or updated <= 0:
                raise ConstrainedErcCcdConvergenceError(
                    "CCD bound projection 뒤 weight가 strictly positive가 아닙니다."
                )
            maximum_change = max(maximum_change, abs(updated - float(weights[index])))
            weights[index] = updated
        if maximum_change <= config.coordinate_change_tolerance:
            weights.setflags(write=False)
            return _InnerSolution(weights=weights, sweeps=sweep)
    raise ConstrainedErcCcdConvergenceError(
        "CCD가 허용 sweep 횟수 안에 좌표 변화 허용오차로 수렴하지 않았습니다."
    )


def _validate_and_diagnose(
    covariance: FloatMatrix,
    weights: FloatMatrix,
    budgets: FloatMatrix,
    lowers: FloatMatrix,
    uppers: FloatMatrix,
    lambda_value: float,
    config: ConstrainedErcSolverConfig,
    *,
    require_outer_sum: bool,
) -> ConstrainedErcKktDiagnostics:
    if weights.shape != budgets.shape or not np.all(np.isfinite(weights)) or np.any(weights <= 0):
        raise ConstrainedErcKktValidationError(
            "ERC 최종 weights의 차원·유한성·양수 조건이 올바르지 않습니다."
        )
    bound_tolerance = max(config.coordinate_change_tolerance, config.outer_sum_tolerance)
    lower_violation = float(np.max(np.maximum(lowers - weights, 0.0)))
    upper_violation = float(np.max(np.maximum(weights - uppers, 0.0)))
    sum_residual = abs(float(np.sum(weights)) - 1.0)
    primal_residual = max(lower_violation, upper_violation, sum_residual)
    if lower_violation > bound_tolerance or upper_violation > bound_tolerance:
        raise ConstrainedErcKktValidationError("ERC 최종 weights가 per-asset bounds를 위반합니다.")
    if require_outer_sum and sum_residual > config.outer_sum_tolerance:
        raise ConstrainedErcKktValidationError(
            "ERC 최종 weights 합계 residual이 outer 허용오차를 넘습니다."
        )

    marginal_vector = covariance @ weights
    variance = float(weights @ marginal_vector)
    if not math.isfinite(variance) or variance <= 0:
        raise ConstrainedErcDegenerateVarianceError(
            "ERC 최종 feasible portfolio variance가 양수가 아닙니다."
        )
    sigma = math.sqrt(variance)
    marginal_risks = marginal_vector / sigma
    risk_contributions = weights * marginal_risks
    relative_contributions = risk_contributions / sigma
    if not (
        np.all(np.isfinite(marginal_risks))
        and np.all(np.isfinite(risk_contributions))
        and np.all(np.isfinite(relative_contributions))
    ):
        raise ConstrainedErcKktValidationError("ERC risk contribution 진단에 비유한 값이 있습니다.")
    euler_residual = abs(float(np.sum(risk_contributions)) - sigma)
    euler_tolerance = max(config.normalized_kkt_tolerance * sigma, 1e-14)
    if euler_residual > euler_tolerance:
        raise ConstrainedErcKktValidationError("ERC Euler identity residual이 허용오차를 넘습니다.")

    q_values = risk_contributions - lambda_value * budgets
    flags: list[ConstrainedErcBoundFlag] = []
    kkt_violations: list[float] = []
    complementarity: list[float] = []
    free_contributions: list[float] = []
    for index, q_value in enumerate(q_values):
        weight = float(weights[index])
        lower = float(lowers[index])
        upper = float(uppers[index])
        if lower > 0 and weight <= lower + bound_tolerance:
            flag = ConstrainedErcBoundFlag.LOWER
            violation = max(0.0, -float(q_value))
            multiplier = max(float(q_value) / weight, 0.0)
            complementarity_value = abs((weight - lower) * multiplier)
        elif weight >= upper - bound_tolerance:
            flag = ConstrainedErcBoundFlag.UPPER
            violation = max(0.0, float(q_value))
            multiplier = max(-float(q_value) / weight, 0.0)
            complementarity_value = abs((upper - weight) * multiplier)
        else:
            flag = ConstrainedErcBoundFlag.FREE
            violation = abs(float(q_value))
            complementarity_value = 0.0
            free_contributions.append(float(risk_contributions[index]))
        flags.append(flag)
        kkt_violations.append(violation)
        complementarity.append(complementarity_value)
    normalization_scale = max(sigma, lambda_value, _FLOAT_TINY)
    normalized_kkt = max(kkt_violations, default=0.0) / normalization_scale
    maximum_complementarity = max(complementarity, default=0.0)
    if normalized_kkt > config.normalized_kkt_tolerance:
        raise ConstrainedErcKktValidationError(
            "ERC 정규화 최대 KKT residual이 고정 허용오차를 넘습니다."
        )
    if maximum_complementarity / normalization_scale > config.normalized_kkt_tolerance:
        raise ConstrainedErcKktValidationError(
            "ERC bound complementarity residual이 고정 허용오차를 넘습니다."
        )
    free_dispersion = (
        None if not free_contributions else max(free_contributions) - min(free_contributions)
    )
    return ConstrainedErcKktDiagnostics(
        weights=tuple(_clean_float(value) for value in weights.tolist()),
        portfolio_volatility=_clean_float(sigma),
        marginal_risks=tuple(_clean_float(value) for value in marginal_risks.tolist()),
        absolute_risk_contributions=tuple(
            _clean_float(value) for value in risk_contributions.tolist()
        ),
        relative_risk_contributions=tuple(
            _clean_float(value) for value in relative_contributions.tolist()
        ),
        bound_flags=tuple(flags),
        primal_residual=_clean_float(primal_residual),
        euler_residual=_clean_float(euler_residual),
        normalized_max_kkt_residual=_clean_float(normalized_kkt),
        complementarity_residual=_clean_float(maximum_complementarity),
        free_asset_rc_dispersion=(
            None if free_dispersion is None else _clean_float(free_dispersion)
        ),
    )


def _distribute_positive_quanta(
    weights: list[Decimal],
    maximums: list[Decimal],
    order: tuple[int, ...],
    quantum: Decimal,
    steps: int,
) -> None:
    remaining = steps
    while remaining:
        progressed = False
        for index in order:
            if weights[index] + quantum <= maximums[index]:
                weights[index] += quantum
                remaining -= 1
                progressed = True
                if remaining == 0:
                    return
        if not progressed:
            raise ConstrainedErcReconciliationError(
                "남은 Decimal quantum을 upper-bound slack 안에 배분할 수 없습니다."
            )


def _remove_negative_quanta(
    weights: list[Decimal],
    minimums: list[Decimal],
    order: tuple[int, ...],
    quantum: Decimal,
    steps: int,
) -> None:
    remaining = steps
    while remaining:
        progressed = False
        for index in order:
            if weights[index] - quantum >= minimums[index]:
                weights[index] -= quantum
                remaining -= 1
                progressed = True
                if remaining == 0:
                    return
        if not progressed:
            raise ConstrainedErcReconciliationError(
                "초과 Decimal quantum을 positivity와 lower bounds 안에서 제거할 수 없습니다."
            )


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def _decimal_sum(values: tuple[Decimal, ...]) -> Decimal:
    with localcontext(Context(prec=100)):
        return sum(values, _ZERO)


def _fingerprint(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _clean_float(value: float) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ConstrainedErcKktValidationError("ERC solver 결과에 비유한 float가 있습니다.")
    return 0.0 if result == 0.0 else result


__all__ = [
    "CONSTRAINED_ERC_SOLVER_VERSION",
    "ConstrainedErcSolver",
    "fingerprint_consumed_covariance",
    "fingerprint_covariance",
    "fingerprint_solver_config",
    "reconcile_decimal_weights",
    "solve_constrained_erc",
]
