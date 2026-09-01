"""Pure Decimal one-step fractional self-financing transitions."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import (
    MAX_PREC,
    ROUND_HALF_EVEN,
    Clamped,
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    Inexact,
    InvalidOperation,
    Overflow,
    Rounded,
    Subnormal,
    Underflow,
    localcontext,
)

# Keep the established allocation-backtest exception identity temporarily while
# exposing only the provider-neutral spelling inside the extracted kernel. A
# distinct neutral exception class is deferred beyond this behavior-only PR.
from phalanx.portfolio.errors import (
    AllocationSelfFinancingError as SelfFinancingTransitionError,
)

_DECIMAL_PRECISION = 50
_DECIMAL_EMIN = -999_999
_DECIMAL_EMAX = 999_999
_MAX_EXACT_SUM_PRECISION = _DECIMAL_PRECISION - _DECIMAL_EMIN
_MAX_FIXED_POINT_ITERATIONS = 256
_ZERO = Decimal(0)
_ONE = Decimal(1)
_CONTEXT_CREATION_ERROR = "Decimal 계산 컨텍스트 정밀도가 지원 범위를 벗어났습니다."
_EXACT_SUM_ERROR = "목표비중 합계를 유한한 Decimal로 정확히 계산하지 못했습니다."


@dataclass(frozen=True, slots=True)
class SelfFinancingTransitionInput:
    """Immutable Decimal inputs for one fractional self-financing transition."""

    current_quantities: tuple[Decimal, ...]
    cash_before: Decimal
    valuation_prices: tuple[Decimal, ...]
    target_weights: tuple[Decimal, ...]
    target_equity_weight: Decimal
    buy_cost_rate: Decimal
    sell_cost_rate: Decimal

    @classmethod
    def _from_validated_values(
        cls,
        *,
        current_quantities: tuple[Decimal, ...],
        cash_before: Decimal,
        valuation_prices: tuple[Decimal, ...],
        target_weights: tuple[Decimal, ...],
        target_equity_weight: Decimal,
        buy_cost_rate: Decimal,
        sell_cost_rate: Decimal,
    ) -> SelfFinancingTransitionInput:
        """Construct after validation except for the legacy exact-sum check."""

        _validate_transition_values(
            current_quantities=current_quantities,
            cash_before=cash_before,
            valuation_prices=valuation_prices,
            target_weights=target_weights,
            target_equity_weight=target_equity_weight,
            buy_cost_rate=buy_cost_rate,
            sell_cost_rate=sell_cost_rate,
            require_exact_target_sum=False,
        )

        instance = object.__new__(cls)
        object.__setattr__(instance, "current_quantities", current_quantities)
        object.__setattr__(instance, "cash_before", cash_before)
        object.__setattr__(instance, "valuation_prices", valuation_prices)
        object.__setattr__(instance, "target_weights", target_weights)
        object.__setattr__(instance, "target_equity_weight", target_equity_weight)
        object.__setattr__(instance, "buy_cost_rate", buy_cost_rate)
        object.__setattr__(instance, "sell_cost_rate", sell_cost_rate)
        return instance

    def __post_init__(self) -> None:
        _validate_transition_values(
            current_quantities=self.current_quantities,
            cash_before=self.cash_before,
            valuation_prices=self.valuation_prices,
            target_weights=self.target_weights,
            target_equity_weight=self.target_equity_weight,
            buy_cost_rate=self.buy_cost_rate,
            sell_cost_rate=self.sell_cost_rate,
            require_exact_target_sum=True,
        )


@dataclass(frozen=True, slots=True)
class SelfFinancingTransitionResult:
    """Exact immutable output of one fractional self-financing transition."""

    quantities_after: tuple[Decimal, ...]
    actual_values_after: tuple[Decimal, ...]
    actual_stock_total_after: Decimal
    buy_notional: Decimal
    sell_notional: Decimal
    buy_gross_turnover: Decimal
    sell_gross_turnover: Decimal
    transaction_cost: Decimal
    transaction_cost_rate: Decimal
    pre_trade_nav: Decimal
    post_trade_nav: Decimal
    cash_after: Decimal
    realized_weights: tuple[Decimal, ...]
    realized_cash_weight: Decimal


def apply_fractional_self_financing_transition(
    transition_input: SelfFinancingTransitionInput,
) -> SelfFinancingTransitionResult:
    """Apply one deterministic fractional transition in a fresh fixed context."""

    calculation_context = _new_decimal_context(_DECIMAL_PRECISION)
    with localcontext(calculation_context) as context:
        context.clear_flags()
        if type(transition_input) is not SelfFinancingTransitionInput:
            raise SelfFinancingTransitionError(
                "자기금융 전환 입력은 SelfFinancingTransitionInput이어야 합니다."
            )
        return _apply_fractional_self_financing_transition(transition_input, context)


def _new_decimal_context(
    precision: int,
    *,
    error_message: str = _CONTEXT_CREATION_ERROR,
) -> Context:
    if type(precision) is not int or not 1 <= precision <= MAX_PREC:
        raise SelfFinancingTransitionError(error_message)
    try:
        context = Context(
            prec=precision,
            rounding=ROUND_HALF_EVEN,
            Emin=_DECIMAL_EMIN,
            Emax=_DECIMAL_EMAX,
            capitals=1,
            clamp=0,
            flags=[],
            traps=[],
        )
    except (DecimalException, OverflowError, TypeError, ValueError):
        raise SelfFinancingTransitionError(error_message) from None
    for signal in context.traps:
        context.traps[signal] = False
    for signal in (InvalidOperation, DivisionByZero, Overflow):
        context.traps[signal] = True
    context.clear_flags()
    return context


def _validate_transition_values(
    *,
    current_quantities: tuple[Decimal, ...],
    cash_before: Decimal,
    valuation_prices: tuple[Decimal, ...],
    target_weights: tuple[Decimal, ...],
    target_equity_weight: Decimal,
    buy_cost_rate: Decimal,
    sell_cost_rate: Decimal,
    require_exact_target_sum: bool,
) -> None:
    validation_context = _new_decimal_context(_DECIMAL_PRECISION)
    with localcontext(validation_context) as context:
        context.clear_flags()
        if type(cash_before) is not Decimal or not cash_before.is_finite():
            raise SelfFinancingTransitionError(
                "자기금융 체결 전 현금은 0 이상의 유한한 Decimal이어야 합니다."
            )
        if cash_before < 0:
            raise SelfFinancingTransitionError(
                "자기금융 체결 전 현금은 0 이상의 유한한 Decimal이어야 합니다."
            )
        _require_decimal_tuple(current_quantities, "current_quantities")
        _require_decimal_tuple(valuation_prices, "valuation_prices")
        _require_decimal_tuple(target_weights, "target_weights")
        if not current_quantities:
            raise SelfFinancingTransitionError("자기금융 전환에는 최소 1개 종목이 필요합니다.")
        if len(current_quantities) != len(valuation_prices):
            raise SelfFinancingTransitionError(
                "보유수량과 평가가격의 종목 수가 일치하지 않습니다."
            )
        if len(target_weights) != len(valuation_prices):
            raise SelfFinancingTransitionError(
                "목표가치와 체결가격의 종목 수가 일치하지 않습니다."
            )
        if any(not value.is_finite() or value < 0 for value in current_quantities):
            raise SelfFinancingTransitionError(
                "보유수량은 0 이상의 유한한 Decimal이어야 합니다."
            )
        if any(not value.is_finite() or value <= 0 for value in valuation_prices):
            raise SelfFinancingTransitionError(
                "평가가격은 양의 유한한 Decimal이어야 합니다."
            )
        if any(not value.is_finite() or value < 0 for value in target_weights):
            raise SelfFinancingTransitionError(
                "목표비중은 0 이상의 유한한 Decimal이어야 합니다."
            )
        if (
            type(target_equity_weight) is not Decimal
            or not target_equity_weight.is_finite()
            or not (_ZERO < target_equity_weight <= _ONE)
        ):
            raise SelfFinancingTransitionError(
                "목표 주식비중은 0 초과 1 이하의 유한한 Decimal이어야 합니다."
            )
        if (
            require_exact_target_sum
            and _exact_decimal_sum(target_weights) != target_equity_weight
        ):
            raise SelfFinancingTransitionError(
                "목표비중 합계는 목표 주식비중과 정확히 일치해야 합니다."
            )
        for name, cost_rate in (
            ("매수비용률", buy_cost_rate),
            ("매도비용률", sell_cost_rate),
        ):
            if (
                type(cost_rate) is not Decimal
                or not cost_rate.is_finite()
                or not (_ZERO <= cost_rate < _ONE)
            ):
                raise SelfFinancingTransitionError(
                    f"{name}은 0 이상 1 미만의 유한한 Decimal이어야 합니다."
                )


def _require_decimal_tuple(values: object, name: str) -> None:
    if type(values) is not tuple:
        raise SelfFinancingTransitionError(f"{name}은 Decimal tuple이어야 합니다.")
    if any(type(value) is not Decimal for value in values):
        raise SelfFinancingTransitionError(f"{name}은 Decimal 값만 포함해야 합니다.")


def _exact_decimal_sum(values: tuple[Decimal, ...]) -> Decimal:
    nonzero_values = tuple(value for value in values if not value.is_zero())
    if not nonzero_values:
        return _ZERO
    exponents = tuple(_finite_decimal_exponent(value) for value in nonzero_values)
    if any(
        not _DECIMAL_EMIN
        <= exponent + len(value.as_tuple().digits) - 1
        <= _DECIMAL_EMAX
        for value, exponent in zip(nonzero_values, exponents, strict=True)
    ):
        raise SelfFinancingTransitionError(_EXACT_SUM_ERROR)
    minimum_exponent = min(exponents)
    precision = max(
        len(value.as_tuple().digits) + exponent - minimum_exponent
        for value, exponent in zip(nonzero_values, exponents, strict=True)
    ) + len(str(len(nonzero_values)))
    if not 1 <= precision <= _MAX_EXACT_SUM_PRECISION:
        raise SelfFinancingTransitionError(_EXACT_SUM_ERROR)
    validation_context = _new_decimal_context(
        precision,
        error_message=_EXACT_SUM_ERROR,
    )
    with localcontext(validation_context) as context:
        context.clear_flags()
        try:
            total = _ZERO
            for value in nonzero_values:
                total = context.add(total, value)
        except DecimalException:
            raise SelfFinancingTransitionError(_EXACT_SUM_ERROR) from None
        if any(
            context.flags[signal]
            for signal in (Clamped, Inexact, Rounded, Subnormal, Underflow)
        ):
            raise SelfFinancingTransitionError(_EXACT_SUM_ERROR)
    return total


def _finite_decimal_exponent(value: Decimal) -> int:
    exponent = value.as_tuple().exponent
    if type(exponent) is not int:
        raise SelfFinancingTransitionError(
            "목표비중은 0 이상의 유한한 Decimal이어야 합니다."
        )
    return exponent


def _apply_fractional_self_financing_transition(
    transition_input: SelfFinancingTransitionInput,
    context: Context,
) -> SelfFinancingTransitionResult:
    cash = transition_input.cash_before
    quantities = transition_input.current_quantities
    prices = transition_input.valuation_prices
    target_weights = transition_input.target_weights
    target_equity_weight = transition_input.target_equity_weight
    buy_cost_rate = transition_input.buy_cost_rate
    sell_cost_rate = transition_input.sell_cost_rate

    if not isinstance(cash, Decimal) or not cash.is_finite() or cash < 0:
        raise SelfFinancingTransitionError(
            "자기금융 체결 전 현금은 0 이상의 유한한 Decimal이어야 합니다."
        )
    current_values, current_stock_total = _value_holdings(
        quantities,
        prices,
        context,
    )
    try:
        pre_trade_nav = context.add(cash, current_stock_total)
    except DecimalException:
        raise SelfFinancingTransitionError(
            "자기금융 체결 전 NAV를 유한한 Decimal로 계산하지 못했습니다."
        ) from None
    if not pre_trade_nav.is_finite() or pre_trade_nav <= 0:
        raise SelfFinancingTransitionError(
            "자기금융 체결 전 NAV는 양의 유한한 Decimal이어야 합니다."
        )
    post_trade_nav = pre_trade_nav
    seen_candidates: set[Decimal] = set()
    for _ in range(_MAX_FIXED_POINT_ITERATIONS):
        if post_trade_nav in seen_candidates:
            raise SelfFinancingTransitionError(
                "비대칭 거래비용 자기금융 계산이 순환하여 수렴하지 않았습니다."
            )
        seen_candidates.add(post_trade_nav)
        desired_values = _desired_values(
            target_weights,
            target_equity_weight,
            post_trade_nav,
        )
        buys, sells = _trade_notionals(current_values, desired_values)
        transaction_cost = buys * buy_cost_rate + sells * sell_cost_rate
        next_post_trade_nav = pre_trade_nav - transaction_cost
        if next_post_trade_nav <= 0:
            raise SelfFinancingTransitionError(
                "거래비용 차감 후 NAV가 0 이하이므로 자기금융 체결이 불가능합니다."
            )
        if next_post_trade_nav == post_trade_nav:
            break
        post_trade_nav = next_post_trade_nav
    else:
        raise SelfFinancingTransitionError(
            "비대칭 거래비용 자기금융 계산이 허용 횟수 안에 수렴하지 않았습니다."
        )

    desired_values = _desired_values(
        target_weights,
        target_equity_weight,
        post_trade_nav,
    )
    buys, sells = _trade_notionals(current_values, desired_values)
    transaction_cost = buys * buy_cost_rate + sells * sell_cost_rate
    reconciled_post_nav = pre_trade_nav - transaction_cost
    if reconciled_post_nav != post_trade_nav:
        raise SelfFinancingTransitionError(
            "자기금융 거래비용과 거래 후 NAV가 정확히 대사되지 않습니다."
        )
    new_quantities, actual_values, actual_stock_total = _value_target_holdings(
        target_weights,
        target_equity_weight,
        desired_values,
        prices,
        post_trade_nav,
        context,
    )
    try:
        cash_after = context.subtract(post_trade_nav, actual_stock_total)
    except DecimalException:
        raise SelfFinancingTransitionError(
            "자기금융 체결 후 잔여 현금을 유한한 Decimal로 계산하지 못했습니다."
        ) from None
    if not cash_after.is_finite() or cash_after < 0:
        raise SelfFinancingTransitionError("자기금융 체결 후 잔여 현금이 음수입니다.")
    realized, realized_cash = _realized_weights(
        actual_values,
        actual_stock_total,
        cash_after,
        post_trade_nav,
        context,
    )
    return SelfFinancingTransitionResult(
        quantities_after=new_quantities,
        actual_values_after=actual_values,
        actual_stock_total_after=actual_stock_total,
        buy_notional=buys,
        sell_notional=sells,
        buy_gross_turnover=buys / pre_trade_nav,
        sell_gross_turnover=sells / pre_trade_nav,
        transaction_cost=transaction_cost,
        transaction_cost_rate=transaction_cost / pre_trade_nav,
        pre_trade_nav=pre_trade_nav,
        post_trade_nav=post_trade_nav,
        cash_after=cash_after,
        realized_weights=realized,
        realized_cash_weight=realized_cash,
    )


def _desired_values(
    target_weights: tuple[Decimal, ...],
    target_equity_weight: Decimal,
    post_trade_nav: Decimal,
) -> tuple[Decimal, ...]:
    if len(target_weights) == 1:
        return (target_equity_weight * post_trade_nav,)
    leading = tuple(weight * post_trade_nav for weight in target_weights[:-1])
    final_value = target_equity_weight * post_trade_nav - sum(leading, _ZERO)
    return (*leading, final_value)


def _trade_notionals(
    current_values: tuple[Decimal, ...],
    desired_values: tuple[Decimal, ...],
) -> tuple[Decimal, Decimal]:
    changes = tuple(
        desired - current for current, desired in zip(current_values, desired_values, strict=True)
    )
    buys = sum((change for change in changes if change > 0), _ZERO)
    sells = sum((-change for change in changes if change < 0), _ZERO)
    return buys, sells


def _value_holdings(
    quantities: tuple[Decimal, ...],
    prices: tuple[Decimal, ...],
    context: Context,
) -> tuple[tuple[Decimal, ...], Decimal]:
    if len(quantities) != len(prices):
        raise SelfFinancingTransitionError(
            "보유수량과 평가가격의 종목 수가 일치하지 않습니다."
        )
    if any(
        not isinstance(value, Decimal) or not value.is_finite() or value < 0
        for value in quantities
    ):
        raise SelfFinancingTransitionError(
            "보유수량은 0 이상의 유한한 Decimal이어야 합니다."
        )
    if any(
        not isinstance(value, Decimal) or not value.is_finite() or value <= 0
        for value in prices
    ):
        raise SelfFinancingTransitionError(
            "평가가격은 양의 유한한 Decimal이어야 합니다."
        )
    try:
        stock_values = tuple(
            context.multiply(quantity, price)
            for quantity, price in zip(quantities, prices, strict=True)
        )
    except DecimalException:
        raise SelfFinancingTransitionError(
            "수량과 가격으로 유한한 종목가치를 계산하지 못했습니다."
        ) from None
    return stock_values, _accumulate_stock_values(stock_values, context)


def _value_target_holdings(
    target_weights: tuple[Decimal, ...],
    target_equity_weight: Decimal,
    desired_values: tuple[Decimal, ...],
    prices: tuple[Decimal, ...],
    post_trade_nav: Decimal,
    context: Context,
) -> tuple[tuple[Decimal, ...], tuple[Decimal, ...], Decimal]:
    if len(desired_values) != len(prices):
        raise SelfFinancingTransitionError(
            "목표가치와 체결가격의 종목 수가 일치하지 않습니다."
        )
    if any(
        not isinstance(value, Decimal) or not value.is_finite() or value < 0
        for value in desired_values
    ):
        raise SelfFinancingTransitionError(
            "목표 종목가치는 0 이상의 유한한 Decimal이어야 합니다."
        )
    if any(
        not isinstance(value, Decimal) or not value.is_finite() or value <= 0
        for value in prices
    ):
        raise SelfFinancingTransitionError(
            "체결가격은 양의 유한한 Decimal이어야 합니다."
        )
    try:
        stock_budget = context.multiply(target_equity_weight, post_trade_nav)
    except DecimalException:
        raise SelfFinancingTransitionError(
            "목표 종목가치 합계를 유한한 Decimal로 계산하지 못했습니다."
        ) from None
    if not stock_budget.is_finite() or stock_budget < 0:
        raise SelfFinancingTransitionError("목표 종목가치 합계가 올바르지 않습니다.")

    if target_equity_weight != _ONE:
        quantity_values = tuple(
            _target_quantity_value(value, price, context)
            for value, price in zip(desired_values, prices, strict=True)
        )
        quantities = tuple(value[0] for value in quantity_values)
        actual_values = tuple(value[1] for value in quantity_values)
        actual_total = _accumulate_stock_values(actual_values, context)
        return quantities, actual_values, actual_total

    anchor_index = next(
        (
            index
            for index in range(len(target_weights) - 1, -1, -1)
            if target_weights[index] > 0
        ),
        None,
    )
    if anchor_index is None:
        raise SelfFinancingTransitionError("목표가치 잔차를 대사할 양수 종목비중이 없습니다.")

    anchored_quantities = [_ZERO for _ in desired_values]
    anchored_values = [_ZERO for _ in desired_values]
    other_total = _ZERO
    try:
        # The last positive target is the deterministic quantity anchor. Values
        # after it are target-zero, so the running total stays in stock order.
        for index, (desired_value, price) in enumerate(
            zip(
                desired_values[:anchor_index],
                prices[:anchor_index],
                strict=True,
            )
        ):
            quantity, actual_value = _target_quantity_value(
                desired_value,
                price,
                context,
            )
            anchored_quantities[index] = quantity
            anchored_values[index] = actual_value
            other_total = context.add(other_total, actual_value)

        anchor_notional = context.subtract(stock_budget, other_total)
        if not anchor_notional.is_finite() or anchor_notional < 0:
            raise SelfFinancingTransitionError(
                "실제 종목가치 잔차를 비음수로 대사할 수 없습니다."
            )
        anchor_quantity, anchor_value = _target_quantity_value(
            anchor_notional,
            prices[anchor_index],
            context,
        )
        anchored_quantities[anchor_index] = anchor_quantity
        anchored_values[anchor_index] = anchor_value
        actual_total = context.add(other_total, anchor_value)
    except DecimalException:
        raise SelfFinancingTransitionError(
            "실제 종목가치를 유한한 Decimal로 대사하지 못했습니다."
        ) from None
    if not actual_total.is_finite() or actual_total < 0:
        raise SelfFinancingTransitionError(
            "실제 종목가치 합계가 올바르지 않습니다."
        )
    return tuple(anchored_quantities), tuple(anchored_values), actual_total


def _target_quantity_value(
    desired_value: Decimal,
    price: Decimal,
    context: Context,
) -> tuple[Decimal, Decimal]:
    operation_context = context.copy()
    operation_context.clear_flags()
    try:
        quantity = operation_context.divide(desired_value, price)
        actual_value = operation_context.multiply(quantity, price)
    except DecimalException:
        raise SelfFinancingTransitionError(
            "목표가치를 유한한 연속수량·종목가치로 변환하지 못했습니다."
        ) from None
    if operation_context.flags[Underflow] or operation_context.flags[Subnormal]:
        raise SelfFinancingTransitionError(
            "목표수량·종목가치 계산에서 Decimal underflow가 발생했습니다."
        )
    if not quantity.is_finite() or quantity < 0:
        raise SelfFinancingTransitionError(
            "목표수량은 0 이상의 유한한 Decimal이어야 합니다."
        )
    if not actual_value.is_finite() or actual_value < 0:
        raise SelfFinancingTransitionError(
            "실제 종목가치는 0 이상의 유한한 Decimal이어야 합니다."
        )
    if desired_value > 0 and (quantity == _ZERO or actual_value == _ZERO):
        raise SelfFinancingTransitionError(
            "양수 목표 종목가치를 0이 아닌 수량·종목가치로 표현하지 못했습니다."
        )
    return quantity, actual_value


def _accumulate_stock_values(
    stock_values: tuple[Decimal, ...],
    context: Context,
) -> Decimal:
    total = _ZERO
    for value in stock_values:
        if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
            raise SelfFinancingTransitionError(
                "종목가치는 0 이상의 유한한 Decimal이어야 합니다."
            )
        try:
            total = context.add(total, value)
        except DecimalException:
            raise SelfFinancingTransitionError(
                "종목가치 합계를 유한한 Decimal로 계산하지 못했습니다."
            ) from None
    if not total.is_finite() or total < 0:
        raise SelfFinancingTransitionError(
            "종목가치 합계는 0 이상의 유한한 Decimal이어야 합니다."
        )
    return total


def _nav_ulp(nav: Decimal, context: Context) -> Decimal:
    if not isinstance(nav, Decimal) or not nav.is_finite() or nav <= 0:
        raise SelfFinancingTransitionError(
            "Decimal ULP 계산 기준 NAV는 양의 유한한 값이어야 합니다."
        )
    try:
        # This is the adjacent representable spacing at NAV in the same fixed
        # context as the accounting engine, not an absolute tolerance.
        next_nav = context.next_plus(nav)
        ulp = context.subtract(next_nav, nav)
    except DecimalException:
        raise SelfFinancingTransitionError(
            "Decimal ULP를 유한한 값으로 계산하지 못했습니다."
        ) from None
    if not next_nav.is_finite() or not ulp.is_finite() or ulp <= 0:
        raise SelfFinancingTransitionError(
            "Decimal ULP를 양의 유한한 값으로 계산하지 못했습니다."
        )
    return ulp


def _decimal_gap(left: Decimal, right: Decimal, context: Context) -> Decimal:
    try:
        gap = context.copy_abs(context.subtract(left, right))
    except DecimalException:
        raise SelfFinancingTransitionError(
            "Decimal 표현 차이를 유한한 값으로 계산하지 못했습니다."
        ) from None
    if not gap.is_finite():
        raise SelfFinancingTransitionError("Decimal 표현 차이는 유한해야 합니다.")
    return gap


def _realized_weights(
    stock_values: tuple[Decimal, ...],
    stock_value_total: Decimal,
    cash_value: Decimal,
    nav: Decimal,
    context: Context,
) -> tuple[tuple[Decimal, ...], Decimal]:
    if not stock_values:
        raise SelfFinancingTransitionError("실현비중 계산에는 종목가치가 필요합니다.")
    if any(
        not isinstance(value, Decimal) or not value.is_finite() or value < 0
        for value in stock_values
    ):
        raise SelfFinancingTransitionError(
            "실현비중 계산의 종목가치는 0 이상의 유한한 Decimal이어야 합니다."
        )
    if (
        not isinstance(stock_value_total, Decimal)
        or not stock_value_total.is_finite()
        or stock_value_total < 0
        or any(value > stock_value_total for value in stock_values)
    ):
        raise SelfFinancingTransitionError(
            "실현비중 계산의 종목가치 합계가 올바르지 않습니다."
        )
    if not isinstance(cash_value, Decimal) or not cash_value.is_finite() or cash_value < 0:
        raise SelfFinancingTransitionError(
            "실현비중 계산의 실제 현금은 0 이상의 유한한 Decimal이어야 합니다."
        )
    if not isinstance(nav, Decimal) or not nav.is_finite() or nav <= 0:
        raise SelfFinancingTransitionError(
            "실현비중 계산의 NAV는 양의 유한한 Decimal이어야 합니다."
        )
    try:
        recombined_nav = context.add(stock_value_total, cash_value)
    except DecimalException:
        raise SelfFinancingTransitionError(
            "실현비중 계산의 주식가치·현금·NAV를 유한하게 대사하지 못했습니다."
        ) from None
    if not recombined_nav.is_finite():
        raise SelfFinancingTransitionError(
            "실현비중 계산의 주식가치·현금·NAV 대사값이 유한하지 않습니다."
        )
    nav_residual = _decimal_gap(recombined_nav, nav, context)
    if nav_residual > _nav_ulp(nav, context):
        raise SelfFinancingTransitionError(
            "실현비중 계산의 주식가치·현금·NAV 불일치가 1 Decimal ULP를 초과합니다."
        )
    try:
        weights = tuple(context.divide(value, nav) for value in stock_values)
        weight_total = _ZERO
        for weight in weights:
            weight_total = context.add(weight_total, weight)
        cash_weight = context.subtract(_ONE, weight_total)
        exact_weight_total = context.add(weight_total, cash_weight)
    except DecimalException:
        raise SelfFinancingTransitionError(
            "실현비중을 유한한 Decimal로 계산하지 못했습니다."
        ) from None
    if (
        all(weight.is_finite() and weight >= 0 for weight in weights)
        and cash_weight.is_finite()
        and cash_weight >= 0
        and exact_weight_total == _ONE
    ):
        return weights, cash_weight

    try:
        actual_cash_weight = context.divide(cash_value, nav)
    except DecimalException:
        raise SelfFinancingTransitionError(
            "실현 현금비중을 유한한 Decimal로 계산하지 못했습니다."
        ) from None
    if not actual_cash_weight.is_finite() or actual_cash_weight < 0:
        raise SelfFinancingTransitionError(
            "실현 현금비중은 0 이상의 유한한 Decimal이어야 합니다."
        )
    anchor_index = next(
        (index for index in range(len(stock_values) - 1, -1, -1) if stock_values[index] > 0),
        None,
    )
    if anchor_index is None:
        raise SelfFinancingTransitionError(
            "실현비중 Decimal 잔차를 대사할 양수 주식가치가 없습니다."
        )
    try:
        other_weight = _ZERO
        for weight in weights[:anchor_index]:
            other_weight = context.add(other_weight, weight)
        anchor_weight = context.subtract(
            context.subtract(_ONE, actual_cash_weight),
            other_weight,
        )
    except DecimalException:
        raise SelfFinancingTransitionError(
            "실현비중 Decimal 잔차를 유한하게 대사하지 못했습니다."
        ) from None
    if not anchor_weight.is_finite() or anchor_weight < 0:
        raise SelfFinancingTransitionError(
            "실현비중 Decimal 잔차를 비음수 종목비중으로 대사할 수 없습니다."
        )
    reconciled = list(weights)
    reconciled[anchor_index] = anchor_weight
    reconciled_tuple = tuple(reconciled)
    try:
        reconciled_total = _ZERO
        for weight in reconciled_tuple:
            reconciled_total = context.add(reconciled_total, weight)
        exact_total = context.add(reconciled_total, actual_cash_weight)
    except DecimalException:
        raise SelfFinancingTransitionError(
            "실현비중 Decimal 잔차 대사 결과를 검증하지 못했습니다."
        ) from None
    if exact_total != _ONE:
        raise SelfFinancingTransitionError(
            "실현 주식비중과 현금비중 합계를 정확히 1로 대사하지 못했습니다."
        )
    return reconciled_tuple, actual_cash_weight


__all__ = [
    "SelfFinancingTransitionError",
    "SelfFinancingTransitionInput",
    "SelfFinancingTransitionResult",
    "apply_fractional_self_financing_transition",
]
