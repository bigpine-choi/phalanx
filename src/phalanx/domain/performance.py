"""Immutable historical performance analysis models."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import pairwise

from phalanx.portfolio.errors import (
    InvalidHistoricalUniverseAnalysisError,
    InvalidPerformanceMetricsError,
)

_STOCK_CODE_PATTERN = re.compile(r"^[0-9]{6}$")


@dataclass(frozen=True, slots=True)
class PerformanceMetrics:
    """One immutable summary calculated from at least two daily returns."""

    observation_count: int
    total_return: Decimal
    annualized_return: Decimal
    annualized_volatility: Decimal
    sharpe_ratio: Decimal | None
    sortino_ratio: Decimal | None
    max_drawdown: Decimal
    calmar_ratio: Decimal | None
    positive_day_ratio: Decimal
    best_daily_return: Decimal
    worst_daily_return: Decimal

    def __post_init__(self) -> None:
        if type(self.observation_count) is not int or self.observation_count < 2:
            raise InvalidPerformanceMetricsError("성과지표 관측치 수는 2 이상의 정수여야 합니다.")
        required_values = (
            self.total_return,
            self.annualized_return,
            self.annualized_volatility,
            self.max_drawdown,
            self.positive_day_ratio,
            self.best_daily_return,
            self.worst_daily_return,
        )
        optional_values = (
            self.sharpe_ratio,
            self.sortino_ratio,
            self.calmar_ratio,
        )
        if any(not _is_finite_decimal(value) for value in required_values):
            raise InvalidPerformanceMetricsError(
                "성과지표의 필수 계산값은 유한한 Decimal이어야 합니다."
            )
        if any(value is not None and not _is_finite_decimal(value) for value in optional_values):
            raise InvalidPerformanceMetricsError(
                "성과지표의 선택 계산값은 None 또는 유한한 Decimal이어야 합니다."
            )
        if self.annualized_volatility < 0:
            raise InvalidPerformanceMetricsError("연환산변동성은 음수일 수 없습니다.")
        if not Decimal(0) <= self.positive_day_ratio <= Decimal(1):
            raise InvalidPerformanceMetricsError("상승일 비율은 0 이상 1 이하여야 합니다.")
        if self.max_drawdown > 0:
            raise InvalidPerformanceMetricsError("최대낙폭은 0보다 클 수 없습니다.")
        if self.best_daily_return < self.worst_daily_return:
            raise InvalidPerformanceMetricsError(
                "최고 일간수익률은 최악 일간수익률보다 작을 수 없습니다."
            )


@dataclass(frozen=True, slots=True)
class MonthlyReturn:
    """One compounded calendar-month baseline return."""

    month: date
    value: Decimal

    def __post_init__(self) -> None:
        if type(self.month) is not date or self.month.day != 1:
            raise InvalidHistoricalUniverseAnalysisError(
                "월별 수익률의 month는 해당 월 1일인 date여야 합니다."
            )
        if not _is_finite_decimal(self.value):
            raise InvalidHistoricalUniverseAnalysisError(
                "월별 수익률은 유한한 Decimal이어야 합니다."
            )


@dataclass(frozen=True, slots=True)
class HistoricalUniverseAnalysis:
    """Aligned stocks and an equal-weight buy-and-hold baseline analysis.

    ``stock_growth_factors`` is row-major by ``dates`` and then
    ``stock_codes``. The baseline series have one value per return date.
    """

    stock_codes: tuple[str, ...]
    dates: tuple[date, ...]
    stock_metrics: tuple[PerformanceMetrics, ...]
    baseline_metrics: PerformanceMetrics
    stock_growth_factors: tuple[tuple[Decimal, ...], ...]
    baseline_growth_factors: tuple[Decimal, ...]
    baseline_daily_returns: tuple[Decimal, ...]
    baseline_drawdowns: tuple[Decimal, ...]
    monthly_baseline_returns: tuple[MonthlyReturn, ...]
    correlation_matrix: tuple[tuple[Decimal | None, ...], ...]

    def __post_init__(self) -> None:
        _validate_tuple_fields(self)
        _validate_codes(self.stock_codes)
        _validate_dates(self.dates)
        observation_count = len(self.dates)
        stock_count = len(self.stock_codes)
        if observation_count < 2:
            raise InvalidHistoricalUniverseAnalysisError(
                "과거 성과 분석에는 최소 2개의 수익률 기준일이 필요합니다."
            )
        if len(self.stock_metrics) != stock_count:
            raise InvalidHistoricalUniverseAnalysisError(
                "종목별 성과지표 수는 stock_codes 길이와 일치해야 합니다."
            )
        if any(not isinstance(metric, PerformanceMetrics) for metric in self.stock_metrics):
            raise InvalidHistoricalUniverseAnalysisError(
                "stock_metrics는 PerformanceMetrics만 포함해야 합니다."
            )
        if not isinstance(self.baseline_metrics, PerformanceMetrics):
            raise InvalidHistoricalUniverseAnalysisError(
                "baseline_metrics는 PerformanceMetrics여야 합니다."
            )
        if any(metric.observation_count != observation_count for metric in self.stock_metrics):
            raise InvalidHistoricalUniverseAnalysisError(
                "종목별 성과지표 관측치 수는 dates 길이와 일치해야 합니다."
            )
        if self.baseline_metrics.observation_count != observation_count:
            raise InvalidHistoricalUniverseAnalysisError(
                "기준선 성과지표 관측치 수는 dates 길이와 일치해야 합니다."
            )
        _validate_stock_growth(self.stock_growth_factors, observation_count, stock_count)
        _validate_baseline_series(self, observation_count)
        _validate_monthly_returns(self.monthly_baseline_returns)
        _validate_correlations(self.correlation_matrix, stock_count)


def _is_finite_decimal(value: object) -> bool:
    return isinstance(value, Decimal) and value.is_finite()


def _validate_tuple_fields(analysis: HistoricalUniverseAnalysis) -> None:
    tuple_fields = (
        analysis.stock_codes,
        analysis.dates,
        analysis.stock_metrics,
        analysis.stock_growth_factors,
        analysis.baseline_growth_factors,
        analysis.baseline_daily_returns,
        analysis.baseline_drawdowns,
        analysis.monthly_baseline_returns,
        analysis.correlation_matrix,
    )
    if any(not isinstance(value, tuple) for value in tuple_fields):
        raise InvalidHistoricalUniverseAnalysisError(
            "과거 성과 분석의 시퀀스 필드는 모두 tuple이어야 합니다."
        )


def _validate_codes(stock_codes: tuple[str, ...]) -> None:
    if not stock_codes:
        raise InvalidHistoricalUniverseAnalysisError("과거 성과 분석에는 종목이 필요합니다.")
    if any(
        not isinstance(stock_code, str) or _STOCK_CODE_PATTERN.fullmatch(stock_code) is None
        for stock_code in stock_codes
    ):
        raise InvalidHistoricalUniverseAnalysisError(
            "stock_codes는 공백 없는 6자리 숫자여야 합니다."
        )
    if len(set(stock_codes)) != len(stock_codes):
        raise InvalidHistoricalUniverseAnalysisError("stock_codes에 중복이 있습니다.")


def _validate_dates(dates: tuple[date, ...]) -> None:
    previous: date | None = None
    seen: set[date] = set()
    for value in dates:
        if type(value) is not date:
            raise InvalidHistoricalUniverseAnalysisError("dates는 date 값이어야 합니다.")
        if value in seen:
            raise InvalidHistoricalUniverseAnalysisError("dates에 중복 날짜가 있습니다.")
        if previous is not None and value <= previous:
            raise InvalidHistoricalUniverseAnalysisError("dates는 엄격한 오름차순이어야 합니다.")
        seen.add(value)
        previous = value


def _validate_stock_growth(
    rows: tuple[tuple[Decimal, ...], ...],
    observation_count: int,
    stock_count: int,
) -> None:
    if len(rows) != observation_count:
        raise InvalidHistoricalUniverseAnalysisError(
            "종목 성장계수 행 수는 dates 길이와 일치해야 합니다."
        )
    for row in rows:
        if not isinstance(row, tuple) or len(row) != stock_count:
            raise InvalidHistoricalUniverseAnalysisError(
                "종목 성장계수 열 수는 stock_codes 길이와 일치해야 합니다."
            )
        if any(not _is_finite_decimal(value) or value <= 0 for value in row):
            raise InvalidHistoricalUniverseAnalysisError(
                "종목 성장계수는 유한한 양의 Decimal이어야 합니다."
            )


def _validate_baseline_series(
    analysis: HistoricalUniverseAnalysis,
    observation_count: int,
) -> None:
    series = (
        analysis.baseline_growth_factors,
        analysis.baseline_daily_returns,
        analysis.baseline_drawdowns,
    )
    if any(len(values) != observation_count for values in series):
        raise InvalidHistoricalUniverseAnalysisError(
            "기준선 시계열 길이는 dates 길이와 일치해야 합니다."
        )
    if any(
        not _is_finite_decimal(value) or value <= 0 for value in analysis.baseline_growth_factors
    ):
        raise InvalidHistoricalUniverseAnalysisError(
            "기준선 성장계수는 유한한 양의 Decimal이어야 합니다."
        )
    if any(
        not _is_finite_decimal(value) or value <= Decimal(-1)
        for value in analysis.baseline_daily_returns
    ):
        raise InvalidHistoricalUniverseAnalysisError(
            "기준선 일별 수익률은 -1보다 큰 유한한 Decimal이어야 합니다."
        )
    if any(not _is_finite_decimal(value) or value > 0 for value in analysis.baseline_drawdowns):
        raise InvalidHistoricalUniverseAnalysisError(
            "기준선 drawdown은 0 이하의 유한한 Decimal이어야 합니다."
        )


def _validate_monthly_returns(values: tuple[MonthlyReturn, ...]) -> None:
    if not values:
        raise InvalidHistoricalUniverseAnalysisError("월별 기준선 수익률이 비어 있습니다.")
    if any(not isinstance(value, MonthlyReturn) for value in values):
        raise InvalidHistoricalUniverseAnalysisError(
            "monthly_baseline_returns는 MonthlyReturn만 포함해야 합니다."
        )
    months = tuple(value.month for value in values)
    if len(set(months)) != len(months):
        raise InvalidHistoricalUniverseAnalysisError("월별 기준선 수익률에 중복 월이 있습니다.")
    if any(current <= previous for previous, current in pairwise(months)):
        raise InvalidHistoricalUniverseAnalysisError(
            "월별 기준선 수익률은 엄격한 오름차순이어야 합니다."
        )


def _validate_correlations(
    matrix: tuple[tuple[Decimal | None, ...], ...],
    stock_count: int,
) -> None:
    if len(matrix) != stock_count:
        raise InvalidHistoricalUniverseAnalysisError(
            "상관계수 행 수는 stock_codes 길이와 일치해야 합니다."
        )
    for row in matrix:
        if not isinstance(row, tuple) or len(row) != stock_count:
            raise InvalidHistoricalUniverseAnalysisError(
                "상관계수 열 수는 stock_codes 길이와 일치해야 합니다."
            )
        if any(
            value is not None
            and (not _is_finite_decimal(value) or not Decimal(-1) <= value <= Decimal(1))
            for value in row
        ):
            raise InvalidHistoricalUniverseAnalysisError(
                "상관계수는 None 또는 -1 이상 1 이하의 유한한 Decimal이어야 합니다."
            )
    for row_index in range(stock_count):
        diagonal = matrix[row_index][row_index]
        if diagonal is not None and diagonal != Decimal(1):
            raise InvalidHistoricalUniverseAnalysisError(
                "정의 가능한 상관계수 대각값은 1이어야 합니다."
            )
        for column_index in range(row_index + 1, stock_count):
            if matrix[row_index][column_index] != matrix[column_index][row_index]:
                raise InvalidHistoricalUniverseAnalysisError("상관계수 행렬은 대칭이어야 합니다.")


__all__ = ["HistoricalUniverseAnalysis", "MonthlyReturn", "PerformanceMetrics"]
