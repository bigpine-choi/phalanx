"""Provider-neutral allocation policy interface and three baseline policies."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from typing import Protocol

from phalanx.domain import AllocationPolicyInput, AllocationTarget
from phalanx.portfolio.errors import AllocationZeroVolatilityError

_ALLOCATION_DECIMAL_PRECISION = 50
_ZERO = Decimal(0)


class AllocationPolicy(Protocol):
    """A policy that sees trailing close returns but never future prices."""

    policy_id: str
    policy_version: str

    def should_rebalance(self, signal_number: int) -> bool: ...

    def build_target(
        self,
        policy_input: AllocationPolicyInput,
        target_equity_weight: Decimal,
    ) -> AllocationTarget: ...


class WeeklyEqualWeight:
    """Reset every stock to an equal target at each eligible weekly signal."""

    policy_id = "weekly_equal_weight"
    policy_version = "1"

    def should_rebalance(self, signal_number: int) -> bool:
        return True

    def build_target(
        self,
        policy_input: AllocationPolicyInput,
        target_equity_weight: Decimal,
    ) -> AllocationTarget:
        return AllocationTarget(
            signal_date=policy_input.signal_date,
            stock_codes=policy_input.stock_codes,
            target_weights=_equal_weights(
                len(policy_input.stock_codes),
                target_equity_weight,
            ),
            policy_id=self.policy_id,
            target_equity_weight=target_equity_weight,
        )


class WeeklyInverseVolatility:
    """Allocate proportionally to inverse trailing sample volatility."""

    policy_id = "weekly_inverse_volatility"
    policy_version = "1"

    def should_rebalance(self, signal_number: int) -> bool:
        return True

    def build_target(
        self,
        policy_input: AllocationPolicyInput,
        target_equity_weight: Decimal,
    ) -> AllocationTarget:
        context = Context(prec=_ALLOCATION_DECIMAL_PRECISION, rounding=ROUND_HALF_EVEN)
        with localcontext(context):
            count = len(policy_input.return_values)
            if count < 2:
                raise AllocationZeroVolatilityError(policy_input.stock_codes[0])
            inverse_volatilities: list[Decimal] = []
            for column, stock_code in enumerate(policy_input.stock_codes):
                values = tuple(row[column] for row in policy_input.return_values)
                mean = sum(values, _ZERO) / Decimal(count)
                variance = sum(((value - mean) ** 2 for value in values), _ZERO) / Decimal(
                    count - 1
                )
                if variance <= 0:
                    raise AllocationZeroVolatilityError(stock_code)
                standard_deviation = context.sqrt(variance)
                if standard_deviation == 0:
                    raise AllocationZeroVolatilityError(stock_code)
                inverse_volatilities.append(Decimal(1) / standard_deviation)
            total_inverse_volatility = sum(inverse_volatilities, _ZERO)
            weights = _scaled_weights(
                tuple(inverse_volatilities),
                total_inverse_volatility,
                target_equity_weight,
            )
        return AllocationTarget(
            signal_date=policy_input.signal_date,
            stock_codes=policy_input.stock_codes,
            target_weights=weights,
            policy_id=self.policy_id,
            target_equity_weight=target_equity_weight,
        )


class EqualWeightBuyAndHold:
    """Buy equal weights once and allow all later weights to drift."""

    policy_id = "equal_weight_buy_and_hold"
    policy_version = "1"

    def should_rebalance(self, signal_number: int) -> bool:
        return signal_number == 0

    def build_target(
        self,
        policy_input: AllocationPolicyInput,
        target_equity_weight: Decimal,
    ) -> AllocationTarget:
        return AllocationTarget(
            signal_date=policy_input.signal_date,
            stock_codes=policy_input.stock_codes,
            target_weights=_equal_weights(
                len(policy_input.stock_codes),
                target_equity_weight,
            ),
            policy_id=self.policy_id,
            target_equity_weight=target_equity_weight,
        )


def default_allocation_policies() -> tuple[AllocationPolicy, ...]:
    """Return the fixed, ordered set compared by the first research harness."""

    return (
        WeeklyEqualWeight(),
        WeeklyInverseVolatility(),
        EqualWeightBuyAndHold(),
    )


def _equal_weights(count: int, target_equity_weight: Decimal) -> tuple[Decimal, ...]:
    context = Context(prec=_ALLOCATION_DECIMAL_PRECISION, rounding=ROUND_HALF_EVEN)
    with localcontext(context):
        equal = target_equity_weight / Decimal(count)
        return _weights_with_exact_total(
            tuple(equal for _ in range(count)),
            target_equity_weight,
        )


def _scaled_weights(
    values: tuple[Decimal, ...],
    total: Decimal,
    target_equity_weight: Decimal,
) -> tuple[Decimal, ...]:
    raw = tuple(value / total * target_equity_weight for value in values)
    return _weights_with_exact_total(raw, target_equity_weight)


def _weights_with_exact_total(
    values: tuple[Decimal, ...],
    target_equity_weight: Decimal,
) -> tuple[Decimal, ...]:
    if len(values) == 1:
        return (target_equity_weight,)
    leading = values[:-1]
    return (*leading, target_equity_weight - sum(leading, _ZERO))


__all__ = [
    "AllocationPolicy",
    "EqualWeightBuyAndHold",
    "WeeklyEqualWeight",
    "WeeklyInverseVolatility",
    "default_allocation_policies",
]
