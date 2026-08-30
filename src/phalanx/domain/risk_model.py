"""Immutable, provider-neutral dynamic risk-model research contracts."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise

from phalanx.domain.portfolio import AlignedReturnMatrix
from phalanx.portfolio.errors import (
    RiskModelConfigurationError,
    RiskModelNumericalError,
)

DYNAMIC_RISK_MODEL_VERSION = "dynamic-risk-model-v1"
RISK_MODEL_SCHEMA_VERSION = "1"
RISK_MODEL_RESEARCH_SCOPE = "현재 유니버스 조건부 위험모형 연구"

_STOCK_CODE_PATTERN = re.compile(r"^[0-9]{6}$")
_TRIAL_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_FAILURE_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_MATRIX_TOLERANCE = 1e-10


class CovarianceScenarioKind(StrEnum):
    """Fixed v1 covariance forecast scenarios in audit order."""

    LONG_RUN_LEDOIT_WOLF = "long_run_ledoit_wolf"
    FAST_IEWMA = "fast_iewma"
    SLOW_IEWMA = "slow_iewma"
    DOWNSIDE_STRESS_LEDOIT_WOLF = "downside_stress_ledoit_wolf"


SCENARIO_KIND_ORDER = (
    CovarianceScenarioKind.LONG_RUN_LEDOIT_WOLF,
    CovarianceScenarioKind.FAST_IEWMA,
    CovarianceScenarioKind.SLOW_IEWMA,
    CovarianceScenarioKind.DOWNSIDE_STRESS_LEDOIT_WOLF,
)


class RiskModelResearchStatus(StrEnum):
    """Whole-trial state; one failed snapshot makes the trial failed."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class DynamicRiskModelConfig:
    """Fixed v1 estimator and rolling-research settings."""

    minimum_observations: int = 504
    maximum_observations: int = 756
    rebalance_interval: int = 5
    annualization_days: int = 252
    fast_volatility_half_life: int = 21
    fast_correlation_half_life: int = 63
    slow_volatility_half_life: int = 63
    slow_correlation_half_life: int = 125
    standardized_return_clip: float = 4.2
    minimum_volatility_seed_observations: int = 20
    minimum_correlation_observations: int = 60
    downside_fraction: Decimal = Decimal("0.20")
    minimum_downside_observations: int = 60
    psd_relative_eigen_tolerance: float = 1e-10
    psd_absolute_eigen_tolerance: float = 1e-15
    maximum_relative_psd_repair: float = 1e-8

    def __post_init__(self) -> None:
        positive_integers = (
            ("최소 관측치", self.minimum_observations),
            ("최대 관측치", self.maximum_observations),
            ("연구 간격", self.rebalance_interval),
            ("연환산 거래일", self.annualization_days),
            ("fast 변동성 반감기", self.fast_volatility_half_life),
            ("fast 상관관계 반감기", self.fast_correlation_half_life),
            ("slow 변동성 반감기", self.slow_volatility_half_life),
            ("slow 상관관계 반감기", self.slow_correlation_half_life),
            ("최소 변동성 seed 관측치", self.minimum_volatility_seed_observations),
            ("최소 상관관계 관측치", self.minimum_correlation_observations),
            ("최소 하방 관측치", self.minimum_downside_observations),
        )
        for name, value in positive_integers:
            if type(value) is not int or value <= 0:
                raise RiskModelConfigurationError(f"{name}는 양의 정수여야 합니다.")
        if self.minimum_observations > self.maximum_observations:
            raise RiskModelConfigurationError("최소 관측치는 최대 관측치보다 클 수 없습니다.")
        if self.fast_volatility_half_life >= self.fast_correlation_half_life:
            raise RiskModelConfigurationError(
                "fast IEWMA 변동성 반감기는 상관관계 반감기보다 짧아야 합니다."
            )
        if self.slow_volatility_half_life >= self.slow_correlation_half_life:
            raise RiskModelConfigurationError(
                "slow IEWMA 변동성 반감기는 상관관계 반감기보다 짧아야 합니다."
            )
        if self.fast_volatility_half_life >= self.slow_volatility_half_life:
            raise RiskModelConfigurationError(
                "fast 변동성 반감기는 slow 변동성 반감기보다 짧아야 합니다."
            )
        if self.fast_correlation_half_life >= self.slow_correlation_half_life:
            raise RiskModelConfigurationError(
                "fast 상관관계 반감기는 slow 상관관계 반감기보다 짧아야 합니다."
            )
        if not _is_positive_finite_float(self.standardized_return_clip):
            raise RiskModelConfigurationError("표준화 수익률 clip은 양의 유한한 float여야 합니다.")
        if (
            not isinstance(self.downside_fraction, Decimal)
            or not self.downside_fraction.is_finite()
            or not Decimal(0) < self.downside_fraction < Decimal(1)
        ):
            raise RiskModelConfigurationError(
                "하방 비율은 0과 1 사이의 유한한 Decimal이어야 합니다."
            )
        if not _is_positive_finite_float(self.psd_relative_eigen_tolerance):
            raise RiskModelConfigurationError("PSD 상대 고윳값 허용오차는 양수여야 합니다.")
        if not _is_positive_finite_float(self.psd_absolute_eigen_tolerance):
            raise RiskModelConfigurationError("PSD 절대 고윳값 허용오차는 양수여야 합니다.")
        if not _is_positive_finite_float(self.maximum_relative_psd_repair):
            raise RiskModelConfigurationError("PSD 상대 보정 상한은 양수여야 합니다.")
        if self.psd_relative_eigen_tolerance >= 1:
            raise RiskModelConfigurationError("PSD 상대 고윳값 허용오차는 1보다 작아야 합니다.")
        if self.psd_absolute_eigen_tolerance >= 1:
            raise RiskModelConfigurationError("PSD 절대 고윳값 허용오차는 1보다 작아야 합니다.")
        if not self.psd_relative_eigen_tolerance < self.maximum_relative_psd_repair < 1:
            raise RiskModelConfigurationError(
                "PSD 상대 보정 상한은 상대 고윳값 허용오차보다 크고 1보다 작아야 합니다."
            )


@dataclass(frozen=True, slots=True)
class PsdDiagnostics:
    """Auditable numerical diagnostics for one PSD quality check."""

    minimum_eigenvalue_before: float
    minimum_eigenvalue_after: float
    maximum_eigenvalue_after: float
    numerical_tolerance: float
    rank: int
    condition_number: float | None
    frobenius_repair_norm: float
    relative_repair_norm: float
    repaired: bool

    def __post_init__(self) -> None:
        finite_values = (
            self.minimum_eigenvalue_before,
            self.minimum_eigenvalue_after,
            self.maximum_eigenvalue_after,
            self.numerical_tolerance,
            self.frobenius_repair_norm,
            self.relative_repair_norm,
        )
        if any(not _is_finite_float(value) for value in finite_values):
            raise RiskModelNumericalError("PSD 진단에는 유한한 float 값만 사용할 수 있습니다.")
        if self.numerical_tolerance <= 0:
            raise RiskModelNumericalError("PSD 수치 허용오차는 양수여야 합니다.")
        if self.minimum_eigenvalue_after < -self.numerical_tolerance:
            raise RiskModelNumericalError("PSD 보정 뒤 음의 고윳값이 허용오차를 넘습니다.")
        if self.maximum_eigenvalue_after < self.minimum_eigenvalue_after:
            raise RiskModelNumericalError("PSD 진단의 최대 고윳값이 최소 고윳값보다 작습니다.")
        if type(self.rank) is not int or self.rank < 0:
            raise RiskModelNumericalError("PSD 행렬 rank는 0 이상의 정수여야 합니다.")
        if self.condition_number is not None and (
            not _is_finite_float(self.condition_number) or self.condition_number < 1
        ):
            raise RiskModelNumericalError(
                "PSD condition number는 1 이상의 유한한 float여야 합니다."
            )
        if self.frobenius_repair_norm < 0 or self.relative_repair_norm < 0:
            raise RiskModelNumericalError("PSD 보정 크기는 음수일 수 없습니다.")
        if type(self.repaired) is not bool:
            raise RiskModelNumericalError("PSD repaired 표시는 bool이어야 합니다.")


@dataclass(frozen=True, slots=True)
class LedoitWolfMetadata:
    """Long-run zero-centered Ledoit-Wolf estimator provenance."""

    shrinkage: float
    assume_centered: bool = True
    store_precision: bool = False
    estimator: str = "sklearn.covariance.LedoitWolf"
    moment_assumption: str = "zero_daily_mean_second_moment"

    def __post_init__(self) -> None:
        if not _is_finite_float(self.shrinkage) or not 0 <= self.shrinkage <= 1:
            raise RiskModelNumericalError("Ledoit-Wolf shrinkage는 0과 1 사이여야 합니다.")
        if self.assume_centered is not True or self.store_precision is not False:
            raise RiskModelNumericalError(
                "Ledoit-Wolf는 assume_centered=True, store_precision=False여야 합니다."
            )
        if self.estimator != "sklearn.covariance.LedoitWolf":
            raise RiskModelNumericalError("Ledoit-Wolf estimator 식별자가 올바르지 않습니다.")
        if self.moment_assumption != "zero_daily_mean_second_moment":
            raise RiskModelNumericalError("Ledoit-Wolf second-moment 가정이 올바르지 않습니다.")


@dataclass(frozen=True, slots=True)
class IewmaMetadata:
    """Causal finite-history IEWMA estimator provenance."""

    volatility_half_life: int
    correlation_half_life: int
    volatility_seed_count: int
    correlation_observation_count: int
    volatility_effective_sample_size: float
    correlation_effective_sample_size: float
    clip_threshold: float
    clipped_scalar_count: int
    correlation_psd_diagnostics: PsdDiagnostics
    forecast_horizon: str = "next_return_period"

    def __post_init__(self) -> None:
        for integer_value in (
            self.volatility_half_life,
            self.correlation_half_life,
            self.volatility_seed_count,
            self.correlation_observation_count,
        ):
            if type(integer_value) is not int or integer_value <= 0:
                raise RiskModelNumericalError("IEWMA 반감기와 관측치 수는 양의 정수여야 합니다.")
        if self.volatility_half_life >= self.correlation_half_life:
            raise RiskModelNumericalError(
                "IEWMA 변동성 반감기는 상관관계 반감기보다 짧아야 합니다."
            )
        for float_value in (
            self.volatility_effective_sample_size,
            self.correlation_effective_sample_size,
            self.clip_threshold,
        ):
            if not _is_positive_finite_float(float_value):
                raise RiskModelNumericalError("IEWMA ESS와 clip은 양의 유한한 float여야 합니다.")
        if type(self.clipped_scalar_count) is not int or self.clipped_scalar_count < 0:
            raise RiskModelNumericalError("IEWMA clipping 수는 0 이상의 정수여야 합니다.")
        if not isinstance(self.correlation_psd_diagnostics, PsdDiagnostics):
            raise RiskModelNumericalError("IEWMA correlation PSD 진단이 올바르지 않습니다.")
        if self.forecast_horizon != "next_return_period":
            raise RiskModelNumericalError("IEWMA 예측 구간은 next_return_period여야 합니다.")


@dataclass(frozen=True, slots=True)
class DownsideStressMetadata:
    """Current-universe bottom-date zero-centered stress provenance."""

    downside_fraction: Decimal
    selected_count: int
    cutoff_equal_weight_return: Decimal
    selected_dates: tuple[date, ...]
    selected_dates_fingerprint: str
    shrinkage: float
    assume_centered: bool = True
    store_precision: bool = False
    estimator: str = "sklearn.covariance.LedoitWolf"
    moment_assumption: str = "conditional_zero_centered_second_moment"

    def __post_init__(self) -> None:
        if (
            not isinstance(self.downside_fraction, Decimal)
            or not self.downside_fraction.is_finite()
            or not Decimal(0) < self.downside_fraction < Decimal(1)
        ):
            raise RiskModelNumericalError("하방 비율은 0과 1 사이의 유한한 Decimal이어야 합니다.")
        if type(self.selected_count) is not int or self.selected_count <= 0:
            raise RiskModelNumericalError("하방 선택 관측치 수는 양의 정수여야 합니다.")
        if (
            not isinstance(self.cutoff_equal_weight_return, Decimal)
            or not self.cutoff_equal_weight_return.is_finite()
        ):
            raise RiskModelNumericalError("하방 cutoff는 유한한 Decimal이어야 합니다.")
        if (
            not isinstance(self.selected_dates, tuple)
            or not self.selected_dates
            or any(type(value) is not date for value in self.selected_dates)
            or len(set(self.selected_dates)) != len(self.selected_dates)
        ):
            raise RiskModelNumericalError("하방 선택 날짜는 중복 없는 date tuple이어야 합니다.")
        if len(self.selected_dates) != self.selected_count:
            raise RiskModelNumericalError("하방 선택 날짜 수가 selected count와 일치하지 않습니다.")
        _validate_fingerprint(self.selected_dates_fingerprint, "하방 선택 날짜")
        if not _is_finite_float(self.shrinkage) or not 0 <= self.shrinkage <= 1:
            raise RiskModelNumericalError("하방 Ledoit-Wolf shrinkage는 0과 1 사이여야 합니다.")
        if self.assume_centered is not True or self.store_precision is not False:
            raise RiskModelNumericalError(
                "하방 Ledoit-Wolf는 assume_centered=True, store_precision=False여야 합니다."
            )
        if self.estimator != "sklearn.covariance.LedoitWolf":
            raise RiskModelNumericalError("하방 estimator 식별자가 올바르지 않습니다.")
        if self.moment_assumption != "conditional_zero_centered_second_moment":
            raise RiskModelNumericalError("하방 second-moment 가정이 올바르지 않습니다.")


type ScenarioMetadata = LedoitWolfMetadata | IewmaMetadata | DownsideStressMetadata


@dataclass(frozen=True, slots=True)
class CovarianceScenario:
    """One independent annualized next-return-period covariance forecast."""

    kind: CovarianceScenarioKind
    stock_codes: tuple[str, ...]
    observation_dates: tuple[date, ...]
    annualized_covariance: tuple[tuple[float, ...], ...]
    annualized_volatilities: tuple[float, ...]
    correlation_matrix: tuple[tuple[float, ...], ...]
    metadata: ScenarioMetadata
    psd_diagnostics: PsdDiagnostics

    def __post_init__(self) -> None:
        if not isinstance(self.kind, CovarianceScenarioKind):
            raise RiskModelNumericalError("공분산 scenario 종류가 올바르지 않습니다.")
        _validate_stock_codes(self.stock_codes)
        _validate_dates(self.observation_dates, minimum=1, label="scenario 관측 날짜")
        size = len(self.stock_codes)
        _validate_float_matrix(self.annualized_covariance, size, "연환산 공분산")
        _validate_float_matrix(self.correlation_matrix, size, "상관계수")
        if len(self.annualized_volatilities) != size or any(
            not _is_finite_float(value) or value < 0 for value in self.annualized_volatilities
        ):
            raise RiskModelNumericalError(
                "연환산 변동성은 종목 수와 같은 길이의 음수가 아닌 유한한 float여야 합니다."
            )
        _validate_symmetric(self.annualized_covariance, "연환산 공분산")
        _validate_symmetric(self.correlation_matrix, "상관계수")
        for index in range(size):
            covariance_diagonal = self.annualized_covariance[index][index]
            if covariance_diagonal < 0:
                raise RiskModelNumericalError("연환산 공분산 대각원소는 음수일 수 없습니다.")
            expected_volatility = math.sqrt(covariance_diagonal)
            if not math.isclose(
                self.annualized_volatilities[index],
                expected_volatility,
                rel_tol=1e-10,
                abs_tol=1e-14,
            ):
                raise RiskModelNumericalError(
                    "연환산 변동성이 공분산 대각원소와 일치하지 않습니다."
                )
            if not math.isclose(
                self.correlation_matrix[index][index],
                1.0,
                rel_tol=0.0,
                abs_tol=_MATRIX_TOLERANCE,
            ):
                raise RiskModelNumericalError("상관계수 행렬 대각원소는 1이어야 합니다.")
        if any(
            value < -1 - _MATRIX_TOLERANCE or value > 1 + _MATRIX_TOLERANCE
            for row in self.correlation_matrix
            for value in row
        ):
            raise RiskModelNumericalError("상관계수는 -1과 1 사이여야 합니다.")
        if not isinstance(self.psd_diagnostics, PsdDiagnostics):
            raise RiskModelNumericalError("scenario PSD 진단이 올바르지 않습니다.")
        if self.psd_diagnostics.rank > size:
            raise RiskModelNumericalError("scenario PSD rank가 종목 수를 넘습니다.")
        expected_metadata_type: type[object]
        if self.kind is CovarianceScenarioKind.LONG_RUN_LEDOIT_WOLF:
            expected_metadata_type = LedoitWolfMetadata
        elif self.kind in (
            CovarianceScenarioKind.FAST_IEWMA,
            CovarianceScenarioKind.SLOW_IEWMA,
        ):
            expected_metadata_type = IewmaMetadata
        else:
            expected_metadata_type = DownsideStressMetadata
        if not isinstance(self.metadata, expected_metadata_type):
            raise RiskModelNumericalError("scenario 종류와 metadata 타입이 일치하지 않습니다.")


@dataclass(frozen=True, slots=True)
class DynamicRiskModelSnapshot:
    """Four independent forecasts made with one exact trailing return window."""

    as_of_date: date
    consumed_start_date: date
    consumed_end_date: date
    consumed_observation_count: int
    stock_codes: tuple[str, ...]
    consumed_dates: tuple[date, ...]
    scenarios: tuple[CovarianceScenario, ...]
    consumed_input_fingerprint: str
    model_version: str = DYNAMIC_RISK_MODEL_VERSION
    schema_version: str = RISK_MODEL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if type(self.as_of_date) is not date:
            raise RiskModelNumericalError("위험모형 as-of는 date 값이어야 합니다.")
        _validate_stock_codes(self.stock_codes)
        _validate_dates(self.consumed_dates, minimum=1, label="소비 수익률 날짜")
        if (
            type(self.consumed_start_date) is not date
            or type(self.consumed_end_date) is not date
            or self.consumed_start_date != self.consumed_dates[0]
            or self.consumed_end_date != self.consumed_dates[-1]
        ):
            raise RiskModelNumericalError("소비 기간은 실제 소비 수익률 날짜와 일치해야 합니다.")
        if self.as_of_date != self.consumed_end_date:
            raise RiskModelNumericalError("위험모형 as-of는 소비 기간 종료일과 일치해야 합니다.")
        if type(
            self.consumed_observation_count
        ) is not int or self.consumed_observation_count != len(self.consumed_dates):
            raise RiskModelNumericalError("소비 관측치 수가 소비 날짜 수와 일치하지 않습니다.")
        if not isinstance(self.scenarios, tuple):
            raise RiskModelNumericalError("위험모형 scenarios는 tuple이어야 합니다.")
        if tuple(scenario.kind for scenario in self.scenarios) != SCENARIO_KIND_ORDER:
            raise RiskModelNumericalError(
                "위험모형 snapshot에는 고정 순서의 네 scenario가 정확히 한 번씩 필요합니다."
            )
        for scenario in self.scenarios:
            if scenario.stock_codes != self.stock_codes:
                raise RiskModelNumericalError("scenario 종목 순서가 snapshot과 일치하지 않습니다.")
            if scenario.observation_dates != self.consumed_dates:
                raise RiskModelNumericalError("scenario 소비 날짜가 snapshot과 일치하지 않습니다.")
        _validate_fingerprint(self.consumed_input_fingerprint, "소비 입력")
        if self.model_version != DYNAMIC_RISK_MODEL_VERSION:
            raise RiskModelNumericalError("위험모형 model version이 올바르지 않습니다.")
        if self.schema_version != RISK_MODEL_SCHEMA_VERSION:
            raise RiskModelNumericalError("위험모형 schema version이 올바르지 않습니다.")

    def get_scenario(self, kind: CovarianceScenarioKind) -> CovarianceScenario:
        """Return one explicitly selected scenario without an implicit default."""

        if not isinstance(kind, CovarianceScenarioKind):
            raise RiskModelNumericalError("조회할 scenario 종류가 올바르지 않습니다.")
        for scenario in self.scenarios:
            if scenario.kind is kind:
                return scenario
        raise RiskModelNumericalError("요청한 scenario가 snapshot에 없습니다.")


@dataclass(frozen=True, slots=True)
class RiskModelFailure:
    """Allow-listed, secret-free failure provenance."""

    code: str
    message: str
    as_of_date: date | None = None
    stock_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or _FAILURE_CODE_PATTERN.fullmatch(self.code) is None:
            raise RiskModelNumericalError("위험모형 실패 코드가 올바르지 않습니다.")
        if (
            not isinstance(self.message, str)
            or not self.message
            or self.message != self.message.strip()
            or len(self.message) > 500
        ):
            raise RiskModelNumericalError("위험모형 실패 메시지가 올바르지 않습니다.")
        if self.as_of_date is not None and type(self.as_of_date) is not date:
            raise RiskModelNumericalError("위험모형 실패 as-of는 date 또는 None이어야 합니다.")
        if self.stock_code is not None and (
            not isinstance(self.stock_code, str)
            or _STOCK_CODE_PATTERN.fullmatch(self.stock_code) is None
        ):
            raise RiskModelNumericalError("위험모형 실패 종목코드는 6자리 숫자여야 합니다.")


@dataclass(frozen=True, slots=True)
class DynamicRiskModelResearchResult:
    """Whole rolling schedule outcome; partial snapshots are retained on failure."""

    status: RiskModelResearchStatus
    stock_codes: tuple[str, ...]
    scheduled_as_of_dates: tuple[date, ...]
    snapshots: tuple[DynamicRiskModelSnapshot, ...]
    failure: RiskModelFailure | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, RiskModelResearchStatus):
            raise RiskModelNumericalError("위험모형 연구 상태가 올바르지 않습니다.")
        _validate_stock_codes(self.stock_codes)
        _validate_dates(self.scheduled_as_of_dates, minimum=1, label="연구 예정 as-of")
        if not isinstance(self.snapshots, tuple) or any(
            not isinstance(snapshot, DynamicRiskModelSnapshot) for snapshot in self.snapshots
        ):
            raise RiskModelNumericalError("연구 snapshots는 불변 snapshot tuple이어야 합니다.")
        if len(self.snapshots) > len(self.scheduled_as_of_dates):
            raise RiskModelNumericalError("완료 snapshot 수가 예정 as-of 수를 넘습니다.")
        for index, snapshot in enumerate(self.snapshots):
            if snapshot.stock_codes != self.stock_codes:
                raise RiskModelNumericalError("snapshot 종목 순서가 연구 결과와 일치하지 않습니다.")
            if snapshot.as_of_date != self.scheduled_as_of_dates[index]:
                raise RiskModelNumericalError(
                    "snapshot as-of 순서가 예정 일정과 일치하지 않습니다."
                )
        if self.status is RiskModelResearchStatus.SUCCEEDED:
            if self.failure is not None or len(self.snapshots) != len(self.scheduled_as_of_dates):
                raise RiskModelNumericalError(
                    "성공 연구에는 모든 snapshot과 실패 정보 없음이 필요합니다."
                )
        else:
            if self.failure is None or len(self.snapshots) >= len(self.scheduled_as_of_dates):
                raise RiskModelNumericalError(
                    "실패 연구에는 실패 정보와 미완료 snapshot이 필요합니다."
                )
            expected_failed_date = self.scheduled_as_of_dates[len(self.snapshots)]
            if (
                self.failure.as_of_date is not None
                and self.failure.as_of_date != expected_failed_date
            ):
                raise RiskModelNumericalError(
                    "실패 as-of가 최초 미완료 예정일과 일치하지 않습니다."
                )


@dataclass(frozen=True, slots=True)
class RiskModelLibraryProvenance:
    """Runtime versions needed to reproduce estimator behavior."""

    python_version: str
    numpy_version: str
    scikit_learn_version: str
    model_version: str = DYNAMIC_RISK_MODEL_VERSION
    schema_version: str = RISK_MODEL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name, value in (
            ("Python", self.python_version),
            ("NumPy", self.numpy_version),
            ("scikit-learn", self.scikit_learn_version),
        ):
            if not isinstance(value, str) or not value.strip() or len(value) > 128:
                raise RiskModelNumericalError(f"{name} provenance가 올바르지 않습니다.")
        if self.model_version != DYNAMIC_RISK_MODEL_VERSION:
            raise RiskModelNumericalError("provenance model version이 올바르지 않습니다.")
        if self.schema_version != RISK_MODEL_SCHEMA_VERSION:
            raise RiskModelNumericalError("provenance schema version이 올바르지 않습니다.")


@dataclass(frozen=True, slots=True)
class RiskModelResearchTrial:
    """One reproducible current-universe-conditional risk-model trial."""

    trial_id: str
    status: RiskModelResearchStatus
    executed_at: datetime
    requested_start: date
    requested_end: date
    stock_codes: tuple[str, ...]
    aligned_returns: AlignedReturnMatrix | None
    config: DynamicRiskModelConfig
    config_fingerprint: str
    input_fingerprint: str
    trial_fingerprint: str
    provenance: RiskModelLibraryProvenance
    result: DynamicRiskModelResearchResult | None
    failure: RiskModelFailure | None
    model_version: str = DYNAMIC_RISK_MODEL_VERSION
    schema_version: str = RISK_MODEL_SCHEMA_VERSION
    research_scope: str = RISK_MODEL_RESEARCH_SCOPE

    def __post_init__(self) -> None:
        if not isinstance(self.trial_id, str) or _TRIAL_ID_PATTERN.fullmatch(self.trial_id) is None:
            raise RiskModelNumericalError(
                "risk trial ID는 경로 구분자 없는 영문자·숫자·밑줄·하이픈이어야 합니다."
            )
        if not isinstance(self.status, RiskModelResearchStatus):
            raise RiskModelNumericalError("risk trial 상태가 올바르지 않습니다.")
        if (
            not isinstance(self.executed_at, datetime)
            or self.executed_at.tzinfo is None
            or self.executed_at.utcoffset() is None
        ):
            raise RiskModelNumericalError("risk trial 실행시각은 timezone-aware여야 합니다.")
        if type(self.requested_start) is not date or type(self.requested_end) is not date:
            raise RiskModelNumericalError("risk trial 요청기간은 date 값이어야 합니다.")
        if self.requested_start > self.requested_end:
            raise RiskModelNumericalError("risk trial 요청 시작일은 종료일보다 늦을 수 없습니다.")
        if self.stock_codes:
            _validate_stock_codes(self.stock_codes)
        elif self.status is RiskModelResearchStatus.SUCCEEDED:
            raise RiskModelNumericalError("성공 risk trial에는 활성 종목코드가 필요합니다.")
        if self.aligned_returns is not None:
            if not isinstance(self.aligned_returns, AlignedReturnMatrix):
                raise RiskModelNumericalError("trial aligned returns 타입이 올바르지 않습니다.")
            if self.aligned_returns.stock_codes != self.stock_codes:
                raise RiskModelNumericalError(
                    "trial 종목 순서가 aligned returns와 일치하지 않습니다."
                )
        if not isinstance(self.config, DynamicRiskModelConfig):
            raise RiskModelNumericalError("trial 설정은 DynamicRiskModelConfig여야 합니다.")
        for name, value in (
            ("설정", self.config_fingerprint),
            ("입력", self.input_fingerprint),
            ("trial", self.trial_fingerprint),
        ):
            _validate_fingerprint(value, name)
        if not isinstance(self.provenance, RiskModelLibraryProvenance):
            raise RiskModelNumericalError("trial library provenance가 올바르지 않습니다.")
        if self.status is RiskModelResearchStatus.SUCCEEDED:
            if self.result is None or self.failure is not None:
                raise RiskModelNumericalError("성공 risk trial에는 성공 결과만 있어야 합니다.")
            if self.result.status is not RiskModelResearchStatus.SUCCEEDED:
                raise RiskModelNumericalError("trial과 연구 결과 상태가 일치하지 않습니다.")
        else:
            if self.failure is None:
                raise RiskModelNumericalError("실패 risk trial에는 정제된 실패 정보가 필요합니다.")
            if self.result is not None and (
                self.result.status is not RiskModelResearchStatus.FAILED
                or self.result.failure != self.failure
            ):
                raise RiskModelNumericalError(
                    "실패 trial과 rolling 연구 실패 정보가 일치하지 않습니다."
                )
        if self.result is not None and self.result.stock_codes != self.stock_codes:
            raise RiskModelNumericalError("trial과 연구 결과 종목 순서가 일치하지 않습니다.")
        if self.model_version != DYNAMIC_RISK_MODEL_VERSION:
            raise RiskModelNumericalError("trial model version이 올바르지 않습니다.")
        if self.schema_version != RISK_MODEL_SCHEMA_VERSION:
            raise RiskModelNumericalError("trial schema version이 올바르지 않습니다.")
        if self.research_scope != RISK_MODEL_RESEARCH_SCOPE:
            raise RiskModelNumericalError("trial 연구 범위 표시가 올바르지 않습니다.")


def _validate_stock_codes(stock_codes: tuple[str, ...]) -> None:
    if not isinstance(stock_codes, tuple) or not stock_codes:
        raise RiskModelNumericalError("위험모형에는 최소 1개의 종목코드가 필요합니다.")
    if any(
        not isinstance(stock_code, str) or _STOCK_CODE_PATTERN.fullmatch(stock_code) is None
        for stock_code in stock_codes
    ):
        raise RiskModelNumericalError("위험모형 종목코드는 공백 없는 6자리 숫자여야 합니다.")
    if len(set(stock_codes)) != len(stock_codes):
        raise RiskModelNumericalError("위험모형 종목코드에 중복이 있습니다.")


def _validate_dates(dates: tuple[date, ...], *, minimum: int, label: str) -> None:
    if not isinstance(dates, tuple) or len(dates) < minimum:
        raise RiskModelNumericalError(f"{label}는 최소 {minimum}개가 필요합니다.")
    if any(type(value) is not date for value in dates):
        raise RiskModelNumericalError(f"{label}는 date 값이어야 합니다.")
    if len(set(dates)) != len(dates) or any(
        current <= previous for previous, current in pairwise(dates)
    ):
        raise RiskModelNumericalError(f"{label}는 중복 없는 엄격한 오름차순이어야 합니다.")


def _validate_float_matrix(
    matrix: tuple[tuple[float, ...], ...],
    size: int,
    label: str,
) -> None:
    if not isinstance(matrix, tuple) or len(matrix) != size:
        raise RiskModelNumericalError(f"{label} 행 수는 종목 수와 일치해야 합니다.")
    for row in matrix:
        if not isinstance(row, tuple) or len(row) != size:
            raise RiskModelNumericalError(f"{label}은 N x N tuple 행렬이어야 합니다.")
        if any(not _is_finite_float(value) for value in row):
            raise RiskModelNumericalError(f"{label}에는 유한한 float만 사용할 수 있습니다.")


def _validate_symmetric(matrix: tuple[tuple[float, ...], ...], label: str) -> None:
    for row_index, row in enumerate(matrix):
        for column_index in range(row_index):
            if not math.isclose(
                row[column_index],
                matrix[column_index][row_index],
                rel_tol=_MATRIX_TOLERANCE,
                abs_tol=_MATRIX_TOLERANCE,
            ):
                raise RiskModelNumericalError(f"{label}은 대칭이어야 합니다.")


def _validate_fingerprint(value: object, label: str) -> None:
    if not isinstance(value, str) or _FINGERPRINT_PATTERN.fullmatch(value) is None:
        raise RiskModelNumericalError(f"{label} fingerprint는 64자리 소문자 SHA-256이어야 합니다.")


def _is_finite_float(value: object) -> bool:
    return type(value) is float and math.isfinite(value)


def _is_positive_finite_float(value: object) -> bool:
    return type(value) is float and math.isfinite(value) and value > 0


__all__ = [
    "DYNAMIC_RISK_MODEL_VERSION",
    "RISK_MODEL_RESEARCH_SCOPE",
    "RISK_MODEL_SCHEMA_VERSION",
    "SCENARIO_KIND_ORDER",
    "CovarianceScenario",
    "CovarianceScenarioKind",
    "DownsideStressMetadata",
    "DynamicRiskModelConfig",
    "DynamicRiskModelResearchResult",
    "DynamicRiskModelSnapshot",
    "IewmaMetadata",
    "LedoitWolfMetadata",
    "PsdDiagnostics",
    "RiskModelFailure",
    "RiskModelLibraryProvenance",
    "RiskModelResearchStatus",
    "RiskModelResearchTrial",
    "ScenarioMetadata",
]
