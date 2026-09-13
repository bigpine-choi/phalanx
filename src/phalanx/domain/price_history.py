"""Immutable job inputs, symbol attempts and exact adjusted daily-price results."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from enum import StrEnum
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from phalanx.domain.discovery import Market, SourceFile
from phalanx.domain.market_data import DailyBar


class Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SymbolStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    EMPTY = "empty"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


class HistoryTarget(Model):
    market: Market
    short_code: str | None
    standard_code: str | None
    name: str | None
    policy_version: str
    source_files: tuple[SourceFile, ...]


class HistoryJob(Model):
    job_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    created_at: AwareDatetime
    discovery_run_id: str
    discovery_started_at: AwareDatetime
    discovery_completed_at: AwareDatetime
    start: date
    end: date
    targets: tuple[HistoryTarget, ...]
    schema_version: Literal["1"] = "1"
    collection_contract: Literal["whole_symbol_range_v1"] = "whole_symbol_range_v1"
    provider: Literal["KIS"] = "KIS"
    api_path: Literal["/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"] = (
        "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
    )
    transaction_id: Literal["FHKST03010100"] = "FHKST03010100"
    market_division: Literal["J"] = "J"
    period_division: Literal["D"] = "D"
    adjustment: Literal["0"] = "0"

    @model_validator(mode="after")
    def _valid_inputs(self) -> Self:
        if self.start > self.end or not self.targets:
            raise ValueError("a job needs an ordered date range and targets")
        codes = [t.short_code for t in self.targets if t.short_code is not None]
        if len(set(codes)) != len(codes):
            raise ValueError("ambiguous duplicate target codes")
        return self


class HistoryAttempt(Model):
    number: int = Field(ge=1)
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    # Recovery detection is not an invented process termination timestamp.
    recovered_at: AwareDatetime | None = None
    outcome: Literal["in_progress", "completed", "empty", "failed", "interrupted"]
    error_code: str | None = None
    error_message: str | None = None


def price_data_hash(bars: tuple[DailyBar, ...]) -> str:
    payload = json.dumps(
        [bar.model_dump(mode="json") for bar in bars],
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


class HistoryResult(Model):
    bars: tuple[DailyBar, ...]
    row_count: int = Field(ge=0)
    first_trade_date: date | None
    last_trade_date: date | None
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    api_query: Literal["completed"] = "completed"
    trading_day_completeness: Literal["unverified"] = "unverified"

    @model_validator(mode="after")
    def _coherent_result(self) -> Self:
        dates = [bar.trade_date for bar in self.bars]
        if (
            dates != sorted(set(dates))
            or self.row_count != len(self.bars)
            or self.first_trade_date != (dates[0] if dates else None)
            or self.last_trade_date != (dates[-1] if dates else None)
            or self.sha256 != price_data_hash(self.bars)
        ):
            raise ValueError("invalid stored price result or hash")
        return self


class SymbolHistory(Model):
    ordinal: int = Field(ge=0)
    status: SymbolStatus
    attempts: tuple[HistoryAttempt, ...] = ()
    result: HistoryResult | None = None
    error_code: str | None = None
    error_message: str | None = None

    @model_validator(mode="after")
    def _coherent_state(self) -> Self:
        done = self.status in (SymbolStatus.COMPLETED, SymbolStatus.EMPTY)
        if done != (self.result is not None):
            raise ValueError("result and completion status disagree")
        if self.result is not None and (self.status == SymbolStatus.EMPTY) != (
            not self.result.bars
        ):
            raise ValueError("empty and nonempty results have distinct statuses")
        if [a.number for a in self.attempts] != list(range(1, len(self.attempts) + 1)):
            raise ValueError("attempt numbers must be contiguous")
        if self.status == SymbolStatus.IN_PROGRESS and (
            not self.attempts or self.attempts[-1].outcome != "in_progress"
        ):
            raise ValueError("in-progress state requires an open attempt")
        return self


class HistoryView(Model):
    job: HistoryJob
    symbols: tuple[SymbolHistory, ...]

    @model_validator(mode="after")
    def _ordered_symbols(self) -> Self:
        if [s.ordinal for s in self.symbols] != list(range(len(self.job.targets))):
            raise ValueError("symbol states must match the frozen target order")
        for target, symbol in zip(self.job.targets, self.symbols, strict=True):
            if symbol.result is not None and any(
                b.stock_code != target.short_code
                or not self.job.start <= b.trade_date <= self.job.end
                for b in symbol.result.bars
            ):
                raise ValueError("stored bars disagree with the frozen request")
        return self

    @property
    def counts(self) -> dict[str, int]:
        return {s.value: sum(row.status == s for row in self.symbols) for s in SymbolStatus}

    @property
    def complete(self) -> bool:
        return all(s.status in (SymbolStatus.COMPLETED, SymbolStatus.EMPTY) for s in self.symbols)
