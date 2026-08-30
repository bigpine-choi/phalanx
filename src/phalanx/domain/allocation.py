"""Immutable, provider-neutral allocation research domain models."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise
from typing import TypeGuard

from phalanx.portfolio.errors import (
    InvalidAlignedPricePanelError,
    InvalidAllocationBacktestConfigError,
    InvalidAllocationBacktestResultError,
    InvalidAllocationPolicyInputError,
    InvalidAllocationRebalanceError,
    InvalidAllocationResearchTrialError,
    InvalidAllocationTargetError,
)

_STOCK_CODE_PATTERN = re.compile(r"^[0-9]{6}$")
_TRIAL_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")
ALLOCATION_RESEARCH_SCOPE = "현재 유니버스 조건부 allocation-only 연구"


class AllocationTrialStatus(StrEnum):
    """Overall research trial completion state."""

    SUCCEEDED = "succeeded"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"


class AllocationPolicyOutcomeStatus(StrEnum):
    """One allocation policy's completion state."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class AlignedPricePanel:
    """Adjusted open and close prices aligned to common dates and stock order."""

    stock_codes: tuple[str, ...]
    dates: tuple[date, ...]
    open_prices: tuple[tuple[Decimal, ...], ...]
    close_prices: tuple[tuple[Decimal, ...], ...]

    def __post_init__(self) -> None:
        _require_tuple(self.stock_codes, InvalidAlignedPricePanelError, "stock_codes")
        _require_tuple(self.dates, InvalidAlignedPricePanelError, "dates")
        _require_tuple(self.open_prices, InvalidAlignedPricePanelError, "open_prices")
        _require_tuple(self.close_prices, InvalidAlignedPricePanelError, "close_prices")
        _validate_stock_codes(self.stock_codes, InvalidAlignedPricePanelError)
        _validate_dates(self.dates, InvalidAlignedPricePanelError, minimum=2)
        _validate_price_rows(
            self.open_prices,
            len(self.dates),
            len(self.stock_codes),
            "open_prices",
        )
        _validate_price_rows(
            self.close_prices,
            len(self.dates),
            len(self.stock_codes),
            "close_prices",
        )


@dataclass(frozen=True, slots=True)
class AllocationTarget:
    """One policy target generated after a signal-date close."""

    signal_date: date
    stock_codes: tuple[str, ...]
    target_weights: tuple[Decimal, ...]
    policy_id: str
    target_equity_weight: Decimal

    def __post_init__(self) -> None:
        if type(self.signal_date) is not date:
            raise InvalidAllocationTargetError("배분 목표 기준일은 date 값이어야 합니다.")
        _require_tuple(self.stock_codes, InvalidAllocationTargetError, "stock_codes")
        _require_tuple(self.target_weights, InvalidAllocationTargetError, "target_weights")
        _validate_stock_codes(self.stock_codes, InvalidAllocationTargetError)
        _validate_policy_id(self.policy_id, InvalidAllocationTargetError)
        _validate_equity_weight(self.target_equity_weight, InvalidAllocationTargetError)
        if len(self.target_weights) != len(self.stock_codes):
            raise InvalidAllocationTargetError("목표비중 수는 종목코드 수와 일치해야 합니다.")
        if any(not _is_finite_decimal(value) or value < 0 for value in self.target_weights):
            raise InvalidAllocationTargetError("목표비중은 0 이상의 유한한 Decimal이어야 합니다.")
        if sum(self.target_weights, Decimal(0)) != self.target_equity_weight:
            raise InvalidAllocationTargetError(
                "목표비중 합계는 목표 주식비중과 정확히 일치해야 합니다."
            )


@dataclass(frozen=True, slots=True)
class AllocationBacktestConfig:
    """Reproducible assumptions shared by every allocation policy."""

    minimum_training_returns: int = 504
    maximum_training_returns: int = 756
    rebalance_interval: int = 5
    target_equity_weight: Decimal = Decimal("0.995")
    buy_cost_rate: Decimal = Decimal("0.001")
    sell_cost_rate: Decimal = Decimal("0.0025")
    annualization_trading_days: int = 252

    def __post_init__(self) -> None:
        for name, value in (
            ("최소 학습 수익률", self.minimum_training_returns),
            ("최대 rolling 학습 수익률", self.maximum_training_returns),
            ("리밸런싱 간격", self.rebalance_interval),
            ("연환산 거래일", self.annualization_trading_days),
        ):
            if type(value) is not int or value <= 0:
                raise InvalidAllocationBacktestConfigError(f"{name}은 양의 정수여야 합니다.")
        if self.maximum_training_returns < self.minimum_training_returns:
            raise InvalidAllocationBacktestConfigError(
                "최대 rolling 학습 수익률은 최소 학습 수익률 이상이어야 합니다."
            )
        _validate_equity_weight(
            self.target_equity_weight,
            InvalidAllocationBacktestConfigError,
        )
        for name, cost_value in (
            ("매수비용률", self.buy_cost_rate),
            ("매도비용률", self.sell_cost_rate),
        ):
            if not _is_finite_decimal(cost_value) or not (Decimal(0) <= cost_value < Decimal(1)):
                raise InvalidAllocationBacktestConfigError(
                    f"{name}은 0 이상 1 미만의 유한한 Decimal이어야 합니다."
                )


@dataclass(frozen=True, slots=True)
class AllocationPolicyInput:
    """Trailing returns visible to a policy at one signal-date close only."""

    signal_date: date
    signal_number: int
    stock_codes: tuple[str, ...]
    return_dates: tuple[date, ...]
    return_values: tuple[tuple[Decimal, ...], ...]

    def __post_init__(self) -> None:
        if type(self.signal_date) is not date:
            raise InvalidAllocationPolicyInputError("정책 신호일은 date 값이어야 합니다.")
        if type(self.signal_number) is not int or self.signal_number < 0:
            raise InvalidAllocationPolicyInputError("정책 신호 번호는 0 이상의 정수여야 합니다.")
        _require_tuple(self.stock_codes, InvalidAllocationPolicyInputError, "stock_codes")
        _require_tuple(self.return_dates, InvalidAllocationPolicyInputError, "return_dates")
        _require_tuple(self.return_values, InvalidAllocationPolicyInputError, "return_values")
        _validate_stock_codes(self.stock_codes, InvalidAllocationPolicyInputError)
        _validate_dates(self.return_dates, InvalidAllocationPolicyInputError, minimum=1)
        if self.return_dates[-1] != self.signal_date:
            raise InvalidAllocationPolicyInputError(
                "정책 입력의 마지막 수익률 기준일은 신호일과 일치해야 합니다."
            )
        if len(self.return_values) != len(self.return_dates):
            raise InvalidAllocationPolicyInputError(
                "정책 수익률 행 수는 수익률 날짜 수와 일치해야 합니다."
            )
        for row in self.return_values:
            if not isinstance(row, tuple) or len(row) != len(self.stock_codes):
                raise InvalidAllocationPolicyInputError(
                    "정책 수익률 열 수는 종목코드 수와 일치해야 합니다."
                )
            if any(not _is_finite_decimal(value) or value <= Decimal(-1) for value in row):
                raise InvalidAllocationPolicyInputError(
                    "정책 수익률은 -1보다 큰 유한한 Decimal이어야 합니다."
                )


@dataclass(frozen=True, slots=True)
class AllocationRebalanceRecord:
    """One next-open execution and its self-financing cost reconciliation."""

    target: AllocationTarget
    execution_date: date
    realized_weights: tuple[Decimal, ...]
    realized_cash_weight: Decimal
    buy_gross_turnover: Decimal
    sell_gross_turnover: Decimal
    transaction_cost: Decimal
    transaction_cost_rate: Decimal
    pre_trade_nav: Decimal
    post_trade_nav: Decimal
    cash_after: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.target, AllocationTarget):
            raise InvalidAllocationRebalanceError("리밸런싱 목표는 AllocationTarget이어야 합니다.")
        if type(self.execution_date) is not date or self.execution_date <= self.target.signal_date:
            raise InvalidAllocationRebalanceError(
                "리밸런싱 체결일은 신호일 다음의 거래일이어야 합니다."
            )
        _require_tuple(
            self.realized_weights,
            InvalidAllocationRebalanceError,
            "realized_weights",
        )
        if len(self.realized_weights) != len(self.target.stock_codes):
            raise InvalidAllocationRebalanceError(
                "실현비중 수는 목표 종목코드 수와 일치해야 합니다."
            )
        if any(not _is_finite_decimal(value) or value < 0 for value in self.realized_weights):
            raise InvalidAllocationRebalanceError(
                "실현비중은 0 이상의 유한한 Decimal이어야 합니다."
            )
        if not _is_finite_decimal(self.realized_cash_weight) or self.realized_cash_weight < 0:
            raise InvalidAllocationRebalanceError(
                "실현 현금비중은 0 이상의 유한한 Decimal이어야 합니다."
            )
        if sum(self.realized_weights, Decimal(0)) + self.realized_cash_weight != Decimal(1):
            raise InvalidAllocationRebalanceError(
                "실현 주식비중과 현금비중의 합계는 1이어야 합니다."
            )
        nonnegative_values = (
            self.buy_gross_turnover,
            self.sell_gross_turnover,
            self.transaction_cost,
            self.transaction_cost_rate,
            self.cash_after,
        )
        if any(not _is_finite_decimal(value) or value < 0 for value in nonnegative_values):
            raise InvalidAllocationRebalanceError(
                "리밸런싱 회전율·비용·현금은 음수가 아닌 유한한 Decimal이어야 합니다."
            )
        if any(
            not _is_finite_decimal(value) or value <= 0
            for value in (self.pre_trade_nav, self.post_trade_nav)
        ):
            raise InvalidAllocationRebalanceError(
                "거래 전후 NAV는 양의 유한한 Decimal이어야 합니다."
            )
        if self.post_trade_nav != self.pre_trade_nav - self.transaction_cost:
            raise InvalidAllocationRebalanceError(
                "거래 후 NAV는 거래 전 NAV에서 비용을 차감한 값이어야 합니다."
            )


@dataclass(frozen=True, slots=True)
class AllocationBacktestResult:
    """One policy's cost-adjusted fractional-share walk-forward result."""

    policy_id: str
    stock_codes: tuple[str, ...]
    dates: tuple[date, ...]
    net_asset_values: tuple[Decimal, ...]
    realized_weights: tuple[tuple[Decimal, ...], ...]
    realized_cash_weights: tuple[Decimal, ...]
    rebalances: tuple[AllocationRebalanceRecord, ...]
    buy_gross_turnover: Decimal
    sell_gross_turnover: Decimal
    cumulative_transaction_cost: Decimal
    cumulative_cost_rate: Decimal
    total_return: Decimal
    annualized_return: Decimal
    annualized_volatility: Decimal
    max_drawdown: Decimal

    def __post_init__(self) -> None:
        _validate_policy_id(self.policy_id, InvalidAllocationBacktestResultError)
        _require_tuple(self.stock_codes, InvalidAllocationBacktestResultError, "stock_codes")
        _require_tuple(self.dates, InvalidAllocationBacktestResultError, "dates")
        _require_tuple(
            self.net_asset_values,
            InvalidAllocationBacktestResultError,
            "net_asset_values",
        )
        _require_tuple(
            self.realized_weights,
            InvalidAllocationBacktestResultError,
            "realized_weights",
        )
        _require_tuple(
            self.realized_cash_weights,
            InvalidAllocationBacktestResultError,
            "realized_cash_weights",
        )
        _require_tuple(self.rebalances, InvalidAllocationBacktestResultError, "rebalances")
        _validate_stock_codes(self.stock_codes, InvalidAllocationBacktestResultError)
        _validate_dates(self.dates, InvalidAllocationBacktestResultError, minimum=1)
        observation_count = len(self.dates)
        if not (
            len(self.net_asset_values)
            == len(self.realized_weights)
            == len(self.realized_cash_weights)
            == observation_count
        ):
            raise InvalidAllocationBacktestResultError(
                "일별 NAV·실현비중 길이는 평가일 길이와 일치해야 합니다."
            )
        if any(not _is_finite_decimal(value) or value <= 0 for value in self.net_asset_values):
            raise InvalidAllocationBacktestResultError(
                "일별 NAV는 양의 유한한 Decimal이어야 합니다."
            )
        for weights, cash_weight in zip(
            self.realized_weights,
            self.realized_cash_weights,
            strict=True,
        ):
            if not isinstance(weights, tuple) or len(weights) != len(self.stock_codes):
                raise InvalidAllocationBacktestResultError(
                    "일별 실현비중 열 수는 종목코드 수와 일치해야 합니다."
                )
            if any(not _is_finite_decimal(value) or value < 0 for value in weights):
                raise InvalidAllocationBacktestResultError(
                    "일별 실현 주식비중은 음수가 아닌 유한한 Decimal이어야 합니다."
                )
            if not _is_finite_decimal(cash_weight) or cash_weight < 0:
                raise InvalidAllocationBacktestResultError(
                    "일별 실현 현금비중은 음수가 아닌 유한한 Decimal이어야 합니다."
                )
            if sum(weights, Decimal(0)) + cash_weight != Decimal(1):
                raise InvalidAllocationBacktestResultError(
                    "일별 실현 주식비중과 현금비중의 합계는 1이어야 합니다."
                )
        if not self.rebalances:
            raise InvalidAllocationBacktestResultError(
                "자산배분 결과에는 최소 1회의 체결 기록이 필요합니다."
            )
        previous_execution: date | None = None
        for record in self.rebalances:
            if not isinstance(record, AllocationRebalanceRecord):
                raise InvalidAllocationBacktestResultError(
                    "rebalances는 AllocationRebalanceRecord만 포함해야 합니다."
                )
            if record.target.policy_id != self.policy_id:
                raise InvalidAllocationBacktestResultError(
                    "리밸런싱 정책 식별자는 결과 정책과 일치해야 합니다."
                )
            if record.target.stock_codes != self.stock_codes:
                raise InvalidAllocationBacktestResultError(
                    "리밸런싱 종목코드 순서는 결과 종목 순서와 일치해야 합니다."
                )
            if record.execution_date not in self.dates:
                raise InvalidAllocationBacktestResultError(
                    "리밸런싱 체결일은 평가일에 포함되어야 합니다."
                )
            if previous_execution is not None and record.execution_date <= previous_execution:
                raise InvalidAllocationBacktestResultError(
                    "리밸런싱 체결일은 엄격한 오름차순이어야 합니다."
                )
            previous_execution = record.execution_date
        aggregate_values = (
            self.buy_gross_turnover,
            self.sell_gross_turnover,
            self.cumulative_transaction_cost,
            self.cumulative_cost_rate,
            self.annualized_volatility,
        )
        if any(not _is_finite_decimal(value) or value < 0 for value in aggregate_values):
            raise InvalidAllocationBacktestResultError(
                "누적 회전율·비용·변동성은 음수가 아닌 유한한 Decimal이어야 합니다."
            )
        metrics = (self.total_return, self.annualized_return, self.max_drawdown)
        if any(not _is_finite_decimal(value) for value in metrics):
            raise InvalidAllocationBacktestResultError("성과지표는 유한한 Decimal이어야 합니다.")
        if self.max_drawdown > 0:
            raise InvalidAllocationBacktestResultError("최대 Drawdown은 0보다 클 수 없습니다.")


@dataclass(frozen=True, slots=True)
class AllocationPolicyFailure:
    """Whitelisted, secret-free failure information for one policy."""

    code: str
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not self.code or len(self.code) > 128:
            raise InvalidAllocationResearchTrialError("정책 실패 코드는 비어 있을 수 없습니다.")
        if not isinstance(self.message, str) or not self.message or len(self.message) > 500:
            raise InvalidAllocationResearchTrialError("정책 실패 메시지는 비어 있을 수 없습니다.")


@dataclass(frozen=True, slots=True)
class AllocationPolicyOutcome:
    """Success or sanitized failure for one policy in a shared trial."""

    policy_id: str
    status: AllocationPolicyOutcomeStatus
    result: AllocationBacktestResult | None = None
    failure: AllocationPolicyFailure | None = None

    def __post_init__(self) -> None:
        _validate_policy_id(self.policy_id, InvalidAllocationResearchTrialError)
        if not isinstance(self.status, AllocationPolicyOutcomeStatus):
            raise InvalidAllocationResearchTrialError("정책 결과 상태가 올바르지 않습니다.")
        if self.status is AllocationPolicyOutcomeStatus.SUCCEEDED:
            if self.result is None or self.failure is not None:
                raise InvalidAllocationResearchTrialError(
                    "성공 정책 결과에는 결과만 포함되어야 합니다."
                )
            if self.result.policy_id != self.policy_id:
                raise InvalidAllocationResearchTrialError(
                    "정책 결과 식별자가 outcome과 일치하지 않습니다."
                )
        elif self.result is not None or self.failure is None:
            raise InvalidAllocationResearchTrialError(
                "실패 정책 결과에는 정제된 실패 정보만 포함되어야 합니다."
            )


@dataclass(frozen=True, slots=True)
class AllocationResearchTrial:
    """One reproducible, current-universe-conditional allocation trial."""

    trial_id: str
    status: AllocationTrialStatus
    executed_at: datetime
    requested_start: date
    requested_end: date
    actual_evaluation_start: date | None
    actual_evaluation_end: date | None
    stock_codes: tuple[str, ...]
    config: AllocationBacktestConfig
    policy_fingerprint: str
    config_fingerprint: str
    market_data_fingerprint: str
    policy_outcomes: tuple[AllocationPolicyOutcome, ...]
    code_model_version: str
    research_scope: str = ALLOCATION_RESEARCH_SCOPE

    def __post_init__(self) -> None:
        if not isinstance(self.trial_id, str) or _TRIAL_ID_PATTERN.fullmatch(self.trial_id) is None:
            raise InvalidAllocationResearchTrialError(
                "trial ID는 경로 구분자 없는 영문자·숫자·밑줄·하이픈이어야 합니다."
            )
        if not isinstance(self.status, AllocationTrialStatus):
            raise InvalidAllocationResearchTrialError("trial 상태가 올바르지 않습니다.")
        if (
            not isinstance(self.executed_at, datetime)
            or self.executed_at.tzinfo is None
            or self.executed_at.utcoffset() is None
        ):
            raise InvalidAllocationResearchTrialError(
                "trial 실행시각은 timezone-aware datetime이어야 합니다."
            )
        if type(self.requested_start) is not date or type(self.requested_end) is not date:
            raise InvalidAllocationResearchTrialError("요청기간은 date 값이어야 합니다.")
        if self.requested_start > self.requested_end:
            raise InvalidAllocationResearchTrialError(
                "요청 시작일은 요청 종료일보다 늦을 수 없습니다."
            )
        actual_dates = (self.actual_evaluation_start, self.actual_evaluation_end)
        if (actual_dates[0] is None) != (actual_dates[1] is None):
            raise InvalidAllocationResearchTrialError(
                "실제 평가기간의 시작일과 종료일은 함께 있어야 합니다."
            )
        if actual_dates[0] is not None and actual_dates[1] is not None:
            if type(actual_dates[0]) is not date or type(actual_dates[1]) is not date:
                raise InvalidAllocationResearchTrialError("실제 평가기간은 date 값이어야 합니다.")
            if actual_dates[0] > actual_dates[1]:
                raise InvalidAllocationResearchTrialError(
                    "실제 평가 시작일은 종료일보다 늦을 수 없습니다."
                )
        _require_tuple(self.stock_codes, InvalidAllocationResearchTrialError, "stock_codes")
        if self.stock_codes:
            _validate_stock_codes(self.stock_codes, InvalidAllocationResearchTrialError)
        elif self.status is not AllocationTrialStatus.FAILED:
            raise InvalidAllocationResearchTrialError(
                "성공 또는 부분 실패 trial에는 활성 종목코드가 필요합니다."
            )
        if not isinstance(self.config, AllocationBacktestConfig):
            raise InvalidAllocationResearchTrialError(
                "trial 설정은 AllocationBacktestConfig여야 합니다."
            )
        for fingerprint in (
            self.policy_fingerprint,
            self.config_fingerprint,
            self.market_data_fingerprint,
        ):
            if (
                not isinstance(fingerprint, str)
                or _FINGERPRINT_PATTERN.fullmatch(fingerprint) is None
            ):
                raise InvalidAllocationResearchTrialError(
                    "trial fingerprint는 64자리 소문자 SHA-256이어야 합니다."
                )
        _require_tuple(
            self.policy_outcomes,
            InvalidAllocationResearchTrialError,
            "policy_outcomes",
        )
        if not self.policy_outcomes or any(
            not isinstance(outcome, AllocationPolicyOutcome) for outcome in self.policy_outcomes
        ):
            raise InvalidAllocationResearchTrialError(
                "trial에는 최소 1개의 정책 결과가 필요합니다."
            )
        policy_ids = tuple(outcome.policy_id for outcome in self.policy_outcomes)
        if len(set(policy_ids)) != len(policy_ids):
            raise InvalidAllocationResearchTrialError("trial 정책 식별자에 중복이 있습니다.")
        successful_results = tuple(
            outcome.result
            for outcome in self.policy_outcomes
            if outcome.status is AllocationPolicyOutcomeStatus.SUCCEEDED
            and outcome.result is not None
        )
        succeeded = len(successful_results)
        expected_status = (
            AllocationTrialStatus.SUCCEEDED
            if succeeded == len(self.policy_outcomes)
            else AllocationTrialStatus.FAILED
            if succeeded == 0
            else AllocationTrialStatus.PARTIAL_FAILURE
        )
        if self.status is not expected_status:
            raise InvalidAllocationResearchTrialError(
                "trial 상태가 정책별 결과 상태와 일치하지 않습니다."
            )
        if successful_results:
            if actual_dates[0] is None or actual_dates[1] is None:
                raise InvalidAllocationResearchTrialError(
                    "성공 결과가 있는 trial에는 실제 평가기간이 필요합니다."
                )
            expected_dates = successful_results[0].dates
            if any(result.stock_codes != self.stock_codes for result in successful_results):
                raise InvalidAllocationResearchTrialError(
                    "성공 정책 결과의 종목 순서는 trial 활성 종목 순서와 일치해야 합니다."
                )
            if any(result.dates != expected_dates for result in successful_results):
                raise InvalidAllocationResearchTrialError(
                    "성공 정책 결과의 실제 평가일은 모두 동일해야 합니다."
                )
            if actual_dates != (expected_dates[0], expected_dates[-1]):
                raise InvalidAllocationResearchTrialError(
                    "trial 실제 평가기간은 성공 정책 결과 날짜 범위와 일치해야 합니다."
                )
            if not (
                self.requested_start <= expected_dates[0]
                and expected_dates[-1] <= self.requested_end
            ):
                raise InvalidAllocationResearchTrialError(
                    "실제 평가기간은 요청기간 안에 있어야 합니다."
                )
        elif actual_dates != (None, None):
            raise InvalidAllocationResearchTrialError(
                "성공 결과가 없는 trial에는 실제 평가기간을 둘 수 없습니다."
            )
        if not isinstance(self.code_model_version, str) or not self.code_model_version.strip():
            raise InvalidAllocationResearchTrialError("코드 모델 버전은 비어 있을 수 없습니다.")
        if self.research_scope != ALLOCATION_RESEARCH_SCOPE:
            raise InvalidAllocationResearchTrialError(
                "trial은 현재 유니버스 조건부 allocation-only 연구로 표시되어야 합니다."
            )


def _is_finite_decimal(value: object) -> TypeGuard[Decimal]:
    return isinstance(value, Decimal) and value.is_finite()


def _require_tuple(value: object, error_type: type[Exception], field_name: str) -> None:
    if not isinstance(value, tuple):
        raise error_type(f"{field_name}는 tuple이어야 합니다.")


def _validate_stock_codes(stock_codes: tuple[str, ...], error_type: type[Exception]) -> None:
    if not stock_codes:
        raise error_type("자산배분 연구에는 최소 1개의 종목코드가 필요합니다.")
    if any(
        not isinstance(stock_code, str) or _STOCK_CODE_PATTERN.fullmatch(stock_code) is None
        for stock_code in stock_codes
    ):
        raise error_type("종목코드는 공백 없는 6자리 숫자여야 합니다.")
    if len(set(stock_codes)) != len(stock_codes):
        raise error_type("자산배분 종목코드에 중복이 있습니다.")


def _validate_dates(
    dates: tuple[date, ...],
    error_type: type[Exception],
    *,
    minimum: int,
) -> None:
    if len(dates) < minimum:
        raise error_type(f"날짜 관측치는 최소 {minimum}개가 필요합니다.")
    if any(type(value) is not date for value in dates):
        raise error_type("날짜는 date 값이어야 합니다.")
    if len(set(dates)) != len(dates):
        raise error_type("날짜에 중복이 있습니다.")
    if any(current <= previous for previous, current in pairwise(dates)):
        raise error_type("날짜는 엄격한 오름차순이어야 합니다.")


def _validate_price_rows(
    rows: tuple[tuple[Decimal, ...], ...],
    date_count: int,
    stock_count: int,
    field_name: str,
) -> None:
    if len(rows) != date_count:
        raise InvalidAlignedPricePanelError(f"{field_name} 행 수는 dates 길이와 일치해야 합니다.")
    for row in rows:
        if not isinstance(row, tuple) or len(row) != stock_count:
            raise InvalidAlignedPricePanelError(
                f"{field_name} 열 수는 stock_codes 길이와 일치해야 합니다."
            )
        if any(not _is_finite_decimal(value) or value <= 0 for value in row):
            raise InvalidAlignedPricePanelError(
                f"{field_name}는 양의 유한한 Decimal만 포함해야 합니다."
            )


def _validate_policy_id(policy_id: object, error_type: type[Exception]) -> None:
    if (
        not isinstance(policy_id, str)
        or not policy_id.strip()
        or policy_id != policy_id.strip()
        or len(policy_id) > 128
    ):
        raise error_type("정책 식별자는 공백 없는 비어 있지 않은 문자열이어야 합니다.")


def _validate_equity_weight(value: object, error_type: type[Exception]) -> None:
    if not _is_finite_decimal(value) or not Decimal(0) < value <= Decimal(1):
        raise error_type("목표 주식비중은 0 초과 1 이하의 유한한 Decimal이어야 합니다.")


__all__ = [
    "ALLOCATION_RESEARCH_SCOPE",
    "AlignedPricePanel",
    "AllocationBacktestConfig",
    "AllocationBacktestResult",
    "AllocationPolicyFailure",
    "AllocationPolicyInput",
    "AllocationPolicyOutcome",
    "AllocationPolicyOutcomeStatus",
    "AllocationRebalanceRecord",
    "AllocationResearchTrial",
    "AllocationTarget",
    "AllocationTrialStatus",
]
