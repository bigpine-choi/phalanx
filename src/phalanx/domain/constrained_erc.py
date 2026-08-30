"""Immutable contracts for constrained equal-risk-contribution research."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Context, Decimal, localcontext
from enum import StrEnum
from itertools import pairwise
from typing import TypeGuard

from phalanx.domain.allocation import (
    AlignedPricePanel,
    AllocationBacktestConfig,
    AllocationBacktestResult,
)
from phalanx.domain.portfolio import AlignedReturnMatrix
from phalanx.domain.risk_model import (
    SCENARIO_KIND_ORDER,
    CovarianceScenarioKind,
    DynamicRiskModelConfig,
    DynamicRiskModelSnapshot,
    RiskModelLibraryProvenance,
)
from phalanx.portfolio.errors import InvalidConstrainedErcDomainError

CONSTRAINED_ERC_SCHEMA = "phalanx.constrained_erc_research_trial.v1"
CONSTRAINED_ERC_SCHEMA_VERSION = "1"
CONSTRAINED_ERC_SOLVER_VERSION = "constrained-erc-ccd-bisection-v1"
CONSTRAINED_ERC_CODE_MODEL_VERSION = "constrained-erc-research-v1"
CONSTRAINED_ERC_RESEARCH_SCOPE = "current-universe conditional allocation-only"

CONSTRAINED_ERC_SCENARIO_POLICY_IDS = (
    "constrained_erc_long_run_ledoit_wolf",
    "constrained_erc_fast_iewma",
    "constrained_erc_slow_iewma",
    "constrained_erc_downside_stress_ledoit_wolf",
)
CONSTRAINED_ERC_CONTROL_POLICY_IDS = (
    "weekly_equal_weight",
    "weekly_inverse_volatility",
    "equal_weight_buy_and_hold",
)
CONSTRAINED_ERC_POLICY_ORDER = (
    *CONSTRAINED_ERC_SCENARIO_POLICY_IDS,
    *CONSTRAINED_ERC_CONTROL_POLICY_IDS,
)

_STOCK_CODE_PATTERN = re.compile(r"^[0-9]{6}$")
_POLICY_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_TRIAL_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_ZERO = Decimal(0)
_ONE = Decimal(1)


class ConstrainedErcBoundFlag(StrEnum):
    """KKT classification for one final risky-asset weight."""

    FREE = "free"
    LOWER = "lower"
    UPPER = "upper"


class ConstrainedErcOutcomeStatus(StrEnum):
    """One policy or one risk-snapshot calculation state."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ConstrainedErcResearchStatus(StrEnum):
    """Whole-trial state; any failed policy makes the trial failed."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ConstrainedErcCommonFailureStage(StrEnum):
    """Stage at which one failure prevented every policy from running."""

    INPUT_PREPARATION = "input_preparation"


@dataclass(frozen=True, slots=True)
class ConstrainedErcSolverConfig:
    """Versioned deterministic CCD, bisection, and reconciliation settings."""

    weight_quantum: Decimal = Decimal("0.000000000001")
    coordinate_change_tolerance: float = 1e-12
    normalized_kkt_tolerance: float = 1e-10
    outer_sum_tolerance: float = 1e-12
    maximum_ccd_sweeps: int = 10_000
    maximum_bisection_iterations: int = 200
    maximum_bracket_expansions: int = 128
    bracket_expansion_factor: float = 2.0
    solver_version: str = CONSTRAINED_ERC_SOLVER_VERSION

    def __post_init__(self) -> None:
        if (
            not isinstance(self.weight_quantum, Decimal)
            or not self.weight_quantum.is_finite()
            or self.weight_quantum <= 0
        ):
            raise InvalidConstrainedErcDomainError(
                "ERC weight quantum은 양의 유한한 Decimal이어야 합니다."
            )
        for label, value in (
            ("CCD 좌표 변화 허용오차", self.coordinate_change_tolerance),
            ("정규화 KKT 허용오차", self.normalized_kkt_tolerance),
            ("outer 합계 허용오차", self.outer_sum_tolerance),
        ):
            if type(value) is not float or not math.isfinite(value) or value <= 0:
                raise InvalidConstrainedErcDomainError(f"{label}는 양의 유한한 float여야 합니다.")
        for label, value in (
            ("최대 CCD sweep", self.maximum_ccd_sweeps),
            ("최대 bisection 반복", self.maximum_bisection_iterations),
            ("최대 lambda bracket 확장", self.maximum_bracket_expansions),
        ):
            if type(value) is not int or value <= 0:
                raise InvalidConstrainedErcDomainError(f"{label}은 양의 정수여야 합니다.")
        if (
            type(self.bracket_expansion_factor) is not float
            or not math.isfinite(self.bracket_expansion_factor)
            or self.bracket_expansion_factor <= 1
        ):
            raise InvalidConstrainedErcDomainError(
                "lambda bracket 확장 배수는 1보다 큰 유한한 float여야 합니다."
            )
        if self.solver_version != CONSTRAINED_ERC_SOLVER_VERSION:
            raise InvalidConstrainedErcDomainError(
                "지원하지 않는 Constrained ERC solver 버전입니다."
            )


@dataclass(frozen=True, slots=True)
class ConstrainedErcKktDiagnostics:
    """Feasibility, Euler, contribution, and bound-KKT evidence for one solution."""

    weights: tuple[float, ...]
    portfolio_volatility: float
    marginal_risks: tuple[float, ...]
    absolute_risk_contributions: tuple[float, ...]
    relative_risk_contributions: tuple[float, ...]
    bound_flags: tuple[ConstrainedErcBoundFlag, ...]
    primal_residual: float
    euler_residual: float
    normalized_max_kkt_residual: float
    complementarity_residual: float
    free_asset_rc_dispersion: float | None

    def __post_init__(self) -> None:
        _require_tuple(self.weights, "KKT weights")
        if not self.weights or any(not _positive_finite_float(value) for value in self.weights):
            raise InvalidConstrainedErcDomainError(
                "KKT weights는 비어 있지 않은 양의 유한한 float tuple이어야 합니다."
            )
        size = len(self.weights)
        for label, values in (
            ("marginal risk", self.marginal_risks),
            ("absolute risk contribution", self.absolute_risk_contributions),
            ("relative risk contribution", self.relative_risk_contributions),
        ):
            _require_tuple(values, label)
            if len(values) != size or any(not _finite_float(value) for value in values):
                raise InvalidConstrainedErcDomainError(
                    f"{label}은 종목 수와 같은 길이의 유한한 float tuple이어야 합니다."
                )
        _require_tuple(self.bound_flags, "bound flags")
        if len(self.bound_flags) != size or any(
            not isinstance(value, ConstrainedErcBoundFlag) for value in self.bound_flags
        ):
            raise InvalidConstrainedErcDomainError(
                "bound flags는 종목 수와 같은 길이의 올바른 KKT 분류여야 합니다."
            )
        if not _positive_finite_float(self.portfolio_volatility):
            raise InvalidConstrainedErcDomainError(
                "포트폴리오 변동성은 양의 유한한 float여야 합니다."
            )
        for label, value in (
            ("primal residual", self.primal_residual),
            ("Euler residual", self.euler_residual),
            ("정규화 최대 KKT residual", self.normalized_max_kkt_residual),
            ("complementarity residual", self.complementarity_residual),
        ):
            if not _nonnegative_finite_float(value):
                raise InvalidConstrainedErcDomainError(
                    f"{label}은 음수가 아닌 유한한 float여야 합니다."
                )
        if self.free_asset_rc_dispersion is not None and not _nonnegative_finite_float(
            self.free_asset_rc_dispersion
        ):
            raise InvalidConstrainedErcDomainError(
                "free-asset RC dispersion은 None 또는 음수가 아닌 유한한 float여야 합니다."
            )
        has_free_asset = ConstrainedErcBoundFlag.FREE in self.bound_flags
        if has_free_asset != (self.free_asset_rc_dispersion is not None):
            raise InvalidConstrainedErcDomainError(
                "free-asset RC dispersion의 N/A 여부가 bound 분류와 일치하지 않습니다."
            )


@dataclass(frozen=True, slots=True)
class ConstrainedErcTarget:
    """One exact signal-date scenario solution consumed by the Decimal backtest."""

    policy_id: str
    scenario_kind: CovarianceScenarioKind
    as_of_date: date
    stock_codes: tuple[str, ...]
    risk_budgets: tuple[Decimal, ...]
    lower_bounds: tuple[Decimal, ...]
    upper_bounds: tuple[Decimal, ...]
    covariance_fingerprint: str
    lambda_value: float
    raw_float_weights: tuple[float, ...]
    reconciled_weights: tuple[Decimal, ...]
    diagnostics_before_reconciliation: ConstrainedErcKktDiagnostics
    diagnostics_after_reconciliation: ConstrainedErcKktDiagnostics
    reconciliation_max_error: float
    weight_sum_residual_before: float
    weight_sum_residual_after: Decimal
    ccd_sweeps: int
    bisection_iterations: int
    bracket_expansions: int
    solver_config_fingerprint: str
    all_assets_bound_degeneracy: bool
    solver_version: str = CONSTRAINED_ERC_SOLVER_VERSION

    def __post_init__(self) -> None:
        _validate_policy_id(self.policy_id)
        expected_policy_id = scenario_policy_id(self.scenario_kind)
        if self.policy_id != expected_policy_id:
            raise InvalidConstrainedErcDomainError(
                "ERC 정책 식별자가 covariance scenario와 일치하지 않습니다."
            )
        if type(self.as_of_date) is not date:
            raise InvalidConstrainedErcDomainError("ERC 목표 as-of는 date 값이어야 합니다.")
        _validate_stock_codes(self.stock_codes)
        size = len(self.stock_codes)
        for label, values in (
            ("risk budgets", self.risk_budgets),
            ("lower bounds", self.lower_bounds),
            ("upper bounds", self.upper_bounds),
            ("Decimal 목표비중", self.reconciled_weights),
        ):
            _require_tuple(values, label)
            if len(values) != size or any(not _finite_decimal(value) for value in values):
                raise InvalidConstrainedErcDomainError(
                    f"{label}는 종목 수와 같은 길이의 유한한 Decimal tuple이어야 합니다."
                )
        if (
            any(value <= 0 for value in self.risk_budgets)
            or _decimal_sum(self.risk_budgets) != _ONE
        ):
            raise InvalidConstrainedErcDomainError(
                "risk budgets는 양수이고 합계가 정확히 1이어야 합니다."
            )
        for lower, upper in zip(self.lower_bounds, self.upper_bounds, strict=True):
            if lower < 0 or upper <= 0 or lower >= upper:
                raise InvalidConstrainedErcDomainError(
                    "ERC bounds는 0 <= lower < upper이고 upper는 양수여야 합니다."
                )
        if any(
            weight <= 0 or weight < lower or weight > upper
            for weight, lower, upper in zip(
                self.reconciled_weights,
                self.lower_bounds,
                self.upper_bounds,
                strict=True,
            )
        ):
            raise InvalidConstrainedErcDomainError(
                "reconciled ERC 목표비중은 양수이고 각 bounds 안에 있어야 합니다."
            )
        if _decimal_sum(self.reconciled_weights) != _ONE:
            raise InvalidConstrainedErcDomainError(
                "reconciled ERC 목표비중 합계는 정확히 1이어야 합니다."
            )
        _require_tuple(self.raw_float_weights, "raw float weights")
        if len(self.raw_float_weights) != size or any(
            not _positive_finite_float(value) for value in self.raw_float_weights
        ):
            raise InvalidConstrainedErcDomainError(
                "raw float weights는 종목 수와 같은 길이의 양의 유한한 tuple이어야 합니다."
            )
        if any(
            weight < float(lower) - 1e-12 or weight > float(upper) + 1e-12
            for weight, lower, upper in zip(
                self.raw_float_weights,
                self.lower_bounds,
                self.upper_bounds,
                strict=True,
            )
        ):
            raise InvalidConstrainedErcDomainError(
                "raw float weights는 고정 수치 허용오차 안에서 각 bounds를 지켜야 합니다."
            )
        if not isinstance(
            self.diagnostics_before_reconciliation,
            ConstrainedErcKktDiagnostics,
        ) or not isinstance(
            self.diagnostics_after_reconciliation,
            ConstrainedErcKktDiagnostics,
        ):
            raise InvalidConstrainedErcDomainError(
                "reconciliation 전후 진단은 올바른 KKT diagnostics여야 합니다."
            )
        if self.diagnostics_before_reconciliation.weights != self.raw_float_weights:
            raise InvalidConstrainedErcDomainError(
                "reconciliation 전 진단 weights가 raw float weights와 일치하지 않습니다."
            )
        reconciled_float = tuple(float(value) for value in self.reconciled_weights)
        if self.diagnostics_after_reconciliation.weights != reconciled_float:
            raise InvalidConstrainedErcDomainError(
                "reconciliation 후 진단 weights가 Decimal 목표비중과 일치하지 않습니다."
            )
        _validate_fingerprint(self.covariance_fingerprint, "covariance")
        _validate_fingerprint(self.solver_config_fingerprint, "solver config")
        if not _positive_finite_float(self.lambda_value):
            raise InvalidConstrainedErcDomainError("ERC lambda는 양의 유한한 float여야 합니다.")
        for label, value in (
            ("reconciliation 최대 오차", self.reconciliation_max_error),
            ("reconciliation 전 합계 residual", self.weight_sum_residual_before),
        ):
            if not _nonnegative_finite_float(value):
                raise InvalidConstrainedErcDomainError(
                    f"{label}는 음수가 아닌 유한한 float여야 합니다."
                )
        expected_weight_sum_residual = abs(sum(self.raw_float_weights) - 1.0)
        if (
            self.weight_sum_residual_before != expected_weight_sum_residual
            or self.weight_sum_residual_before > 1e-12
        ):
            raise InvalidConstrainedErcDomainError(
                "reconciliation 전 합계 residual이 raw float weights와 일치해야 합니다."
            )
        expected_reconciliation_error = max(
            abs(float(reconciled) - raw)
            for reconciled, raw in zip(
                self.reconciled_weights,
                self.raw_float_weights,
                strict=True,
            )
        )
        if self.reconciliation_max_error != expected_reconciliation_error:
            raise InvalidConstrainedErcDomainError(
                "reconciliation 최대 오차가 raw/Decimal weights와 일치해야 합니다."
            )
        if self.weight_sum_residual_after != _ZERO:
            raise InvalidConstrainedErcDomainError(
                "reconciliation 후 Decimal 합계 residual은 정확히 0이어야 합니다."
            )
        for label, value, allow_zero in (
            ("CCD sweep 수", self.ccd_sweeps, False),
            ("bisection 반복 수", self.bisection_iterations, True),
            ("lambda bracket 확장 수", self.bracket_expansions, True),
        ):
            if type(value) is not int or value < (0 if allow_zero else 1):
                raise InvalidConstrainedErcDomainError(f"{label}가 올바르지 않습니다.")
        if type(self.all_assets_bound_degeneracy) is not bool:
            raise InvalidConstrainedErcDomainError("all-assets-bound 표시는 bool이어야 합니다.")
        expected_all_bound = all(
            flag is not ConstrainedErcBoundFlag.FREE
            for flag in self.diagnostics_after_reconciliation.bound_flags
        )
        if self.all_assets_bound_degeneracy != expected_all_bound:
            raise InvalidConstrainedErcDomainError(
                "all-assets-bound 표시가 최종 KKT bound 분류와 일치하지 않습니다."
            )
        if self.solver_version != CONSTRAINED_ERC_SOLVER_VERSION:
            raise InvalidConstrainedErcDomainError("ERC 목표의 solver 버전이 올바르지 않습니다.")

    @property
    def target_weights(self) -> tuple[Decimal, ...]:
        """Expose the exact downstream allocation weights."""

        return self.reconciled_weights

    @property
    def expected_portfolio_volatility(self) -> float:
        """Return post-reconciliation annualized portfolio volatility."""

        return self.diagnostics_after_reconciliation.portfolio_volatility


@dataclass(frozen=True, slots=True)
class ConstrainedErcFailure:
    """Allow-listed, secret-free failure information."""

    code: str
    message: str
    as_of_date: date | None = None
    scenario_kind: CovarianceScenarioKind | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.code, str)
            or _POLICY_ID_PATTERN.fullmatch(self.code) is None
            or len(self.code) > 64
        ):
            raise InvalidConstrainedErcDomainError("ERC 실패 코드는 안전한 snake_case여야 합니다.")
        if (
            not isinstance(self.message, str)
            or not self.message
            or self.message != self.message.strip()
            or len(self.message) > 500
        ):
            raise InvalidConstrainedErcDomainError("ERC 실패 메시지는 비어 있지 않아야 합니다.")
        if self.as_of_date is not None and type(self.as_of_date) is not date:
            raise InvalidConstrainedErcDomainError("ERC 실패 as-of는 date 또는 None이어야 합니다.")
        if self.scenario_kind is not None and not isinstance(
            self.scenario_kind, CovarianceScenarioKind
        ):
            raise InvalidConstrainedErcDomainError(
                "ERC 실패 scenario는 CovarianceScenarioKind 또는 None이어야 합니다."
            )


@dataclass(frozen=True, slots=True)
class ConstrainedErcCommonFailure:
    """One explicit trial-level failure before independent policy execution."""

    stage: ConstrainedErcCommonFailureStage
    failure: ConstrainedErcFailure

    def __post_init__(self) -> None:
        if not isinstance(self.stage, ConstrainedErcCommonFailureStage):
            raise InvalidConstrainedErcDomainError("공통 실패 단계가 올바르지 않습니다.")
        if not isinstance(self.failure, ConstrainedErcFailure):
            raise InvalidConstrainedErcDomainError("공통 실패 정보 타입이 올바르지 않습니다.")
        if self.failure.scenario_kind is not None:
            raise InvalidConstrainedErcDomainError(
                "공통 실패는 특정 covariance scenario에 귀속될 수 없습니다."
            )
        if self.stage is ConstrainedErcCommonFailureStage.INPUT_PREPARATION and (
            self.failure.code != "constrained_erc_input_error"
            or self.failure.as_of_date is not None
        ):
            raise InvalidConstrainedErcDomainError(
                "입력 준비 공통 실패는 전역 입력 오류 코드로만 기록해야 합니다."
            )


@dataclass(frozen=True, slots=True)
class ConstrainedErcRiskSnapshotOutcome:
    """One exact shared signal-date risk snapshot or a sanitized failure."""

    as_of_date: date
    status: ConstrainedErcOutcomeStatus
    snapshot: DynamicRiskModelSnapshot | None = None
    failure: ConstrainedErcFailure | None = None

    def __post_init__(self) -> None:
        if type(self.as_of_date) is not date:
            raise InvalidConstrainedErcDomainError("위험 snapshot outcome as-of는 date여야 합니다.")
        if not isinstance(self.status, ConstrainedErcOutcomeStatus):
            raise InvalidConstrainedErcDomainError(
                "위험 snapshot outcome 상태가 올바르지 않습니다."
            )
        if self.status is ConstrainedErcOutcomeStatus.SUCCEEDED:
            if not isinstance(self.snapshot, DynamicRiskModelSnapshot) or self.failure is not None:
                raise InvalidConstrainedErcDomainError(
                    "성공 위험 snapshot outcome에는 snapshot만 있어야 합니다."
                )
            if self.snapshot.as_of_date != self.as_of_date:
                raise InvalidConstrainedErcDomainError(
                    "위험 snapshot as-of가 shared signal date와 일치하지 않습니다."
                )
        elif self.snapshot is not None or not isinstance(self.failure, ConstrainedErcFailure):
            raise InvalidConstrainedErcDomainError(
                "실패 위험 snapshot outcome에는 정제된 실패 정보만 있어야 합니다."
            )


@dataclass(frozen=True, slots=True)
class ConstrainedErcPolicyOutcome:
    """One of four ERC or three control policy outcomes."""

    policy_id: str
    status: ConstrainedErcOutcomeStatus
    erc_targets: tuple[ConstrainedErcTarget, ...] = ()
    result: AllocationBacktestResult | None = None
    failure: ConstrainedErcFailure | None = None

    def __post_init__(self) -> None:
        _validate_policy_id(self.policy_id)
        if self.policy_id not in CONSTRAINED_ERC_POLICY_ORDER:
            raise InvalidConstrainedErcDomainError("지원하지 않는 Constrained ERC 연구 정책입니다.")
        _require_tuple(self.erc_targets, "ERC targets")
        if any(not isinstance(target, ConstrainedErcTarget) for target in self.erc_targets):
            raise InvalidConstrainedErcDomainError(
                "ERC targets는 ConstrainedErcTarget만 포함해야 합니다."
            )
        if any(target.policy_id != self.policy_id for target in self.erc_targets):
            raise InvalidConstrainedErcDomainError(
                "ERC target 정책 식별자가 policy outcome과 일치하지 않습니다."
            )
        if self.policy_id in CONSTRAINED_ERC_CONTROL_POLICY_IDS and self.erc_targets:
            raise InvalidConstrainedErcDomainError(
                "control policy outcome에는 ERC target이 없어야 합니다."
            )
        target_dates = tuple(target.as_of_date for target in self.erc_targets)
        if any(current <= previous for previous, current in pairwise(target_dates)):
            raise InvalidConstrainedErcDomainError(
                "ERC target as-of는 엄격한 오름차순이어야 합니다."
            )
        if not isinstance(self.status, ConstrainedErcOutcomeStatus):
            raise InvalidConstrainedErcDomainError("정책 outcome 상태가 올바르지 않습니다.")
        if self.status is ConstrainedErcOutcomeStatus.SUCCEEDED:
            if not isinstance(self.result, AllocationBacktestResult) or self.failure is not None:
                raise InvalidConstrainedErcDomainError(
                    "성공 정책 outcome에는 backtest 결과만 있어야 합니다."
                )
            if self.result.policy_id != self.policy_id:
                raise InvalidConstrainedErcDomainError(
                    "backtest 정책 식별자가 policy outcome과 일치하지 않습니다."
                )
            if self.policy_id in CONSTRAINED_ERC_SCENARIO_POLICY_IDS and not self.erc_targets:
                raise InvalidConstrainedErcDomainError(
                    "성공 ERC 정책에는 최소 1개의 target이 필요합니다."
                )
        elif self.result is not None or not isinstance(self.failure, ConstrainedErcFailure):
            raise InvalidConstrainedErcDomainError(
                "실패 정책 outcome에는 정제된 실패 정보만 있어야 합니다."
            )


@dataclass(frozen=True, slots=True)
class ConstrainedErcResearchTrial:
    """Auditable seven-policy constrained-ERC research record."""

    trial_id: str
    status: ConstrainedErcResearchStatus
    executed_at: datetime
    requested_start: date
    requested_end: date
    actual_evaluation_start: date | None
    actual_evaluation_end: date | None
    stock_codes: tuple[str, ...]
    price_panel: AlignedPricePanel | None
    aligned_returns: AlignedReturnMatrix | None
    allocation_config: AllocationBacktestConfig
    risk_model_config: DynamicRiskModelConfig
    solver_config: ConstrainedErcSolverConfig
    signal_dates: tuple[date, ...]
    execution_dates: tuple[date, ...]
    risk_snapshot_outcomes: tuple[ConstrainedErcRiskSnapshotOutcome, ...]
    policy_outcomes: tuple[ConstrainedErcPolicyOutcome, ...]
    config_fingerprint: str
    market_data_fingerprint: str
    covariance_fingerprint: str
    trial_fingerprint: str
    provenance: RiskModelLibraryProvenance
    common_failure: ConstrainedErcCommonFailure | None = None
    code_model_version: str = CONSTRAINED_ERC_CODE_MODEL_VERSION
    schema: str = CONSTRAINED_ERC_SCHEMA
    schema_version: str = CONSTRAINED_ERC_SCHEMA_VERSION
    research_scope: str = CONSTRAINED_ERC_RESEARCH_SCOPE

    def __post_init__(self) -> None:
        if not isinstance(self.trial_id, str) or _TRIAL_ID_PATTERN.fullmatch(self.trial_id) is None:
            raise InvalidConstrainedErcDomainError(
                "Constrained ERC trial ID는 경로 구분자 없는 안전한 문자열이어야 합니다."
            )
        if not isinstance(self.status, ConstrainedErcResearchStatus):
            raise InvalidConstrainedErcDomainError(
                "Constrained ERC trial 상태가 올바르지 않습니다."
            )
        if not isinstance(self.executed_at, datetime) or self.executed_at.tzinfo is None:
            raise InvalidConstrainedErcDomainError(
                "trial 실행시각은 timezone-aware datetime이어야 합니다."
            )
        if (
            type(self.requested_start) is not date
            or type(self.requested_end) is not date
            or self.requested_start > self.requested_end
        ):
            raise InvalidConstrainedErcDomainError("trial 요청기간이 올바르지 않습니다.")
        _validate_stock_codes(
            self.stock_codes,
            allow_empty=self.price_panel is None
            and self.status is ConstrainedErcResearchStatus.FAILED,
        )
        if not isinstance(self.allocation_config, AllocationBacktestConfig):
            raise InvalidConstrainedErcDomainError("allocation config 타입이 올바르지 않습니다.")
        if not isinstance(self.risk_model_config, DynamicRiskModelConfig):
            raise InvalidConstrainedErcDomainError("risk-model config 타입이 올바르지 않습니다.")
        if not isinstance(self.solver_config, ConstrainedErcSolverConfig):
            raise InvalidConstrainedErcDomainError("solver config 타입이 올바르지 않습니다.")
        if (
            self.allocation_config.minimum_training_returns
            != self.risk_model_config.minimum_observations
            or self.allocation_config.maximum_training_returns
            != self.risk_model_config.maximum_observations
            or self.allocation_config.rebalance_interval
            != self.risk_model_config.rebalance_interval
        ):
            raise InvalidConstrainedErcDomainError(
                "allocation과 risk-model의 504/756/5 일정 설정이 일치해야 합니다."
            )
        _require_tuple(self.signal_dates, "signal dates")
        _require_tuple(self.execution_dates, "execution dates")
        _validate_dates(self.signal_dates, "signal dates", allow_empty=self.price_panel is None)
        _validate_dates(
            self.execution_dates, "execution dates", allow_empty=self.price_panel is None
        )
        if len(self.signal_dates) != len(self.execution_dates) or any(
            execution <= signal
            for signal, execution in zip(self.signal_dates, self.execution_dates, strict=True)
        ):
            raise InvalidConstrainedErcDomainError(
                "signal date와 next-open execution date 일정이 일치하지 않습니다."
            )
        if (self.price_panel is None) != (self.aligned_returns is None):
            raise InvalidConstrainedErcDomainError(
                "가격 패널과 정렬 수익률은 함께 존재하거나 함께 없어야 합니다."
            )
        if self.price_panel is not None and not isinstance(self.price_panel, AlignedPricePanel):
            raise InvalidConstrainedErcDomainError("가격 패널 타입이 올바르지 않습니다.")
        if self.aligned_returns is not None and not isinstance(
            self.aligned_returns,
            AlignedReturnMatrix,
        ):
            raise InvalidConstrainedErcDomainError("정렬 수익률 타입이 올바르지 않습니다.")
        if self.price_panel is not None and self.aligned_returns is not None:
            if self.price_panel.stock_codes != self.stock_codes:
                raise InvalidConstrainedErcDomainError(
                    "가격 패널 종목 순서가 trial과 일치하지 않습니다."
                )
            if self.aligned_returns.stock_codes != self.stock_codes:
                raise InvalidConstrainedErcDomainError(
                    "수익률 행렬 종목 순서가 trial과 일치하지 않습니다."
                )
            if self.aligned_returns.dates != self.price_panel.dates[1:]:
                raise InvalidConstrainedErcDomainError(
                    "수익률 날짜가 공통 가격 패널의 close-to-close 구간과 일치하지 않습니다."
                )
            panel_positions = {value: index for index, value in enumerate(self.price_panel.dates)}
            try:
                expected_execution_dates = tuple(
                    self.price_panel.dates[panel_positions[signal] + 1]
                    for signal in self.signal_dates
                )
            except (KeyError, IndexError):
                raise InvalidConstrainedErcDomainError(
                    "signal date마다 다음 공통 거래일 시가 체결일이 있어야 합니다."
                ) from None
            if self.execution_dates != expected_execution_dates:
                raise InvalidConstrainedErcDomainError(
                    "execution dates는 각 signal date의 다음 공통 거래일이어야 합니다."
                )
        _require_tuple(self.risk_snapshot_outcomes, "risk snapshot outcomes")
        if any(
            not isinstance(outcome, ConstrainedErcRiskSnapshotOutcome)
            for outcome in self.risk_snapshot_outcomes
        ):
            raise InvalidConstrainedErcDomainError(
                "risk snapshot outcomes 타입이 올바르지 않습니다."
            )
        if (
            tuple(outcome.as_of_date for outcome in self.risk_snapshot_outcomes)
            != self.signal_dates
        ):
            raise InvalidConstrainedErcDomainError(
                "위험 snapshot outcome 일정이 shared signal date와 일치하지 않습니다."
            )
        for outcome in self.risk_snapshot_outcomes:
            if outcome.snapshot is not None and outcome.snapshot.stock_codes != self.stock_codes:
                raise InvalidConstrainedErcDomainError(
                    "위험 snapshot 종목 순서가 trial 등록 순서와 일치하지 않습니다."
                )
        _require_tuple(self.policy_outcomes, "policy outcomes")
        if any(
            not isinstance(outcome, ConstrainedErcPolicyOutcome) for outcome in self.policy_outcomes
        ):
            raise InvalidConstrainedErcDomainError("policy outcomes 타입이 올바르지 않습니다.")
        if (
            tuple(outcome.policy_id for outcome in self.policy_outcomes)
            != CONSTRAINED_ERC_POLICY_ORDER
        ):
            raise InvalidConstrainedErcDomainError(
                "정책 outcome은 고정된 7개 정책 순서여야 합니다."
            )
        for policy_outcome in self.policy_outcomes:
            if any(target.stock_codes != self.stock_codes for target in policy_outcome.erc_targets):
                raise InvalidConstrainedErcDomainError(
                    "ERC target 종목 순서가 trial 등록 순서와 일치하지 않습니다."
                )
            if policy_outcome.policy_id in CONSTRAINED_ERC_SCENARIO_POLICY_IDS:
                target_dates = tuple(target.as_of_date for target in policy_outcome.erc_targets)
                if target_dates != self.signal_dates[: len(target_dates)]:
                    raise InvalidConstrainedErcDomainError(
                        "ERC target 일정은 shared signal 일정의 정확한 prefix여야 합니다."
                    )
                if (
                    policy_outcome.status is ConstrainedErcOutcomeStatus.SUCCEEDED
                    and target_dates != self.signal_dates
                ):
                    raise InvalidConstrainedErcDomainError(
                        "성공 ERC 정책은 모든 shared signal date의 target이 필요합니다."
                    )
            if policy_outcome.result is not None:
                if policy_outcome.result.stock_codes != self.stock_codes:
                    raise InvalidConstrainedErcDomainError(
                        "정책 결과 종목 순서가 trial 등록 순서와 일치하지 않습니다."
                    )
                expected_rebalance_dates = (
                    self.execution_dates[:1]
                    if policy_outcome.policy_id == "equal_weight_buy_and_hold"
                    else self.execution_dates
                )
                actual_rebalance_dates = tuple(
                    record.execution_date for record in policy_outcome.result.rebalances
                )
                if actual_rebalance_dates != expected_rebalance_dates:
                    raise InvalidConstrainedErcDomainError(
                        "정책 체결일이 shared next-open 일정과 일치하지 않습니다."
                    )
                if self.price_panel is not None:
                    first_execution_index = self.price_panel.dates.index(
                        expected_rebalance_dates[0]
                    )
                    if (
                        policy_outcome.result.dates
                        != self.price_panel.dates[first_execution_index:]
                    ):
                        raise InvalidConstrainedErcDomainError(
                            "정책 평가일이 shared 가격 패널의 공통 평가기간과 일치하지 않습니다."
                        )
        succeeded = all(
            outcome.status is ConstrainedErcOutcomeStatus.SUCCEEDED
            for outcome in self.policy_outcomes
        )
        if (self.status is ConstrainedErcResearchStatus.SUCCEEDED) != succeeded:
            raise InvalidConstrainedErcDomainError(
                "전체 trial 상태가 7개 정책 outcome 상태와 일치하지 않습니다."
            )
        if self.common_failure is not None:
            if not isinstance(self.common_failure, ConstrainedErcCommonFailure):
                raise InvalidConstrainedErcDomainError("trial 공통 실패 타입이 올바르지 않습니다.")
            if self.status is not ConstrainedErcResearchStatus.FAILED:
                raise InvalidConstrainedErcDomainError(
                    "공통 실패가 있는 trial은 failed 상태여야 합니다."
                )
            if any(
                outcome.status is not ConstrainedErcOutcomeStatus.FAILED
                or outcome.result is not None
                or outcome.erc_targets
                for outcome in self.policy_outcomes
            ):
                raise InvalidConstrainedErcDomainError(
                    "공통 실패 trial의 모든 정책은 target/result 없이 미실행 실패여야 합니다."
                )
            if any(
                outcome.failure is None
                or outcome.failure.code != "constrained_erc_not_run_common_failure"
                or outcome.failure.as_of_date is not None
                or outcome.failure.scenario_kind is not None
                for outcome in self.policy_outcomes
            ):
                raise InvalidConstrainedErcDomainError(
                    "공통 실패 trial의 정책 실패는 전역 미실행 코드로만 기록해야 합니다."
                )
            if self.common_failure.stage is ConstrainedErcCommonFailureStage.INPUT_PREPARATION and (
                self.price_panel is not None
                or self.aligned_returns is not None
                or self.signal_dates
                or self.execution_dates
                or self.risk_snapshot_outcomes
            ):
                raise InvalidConstrainedErcDomainError(
                    "입력 준비 공통 실패 trial에는 공통 분석 산출물이 없어야 합니다."
                )
        elif self.price_panel is None:
            raise InvalidConstrainedErcDomainError(
                "공통 가격 패널이 없는 failed trial에는 공통 실패 정보가 필요합니다."
            )
        successful_results = tuple(
            outcome.result for outcome in self.policy_outcomes if outcome.result is not None
        )
        if successful_results:
            expected_dates = successful_results[0].dates
            if any(result.dates != expected_dates for result in successful_results[1:]):
                raise InvalidConstrainedErcDomainError(
                    "성공 정책의 실제 평가기간은 모두 정확히 일치해야 합니다."
                )
            if (
                self.actual_evaluation_start != expected_dates[0]
                or self.actual_evaluation_end != expected_dates[-1]
            ):
                raise InvalidConstrainedErcDomainError(
                    "trial 실제 평가기간이 성공 정책의 공통 평가기간과 일치하지 않습니다."
                )
        elif self.actual_evaluation_start is not None or self.actual_evaluation_end is not None:
            raise InvalidConstrainedErcDomainError(
                "성공 정책이 없으면 trial 실제 평가기간은 None이어야 합니다."
            )
        for label, value in (
            ("config", self.config_fingerprint),
            ("market data", self.market_data_fingerprint),
            ("covariance", self.covariance_fingerprint),
            ("trial", self.trial_fingerprint),
        ):
            _validate_fingerprint(value, label)
        if not isinstance(self.provenance, RiskModelLibraryProvenance):
            raise InvalidConstrainedErcDomainError("trial library provenance가 올바르지 않습니다.")
        if self.code_model_version != CONSTRAINED_ERC_CODE_MODEL_VERSION:
            raise InvalidConstrainedErcDomainError(
                "Constrained ERC code model 버전이 올바르지 않습니다."
            )
        if (
            self.schema != CONSTRAINED_ERC_SCHEMA
            or self.schema_version != CONSTRAINED_ERC_SCHEMA_VERSION
        ):
            raise InvalidConstrainedErcDomainError(
                "Constrained ERC trial schema가 올바르지 않습니다."
            )
        if self.research_scope != CONSTRAINED_ERC_RESEARCH_SCOPE:
            raise InvalidConstrainedErcDomainError(
                "Constrained ERC 연구 범위 표시가 올바르지 않습니다."
            )


def scenario_policy_id(kind: CovarianceScenarioKind) -> str:
    """Map a fixed covariance scenario to its independently tested ERC policy."""

    if not isinstance(kind, CovarianceScenarioKind):
        raise InvalidConstrainedErcDomainError("covariance scenario 종류가 올바르지 않습니다.")
    return CONSTRAINED_ERC_SCENARIO_POLICY_IDS[SCENARIO_KIND_ORDER.index(kind)]


def _validate_stock_codes(stock_codes: tuple[str, ...], *, allow_empty: bool = False) -> None:
    _require_tuple(stock_codes, "stock codes")
    if not stock_codes:
        if allow_empty:
            return
        raise InvalidConstrainedErcDomainError("Constrained ERC 종목코드는 비어 있을 수 없습니다.")
    if any(
        not isinstance(value, str) or _STOCK_CODE_PATTERN.fullmatch(value) is None
        for value in stock_codes
    ):
        raise InvalidConstrainedErcDomainError("종목코드는 공백 없는 6자리 숫자여야 합니다.")
    if len(set(stock_codes)) != len(stock_codes):
        raise InvalidConstrainedErcDomainError("Constrained ERC 종목코드에 중복이 있습니다.")


def _validate_policy_id(value: object) -> None:
    if not isinstance(value, str) or _POLICY_ID_PATTERN.fullmatch(value) is None:
        raise InvalidConstrainedErcDomainError("정책 식별자는 안전한 snake_case여야 합니다.")


def _validate_dates(values: tuple[date, ...], label: str, *, allow_empty: bool) -> None:
    if not values:
        if allow_empty:
            return
        raise InvalidConstrainedErcDomainError(f"{label}는 비어 있을 수 없습니다.")
    if any(type(value) is not date for value in values) or any(
        current <= previous for previous, current in pairwise(values)
    ):
        raise InvalidConstrainedErcDomainError(f"{label}는 중복 없는 엄격한 오름차순이어야 합니다.")


def _validate_fingerprint(value: object, label: str) -> None:
    if not isinstance(value, str) or _FINGERPRINT_PATTERN.fullmatch(value) is None:
        raise InvalidConstrainedErcDomainError(
            f"{label} fingerprint는 64자리 소문자 SHA-256이어야 합니다."
        )


def _require_tuple(value: object, label: str) -> None:
    if not isinstance(value, tuple):
        raise InvalidConstrainedErcDomainError(f"{label}는 tuple이어야 합니다.")


def _finite_decimal(value: object) -> bool:
    return isinstance(value, Decimal) and value.is_finite()


def _decimal_sum(values: tuple[Decimal, ...]) -> Decimal:
    with localcontext(Context(prec=100)):
        return sum(values, _ZERO)


def _finite_float(value: object) -> TypeGuard[float]:
    return type(value) is float and math.isfinite(value)


def _positive_finite_float(value: object) -> bool:
    return _finite_float(value) and value > 0


def _nonnegative_finite_float(value: object) -> bool:
    return _finite_float(value) and value >= 0


__all__ = [
    "CONSTRAINED_ERC_CODE_MODEL_VERSION",
    "CONSTRAINED_ERC_CONTROL_POLICY_IDS",
    "CONSTRAINED_ERC_POLICY_ORDER",
    "CONSTRAINED_ERC_RESEARCH_SCOPE",
    "CONSTRAINED_ERC_SCENARIO_POLICY_IDS",
    "CONSTRAINED_ERC_SCHEMA",
    "CONSTRAINED_ERC_SCHEMA_VERSION",
    "CONSTRAINED_ERC_SOLVER_VERSION",
    "ConstrainedErcBoundFlag",
    "ConstrainedErcCommonFailure",
    "ConstrainedErcCommonFailureStage",
    "ConstrainedErcFailure",
    "ConstrainedErcKktDiagnostics",
    "ConstrainedErcOutcomeStatus",
    "ConstrainedErcPolicyOutcome",
    "ConstrainedErcResearchStatus",
    "ConstrainedErcResearchTrial",
    "ConstrainedErcRiskSnapshotOutcome",
    "ConstrainedErcSolverConfig",
    "ConstrainedErcTarget",
    "scenario_policy_id",
]
