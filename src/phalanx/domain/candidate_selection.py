"""Validated single-feature policy and reusable offline candidate selection evidence."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from phalanx.domain.account import DecimalValue
from phalanx.domain.price_features import MetricName, PriceFeatureMetric, PriceFeaturePolicy
from phalanx.domain.price_history import HistoryTarget, SymbolStatus

PositiveInt = Annotated[int, Field(strict=True, gt=0)]
NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]


def valid_candidate_code(code: str | None) -> bool:
    return code is not None and re.fullmatch(r"[0-9A-Z]{6}", code) is not None


class SelectionMetric(StrEnum):
    RETURN_20 = "return_20"
    RETURN_60 = "return_60"
    RETURN_120 = "return_120"
    RETURN_252 = "return_252"
    VOLATILITY_20 = "volatility_20"
    VOLATILITY_60 = "volatility_60"
    DRAWDOWN_60 = "drawdown_60"
    DRAWDOWN_252 = "drawdown_252"


@dataclass(frozen=True)
class MetricRule:
    name: MetricName
    intervals: int
    direction: Literal["descending", "ascending"]


METRIC_RULES = MappingProxyType(
    {
        SelectionMetric.RETURN_20: MetricRule("price_return", 20, "descending"),
        SelectionMetric.RETURN_60: MetricRule("price_return", 60, "descending"),
        SelectionMetric.RETURN_120: MetricRule("price_return", 120, "descending"),
        SelectionMetric.RETURN_252: MetricRule("price_return", 252, "descending"),
        SelectionMetric.VOLATILITY_20: MetricRule("annualized_volatility", 20, "ascending"),
        SelectionMetric.VOLATILITY_60: MetricRule("annualized_volatility", 60, "ascending"),
        SelectionMetric.DRAWDOWN_60: MetricRule("maximum_drawdown", 60, "descending"),
        SelectionMetric.DRAWDOWN_252: MetricRule("maximum_drawdown", 252, "descending"),
    }
)


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SelectionPolicy(_Model):
    policy_id: Literal["single_price_feature_rank_v1"] = "single_price_feature_rank_v1"
    metric: SelectionMetric
    top: PositiveInt
    max_age_days: NonNegativeInt
    tie_breaker: Literal["short_code_ascii_ascending"] = "short_code_ascii_ascending"
    rank_method: Literal["competition"] = "competition"

    @property
    def rule(self) -> MetricRule:
        return METRIC_RULES[self.metric]


class SelectionReason(_Model):
    code: str
    description: str


class CandidateEvaluation(_Model):
    ordinal: NonNegativeInt
    target: HistoryTarget
    source_status: SymbolStatus
    source_error_code: str | None
    source_error_message: str | None
    source_price_sha256: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    consumed_input_sha256: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    eligible_observation_count: NonNegativeInt
    used_observation_count: NonNegativeInt
    used_start: date | None
    used_end: date | None
    last_close: DecimalValue | None
    calendar_days_since_last_observation: NonNegativeInt | None
    selected_feature: PriceFeatureMetric
    score: DecimalValue | None
    status: Literal["selected", "not_selected", "unavailable"]
    metric_rank: PositiveInt | None
    selection_order: PositiveInt | None
    reasons: tuple[SelectionReason, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _coherent_evaluation(self) -> Self:
        if self.score != self.selected_feature.value:
            raise ValueError("score must preserve the selected feature value")
        reason_codes = [reason.code for reason in self.reasons]
        if len(set(reason_codes)) != len(reason_codes):
            raise ValueError("evaluation reasons must not be duplicated")
        if self.status == "unavailable":
            if self.metric_rank is not None or self.selection_order is not None:
                raise ValueError("unavailable candidates cannot have ranks")
            if set(reason_codes).intersection({"SELECTED_TOP_N", "OUTSIDE_TOP_N"}):
                raise ValueError("unavailable candidates require unavailability reasons")
        elif (
            self.score is None
            or not self.selected_feature.available
            or self.metric_rank is None
            or self.selection_order is None
            or self.source_status != SymbolStatus.COMPLETED
            or not valid_candidate_code(self.target.short_code)
        ):
            raise ValueError("ranked candidates require an available score and valid source")
        elif reason_codes != ["SELECTED_TOP_N" if self.status == "selected" else "OUTSIDE_TOP_N"]:
            raise ValueError("ranked candidate reasons must describe their selection status")
        return self


class SelectionSource(_Model):
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    history_job_id: str
    discovery_run_id: str
    as_of: date
    calculated_at: AwareDatetime
    feature_schema_version: Literal["1"]
    feature_policy: PriceFeaturePolicy
    features_complete: bool
    source_price_hashes_verified: Literal[False] = False


class CandidateSelection(_Model):
    schema_version: Literal["1"] = "1"
    source: SelectionSource
    policy: SelectionPolicy
    sort_direction: Literal["descending", "ascending"]
    reference_price_date: date | None
    evaluated_at: AwareDatetime
    candidates: tuple[CandidateEvaluation, ...] = Field(min_length=1)
    selected_codes: tuple[str, ...]
    requested_top: PositiveInt
    eligible_count: NonNegativeInt
    selected_count: NonNegativeInt
    not_selected_count: NonNegativeInt
    unavailable_count: NonNegativeInt
    shortfall: NonNegativeInt
    evaluation_complete: bool
    selection_filled: bool
    complete: bool
    comparison_scope: Literal["provided_features_candidates"] = "provided_features_candidates"
    trading_day_completeness: Literal["unverified"] = "unverified"
    point_in_time_backtest_guaranteed: Literal[False] = False
    price_basis: Literal["adjusted_close_price_return_excluding_dividends"] = (
        "adjusted_close_price_return_excluding_dividends"
    )

    @model_validator(mode="after")
    def _coherent_counts_and_order(self) -> Self:
        valid_codes = [
            c.target.short_code
            for c in self.candidates
            if valid_candidate_code(c.target.short_code)
        ]
        reference = max(
            (
                c.used_end
                for c in self.candidates
                if c.source_status == SymbolStatus.COMPLETED and c.used_end is not None
            ),
            default=None,
        )
        if len(set(valid_codes)) != len(valid_codes) or reference != self.reference_price_date:
            raise ValueError("candidate identifiers and the input-wide price endpoint must agree")
        for candidate in self.candidates:
            if (candidate.selected_feature.name, candidate.selected_feature.intervals) != (
                self.policy.rule.name,
                self.policy.rule.intervals,
            ):
                raise ValueError("candidate scores must use the selected policy metric")
            if candidate.status != "unavailable" and (
                candidate.used_end != reference
                or candidate.used_end is None
                or candidate.calendar_days_since_last_observation is None
                or candidate.calendar_days_since_last_observation
                != (self.source.as_of - candidate.used_end).days
                or not 0
                <= candidate.calendar_days_since_last_observation
                <= self.policy.max_age_days
            ):
                raise ValueError("ranked candidates must meet the endpoint and calendar-age policy")
        ordered = sorted(
            (c for c in self.candidates if c.selection_order is not None),
            key=lambda c: c.selection_order or 0,
        )
        selected = [c for c in ordered if c.status == "selected"]
        unavailable = sum(c.status == "unavailable" for c in self.candidates)
        if (
            len({c.ordinal for c in self.candidates}) != len(self.candidates)
            or self.sort_direction != self.policy.rule.direction
            or self.requested_top != self.policy.top
            or self.eligible_count != len(ordered)
            or self.selected_count != min(self.policy.top, len(ordered))
            or self.selected_count != len(selected)
            or self.not_selected_count != len(ordered) - len(selected)
            or self.unavailable_count != unavailable
            or self.shortfall != self.policy.top - len(selected)
            or self.evaluation_complete != (unavailable == 0)
            or self.selection_filled != (len(selected) == self.policy.top)
            or self.complete != (self.evaluation_complete and self.selection_filled)
            or self.selected_codes != tuple(c.target.short_code for c in selected)
            or [c.selection_order for c in ordered] != list(range(1, len(ordered) + 1))
        ):
            raise ValueError("selection counts, completion and ordering must agree")
        rank = 0
        for index, candidate in enumerate(ordered, 1):
            previous = ordered[index - 2] if index > 1 else None
            if previous is None or candidate.score != previous.score:
                rank = index
            if candidate.metric_rank != rank or (candidate.status == "selected") != (
                index <= self.policy.top
            ):
                raise ValueError("competition ranks and top boundary must agree")
            if previous is not None:
                assert previous.score is not None and candidate.score is not None
                if previous.score == candidate.score:
                    if (previous.target.short_code or "") >= (candidate.target.short_code or ""):
                        raise ValueError("score ties require ascending unique ASCII codes")
                elif (previous.score < candidate.score) == (self.sort_direction == "descending"):
                    raise ValueError("scores must follow policy direction")
        return self

    def to_json_bytes(self) -> bytes:
        return (
            json.dumps(
                self.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
