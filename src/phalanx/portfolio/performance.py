"""Pure Decimal historical performance analysis over aligned daily returns."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

from phalanx.domain import (
    AlignedReturnMatrix,
    HistoricalUniverseAnalysis,
    MonthlyReturn,
    PerformanceMetrics,
)
from phalanx.portfolio.errors import (
    InsufficientPerformanceObservationsError,
    InvalidPerformanceReturnError,
)

ANNUAL_TRADING_DAYS = 252
_PERFORMANCE_DECIMAL_PRECISION = 50
_ZERO = Decimal(0)
_ONE = Decimal(1)


def analyze_historical_universe(
    matrix: AlignedReturnMatrix,
) -> HistoricalUniverseAnalysis:
    """Analyze stocks and an equal-weight, non-rebalanced buy-and-hold baseline."""

    observation_count = len(matrix.dates)
    if observation_count < 2:
        raise InsufficientPerformanceObservationsError(observation_count)
    for row in matrix.values:
        if any(value <= -_ONE for value in row):
            raise InvalidPerformanceReturnError("성과 분석의 일별 수익률은 -1보다 커야 합니다.")

    calculation_context = Context(
        prec=_PERFORMANCE_DECIMAL_PRECISION,
        rounding=ROUND_HALF_EVEN,
    )
    with localcontext(calculation_context) as context:
        stock_returns = tuple(
            tuple(row[column] for row in matrix.values) for column in range(len(matrix.stock_codes))
        )
        stock_growth_factors = _stock_growth_factors(matrix.values)
        stock_metrics = tuple(
            _performance_metrics(
                returns,
                tuple(row[column] for row in stock_growth_factors),
                context,
            )
            for column, returns in enumerate(stock_returns)
        )
        baseline_growth_factors = tuple(
            sum(row, _ZERO) / Decimal(len(matrix.stock_codes)) for row in stock_growth_factors
        )
        baseline_daily_returns = _returns_from_growth(baseline_growth_factors)
        baseline_drawdowns = _drawdowns(baseline_growth_factors)
        baseline_metrics = _performance_metrics(
            baseline_daily_returns,
            baseline_growth_factors,
            context,
        )
        monthly_returns = _monthly_returns(matrix.dates, baseline_daily_returns)
        correlations = _correlation_matrix(stock_returns, context)

    return HistoricalUniverseAnalysis(
        stock_codes=matrix.stock_codes,
        dates=matrix.dates,
        stock_metrics=stock_metrics,
        baseline_metrics=baseline_metrics,
        stock_growth_factors=stock_growth_factors,
        baseline_growth_factors=baseline_growth_factors,
        baseline_daily_returns=baseline_daily_returns,
        baseline_drawdowns=baseline_drawdowns,
        monthly_baseline_returns=monthly_returns,
        correlation_matrix=correlations,
    )


def _stock_growth_factors(
    rows: tuple[tuple[Decimal, ...], ...],
) -> tuple[tuple[Decimal, ...], ...]:
    running = [_ONE] * len(rows[0])
    result: list[tuple[Decimal, ...]] = []
    for row in rows:
        running = [growth * (_ONE + value) for growth, value in zip(running, row, strict=True)]
        result.append(tuple(running))
    return tuple(result)


def _returns_from_growth(growth_factors: tuple[Decimal, ...]) -> tuple[Decimal, ...]:
    previous = _ONE
    returns: list[Decimal] = []
    for current in growth_factors:
        returns.append(current / previous - _ONE)
        previous = current
    return tuple(returns)


def _drawdowns(growth_factors: tuple[Decimal, ...]) -> tuple[Decimal, ...]:
    running_peak = _ONE
    values: list[Decimal] = []
    for growth in growth_factors:
        running_peak = max(running_peak, growth)
        values.append(growth / running_peak - _ONE)
    return tuple(values)


def _performance_metrics(
    returns: tuple[Decimal, ...],
    growth_factors: tuple[Decimal, ...],
    context: Context,
) -> PerformanceMetrics:
    count = len(returns)
    count_decimal = Decimal(count)
    mean = sum(returns, _ZERO) / count_decimal
    centered_squares = sum(((value - mean) ** 2 for value in returns), _ZERO)
    sample_variance = centered_squares / Decimal(count - 1)
    daily_standard_deviation = context.sqrt(sample_variance)
    annualization_scale = context.sqrt(Decimal(ANNUAL_TRADING_DAYS))
    annualized_volatility = daily_standard_deviation * annualization_scale
    sharpe_ratio = (
        None
        if daily_standard_deviation == 0
        else mean / daily_standard_deviation * annualization_scale
    )

    downside_variance = sum((min(value, _ZERO) ** 2 for value in returns), _ZERO) / count_decimal
    downside_deviation = context.sqrt(downside_variance)
    sortino_ratio = (
        None if downside_deviation == 0 else mean / downside_deviation * annualization_scale
    )

    final_growth = growth_factors[-1]
    total_return = final_growth - _ONE
    annualized_return = (
        context.power(
            final_growth,
            Decimal(ANNUAL_TRADING_DAYS) / count_decimal,
        )
        - _ONE
    )
    max_drawdown = min(_drawdowns(growth_factors))
    calmar_ratio = None if max_drawdown == 0 else annualized_return / abs(max_drawdown)
    positive_day_ratio = Decimal(sum(value > 0 for value in returns)) / count_decimal

    return PerformanceMetrics(
        observation_count=count,
        total_return=total_return,
        annualized_return=annualized_return,
        annualized_volatility=annualized_volatility,
        sharpe_ratio=sharpe_ratio,
        sortino_ratio=sortino_ratio,
        max_drawdown=max_drawdown,
        calmar_ratio=calmar_ratio,
        positive_day_ratio=positive_day_ratio,
        best_daily_return=max(returns),
        worst_daily_return=min(returns),
    )


def _monthly_returns(
    dates: tuple[date, ...],
    returns: tuple[Decimal, ...],
) -> tuple[MonthlyReturn, ...]:
    grouped: dict[tuple[int, int], list[Decimal]] = defaultdict(list)
    for return_date, value in zip(dates, returns, strict=True):
        grouped[(return_date.year, return_date.month)].append(value)

    monthly: list[MonthlyReturn] = []
    for (year, month), values in sorted(grouped.items()):
        growth = _ONE
        for value in values:
            growth *= _ONE + value
        monthly.append(MonthlyReturn(date(year, month, 1), growth - _ONE))
    return tuple(monthly)


def _correlation_matrix(
    columns: tuple[tuple[Decimal, ...], ...],
    context: Context,
) -> tuple[tuple[Decimal | None, ...], ...]:
    count = len(columns[0])
    divisor = Decimal(count - 1)
    means = tuple(sum(column, _ZERO) / Decimal(count) for column in columns)
    sample_variances = tuple(
        sum(((value - mean) ** 2 for value in column), _ZERO) / divisor
        for column, mean in zip(columns, means, strict=True)
    )
    result: list[list[Decimal | None]] = [[None for _ in columns] for _ in columns]
    for row_index, row_values in enumerate(columns):
        if sample_variances[row_index] == 0:
            continue
        result[row_index][row_index] = _ONE
        row_standard_deviation = context.sqrt(sample_variances[row_index])
        for column_index in range(row_index + 1, len(columns)):
            if sample_variances[column_index] == 0:
                continue
            covariance = (
                sum(
                    (
                        (row_value - means[row_index]) * (column_value - means[column_index])
                        for row_value, column_value in zip(
                            row_values,
                            columns[column_index],
                            strict=True,
                        )
                    ),
                    _ZERO,
                )
                / divisor
            )
            correlation = covariance / (
                row_standard_deviation * context.sqrt(sample_variances[column_index])
            )
            correlation = min(_ONE, max(-_ONE, correlation))
            result[row_index][column_index] = correlation
            result[column_index][row_index] = correlation
    return tuple(tuple(row) for row in result)


__all__ = ["ANNUAL_TRADING_DAYS", "analyze_historical_universe"]
