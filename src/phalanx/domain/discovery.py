"""Provider-neutral candidate records; no account or manual-universe model dependency."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, model_validator


class Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Market(StrEnum):
    KOSPI = "KOSPI"
    KOSDAQ = "KOSDAQ"


class Eligibility(StrEnum):
    ELIGIBLE = "eligible"
    EXCLUDED = "excluded"
    UNKNOWN = "unknown"


class Reason(Model):
    code: str
    description: str
    kind: Literal["pass", "exclude", "unknown", "evidence"]
    field: str | None = None


class Candidate(Model):
    market: Market
    line_number: int = Field(ge=1)
    short_code: str | None
    standard_code: str | None
    name: str | None
    # The master has no issuer identifier. grp_code is a business-group code.
    issuer_id: None = None
    security_group: str | None
    preferred_class: str | None
    etp_class: str | None
    spac: StrictBool | None
    trading_halted: StrictBool | None
    liquidation_trading: StrictBool | None
    managed: StrictBool | None
    raw_fields: dict[str, str]


class Decision(Model):
    policy_version: str
    status: Eligibility
    reasons: tuple[Reason, ...]

    @model_validator(mode="after")
    def _consistent_status(self) -> Self:
        # Evidence can accompany any outcome; it cannot by itself authorize eligibility.
        kinds = {reason.kind for reason in self.reasons} - {"evidence"}
        expected = (
            Eligibility.EXCLUDED
            if "exclude" in kinds
            else Eligibility.UNKNOWN
            if "unknown" in kinds
            else Eligibility.ELIGIBLE
        )
        if not kinds or self.status != expected or ("pass" in kinds and len(kinds) > 1):
            raise ValueError("decision reasons and status disagree")
        return self


class CandidateResult(Model):
    record: Candidate
    decision: Decision


class ParseIssue(Model):
    code: str
    description: str
    line_number: int | None = None


class ParsedMaster(Model):
    total_lines: int
    records: tuple[Candidate, ...]
    issues: tuple[ParseIssue, ...]


class SourceFile(Model):
    filename: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0, strict=True)


class MarketSnapshot(Model):
    provider: str
    market: Market
    source_url: str
    collection_started_at: AwareDatetime
    collection_completed_at: AwareDatetime
    provider_as_of: AwareDatetime | None = None
    http_last_modified: str | None = None
    schema_version: str
    parser_version: str
    policy_version: str
    download_status: Literal["success", "failed"]
    parse_status: Literal["success", "failed", "conflict", "not_attempted"]
    # Successful processing is never a guarantee of provider market coverage.
    market_completeness: Literal["unverified"] = "unverified"
    total_records: int = Field(default=0, ge=0, strict=True)
    issues: tuple[ParseIssue, ...] = ()
    sources: tuple[SourceFile, ...] = ()
    candidates: tuple[CandidateResult, ...] = ()

    @model_validator(mode="after")
    def _consistent_processing(self) -> Self:
        if self.collection_completed_at < self.collection_started_at:
            raise ValueError("collection timestamps are reversed")
        if self.parse_status == "success" and (
            self.download_status != "success"
            or self.issues
            or not self.candidates
            or self.total_records != len(self.candidates)
        ):
            raise ValueError("successful parsing requires every nonempty record")
        if self.total_records < len(self.candidates):
            raise ValueError("normalized record count exceeds source count")
        if any(
            c.record.market != self.market or c.decision.policy_version != self.policy_version
            for c in self.candidates
        ):
            raise ValueError("candidate market or policy does not match its snapshot")
        return self

    @property
    def successful(self) -> bool:
        return self.download_status == "success" and self.parse_status == "success"

    @property
    def counts(self) -> dict[str, int]:
        return {
            status.value: sum(c.decision.status == status for c in self.candidates)
            for status in Eligibility
        }


class Snapshot(Model):
    run_id: str
    collection_started_at: AwareDatetime
    collection_completed_at: AwareDatetime
    markets: tuple[MarketSnapshot, ...]

    @model_validator(mode="after")
    def _both_markets(self) -> Self:
        if len(self.markets) != 2 or {m.market for m in self.markets} != set(Market):
            raise ValueError("snapshot must record each supported market exactly once")
        if self.collection_completed_at < self.collection_started_at:
            raise ValueError("collection timestamps are reversed")
        return self

    @property
    def status(self) -> str:
        successful = sum(m.successful for m in self.markets)
        if successful == 2 and {m.market for m in self.markets} == set(Market):
            return "success"
        return "partial" if successful else "failed"


class Attempt(Model):
    run_id: str
    started_at: AwareDatetime
    completed_at: AwareDatetime | None
    status: Literal["in_progress", "success", "partial", "failed", "storage_failed"]


class DiscoveryView(Model):
    latest_attempt: Attempt | None
    latest_snapshot: Snapshot | None = None
    snapshot: Snapshot | None

    @property
    def degraded(self) -> bool:
        return self.latest_attempt is not None and self.latest_attempt.status != "success"
