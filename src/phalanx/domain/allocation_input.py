"""Evidence for preparing risk-model returns, without target weights or ERC claims."""

from __future__ import annotations

import json
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_serializer

from phalanx.domain.candidate_selection import CandidateSelection, SelectionPolicy, SelectionSource
from phalanx.domain.portfolio import AlignedReturnMatrix

DATE_POLICY: Literal["strict_observed_window_v1"] = "strict_observed_window_v1"


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AllocationInputReason(_Model):
    code: str
    description: str


class SelectionCompletion(_Model):
    evaluation_complete: bool
    selection_filled: bool
    complete: bool
    requested_top: int
    selected_count: int
    shortfall: int

    @classmethod
    def from_selection(cls, selection: CandidateSelection) -> SelectionCompletion:
        return cls(**{name: getattr(selection, name) for name in cls.model_fields})


class HistoryContract(_Model):
    requested_start: date
    requested_end: date
    provider: Literal["KIS"] = "KIS"
    collection_contract: Literal["whole_symbol_range_v1"] = "whole_symbol_range_v1"
    market_division: Literal["J"] = "J"
    period_division: Literal["D"] = "D"
    adjustment: Literal["0"] = "0"


class SymbolInputDiagnostics(_Model):
    code: str
    ordinal: int
    verified_source_price_sha256: str
    selection_consumed_input_sha256: str
    stored_price_count: int
    eligible_price_count: int
    first_eligible_date: date | None
    last_eligible_date: date | None
    window_price_count: int = 0
    missing_dates: tuple[date, ...] = ()


class AllocationInput(_Model):
    schema_version: Literal["1"] = "1"
    input_ready: bool
    readiness_scope: Literal["risk_model_return_matrix_only"] = "risk_model_return_matrix_only"
    reasons: tuple[AllocationInputReason, ...]
    selected_codes: tuple[str, ...]
    selection_as_of: date
    reference_price_date: date | None
    selection_file_sha256: str
    selection_source: SelectionSource
    selection_policy: SelectionPolicy
    selection_completion: SelectionCompletion
    history_job_id: str
    discovery_run_id: str
    history_contract: HistoryContract | None
    symbols: tuple[SymbolInputDiagnostics, ...]
    date_policy: Literal["strict_observed_window_v1"] = DATE_POLICY
    price_basis: Literal["adjusted_close_price_return_excluding_dividends"] = (
        "adjusted_close_price_return_excluding_dividends"
    )
    minimum_observations: int
    maximum_observations: int
    decimal_precision: Literal[50] = 50
    decimal_rounding: Literal["ROUND_HALF_EVEN"] = "ROUND_HALF_EVEN"
    inspected_price_dates: tuple[date, ...]
    used_start: date | None
    used_end: date | None
    return_observation_count: int
    return_start_dates: tuple[date, ...]
    matrix: AlignedReturnMatrix | None
    # These hashes identify the full window and the actual matrix respectively.
    # Neither is the feature policy's consumed_input_sha256.
    price_window_sha256: str | None
    calculation_fingerprint: str | None
    features_consumed_input_hashes_verified: Literal[False] = False
    trading_day_completeness: Literal["unverified"] = "unverified"
    point_in_time_backtest_guaranteed: Literal[False] = False

    @field_serializer("matrix")
    def _matrix_json(self, matrix: AlignedReturnMatrix | None) -> dict[str, object] | None:
        if matrix is None:
            return None
        return {
            "stock_codes": matrix.stock_codes,
            "dates": tuple(day.isoformat() for day in matrix.dates),
            "values": tuple(tuple(format(value, "f") for value in row) for row in matrix.values),
        }

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
