"""Shared-schedule orchestration for four ERC scenarios and three controls."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from decimal import Context, Decimal, localcontext
from typing import Protocol
from uuid import uuid4

from phalanx.domain import (
    CONSTRAINED_ERC_CONTROL_POLICY_IDS,
    CONSTRAINED_ERC_POLICY_ORDER,
    SCENARIO_KIND_ORDER,
    AlignedPricePanel,
    AlignedReturnMatrix,
    AllocationBacktestConfig,
    AllocationTarget,
    ConstrainedErcCommonFailure,
    ConstrainedErcCommonFailureStage,
    ConstrainedErcFailure,
    ConstrainedErcOutcomeStatus,
    ConstrainedErcPolicyOutcome,
    ConstrainedErcResearchStatus,
    ConstrainedErcResearchTrial,
    ConstrainedErcRiskSnapshotOutcome,
    ConstrainedErcSolverConfig,
    ConstrainedErcTarget,
    CovarianceScenario,
    DynamicRiskModelConfig,
    DynamicRiskModelSnapshot,
    scenario_policy_id,
)
from phalanx.market_data.service import StockDailyBars
from phalanx.portfolio._allocation_schedule import (
    AllocationSignalWindow,
    build_price_panel_return_matrix,
    build_return_matrix_signal_windows,
)
from phalanx.portfolio.allocation_backtest import (
    ScheduledAllocationTarget,
    build_allocation_target_schedule,
    run_allocation_backtest_with_targets,
)
from phalanx.portfolio.allocation_data import build_aligned_price_panel
from phalanx.portfolio.allocation_policies import (
    AllocationPolicy,
    default_allocation_policies,
)
from phalanx.portfolio.constrained_erc import (
    ConstrainedErcSolver,
    fingerprint_consumed_covariance,
    fingerprint_solver_config,
)
from phalanx.portfolio.constrained_erc_trial_registry import (
    fingerprint_constrained_erc_config,
    fingerprint_constrained_erc_covariances,
    fingerprint_constrained_erc_market_data,
    fingerprint_constrained_erc_trial,
)
from phalanx.portfolio.dynamic_risk_model import DynamicRiskModel
from phalanx.portfolio.errors import (
    AllocationSelfFinancingError,
    ConstrainedErcBisectionConvergenceError,
    ConstrainedErcCcdConvergenceError,
    ConstrainedErcDegenerateVarianceError,
    ConstrainedErcDuplicateRiskSnapshotError,
    ConstrainedErcInfeasibleBoundsError,
    ConstrainedErcInvalidCovarianceError,
    ConstrainedErcKktValidationError,
    ConstrainedErcLambdaBracketError,
    ConstrainedErcMissingRiskSnapshotError,
    ConstrainedErcReconciliationError,
    ConstrainedErcResearchError,
    ConstrainedErcScenarioScheduleError,
    RiskModelError,
)
from phalanx.portfolio.risk_model_research import current_risk_model_provenance

_ZERO = Decimal(0)
_ONE = Decimal(1)
_PRODUCTION_UPPER_BOUND = Decimal("0.20")


class ConstrainedErcScenarioSolver(Protocol):
    """Injectable solver boundary for deterministic failure and orchestration tests."""

    def solve_scenario(
        self,
        scenario: CovarianceScenario,
        *,
        as_of_date: date,
        risk_budgets: tuple[Decimal, ...] | None = None,
        lower_bounds: tuple[Decimal, ...] | None = None,
        upper_bounds: tuple[Decimal, ...] | None = None,
    ) -> ConstrainedErcTarget: ...


class ConstrainedErcRiskEstimator(Protocol):
    """Causal exact-window risk snapshot boundary."""

    def estimate(
        self,
        matrix: AlignedReturnMatrix,
        *,
        as_of_date: date,
    ) -> DynamicRiskModelSnapshot: ...


def conduct_constrained_erc_research(
    histories: Sequence[StockDailyBars],
    requested_start: date,
    requested_end: date,
    *,
    allocation_config: AllocationBacktestConfig | None = None,
    risk_model_config: DynamicRiskModelConfig | None = None,
    solver_config: ConstrainedErcSolverConfig | None = None,
    estimator: ConstrainedErcRiskEstimator | None = None,
    solver: ConstrainedErcScenarioSolver | None = None,
    control_policies: tuple[AllocationPolicy, ...] | None = None,
    trial_id_factory: Callable[[], str] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> ConstrainedErcResearchTrial:
    """Build one panel/schedule/risk sequence, then judge seven fixed policies."""

    if type(requested_start) is not date or type(requested_end) is not date:
        raise ConstrainedErcResearchError("Constrained ERC 요청기간은 date 값이어야 합니다.")
    if requested_start > requested_end:
        raise ConstrainedErcResearchError("Constrained ERC 시작일은 종료일보다 늦을 수 없습니다.")
    selected_allocation_config = (
        AllocationBacktestConfig(target_equity_weight=_ONE)
        if allocation_config is None
        else allocation_config
    )
    selected_risk_config = (
        DynamicRiskModelConfig() if risk_model_config is None else risk_model_config
    )
    selected_solver_config = (
        ConstrainedErcSolverConfig() if solver_config is None else solver_config
    )
    _validate_shared_config(selected_allocation_config, selected_risk_config)
    selected_estimator = DynamicRiskModel(selected_risk_config) if estimator is None else estimator
    selected_solver = (
        ConstrainedErcSolver(selected_solver_config, psd_config=selected_risk_config)
        if solver is None
        else solver
    )
    selected_controls = (
        default_allocation_policies() if control_policies is None else control_policies
    )
    if (
        tuple(policy.policy_id for policy in selected_controls)
        != CONSTRAINED_ERC_CONTROL_POLICY_IDS
    ):
        raise ConstrainedErcScenarioScheduleError(
            "control policies는 기존 세 정책의 고정 순서와 정확히 일치해야 합니다."
        )

    trial_id = uuid4().hex if trial_id_factory is None else trial_id_factory()
    executed_at = datetime.now(UTC) if clock is None else clock()
    config_fingerprint = fingerprint_constrained_erc_config(
        selected_allocation_config,
        selected_risk_config,
        selected_solver_config,
    )
    histories_tuple = tuple(histories)
    stock_codes = _unique_stock_codes(histories_tuple)
    try:
        panel = build_aligned_price_panel(
            histories_tuple,
            minimum_common_observations=(selected_allocation_config.minimum_training_returns + 2),
        )
        matrix = build_price_panel_return_matrix(panel)
        windows = build_return_matrix_signal_windows(
            matrix,
            minimum_observations=selected_allocation_config.minimum_training_returns,
            maximum_observations=selected_allocation_config.maximum_training_returns,
            rebalance_interval=selected_allocation_config.rebalance_interval,
        )
        _validate_shared_schedule(panel, matrix, windows)
    except Exception as error:
        return _failed_input_trial(
            trial_id=trial_id,
            executed_at=executed_at,
            requested_start=requested_start,
            requested_end=requested_end,
            stock_codes=stock_codes,
            allocation_config=selected_allocation_config,
            risk_model_config=selected_risk_config,
            solver_config=selected_solver_config,
            config_fingerprint=config_fingerprint,
            error=error,
        )

    signal_dates = tuple(window.policy_input.signal_date for window in windows)
    execution_dates = tuple(panel.dates[window.as_of_index + 2] for window in windows)
    risk_outcomes = _build_risk_snapshot_outcomes(
        matrix,
        windows,
        selected_estimator,
    )
    policy_outcomes = (
        *_build_erc_policy_outcomes(
            panel,
            windows,
            risk_outcomes,
            selected_solver,
            selected_allocation_config,
            selected_solver_config,
            selected_risk_config,
        ),
        *_build_control_policy_outcomes(
            panel,
            windows,
            selected_controls,
            selected_allocation_config,
        ),
    )
    if tuple(outcome.policy_id for outcome in policy_outcomes) != CONSTRAINED_ERC_POLICY_ORDER:
        raise ConstrainedErcScenarioScheduleError("7개 정책 결과의 고정 순서가 훼손되었습니다.")
    market_fingerprint = fingerprint_constrained_erc_market_data(
        panel.stock_codes,
        panel,
        matrix,
    )
    covariance_fingerprint = fingerprint_constrained_erc_covariances(risk_outcomes)
    trial_fingerprint = fingerprint_constrained_erc_trial(
        config_fingerprint=config_fingerprint,
        market_data_fingerprint=market_fingerprint,
        covariance_fingerprint=covariance_fingerprint,
        signal_dates=signal_dates,
        execution_dates=execution_dates,
        policy_outcomes=policy_outcomes,
    )
    successful_results = tuple(
        outcome.result for outcome in policy_outcomes if outcome.result is not None
    )
    status = (
        ConstrainedErcResearchStatus.SUCCEEDED
        if all(
            outcome.status is ConstrainedErcOutcomeStatus.SUCCEEDED for outcome in policy_outcomes
        )
        else ConstrainedErcResearchStatus.FAILED
    )
    return ConstrainedErcResearchTrial(
        trial_id=trial_id,
        status=status,
        executed_at=executed_at,
        requested_start=requested_start,
        requested_end=requested_end,
        actual_evaluation_start=(
            None if not successful_results else successful_results[0].dates[0]
        ),
        actual_evaluation_end=(None if not successful_results else successful_results[0].dates[-1]),
        stock_codes=panel.stock_codes,
        price_panel=panel,
        aligned_returns=matrix,
        allocation_config=selected_allocation_config,
        risk_model_config=selected_risk_config,
        solver_config=selected_solver_config,
        signal_dates=signal_dates,
        execution_dates=execution_dates,
        risk_snapshot_outcomes=risk_outcomes,
        policy_outcomes=policy_outcomes,
        config_fingerprint=config_fingerprint,
        market_data_fingerprint=market_fingerprint,
        covariance_fingerprint=covariance_fingerprint,
        trial_fingerprint=trial_fingerprint,
        provenance=current_risk_model_provenance(),
    )


def _validate_shared_config(
    allocation_config: AllocationBacktestConfig,
    risk_config: DynamicRiskModelConfig,
) -> None:
    if allocation_config.target_equity_weight != _ONE:
        raise ConstrainedErcScenarioScheduleError(
            "Constrained ERC 7정책 비교의 목표 주식비중은 정확히 1이어야 합니다."
        )
    if (
        allocation_config.minimum_training_returns != risk_config.minimum_observations
        or allocation_config.maximum_training_returns != risk_config.maximum_observations
        or allocation_config.rebalance_interval != risk_config.rebalance_interval
        or allocation_config.annualization_trading_days != risk_config.annualization_days
    ):
        raise ConstrainedErcScenarioScheduleError(
            "allocation과 risk-model의 학습·rolling·리밸런싱·연환산 설정이 일치해야 합니다."
        )


def _validate_shared_schedule(
    panel: AlignedPricePanel,
    matrix: AlignedReturnMatrix,
    windows: tuple[AllocationSignalWindow, ...],
) -> None:
    if not windows:
        raise ConstrainedErcScenarioScheduleError(
            "Constrained ERC 연구에 실행 가능한 shared signal date가 없습니다."
        )
    seen_dates: set[date] = set()
    for expected_number, window in enumerate(windows):
        policy_input = window.policy_input
        if policy_input.signal_number != expected_number:
            raise ConstrainedErcScenarioScheduleError("shared signal 번호가 연속적이지 않습니다.")
        if policy_input.stock_codes != panel.stock_codes or matrix.stock_codes != panel.stock_codes:
            raise ConstrainedErcScenarioScheduleError(
                "shared schedule의 종목 순서가 가격 패널 등록 순서와 다릅니다."
            )
        if policy_input.signal_date in seen_dates:
            raise ConstrainedErcDuplicateRiskSnapshotError(
                "shared schedule에 중복 signal date가 있습니다."
            )
        if panel.dates[window.as_of_index + 1] != policy_input.signal_date:
            raise ConstrainedErcScenarioScheduleError(
                "return as-of와 가격 패널 signal date의 index가 일치하지 않습니다."
            )
        if window.as_of_index + 2 >= len(panel.dates):
            raise ConstrainedErcScenarioScheduleError(
                "shared signal date 다음 공통 거래일 시가가 없습니다."
            )
        seen_dates.add(policy_input.signal_date)


def _build_risk_snapshot_outcomes(
    matrix: AlignedReturnMatrix,
    windows: tuple[AllocationSignalWindow, ...],
    estimator: ConstrainedErcRiskEstimator,
) -> tuple[ConstrainedErcRiskSnapshotOutcome, ...]:
    outcomes: list[ConstrainedErcRiskSnapshotOutcome] = []
    returned_as_of_dates: set[date] = set()
    for window in windows:
        policy_input = window.policy_input
        visible_matrix = AlignedReturnMatrix(
            stock_codes=matrix.stock_codes,
            dates=policy_input.return_dates,
            values=policy_input.return_values,
        )
        try:
            snapshot = estimator.estimate(
                visible_matrix,
                as_of_date=policy_input.signal_date,
            )
            _validate_exact_snapshot(
                snapshot,
                visible_matrix,
                policy_input.signal_date,
                returned_as_of_dates,
            )
        except Exception as error:
            outcomes.append(
                ConstrainedErcRiskSnapshotOutcome(
                    as_of_date=policy_input.signal_date,
                    status=ConstrainedErcOutcomeStatus.FAILED,
                    failure=safe_constrained_erc_failure(
                        error,
                        as_of_date=policy_input.signal_date,
                    ),
                )
            )
        else:
            returned_as_of_dates.add(snapshot.as_of_date)
            outcomes.append(
                ConstrainedErcRiskSnapshotOutcome(
                    as_of_date=policy_input.signal_date,
                    status=ConstrainedErcOutcomeStatus.SUCCEEDED,
                    snapshot=snapshot,
                )
            )
    return tuple(outcomes)


def _validate_exact_snapshot(
    snapshot: DynamicRiskModelSnapshot,
    visible_matrix: AlignedReturnMatrix,
    expected_as_of: date,
    returned_as_of_dates: set[date],
) -> None:
    if not isinstance(snapshot, DynamicRiskModelSnapshot):
        raise ConstrainedErcScenarioScheduleError(
            "위험 estimator가 DynamicRiskModelSnapshot을 반환하지 않았습니다."
        )
    if snapshot.as_of_date in returned_as_of_dates:
        raise ConstrainedErcDuplicateRiskSnapshotError(
            "동일 as-of의 위험 snapshot이 중복 생성되었습니다."
        )
    if snapshot.as_of_date != expected_as_of:
        raise ConstrainedErcScenarioScheduleError(
            "위험 snapshot as-of가 shared signal date와 정확히 일치하지 않습니다."
        )
    if snapshot.stock_codes != visible_matrix.stock_codes:
        raise ConstrainedErcScenarioScheduleError(
            "위험 snapshot 종목 순서가 유니버스 등록 순서와 일치하지 않습니다."
        )
    if snapshot.consumed_dates != visible_matrix.dates:
        raise ConstrainedErcScenarioScheduleError(
            "위험 snapshot이 shared rolling window와 다른 날짜를 소비했습니다."
        )
    if any(scenario.stock_codes != visible_matrix.stock_codes for scenario in snapshot.scenarios):
        raise ConstrainedErcScenarioScheduleError(
            "covariance scenario 종목 순서가 shared rolling window와 다릅니다."
        )


def _build_erc_policy_outcomes(
    panel: AlignedPricePanel,
    windows: tuple[AllocationSignalWindow, ...],
    risk_outcomes: tuple[ConstrainedErcRiskSnapshotOutcome, ...],
    solver: ConstrainedErcScenarioSolver,
    config: AllocationBacktestConfig,
    solver_config: ConstrainedErcSolverConfig,
    risk_config: DynamicRiskModelConfig,
) -> tuple[ConstrainedErcPolicyOutcome, ...]:
    results: list[ConstrainedErcPolicyOutcome] = []
    lower_bounds = tuple(_ZERO for _ in panel.stock_codes)
    upper_bounds = tuple(_PRODUCTION_UPPER_BOUND for _ in panel.stock_codes)
    for scenario_kind in SCENARIO_KIND_ORDER:
        policy_id = scenario_policy_id(scenario_kind)
        targets: list[ConstrainedErcTarget] = []
        failure: ConstrainedErcFailure | None = None
        for window, risk_outcome in zip(windows, risk_outcomes, strict=True):
            as_of_date = window.policy_input.signal_date
            if risk_outcome.snapshot is None:
                error = ConstrainedErcMissingRiskSnapshotError(
                    "exact signal-date 위험 snapshot이 없어 ERC target을 만들 수 없습니다."
                )
                failure = safe_constrained_erc_failure(
                    error,
                    as_of_date=as_of_date,
                    scenario_kind=scenario_kind,
                )
                break
            try:
                scenario = risk_outcome.snapshot.get_scenario(scenario_kind)
                target = solver.solve_scenario(
                    scenario,
                    as_of_date=as_of_date,
                    lower_bounds=lower_bounds,
                    upper_bounds=upper_bounds,
                )
                _validate_exact_erc_target(
                    target,
                    policy_id,
                    scenario_kind,
                    as_of_date,
                    panel.stock_codes,
                    lower_bounds,
                    upper_bounds,
                    fingerprint_solver_config(solver_config),
                    fingerprint_consumed_covariance(
                        scenario.annualized_covariance,
                        scenario.stock_codes,
                        psd_config=risk_config,
                    ),
                )
            except Exception as error:
                failure = safe_constrained_erc_failure(
                    error,
                    as_of_date=as_of_date,
                    scenario_kind=scenario_kind,
                )
                break
            targets.append(target)
        if failure is not None:
            results.append(
                ConstrainedErcPolicyOutcome(
                    policy_id=policy_id,
                    status=ConstrainedErcOutcomeStatus.FAILED,
                    erc_targets=tuple(targets),
                    failure=failure,
                )
            )
            continue
        try:
            scheduled_targets = _erc_allocation_targets(windows, tuple(targets), config)
            backtest = run_allocation_backtest_with_targets(
                panel,
                policy_id,
                scheduled_targets,
                config,
            )
        except Exception as error:
            results.append(
                ConstrainedErcPolicyOutcome(
                    policy_id=policy_id,
                    status=ConstrainedErcOutcomeStatus.FAILED,
                    erc_targets=tuple(targets),
                    failure=safe_constrained_erc_failure(
                        error,
                        scenario_kind=scenario_kind,
                    ),
                )
            )
        else:
            results.append(
                ConstrainedErcPolicyOutcome(
                    policy_id=policy_id,
                    status=ConstrainedErcOutcomeStatus.SUCCEEDED,
                    erc_targets=tuple(targets),
                    result=backtest,
                )
            )
    return tuple(results)


def _erc_allocation_targets(
    windows: tuple[AllocationSignalWindow, ...],
    erc_targets: tuple[ConstrainedErcTarget, ...],
    config: AllocationBacktestConfig,
) -> tuple[ScheduledAllocationTarget, ...]:
    if len(erc_targets) != len(windows):
        raise ConstrainedErcMissingRiskSnapshotError(
            "ERC target schedule이 shared signal schedule을 완전히 포함하지 않습니다."
        )
    scheduled: list[ScheduledAllocationTarget] = []
    for window, erc_target in zip(windows, erc_targets, strict=True):
        if erc_target.as_of_date != window.policy_input.signal_date:
            raise ConstrainedErcScenarioScheduleError(
                "ERC target as-of가 shared signal date와 일치하지 않습니다."
            )
        target = AllocationTarget(
            signal_date=erc_target.as_of_date,
            stock_codes=erc_target.stock_codes,
            target_weights=erc_target.reconciled_weights,
            policy_id=erc_target.policy_id,
            target_equity_weight=config.target_equity_weight,
        )
        scheduled.append(
            ScheduledAllocationTarget(
                execution_index=window.as_of_index + 2,
                target=target,
            )
        )
    return tuple(scheduled)


def _validate_exact_erc_target(
    target: ConstrainedErcTarget,
    policy_id: str,
    scenario_kind: object,
    as_of_date: date,
    stock_codes: tuple[str, ...],
    lower_bounds: tuple[Decimal, ...],
    upper_bounds: tuple[Decimal, ...],
    solver_config_fingerprint: str,
    covariance_fingerprint: str,
) -> None:
    if not isinstance(target, ConstrainedErcTarget):
        raise ConstrainedErcScenarioScheduleError(
            "ERC solver가 ConstrainedErcTarget을 반환하지 않았습니다."
        )
    if (
        target.policy_id != policy_id
        or target.scenario_kind is not scenario_kind
        or target.as_of_date != as_of_date
        or target.stock_codes != stock_codes
        or target.lower_bounds != lower_bounds
        or target.upper_bounds != upper_bounds
        or target.risk_budgets != _equal_risk_budgets(len(stock_codes))
        or target.solver_config_fingerprint != solver_config_fingerprint
        or target.covariance_fingerprint != covariance_fingerprint
    ):
        raise ConstrainedErcScenarioScheduleError(
            "ERC target의 정책·scenario·as-of·종목 순서·budget·bounds·covariance·solver "
            "설정이 shared 계약과 다릅니다."
        )


def _equal_risk_budgets(size: int) -> tuple[Decimal, ...]:
    with localcontext(Context(prec=50)):
        equal = _ONE / Decimal(size)
        if size == 1:
            return (_ONE,)
        leading = tuple(equal for _ in range(size - 1))
        return (*leading, _ONE - sum(leading, _ZERO))


def _build_control_policy_outcomes(
    panel: AlignedPricePanel,
    windows: tuple[AllocationSignalWindow, ...],
    policies: tuple[AllocationPolicy, ...],
    config: AllocationBacktestConfig,
) -> tuple[ConstrainedErcPolicyOutcome, ...]:
    results: list[ConstrainedErcPolicyOutcome] = []
    for policy in policies:
        try:
            schedule = build_allocation_target_schedule(panel, policy, config, windows)
            result = run_allocation_backtest_with_targets(
                panel,
                policy.policy_id,
                schedule,
                config,
            )
        except Exception as error:
            results.append(
                ConstrainedErcPolicyOutcome(
                    policy_id=policy.policy_id,
                    status=ConstrainedErcOutcomeStatus.FAILED,
                    failure=safe_constrained_erc_failure(error),
                )
            )
        else:
            results.append(
                ConstrainedErcPolicyOutcome(
                    policy_id=policy.policy_id,
                    status=ConstrainedErcOutcomeStatus.SUCCEEDED,
                    result=result,
                )
            )
    return tuple(results)


def _failed_input_trial(
    *,
    trial_id: str,
    executed_at: datetime,
    requested_start: date,
    requested_end: date,
    stock_codes: tuple[str, ...],
    allocation_config: AllocationBacktestConfig,
    risk_model_config: DynamicRiskModelConfig,
    solver_config: ConstrainedErcSolverConfig,
    config_fingerprint: str,
    error: Exception,
) -> ConstrainedErcResearchTrial:
    failure = safe_constrained_erc_failure(error, data_level=True)
    common_failure = ConstrainedErcCommonFailure(
        stage=ConstrainedErcCommonFailureStage.INPUT_PREPARATION,
        failure=failure,
    )
    not_run_failure = ConstrainedErcFailure(
        code="constrained_erc_not_run_common_failure",
        message="공통 입력 준비 실패로 정책을 실행하지 않았습니다.",
    )
    policy_outcomes = tuple(
        ConstrainedErcPolicyOutcome(
            policy_id=policy_id,
            status=ConstrainedErcOutcomeStatus.FAILED,
            failure=not_run_failure,
        )
        for policy_id in CONSTRAINED_ERC_POLICY_ORDER
    )
    market_fingerprint = fingerprint_constrained_erc_market_data(stock_codes, None, None)
    covariance_fingerprint = fingerprint_constrained_erc_covariances(())
    trial_fingerprint = fingerprint_constrained_erc_trial(
        config_fingerprint=config_fingerprint,
        market_data_fingerprint=market_fingerprint,
        covariance_fingerprint=covariance_fingerprint,
        signal_dates=(),
        execution_dates=(),
        policy_outcomes=policy_outcomes,
        common_failure=common_failure,
    )
    return ConstrainedErcResearchTrial(
        trial_id=trial_id,
        status=ConstrainedErcResearchStatus.FAILED,
        executed_at=executed_at,
        requested_start=requested_start,
        requested_end=requested_end,
        actual_evaluation_start=None,
        actual_evaluation_end=None,
        stock_codes=stock_codes,
        price_panel=None,
        aligned_returns=None,
        allocation_config=allocation_config,
        risk_model_config=risk_model_config,
        solver_config=solver_config,
        signal_dates=(),
        execution_dates=(),
        risk_snapshot_outcomes=(),
        policy_outcomes=policy_outcomes,
        config_fingerprint=config_fingerprint,
        market_data_fingerprint=market_fingerprint,
        covariance_fingerprint=covariance_fingerprint,
        trial_fingerprint=trial_fingerprint,
        provenance=current_risk_model_provenance(),
        common_failure=common_failure,
    )


def safe_constrained_erc_failure(
    error: Exception,
    *,
    as_of_date: date | None = None,
    scenario_kind: object | None = None,
    data_level: bool = False,
) -> ConstrainedErcFailure:
    """Map exception types to fixed allow-listed text; never persist exception data."""

    from phalanx.domain import CovarianceScenarioKind

    if data_level:
        return ConstrainedErcFailure(
            code="constrained_erc_input_error",
            message="Constrained ERC 공통 시장데이터 입력을 구성하지 못했습니다.",
        )

    selected_scenario = scenario_kind if isinstance(scenario_kind, CovarianceScenarioKind) else None
    code = "constrained_erc_calculation_error"
    message = "Constrained ERC 정책 계산을 완료하지 못했습니다."
    mappings: tuple[tuple[type[Exception], str, str], ...] = (
        (
            AllocationSelfFinancingError,
            "constrained_erc_self_financing_failure",
            "자산배분 자기금융 회계 계산을 완료하지 못했습니다.",
        ),
        (
            ConstrainedErcInfeasibleBoundsError,
            "constrained_erc_infeasible_bounds",
            "위험자산 합계 1을 만족하는 ERC bounds가 실행 불가능합니다.",
        ),
        (
            ConstrainedErcInvalidCovarianceError,
            "constrained_erc_invalid_covariance",
            "ERC covariance 차원 또는 수치 품질이 올바르지 않습니다.",
        ),
        (
            ConstrainedErcDegenerateVarianceError,
            "constrained_erc_degenerate_variance",
            "ERC feasible portfolio variance가 양수가 아닙니다.",
        ),
        (
            ConstrainedErcLambdaBracketError,
            "constrained_erc_lambda_bracket_failure",
            "ERC positive lambda bracket을 생성하지 못했습니다.",
        ),
        (
            ConstrainedErcCcdConvergenceError,
            "constrained_erc_ccd_non_convergence",
            "ERC CCD가 고정 반복 한도 안에 수렴하지 않았습니다.",
        ),
        (
            ConstrainedErcBisectionConvergenceError,
            "constrained_erc_bisection_non_convergence",
            "ERC outer bisection이 고정 반복 한도 안에 수렴하지 않았습니다.",
        ),
        (
            ConstrainedErcReconciliationError,
            "constrained_erc_decimal_reconciliation_failure",
            "ERC float weights를 exact Decimal 목표비중으로 대사하지 못했습니다.",
        ),
        (
            ConstrainedErcKktValidationError,
            "constrained_erc_kkt_validation_failure",
            "ERC 해가 feasibility·Euler·KKT 검증을 통과하지 못했습니다.",
        ),
        (
            ConstrainedErcDuplicateRiskSnapshotError,
            "constrained_erc_duplicate_risk_snapshot",
            "동일 signal date의 위험 snapshot이 중복되었습니다.",
        ),
        (
            ConstrainedErcMissingRiskSnapshotError,
            "constrained_erc_missing_risk_snapshot",
            "정확한 signal date의 위험 snapshot이 없습니다.",
        ),
        (
            ConstrainedErcScenarioScheduleError,
            "constrained_erc_scenario_schedule_mismatch",
            "covariance scenario와 shared signal 일정이 일치하지 않습니다.",
        ),
    )
    for error_type, mapped_code, mapped_message in mappings:
        if isinstance(error, error_type):
            code = mapped_code
            message = mapped_message
            break
    if isinstance(error, RiskModelError):
        code = "constrained_erc_risk_snapshot_failure"
        message = "동적 위험모형 snapshot을 생성하지 못했습니다."
    return ConstrainedErcFailure(
        code=code,
        message=message,
        as_of_date=as_of_date,
        scenario_kind=selected_scenario,
    )


def _unique_stock_codes(histories: tuple[StockDailyBars, ...]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for history in histories:
        stock_code = history.stock.stock_code
        if stock_code not in seen:
            seen.add(stock_code)
            result.append(stock_code)
    return tuple(result)


__all__ = [
    "ConstrainedErcRiskEstimator",
    "ConstrainedErcScenarioSolver",
    "conduct_constrained_erc_research",
    "safe_constrained_erc_failure",
]
