"""Canonical JSON registry for independent dynamic-risk-model research trials."""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Protocol, cast

from phalanx.domain import (
    DYNAMIC_RISK_MODEL_VERSION,
    RISK_MODEL_SCHEMA_VERSION,
    AlignedReturnMatrix,
    CovarianceScenario,
    CovarianceScenarioKind,
    DownsideStressMetadata,
    DynamicRiskModelConfig,
    DynamicRiskModelResearchResult,
    DynamicRiskModelSnapshot,
    IewmaMetadata,
    LedoitWolfMetadata,
    PsdDiagnostics,
    RiskModelFailure,
    RiskModelLibraryProvenance,
    RiskModelResearchStatus,
    RiskModelResearchTrial,
)
from phalanx.portfolio.dynamic_risk_model import (
    canonical_decimal,
    fingerprint_consumed_risk_input,
    risk_model_config_payload,
)
from phalanx.portfolio.errors import (
    RiskModelError,
    RiskModelTrialAlreadyExistsError,
    RiskModelTrialCorruptionError,
    RiskModelTrialLockTimeoutError,
    RiskModelTrialStorageError,
)
from phalanx.portfolio.private_json_storage import (
    PrivateJsonAlreadyExistsError,
    PrivateJsonLockTimeoutError,
    PrivateJsonStorageError,
    store_private_json_bytes,
)
from phalanx.portfolio.risk_model_research import (
    aligned_return_matrix_payload,
    fingerprint_aligned_return_matrix,
    fingerprint_risk_model_config,
    fingerprint_risk_model_trial,
)

_LOCK_TIMEOUT_SECONDS = 10.0
_SAFE_FAILURE_MESSAGES = {
    "risk_model_input_error": "공통 수익률 입력을 구성하지 못했습니다.",
    "risk_model_configuration_error": "동적 위험모형 설정이 올바르지 않습니다.",
    "risk_model_as_of_not_found": "동적 위험모형 기준일을 확인하지 못했습니다.",
    "insufficient_risk_history": "동적 위험모형 수익률 관측치가 부족합니다.",
    "insufficient_correlation_history": "IEWMA 상관관계 관측치가 부족합니다.",
    "insufficient_downside_history": "하방 스트레스 관측치가 부족합니다.",
    "degenerate_risk_series": "한 종목의 수익률 분산이 0입니다.",
    "materially_indefinite_covariance": "공분산 수치 품질 검사를 통과하지 못했습니다.",
    "risk_model_quality_error": "위험모형 수치 품질 상한을 통과하지 못했습니다.",
    "risk_model_numerical_error": "동적 위험모형 수치 계산을 완료하지 못했습니다.",
    "risk_model_error": "동적 위험모형 계산을 완료하지 못했습니다.",
}
_GENERIC_FAILURE_CODE = "risk_model_numerical_error"


class RiskModelTrialRegistry(Protocol):
    """Persistence contract for one immutable risk-model research trial."""

    def save(self, trial: RiskModelResearchTrial) -> Path: ...


class JsonRiskModelTrialRegistry:
    """Store each risk-model trial once as private, canonical JSON."""

    def __init__(self, output_dir: Path, *, lock_timeout: float = _LOCK_TIMEOUT_SECONDS) -> None:
        self.output_dir = Path(output_dir)
        self.lock_timeout = lock_timeout

    def save(self, trial: RiskModelResearchTrial) -> Path:
        """Atomically save one trial without changing existing files."""

        payload = serialize_risk_model_trial(trial)
        output_path = self.output_dir / f"risk_model_research_trial_{trial.trial_id}.json"
        try:
            return store_private_json_bytes(
                output_path,
                payload,
                lock_timeout=self.lock_timeout,
            )
        except PrivateJsonAlreadyExistsError:
            raise RiskModelTrialAlreadyExistsError(
                f"기존 위험모형 trial을 덮어쓰지 않습니다: {output_path}"
            ) from None
        except PrivateJsonLockTimeoutError:
            raise RiskModelTrialLockTimeoutError(
                "위험모형 trial 출력 파일 잠금 대기시간이 초과되었습니다."
            ) from None
        except PrivateJsonStorageError:
            raise RiskModelTrialStorageError(
                f"위험모형 trial을 원자적으로 저장하지 못했습니다: {output_path}"
            ) from None

    def load(self, path: Path) -> RiskModelResearchTrial:
        """Load and fully validate one stored trial or report corruption."""

        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            trial = _trial_from_payload(_require_dict(payload, "trial"))
            _verify_trial_fingerprints(trial)
            return trial
        except RiskModelTrialCorruptionError:
            raise
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            ValueError,
            TypeError,
            KeyError,
            RiskModelError,
        ):
            raise RiskModelTrialCorruptionError(
                "위험모형 trial JSON이 손상되었거나 지원하지 않는 형식입니다."
            ) from None


def serialize_risk_model_trial(trial: RiskModelResearchTrial) -> bytes:
    """Serialize an explicit allow-list with Decimal text and finite floats only."""

    if not isinstance(trial, RiskModelResearchTrial):
        raise RiskModelTrialStorageError("저장할 trial은 RiskModelResearchTrial이어야 합니다.")
    payload = {
        "schema_version": trial.schema_version,
        "model_version": trial.model_version,
        "trial_id": trial.trial_id,
        "status": trial.status.value,
        "executed_at": trial.executed_at.isoformat(),
        "requested_period": {
            "start": trial.requested_start.isoformat(),
            "end": trial.requested_end.isoformat(),
        },
        "stock_codes": list(trial.stock_codes),
        "aligned_returns": (
            None
            if trial.aligned_returns is None
            else aligned_return_matrix_payload(trial.aligned_returns)
        ),
        "config": risk_model_config_payload(trial.config),
        "fingerprints": {
            "config_sha256": trial.config_fingerprint,
            "input_sha256": trial.input_fingerprint,
            "trial_sha256": trial.trial_fingerprint,
        },
        "provenance": {
            "python_version": trial.provenance.python_version,
            "numpy_version": trial.provenance.numpy_version,
            "scikit_learn_version": trial.provenance.scikit_learn_version,
            "model_version": trial.provenance.model_version,
            "schema_version": trial.provenance.schema_version,
        },
        "result": None if trial.result is None else _research_result_payload(trial.result),
        "failure": None if trial.failure is None else _safe_failure_payload(trial.failure),
        "research_scope": trial.research_scope,
    }
    try:
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
    except (TypeError, ValueError):
        raise RiskModelTrialStorageError(
            "위험모형 trial에 JSON으로 저장할 수 없는 값이 있습니다."
        ) from None
    return f"{serialized}\n".encode()


def _research_result_payload(result: DynamicRiskModelResearchResult) -> dict[str, object]:
    return {
        "status": result.status.value,
        "stock_codes": list(result.stock_codes),
        "scheduled_as_of_dates": [value.isoformat() for value in result.scheduled_as_of_dates],
        "snapshots": [_snapshot_payload(snapshot) for snapshot in result.snapshots],
        "failure": None if result.failure is None else _safe_failure_payload(result.failure),
    }


def _snapshot_payload(snapshot: DynamicRiskModelSnapshot) -> dict[str, object]:
    return {
        "as_of_date": snapshot.as_of_date.isoformat(),
        "consumed_period": {
            "start": snapshot.consumed_start_date.isoformat(),
            "end": snapshot.consumed_end_date.isoformat(),
            "observation_count": snapshot.consumed_observation_count,
        },
        "stock_codes": list(snapshot.stock_codes),
        "consumed_dates": [value.isoformat() for value in snapshot.consumed_dates],
        "scenarios": [_scenario_payload(scenario) for scenario in snapshot.scenarios],
        "consumed_input_fingerprint": snapshot.consumed_input_fingerprint,
        "model_version": snapshot.model_version,
        "schema_version": snapshot.schema_version,
    }


def _scenario_payload(scenario: CovarianceScenario) -> dict[str, object]:
    return {
        "kind": scenario.kind.value,
        "stock_codes": list(scenario.stock_codes),
        "observation_dates": [value.isoformat() for value in scenario.observation_dates],
        "annualized_covariance": _float_matrix_payload(scenario.annualized_covariance),
        "annualized_volatilities": [
            _json_float(value) for value in scenario.annualized_volatilities
        ],
        "correlation_matrix": _float_matrix_payload(scenario.correlation_matrix),
        "metadata": _metadata_payload(scenario.metadata),
        "psd_diagnostics": _diagnostics_payload(scenario.psd_diagnostics),
    }


def _metadata_payload(
    metadata: LedoitWolfMetadata | IewmaMetadata | DownsideStressMetadata,
) -> dict[str, object]:
    if isinstance(metadata, LedoitWolfMetadata):
        return {
            "metadata_type": "ledoit_wolf",
            "shrinkage": _json_float(metadata.shrinkage),
            "assume_centered": metadata.assume_centered,
            "store_precision": metadata.store_precision,
            "estimator": metadata.estimator,
            "moment_assumption": metadata.moment_assumption,
        }
    if isinstance(metadata, IewmaMetadata):
        return {
            "metadata_type": "iewma",
            "volatility_half_life": metadata.volatility_half_life,
            "correlation_half_life": metadata.correlation_half_life,
            "volatility_seed_count": metadata.volatility_seed_count,
            "correlation_observation_count": metadata.correlation_observation_count,
            "volatility_effective_sample_size": _json_float(
                metadata.volatility_effective_sample_size
            ),
            "correlation_effective_sample_size": _json_float(
                metadata.correlation_effective_sample_size
            ),
            "clip_threshold": _json_float(metadata.clip_threshold),
            "clipped_scalar_count": metadata.clipped_scalar_count,
            "correlation_psd_diagnostics": _diagnostics_payload(
                metadata.correlation_psd_diagnostics
            ),
            "forecast_horizon": metadata.forecast_horizon,
        }
    return {
        "metadata_type": "downside_stress",
        "downside_fraction": canonical_decimal(metadata.downside_fraction),
        "selected_count": metadata.selected_count,
        "cutoff_equal_weight_return": canonical_decimal(metadata.cutoff_equal_weight_return),
        "selected_dates": [value.isoformat() for value in metadata.selected_dates],
        "selected_dates_fingerprint": metadata.selected_dates_fingerprint,
        "shrinkage": _json_float(metadata.shrinkage),
        "assume_centered": metadata.assume_centered,
        "store_precision": metadata.store_precision,
        "estimator": metadata.estimator,
        "moment_assumption": metadata.moment_assumption,
    }


def _diagnostics_payload(diagnostics: PsdDiagnostics) -> dict[str, object]:
    return {
        "minimum_eigenvalue_before": _json_float(diagnostics.minimum_eigenvalue_before),
        "minimum_eigenvalue_after": _json_float(diagnostics.minimum_eigenvalue_after),
        "maximum_eigenvalue_after": _json_float(diagnostics.maximum_eigenvalue_after),
        "numerical_tolerance": _json_float(diagnostics.numerical_tolerance),
        "rank": diagnostics.rank,
        "condition_number": (
            None
            if diagnostics.condition_number is None
            else _json_float(diagnostics.condition_number)
        ),
        "frobenius_repair_norm": _json_float(diagnostics.frobenius_repair_norm),
        "relative_repair_norm": _json_float(diagnostics.relative_repair_norm),
        "repaired": diagnostics.repaired,
    }


def _safe_failure_payload(failure: RiskModelFailure) -> dict[str, object]:
    code = failure.code if failure.code in _SAFE_FAILURE_MESSAGES else _GENERIC_FAILURE_CODE
    return {
        "code": code,
        "message": _SAFE_FAILURE_MESSAGES[code],
        "as_of_date": None if failure.as_of_date is None else failure.as_of_date.isoformat(),
        "stock_code": failure.stock_code,
    }


def _trial_from_payload(payload: dict[str, object]) -> RiskModelResearchTrial:
    _require_exact(payload, "schema_version", RISK_MODEL_SCHEMA_VERSION)
    _require_exact(payload, "model_version", DYNAMIC_RISK_MODEL_VERSION)
    requested = _require_dict(payload["requested_period"], "requested_period")
    fingerprints = _require_dict(payload["fingerprints"], "fingerprints")
    provenance_payload = _require_dict(payload["provenance"], "provenance")
    aligned_payload = payload.get("aligned_returns")
    result_payload = payload.get("result")
    failure_payload = payload.get("failure")
    return RiskModelResearchTrial(
        trial_id=_require_str(payload["trial_id"], "trial_id"),
        status=RiskModelResearchStatus(_require_str(payload["status"], "status")),
        executed_at=_parse_datetime(payload["executed_at"], "executed_at"),
        requested_start=_parse_date(requested["start"], "requested start"),
        requested_end=_parse_date(requested["end"], "requested end"),
        stock_codes=_string_tuple(payload["stock_codes"], "stock_codes"),
        aligned_returns=(
            None
            if aligned_payload is None
            else _aligned_matrix_from_payload(_require_dict(aligned_payload, "aligned_returns"))
        ),
        config=_config_from_payload(_require_dict(payload["config"], "config")),
        config_fingerprint=_require_str(fingerprints["config_sha256"], "config fingerprint"),
        input_fingerprint=_require_str(fingerprints["input_sha256"], "input fingerprint"),
        trial_fingerprint=_require_str(fingerprints["trial_sha256"], "trial fingerprint"),
        provenance=RiskModelLibraryProvenance(
            python_version=_require_str(provenance_payload["python_version"], "Python version"),
            numpy_version=_require_str(provenance_payload["numpy_version"], "NumPy version"),
            scikit_learn_version=_require_str(
                provenance_payload["scikit_learn_version"],
                "scikit-learn version",
            ),
            model_version=_require_str(provenance_payload["model_version"], "model version"),
            schema_version=_require_str(provenance_payload["schema_version"], "schema version"),
        ),
        result=(
            None
            if result_payload is None
            else _research_result_from_payload(_require_dict(result_payload, "result"))
        ),
        failure=(
            None
            if failure_payload is None
            else _failure_from_payload(_require_dict(failure_payload, "failure"))
        ),
        research_scope=_require_str(payload["research_scope"], "research_scope"),
    )


def _aligned_matrix_from_payload(payload: dict[str, object]) -> AlignedReturnMatrix:
    rows = _require_list(payload["values"], "aligned values")
    return AlignedReturnMatrix(
        stock_codes=_string_tuple(payload["stock_codes"], "aligned stock_codes"),
        dates=_date_tuple(payload["dates"], "aligned dates"),
        values=tuple(
            tuple(_parse_decimal(value, "aligned return") for value in _require_list(row, "row"))
            for row in rows
        ),
    )


def _config_from_payload(payload: dict[str, object]) -> DynamicRiskModelConfig:
    return DynamicRiskModelConfig(
        minimum_observations=_require_int(payload["minimum_observations"], "minimum"),
        maximum_observations=_require_int(payload["maximum_observations"], "maximum"),
        rebalance_interval=_require_int(payload["rebalance_interval"], "interval"),
        annualization_days=_require_int(payload["annualization_days"], "annualization"),
        fast_volatility_half_life=_require_int(
            payload["fast_volatility_half_life"], "fast volatility half-life"
        ),
        fast_correlation_half_life=_require_int(
            payload["fast_correlation_half_life"], "fast correlation half-life"
        ),
        slow_volatility_half_life=_require_int(
            payload["slow_volatility_half_life"], "slow volatility half-life"
        ),
        slow_correlation_half_life=_require_int(
            payload["slow_correlation_half_life"], "slow correlation half-life"
        ),
        standardized_return_clip=_require_float(payload["standardized_return_clip"], "clip"),
        minimum_volatility_seed_observations=_require_int(
            payload["minimum_volatility_seed_observations"], "volatility seed"
        ),
        minimum_correlation_observations=_require_int(
            payload["minimum_correlation_observations"], "correlation minimum"
        ),
        downside_fraction=_parse_decimal(payload["downside_fraction"], "downside fraction"),
        minimum_downside_observations=_require_int(
            payload["minimum_downside_observations"], "downside minimum"
        ),
        psd_relative_eigen_tolerance=_require_float(
            payload["psd_relative_eigen_tolerance"], "PSD relative tolerance"
        ),
        psd_absolute_eigen_tolerance=_require_float(
            payload["psd_absolute_eigen_tolerance"], "PSD absolute tolerance"
        ),
        maximum_relative_psd_repair=_require_float(
            payload["maximum_relative_psd_repair"], "PSD repair ceiling"
        ),
    )


def _research_result_from_payload(payload: dict[str, object]) -> DynamicRiskModelResearchResult:
    failure_payload = payload.get("failure")
    return DynamicRiskModelResearchResult(
        status=RiskModelResearchStatus(_require_str(payload["status"], "result status")),
        stock_codes=_string_tuple(payload["stock_codes"], "result stock codes"),
        scheduled_as_of_dates=_date_tuple(
            payload["scheduled_as_of_dates"], "scheduled as-of dates"
        ),
        snapshots=tuple(
            _snapshot_from_payload(_require_dict(value, "snapshot"))
            for value in _require_list(payload["snapshots"], "snapshots")
        ),
        failure=(
            None
            if failure_payload is None
            else _failure_from_payload(_require_dict(failure_payload, "result failure"))
        ),
    )


def _snapshot_from_payload(payload: dict[str, object]) -> DynamicRiskModelSnapshot:
    consumed = _require_dict(payload["consumed_period"], "consumed period")
    return DynamicRiskModelSnapshot(
        as_of_date=_parse_date(payload["as_of_date"], "as-of"),
        consumed_start_date=_parse_date(consumed["start"], "consumed start"),
        consumed_end_date=_parse_date(consumed["end"], "consumed end"),
        consumed_observation_count=_require_int(consumed["observation_count"], "consumed count"),
        stock_codes=_string_tuple(payload["stock_codes"], "snapshot stock codes"),
        consumed_dates=_date_tuple(payload["consumed_dates"], "consumed dates"),
        scenarios=tuple(
            _scenario_from_payload(_require_dict(value, "scenario"))
            for value in _require_list(payload["scenarios"], "scenarios")
        ),
        consumed_input_fingerprint=_require_str(
            payload["consumed_input_fingerprint"], "snapshot fingerprint"
        ),
        model_version=_require_str(payload["model_version"], "snapshot model version"),
        schema_version=_require_str(payload["schema_version"], "snapshot schema version"),
    )


def _scenario_from_payload(payload: dict[str, object]) -> CovarianceScenario:
    kind = CovarianceScenarioKind(_require_str(payload["kind"], "scenario kind"))
    metadata_payload = _require_dict(payload["metadata"], "metadata")
    return CovarianceScenario(
        kind=kind,
        stock_codes=_string_tuple(payload["stock_codes"], "scenario stock codes"),
        observation_dates=_date_tuple(payload["observation_dates"], "observation dates"),
        annualized_covariance=_float_matrix_from_payload(
            payload["annualized_covariance"], "annualized covariance"
        ),
        annualized_volatilities=_float_tuple(
            payload["annualized_volatilities"], "annualized volatilities"
        ),
        correlation_matrix=_float_matrix_from_payload(payload["correlation_matrix"], "correlation"),
        metadata=_metadata_from_payload(kind, metadata_payload),
        psd_diagnostics=_diagnostics_from_payload(
            _require_dict(payload["psd_diagnostics"], "PSD diagnostics")
        ),
    )


def _metadata_from_payload(
    kind: CovarianceScenarioKind,
    payload: dict[str, object],
) -> LedoitWolfMetadata | IewmaMetadata | DownsideStressMetadata:
    metadata_type = _require_str(payload["metadata_type"], "metadata type")
    if kind is CovarianceScenarioKind.LONG_RUN_LEDOIT_WOLF and metadata_type == "ledoit_wolf":
        return LedoitWolfMetadata(
            shrinkage=_require_float(payload["shrinkage"], "shrinkage"),
            assume_centered=_require_bool(payload["assume_centered"], "assume centered"),
            store_precision=_require_bool(payload["store_precision"], "store precision"),
            estimator=_require_str(payload["estimator"], "estimator"),
            moment_assumption=_require_str(payload["moment_assumption"], "moment assumption"),
        )
    if kind in (CovarianceScenarioKind.FAST_IEWMA, CovarianceScenarioKind.SLOW_IEWMA) and (
        metadata_type == "iewma"
    ):
        return IewmaMetadata(
            volatility_half_life=_require_int(
                payload["volatility_half_life"], "volatility half-life"
            ),
            correlation_half_life=_require_int(
                payload["correlation_half_life"], "correlation half-life"
            ),
            volatility_seed_count=_require_int(
                payload["volatility_seed_count"], "volatility seed count"
            ),
            correlation_observation_count=_require_int(
                payload["correlation_observation_count"], "correlation count"
            ),
            volatility_effective_sample_size=_require_float(
                payload["volatility_effective_sample_size"], "volatility ESS"
            ),
            correlation_effective_sample_size=_require_float(
                payload["correlation_effective_sample_size"], "correlation ESS"
            ),
            clip_threshold=_require_float(payload["clip_threshold"], "clip threshold"),
            clipped_scalar_count=_require_int(
                payload["clipped_scalar_count"], "clipped scalar count"
            ),
            correlation_psd_diagnostics=_diagnostics_from_payload(
                _require_dict(
                    payload["correlation_psd_diagnostics"],
                    "correlation PSD diagnostics",
                )
            ),
            forecast_horizon=_require_str(payload["forecast_horizon"], "forecast horizon"),
        )
    if (
        kind is CovarianceScenarioKind.DOWNSIDE_STRESS_LEDOIT_WOLF
        and metadata_type == "downside_stress"
    ):
        return DownsideStressMetadata(
            downside_fraction=_parse_decimal(payload["downside_fraction"], "downside fraction"),
            selected_count=_require_int(payload["selected_count"], "selected count"),
            cutoff_equal_weight_return=_parse_decimal(
                payload["cutoff_equal_weight_return"], "downside cutoff"
            ),
            selected_dates=_date_tuple(payload["selected_dates"], "selected dates"),
            selected_dates_fingerprint=_require_str(
                payload["selected_dates_fingerprint"], "selected fingerprint"
            ),
            shrinkage=_require_float(payload["shrinkage"], "downside shrinkage"),
            assume_centered=_require_bool(payload["assume_centered"], "assume centered"),
            store_precision=_require_bool(payload["store_precision"], "store precision"),
            estimator=_require_str(payload["estimator"], "estimator"),
            moment_assumption=_require_str(payload["moment_assumption"], "moment assumption"),
        )
    raise RiskModelTrialCorruptionError("scenario 종류와 metadata가 일치하지 않습니다.")


def _diagnostics_from_payload(payload: dict[str, object]) -> PsdDiagnostics:
    condition_value = payload.get("condition_number")
    return PsdDiagnostics(
        minimum_eigenvalue_before=_require_float(
            payload["minimum_eigenvalue_before"], "minimum eigenvalue before"
        ),
        minimum_eigenvalue_after=_require_float(
            payload["minimum_eigenvalue_after"], "minimum eigenvalue after"
        ),
        maximum_eigenvalue_after=_require_float(
            payload["maximum_eigenvalue_after"], "maximum eigenvalue after"
        ),
        numerical_tolerance=_require_float(payload["numerical_tolerance"], "tolerance"),
        rank=_require_int(payload["rank"], "rank"),
        condition_number=(
            None if condition_value is None else _require_float(condition_value, "condition")
        ),
        frobenius_repair_norm=_require_float(payload["frobenius_repair_norm"], "repair norm"),
        relative_repair_norm=_require_float(payload["relative_repair_norm"], "relative repair"),
        repaired=_require_bool(payload["repaired"], "repaired"),
    )


def _failure_from_payload(payload: dict[str, object]) -> RiskModelFailure:
    as_of_value = payload.get("as_of_date")
    stock_code_value = payload.get("stock_code")
    return RiskModelFailure(
        code=_require_str(payload["code"], "failure code"),
        message=_require_str(payload["message"], "failure message"),
        as_of_date=None if as_of_value is None else _parse_date(as_of_value, "failure as-of"),
        stock_code=(
            None if stock_code_value is None else _require_str(stock_code_value, "stock code")
        ),
    )


def _verify_trial_fingerprints(trial: RiskModelResearchTrial) -> None:
    expected_config = fingerprint_risk_model_config(trial.config)
    if trial.config_fingerprint != expected_config:
        raise RiskModelTrialCorruptionError("위험모형 trial 설정 fingerprint가 일치하지 않습니다.")
    if trial.aligned_returns is not None:
        expected_input = fingerprint_aligned_return_matrix(trial.aligned_returns, trial.config)
        if trial.input_fingerprint != expected_input:
            raise RiskModelTrialCorruptionError(
                "위험모형 trial 입력 fingerprint가 일치하지 않습니다."
            )
        if trial.result is not None:
            matrix = trial.aligned_returns
            for snapshot in trial.result.snapshots:
                end_index = matrix.dates.index(snapshot.as_of_date)
                start_index = end_index + 1 - snapshot.consumed_observation_count
                expected_snapshot = fingerprint_consumed_risk_input(
                    matrix.stock_codes,
                    matrix.dates[start_index : end_index + 1],
                    matrix.values[start_index : end_index + 1],
                    trial.config,
                )
                if snapshot.consumed_input_fingerprint != expected_snapshot:
                    raise RiskModelTrialCorruptionError(
                        "위험모형 snapshot 입력 fingerprint가 일치하지 않습니다."
                    )
    expected_trial = fingerprint_risk_model_trial(
        trial.config_fingerprint,
        trial.input_fingerprint,
    )
    if trial.trial_fingerprint != expected_trial:
        raise RiskModelTrialCorruptionError("위험모형 trial fingerprint가 일치하지 않습니다.")


def _float_matrix_payload(matrix: tuple[tuple[float, ...], ...]) -> list[list[float]]:
    return [[_json_float(value) for value in row] for row in matrix]


def _json_float(value: float) -> float:
    if type(value) is not float or not math.isfinite(value):
        raise RiskModelTrialStorageError("위험모형 JSON에는 유한한 float만 저장할 수 있습니다.")
    return 0.0 if value == 0.0 else value


def _require_dict(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise RiskModelTrialCorruptionError(f"{label} JSON object가 올바르지 않습니다.")
    return cast(dict[str, object], value)


def _require_list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise RiskModelTrialCorruptionError(f"{label} JSON array가 올바르지 않습니다.")
    return cast(list[object], value)


def _require_str(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise RiskModelTrialCorruptionError(f"{label} 문자열이 올바르지 않습니다.")
    return value


def _require_int(value: object, label: str) -> int:
    if type(value) is not int:
        raise RiskModelTrialCorruptionError(f"{label} 정수가 올바르지 않습니다.")
    return value


def _require_float(value: object, label: str) -> float:
    if type(value) is not float or not math.isfinite(value):
        raise RiskModelTrialCorruptionError(f"{label} float가 올바르지 않습니다.")
    return value


def _require_bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise RiskModelTrialCorruptionError(f"{label} bool이 올바르지 않습니다.")
    return value


def _require_exact(payload: dict[str, object], key: str, expected: str) -> None:
    if payload.get(key) != expected:
        raise RiskModelTrialCorruptionError(f"지원하지 않는 위험모형 {key}입니다.")


def _parse_date(value: object, label: str) -> date:
    try:
        return date.fromisoformat(_require_str(value, label))
    except ValueError:
        raise RiskModelTrialCorruptionError(f"{label} 날짜가 올바르지 않습니다.") from None


def _parse_datetime(value: object, label: str) -> datetime:
    try:
        return datetime.fromisoformat(_require_str(value, label))
    except ValueError:
        raise RiskModelTrialCorruptionError(f"{label} 시각이 올바르지 않습니다.") from None


def _parse_decimal(value: object, label: str) -> Decimal:
    try:
        result = Decimal(_require_str(value, label))
    except InvalidOperation:
        raise RiskModelTrialCorruptionError(f"{label} Decimal이 올바르지 않습니다.") from None
    if not result.is_finite():
        raise RiskModelTrialCorruptionError(f"{label} Decimal은 유한해야 합니다.")
    return result


def _string_tuple(value: object, label: str) -> tuple[str, ...]:
    return tuple(_require_str(item, label) for item in _require_list(value, label))


def _date_tuple(value: object, label: str) -> tuple[date, ...]:
    return tuple(_parse_date(item, label) for item in _require_list(value, label))


def _float_tuple(value: object, label: str) -> tuple[float, ...]:
    return tuple(_require_float(item, label) for item in _require_list(value, label))


def _float_matrix_from_payload(
    value: object,
    label: str,
) -> tuple[tuple[float, ...], ...]:
    return tuple(_float_tuple(row, label) for row in _require_list(value, label))


__all__ = [
    "JsonRiskModelTrialRegistry",
    "RiskModelTrialRegistry",
    "serialize_risk_model_trial",
]
