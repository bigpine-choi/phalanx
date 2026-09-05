"""Immutable inputs and calculation evidence for whole-account performance."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from phalanx.domain.account import DecimalValue


def _require_confirmed(value: Any) -> Any:
    if value is not True:
        raise ValueError("사용자 선언은 명시적인 true여야 합니다.")
    return value


def _require_instant(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            raise ValueError("시각은 timezone-aware ISO-8601 형식이어야 합니다.") from None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("시각은 timezone-aware ISO-8601 형식이어야 합니다.")
    try:
        value.astimezone(UTC)
    except OverflowError:
        raise ValueError("시각이 UTC로 변환 가능한 날짜 범위를 벗어났습니다.") from None
    return value


def _require_cash_flow_amount(value: Any) -> Decimal:
    if not isinstance(value, str) or re.fullmatch(r"[+-]?[0-9]+(?:\.[0-9]+)?", value) is None:
        raise ValueError("입출금 금액은 지수 표기 없는 십진 문자열이어야 합니다.")
    amount = Decimal(value)
    if not amount.is_finite() or amount.is_zero():
        raise ValueError("입출금 금액은 0이 아닌 유한한 금액이어야 합니다.")
    return amount


Confirmed = Annotated[Literal[True], BeforeValidator(_require_confirmed)]
ObservedInstant = Annotated[datetime, BeforeValidator(_require_instant)]
CashFlowAmount = Annotated[DecimalValue, BeforeValidator(_require_cash_flow_amount)]


class _FrozenPerformanceModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CashFlowEvent(_FrozenPerformanceModel):
    """One external cash movement, with deposits positive and withdrawals negative."""

    event_id: Annotated[
        str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=200)
    ]
    occurred_at: ObservedInstant
    amount: CashFlowAmount


class CashFlowLedger(_FrozenPerformanceModel):
    """Explicit user declarations and a complete external cash-flow list."""

    schema_version: Literal["1"]
    coverage_start: ObservedInstant
    coverage_end: ObservedInstant
    same_account_confirmed: Confirmed
    external_flows_complete: Confirmed
    no_in_kind_transfers: Confirmed
    events: tuple[CashFlowEvent, ...]

    @model_validator(mode="after")
    def _validate_coverage_and_events(self) -> Self:
        start = self.coverage_start.astimezone(UTC)
        end = self.coverage_end.astimezone(UTC)
        if start >= end:
            raise ValueError("원장 시작시각은 종료시각보다 빨라야 합니다.")
        identifiers = [event.event_id for event in self.events]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("중복 event_id는 허용하지 않습니다.")
        # Event bounds require the snapshot query intervals: an event before
        # coverage_start may be in the first query and needs the NAV-ambiguity error.
        return self


class WeightedCashFlow(_FrozenPerformanceModel):
    """Unrounded time weight and contribution retained for reproducibility."""

    event_id: str
    occurred_at: ObservedInstant
    amount: DecimalValue
    remaining_microseconds: int = Field(ge=0)
    weight: DecimalValue
    weighted_amount: DecimalValue


class AccountPerformanceAssumptions(_FrozenPerformanceModel):
    """Declarations come from the validated ledger, never inferred from snapshots."""

    ledger_schema_version: Literal["1"]
    coverage_start: ObservedInstant
    coverage_end: ObservedInstant
    same_account_confirmed: Confirmed
    external_flows_complete: Confirmed
    no_in_kind_transfers: Confirmed
    cash_flow_source: Literal["user_provided_external_cash_flow_ledger"] = (
        "user_provided_external_cash_flow_ledger"
    )
    net_asset_source: Literal["snapshot.summary.net_assets"] = "snapshot.summary.net_assets"
    observation_time_basis: Literal["snapshot.query_completed_at"] = "snapshot.query_completed_at"
    observation_time_caveat: str = (
        "조회 완료시각을 계산용 관측시각으로 사용한 추정입니다. "
        "실제 거래소 평가시각이나 확정 종가시각을 의미하지 않습니다."
    )
    account_scope_caveat: str = "실계좌 전체의 성과이며 팔랑크스 알고리즘만의 성과가 아닙니다."
    internal_cash_flow_treatment: str = (
        "매매대금·계좌 내 배당·이자·수수료·세금은 외부 CF에서 제외하며, "
        "순자산에 반영된 비용을 다시 차감하지 않습니다."
    )
    unsupported_metrics: tuple[str, ...] = (
        "exact_twr",
        "unit_value_series",
        "annualized_return",
        "maximum_drawdown",
        "benchmark_comparison",
    )


class AccountPerformanceFormulas(_FrozenPerformanceModel):
    profit_loss: str = "E - B - sum(CF_i)"
    weight: str = "(t1 - occurred_at_i) / (t1 - t0)"
    average_invested_capital: str = "B + sum(weight_i * CF_i)"
    estimated_return: str = "profit_loss / average_invested_capital"
    time_difference_unit: Literal["integer_utc_microseconds"] = "integer_utc_microseconds"
    withdrawal_display_convention: str = "total_withdrawals is the positive absolute total"
    event_order: str = "occurred_at in UTC, then event_id"


class AccountPerformanceDecimalContext(_FrozenPerformanceModel):
    precision: int = 50
    rounding: Literal["ROUND_HALF_EVEN"] = "ROUND_HALF_EVEN"
    emin: int = -999999
    emax: int = 999999
    capitals: int = 1
    clamp: int = 0
    traps: tuple[str, ...] = (
        "InvalidOperation",
        "DivisionByZero",
        "Overflow",
        "Underflow",
        "FloatOperation",
    )
    rounding_policy: str = (
        "고정 Decimal context로 계산하며 별도 금액·수익률 반올림은 표시 단계에서만 합니다."
    )


class AccountPerformance(_FrozenPerformanceModel):
    """Whole-account Modified Dietz estimate with its calculation evidence."""

    schema_version: Literal["1"] = "1"
    method: Literal["modified_dietz"] = "modified_dietz"
    scope: Literal["whole_account"] = "whole_account"
    provider: str
    currency: str
    account_number_masked: str = Field(pattern=r"^\d{4}\*{4}-\*{2}$")
    start_observed_at: ObservedInstant
    end_observed_at: ObservedInstant
    start_query_started_at: ObservedInstant
    end_query_started_at: ObservedInstant
    beginning_net_assets: DecimalValue
    ending_net_assets: DecimalValue
    total_deposits: DecimalValue
    total_withdrawals: DecimalValue
    net_cash_flow: DecimalValue
    profit_loss: DecimalValue
    average_invested_capital: DecimalValue
    estimated_return: DecimalValue | None
    return_unavailable_reasons: tuple[str, ...]
    weighted_cash_flows: tuple[WeightedCashFlow, ...]
    period_microseconds: int = Field(gt=0)
    assumptions: AccountPerformanceAssumptions
    formulas: AccountPerformanceFormulas = Field(default_factory=AccountPerformanceFormulas)
    decimal_context: AccountPerformanceDecimalContext = Field(
        default_factory=AccountPerformanceDecimalContext
    )
