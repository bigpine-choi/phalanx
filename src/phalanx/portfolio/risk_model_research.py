"""Reproducible rolling dynamic-risk-model research orchestration."""

from __future__ import annotations

import hashlib
import json
import platform
from collections.abc import Callable
from datetime import UTC, date, datetime
from importlib.metadata import version
from typing import Protocol
from uuid import uuid4

import numpy as np

from phalanx.domain import (
    DYNAMIC_RISK_MODEL_VERSION,
    RISK_MODEL_SCHEMA_VERSION,
    AlignedReturnMatrix,
    DynamicRiskModelConfig,
    DynamicRiskModelResearchResult,
    DynamicRiskModelSnapshot,
    RiskModelFailure,
    RiskModelLibraryProvenance,
    RiskModelResearchStatus,
    RiskModelResearchTrial,
)
from phalanx.portfolio._allocation_schedule import build_return_matrix_signal_windows
from phalanx.portfolio.dynamic_risk_model import (
    DynamicRiskModel,
    canonical_decimal,
    fingerprint_consumed_risk_input,
    risk_model_config_payload,
)
from phalanx.portfolio.errors import (
    DegenerateRiskSeriesError,
    InsufficientAllocationObservationsError,
    InsufficientCorrelationHistoryError,
    InsufficientDownsideHistoryError,
    InsufficientRiskHistoryError,
    MateriallyIndefiniteCovarianceError,
    RiskModelAsOfDateNotFoundError,
    RiskModelConfigurationError,
    RiskModelError,
    RiskModelNumericalError,
    RiskModelQualityError,
)


class RiskModelEstimator(Protocol):
    """Explicit estimator boundary used by rolling research and future consumers."""

    def estimate(
        self,
        matrix: AlignedReturnMatrix,
        *,
        as_of_date: date,
    ) -> DynamicRiskModelSnapshot: ...


def conduct_dynamic_risk_model_research(
    matrix: AlignedReturnMatrix,
    *,
    config: DynamicRiskModelConfig | None = None,
    estimator: RiskModelEstimator | None = None,
) -> DynamicRiskModelResearchResult:
    """Estimate every allocation-compatible 504/756/5 as-of in order."""

    selected_config = DynamicRiskModelConfig() if config is None else config
    selected_estimator = DynamicRiskModel(selected_config) if estimator is None else estimator
    try:
        windows = build_return_matrix_signal_windows(
            matrix,
            minimum_observations=selected_config.minimum_observations,
            maximum_observations=selected_config.maximum_observations,
            rebalance_interval=selected_config.rebalance_interval,
        )
    except InsufficientAllocationObservationsError as error:
        raise InsufficientRiskHistoryError(
            max(0, len(matrix.dates)),
            selected_config.minimum_observations + 1,
        ) from error
    scheduled_dates = tuple(window.policy_input.signal_date for window in windows)
    snapshots: list[DynamicRiskModelSnapshot] = []
    for window in windows:
        as_of_date = window.policy_input.signal_date
        # A prefix matrix prevents a custom estimator from observing future rows.
        prefix_end = window.as_of_index + 1
        visible_matrix = AlignedReturnMatrix(
            stock_codes=matrix.stock_codes,
            dates=matrix.dates[:prefix_end],
            values=matrix.values[:prefix_end],
        )
        try:
            snapshots.append(
                selected_estimator.estimate(
                    visible_matrix,
                    as_of_date=as_of_date,
                )
            )
        except Exception as error:
            failure = safe_risk_model_failure(error, as_of_date=as_of_date)
            return DynamicRiskModelResearchResult(
                status=RiskModelResearchStatus.FAILED,
                stock_codes=matrix.stock_codes,
                scheduled_as_of_dates=scheduled_dates,
                snapshots=tuple(snapshots),
                failure=failure,
            )
    return DynamicRiskModelResearchResult(
        status=RiskModelResearchStatus.SUCCEEDED,
        stock_codes=matrix.stock_codes,
        scheduled_as_of_dates=scheduled_dates,
        snapshots=tuple(snapshots),
    )


def create_risk_model_research_trial(
    matrix: AlignedReturnMatrix,
    requested_start: date,
    requested_end: date,
    *,
    config: DynamicRiskModelConfig | None = None,
    estimator: RiskModelEstimator | None = None,
    trial_id_factory: Callable[[], str] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> RiskModelResearchTrial:
    """Build one successful or sanitized failed trial from an aligned matrix."""

    selected_config = DynamicRiskModelConfig() if config is None else config
    trial_id = uuid4().hex if trial_id_factory is None else trial_id_factory()
    executed_at = datetime.now(UTC) if clock is None else clock()
    config_fingerprint = fingerprint_risk_model_config(selected_config)
    input_fingerprint = fingerprint_aligned_return_matrix(matrix, selected_config)
    trial_fingerprint = fingerprint_risk_model_trial(config_fingerprint, input_fingerprint)
    provenance = current_risk_model_provenance()
    try:
        result = conduct_dynamic_risk_model_research(
            matrix,
            config=selected_config,
            estimator=estimator,
        )
    except Exception as error:
        failure = safe_risk_model_failure(error)
        return RiskModelResearchTrial(
            trial_id=trial_id,
            status=RiskModelResearchStatus.FAILED,
            executed_at=executed_at,
            requested_start=requested_start,
            requested_end=requested_end,
            stock_codes=matrix.stock_codes,
            aligned_returns=matrix,
            config=selected_config,
            config_fingerprint=config_fingerprint,
            input_fingerprint=input_fingerprint,
            trial_fingerprint=trial_fingerprint,
            provenance=provenance,
            result=None,
            failure=failure,
        )
    if result.status is RiskModelResearchStatus.FAILED:
        if result.failure is None:
            raise RiskModelNumericalError("실패 rolling 연구에 정제된 실패 정보가 없습니다.")
        return RiskModelResearchTrial(
            trial_id=trial_id,
            status=RiskModelResearchStatus.FAILED,
            executed_at=executed_at,
            requested_start=requested_start,
            requested_end=requested_end,
            stock_codes=matrix.stock_codes,
            aligned_returns=matrix,
            config=selected_config,
            config_fingerprint=config_fingerprint,
            input_fingerprint=input_fingerprint,
            trial_fingerprint=trial_fingerprint,
            provenance=provenance,
            result=result,
            failure=result.failure,
        )
    return RiskModelResearchTrial(
        trial_id=trial_id,
        status=RiskModelResearchStatus.SUCCEEDED,
        executed_at=executed_at,
        requested_start=requested_start,
        requested_end=requested_end,
        stock_codes=matrix.stock_codes,
        aligned_returns=matrix,
        config=selected_config,
        config_fingerprint=config_fingerprint,
        input_fingerprint=input_fingerprint,
        trial_fingerprint=trial_fingerprint,
        provenance=provenance,
        result=result,
        failure=None,
    )


def create_failed_risk_model_trial(
    stock_codes: tuple[str, ...],
    requested_start: date,
    requested_end: date,
    error: Exception,
    *,
    config: DynamicRiskModelConfig | None = None,
    trial_id_factory: Callable[[], str] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> RiskModelResearchTrial:
    """Create a secret-safe failed trial when aligned returns cannot be built."""

    selected_config = DynamicRiskModelConfig() if config is None else config
    trial_id = uuid4().hex if trial_id_factory is None else trial_id_factory()
    executed_at = datetime.now(UTC) if clock is None else clock()
    config_fingerprint = fingerprint_risk_model_config(selected_config)
    input_fingerprint = _fingerprint(
        {
            "schema_version": RISK_MODEL_SCHEMA_VERSION,
            "model_version": DYNAMIC_RISK_MODEL_VERSION,
            "stock_codes": list(stock_codes),
            "requested_start": requested_start.isoformat(),
            "requested_end": requested_end.isoformat(),
            "aligned_returns": None,
        }
    )
    failure = safe_risk_model_failure(error, data_level=True)
    return RiskModelResearchTrial(
        trial_id=trial_id,
        status=RiskModelResearchStatus.FAILED,
        executed_at=executed_at,
        requested_start=requested_start,
        requested_end=requested_end,
        stock_codes=stock_codes,
        aligned_returns=None,
        config=selected_config,
        config_fingerprint=config_fingerprint,
        input_fingerprint=input_fingerprint,
        trial_fingerprint=fingerprint_risk_model_trial(
            config_fingerprint,
            input_fingerprint,
        ),
        provenance=current_risk_model_provenance(),
        result=None,
        failure=failure,
    )


def safe_risk_model_failure(
    error: Exception,
    *,
    as_of_date: date | None = None,
    data_level: bool = False,
) -> RiskModelFailure:
    """Project known safe fields only; never persist arbitrary exception text."""

    code = "risk_model_input_error" if data_level else "risk_model_numerical_error"
    message = (
        "공통 수익률 입력을 구성하지 못했습니다."
        if data_level
        else "동적 위험모형 계산을 완료하지 못했습니다."
    )
    if isinstance(error, RiskModelConfigurationError):
        code = "risk_model_configuration_error"
        message = str(error)
    elif isinstance(error, RiskModelAsOfDateNotFoundError):
        code = "risk_model_as_of_not_found"
        message = str(error)
    elif isinstance(error, InsufficientRiskHistoryError):
        code = "insufficient_risk_history"
        message = str(error)
    elif isinstance(error, InsufficientCorrelationHistoryError):
        code = "insufficient_correlation_history"
        message = str(error)
    elif isinstance(error, InsufficientDownsideHistoryError):
        code = "insufficient_downside_history"
        message = str(error)
    elif isinstance(error, DegenerateRiskSeriesError):
        code = "degenerate_risk_series"
        message = str(error)
    elif isinstance(error, MateriallyIndefiniteCovarianceError):
        code = "materially_indefinite_covariance"
        message = str(error)
    elif isinstance(error, RiskModelQualityError):
        code = "risk_model_quality_error"
        message = str(error)
    elif isinstance(error, RiskModelNumericalError):
        code = "risk_model_numerical_error"
        message = str(error)
    elif isinstance(error, RiskModelError):
        code = "risk_model_error"
        message = str(error)
    stock_code = error.stock_code if isinstance(error, DegenerateRiskSeriesError) else None
    return RiskModelFailure(
        code=code,
        message=message,
        as_of_date=as_of_date,
        stock_code=stock_code,
    )


def fingerprint_risk_model_config(config: DynamicRiskModelConfig) -> str:
    """Return deterministic SHA-256 over the fixed v1 configuration."""

    return _fingerprint(
        {
            "schema_version": RISK_MODEL_SCHEMA_VERSION,
            "model_version": DYNAMIC_RISK_MODEL_VERSION,
            "config": risk_model_config_payload(config),
        }
    )


def fingerprint_aligned_return_matrix(
    matrix: AlignedReturnMatrix,
    config: DynamicRiskModelConfig,
) -> str:
    """Fingerprint all aligned Decimal rows retained in the trial."""

    return fingerprint_consumed_risk_input(
        matrix.stock_codes,
        matrix.dates,
        matrix.values,
        config,
    )


def fingerprint_risk_model_trial(config_fingerprint: str, input_fingerprint: str) -> str:
    """Return a deterministic trial-content fingerprint excluding UUID and time."""

    return _fingerprint(
        {
            "schema_version": RISK_MODEL_SCHEMA_VERSION,
            "model_version": DYNAMIC_RISK_MODEL_VERSION,
            "config_sha256": config_fingerprint,
            "input_sha256": input_fingerprint,
        }
    )


def current_risk_model_provenance() -> RiskModelLibraryProvenance:
    """Capture safe library versions without environment or credential fields."""

    return RiskModelLibraryProvenance(
        python_version=platform.python_version(),
        numpy_version=np.__version__,
        scikit_learn_version=version("scikit-learn"),
    )


def aligned_return_matrix_payload(matrix: AlignedReturnMatrix) -> dict[str, object]:
    """Canonical Decimal-text projection for persisted trial provenance."""

    return {
        "stock_codes": list(matrix.stock_codes),
        "dates": [value.isoformat() for value in matrix.dates],
        "values": [[canonical_decimal(value) for value in row] for row in matrix.values],
    }


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
    "RiskModelEstimator",
    "aligned_return_matrix_payload",
    "conduct_dynamic_risk_model_research",
    "create_failed_risk_model_trial",
    "create_risk_model_research_trial",
    "current_risk_model_provenance",
    "fingerprint_aligned_return_matrix",
    "fingerprint_risk_model_config",
    "fingerprint_risk_model_trial",
    "safe_risk_model_failure",
]
