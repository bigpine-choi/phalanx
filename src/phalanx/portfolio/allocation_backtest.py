"""Pure Decimal walk-forward allocation execution and self-financing accounting."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

from phalanx.domain import (
    AlignedPricePanel,
    AllocationBacktestConfig,
    AllocationBacktestResult,
    AllocationRebalanceRecord,
    AllocationTarget,
)
from phalanx.portfolio._allocation_schedule import build_price_panel_signal_windows
from phalanx.portfolio.allocation_policies import AllocationPolicy
from phalanx.portfolio.errors import (
    AllocationSelfFinancingError,
    InvalidAllocationTargetError,
)

_ALLOCATION_DECIMAL_PRECISION = 50
_MAX_FIXED_POINT_ITERATIONS = 256
_ZERO = Decimal(0)
_ONE = Decimal(1)


def run_allocation_backtest(
    panel: AlignedPricePanel,
    policy: AllocationPolicy,
    config: AllocationBacktestConfig,
    *,
    initial_nav: Decimal = _ONE,
) -> AllocationBacktestResult:
    """Run one policy using close signals and strictly next-open execution."""

    if not isinstance(initial_nav, Decimal) or not initial_nav.is_finite() or initial_nav <= 0:
        raise AllocationSelfFinancingError("초기 NAV는 양의 유한한 Decimal이어야 합니다.")

    calculation_context = Context(
        prec=_ALLOCATION_DECIMAL_PRECISION,
        rounding=ROUND_HALF_EVEN,
    )
    with localcontext(calculation_context) as context:
        scheduled_targets = _scheduled_targets(panel, policy, config)
        if not scheduled_targets:
            raise AllocationSelfFinancingError(
                "정책이 실행 가능한 리밸런싱 목표를 생성하지 않았습니다."
            )
        result = _simulate(
            panel,
            policy.policy_id,
            scheduled_targets,
            config,
            initial_nav,
            context,
        )
    return result


def _scheduled_targets(
    panel: AlignedPricePanel,
    policy: AllocationPolicy,
    config: AllocationBacktestConfig,
) -> dict[int, AllocationTarget]:
    targets: dict[int, AllocationTarget] = {}
    for signal_window in build_price_panel_signal_windows(panel, config):
        policy_input = signal_window.policy_input
        if not policy.should_rebalance(policy_input.signal_number):
            continue
        signal_index = signal_window.as_of_index + 1
        target = policy.build_target(policy_input, config.target_equity_weight)
        _validate_policy_target(target, panel, policy, config, signal_index)
        execution_index = signal_window.as_of_index + 2
        targets[execution_index] = target
    return targets


def _validate_policy_target(
    target: AllocationTarget,
    panel: AlignedPricePanel,
    policy: AllocationPolicy,
    config: AllocationBacktestConfig,
    signal_index: int,
) -> None:
    if target.signal_date != panel.dates[signal_index]:
        raise InvalidAllocationTargetError("정책 목표 기준일이 실제 신호일과 일치하지 않습니다.")
    if target.stock_codes != panel.stock_codes:
        raise InvalidAllocationTargetError(
            "정책 목표 종목 순서가 가격 패널 등록 순서와 일치하지 않습니다."
        )
    if target.policy_id != policy.policy_id:
        raise InvalidAllocationTargetError("정책 목표 식별자가 실행 정책과 일치하지 않습니다.")
    if target.target_equity_weight != config.target_equity_weight:
        raise InvalidAllocationTargetError(
            "정책 목표 주식비중이 공통 backtest 설정과 일치하지 않습니다."
        )


def _simulate(
    panel: AlignedPricePanel,
    policy_id: str,
    scheduled_targets: dict[int, AllocationTarget],
    config: AllocationBacktestConfig,
    initial_nav: Decimal,
    context: Context,
) -> AllocationBacktestResult:
    first_execution_index = min(scheduled_targets)
    quantities = tuple(_ZERO for _ in panel.stock_codes)
    cash = initial_nav
    dates: list[date] = []
    navs: list[Decimal] = []
    realized_weights: list[tuple[Decimal, ...]] = []
    realized_cash_weights: list[Decimal] = []
    records: list[AllocationRebalanceRecord] = []

    for price_index in range(first_execution_index, len(panel.dates)):
        target = scheduled_targets.get(price_index)
        if target is not None:
            quantities, cash, record = _execute_target(
                target,
                panel.dates[price_index],
                panel.open_prices[price_index],
                quantities,
                cash,
                config,
            )
            records.append(record)

        close_values = tuple(
            quantity * price
            for quantity, price in zip(
                quantities,
                panel.close_prices[price_index],
                strict=True,
            )
        )
        close_nav = cash + sum(close_values, _ZERO)
        if close_nav <= 0:
            raise AllocationSelfFinancingError(
                "비용 차감 일별 NAV가 0 이하가 되어 연구를 계속할 수 없습니다."
            )
        weights, cash_weight = _realized_weights(close_values, close_nav)
        dates.append(panel.dates[price_index])
        navs.append(close_nav)
        realized_weights.append(weights)
        realized_cash_weights.append(cash_weight)

    nav_tuple = tuple(navs)
    daily_returns = _nav_returns(nav_tuple, initial_nav)
    total_return, annualized_return, annualized_volatility, max_drawdown = _metrics(
        nav_tuple,
        daily_returns,
        initial_nav,
        config.annualization_trading_days,
        context,
    )
    record_tuple = tuple(records)
    cumulative_cost = sum((record.transaction_cost for record in record_tuple), _ZERO)
    return AllocationBacktestResult(
        policy_id=policy_id,
        stock_codes=panel.stock_codes,
        dates=tuple(dates),
        net_asset_values=nav_tuple,
        realized_weights=tuple(realized_weights),
        realized_cash_weights=tuple(realized_cash_weights),
        rebalances=record_tuple,
        buy_gross_turnover=sum(
            (record.buy_gross_turnover for record in record_tuple),
            _ZERO,
        ),
        sell_gross_turnover=sum(
            (record.sell_gross_turnover for record in record_tuple),
            _ZERO,
        ),
        cumulative_transaction_cost=cumulative_cost,
        cumulative_cost_rate=cumulative_cost / initial_nav,
        total_return=total_return,
        annualized_return=annualized_return,
        annualized_volatility=annualized_volatility,
        max_drawdown=max_drawdown,
    )


def _execute_target(
    target: AllocationTarget,
    execution_date: date,
    open_prices: tuple[Decimal, ...],
    quantities: tuple[Decimal, ...],
    cash: Decimal,
    config: AllocationBacktestConfig,
) -> tuple[tuple[Decimal, ...], Decimal, AllocationRebalanceRecord]:
    current_values = tuple(
        quantity * price for quantity, price in zip(quantities, open_prices, strict=True)
    )
    pre_trade_nav = cash + sum(current_values, _ZERO)
    post_trade_nav = pre_trade_nav
    seen_candidates: set[Decimal] = set()
    for _ in range(_MAX_FIXED_POINT_ITERATIONS):
        if post_trade_nav in seen_candidates:
            raise AllocationSelfFinancingError(
                "비대칭 거래비용 자기금융 계산이 순환하여 수렴하지 않았습니다."
            )
        seen_candidates.add(post_trade_nav)
        desired_values = _desired_values(target, post_trade_nav)
        buys, sells = _trade_notionals(current_values, desired_values)
        transaction_cost = buys * config.buy_cost_rate + sells * config.sell_cost_rate
        next_post_trade_nav = pre_trade_nav - transaction_cost
        if next_post_trade_nav <= 0:
            raise AllocationSelfFinancingError(
                "거래비용 차감 후 NAV가 0 이하이므로 자기금융 체결이 불가능합니다."
            )
        if next_post_trade_nav == post_trade_nav:
            break
        post_trade_nav = next_post_trade_nav
    else:
        raise AllocationSelfFinancingError(
            "비대칭 거래비용 자기금융 계산이 허용 횟수 안에 수렴하지 않았습니다."
        )

    desired_values = _desired_values(target, post_trade_nav)
    buys, sells = _trade_notionals(current_values, desired_values)
    transaction_cost = buys * config.buy_cost_rate + sells * config.sell_cost_rate
    reconciled_post_nav = pre_trade_nav - transaction_cost
    if reconciled_post_nav != post_trade_nav:
        raise AllocationSelfFinancingError(
            "자기금융 거래비용과 거래 후 NAV가 정확히 대사되지 않습니다."
        )
    new_quantities = tuple(
        value / price for value, price in zip(desired_values, open_prices, strict=True)
    )
    cash_after = post_trade_nav - sum(desired_values, _ZERO)
    if cash_after < 0:
        raise AllocationSelfFinancingError("자기금융 체결 후 잔여 현금이 음수입니다.")
    realized, realized_cash = _realized_weights(desired_values, post_trade_nav)
    record = AllocationRebalanceRecord(
        target=target,
        execution_date=execution_date,
        realized_weights=realized,
        realized_cash_weight=realized_cash,
        buy_gross_turnover=buys / pre_trade_nav,
        sell_gross_turnover=sells / pre_trade_nav,
        transaction_cost=transaction_cost,
        transaction_cost_rate=transaction_cost / pre_trade_nav,
        pre_trade_nav=pre_trade_nav,
        post_trade_nav=post_trade_nav,
        cash_after=cash_after,
    )
    return new_quantities, cash_after, record


def _desired_values(target: AllocationTarget, post_trade_nav: Decimal) -> tuple[Decimal, ...]:
    if len(target.target_weights) == 1:
        return (target.target_equity_weight * post_trade_nav,)
    leading = tuple(weight * post_trade_nav for weight in target.target_weights[:-1])
    final_value = target.target_equity_weight * post_trade_nav - sum(leading, _ZERO)
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


def _realized_weights(
    stock_values: tuple[Decimal, ...],
    nav: Decimal,
) -> tuple[tuple[Decimal, ...], Decimal]:
    weights = tuple(value / nav for value in stock_values)
    cash_weight = _ONE - sum(weights, _ZERO)
    if cash_weight < 0:
        raise AllocationSelfFinancingError("실현비중 계산 결과 현금비중이 음수입니다.")
    return weights, cash_weight


def _nav_returns(
    navs: tuple[Decimal, ...],
    initial_nav: Decimal,
) -> tuple[Decimal, ...]:
    previous = initial_nav
    returns: list[Decimal] = []
    for current in navs:
        returns.append(current / previous - _ONE)
        previous = current
    return tuple(returns)


def _metrics(
    navs: tuple[Decimal, ...],
    daily_returns: tuple[Decimal, ...],
    initial_nav: Decimal,
    annualization_trading_days: int,
    context: Context,
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    observation_count = len(daily_returns)
    final_growth = navs[-1] / initial_nav
    total_return = final_growth - _ONE
    annualized_return = (
        context.power(
            final_growth,
            Decimal(annualization_trading_days) / Decimal(observation_count),
        )
        - _ONE
    )
    if observation_count < 2:
        annualized_volatility = _ZERO
    else:
        mean = sum(daily_returns, _ZERO) / Decimal(observation_count)
        sample_variance = sum(((value - mean) ** 2 for value in daily_returns), _ZERO) / Decimal(
            observation_count - 1
        )
        annualized_volatility = context.sqrt(sample_variance) * context.sqrt(
            Decimal(annualization_trading_days)
        )
    running_peak = initial_nav
    max_drawdown = _ZERO
    for nav in navs:
        running_peak = max(running_peak, nav)
        max_drawdown = min(max_drawdown, nav / running_peak - _ONE)
    return total_return, annualized_return, annualized_volatility, max_drawdown


__all__ = ["run_allocation_backtest"]
