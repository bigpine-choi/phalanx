"""Exact offline candidate price features and their calculation evidence."""

from __future__ import annotations

import json
from datetime import date
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from phalanx.domain.account import DecimalValue
from phalanx.domain.price_history import HistoryTarget, SymbolStatus

type MetricName = Literal["price_return", "annualized_volatility", "maximum_drawdown"]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PriceFeaturePolicy(_Model):
    version: Literal["candidate_price_features_v1"] = "candidate_price_features_v1"
    return_intervals: tuple[Literal[20], Literal[60], Literal[120], Literal[252]] = (
        20,
        60,
        120,
        252,
    )
    volatility_intervals: tuple[Literal[20], Literal[60]] = (20, 60)
    drawdown_intervals: tuple[Literal[60], Literal[252]] = (60, 252)
    interval_basis: Literal["consecutive_observed_closes"] = "consecutive_observed_closes"
    annualization_periods: Literal[252] = 252
    annualization_formula: Literal["sample_std(simple_returns) * sqrt(252)"] = (
        "sample_std(simple_returns) * sqrt(252)"
    )
    variance_ddof: Literal[1] = 1
    decimal_precision: Literal[50] = 50
    decimal_rounding: Literal["ROUND_HALF_EVEN"] = "ROUND_HALF_EVEN"
    consumed_input_contract: Literal["dated_closes_as_of_v1"] = "dated_closes_as_of_v1"


class PriceFeatureMetric(_Model):
    name: MetricName
    intervals: int = Field(gt=0)
    required_observations: int = Field(gt=0)
    available_observations: int = Field(ge=0)
    window_start: date | None
    window_end: date | None
    value: DecimalValue | None
    available: bool
    reason_code: str | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def _coherent_availability(self) -> Self:
        if self.required_observations != self.intervals + 1:
            raise ValueError("N intervals require N+1 observed closes")
        if self.available != (self.value is not None):
            raise ValueError("available metrics require a value, including zero")
        if self.available:
            if (
                self.reason_code is not None
                or self.reason is not None
                or self.available_observations < self.required_observations
                or self.window_start is None
                or self.window_end is None
            ):
                raise ValueError("available metrics require a full window and no failure reason")
        elif not self.reason_code or not self.reason:
            raise ValueError("unavailable metrics require a specific reason")
        return self


class SymbolPriceFeatures(_Model):
    ordinal: int = Field(ge=0)
    target: HistoryTarget
    source_status: SymbolStatus
    source_error_code: str | None
    source_error_message: str | None
    source_price_sha256: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    consumed_input_sha256: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    eligible_observation_count: int = Field(ge=0)
    used_observation_count: int = Field(ge=0, le=253)
    used_start: date | None
    used_end: date | None
    last_close: DecimalValue | None
    calendar_days_since_last_observation: int | None = Field(ge=0)
    metrics: tuple[PriceFeatureMetric, ...]

    @property
    def complete(self) -> bool:
        return bool(self.metrics) and all(metric.available for metric in self.metrics)


class CandidatePriceFeatures(_Model):
    schema_version: Literal["1"] = "1"
    history_job_id: str
    discovery_run_id: str
    history_requested_start: date
    history_requested_end: date
    as_of: date
    calculated_at: AwareDatetime
    policy: PriceFeaturePolicy = Field(default_factory=PriceFeaturePolicy)
    trading_day_completeness: Literal["unverified"] = "unverified"
    price_basis: Literal["adjusted_close_price_return_excluding_dividends"] = (
        "adjusted_close_price_return_excluding_dividends"
    )
    point_in_time_backtest_guaranteed: Literal[False] = False
    symbols: tuple[SymbolPriceFeatures, ...]
    complete: bool

    @model_validator(mode="after")
    def _coherent_completion(self) -> Self:
        if not self.symbols or self.complete != all(symbol.complete for symbol in self.symbols):
            raise ValueError("completion must describe all selected symbols' metrics")
        return self

    def to_json_bytes(self) -> bytes:
        """Stable JSON with exact decimal strings, suitable for write-once storage."""
        payload = self.model_dump(mode="json")
        return (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            + "\n"
        ).encode("utf-8")
