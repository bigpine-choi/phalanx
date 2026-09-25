"""One prepared matrix, one risk snapshot, four independent fixed ERC scenarios."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal, localcontext
from typing import Literal

from phalanx.decimal_math import financial_decimal_context
from phalanx.domain.allocation_input import AllocationInput
from phalanx.domain.allocation_targets import (
    AllocationTargetFailure,
    AllocationTargets,
    ScenarioAllocationTarget,
)
from phalanx.domain.constrained_erc import ConstrainedErcSolverConfig, ConstrainedErcTarget
from phalanx.domain.portfolio import AlignedReturnMatrix
from phalanx.domain.risk_model import (
    SCENARIO_KIND_ORDER,
    CovarianceScenario,
    CovarianceScenarioKind,
    DynamicRiskModelConfig,
    DynamicRiskModelSnapshot,
)
from phalanx.portfolio.allocation_targets.errors import AllocationTargetsContractError
from phalanx.portfolio.constrained_erc import (
    ConstrainedErcSolver,
    fingerprint_consumed_covariance,
    fingerprint_solver_config,
)
from phalanx.portfolio.constrained_erc_research import (
    ConstrainedErcRiskEstimator,
    ConstrainedErcScenarioSolver,
    safe_constrained_erc_failure,
)
from phalanx.portfolio.constrained_erc_trial_registry import _erc_target_payload, _snapshot_payload
from phalanx.portfolio.dynamic_risk_model import DynamicRiskModel, fingerprint_consumed_risk_input
from phalanx.portfolio.errors import (
    ConstrainedErcResearchError,
    ConstrainedErcTrialSerializationError,
    RiskModelError,
)
from phalanx.portfolio.risk_model_research import (
    current_risk_model_provenance,
    fingerprint_risk_model_config,
)


def _failure(
    error: Exception,
    stage: Literal["input_contract", "risk_snapshot", "scenario"],
    calculation_date: date | None,
    kind: CovarianceScenarioKind | None = None,
) -> AllocationTargetFailure:
    category: Literal["calculation", "contract", "unexpected"]
    if isinstance(error, AllocationTargetsContractError):
        category = "contract"
    elif isinstance(error, (RiskModelError, ConstrainedErcResearchError)):
        category = "calculation"
    else:
        category = "unexpected"
    return AllocationTargetFailure(
        stage=stage,
        category=category,
        failure=safe_constrained_erc_failure(
            error, as_of_date=calculation_date, scenario_kind=kind
        ),
    )


def _validate_prepared(prepared: AllocationInput) -> AlignedReturnMatrix:
    matrix = prepared.matrix
    if (
        not isinstance(matrix, AlignedReturnMatrix)
        or prepared.used_end is None
        or not prepared.used_end == prepared.reference_price_date == matrix.dates[-1]
        or matrix.stock_codes != prepared.selected_codes
        or prepared.return_observation_count != len(matrix.dates)
    ):
        raise AllocationTargetsContractError("준비 행렬의 날짜·종목 순서·관측 수가 모순됩니다.")
    return matrix


def _validate_snapshot(
    snapshot: DynamicRiskModelSnapshot,
    matrix: AlignedReturnMatrix,
    calculation_date: date,
    input_fingerprint: str,
) -> None:
    if not isinstance(snapshot, DynamicRiskModelSnapshot):
        raise AllocationTargetsContractError("위험모형 반환 타입이 올바르지 않습니다.")
    if (
        snapshot.as_of_date != calculation_date
        or snapshot.stock_codes != matrix.stock_codes
        or snapshot.consumed_dates != matrix.dates
        or snapshot.consumed_input_fingerprint != input_fingerprint
    ):
        raise AllocationTargetsContractError("위험 snapshot의 날짜·종목·소비 입력이 다릅니다.")
    # Re-run existing immutable domain/JSON checks at the injected engine boundary.
    try:
        replace(snapshot)
        for scenario in snapshot.scenarios:
            replace(scenario)
            replace(scenario.metadata)
            replace(scenario.psd_diagnostics)
        _snapshot_payload(snapshot)
    except (RiskModelError, ConstrainedErcTrialSerializationError, TypeError, ValueError):
        raise AllocationTargetsContractError(
            "위험 snapshot의 구조·수치 근거가 유효하지 않습니다."
        ) from None


def _validate_target(
    target: ConstrainedErcTarget,
    scenario: CovarianceScenario,
    calculation_date: date,
    covariance_fingerprint: str,
    solver_fingerprint: str,
) -> None:
    if not isinstance(target, ConstrainedErcTarget):
        raise AllocationTargetsContractError("ERC 반환 타입이 올바르지 않습니다.")
    if (
        target.as_of_date != calculation_date
        or target.stock_codes != scenario.stock_codes
        or target.scenario_kind != scenario.kind
        or target.covariance_fingerprint != covariance_fingerprint
        or target.solver_config_fingerprint != solver_fingerprint
        or any(value != Decimal(0) for value in target.lower_bounds)
        or any(value != Decimal("0.20") for value in target.upper_bounds)
    ):
        raise AllocationTargetsContractError(
            "ERC 목표의 날짜·종목·scenario·bounds·fingerprint가 다릅니다."
        )
    try:
        replace(target)
        replace(target.diagnostics_before_reconciliation)
        replace(target.diagnostics_after_reconciliation)
        _erc_target_payload(target)
    except (
        ConstrainedErcResearchError,
        ConstrainedErcTrialSerializationError,
        TypeError,
        ValueError,
    ):
        raise AllocationTargetsContractError(
            "ERC 목표의 구조·수치 근거가 유효하지 않습니다."
        ) from None
    # Budgets are created by solve_scenario's existing default. Never regenerate
    # 1/N here: its last exact residual deliberately uses a different precision.


def calculate_allocation_targets(
    prepared: AllocationInput,
    *,
    estimator: ConstrainedErcRiskEstimator | None = None,
    solver: ConstrainedErcScenarioSolver | None = None,
) -> AllocationTargets:
    """Calculate one observation endpoint; injected engines are test boundaries only."""
    with localcontext(financial_decimal_context()):
        return _calculate(prepared, estimator, solver)


def _calculate(
    prepared: AllocationInput,
    estimator: ConstrainedErcRiskEstimator | None,
    solver: ConstrainedErcScenarioSolver | None,
) -> AllocationTargets:
    risk_config = DynamicRiskModelConfig()
    solver_config = ConstrainedErcSolverConfig()
    provenance = current_risk_model_provenance()
    risk_config_hash = fingerprint_risk_model_config(risk_config)
    solver_hash = fingerprint_solver_config(solver_config)
    calculation_date = prepared.used_end if prepared.input_ready else None
    input_hash: str | None = None
    snapshot: DynamicRiskModelSnapshot | None = None
    common_failure: AllocationTargetFailure | None = None
    outcomes = tuple(ScenarioAllocationTarget(kind, "not_run") for kind in SCENARIO_KIND_ORDER)
    status: Literal["input_unavailable", "common_failure", "succeeded", "partial", "failed"]
    status = "input_unavailable"
    if prepared.input_ready:
        stage: Literal["input_contract", "risk_snapshot"] = "input_contract"
        try:
            matrix = _validate_prepared(prepared)
            assert calculation_date is not None
            input_hash = fingerprint_consumed_risk_input(
                matrix.stock_codes, matrix.dates, matrix.values, risk_config
            )
            stage = "risk_snapshot"
            risk_engine = DynamicRiskModel() if estimator is None else estimator
            candidate_snapshot = risk_engine.estimate(matrix, as_of_date=calculation_date)
            _validate_snapshot(candidate_snapshot, matrix, calculation_date, input_hash)
            snapshot = candidate_snapshot
        except Exception as error:
            common_failure = _failure(error, stage, calculation_date)
            status = "common_failure"
        if snapshot is not None:
            assert calculation_date is not None
            # Instantiate only after successful input/risk preparation. The default
            # engines and their fixed settings receive no policy overrides.
            try:
                scenario_solver = ConstrainedErcSolver() if solver is None else solver
            except Exception as error:
                outcomes = tuple(
                    ScenarioAllocationTarget(
                        kind, "failed", failure=_failure(error, "scenario", calculation_date, kind)
                    )
                    for kind in SCENARIO_KIND_ORDER
                )
            else:
                outcomes = tuple(
                    _solve_one(
                        snapshot.get_scenario(kind),
                        calculation_date,
                        scenario_solver,
                        risk_config,
                        solver_hash,
                    )
                    for kind in SCENARIO_KIND_ORDER
                )
            succeeded = sum(outcome.status == "succeeded" for outcome in outcomes)
            status = "succeeded" if succeeded == 4 else "partial" if succeeded else "failed"
    return AllocationTargets(
        status=status,
        prepared=prepared,
        calculation_date=calculation_date,
        risk_config=risk_config,
        solver_config=solver_config,
        library_provenance=provenance,
        risk_config_fingerprint=risk_config_hash,
        solver_config_fingerprint=solver_hash,
        risk_input_fingerprint=input_hash,
        risk_snapshot=snapshot,
        common_failure=common_failure,
        scenarios=outcomes,
    )


def _solve_one(
    scenario: CovarianceScenario,
    calculation_date: date,
    solver: ConstrainedErcScenarioSolver,
    risk_config: DynamicRiskModelConfig,
    solver_hash: str,
) -> ScenarioAllocationTarget:
    covariance_hash: str | None = None
    try:
        covariance_hash = fingerprint_consumed_covariance(
            scenario.annualized_covariance, scenario.stock_codes, psd_config=risk_config
        )
        target = solver.solve_scenario(scenario, as_of_date=calculation_date)
        _validate_target(target, scenario, calculation_date, covariance_hash, solver_hash)
        return ScenarioAllocationTarget(scenario.kind, "succeeded", covariance_hash, target)
    except Exception as error:
        return ScenarioAllocationTarget(
            scenario_kind=scenario.kind,
            status="failed",
            covariance_fingerprint=covariance_hash,
            failure=_failure(error, "scenario", calculation_date, scenario.kind),
        )
