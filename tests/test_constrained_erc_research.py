from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Context, Decimal, localcontext

import pytest

import phalanx.portfolio.constrained_erc_research as research_module
from phalanx.domain import (
    CONSTRAINED_ERC_POLICY_ORDER,
    AlignedReturnMatrix,
    AllocationBacktestConfig,
    ConstrainedErcCommonFailureStage,
    ConstrainedErcOutcomeStatus,
    ConstrainedErcResearchStatus,
    ConstrainedErcTarget,
    CovarianceScenario,
    CovarianceScenarioKind,
    DailyBar,
    DynamicRiskModelConfig,
    DynamicRiskModelSnapshot,
    KoreanStock,
    StockMarket,
)
from phalanx.market_data.service import StockDailyBars
from phalanx.portfolio.allocation_backtest import run_allocation_backtest
from phalanx.portfolio.allocation_data import build_aligned_price_panel
from phalanx.portfolio.allocation_policies import default_allocation_policies
from phalanx.portfolio.constrained_erc import ConstrainedErcSolver
from phalanx.portfolio.dynamic_risk_model import DynamicRiskModel
from phalanx.portfolio.errors import (
    AllocationSelfFinancingError,
    ConstrainedErcScenarioScheduleError,
    InvalidConstrainedErcDomainError,
)

START = date(2025, 1, 1)
EXECUTED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _allocation_config() -> AllocationBacktestConfig:
    return AllocationBacktestConfig(
        minimum_training_returns=20,
        maximum_training_returns=22,
        rebalance_interval=2,
        target_equity_weight=Decimal(1),
    )


def _risk_config() -> DynamicRiskModelConfig:
    return DynamicRiskModelConfig(
        minimum_observations=20,
        maximum_observations=22,
        rebalance_interval=2,
        fast_volatility_half_life=2,
        fast_correlation_half_life=4,
        slow_volatility_half_life=3,
        slow_correlation_half_life=6,
        minimum_volatility_seed_observations=2,
        minimum_correlation_observations=3,
        downside_fraction=Decimal("0.50"),
        minimum_downside_observations=3,
    )


def _histories(count: int = 27, stock_count: int = 5) -> tuple[StockDailyBars, ...]:
    codes = tuple(f"{index + 1:06d}" for index in range(stock_count))
    histories: list[StockDailyBars] = []
    for column, stock_code in enumerate(codes):
        bars: list[DailyBar] = []
        for index in range(count):
            trade_date = START + timedelta(days=index)
            trend = Decimal(index * (column + 1))
            cycle = Decimal(((index + column) % 4) - 2) / Decimal(3)
            close = Decimal(100 + column * 20) + trend + cycle
            overnight = Decimal((index + column) % 3 - 1) / Decimal(5)
            open_price = close - overnight
            bars.append(
                DailyBar(
                    stock_code=stock_code,
                    trade_date=trade_date,
                    open_price=open_price,
                    high_price=max(open_price, close) + Decimal(1),
                    low_price=min(open_price, close) - Decimal(1),
                    close_price=close,
                    volume=1_000 + index,
                )
            )
        histories.append(
            StockDailyBars(
                stock=KoreanStock(
                    stock_code,
                    f"종목-{column + 1}",
                    StockMarket.KOSPI,
                ),
                bars=tuple(bars),
            )
        )
    return tuple(histories)


def _production_shape_histories() -> tuple[StockDailyBars, ...]:
    first = date(2024, 1, 2)
    last = date(2026, 8, 28)
    weekdays: list[date] = []
    current = first
    while current <= last:
        if current.weekday() < 5:
            weekdays.append(current)
        current += timedelta(days=1)
    removed_indices = {round(number * (len(weekdays) - 1) / 48) for number in range(1, 48)}
    trade_dates = tuple(
        value for index, value in enumerate(weekdays) if index not in removed_indices
    )
    assert len(trade_dates) == 647

    histories: list[StockDailyBars] = []
    for column in range(9):
        stock_code = f"{column + 1:06d}"
        bars: list[DailyBar] = []
        for index, trade_date in enumerate(trade_dates):
            trend = Decimal(index * (column + 1)) / Decimal(17)
            cycle = Decimal(((index + column) % 7) - 3) / Decimal(19)
            close = Decimal(100 + column * 23) + trend + cycle
            open_price = close - Decimal(((index + 2 * column) % 5) - 2) / Decimal(13)
            bars.append(
                DailyBar(
                    stock_code=stock_code,
                    trade_date=trade_date,
                    open_price=open_price,
                    high_price=max(open_price, close) + Decimal(1),
                    low_price=min(open_price, close) - Decimal(1),
                    close_price=close,
                    volume=10_000 + index,
                )
            )
        histories.append(
            StockDailyBars(
                stock=KoreanStock(stock_code, f"장기합성-{column + 1}", StockMarket.KOSPI),
                bars=tuple(bars),
            )
        )
    return tuple(histories)


class RecordingEstimator:
    def __init__(self, config: DynamicRiskModelConfig) -> None:
        self.delegate = DynamicRiskModel(config)
        self.calls: list[tuple[date, tuple[date, ...]]] = []

    def estimate(
        self,
        matrix: AlignedReturnMatrix,
        *,
        as_of_date: date,
    ) -> DynamicRiskModelSnapshot:
        self.calls.append((as_of_date, matrix.dates))
        assert matrix.dates[-1] == as_of_date
        return self.delegate.estimate(matrix, as_of_date=as_of_date)


class OneScenarioFailingSolver:
    def __init__(
        self,
        delegate: ConstrainedErcSolver,
        failed_kind: CovarianceScenarioKind,
    ) -> None:
        self.delegate = delegate
        self.failed_kind = failed_kind
        self.calls: list[tuple[CovarianceScenarioKind, date]] = []

    def solve_scenario(
        self,
        scenario: CovarianceScenario,
        *,
        as_of_date: date,
        risk_budgets: tuple[Decimal, ...] | None = None,
        lower_bounds: tuple[Decimal, ...] | None = None,
        upper_bounds: tuple[Decimal, ...] | None = None,
    ) -> ConstrainedErcTarget:
        self.calls.append((scenario.kind, as_of_date))
        if scenario.kind is self.failed_kind:
            raise RuntimeError("APP_SECRET=never-persist-this")
        return self.delegate.solve_scenario(
            scenario,
            as_of_date=as_of_date,
            risk_budgets=risk_budgets,
            lower_bounds=lower_bounds,
            upper_bounds=upper_bounds,
        )


class WrongCovarianceSolver:
    def __init__(self, delegate: ConstrainedErcSolver) -> None:
        self.delegate = delegate

    def solve_scenario(
        self,
        scenario: CovarianceScenario,
        *,
        as_of_date: date,
        risk_budgets: tuple[Decimal, ...] | None = None,
        lower_bounds: tuple[Decimal, ...] | None = None,
        upper_bounds: tuple[Decimal, ...] | None = None,
    ) -> ConstrainedErcTarget:
        size = len(scenario.stock_codes)
        different_covariance = tuple(
            tuple(1.0 if row == column else 0.0 for column in range(size)) for row in range(size)
        )
        return self.delegate.solve(
            different_covariance,
            scenario.stock_codes,
            risk_budgets=risk_budgets,
            lower_bounds=lower_bounds,
            upper_bounds=upper_bounds,
            scenario_kind=scenario.kind,
            as_of_date=as_of_date,
        )


def _conduct(
    *,
    estimator: RecordingEstimator | None = None,
    solver: OneScenarioFailingSolver | None = None,
    trial_id: str = "constrained-research",
    clock: datetime = EXECUTED_AT,
):
    return research_module.conduct_constrained_erc_research(
        _histories(),
        START,
        START + timedelta(days=26),
        allocation_config=_allocation_config(),
        risk_model_config=_risk_config(),
        estimator=estimator,
        solver=solver,
        trial_id_factory=lambda: trial_id,
        clock=lambda: clock,
    )


def test_shared_schedule_is_causal_exact_and_all_seven_policies_are_comparable() -> None:
    estimator = RecordingEstimator(_risk_config())

    trial = _conduct(estimator=estimator)

    assert trial.status is ConstrainedErcResearchStatus.SUCCEEDED
    assert tuple(outcome.policy_id for outcome in trial.policy_outcomes) == (
        CONSTRAINED_ERC_POLICY_ORDER
    )
    assert trial.signal_dates == (
        START + timedelta(days=20),
        START + timedelta(days=22),
        START + timedelta(days=24),
    )
    assert trial.execution_dates == tuple(value + timedelta(days=1) for value in trial.signal_dates)
    assert tuple(len(dates) for _, dates in estimator.calls) == (20, 22, 22)
    assert tuple(as_of for as_of, _ in estimator.calls) == trial.signal_dates
    assert all(dates[-1] == as_of for as_of, dates in estimator.calls)
    results = tuple(outcome.result for outcome in trial.policy_outcomes)
    assert all(result is not None for result in results)
    assert len({result.dates for result in results if result is not None}) == 1
    assert all(
        result.rebalances[0].pre_trade_nav == Decimal(1) for result in results if result is not None
    )
    assert all(
        record.target.target_equity_weight == Decimal(1)
        for result in results
        if result is not None
        for record in result.rebalances
    )
    for outcome in trial.policy_outcomes[:4]:
        assert outcome.result is not None
        assert len(outcome.erc_targets) == len(trial.signal_dates)
        assert all(
            target.reconciled_weights == (Decimal("0.2"),) * 5 for target in outcome.erc_targets
        )
        assert all(target.all_assets_bound_degeneracy for target in outcome.erc_targets)
        assert tuple(record.execution_date for record in outcome.result.rebalances) == (
            trial.execution_dates
        )
        assert all(
            weight <= Decimal("0.20")
            for record in outcome.result.rebalances
            for weight in record.target.target_weights
        )
        assert any(
            weight > Decimal("0.20")
            for realized in outcome.result.realized_weights
            for weight in realized
        )


def test_shared_window_control_path_is_exactly_equal_to_legacy_backtest() -> None:
    trial = _conduct()
    panel = build_aligned_price_panel(
        _histories(),
        minimum_common_observations=_allocation_config().minimum_training_returns + 2,
    )

    for policy, outcome in zip(
        default_allocation_policies(),
        trial.policy_outcomes[4:],
        strict=True,
    ):
        assert outcome.result == run_allocation_backtest(panel, policy, _allocation_config())


def test_six_asset_dynamic_risk_to_erc_pipeline_is_non_degenerate() -> None:
    allocation_config = replace(
        _allocation_config(),
        minimum_training_returns=24,
        maximum_training_returns=26,
    )
    risk_config = replace(
        _risk_config(),
        minimum_observations=24,
        maximum_observations=26,
    )
    trial = research_module.conduct_constrained_erc_research(
        _histories(count=31, stock_count=6),
        START,
        START + timedelta(days=30),
        allocation_config=allocation_config,
        risk_model_config=risk_config,
        trial_id_factory=lambda: "six-asset-integration",
        clock=lambda: EXECUTED_AT,
    )

    assert trial.status is ConstrainedErcResearchStatus.SUCCEEDED
    first_targets = tuple(
        outcome.erc_targets[0].reconciled_weights for outcome in trial.policy_outcomes[:4]
    )
    assert len(set(first_targets)) > 1
    assert any(len(set(weights)) > 1 for weights in first_targets)
    for outcome in trial.policy_outcomes[:4]:
        assert outcome.result is not None
        assert all(not target.all_assets_bound_degeneracy for target in outcome.erc_targets)
        assert all(
            sum(target.reconciled_weights, Decimal(0)) == Decimal(1)
            and max(target.reconciled_weights) <= Decimal("0.20")
            and target.diagnostics_after_reconciliation.normalized_max_kkt_residual <= 1e-10
            for target in outcome.erc_targets
        )


def test_nine_asset_production_shape_fully_invested_research_reconciles_cash() -> None:
    trial = research_module.conduct_constrained_erc_research(
        _production_shape_histories(),
        date(2024, 1, 1),
        date(2026, 8, 28),
        trial_id_factory=lambda: "nine-asset-production-shape",
        clock=lambda: EXECUTED_AT,
    )

    assert trial.status is ConstrainedErcResearchStatus.SUCCEEDED
    assert len(trial.stock_codes) == 9
    assert trial.price_panel is not None
    assert trial.aligned_returns is not None
    assert len(trial.price_panel.dates) == 647
    assert len(trial.aligned_returns.dates) == 646
    assert trial.allocation_config.minimum_training_returns == 504
    assert trial.allocation_config.maximum_training_returns == 756
    assert trial.allocation_config.rebalance_interval == 5
    assert trial.risk_model_config.minimum_observations == 504
    assert trial.risk_model_config.maximum_observations == 756
    assert trial.risk_model_config.rebalance_interval == 5
    assert len(trial.signal_dates) == len(trial.execution_dates) == 29
    assert (trial.signal_dates[0], trial.execution_dates[0]) == (
        date(2026, 1, 28),
        date(2026, 1, 29),
    )
    assert (trial.signal_dates[-1], trial.execution_dates[-1]) == (
        date(2026, 8, 26),
        date(2026, 8, 27),
    )
    panel_positions = {
        trade_date: index for index, trade_date in enumerate(trial.price_panel.dates)
    }
    assert all(
        panel_positions[current] - panel_positions[previous] == 5
        for previous, current in zip(
            trial.signal_dates[:-1],
            trial.signal_dates[1:],
            strict=True,
        )
    )
    assert tuple(
        len(outcome.result.rebalances) if outcome.result is not None else 0
        for outcome in trial.policy_outcomes
    ) == (29, 29, 29, 29, 29, 29, 1)
    assert trial.risk_snapshot_outcomes[0].snapshot is not None
    assert trial.risk_snapshot_outcomes[-1].snapshot is not None
    assert trial.risk_snapshot_outcomes[0].snapshot.consumed_observation_count == 504
    assert trial.risk_snapshot_outcomes[-1].snapshot.consumed_observation_count == 644
    with localcontext(Context(prec=50)):
        for outcome in trial.policy_outcomes:
            assert outcome.result is not None
            assert outcome.result.dates == trial.price_panel.dates[505:]
            assert all(value >= 0 for value in outcome.result.realized_cash_weights)
            assert all(
                sum(weights, Decimal(0)) + cash_weight == Decimal(1)
                for weights, cash_weight in zip(
                    outcome.result.realized_weights,
                    outcome.result.realized_cash_weights,
                    strict=True,
                )
            )


def test_one_scenario_solver_failure_has_no_fallback_and_controls_continue() -> None:
    estimator = RecordingEstimator(_risk_config())
    solver = OneScenarioFailingSolver(
        ConstrainedErcSolver(psd_config=_risk_config()),
        CovarianceScenarioKind.FAST_IEWMA,
    )

    trial = _conduct(estimator=estimator, solver=solver)

    assert trial.status is ConstrainedErcResearchStatus.FAILED
    assert trial.common_failure is None
    statuses = {outcome.policy_id: outcome.status for outcome in trial.policy_outcomes}
    assert statuses["constrained_erc_fast_iewma"] is ConstrainedErcOutcomeStatus.FAILED
    assert all(
        statuses[policy_id] is ConstrainedErcOutcomeStatus.SUCCEEDED
        for policy_id in CONSTRAINED_ERC_POLICY_ORDER
        if policy_id != "constrained_erc_fast_iewma"
    )
    failed = trial.policy_outcomes[1]
    assert failed.result is None
    assert failed.failure is not None
    assert failed.failure.code == "constrained_erc_calculation_error"
    assert "never-persist-this" not in failed.failure.message
    assert sum(kind is CovarianceScenarioKind.FAST_IEWMA for kind, _ in solver.calls) == 1
    assert sum(kind is CovarianceScenarioKind.LONG_RUN_LEDOIT_WOLF for kind, _ in solver.calls) == 3
    assert sum(kind is CovarianceScenarioKind.SLOW_IEWMA for kind, _ in solver.calls) == 3
    assert (
        sum(kind is CovarianceScenarioKind.DOWNSIDE_STRESS_LEDOIT_WOLF for kind, _ in solver.calls)
        == 3
    )
    assert len(estimator.calls) == len(trial.signal_dates)


def test_target_from_a_different_covariance_is_rejected_without_fallback() -> None:
    trial = research_module.conduct_constrained_erc_research(
        _histories(),
        START,
        START + timedelta(days=26),
        allocation_config=_allocation_config(),
        risk_model_config=_risk_config(),
        solver=WrongCovarianceSolver(
            ConstrainedErcSolver(psd_config=_risk_config()),
        ),
        trial_id_factory=lambda: "wrong-covariance",
        clock=lambda: EXECUTED_AT,
    )

    assert trial.status is ConstrainedErcResearchStatus.FAILED
    assert all(
        outcome.status is ConstrainedErcOutcomeStatus.FAILED
        and outcome.failure is not None
        and outcome.failure.code == "constrained_erc_scenario_schedule_mismatch"
        for outcome in trial.policy_outcomes[:4]
    )
    assert all(
        outcome.status is ConstrainedErcOutcomeStatus.SUCCEEDED
        for outcome in trial.policy_outcomes[4:]
    )


def test_panel_return_schedule_builders_are_each_called_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counts = {"panel": 0, "matrix": 0, "schedule": 0}
    original_panel = research_module.build_aligned_price_panel
    original_matrix = research_module.build_price_panel_return_matrix
    original_schedule = research_module.build_return_matrix_signal_windows

    def panel_builder(*args: object, **kwargs: object):
        counts["panel"] += 1
        return original_panel(*args, **kwargs)  # type: ignore[arg-type]

    def matrix_builder(*args: object, **kwargs: object):
        counts["matrix"] += 1
        return original_matrix(*args, **kwargs)  # type: ignore[arg-type]

    def schedule_builder(*args: object, **kwargs: object):
        counts["schedule"] += 1
        return original_schedule(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(research_module, "build_aligned_price_panel", panel_builder)
    monkeypatch.setattr(research_module, "build_price_panel_return_matrix", matrix_builder)
    monkeypatch.setattr(
        research_module,
        "build_return_matrix_signal_windows",
        schedule_builder,
    )

    trial = _conduct()

    assert trial.status is ConstrainedErcResearchStatus.SUCCEEDED
    assert counts == {"panel": 1, "matrix": 1, "schedule": 1}


def test_trial_fingerprint_excludes_uuid_and_execution_time() -> None:
    first = _conduct(trial_id="first", clock=EXECUTED_AT)
    second = _conduct(
        trial_id="second",
        clock=EXECUTED_AT + timedelta(days=30),
    )

    assert first.trial_id != second.trial_id
    assert first.executed_at != second.executed_at
    assert first.trial_fingerprint == second.trial_fingerprint
    assert first.config_fingerprint == second.config_fingerprint
    assert first.market_data_fingerprint == second.market_data_fingerprint
    assert first.covariance_fingerprint == second.covariance_fingerprint


def test_empty_universe_becomes_persistable_secret_free_failed_trial() -> None:
    trial = research_module.conduct_constrained_erc_research(
        (),
        START,
        START + timedelta(days=26),
        allocation_config=_allocation_config(),
        risk_model_config=_risk_config(),
        trial_id_factory=lambda: "empty",
        clock=lambda: EXECUTED_AT,
    )

    assert trial.status is ConstrainedErcResearchStatus.FAILED
    assert trial.stock_codes == ()
    assert trial.price_panel is None
    assert trial.common_failure is not None
    assert trial.common_failure.stage is ConstrainedErcCommonFailureStage.INPUT_PREPARATION
    assert trial.common_failure.failure.code == "constrained_erc_input_error"
    assert all(
        outcome.status is ConstrainedErcOutcomeStatus.FAILED for outcome in trial.policy_outcomes
    )
    assert all(
        outcome.failure is not None
        and outcome.failure.code == "constrained_erc_not_run_common_failure"
        for outcome in trial.policy_outcomes
    )


def test_common_input_failure_is_required_when_no_shared_panel_exists() -> None:
    trial = research_module.conduct_constrained_erc_research(
        (),
        START,
        START + timedelta(days=26),
        allocation_config=_allocation_config(),
        risk_model_config=_risk_config(),
        trial_id_factory=lambda: "missing-common-failure",
        clock=lambda: EXECUTED_AT,
    )

    with pytest.raises(InvalidConstrainedErcDomainError, match="공통 실패 정보"):
        replace(trial, common_failure=None)

    disguised_outcome = replace(
        trial.policy_outcomes[0],
        failure=research_module.safe_constrained_erc_failure(RuntimeError("solver-like")),
    )
    with pytest.raises(InvalidConstrainedErcDomainError, match="전역 미실행 코드"):
        replace(
            trial,
            policy_outcomes=(disguised_outcome, *trial.policy_outcomes[1:]),
        )


def test_self_financing_failure_maps_to_stable_secret_free_code() -> None:
    failure = research_module.safe_constrained_erc_failure(
        AllocationSelfFinancingError("synthetic-secret-account-token"),
    )

    assert failure.code == "constrained_erc_self_financing_failure"
    assert failure.message == "자산배분 자기금융 회계 계산을 완료하지 못했습니다."
    assert "synthetic-secret" not in failure.message


def test_common_preparation_failure_keeps_one_stable_global_code() -> None:
    failure = research_module.safe_constrained_erc_failure(
        ConstrainedErcScenarioScheduleError("synthetic-secret-schedule-token"),
        data_level=True,
    )

    assert failure.code == "constrained_erc_input_error"
    assert failure.message == "Constrained ERC 공통 시장데이터 입력을 구성하지 못했습니다."
    assert failure.as_of_date is None
    assert failure.scenario_kind is None
    assert "synthetic-secret" not in failure.message


def test_trial_rejects_invalid_shared_date_dimensions_and_policy_order() -> None:
    trial = _conduct()

    with pytest.raises(InvalidConstrainedErcDomainError, match="오름차순"):
        replace(trial, signal_dates=tuple(reversed(trial.signal_dates)))

    with pytest.raises(InvalidConstrainedErcDomainError, match="일정"):
        replace(trial, execution_dates=trial.execution_dates[:-1])

    with pytest.raises(InvalidConstrainedErcDomainError, match="고정된 7개 정책 순서"):
        replace(trial, policy_outcomes=tuple(reversed(trial.policy_outcomes)))
