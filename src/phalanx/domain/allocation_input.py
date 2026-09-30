"""Evidence for preparing risk-model returns, without target weights or ERC claims."""

from __future__ import annotations

import json
from datetime import date
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_serializer, model_validator

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


class ReplayAllocationProvenance(_Model):
    evidence_kind: Literal["recomputed_history_replay_with_local_read_receipt_v1"] = (
        "recomputed_history_replay_with_local_read_receipt_v1"
    )
    replay_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    read_receipt_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    read_receipt_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    row_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    features_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    history_job_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    as_of: date
    selected_codes: tuple[str, ...]
    decision_at: AwareDatetime
    replayed_at: AwareDatetime
    read_completed_at: AwareDatetime
    local_snapshot_read_before_decision_confirmed: Literal[True] = True
    vendor_release_time_verified: Literal[False] = False
    point_in_time_backtest_guaranteed: Literal[False] = False

    @model_validator(mode="after")
    def _coherent_times(self) -> Self:
        try:
            coherent = self.read_completed_at <= self.decision_at <= self.replayed_at
        except OverflowError:
            coherent = False
        if not coherent:
            raise ValueError("replay provenance times are inconsistent")
        return self


class AllocationInput(_Model):
    schema_version: Literal["1"] = "1"
    input_ready: bool
    readiness_scope: Literal["risk_model_return_matrix_only"] = "risk_model_return_matrix_only"
    reasons: tuple[AllocationInputReason, ...]
    selected_codes: tuple[str, ...]
    selection_as_of: date
    reference_price_date: date | None
    selection_file_sha256: str | None
    replay_provenance: ReplayAllocationProvenance | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
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

    @model_validator(mode="after")
    def _coherent_provenance(self) -> Self:
        evidence = self.replay_provenance
        if evidence is None:
            coherent = self.selection_file_sha256 is not None
        else:
            coherent = (
                self.selection_file_sha256 is None
                and evidence.history_job_id == self.history_job_id
                and evidence.as_of == self.selection_as_of
                and evidence.selected_codes == self.selected_codes
            )
        if not coherent:
            raise ValueError("allocation input source provenance is inconsistent")
        return self

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
                self.to_json_object(),
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")

    def to_json_object(self) -> dict[str, object]:
        return self.model_dump(mode="json")
