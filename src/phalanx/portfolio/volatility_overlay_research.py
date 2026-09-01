"""Four-scenario volatility overlays on unchanged constrained-ERC sleeves."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from uuid import uuid4

from phalanx.domain import (
    SCENARIO_KIND_ORDER,
    AllocationBacktestConfig,
    AllocationTarget,
    ConstrainedErcOutcomeStatus,
    ConstrainedErcSolverConfig,
    DynamicRiskModelConfig,
    VolatilityOverlayConfig,
    VolatilityOverlayFailure,
    VolatilityOverlayOutcomeStatus,
    VolatilityOverlayPolicyOutcome,
    VolatilityOverlayResearchStatus,
    VolatilityOverlayResearchTrial,
    VolatilityOverlayTarget,
    overlay_policy_id,
)
from phalanx.market_data.service import StockDailyBars
from phalanx.portfolio.allocation_backtest import (
    ScheduledAllocationTarget,
    run_allocation_backtest_with_dynamic_targets,
)
from phalanx.portfolio.constrained_erc_research import (
    ConstrainedErcRiskEstimator,
    ConstrainedErcScenarioSolver,
    conduct_constrained_erc_research,
)
from phalanx.portfolio.errors import (
    AllocationSelfFinancingError,
    InvalidAllocationTargetError,
    InvalidVolatilityOverlayDomainError,
    VolatilityOverlayResearchError,
)
from phalanx.portfolio.volatility_overlay import apply_volatility_overlay
from phalanx.portfolio.volatility_overlay_trial_registry import (
    fingerprint_volatility_overlay_config,
    fingerprint_volatility_overlay_trial,
)

_ZERO = Decimal(0)
_SOURCE_TRIAL_ID = "volatility_overlay_source"


def conduct_volatility_overlay_research(
    histories: Sequence[StockDailyBars],
    requested_start: date,
    requested_end: date,
    *,
    target_annual_volatility: Decimal,
    annual_cash_yield: Decimal = _ZERO,
    allocation_config: AllocationBacktestConfig | None = None,
    risk_model_config: DynamicRiskModelConfig | None = None,
    solver_config: ConstrainedErcSolverConfig | None = None,
    estimator: ConstrainedErcRiskEstimator | None = None,
    solver: ConstrainedErcScenarioSolver | None = None,
    trial_id_factory: Callable[[], str] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> VolatilityOverlayResearchTrial:
    """Run the existing ERC research, then scale each successful sleeve independently."""

    if type(requested_start) is not date or type(requested_end) is not date:
        raise VolatilityOverlayResearchError("volatility overlay 요청기간은 date 값이어야 합니다.")
    if requested_start > requested_end:
        raise VolatilityOverlayResearchError(
            "volatility overlay 시작일은 종료일보다 늦을 수 없습니다."
        )
    overlay_config = VolatilityOverlayConfig(
        target_annual_volatility=target_annual_volatility,
        annual_cash_yield=annual_cash_yield,
    )
    trial_id = uuid4().hex if trial_id_factory is None else trial_id_factory()
    executed_at = datetime.now(UTC) if clock is None else clock()
    source_trial = conduct_constrained_erc_research(
        histories,
        requested_start,
        requested_end,
        allocation_config=allocation_config,
        risk_model_config=risk_model_config,
        solver_config=solver_config,
        estimator=estimator,
        solver=solver,
        trial_id_factory=lambda: _SOURCE_TRIAL_ID,
        clock=lambda: executed_at,
    )
    policy_outcomes = _build_policy_outcomes(source_trial, overlay_config)
    config_fingerprint = fingerprint_volatility_overlay_config(
        source_trial,
        overlay_config,
    )
    trial_fingerprint = fingerprint_volatility_overlay_trial(
        source_trial_fingerprint=source_trial.trial_fingerprint,
        config_fingerprint=config_fingerprint,
        signal_dates=source_trial.signal_dates,
        execution_dates=source_trial.execution_dates,
        policy_outcomes=policy_outcomes,
    )
    successful_results = tuple(
        outcome.result for outcome in policy_outcomes if outcome.result is not None
    )
    status = (
        VolatilityOverlayResearchStatus.SUCCEEDED
        if all(
            outcome.status is VolatilityOverlayOutcomeStatus.SUCCEEDED
            for outcome in policy_outcomes
        )
        else VolatilityOverlayResearchStatus.FAILED
    )
    return VolatilityOverlayResearchTrial(
        trial_id=trial_id,
        status=status,
        executed_at=executed_at,
        requested_start=requested_start,
        requested_end=requested_end,
        actual_evaluation_start=(
            None if not successful_results else successful_results[0].dates[0]
        ),
        actual_evaluation_end=(None if not successful_results else successful_results[0].dates[-1]),
        source_trial=source_trial,
        overlay_config=overlay_config,
        policy_outcomes=policy_outcomes,
        config_fingerprint=config_fingerprint,
        trial_fingerprint=trial_fingerprint,
        provenance=source_trial.provenance,
    )


def _build_policy_outcomes(
    source_trial: object,
    overlay_config: VolatilityOverlayConfig,
) -> tuple[VolatilityOverlayPolicyOutcome, ...]:
    from phalanx.domain import ConstrainedErcResearchTrial

    if not isinstance(source_trial, ConstrainedErcResearchTrial):
        raise VolatilityOverlayResearchError(
            "source research가 ConstrainedErcResearchTrial을 반환하지 않았습니다."
        )
    source_outcomes = source_trial.policy_outcomes[:4]
    outcomes: list[VolatilityOverlayPolicyOutcome] = []
    for scenario_kind, source_outcome in zip(
        SCENARIO_KIND_ORDER,
        source_outcomes,
        strict=True,
    ):
        policy_id = overlay_policy_id(scenario_kind)
        targets: list[VolatilityOverlayTarget] = []
        target_failure: VolatilityOverlayFailure | None = None
        for source_target in source_outcome.erc_targets:
            try:
                target = apply_volatility_overlay(source_target, overlay_config)
            except Exception as error:
                target_failure = safe_volatility_overlay_failure(
                    error,
                    as_of_date=source_target.as_of_date,
                    scenario_kind=scenario_kind,
                )
                break
            targets.append(target)
        if target_failure is not None:
            outcomes.append(
                VolatilityOverlayPolicyOutcome(
                    policy_id=policy_id,
                    status=VolatilityOverlayOutcomeStatus.FAILED,
                    overlay_targets=tuple(targets),
                    failure=target_failure,
                )
            )
            continue
        if source_outcome.status is ConstrainedErcOutcomeStatus.FAILED:
            source_common_failure = source_trial.common_failure is not None
            outcomes.append(
                VolatilityOverlayPolicyOutcome(
                    policy_id=policy_id,
                    status=VolatilityOverlayOutcomeStatus.FAILED,
                    overlay_targets=tuple(targets),
                    failure=VolatilityOverlayFailure(
                        code=(
                            "volatility_overlay_source_common_failure"
                            if source_common_failure
                            else "volatility_overlay_source_erc_failure"
                        ),
                        message=(
                            "Constrained ERC 공통 입력 실패로 overlay를 실행하지 않았습니다."
                            if source_common_failure
                            else "해당 covariance scenario의 Constrained ERC가 실패하여 "
                            "overlay를 실행하지 않았습니다."
                        ),
                        as_of_date=(
                            None
                            if source_outcome.failure is None
                            else source_outcome.failure.as_of_date
                        ),
                        scenario_kind=(None if source_common_failure else scenario_kind),
                    ),
                )
            )
            continue
        try:
            schedule = _build_dynamic_schedule(source_trial, tuple(targets))
            if source_trial.price_panel is None:
                raise InvalidAllocationTargetError(
                    "성공 source ERC trial에 공통 가격 패널이 없습니다."
                )
            result = run_allocation_backtest_with_dynamic_targets(
                source_trial.price_panel,
                policy_id,
                schedule,
                source_trial.allocation_config,
                annual_cash_yield=overlay_config.annual_cash_yield,
            )
        except Exception as error:
            outcomes.append(
                VolatilityOverlayPolicyOutcome(
                    policy_id=policy_id,
                    status=VolatilityOverlayOutcomeStatus.FAILED,
                    overlay_targets=tuple(targets),
                    failure=safe_volatility_overlay_failure(
                        error,
                        scenario_kind=scenario_kind,
                    ),
                )
            )
        else:
            outcomes.append(
                VolatilityOverlayPolicyOutcome(
                    policy_id=policy_id,
                    status=VolatilityOverlayOutcomeStatus.SUCCEEDED,
                    overlay_targets=tuple(targets),
                    result=result,
                )
            )
    return tuple(outcomes)


def _build_dynamic_schedule(
    source_trial: object,
    overlay_targets: tuple[VolatilityOverlayTarget, ...],
) -> tuple[ScheduledAllocationTarget, ...]:
    from phalanx.domain import ConstrainedErcResearchTrial

    if not isinstance(source_trial, ConstrainedErcResearchTrial):
        raise InvalidAllocationTargetError(
            "동적 overlay 일정의 source trial 타입이 올바르지 않습니다."
        )
    panel = source_trial.price_panel
    if panel is None or len(overlay_targets) != len(source_trial.signal_dates):
        raise InvalidAllocationTargetError(
            "overlay target schedule이 source signal schedule 전체와 일치하지 않습니다."
        )
    panel_positions = {value: index for index, value in enumerate(panel.dates)}
    scheduled: list[ScheduledAllocationTarget] = []
    for overlay_target, signal_date, execution_date in zip(
        overlay_targets,
        source_trial.signal_dates,
        source_trial.execution_dates,
        strict=True,
    ):
        if overlay_target.as_of_date != signal_date:
            raise InvalidAllocationTargetError(
                "overlay target as-of가 source signal date와 일치하지 않습니다."
            )
        try:
            execution_index = panel_positions[execution_date]
        except KeyError:
            raise InvalidAllocationTargetError(
                "source next-common-open 체결일이 가격 패널에 없습니다."
            ) from None
        # Overlay weights retain the source quantum and a 50-digit scalar, so
        # construction needs a wider context than the execution engine itself.
        with localcontext(Context(prec=100, rounding=ROUND_HALF_EVEN)):
            allocation_target = AllocationTarget(
                signal_date=signal_date,
                stock_codes=overlay_target.stock_codes,
                target_weights=overlay_target.target_weights,
                policy_id=overlay_target.policy_id,
                target_equity_weight=overlay_target.target_equity_weight,
            )
        scheduled.append(
            ScheduledAllocationTarget(
                execution_index=execution_index,
                target=allocation_target,
            )
        )
    return tuple(scheduled)


def safe_volatility_overlay_failure(
    error: Exception,
    *,
    as_of_date: date | None = None,
    scenario_kind: object | None = None,
) -> VolatilityOverlayFailure:
    """Map arbitrary exceptions to fixed messages without persisting exception data."""

    from phalanx.domain import CovarianceScenarioKind

    selected_scenario = scenario_kind if isinstance(scenario_kind, CovarianceScenarioKind) else None
    selected_as_of_date = as_of_date
    if selected_as_of_date is None and isinstance(error, AllocationSelfFinancingError):
        error_as_of_date = error.as_of_date
        if type(error_as_of_date) is date:
            selected_as_of_date = error_as_of_date
    code = "volatility_overlay_calculation_error"
    message = "volatility overlay 정책 계산을 완료하지 못했습니다."
    if isinstance(error, InvalidVolatilityOverlayDomainError):
        code = "volatility_overlay_invalid_forecast"
        message = "양의 유한한 forecast 연환산변동성이 없어 overlay를 계산하지 못했습니다."
    elif isinstance(error, AllocationSelfFinancingError):
        code = "volatility_overlay_self_financing_failure"
        message = "동적 주식·현금 자기금융 backtest를 완료하지 못했습니다."
    elif isinstance(error, InvalidAllocationTargetError):
        code = "volatility_overlay_schedule_mismatch"
        message = "overlay target과 source signal·next-open 일정이 일치하지 않습니다."
    return VolatilityOverlayFailure(
        code=code,
        message=message,
        as_of_date=selected_as_of_date,
        scenario_kind=selected_scenario,
    )


__all__ = [
    "conduct_volatility_overlay_research",
    "safe_volatility_overlay_failure",
]
