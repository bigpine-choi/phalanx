from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import Decimal, getcontext, localcontext
from typing import cast

import numpy as np
import pytest
from sklearn.covariance import LedoitWolf

from phalanx.domain import (
    AlignedReturnMatrix,
    CovarianceScenarioKind,
    DownsideStressMetadata,
    DynamicRiskModelConfig,
    IewmaMetadata,
    LedoitWolfMetadata,
)
from phalanx.portfolio.dynamic_risk_model import (
    DynamicRiskModel,
    ewma_beta,
    normalized_ewma_effective_sample_size,
)
from phalanx.portfolio.errors import (
    DegenerateRiskSeriesError,
    InsufficientCorrelationHistoryError,
    InsufficientDownsideHistoryError,
    InsufficientRiskHistoryError,
    RiskModelAsOfDateNotFoundError,
)

_START = date(2020, 1, 1)
_CODES = ("005930", "000660")


def _dates(count: int) -> tuple[date, ...]:
    return tuple(_START + timedelta(days=index) for index in range(count))


def _default_values(count: int) -> tuple[tuple[Decimal, ...], ...]:
    return tuple(
        (
            Decimal((index * 7) % 29 - 14) / Decimal("1000"),
            Decimal((index * 11 + 3) % 31 - 15) / Decimal("800"),
        )
        for index in range(count)
    )


def _matrix(
    count: int = 504,
    *,
    values: tuple[tuple[Decimal, ...], ...] | None = None,
    codes: tuple[str, ...] = _CODES,
) -> AlignedReturnMatrix:
    selected_values = _default_values(count) if values is None else values
    return AlignedReturnMatrix(
        stock_codes=codes,
        dates=_dates(count),
        values=selected_values,
    )


def _small_config(**changes: object) -> DynamicRiskModelConfig:
    values: dict[str, object] = {
        "minimum_observations": 12,
        "maximum_observations": 20,
        "rebalance_interval": 2,
        "annualization_days": 252,
        "fast_volatility_half_life": 2,
        "fast_correlation_half_life": 4,
        "slow_volatility_half_life": 5,
        "slow_correlation_half_life": 8,
        "standardized_return_clip": 4.2,
        "minimum_volatility_seed_observations": 2,
        "minimum_correlation_observations": 2,
        "downside_fraction": Decimal("0.50"),
        "minimum_downside_observations": 1,
        "psd_relative_eigen_tolerance": 1e-10,
        "psd_absolute_eigen_tolerance": 1e-15,
        "maximum_relative_psd_repair": 1e-8,
    }
    values.update(changes)
    return DynamicRiskModelConfig(**values)  # type: ignore[arg-type]


def _reference_iewma(
    values: np.ndarray[tuple[int, int], np.dtype[np.float64]],
    *,
    volatility_half_life: int,
    correlation_half_life: int,
    seed_count: int,
    clip: float,
    annualization: int,
) -> tuple[np.ndarray[tuple[int, int], np.dtype[np.float64]], int]:
    beta_vol = 2.0 ** (-1.0 / volatility_half_life)
    beta_corr = 2.0 ** (-1.0 / correlation_half_life)
    seed_weights = beta_vol ** np.arange(seed_count - 1, -1, -1, dtype=np.float64)
    numerator = np.sum(seed_weights[:, None] * values[:seed_count] ** 2, axis=0)
    denominator = float(np.sum(seed_weights))
    standardized: list[np.ndarray[tuple[int], np.dtype[np.float64]]] = []
    clipped_count = 0
    for row in values[seed_count:]:
        prior_sigma = np.sqrt(numerator / denominator)
        raw_z = row / prior_sigma
        clipped_z = np.clip(raw_z, -clip, clip)
        clipped_count += int(np.count_nonzero(raw_z != clipped_z))
        standardized.append(clipped_z)
        numerator = beta_vol * numerator + row**2
        denominator = beta_vol * denominator + 1.0
    z_values = np.asarray(standardized, dtype=np.float64)
    corr_weights = beta_corr ** np.arange(len(z_values) - 1, -1, -1, dtype=np.float64)
    corr_weights /= np.sum(corr_weights)
    q_matrix = (z_values * corr_weights[:, None]).T @ z_values
    scale = np.sqrt(np.diag(q_matrix))
    correlation = q_matrix / np.outer(scale, scale)
    np.fill_diagonal(correlation, 1.0)
    forecast_variance = numerator / denominator
    daily_covariance = np.outer(np.sqrt(forecast_variance), np.sqrt(forecast_variance))
    daily_covariance *= correlation
    np.fill_diagonal(daily_covariance, forecast_variance)
    return daily_covariance * annualization, clipped_count


def test_default_config_estimates_exactly_four_scenarios_in_fixed_order() -> None:
    matrix = _matrix()

    snapshot = DynamicRiskModel().estimate(matrix, as_of_date=matrix.dates[-1])

    assert tuple(scenario.kind for scenario in snapshot.scenarios) == tuple(CovarianceScenarioKind)
    assert snapshot.stock_codes == _CODES
    assert snapshot.consumed_observation_count == 504
    assert snapshot.as_of_date == matrix.dates[-1]


def test_iewma_matches_independent_finite_history_reference() -> None:
    config = _small_config()
    matrix = _matrix(12)
    values = np.asarray(matrix.values, dtype=np.float64)

    snapshot = DynamicRiskModel(config).estimate(matrix, as_of_date=matrix.dates[-1])
    scenario = snapshot.get_scenario(CovarianceScenarioKind.FAST_IEWMA)
    expected, clipped_count = _reference_iewma(
        values,
        volatility_half_life=config.fast_volatility_half_life,
        correlation_half_life=config.fast_correlation_half_life,
        seed_count=2,
        clip=config.standardized_return_clip,
        annualization=config.annualization_days,
    )

    np.testing.assert_allclose(np.asarray(scenario.annualized_covariance), expected, rtol=1e-12)
    metadata = cast(IewmaMetadata, scenario.metadata)
    assert metadata.clipped_scalar_count == clipped_count
    assert metadata.correlation_observation_count == 10
    assert np.diag(np.asarray(scenario.correlation_matrix)) == pytest.approx((1.0, 1.0))


def test_beta_half_life_normalized_weights_and_ess_reference() -> None:
    half_life = 21
    beta = ewma_beta(half_life)
    count = 50
    raw_weights = beta ** np.arange(count - 1, -1, -1, dtype=np.float64)
    weights = raw_weights / raw_weights.sum()

    assert beta**half_life == pytest.approx(0.5)
    assert weights.sum() == pytest.approx(1.0)
    assert weights[-1 - half_life] / weights[-1] == pytest.approx(0.5)
    assert normalized_ewma_effective_sample_size(beta, count) == pytest.approx(
        1.0 / np.sum(weights**2)
    )


def test_causal_standardization_uses_prior_sigma_and_raw_outlier_updates_forecast() -> None:
    config = _small_config()
    base = list(_default_values(12))
    shocked = list(base)
    shocked[-1] = (Decimal("0.80"), Decimal("-0.70"))
    base_matrix = _matrix(12, values=tuple(base))
    shock_matrix = _matrix(12, values=tuple(shocked))

    base_fast = (
        DynamicRiskModel(config)
        .estimate(base_matrix, as_of_date=base_matrix.dates[-1])
        .get_scenario(CovarianceScenarioKind.FAST_IEWMA)
    )
    shock_fast = (
        DynamicRiskModel(config)
        .estimate(shock_matrix, as_of_date=shock_matrix.dates[-1])
        .get_scenario(CovarianceScenarioKind.FAST_IEWMA)
    )
    expected, clipped_count = _reference_iewma(
        np.asarray(shock_matrix.values, dtype=np.float64),
        volatility_half_life=2,
        correlation_half_life=4,
        seed_count=2,
        clip=4.2,
        annualization=252,
    )

    np.testing.assert_allclose(np.asarray(shock_fast.annualized_covariance), expected, rtol=1e-12)
    assert cast(IewmaMetadata, shock_fast.metadata).clipped_scalar_count == clipped_count
    assert shock_fast.annualized_covariance[0][0] > base_fast.annualized_covariance[0][0]
    assert shock_fast.annualized_covariance[1][1] > base_fast.annualized_covariance[1][1]


def test_clip_boundary_counts_only_values_strictly_outside_plus_or_minus_4_2() -> None:
    seed = (
        (Decimal("-0.01"), Decimal("-0.02")),
        (Decimal("0.01"), Decimal("0.02")),
    )
    tail = tuple((Decimal("0.001"), Decimal("-0.001")) for _ in range(9))
    at_boundary = _matrix(
        12,
        values=(*seed, (Decimal("0.042"), Decimal("-0.084")), *tail),
    )
    outside = _matrix(
        12,
        values=(*seed, (Decimal("0.042001"), Decimal("-0.084001")), *tail),
    )

    boundary_metadata = cast(
        IewmaMetadata,
        DynamicRiskModel(_small_config())
        .estimate(at_boundary, as_of_date=at_boundary.dates[-1])
        .get_scenario(CovarianceScenarioKind.FAST_IEWMA)
        .metadata,
    )
    outside_metadata = cast(
        IewmaMetadata,
        DynamicRiskModel(_small_config())
        .estimate(outside, as_of_date=outside.dates[-1])
        .get_scenario(CovarianceScenarioKind.FAST_IEWMA)
        .metadata,
    )

    assert boundary_metadata.clipped_scalar_count == 0
    assert outside_metadata.clipped_scalar_count == 2


def test_recent_volatility_shock_affects_fast_more_than_slow() -> None:
    values = list(_default_values(504))
    for index in range(494, 504):
        values[index] = (
            Decimal(index % 2 * 2 - 1) * Decimal("0.20"),
            Decimal(index % 2 * 2 - 1) * Decimal("0.25"),
        )
    matrix = _matrix(values=tuple(values))

    snapshot = DynamicRiskModel().estimate(matrix, as_of_date=matrix.dates[-1])
    fast = snapshot.get_scenario(CovarianceScenarioKind.FAST_IEWMA)
    slow = snapshot.get_scenario(CovarianceScenarioKind.SLOW_IEWMA)

    assert all(
        fast_value > slow_value
        for fast_value, slow_value in zip(
            fast.annualized_volatilities,
            slow.annualized_volatilities,
            strict=True,
        )
    )


def test_correlation_half_life_is_applied_separately() -> None:
    values: list[tuple[Decimal, Decimal]] = []
    for index in range(12):
        first = Decimal(index % 3 - 1) / Decimal("100")
        second = first if index < 6 else -first
        if first == 0:
            first = Decimal("0.002")
            second = first if index < 6 else -first
        values.append((first, second))
    matrix = _matrix(12, values=tuple(values))
    short_corr = _small_config(fast_correlation_half_life=3)
    long_corr = _small_config(fast_correlation_half_life=4)

    short_value = (
        DynamicRiskModel(short_corr)
        .estimate(matrix, as_of_date=matrix.dates[-1])
        .get_scenario(CovarianceScenarioKind.FAST_IEWMA)
        .correlation_matrix[0][1]
    )
    long_value = (
        DynamicRiskModel(long_corr)
        .estimate(matrix, as_of_date=matrix.dates[-1])
        .get_scenario(CovarianceScenarioKind.FAST_IEWMA)
        .correlation_matrix[0][1]
    )

    assert short_value < long_value


def test_ledoit_wolf_matches_direct_sklearn_zero_centered_fit() -> None:
    config = _small_config()
    matrix = _matrix(12)
    values = np.asarray(matrix.values, dtype=np.float64)
    expected_estimator = LedoitWolf(assume_centered=True, store_precision=False).fit(values)

    scenario = (
        DynamicRiskModel(config)
        .estimate(matrix, as_of_date=matrix.dates[-1])
        .get_scenario(CovarianceScenarioKind.LONG_RUN_LEDOIT_WOLF)
    )

    np.testing.assert_allclose(
        np.asarray(scenario.annualized_covariance),
        expected_estimator.covariance_ * 252,
        rtol=1e-13,
    )
    metadata = cast(LedoitWolfMetadata, scenario.metadata)
    assert metadata.shrinkage == pytest.approx(expected_estimator.shrinkage_)
    assert 0 <= metadata.shrinkage <= 1
    assert metadata.assume_centered is True
    assert metadata.store_precision is False


def test_downside_selects_exact_worst_k_dates_with_date_tie_break() -> None:
    config = _small_config()
    averages = (-5, -1, -3, -3, 2, 1, -2, 3, 4, 5, 6, 7)
    values = tuple(
        (
            Decimal(average) / Decimal("100") + Decimal("0.001"),
            Decimal(average) / Decimal("100") - Decimal("0.001"),
        )
        for average in averages
    )
    matrix = _matrix(12, values=values)

    scenario = (
        DynamicRiskModel(config)
        .estimate(matrix, as_of_date=matrix.dates[-1])
        .get_scenario(CovarianceScenarioKind.DOWNSIDE_STRESS_LEDOIT_WOLF)
    )
    metadata = cast(DownsideStressMetadata, scenario.metadata)
    ranked = sorted((Decimal(value), matrix.dates[index]) for index, value in enumerate(averages))
    expected_dates = tuple(item[1] for item in ranked[:6])
    selected_indices = tuple(matrix.dates.index(value) for value in expected_dates)
    selected = np.asarray(matrix.values, dtype=np.float64)[list(selected_indices)]
    direct = LedoitWolf(assume_centered=True, store_precision=False).fit(selected)

    assert metadata.selected_count == 6
    assert metadata.selected_dates == expected_dates
    assert metadata.cutoff_equal_weight_return == ranked[5][0] / Decimal("100")
    assert metadata.assume_centered is True
    np.testing.assert_allclose(
        np.asarray(scenario.annualized_covariance),
        direct.covariance_ * 252,
        rtol=1e-13,
    )


def test_future_rows_do_not_change_result_or_consumed_fingerprint() -> None:
    matrix = _matrix(600)
    as_of = matrix.dates[503]
    changed = list(matrix.values)
    changed[504:] = [(Decimal("1000000"), Decimal("-999999"))] * 96
    future_changed = _matrix(600, values=tuple(changed))

    original = DynamicRiskModel().estimate(matrix, as_of_date=as_of)
    modified = DynamicRiskModel().estimate(future_changed, as_of_date=as_of)

    assert modified == original
    assert modified.consumed_input_fingerprint == original.consumed_input_fingerprint


def test_rows_older_than_trailing_756_do_not_change_result_or_fingerprint() -> None:
    matrix = _matrix(800)
    changed = list(matrix.values)
    changed[:44] = [(Decimal("0.9"), Decimal("-0.8"))] * 44
    older_changed = _matrix(800, values=tuple(changed))

    original = DynamicRiskModel().estimate(matrix, as_of_date=matrix.dates[-1])
    modified = DynamicRiskModel().estimate(older_changed, as_of_date=matrix.dates[-1])

    assert original.consumed_observation_count == 756
    assert modified == original


def test_consumed_last_observation_changes_forecast_and_fingerprint() -> None:
    matrix = _matrix()
    changed = list(matrix.values)
    changed[-1] = (Decimal("0.20"), Decimal("-0.15"))
    changed_matrix = _matrix(values=tuple(changed))

    original = DynamicRiskModel().estimate(matrix, as_of_date=matrix.dates[-1])
    modified = DynamicRiskModel().estimate(changed_matrix, as_of_date=matrix.dates[-1])

    assert original.consumed_input_fingerprint != modified.consumed_input_fingerprint
    assert original.scenarios != modified.scenarios


def test_503_observations_fail_while_504_succeed() -> None:
    short = _matrix(503)
    enough = _matrix(504)

    with pytest.raises(InsufficientRiskHistoryError, match="503"):
        DynamicRiskModel().estimate(short, as_of_date=short.dates[-1])
    assert (
        DynamicRiskModel().estimate(enough, as_of_date=enough.dates[-1]).consumed_observation_count
        == 504
    )


def test_insufficient_correlation_and_downside_subsets_have_dedicated_errors() -> None:
    matrix = _matrix(12)

    with pytest.raises(InsufficientCorrelationHistoryError, match="상관관계"):
        DynamicRiskModel(_small_config(minimum_correlation_observations=20)).estimate(
            matrix,
            as_of_date=matrix.dates[-1],
        )
    with pytest.raises(InsufficientDownsideHistoryError, match="하방"):
        DynamicRiskModel(_small_config(downside_fraction=Decimal("0.10"))).estimate(
            matrix,
            as_of_date=matrix.dates[-1],
        )


def test_zero_seed_variance_fails_even_when_later_returns_vary() -> None:
    values = list(_default_values(12))
    values[0] = (Decimal(0), values[0][1])
    values[1] = (Decimal(0), values[1][1])
    matrix = _matrix(12, values=tuple(values))

    with pytest.raises(DegenerateRiskSeriesError, match="005930"):
        DynamicRiskModel(_small_config()).estimate(matrix, as_of_date=matrix.dates[-1])


def test_missing_as_of_date_is_rejected() -> None:
    matrix = _matrix()

    with pytest.raises(RiskModelAsOfDateNotFoundError, match="기준일"):
        DynamicRiskModel().estimate(matrix, as_of_date=date(1999, 1, 1))


def test_estimate_is_deterministic_and_does_not_mutate_input_or_global_state() -> None:
    matrix = _matrix()
    original_matrix = matrix
    decimal_precision = getcontext().prec
    numpy_error_state = np.geterr().copy()

    first = DynamicRiskModel().estimate(matrix, as_of_date=matrix.dates[-1])
    second = DynamicRiskModel().estimate(matrix, as_of_date=matrix.dates[-1])

    assert first == second
    assert matrix == original_matrix
    assert getcontext().prec == decimal_precision
    assert np.geterr() == numpy_error_state


def test_decimal_precision_does_not_change_estimator_result() -> None:
    matrix = _matrix()

    with localcontext() as context:
        context.prec = 6
        low_precision = DynamicRiskModel().estimate(matrix, as_of_date=matrix.dates[-1])
    with localcontext() as context:
        context.prec = 80
        high_precision = DynamicRiskModel().estimate(matrix, as_of_date=matrix.dates[-1])

    assert low_precision == high_precision


def test_stock_permutation_is_covariance_equivariant() -> None:
    matrix = _matrix()
    permuted = AlignedReturnMatrix(
        stock_codes=tuple(reversed(matrix.stock_codes)),
        dates=matrix.dates,
        values=tuple(tuple(reversed(row)) for row in matrix.values),
    )

    original = DynamicRiskModel().estimate(matrix, as_of_date=matrix.dates[-1])
    changed = DynamicRiskModel().estimate(permuted, as_of_date=permuted.dates[-1])

    for kind in CovarianceScenarioKind:
        expected = np.asarray(original.get_scenario(kind).annualized_covariance)[::-1, ::-1]
        actual = np.asarray(changed.get_scenario(kind).annualized_covariance)
        np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-15)


def test_iewma_asset_scaling_changes_covariance_but_not_correlation() -> None:
    matrix = _matrix()
    scale = Decimal("3")
    scaled = AlignedReturnMatrix(
        stock_codes=matrix.stock_codes,
        dates=matrix.dates,
        values=tuple((row[0] * scale, row[1]) for row in matrix.values),
    )

    original = (
        DynamicRiskModel()
        .estimate(matrix, as_of_date=matrix.dates[-1])
        .get_scenario(CovarianceScenarioKind.FAST_IEWMA)
    )
    changed = (
        DynamicRiskModel()
        .estimate(scaled, as_of_date=scaled.dates[-1])
        .get_scenario(CovarianceScenarioKind.FAST_IEWMA)
    )

    assert changed.annualized_covariance[0][0] == pytest.approx(
        original.annualized_covariance[0][0] * 9
    )
    assert changed.annualized_covariance[0][1] == pytest.approx(
        original.annualized_covariance[0][1] * 3
    )
    np.testing.assert_allclose(changed.correlation_matrix, original.correlation_matrix, atol=1e-13)


def test_annualization_is_applied_once_and_volatility_uses_square_root() -> None:
    matrix = _matrix()
    full = DynamicRiskModel().estimate(matrix, as_of_date=matrix.dates[-1])
    half = DynamicRiskModel(DynamicRiskModelConfig(annualization_days=126)).estimate(
        matrix, as_of_date=matrix.dates[-1]
    )

    for kind in CovarianceScenarioKind:
        full_scenario = full.get_scenario(kind)
        half_scenario = half.get_scenario(kind)
        np.testing.assert_allclose(
            np.asarray(full_scenario.annualized_covariance),
            np.asarray(half_scenario.annualized_covariance) * 2,
            rtol=1e-12,
        )
        np.testing.assert_allclose(
            np.asarray(full_scenario.annualized_volatilities),
            np.asarray(half_scenario.annualized_volatilities) * math.sqrt(2),
            rtol=1e-12,
        )
        np.testing.assert_allclose(
            full_scenario.correlation_matrix,
            half_scenario.correlation_matrix,
            rtol=1e-12,
        )


def test_one_asset_and_perfect_collinearity_preserve_rank_deficiency_without_ridge() -> None:
    single_values = tuple((row[0],) for row in _default_values(504))
    single = _matrix(504, values=single_values, codes=("005930",))
    collinear_values = tuple((row[0], row[0] * Decimal("2")) for row in _default_values(504))
    collinear = _matrix(504, values=collinear_values)

    single_snapshot = DynamicRiskModel().estimate(single, as_of_date=single.dates[-1])
    collinear_snapshot = DynamicRiskModel().estimate(collinear, as_of_date=collinear.dates[-1])

    assert all(scenario.correlation_matrix == ((1.0,),) for scenario in single_snapshot.scenarios)
    fast = collinear_snapshot.get_scenario(CovarianceScenarioKind.FAST_IEWMA)
    assert fast.psd_diagnostics.rank == 1
    assert fast.psd_diagnostics.condition_number is None


def test_constant_or_zero_variance_series_raises_stock_specific_error() -> None:
    values = tuple((Decimal("0.01"), row[1]) for row in _default_values(504))
    matrix = _matrix(values=values)

    with pytest.raises(DegenerateRiskSeriesError, match="005930"):
        DynamicRiskModel().estimate(matrix, as_of_date=matrix.dates[-1])


@pytest.mark.parametrize("scale", (Decimal("1e-90"), Decimal("1e90")))
def test_extreme_but_finite_scales_remain_finite(scale: Decimal) -> None:
    values = tuple((row[0] * scale, row[1] * scale) for row in _default_values(504))
    matrix = _matrix(values=values)

    snapshot = DynamicRiskModel().estimate(matrix, as_of_date=matrix.dates[-1])

    assert all(
        math.isfinite(value)
        for scenario in snapshot.scenarios
        for row in scenario.annualized_covariance
        for value in row
    )
