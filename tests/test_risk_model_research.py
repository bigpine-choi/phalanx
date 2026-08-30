from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from phalanx.domain import (
    SCENARIO_KIND_ORDER,
    AlignedReturnMatrix,
    CovarianceScenario,
    CovarianceScenarioKind,
    DownsideStressMetadata,
    DynamicRiskModelConfig,
    DynamicRiskModelSnapshot,
    IewmaMetadata,
    LedoitWolfMetadata,
    PsdDiagnostics,
    RiskModelResearchStatus,
)
from phalanx.portfolio.risk_model_research import (
    conduct_dynamic_risk_model_research,
    create_risk_model_research_trial,
    current_risk_model_provenance,
)


def _matrix(count: int = 770) -> AlignedReturnMatrix:
    first = date(2020, 1, 1)
    return AlignedReturnMatrix(
        stock_codes=("000660", "005930"),
        dates=tuple(first + timedelta(days=index) for index in range(count)),
        values=tuple(
            (
                Decimal((index % 7) - 3) / Decimal(1000),
                Decimal(((index * 2) % 9) - 4) / Decimal(1000),
            )
            for index in range(count)
        ),
    )


def _diagnostics(size: int) -> PsdDiagnostics:
    return PsdDiagnostics(
        minimum_eigenvalue_before=0.04,
        minimum_eigenvalue_after=0.04,
        maximum_eigenvalue_after=0.04,
        numerical_tolerance=1e-10,
        rank=size,
        condition_number=1.0,
        frobenius_repair_norm=0.0,
        relative_repair_norm=0.0,
        repaired=False,
    )


def _snapshot(
    stock_codes: tuple[str, ...],
    consumed_dates: tuple[date, ...],
    config: DynamicRiskModelConfig,
) -> DynamicRiskModelSnapshot:
    size = len(stock_codes)
    covariance = tuple(
        tuple(0.04 if row == column else 0.0 for column in range(size)) for row in range(size)
    )
    correlation = tuple(
        tuple(1.0 if row == column else 0.0 for column in range(size)) for row in range(size)
    )
    diagnostics = _diagnostics(size)
    scenarios: list[CovarianceScenario] = []
    for kind in SCENARIO_KIND_ORDER:
        if kind is CovarianceScenarioKind.LONG_RUN_LEDOIT_WOLF:
            metadata = LedoitWolfMetadata(shrinkage=0.5)
        elif kind is CovarianceScenarioKind.FAST_IEWMA:
            metadata = IewmaMetadata(
                volatility_half_life=config.fast_volatility_half_life,
                correlation_half_life=config.fast_correlation_half_life,
                volatility_seed_count=len(consumed_dates),
                correlation_observation_count=len(consumed_dates),
                volatility_effective_sample_size=10.0,
                correlation_effective_sample_size=10.0,
                clip_threshold=config.standardized_return_clip,
                clipped_scalar_count=0,
                correlation_psd_diagnostics=diagnostics,
            )
        elif kind is CovarianceScenarioKind.SLOW_IEWMA:
            metadata = IewmaMetadata(
                volatility_half_life=config.slow_volatility_half_life,
                correlation_half_life=config.slow_correlation_half_life,
                volatility_seed_count=len(consumed_dates),
                correlation_observation_count=len(consumed_dates),
                volatility_effective_sample_size=10.0,
                correlation_effective_sample_size=10.0,
                clip_threshold=config.standardized_return_clip,
                clipped_scalar_count=0,
                correlation_psd_diagnostics=diagnostics,
            )
        else:
            metadata = DownsideStressMetadata(
                downside_fraction=config.downside_fraction,
                selected_count=1,
                cutoff_equal_weight_return=Decimal(0),
                selected_dates=(consumed_dates[0],),
                selected_dates_fingerprint="d" * 64,
                shrinkage=0.5,
            )
        scenarios.append(
            CovarianceScenario(
                kind=kind,
                stock_codes=stock_codes,
                observation_dates=consumed_dates,
                annualized_covariance=covariance,
                annualized_volatilities=tuple(0.2 for _ in stock_codes),
                correlation_matrix=correlation,
                metadata=metadata,
                psd_diagnostics=diagnostics,
            )
        )
    return DynamicRiskModelSnapshot(
        as_of_date=consumed_dates[-1],
        consumed_start_date=consumed_dates[0],
        consumed_end_date=consumed_dates[-1],
        consumed_observation_count=len(consumed_dates),
        stock_codes=stock_codes,
        consumed_dates=consumed_dates,
        scenarios=tuple(scenarios),
        consumed_input_fingerprint="a" * 64,
    )


class SpyEstimator:
    def __init__(
        self,
        source: AlignedReturnMatrix,
        config: DynamicRiskModelConfig,
        *,
        fail_call: int | None = None,
        failure_secret: str = "",
    ) -> None:
        self.source = source
        self.config = config
        self.fail_call = fail_call
        self.failure_secret = failure_secret
        self.visible_matrices: list[AlignedReturnMatrix] = []

    def estimate(
        self,
        matrix: AlignedReturnMatrix,
        *,
        as_of_date: date,
    ) -> DynamicRiskModelSnapshot:
        self.visible_matrices.append(matrix)
        if self.fail_call == len(self.visible_matrices):
            raise RuntimeError(self.failure_secret)
        window_start = max(0, len(matrix.dates) - self.config.maximum_observations)
        return _snapshot(
            matrix.stock_codes,
            matrix.dates[window_start:],
            self.config,
        )


def test_rolling_research_reuses_504_756_5_schedule_without_exposing_future_rows() -> None:
    matrix = _matrix()
    config = DynamicRiskModelConfig()
    estimator = SpyEstimator(matrix, config)

    result = conduct_dynamic_risk_model_research(
        matrix,
        config=config,
        estimator=estimator,
    )

    assert result.status is RiskModelResearchStatus.SUCCEEDED
    assert result.stock_codes == matrix.stock_codes
    assert result.failure is None
    assert result.scheduled_as_of_dates[:4] == tuple(
        matrix.dates[index] for index in (503, 508, 513, 518)
    )
    assert tuple(snapshot.consumed_observation_count for snapshot in result.snapshots[:2]) == (
        504,
        509,
    )
    assert max(snapshot.consumed_observation_count for snapshot in result.snapshots) == 756
    assert result.snapshots[-1].consumed_observation_count == 756
    assert len(estimator.visible_matrices) == len(result.scheduled_as_of_dates)
    for as_of_date, visible in zip(
        result.scheduled_as_of_dates,
        estimator.visible_matrices,
        strict=True,
    ):
        as_of_index = matrix.dates.index(as_of_date)
        assert visible.stock_codes == matrix.stock_codes
        assert visible.dates == matrix.dates[: as_of_index + 1]
        assert visible.values == matrix.values[: as_of_index + 1]
        assert visible.dates[-1] == as_of_date


def test_one_snapshot_failure_fails_the_whole_research_with_safe_code_and_as_of() -> None:
    matrix = _matrix()
    config = DynamicRiskModelConfig()
    secret = "synthetic-app-secret-token-account-number"
    estimator = SpyEstimator(
        matrix,
        config,
        fail_call=2,
        failure_secret=secret,
    )

    result = conduct_dynamic_risk_model_research(
        matrix,
        config=config,
        estimator=estimator,
    )

    assert result.status is RiskModelResearchStatus.FAILED
    assert len(result.snapshots) == 1
    assert result.failure is not None
    assert result.failure.code == "risk_model_numerical_error"
    assert result.failure.as_of_date == matrix.dates[508]
    assert secret not in result.failure.message
    assert len(estimator.visible_matrices) == 2


def test_success_and_failure_trials_have_deterministic_fingerprints_and_provenance() -> None:
    matrix = _matrix()
    config = DynamicRiskModelConfig()
    first = create_risk_model_research_trial(
        matrix,
        matrix.dates[0],
        matrix.dates[-1],
        config=config,
        estimator=SpyEstimator(matrix, config),
        trial_id_factory=lambda: "risk-trial-first",
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
    )
    second = create_risk_model_research_trial(
        matrix,
        matrix.dates[0],
        matrix.dates[-1],
        config=config,
        estimator=SpyEstimator(matrix, config),
        trial_id_factory=lambda: "risk-trial-second",
        clock=lambda: datetime(2026, 2, 1, tzinfo=UTC),
    )

    assert first.status is RiskModelResearchStatus.SUCCEEDED
    assert second.status is RiskModelResearchStatus.SUCCEEDED
    assert first.result is not None
    assert first.failure is None
    assert (
        first.config_fingerprint,
        first.input_fingerprint,
        first.trial_fingerprint,
    ) == (
        second.config_fingerprint,
        second.input_fingerprint,
        second.trial_fingerprint,
    )
    assert first.provenance == second.provenance == current_risk_model_provenance()

    secret = "synthetic-secret-in-estimator"
    failed = create_risk_model_research_trial(
        matrix,
        matrix.dates[0],
        matrix.dates[-1],
        config=config,
        estimator=SpyEstimator(
            matrix,
            config,
            fail_call=2,
            failure_secret=secret,
        ),
        trial_id_factory=lambda: "risk-trial-failed",
        clock=lambda: datetime(2026, 3, 1, tzinfo=UTC),
    )
    assert failed.status is RiskModelResearchStatus.FAILED
    assert failed.result is not None
    assert failed.result.status is RiskModelResearchStatus.FAILED
    assert failed.failure == failed.result.failure
    assert failed.failure is not None
    assert failed.failure.as_of_date == matrix.dates[508]
    assert secret not in failed.failure.message
