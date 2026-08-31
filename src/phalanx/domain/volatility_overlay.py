"""Strict immutable contracts for a volatility-target cash overlay."""

from __future__ import annotations

import re
from datetime import date
from decimal import ROUND_HALF_EVEN, Context, Decimal, DecimalException, localcontext
from typing import Annotated, Any, Literal, Self, cast

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    PlainSerializer,
    ValidationInfo,
    model_validator,
)

from phalanx.domain.constrained_erc import CONSTRAINED_ERC_SCENARIO_POLICY_IDS
from phalanx.domain.risk_model import SCENARIO_KIND_ORDER, CovarianceScenarioKind
from phalanx.portfolio.errors import InvalidVolatilityOverlayDomainError

VOLATILITY_OVERLAY_SCHEMA: Literal["phalanx.volatility_overlay_research_trial.v1"] = (
    "phalanx.volatility_overlay_research_trial.v1"
)
VOLATILITY_OVERLAY_SCHEMA_VERSION: Literal["1"] = "1"
VOLATILITY_OVERLAY_CODE_MODEL_VERSION: Literal["volatility-overlay-research-v1"] = (
    "volatility-overlay-research-v1"
)
VOLATILITY_OVERLAY_RESEARCH_SCOPE = "current-universe conditional allocation-only research overlay"
# Kept as a narrow compatibility name for callers that describe the code model as a model.
VOLATILITY_OVERLAY_MODEL_VERSION = VOLATILITY_OVERLAY_CODE_MODEL_VERSION
VOLATILITY_OVERLAY_SCENARIO_IDS = tuple(kind.value for kind in SCENARIO_KIND_ORDER)
VOLATILITY_OVERLAY_SCENARIO_POLICY_IDS = (
    "volatility_overlay_long_run_ledoit_wolf",
    "volatility_overlay_fast_iewma",
    "volatility_overlay_slow_iewma",
    "volatility_overlay_downside_stress_ledoit_wolf",
)
VOLATILITY_OVERLAY_POLICY_ORDER = VOLATILITY_OVERLAY_SCENARIO_POLICY_IDS

_DECIMAL_PRECISION = 50
_MAX_INPUT_FRACTIONAL_PLACES = 12
_ZERO = Decimal(0)
_ONE = Decimal(1)
_PRODUCTION_ERC_CAP = Decimal("0.20")
_STOCK_CODE_PATTERN = re.compile(r"^[0-9]{6}$")
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _require_decimal_input(value: Any, info: ValidationInfo) -> Decimal:
    if info.mode == "json" and isinstance(value, str):
        try:
            value = Decimal(value)
        except DecimalException:
            raise InvalidVolatilityOverlayDomainError(
                "volatility overlay JSON 수치는 Decimal 문자열이어야 합니다."
            ) from None
    if type(value) is not Decimal:
        raise InvalidVolatilityOverlayDomainError(
            "volatility overlay 수치 입력은 float 변환 없는 Decimal이어야 합니다."
        )
    if not value.is_finite():
        raise InvalidVolatilityOverlayDomainError(
            "volatility overlay 수치 입력은 유한한 Decimal이어야 합니다."
        )
    return value


def _require_finite_decimal(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise InvalidVolatilityOverlayDomainError(
            "volatility overlay 수치 입력은 유한한 Decimal이어야 합니다."
        )
    return value


def _serialize_decimal(value: Decimal) -> str:
    return format(value, "f")


def canonicalize_target_annual_volatility(value: Decimal) -> Decimal:
    """Validate and canonicalize the preregistered annual volatility target."""

    return _canonicalize_bounded_overlay_input(
        value,
        label="목표 연환산 변동성",
        allow_zero=False,
    )


def canonicalize_annual_cash_yield(value: Decimal) -> Decimal:
    """Validate and canonicalize the independently modelled annual cash yield."""

    return _canonicalize_bounded_overlay_input(
        value,
        label="연간 현금수익률",
        allow_zero=True,
    )


def _canonicalize_bounded_overlay_input(
    value: object,
    *,
    label: str,
    allow_zero: bool,
) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise InvalidVolatilityOverlayDomainError(
            f"{label}은 유한한 Decimal이어야 합니다."
        )
    if value.is_zero():
        if not allow_zero:
            raise InvalidVolatilityOverlayDomainError(
                f"{label}은 0보다 크고 1 이하여야 합니다."
            )
        return Decimal("0")

    sign, digits, exponent = value.as_tuple()
    canonical_digits = list(digits)
    canonical_exponent = cast(int, exponent)
    while canonical_digits[-1] == 0:
        canonical_digits.pop()
        canonical_exponent += 1
    if canonical_exponent < -_MAX_INPUT_FRACTIONAL_PLACES:
        raise InvalidVolatilityOverlayDomainError(
            f"{label}은 trailing zero 제거 후 소수점 이하 최대 "
            f"{_MAX_INPUT_FRACTIONAL_PLACES}자리여야 합니다."
        )
    canonical = Decimal((sign, tuple(canonical_digits), canonical_exponent))
    lower_bound_satisfied = canonical >= _ZERO if allow_zero else canonical > _ZERO
    if not lower_bound_satisfied or canonical > _ONE:
        range_description = "0 이상 1 이하" if allow_zero else "0보다 크고 1 이하"
        raise InvalidVolatilityOverlayDomainError(
            f"{label}은 {range_description}여야 합니다."
        )
    if canonical.as_tuple() == value.as_tuple():
        return value
    return canonical


OverlayDecimal = Annotated[
    Decimal,
    BeforeValidator(_require_decimal_input),
    AfterValidator(_require_finite_decimal),
    PlainSerializer(_serialize_decimal, return_type=str, when_used="json"),
]

TargetAnnualVolatilityDecimal = Annotated[
    Decimal,
    BeforeValidator(_require_decimal_input),
    AfterValidator(canonicalize_target_annual_volatility),
    PlainSerializer(_serialize_decimal, return_type=str, when_used="json"),
]

AnnualCashYieldDecimal = Annotated[
    Decimal,
    BeforeValidator(_require_decimal_input),
    AfterValidator(canonicalize_annual_cash_yield),
    PlainSerializer(_serialize_decimal, return_type=str, when_used="json"),
]


class _FrozenOverlayModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class VolatilityOverlayConfig(_FrozenOverlayModel):
    """Predeclared target volatility and independently modelled cash yield."""

    target_annual_volatility: TargetAnnualVolatilityDecimal
    annual_cash_yield: AnnualCashYieldDecimal = Decimal("0")
    code_model_version: Literal["volatility-overlay-research-v1"] = (
        VOLATILITY_OVERLAY_CODE_MODEL_VERSION
    )

    @model_validator(mode="after")
    def _validate_config(self) -> Self:
        canonicalize_target_annual_volatility(self.target_annual_volatility)
        canonicalize_annual_cash_yield(self.annual_cash_yield)
        return self

    @property
    def model_version(self) -> str:
        """Expose the code-model version under the research-registry vocabulary."""

        return self.code_model_version


class VolatilityOverlayTarget(_FrozenOverlayModel):
    """One exact Decimal target after scaling a fully invested ERC risky sleeve."""

    scenario_kind: CovarianceScenarioKind
    source_policy_id: str
    policy_id: str
    as_of_date: date
    stock_codes: tuple[str, ...]
    source_covariance_fingerprint: str
    source_solver_config_fingerprint: str
    forecast_annual_volatility: OverlayDecimal
    target_annual_volatility: TargetAnnualVolatilityDecimal
    scalar: OverlayDecimal
    risky_sleeve_weights: tuple[OverlayDecimal, ...]
    target_weights: tuple[OverlayDecimal, ...]
    target_equity_weight: OverlayDecimal
    cash_residual: OverlayDecimal
    annual_cash_yield: AnnualCashYieldDecimal
    code_model_version: Literal["volatility-overlay-research-v1"] = (
        VOLATILITY_OVERLAY_CODE_MODEL_VERSION
    )
    schema_version: Literal["1"] = VOLATILITY_OVERLAY_SCHEMA_VERSION

    @model_validator(mode="after")
    def _validate_target(self) -> Self:
        expected_source_policy = _source_policy_id(self.scenario_kind)
        expected_policy = overlay_policy_id(self.scenario_kind)
        if self.source_policy_id != expected_source_policy:
            raise InvalidVolatilityOverlayDomainError(
                "source policy ID가 covariance scenario와 일치하지 않습니다."
            )
        if self.policy_id != expected_policy:
            raise InvalidVolatilityOverlayDomainError(
                "volatility overlay policy ID가 covariance scenario와 일치하지 않습니다."
            )
        if type(self.as_of_date) is not date:
            raise InvalidVolatilityOverlayDomainError("overlay as-of는 date 값이어야 합니다.")
        _validate_stock_codes(self.stock_codes)
        _validate_fingerprint(self.source_covariance_fingerprint, "source covariance")
        _validate_fingerprint(self.source_solver_config_fingerprint, "source solver config")

        size = len(self.stock_codes)
        if len(self.risky_sleeve_weights) != size or len(self.target_weights) != size:
            raise InvalidVolatilityOverlayDomainError(
                "overlay risky sleeve와 최종 목표비중 차원은 종목 수와 일치해야 합니다."
            )
        if any(value < _ZERO or value > _PRODUCTION_ERC_CAP for value in self.risky_sleeve_weights):
            raise InvalidVolatilityOverlayDomainError(
                "ERC risky sleeve 비중은 음수가 아니고 기존 20% cap 이하여야 합니다."
            )
        if _exact_sum(self.risky_sleeve_weights) != _ONE:
            raise InvalidVolatilityOverlayDomainError(
                "ERC risky sleeve 목표비중 합계는 정확히 1이어야 합니다."
            )
        if self.forecast_annual_volatility <= _ZERO:
            raise InvalidVolatilityOverlayDomainError(
                "예측 연환산 변동성은 양의 유한한 Decimal이어야 합니다."
            )
        canonicalize_target_annual_volatility(self.target_annual_volatility)
        expected_scalar = calculate_volatility_scalar(
            self.target_annual_volatility,
            self.forecast_annual_volatility,
        )
        if self.scalar != expected_scalar or not (_ZERO < self.scalar <= _ONE):
            raise InvalidVolatilityOverlayDomainError(
                "overlay scalar는 min(1, target/forecast)와 정확히 일치해야 합니다."
            )
        expected_weights = scale_risky_sleeve(self.risky_sleeve_weights, self.scalar)
        if self.target_weights != expected_weights:
            raise InvalidVolatilityOverlayDomainError(
                "최종 목표비중은 공통 scalar를 곱해 ERC 상대비중을 보존해야 합니다."
            )
        if any(
            value < _ZERO or value > source or value > _PRODUCTION_ERC_CAP
            for value, source in zip(
                self.target_weights,
                self.risky_sleeve_weights,
                strict=True,
            )
        ):
            raise InvalidVolatilityOverlayDomainError(
                "최종 목표비중은 long-only, no-leverage 및 기존 20% cap을 지켜야 합니다."
            )
        if self.target_equity_weight != self.scalar:
            raise InvalidVolatilityOverlayDomainError(
                "최종 목표 주식비중은 volatility scalar와 정확히 같아야 합니다."
            )
        target_sum = _exact_sum(self.target_weights)
        if target_sum != self.target_equity_weight:
            raise InvalidVolatilityOverlayDomainError(
                "최종 종목 목표비중 합계는 목표 주식비중과 정확히 같아야 합니다."
            )
        expected_cash = calculate_cash_residual(self.target_weights)
        if self.cash_residual != expected_cash or self.cash_residual < _ZERO:
            raise InvalidVolatilityOverlayDomainError(
                "현금 residual은 1에서 최종 종목비중 합계를 뺀 비음수 값이어야 합니다."
            )
        if _exact_sum((*self.target_weights, self.cash_residual)) != _ONE:
            raise InvalidVolatilityOverlayDomainError(
                "최종 종목비중과 현금 residual 합계는 정확히 1이어야 합니다."
            )
        canonicalize_annual_cash_yield(self.annual_cash_yield)
        return self

    @property
    def volatility_scalar(self) -> Decimal:
        """Expose the named volatility scalar without duplicating serialized state."""

        return self.scalar

    @property
    def model_version(self) -> str:
        """Expose the code-model version under the research-registry vocabulary."""

        return self.code_model_version


def overlay_policy_id(kind: CovarianceScenarioKind) -> str:
    """Map one fixed covariance scenario to its volatility-overlay policy ID."""

    if not isinstance(kind, CovarianceScenarioKind):
        raise InvalidVolatilityOverlayDomainError(
            "volatility overlay scenario 종류가 올바르지 않습니다."
        )
    try:
        index = SCENARIO_KIND_ORDER.index(kind)
    except ValueError:
        raise InvalidVolatilityOverlayDomainError(
            "지원하지 않는 volatility overlay scenario입니다."
        ) from None
    return VOLATILITY_OVERLAY_SCENARIO_POLICY_IDS[index]


def volatility_overlay_policy_id(kind: CovarianceScenarioKind) -> str:
    """Compatibility alias for :func:`overlay_policy_id`."""

    return overlay_policy_id(kind)


def calculate_volatility_scalar(
    target_annual_volatility: Decimal,
    forecast_annual_volatility: Decimal,
) -> Decimal:
    """Return ``min(1, target / forecast)`` from strict finite Decimal inputs."""

    target = canonicalize_target_annual_volatility(target_annual_volatility)
    forecast = _validated_positive_decimal(forecast_annual_volatility, "예측 연환산 변동성")
    if target >= forecast:
        return _ONE
    try:
        with localcontext(Context(prec=_DECIMAL_PRECISION, rounding=ROUND_HALF_EVEN)):
            scalar = target / forecast
    except DecimalException:
        raise InvalidVolatilityOverlayDomainError(
            "target/forecast volatility scalar를 안전하게 계산하지 못했습니다."
        ) from None
    if not scalar.is_finite() or not (_ZERO < scalar <= _ONE):
        raise InvalidVolatilityOverlayDomainError(
            "target/forecast volatility scalar는 0보다 크고 1 이하여야 합니다."
        )
    return scalar


def scale_risky_sleeve(
    risky_sleeve_weights: tuple[Decimal, ...],
    scalar: Decimal,
) -> tuple[Decimal, ...]:
    """Multiply every exact risky-sleeve weight by one common Decimal scalar."""

    if not isinstance(risky_sleeve_weights, tuple) or not risky_sleeve_weights:
        raise InvalidVolatilityOverlayDomainError(
            "ERC risky sleeve는 비어 있지 않은 Decimal tuple이어야 합니다."
        )
    for value in risky_sleeve_weights:
        _validated_finite_decimal(value, "ERC risky sleeve 비중")
        if value < _ZERO or value > _PRODUCTION_ERC_CAP:
            raise InvalidVolatilityOverlayDomainError(
                "ERC risky sleeve 비중은 음수가 아니고 기존 20% cap 이하여야 합니다."
            )
    if _exact_sum(risky_sleeve_weights) != _ONE:
        raise InvalidVolatilityOverlayDomainError(
            "ERC risky sleeve 목표비중 합계는 정확히 1이어야 합니다."
        )
    selected_scalar = _validated_finite_decimal(scalar, "volatility scalar")
    if not (_ZERO < selected_scalar <= _ONE):
        raise InvalidVolatilityOverlayDomainError(
            "volatility scalar는 0보다 크고 1 이하여야 합니다."
        )
    precision = max(
        _DECIMAL_PRECISION,
        len(selected_scalar.as_tuple().digits)
        + max(len(value.as_tuple().digits) for value in risky_sleeve_weights)
        + 4,
    )
    with localcontext(Context(prec=precision, rounding=ROUND_HALF_EVEN)):
        result = tuple(value * selected_scalar for value in risky_sleeve_weights)
    if _exact_sum(result) != selected_scalar:
        raise InvalidVolatilityOverlayDomainError(
            "공통 scalar 적용 뒤 최종 종목비중 합계를 정확히 대사하지 못했습니다."
        )
    return result


def calculate_cash_residual(target_weights: tuple[Decimal, ...]) -> Decimal:
    """Return exact nonnegative cash as one minus the exact risky-weight sum."""

    if not isinstance(target_weights, tuple) or not target_weights:
        raise InvalidVolatilityOverlayDomainError(
            "최종 종목 목표비중은 비어 있지 않은 Decimal tuple이어야 합니다."
        )
    for value in target_weights:
        _validated_finite_decimal(value, "최종 종목 목표비중")
        if value < _ZERO:
            raise InvalidVolatilityOverlayDomainError(
                "최종 종목 목표비중은 음수가 아니어야 합니다."
            )
    target_sum = _exact_sum(target_weights)
    if target_sum > _ONE:
        raise InvalidVolatilityOverlayDomainError(
            "최종 종목 목표비중 합계는 leverage 없이 1 이하여야 합니다."
        )
    precision = max(
        _DECIMAL_PRECISION,
        len(target_sum.as_tuple().digits) + abs(_decimal_exponent(target_sum)) + 4,
    )
    with localcontext(Context(prec=precision, rounding=ROUND_HALF_EVEN)):
        residual = _ONE - target_sum
    if residual < _ZERO or _exact_sum((*target_weights, residual)) != _ONE:
        raise InvalidVolatilityOverlayDomainError(
            "최종 종목비중과 현금 residual을 정확히 1로 대사하지 못했습니다."
        )
    return residual


def _source_policy_id(kind: CovarianceScenarioKind) -> str:
    if not isinstance(kind, CovarianceScenarioKind):
        raise InvalidVolatilityOverlayDomainError("source covariance scenario가 올바르지 않습니다.")
    try:
        index = SCENARIO_KIND_ORDER.index(kind)
    except ValueError:
        raise InvalidVolatilityOverlayDomainError(
            "지원하지 않는 source covariance scenario입니다."
        ) from None
    return CONSTRAINED_ERC_SCENARIO_POLICY_IDS[index]


def _validated_positive_decimal(value: object, label: str) -> Decimal:
    result = _validated_finite_decimal(value, label)
    if result <= _ZERO:
        raise InvalidVolatilityOverlayDomainError(f"{label}은 양의 유한한 Decimal이어야 합니다.")
    return result


def _validated_finite_decimal(value: object, label: str) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise InvalidVolatilityOverlayDomainError(f"{label}은 유한한 Decimal이어야 합니다.")
    return value


def _exact_sum(values: tuple[Decimal, ...]) -> Decimal:
    if not values:
        return _ZERO
    nonzero_values = tuple(value for value in values if value != _ZERO)
    if not nonzero_values:
        return _ZERO
    minimum_exponent = min(_decimal_exponent(value) for value in values)
    maximum_adjusted = max(value.adjusted() for value in nonzero_values)
    precision = max(
        _DECIMAL_PRECISION,
        maximum_adjusted - minimum_exponent + len(str(len(values))) + 4,
    )
    with localcontext(Context(prec=precision, rounding=ROUND_HALF_EVEN)):
        return sum(values, _ZERO)


def _validate_stock_codes(stock_codes: tuple[str, ...]) -> None:
    if (
        not isinstance(stock_codes, tuple)
        or not stock_codes
        or len(set(stock_codes)) != len(stock_codes)
        or any(
            not isinstance(value, str) or _STOCK_CODE_PATTERN.fullmatch(value) is None
            for value in stock_codes
        )
    ):
        raise InvalidVolatilityOverlayDomainError(
            "overlay 종목 순서는 중복 없는 6자리 종목코드 tuple이어야 합니다."
        )


def _decimal_exponent(value: Decimal) -> int:
    """Return the integral exponent guaranteed by the finite-Decimal boundary."""

    return cast(int, value.as_tuple().exponent)


def _validate_fingerprint(value: object, label: str) -> None:
    if not isinstance(value, str) or _FINGERPRINT_PATTERN.fullmatch(value) is None:
        raise InvalidVolatilityOverlayDomainError(f"{label} fingerprint가 올바르지 않습니다.")


__all__ = [
    "VOLATILITY_OVERLAY_CODE_MODEL_VERSION",
    "VOLATILITY_OVERLAY_MODEL_VERSION",
    "VOLATILITY_OVERLAY_POLICY_ORDER",
    "VOLATILITY_OVERLAY_RESEARCH_SCOPE",
    "VOLATILITY_OVERLAY_SCENARIO_IDS",
    "VOLATILITY_OVERLAY_SCENARIO_POLICY_IDS",
    "VOLATILITY_OVERLAY_SCHEMA",
    "VOLATILITY_OVERLAY_SCHEMA_VERSION",
    "OverlayDecimal",
    "VolatilityOverlayConfig",
    "VolatilityOverlayTarget",
    "calculate_cash_residual",
    "calculate_volatility_scalar",
    "canonicalize_annual_cash_yield",
    "canonicalize_target_annual_volatility",
    "overlay_policy_id",
    "scale_risky_sleeve",
    "volatility_overlay_policy_id",
]
