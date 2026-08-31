"""Pure Decimal volatility-target scaling for constrained-ERC risky sleeves."""

from __future__ import annotations

import math
from decimal import Decimal

from phalanx.domain.constrained_erc import ConstrainedErcTarget
from phalanx.domain.volatility_overlay import (
    VolatilityOverlayConfig,
    VolatilityOverlayTarget,
    calculate_cash_residual,
    calculate_volatility_scalar,
    overlay_policy_id,
    scale_risky_sleeve,
)
from phalanx.portfolio.errors import InvalidVolatilityOverlayDomainError

_ZERO = Decimal(0)
_ONE = Decimal(1)
_PRODUCTION_ERC_CAP = Decimal("0.20")


def apply_volatility_overlay(
    risky_sleeve: ConstrainedErcTarget,
    config: VolatilityOverlayConfig,
) -> VolatilityOverlayTarget:
    """Adapt one solver float forecast once, then delegate to the Decimal-only API."""

    _validate_source_target(risky_sleeve)
    forecast = risky_sleeve.expected_portfolio_volatility
    if type(forecast) is not float or not math.isfinite(forecast) or forecast <= 0:
        raise InvalidVolatilityOverlayDomainError(
            "ERC 예측 연환산 변동성은 양의 유한한 float이어야 합니다."
        )
    forecast_decimal = Decimal(str(forecast))
    return calculate_volatility_overlay(risky_sleeve, forecast_decimal, config)


def calculate_volatility_overlay(
    risky_sleeve: ConstrainedErcTarget,
    forecast_annual_volatility: Decimal,
    config: VolatilityOverlayConfig,
) -> VolatilityOverlayTarget:
    """Create an exact target; the public numerical inputs here are Decimal-only."""

    _validate_source_target(risky_sleeve)
    if not isinstance(config, VolatilityOverlayConfig):
        raise InvalidVolatilityOverlayDomainError(
            "volatility overlay config 타입이 올바르지 않습니다."
        )
    scalar = calculate_volatility_scalar(
        config.target_annual_volatility,
        forecast_annual_volatility,
    )
    risky_weights = risky_sleeve.reconciled_weights
    target_weights = scale_risky_sleeve(risky_weights, scalar)
    # scale_risky_sleeve proves that the exact target-weight sum is the scalar.
    target_equity_weight = scalar
    cash_residual = calculate_cash_residual(target_weights)
    return VolatilityOverlayTarget(
        scenario_kind=risky_sleeve.scenario_kind,
        source_policy_id=risky_sleeve.policy_id,
        policy_id=overlay_policy_id(risky_sleeve.scenario_kind),
        as_of_date=risky_sleeve.as_of_date,
        stock_codes=risky_sleeve.stock_codes,
        source_covariance_fingerprint=risky_sleeve.covariance_fingerprint,
        source_solver_config_fingerprint=risky_sleeve.solver_config_fingerprint,
        forecast_annual_volatility=forecast_annual_volatility,
        target_annual_volatility=config.target_annual_volatility,
        scalar=scalar,
        risky_sleeve_weights=risky_weights,
        target_weights=target_weights,
        target_equity_weight=target_equity_weight,
        cash_residual=cash_residual,
        annual_cash_yield=config.annual_cash_yield,
    )


def _validate_source_target(target: object) -> None:
    if not isinstance(target, ConstrainedErcTarget):
        raise InvalidVolatilityOverlayDomainError(
            "volatility overlay source는 ConstrainedErcTarget이어야 합니다."
        )
    if (
        not isinstance(target.upper_bounds, tuple)
        or len(target.upper_bounds) != len(target.stock_codes)
        or any(type(value) is not Decimal for value in target.upper_bounds)
        or any(value != _PRODUCTION_ERC_CAP for value in target.upper_bounds)
    ):
        raise InvalidVolatilityOverlayDomainError(
            "volatility overlay source는 기존 종목별 20% ERC cap 계약을 사용해야 합니다."
        )
    if not isinstance(target.reconciled_weights, tuple):
        raise InvalidVolatilityOverlayDomainError(
            "ERC risky sleeve 목표비중은 Decimal tuple이어야 합니다."
        )
    # This validates Decimal type, finiteness, nonnegativity, cap, and exact sum one.
    scale_risky_sleeve(target.reconciled_weights, _ONE)
    if target.policy_id.startswith("volatility_overlay_"):
        raise InvalidVolatilityOverlayDomainError(
            "이미 overlay가 적용된 target을 risky sleeve로 다시 사용할 수 없습니다."
        )
    if any(weight < _ZERO for weight in target.reconciled_weights):
        raise InvalidVolatilityOverlayDomainError(
            "ERC risky sleeve는 short 비중을 포함할 수 없습니다."
        )


__all__ = ["apply_volatility_overlay", "calculate_volatility_overlay"]
