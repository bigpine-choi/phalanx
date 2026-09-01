from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from phalanx.domain import (
    CONSTRAINED_ERC_SCHEMA,
    VOLATILITY_OVERLAY_SCENARIO_POLICY_IDS,
    AlignedReturnMatrix,
    AllocationBacktestConfig,
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
    VolatilityOverlayOutcomeStatus,
    VolatilityOverlayResearchStatus,
    VolatilityOverlayTarget,
)
from phalanx.market_data.service import StockDailyBars
from phalanx.portfolio.constrained_erc import ConstrainedErcSolver
from phalanx.portfolio.dynamic_risk_model import DynamicRiskModel
from phalanx.portfolio.errors import (
    AllocationSelfFinancingError,
    InvalidVolatilityOverlayDomainError,
)
from phalanx.portfolio.volatility_overlay_research import (
    conduct_volatility_overlay_research,
    safe_volatility_overlay_failure,
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


def _histories(count: int = 27) -> tuple[StockDailyBars, ...]:
    histories: list[StockDailyBars] = []
    for column in range(5):
        stock_code = f"{column + 1:06d}"
        bars: list[DailyBar] = []
        for index in range(count):
            trade_date = START + timedelta(days=index)
            trend = Decimal(index * (column + 1))
            cycle = Decimal(((index + column) % 4) - 2) / Decimal(3)
            close = Decimal(100 + column * 20) + trend + cycle
            open_price = close - Decimal((index + column) % 3 - 1) / Decimal(5)
            bars.append(
                DailyBar(
                    stock_code=stock_code,
                    trade_date=trade_date,
                    open_price=open_price,
                    high_price=max(open_price, close) + 1,
                    low_price=min(open_price, close) - 1,
                    close_price=close,
                    volume=1_000 + index,
                )
            )
        histories.append(
            StockDailyBars(
                stock=KoreanStock(stock_code, f"종목-{column + 1}", StockMarket.KOSPI),
                bars=tuple(bars),
            )
        )
    return tuple(histories)


class RecordingEstimator:
    def __init__(self) -> None:
        self.delegate = DynamicRiskModel(_risk_config())
        self.calls: list[tuple[date, tuple[date, ...]]] = []

    def estimate(
        self,
        matrix: AlignedReturnMatrix,
        *,
        as_of_date: date,
    ) -> DynamicRiskModelSnapshot:
        self.calls.append((as_of_date, matrix.dates))
        return self.delegate.estimate(matrix, as_of_date=as_of_date)


class OneScenarioFailingSolver:
    def __init__(self, failed_kind: CovarianceScenarioKind) -> None:
        self.delegate = ConstrainedErcSolver(psd_config=_risk_config())
        self.failed_kind = failed_kind
        self.calls: list[CovarianceScenarioKind] = []

    def solve_scenario(
        self,
        scenario: CovarianceScenario,
        *,
        as_of_date: date,
        risk_budgets: tuple[Decimal, ...] | None = None,
        lower_bounds: tuple[Decimal, ...] | None = None,
        upper_bounds: tuple[Decimal, ...] | None = None,
    ) -> ConstrainedErcTarget:
        self.calls.append(scenario.kind)
        if scenario.kind is self.failed_kind:
            raise RuntimeError("APP_SECRET=must-not-escape")
        return self.delegate.solve_scenario(
            scenario,
            as_of_date=as_of_date,
            risk_budgets=risk_budgets,
            lower_bounds=lower_bounds,
            upper_bounds=upper_bounds,
        )


def _conduct(
    *,
    histories: tuple[StockDailyBars, ...] | None = None,
    target: Decimal = Decimal("0.001"),
    cash_yield: Decimal = Decimal(0),
    estimator: RecordingEstimator | None = None,
    solver: OneScenarioFailingSolver | None = None,
    trial_id: str = "overlay-research",
    executed_at: datetime = EXECUTED_AT,
):
    selected_histories = _histories() if histories is None else histories
    return conduct_volatility_overlay_research(
        selected_histories,
        START,
        START + timedelta(days=len(selected_histories[0].bars) - 1),
        target_annual_volatility=target,
        annual_cash_yield=cash_yield,
        allocation_config=_allocation_config(),
        risk_model_config=_risk_config(),
        estimator=estimator,
        solver=solver,
        trial_id_factory=lambda: trial_id,
        clock=lambda: executed_at,
    )


def test_four_overlays_reuse_causal_schedule_and_preserve_erc_sleeves() -> None:
    estimator = RecordingEstimator()

    trial = _conduct(estimator=estimator)

    assert trial.status is VolatilityOverlayResearchStatus.SUCCEEDED
    assert trial.source_trial.status is ConstrainedErcResearchStatus.SUCCEEDED
    assert trial.source_trial.schema == CONSTRAINED_ERC_SCHEMA
    assert tuple(outcome.policy_id for outcome in trial.policy_outcomes) == (
        VOLATILITY_OVERLAY_SCENARIO_POLICY_IDS
    )
    assert trial.signal_dates == (
        START + timedelta(days=20),
        START + timedelta(days=22),
        START + timedelta(days=24),
    )
    assert trial.execution_dates == tuple(
        signal + timedelta(days=1) for signal in trial.signal_dates
    )
    assert tuple(as_of for as_of, _ in estimator.calls) == trial.signal_dates
    assert all(visible_dates[-1] == as_of for as_of, visible_dates in estimator.calls)
    assert tuple(len(visible) for _, visible in estimator.calls) == (20, 22, 22)

    for source_outcome, overlay_outcome in zip(
        trial.source_trial.policy_outcomes[:4],
        trial.policy_outcomes,
        strict=True,
    ):
        assert source_outcome.status is ConstrainedErcOutcomeStatus.SUCCEEDED
        assert overlay_outcome.status is VolatilityOverlayOutcomeStatus.SUCCEEDED
        assert overlay_outcome.result is not None
        assert source_outcome.result is not None
        assert all(
            record.target.target_equity_weight == Decimal(1)
            for record in source_outcome.result.rebalances
        )
        assert (
            tuple(record.execution_date for record in overlay_outcome.result.rebalances)
            == trial.execution_dates
        )
        for source_target, target, record in zip(
            source_outcome.erc_targets,
            overlay_outcome.overlay_targets,
            overlay_outcome.result.rebalances,
            strict=True,
        ):
            assert target.forecast_annual_volatility == Decimal(
                str(source_target.expected_portfolio_volatility)
            )
            assert target.risky_sleeve_weights == source_target.reconciled_weights
            assert target.scalar < Decimal(1)
            assert target.target_equity_weight == target.scalar
            assert record.target.target_equity_weight == target.scalar
            assert sum(target.target_weights, Decimal(0)) + target.cash_residual == Decimal(1)
            assert max(target.target_weights) <= Decimal("0.20")
            for left in range(len(target.target_weights)):
                for right in range(left + 1, len(target.target_weights)):
                    assert (
                        target.target_weights[left] * target.risky_sleeve_weights[right]
                        == target.target_weights[right] * target.risky_sleeve_weights[left]
                    )


def test_trial_rejects_tampered_forecast_when_scalar_is_clamped_to_one() -> None:
    trial = _conduct(target=Decimal("1"))
    for scenario_index, (source_outcome, original_outcome) in enumerate(
        zip(
            trial.source_trial.policy_outcomes[:4],
            trial.policy_outcomes,
            strict=True,
        )
    ):
        original_target = original_outcome.overlay_targets[0]
        source_target = source_outcome.erc_targets[0]
        source_forecast = Decimal(str(source_target.expected_portfolio_volatility))
        tampered_forecast = source_forecast / Decimal(2)
        assert original_target.scalar == Decimal(1)
        assert trial.overlay_config.target_annual_volatility >= source_forecast
        assert trial.overlay_config.target_annual_volatility >= tampered_forecast

        tampered_target = VolatilityOverlayTarget.model_validate(
            {
                **original_target.model_dump(),
                "forecast_annual_volatility": tampered_forecast,
            }
        )
        assert tampered_target.scalar == Decimal(1)
        tampered_outcome = replace(
            original_outcome,
            overlay_targets=(tampered_target, *original_outcome.overlay_targets[1:]),
        )
        tampered_outcomes = list(trial.policy_outcomes)
        tampered_outcomes[scenario_index] = tampered_outcome

        with pytest.raises(
            InvalidVolatilityOverlayDomainError,
            match="source ERC·CLI config provenance",
        ):
            replace(trial, policy_outcomes=tuple(tampered_outcomes))


def test_one_source_scenario_failure_has_no_fallback_or_winner() -> None:
    solver = OneScenarioFailingSolver(CovarianceScenarioKind.FAST_IEWMA)

    trial = _conduct(solver=solver)

    assert trial.status is VolatilityOverlayResearchStatus.FAILED
    statuses = {outcome.policy_id: outcome.status for outcome in trial.policy_outcomes}
    assert statuses["volatility_overlay_fast_iewma"] is VolatilityOverlayOutcomeStatus.FAILED
    assert all(
        status is VolatilityOverlayOutcomeStatus.SUCCEEDED
        for policy_id, status in statuses.items()
        if policy_id != "volatility_overlay_fast_iewma"
    )
    failed = trial.policy_outcomes[1]
    assert failed.result is None
    assert failed.failure is not None
    assert failed.failure.code == "volatility_overlay_source_erc_failure"
    assert "must-not-escape" not in failed.failure.message
    assert solver.calls.count(CovarianceScenarioKind.FAST_IEWMA) == 1


def test_self_financing_failure_projects_only_safe_code_message_and_signal_date() -> None:
    failure = safe_volatility_overlay_failure(
        AllocationSelfFinancingError(
            "APP_SECRET=must-not-escape",
            as_of_date=START,
        ),
        scenario_kind=CovarianceScenarioKind.FAST_IEWMA,
    )

    assert failure.code == "volatility_overlay_self_financing_failure"
    assert failure.as_of_date == START
    assert failure.scenario_kind is CovarianceScenarioKind.FAST_IEWMA
    assert "must-not-escape" not in failure.message


def test_target_and_cash_yield_are_both_part_of_deterministic_identity() -> None:
    short_histories = _histories(23)
    first = _conduct(histories=short_histories, trial_id="first")
    rerun = _conduct(
        histories=short_histories,
        trial_id="second",
        executed_at=EXECUTED_AT + timedelta(days=10),
    )
    equivalent_inputs = _conduct(
        histories=short_histories,
        target=Decimal("0.001000000000000"),
        cash_yield=Decimal("0E-10000"),
        trial_id="equivalent-inputs",
        executed_at=EXECUTED_AT + timedelta(days=20),
    )
    different_target = _conduct(
        histories=short_histories,
        target=Decimal("0.002"),
        trial_id="different-target",
    )
    different_yield = _conduct(
        histories=short_histories,
        cash_yield=Decimal("0.03"),
        trial_id="different-yield",
    )

    assert first.trial_fingerprint == rerun.trial_fingerprint
    assert first.config_fingerprint == rerun.config_fingerprint
    assert first.trial_fingerprint == equivalent_inputs.trial_fingerprint
    assert first.config_fingerprint == equivalent_inputs.config_fingerprint
    assert equivalent_inputs.overlay_config.target_annual_volatility.as_tuple() == Decimal(
        "0.001"
    ).as_tuple()
    assert equivalent_inputs.overlay_config.annual_cash_yield.as_tuple() == Decimal(
        "0"
    ).as_tuple()
    assert first.trial_id != rerun.trial_id
    assert first.executed_at != rerun.executed_at
    assert first.config_fingerprint != different_target.config_fingerprint
    assert first.trial_fingerprint != different_target.trial_fingerprint
    assert first.config_fingerprint != different_yield.config_fingerprint
    assert first.trial_fingerprint != different_yield.trial_fingerprint


def test_empty_source_failure_is_persistable_and_all_scenarios_remain_failed() -> None:
    trial = conduct_volatility_overlay_research(
        (),
        START,
        START + timedelta(days=22),
        target_annual_volatility=Decimal("0.12"),
        annual_cash_yield=Decimal(0),
        allocation_config=_allocation_config(),
        risk_model_config=_risk_config(),
        trial_id_factory=lambda: "empty-overlay",
        clock=lambda: EXECUTED_AT,
    )

    assert trial.status is VolatilityOverlayResearchStatus.FAILED
    assert trial.stock_codes == ()
    assert trial.source_trial.common_failure is not None
    assert all(
        outcome.status is VolatilityOverlayOutcomeStatus.FAILED
        and outcome.failure is not None
        and outcome.failure.code == "volatility_overlay_source_common_failure"
        and outcome.result is None
        and not outcome.overlay_targets
        for outcome in trial.policy_outcomes
    )
