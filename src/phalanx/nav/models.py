"""Strict normalized inputs and reproducible daily valuation evidence."""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    ValidationError,
    model_validator,
)

from phalanx.domain.account import DecimalValue


class NavError(RuntimeError):
    """A safe, user-facing normalized NAV input or calculation error."""


def _date(value: Any) -> date:
    if type(value) is date:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return date.fromisoformat(value)
    raise ValueError("date must be an explicit YYYY-MM-DD calendar date")


Day = Annotated[date, BeforeValidator(_date)]
Identifier = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=200, pattern=r"^[\w.:/-]+$")
]
Text = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1)]
Environment = Literal["development", "official"]
Positive = Annotated[DecimalValue, Field(gt=0)]
NonNegative = Annotated[DecimalValue, Field(ge=0)]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AccountState(_Model):
    """Trade-date quantities and separately identified unsettled obligations, in KRW."""

    cash: DecimalValue
    positions: dict[Identifier, NonNegative]
    receivables: dict[Identifier, Positive]
    payables: dict[Identifier, Positive]

    @model_validator(mode="after")
    def _unique_obligations(self) -> Self:
        if self.receivables.keys() & self.payables.keys():
            raise ValueError("receivable and payable identifiers must be distinct")
        return self


class Inception(_Model):
    """User-selected close-of-day baseline, never inferred from runtime or observations."""

    series_id: Identifier
    environment: Environment
    inception_date: Day
    initial_state: AccountState
    cash_flow_policy: Literal["previous_close_unit_value"]
    benchmark_id: Literal["KOSPI_TR"]
    source_ref: Text
    currency: Literal["KRW"] = "KRW"


class _Revision(_Model):
    revision: int = Field(default=1, strict=True, ge=1)
    correction_reason: Text | None = None
    source_ref: Text

    @model_validator(mode="after")
    def _reason(self) -> Self:
        if self.revision > 1 and self.correction_reason is None:
            raise ValueError("a correction must preserve an explicit reason")
        return self


class LedgerEvent(_Revision):
    """One uniquely identified accrual, settlement or external cash movement."""

    event_id: Identifier
    date: Day
    sequence: int = Field(strict=True, ge=0)
    kind: Literal[
        "buy",
        "sell",
        "settle_receivable",
        "settle_payable",
        "deposit",
        "withdrawal",
        "dividend",
        "interest",
        "fee",
        "tax",
    ]
    amount: Positive
    instrument: Identifier | None = None
    quantity: Positive | None = None
    reference_id: Identifier | None = None
    void: StrictBool = False

    @model_validator(mode="after")
    def _shape(self) -> Self:
        trade = self.kind in ("buy", "sell")
        settlement = self.kind in ("settle_receivable", "settle_payable")
        if trade != (self.instrument is not None and self.quantity is not None):
            raise ValueError("trades require both instrument and quantity")
        if not trade and (self.instrument is not None or self.quantity is not None):
            raise ValueError("only trades accept instrument and quantity")
        if settlement != (self.reference_id is not None):
            raise ValueError("only settlements require reference_id")
        return self


class DailyInput(_Revision):
    """Explicit daily coverage and unadjusted holding prices plus a total-return index."""

    date: Day
    ledger_complete: StrictBool
    prices: dict[Identifier, NonNegative]
    benchmark_close: Positive | None


class InputBundle(_Model):
    schema_version: Literal["1"]
    series_id: Identifier
    environment: Environment
    inception: Inception | None = None
    events: tuple[LedgerEvent, ...] = ()
    days: tuple[DailyInput, ...] = ()

    @model_validator(mode="after")
    def _identity(self) -> Self:
        if self.inception is not None and (
            self.inception.series_id != self.series_id
            or self.inception.environment != self.environment
        ):
            raise ValueError("bundle and inception identities must match")
        if len({event.event_id for event in self.events}) != len(self.events):
            raise ValueError("duplicate event_id in one import")
        if len({day.date for day in self.days}) != len(self.days):
            raise ValueError("duplicate date in one import")
        return self


class DailyNav(_Model):
    """Confirmed values or explicit missing evidence; no synthetic zero returns."""

    date: Day
    status: Literal["confirmed", "pending"]
    reasons: tuple[str, ...] = ()
    nav: DecimalValue | None = None
    units: DecimalValue | None = None
    unit_value: DecimalValue | None = None
    daily_return: DecimalValue | None = None
    cumulative_return: DecimalValue | None = None
    drawdown: DecimalValue | None = None
    mdd: DecimalValue | None = None
    benchmark_unit_value: DecimalValue | None = None
    benchmark_daily_return: DecimalValue | None = None
    benchmark_cumulative_return: DecimalValue | None = None
    benchmark_drawdown: DecimalValue | None = None
    benchmark_mdd: DecimalValue | None = None
    excess_return: DecimalValue | None = None
    profit_loss: DecimalValue | None = None
    external_flow: DecimalValue | None = None
    state: AccountState | None = None
    calculation_version: Literal["1"] = "1"
    cash_flow_policy: Literal["previous_close_unit_value"] = "previous_close_unit_value"


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise NavError("JSON에 중복 키가 있습니다.")
        result[key] = value
    return result


def parse_bundle_bytes(payload: bytes) -> InputBundle:
    """Retain Decimal validation on Python input, rejecting binary JSON floats and duplicates."""

    try:
        return InputBundle.model_validate(json.loads(payload, object_pairs_hook=_unique_pairs))
    except (ValueError, UnicodeError, ValidationError, RecursionError):
        raise NavError(
            "정규화 원장 JSON 형식이 올바르지 않습니다. 금액은 십진 문자열을 사용하세요."
        ) from None
