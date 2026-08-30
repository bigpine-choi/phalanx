"""Pure, causal covariance forecasts over one aligned Decimal return matrix."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

import numpy as np
from numpy.typing import NDArray
from sklearn.covariance import LedoitWolf  # type: ignore[import-untyped]

from phalanx.domain import (
    DYNAMIC_RISK_MODEL_VERSION,
    RISK_MODEL_SCHEMA_VERSION,
    AlignedReturnMatrix,
    CovarianceScenario,
    CovarianceScenarioKind,
    DownsideStressMetadata,
    DynamicRiskModelConfig,
    DynamicRiskModelSnapshot,
    IewmaMetadata,
    LedoitWolfMetadata,
    PsdDiagnostics,
)
from phalanx.portfolio.errors import (
    DegenerateRiskSeriesError,
    InsufficientCorrelationHistoryError,
    InsufficientDownsideHistoryError,
    InsufficientRiskHistoryError,
    MateriallyIndefiniteCovarianceError,
    RiskModelAsOfDateNotFoundError,
    RiskModelNumericalError,
    RiskModelQualityError,
)

FloatMatrix = NDArray[np.float64]
_FINGERPRINT_DECIMAL_PRECISION = 50
_FLOAT_TINY = float(np.finfo(np.float64).tiny)


class DynamicRiskModel:
    """Estimate four fixed, independent next-return-period covariance scenarios."""

    def __init__(self, config: DynamicRiskModelConfig | None = None) -> None:
        self.config = DynamicRiskModelConfig() if config is None else config
        if not isinstance(self.config, DynamicRiskModelConfig):
            raise RiskModelNumericalError("위험모형 설정 타입이 올바르지 않습니다.")

    def estimate(
        self,
        matrix: AlignedReturnMatrix,
        *,
        as_of_date: date,
    ) -> DynamicRiskModelSnapshot:
        """Use only the finite trailing window ending on an existing as-of date."""

        if not isinstance(matrix, AlignedReturnMatrix):
            raise RiskModelNumericalError("위험모형 입력은 AlignedReturnMatrix여야 합니다.")
        if type(as_of_date) is not date or as_of_date not in matrix.dates:
            raise RiskModelAsOfDateNotFoundError(as_of_date)
        end_index = matrix.dates.index(as_of_date)
        available_count = end_index + 1
        if available_count < self.config.minimum_observations:
            raise InsufficientRiskHistoryError(
                available_count,
                self.config.minimum_observations,
                as_of_date=as_of_date,
            )
        start_index = max(0, available_count - self.config.maximum_observations)
        consumed_dates = matrix.dates[start_index : end_index + 1]
        consumed_values = matrix.values[start_index : end_index + 1]
        input_fingerprint = fingerprint_consumed_risk_input(
            matrix.stock_codes,
            consumed_dates,
            consumed_values,
            self.config,
        )
        downside_selection = _select_downside_rows(
            consumed_dates,
            consumed_values,
            self.config,
            as_of_date,
        )

        # This is the one Decimal -> NumPy float64 estimator boundary. Every
        # scenario below reuses this immutable T x N matrix.
        try:
            returns = np.asarray(consumed_values, dtype=np.float64, order="C")
        except (TypeError, ValueError, OverflowError):
            raise RiskModelNumericalError(
                "Decimal 수익률을 유한한 float64 통계 행렬로 변환하지 못했습니다."
            ) from None
        if returns.shape != (len(consumed_dates), len(matrix.stock_codes)) or not np.all(
            np.isfinite(returns)
        ):
            raise RiskModelNumericalError(
                "float64 통계 행렬의 shape 또는 유한성이 올바르지 않습니다."
            )
        returns.setflags(write=False)
        _reject_degenerate_series(returns, matrix.stock_codes)

        scenarios = (
            _estimate_ledoit_wolf(
                returns,
                matrix.stock_codes,
                consumed_dates,
                self.config,
                CovarianceScenarioKind.LONG_RUN_LEDOIT_WOLF,
            ),
            _estimate_iewma(
                returns,
                matrix.stock_codes,
                consumed_dates,
                self.config,
                CovarianceScenarioKind.FAST_IEWMA,
                self.config.fast_volatility_half_life,
                self.config.fast_correlation_half_life,
                as_of_date,
            ),
            _estimate_iewma(
                returns,
                matrix.stock_codes,
                consumed_dates,
                self.config,
                CovarianceScenarioKind.SLOW_IEWMA,
                self.config.slow_volatility_half_life,
                self.config.slow_correlation_half_life,
                as_of_date,
            ),
            _estimate_downside_ledoit_wolf(
                returns,
                matrix.stock_codes,
                consumed_dates,
                downside_selection,
                self.config,
            ),
        )
        return DynamicRiskModelSnapshot(
            as_of_date=as_of_date,
            consumed_start_date=consumed_dates[0],
            consumed_end_date=consumed_dates[-1],
            consumed_observation_count=len(consumed_dates),
            stock_codes=matrix.stock_codes,
            consumed_dates=consumed_dates,
            scenarios=scenarios,
            consumed_input_fingerprint=input_fingerprint,
        )


def ewma_beta(half_life: int) -> float:
    """Return beta whose H-period-old relative weight is exactly one half."""

    if type(half_life) is not int or half_life <= 0:
        raise RiskModelNumericalError("EWMA 반감기는 양의 정수여야 합니다.")
    return float(math.exp(math.log(0.5) / half_life))


def normalized_ewma_effective_sample_size(beta: float, count: int) -> float:
    """Return 1/sum(w²) for finite normalized geometric weights."""

    if not isinstance(beta, float) or not math.isfinite(beta) or not 0 < beta < 1:
        raise RiskModelNumericalError("EWMA beta는 0과 1 사이의 유한한 float여야 합니다.")
    if type(count) is not int or count <= 0:
        raise RiskModelNumericalError("EWMA ESS 관측치 수는 양의 정수여야 합니다.")
    denominator = (1.0 - beta**count) / (1.0 - beta)
    squared_denominator = (1.0 - beta ** (2 * count)) / (1.0 - beta**2)
    result = denominator * denominator / squared_denominator
    if not math.isfinite(result) or result <= 0:
        raise RiskModelNumericalError("EWMA 유효 표본 크기를 안전하게 계산하지 못했습니다.")
    return _clean_float(result)


def repair_numerical_psd(
    matrix: FloatMatrix,
    config: DynamicRiskModelConfig,
    *,
    correlation: bool = False,
) -> tuple[FloatMatrix, PsdDiagnostics]:
    """Project numerical-negative eigenvalues only; never add a positive ridge."""

    if not isinstance(matrix, np.ndarray) or matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
        raise RiskModelNumericalError("PSD 검사 입력은 정사각 NumPy 행렬이어야 합니다.")
    if matrix.shape[0] == 0 or not np.all(np.isfinite(matrix)):
        raise RiskModelNumericalError("PSD 검사 입력은 비어 있지 않은 유한한 행렬이어야 합니다.")
    size = matrix.shape[0]
    symmetric = np.asarray((matrix + matrix.T) / 2.0, dtype=np.float64)
    try:
        eigenvalues, eigenvectors = np.linalg.eigh(symmetric)
    except np.linalg.LinAlgError:
        raise RiskModelNumericalError("PSD 고윳값 분해를 완료하지 못했습니다.") from None
    if not np.all(np.isfinite(eigenvalues)):
        raise RiskModelNumericalError("PSD 고윳값에 유한하지 않은 값이 있습니다.")
    diagonal = np.diag(symmetric)
    scale = max(
        float(np.trace(symmetric) / size),
        float(np.max(np.abs(diagonal))),
        _FLOAT_TINY,
    )
    tolerance = max(
        config.psd_absolute_eigen_tolerance,
        config.psd_relative_eigen_tolerance * scale,
    )
    minimum_before = float(eigenvalues[0])
    if minimum_before < -tolerance:
        raise MateriallyIndefiniteCovarianceError(minimum_before, tolerance)

    projected = symmetric
    if minimum_before < 0:
        clipped_eigenvalues = np.maximum(eigenvalues, 0.0)
        projected = np.asarray(
            (eigenvectors * clipped_eigenvalues) @ eigenvectors.T,
            dtype=np.float64,
        )
        projected = (projected + projected.T) / 2.0

    if correlation:
        projected = _renormalize_correlation(projected)
        projected = _project_post_normalization_noise(projected, tolerance)
        projected = _renormalize_correlation(projected)

    if not np.all(np.isfinite(projected)):
        raise RiskModelNumericalError("PSD 보정 결과에 유한하지 않은 값이 있습니다.")
    try:
        final_eigenvalues = np.linalg.eigvalsh(projected)
    except np.linalg.LinAlgError:
        raise RiskModelNumericalError("PSD 보정 결과 고윳값을 계산하지 못했습니다.") from None
    minimum_after = float(final_eigenvalues[0])
    if minimum_after < -tolerance:
        raise MateriallyIndefiniteCovarianceError(minimum_after, tolerance)

    repair_norm = _stable_frobenius_norm(projected - symmetric)
    original_norm = _stable_frobenius_norm(symmetric)
    relative_repair = repair_norm / max(original_norm, _FLOAT_TINY)
    if not math.isfinite(relative_repair):
        raise RiskModelNumericalError("PSD 상대 보정 크기를 계산하지 못했습니다.")
    if relative_repair > config.maximum_relative_psd_repair:
        raise RiskModelQualityError(
            "PSD 상대 보정 크기가 품질 상한을 넘습니다: "
            f"{relative_repair:.6g} (상한 {config.maximum_relative_psd_repair:.6g})."
        )
    rank = int(np.count_nonzero(final_eigenvalues > tolerance))
    condition_number: float | None = None
    if rank == size and minimum_after > tolerance:
        condition_number = _clean_float(float(final_eigenvalues[-1] / minimum_after))
    diagnostics = PsdDiagnostics(
        minimum_eigenvalue_before=_clean_float(minimum_before),
        minimum_eigenvalue_after=_clean_float(minimum_after),
        maximum_eigenvalue_after=_clean_float(float(final_eigenvalues[-1])),
        numerical_tolerance=_clean_float(tolerance),
        rank=rank,
        condition_number=condition_number,
        frobenius_repair_norm=_clean_float(repair_norm),
        relative_repair_norm=_clean_float(relative_repair),
        repaired=bool(repair_norm > 0.0),
    )
    projected.setflags(write=False)
    return projected, diagnostics


def fingerprint_consumed_risk_input(
    stock_codes: tuple[str, ...],
    dates: tuple[date, ...],
    values: tuple[tuple[Decimal, ...], ...],
    config: DynamicRiskModelConfig,
) -> str:
    """Fingerprint only the original Decimal observations actually consumed."""

    payload = {
        "schema_version": RISK_MODEL_SCHEMA_VERSION,
        "model_version": DYNAMIC_RISK_MODEL_VERSION,
        "config": risk_model_config_payload(config),
        "stock_codes": list(stock_codes),
        "dates": [value.isoformat() for value in dates],
        "values": [[canonical_decimal(value) for value in row] for row in values],
    }
    return _fingerprint(payload)


def risk_model_config_payload(config: DynamicRiskModelConfig) -> dict[str, object]:
    """Return the canonical public v1 configuration projection."""

    return {
        "minimum_observations": config.minimum_observations,
        "maximum_observations": config.maximum_observations,
        "rebalance_interval": config.rebalance_interval,
        "annualization_days": config.annualization_days,
        "fast_volatility_half_life": config.fast_volatility_half_life,
        "fast_correlation_half_life": config.fast_correlation_half_life,
        "slow_volatility_half_life": config.slow_volatility_half_life,
        "slow_correlation_half_life": config.slow_correlation_half_life,
        "standardized_return_clip": config.standardized_return_clip,
        "minimum_volatility_seed_observations": config.minimum_volatility_seed_observations,
        "minimum_correlation_observations": config.minimum_correlation_observations,
        "downside_fraction": canonical_decimal(config.downside_fraction),
        "minimum_downside_observations": config.minimum_downside_observations,
        "psd_relative_eigen_tolerance": config.psd_relative_eigen_tolerance,
        "psd_absolute_eigen_tolerance": config.psd_absolute_eigen_tolerance,
        "maximum_relative_psd_repair": config.maximum_relative_psd_repair,
    }


def canonical_decimal(value: Decimal) -> str:
    """Canonical fixed-point Decimal text shared by risk fingerprints and JSON."""

    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def _estimate_ledoit_wolf(
    returns: FloatMatrix,
    stock_codes: tuple[str, ...],
    dates: tuple[date, ...],
    config: DynamicRiskModelConfig,
    kind: CovarianceScenarioKind,
) -> CovarianceScenario:
    covariance, shrinkage = _fit_ledoit_wolf(returns)
    return _scenario_from_daily_covariance(
        kind,
        stock_codes,
        dates,
        covariance,
        LedoitWolfMetadata(shrinkage=shrinkage),
        config,
    )


def _estimate_downside_ledoit_wolf(
    returns: FloatMatrix,
    stock_codes: tuple[str, ...],
    dates: tuple[date, ...],
    selection: tuple[tuple[int, ...], Decimal, tuple[date, ...], str],
    config: DynamicRiskModelConfig,
) -> CovarianceScenario:
    selected_indices, cutoff, selected_dates, selected_fingerprint = selection
    selected_returns = np.asarray(
        returns[np.asarray(selected_indices, dtype=np.intp)], dtype=np.float64
    )
    covariance, shrinkage = _fit_ledoit_wolf(selected_returns)
    metadata = DownsideStressMetadata(
        downside_fraction=config.downside_fraction,
        selected_count=len(selected_indices),
        cutoff_equal_weight_return=cutoff,
        selected_dates=selected_dates,
        selected_dates_fingerprint=selected_fingerprint,
        shrinkage=shrinkage,
    )
    return _scenario_from_daily_covariance(
        CovarianceScenarioKind.DOWNSIDE_STRESS_LEDOIT_WOLF,
        stock_codes,
        dates,
        covariance,
        metadata,
        config,
    )


def _estimate_iewma(
    returns: FloatMatrix,
    stock_codes: tuple[str, ...],
    dates: tuple[date, ...],
    config: DynamicRiskModelConfig,
    kind: CovarianceScenarioKind,
    volatility_half_life: int,
    correlation_half_life: int,
    as_of_date: date,
) -> CovarianceScenario:
    observation_count, stock_count = returns.shape
    seed_count = max(config.minimum_volatility_seed_observations, stock_count)
    if seed_count >= observation_count:
        raise InsufficientCorrelationHistoryError(
            max(0, observation_count - seed_count),
            max(config.minimum_correlation_observations, 3 * stock_count),
            as_of_date=as_of_date,
        )
    volatility_beta = ewma_beta(volatility_half_life)
    correlation_beta = ewma_beta(correlation_half_life)
    seed_ages = np.arange(seed_count - 1, -1, -1, dtype=np.float64)
    seed_weights = np.power(volatility_beta, seed_ages)
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        squared_seed = returns[:seed_count] * returns[:seed_count]
        numerator = np.sum(seed_weights[:, None] * squared_seed, axis=0)
    if not np.all(np.isfinite(numerator)):
        raise RiskModelNumericalError("IEWMA 초기 변동성 상태를 유한하게 계산하지 못했습니다.")
    denominator = float(np.sum(seed_weights))
    variance = numerator / denominator
    for index, value in enumerate(variance):
        if not math.isfinite(float(value)) or value <= 0:
            raise DegenerateRiskSeriesError(stock_codes[index])

    # Retain the unnormalized numerator and denominator so each update remains
    # exactly equivalent to one finite-history normalized EWMA over all data.
    standardized_rows: list[FloatMatrix] = []
    clipped_scalar_count = 0
    for row_index in range(seed_count, observation_count):
        prior_variance = numerator / denominator
        if not np.all(np.isfinite(prior_variance)) or np.any(prior_variance <= 0):
            failing_index = int(np.flatnonzero(prior_variance <= 0)[0])
            raise DegenerateRiskSeriesError(stock_codes[failing_index])
        prior_sigma = np.sqrt(prior_variance)
        raw_return = returns[row_index]
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            standardized = raw_return / prior_sigma
        if not np.all(np.isfinite(standardized)):
            raise RiskModelNumericalError(
                "IEWMA 사전 변동성 표준화를 유한하게 계산하지 못했습니다."
            )
        clipped = np.clip(
            standardized,
            -config.standardized_return_clip,
            config.standardized_return_clip,
        )
        clipped_scalar_count += int(np.count_nonzero(clipped != standardized))
        standardized_rows.append(np.asarray(clipped, dtype=np.float64))

        # Raw, unclipped r_t² enters only after z_t was formed with prior sigma_t.
        with np.errstate(over="ignore", invalid="ignore"):
            numerator = volatility_beta * numerator + raw_return * raw_return
            denominator = volatility_beta * denominator + 1.0
        if not np.all(np.isfinite(numerator)) or not math.isfinite(denominator):
            raise RiskModelNumericalError("IEWMA raw 변동성 update를 유한하게 계산하지 못했습니다.")

    correlation_observation_count = len(standardized_rows)
    minimum_correlation = max(config.minimum_correlation_observations, 3 * stock_count)
    if correlation_observation_count < minimum_correlation:
        raise InsufficientCorrelationHistoryError(
            correlation_observation_count,
            minimum_correlation,
            as_of_date=as_of_date,
        )
    standardized_matrix = np.asarray(standardized_rows, dtype=np.float64)
    correlation_weights = _normalized_geometric_weights(
        correlation_beta,
        correlation_observation_count,
    )
    with np.errstate(over="ignore", invalid="ignore"):
        q_matrix = (standardized_matrix * correlation_weights[:, None]).T @ standardized_matrix
    if not np.all(np.isfinite(q_matrix)):
        raise RiskModelNumericalError(
            "IEWMA 상관관계 second moment를 유한하게 계산하지 못했습니다."
        )
    q_diagonal = np.diag(q_matrix)
    for index, value in enumerate(q_diagonal):
        if value <= 0 or not math.isfinite(float(value)):
            raise DegenerateRiskSeriesError(stock_codes[index])
    inverse_scale = 1.0 / np.sqrt(q_diagonal)
    correlation = q_matrix * np.outer(inverse_scale, inverse_scale)
    np.fill_diagonal(correlation, 1.0)
    correlation, correlation_diagnostics = repair_numerical_psd(
        np.asarray(correlation, dtype=np.float64),
        config,
        correlation=True,
    )

    forecast_variance = numerator / denominator
    if not np.all(np.isfinite(forecast_variance)) or np.any(forecast_variance <= 0):
        failing_index = int(np.flatnonzero(forecast_variance <= 0)[0])
        raise DegenerateRiskSeriesError(stock_codes[failing_index])
    forecast_sigma = np.sqrt(forecast_variance)
    daily_covariance = np.outer(forecast_sigma, forecast_sigma) * correlation
    np.fill_diagonal(daily_covariance, forecast_variance)
    metadata = IewmaMetadata(
        volatility_half_life=volatility_half_life,
        correlation_half_life=correlation_half_life,
        volatility_seed_count=seed_count,
        correlation_observation_count=correlation_observation_count,
        volatility_effective_sample_size=normalized_ewma_effective_sample_size(
            volatility_beta,
            observation_count,
        ),
        correlation_effective_sample_size=normalized_ewma_effective_sample_size(
            correlation_beta,
            correlation_observation_count,
        ),
        clip_threshold=config.standardized_return_clip,
        clipped_scalar_count=clipped_scalar_count,
        correlation_psd_diagnostics=correlation_diagnostics,
    )
    return _scenario_from_daily_covariance(
        kind,
        stock_codes,
        dates,
        np.asarray(daily_covariance, dtype=np.float64),
        metadata,
        config,
    )


def _fit_ledoit_wolf(returns: FloatMatrix) -> tuple[FloatMatrix, float]:
    maximum_absolute_return = float(np.max(np.abs(returns)))
    if not math.isfinite(maximum_absolute_return) or maximum_absolute_return <= 0:
        raise RiskModelNumericalError("Ledoit-Wolf 입력 규모가 유한한 양수가 아닙니다.")
    scale = (
        maximum_absolute_return
        if maximum_absolute_return > 1e50 or maximum_absolute_return < 1e-50
        else 1.0
    )
    fitted_returns = np.asarray(returns / scale, dtype=np.float64)
    try:
        estimator = LedoitWolf(assume_centered=True, store_precision=False).fit(fitted_returns)
    except (ValueError, FloatingPointError, np.linalg.LinAlgError):
        raise RiskModelNumericalError(
            "Ledoit-Wolf second moment 추정을 완료하지 못했습니다."
        ) from None
    with np.errstate(over="ignore", invalid="ignore"):
        covariance = np.asarray(estimator.covariance_ * scale * scale, dtype=np.float64)
    shrinkage = float(estimator.shrinkage_)
    if covariance.shape != (returns.shape[1], returns.shape[1]) or not np.all(
        np.isfinite(covariance)
    ):
        raise RiskModelNumericalError("Ledoit-Wolf 공분산 shape 또는 유한성이 올바르지 않습니다.")
    if not math.isfinite(shrinkage) or not 0 <= shrinkage <= 1:
        raise RiskModelNumericalError("Ledoit-Wolf shrinkage가 0과 1 사이가 아닙니다.")
    return covariance, _clean_float(shrinkage)


def _scenario_from_daily_covariance(
    kind: CovarianceScenarioKind,
    stock_codes: tuple[str, ...],
    dates: tuple[date, ...],
    daily_covariance: FloatMatrix,
    metadata: LedoitWolfMetadata | IewmaMetadata | DownsideStressMetadata,
    config: DynamicRiskModelConfig,
) -> CovarianceScenario:
    if not np.all(np.isfinite(daily_covariance)):
        raise RiskModelNumericalError("일별 공분산에 유한하지 않은 값이 있습니다.")
    with np.errstate(over="ignore", invalid="ignore"):
        annualized = np.asarray(
            daily_covariance * float(config.annualization_days),
            dtype=np.float64,
        )
    if not np.all(np.isfinite(annualized)):
        raise RiskModelNumericalError("공분산 연환산 결과가 float64 범위를 벗어났습니다.")
    repaired_covariance, diagnostics = repair_numerical_psd(annualized, config)
    diagonal = np.diag(repaired_covariance)
    if np.any(diagonal <= 0) or not np.all(np.isfinite(diagonal)):
        raise RiskModelNumericalError("연환산 공분산 대각원소는 양수여야 합니다.")
    volatilities = np.sqrt(diagonal)
    correlation = repaired_covariance / np.outer(volatilities, volatilities)
    correlation = np.asarray((correlation + correlation.T) / 2.0, dtype=np.float64)
    np.fill_diagonal(correlation, 1.0)
    if (
        not np.all(np.isfinite(correlation))
        or np.any(correlation < -1 - 1e-10)
        or np.any(correlation > 1 + 1e-10)
    ):
        raise RiskModelNumericalError("공분산에서 일관된 상관계수를 계산하지 못했습니다.")
    return CovarianceScenario(
        kind=kind,
        stock_codes=stock_codes,
        observation_dates=dates,
        annualized_covariance=_matrix_to_tuple(repaired_covariance),
        annualized_volatilities=tuple(_clean_float(float(value)) for value in volatilities),
        correlation_matrix=_matrix_to_tuple(correlation),
        metadata=metadata,
        psd_diagnostics=diagnostics,
    )


def _select_downside_rows(
    dates: tuple[date, ...],
    values: tuple[tuple[Decimal, ...], ...],
    config: DynamicRiskModelConfig,
    as_of_date: date,
) -> tuple[tuple[int, ...], Decimal, tuple[date, ...], str]:
    stock_count = len(values[0])
    decimal_context = Context(prec=_FINGERPRINT_DECIMAL_PRECISION, rounding=ROUND_HALF_EVEN)
    with localcontext(decimal_context):
        ranked = sorted(
            (
                sum(row, Decimal(0)) / Decimal(stock_count),
                dates[index],
                index,
            )
            for index, row in enumerate(values)
        )
        selected_count = int(
            (config.downside_fraction * Decimal(len(values))).to_integral_value(
                rounding="ROUND_CEILING"
            )
        )
    required = max(config.minimum_downside_observations, stock_count + 2)
    if selected_count < required:
        raise InsufficientDownsideHistoryError(selected_count, required, as_of_date=as_of_date)
    selected = ranked[:selected_count]
    selected_indices = tuple(item[2] for item in selected)
    selected_dates = tuple(item[1] for item in selected)
    cutoff = selected[-1][0]
    selected_fingerprint = _fingerprint(
        {
            "schema_version": RISK_MODEL_SCHEMA_VERSION,
            "dates": [value.isoformat() for value in selected_dates],
        }
    )
    return selected_indices, cutoff, selected_dates, selected_fingerprint


def _reject_degenerate_series(returns: FloatMatrix, stock_codes: tuple[str, ...]) -> None:
    for column_index, stock_code in enumerate(stock_codes):
        column = returns[:, column_index]
        if np.all(column == column[0]):
            raise DegenerateRiskSeriesError(stock_code)


def _normalized_geometric_weights(beta: float, count: int) -> NDArray[np.float64]:
    ages = np.arange(count - 1, -1, -1, dtype=np.float64)
    weights = np.power(beta, ages)
    denominator = float(np.sum(weights))
    if not math.isfinite(denominator) or denominator <= 0:
        raise RiskModelNumericalError("finite-history EWMA 가중치를 정규화하지 못했습니다.")
    normalized = np.asarray(weights / denominator, dtype=np.float64)
    if not np.all(np.isfinite(normalized)) or not math.isclose(
        float(np.sum(normalized)),
        1.0,
        rel_tol=0.0,
        abs_tol=1e-14,
    ):
        raise RiskModelNumericalError("finite-history EWMA 가중치 합이 1이 아닙니다.")
    return normalized


def _renormalize_correlation(matrix: FloatMatrix) -> FloatMatrix:
    diagonal = np.diag(matrix)
    if np.any(diagonal <= 0) or not np.all(np.isfinite(diagonal)):
        raise RiskModelNumericalError("PSD 상관계수 행렬의 대각원소는 양수여야 합니다.")
    scale = np.sqrt(diagonal)
    result = np.asarray(matrix / np.outer(scale, scale), dtype=np.float64)
    result = (result + result.T) / 2.0
    np.fill_diagonal(result, 1.0)
    return result


def _project_post_normalization_noise(matrix: FloatMatrix, tolerance: float) -> FloatMatrix:
    try:
        eigenvalues, eigenvectors = np.linalg.eigh(matrix)
    except np.linalg.LinAlgError:
        raise RiskModelNumericalError("상관계수 PSD 재검사를 완료하지 못했습니다.") from None
    minimum = float(eigenvalues[0])
    if minimum < -tolerance:
        raise MateriallyIndefiniteCovarianceError(minimum, tolerance)
    if minimum >= 0:
        return matrix
    result = np.asarray(
        (eigenvectors * np.maximum(eigenvalues, 0.0)) @ eigenvectors.T,
        dtype=np.float64,
    )
    return np.asarray((result + result.T) / 2.0, dtype=np.float64)


def _matrix_to_tuple(matrix: FloatMatrix) -> tuple[tuple[float, ...], ...]:
    return tuple(tuple(_clean_float(float(value)) for value in row) for row in matrix.tolist())


def _stable_frobenius_norm(matrix: FloatMatrix) -> float:
    scale = float(np.max(np.abs(matrix)))
    if scale == 0.0:
        return 0.0
    if not math.isfinite(scale):
        raise RiskModelNumericalError("PSD Frobenius norm 입력 규모가 유한하지 않습니다.")
    normalized = matrix / scale
    result = scale * math.sqrt(float(np.sum(normalized * normalized)))
    if not math.isfinite(result):
        raise RiskModelNumericalError("PSD Frobenius norm을 유한하게 계산하지 못했습니다.")
    return result


def _clean_float(value: float) -> float:
    if not math.isfinite(value):
        raise RiskModelNumericalError("공개 위험모형 값에는 유한한 float만 사용할 수 있습니다.")
    return 0.0 if value == 0.0 else value


def _fingerprint(payload: object) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


__all__ = [
    "DynamicRiskModel",
    "canonical_decimal",
    "ewma_beta",
    "fingerprint_consumed_risk_input",
    "normalized_ewma_effective_sample_size",
    "repair_numerical_psd",
    "risk_model_config_payload",
]
