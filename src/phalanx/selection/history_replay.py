"""Re-run selection from one immutable local history receipt.

Fetch completion is a useful negative look-ahead check. It is not the vendor's
historical publication time, nor proof of when the SQLite commit was visible.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from phalanx.domain.candidate_selection import CandidateSelection, SelectionPolicy
from phalanx.domain.market_data import DailyBar
from phalanx.domain.price_features import CandidatePriceFeatures
from phalanx.domain.price_history import HistoryJob, SymbolHistory, SymbolStatus, price_data_hash
from phalanx.market_data.features.calculation import calculate_price_features
from phalanx.market_data.history.reader import HistoryReader
from phalanx.portfolio.private_json_storage import (
    PrivateJsonAlreadyExistsError,
    PrivateJsonStorageError,
    store_private_json_bytes,
)
from phalanx.selection.engine import select_candidates

_MARKET_TIMEZONE = timezone(timedelta(hours=9))
MAX_REPLAY_TARGETS = 25


class HistoryReplayError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__("일봉 수집 기록과 판단 시각을 확인해 주세요.")
        self.code = code


class ConsumedRowReceipt(BaseModel):
    """One consumed bar and the completion time of its whole-symbol fetch."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    stock_code: str
    trade_date: date
    row_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    history_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fetch_completed_at: AwareDatetime
    attempt_number: int = Field(ge=1)


def _row_hash(bar: DailyBar) -> str:
    encoded = json.dumps(
        bar.model_dump(mode="json"), sort_keys=True, ensure_ascii=True, separators=(",", ":")
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _receipt_bytes(rows: tuple[ConsumedRowReceipt, ...]) -> bytes:
    return json.dumps(
        [row.model_dump(mode="json") for row in rows],
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")


class HistoryReplayResult(BaseModel):
    """Recalculated features and selection with their local fetch receipts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"
    history_job_id: str
    as_of: date
    decision_at: AwareDatetime
    replayed_at: AwareDatetime
    features: CandidatePriceFeatures
    features_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection: CandidateSelection
    rows: tuple[ConsumedRowReceipt, ...]
    row_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_check: Literal["local_fetch_completed_before_decision"] = (
        "local_fetch_completed_before_decision"
    )
    history_results_rehashed_during_replay: Literal[True] = True
    database_commit_before_decision_verified: Literal[False] = False
    vendor_release_time_verified: Literal[False] = False
    vendor_revision_id_available: Literal[False] = False
    point_in_time_backtest_guaranteed: Literal[False] = False

    @model_validator(mode="after")
    def _coherent_hashes(self) -> Self:
        if (
            self.features.history_job_id != self.history_job_id
            or self.features.as_of != self.as_of
            or self.features.calculated_at != self.replayed_at
            or self.selection.evaluated_at != self.replayed_at
            or self.selection.source.input_sha256 != self.features_sha256
            or self.features_sha256 != hashlib.sha256(self.features.to_json_bytes()).hexdigest()
            or self.row_evidence_sha256 != hashlib.sha256(_receipt_bytes(self.rows)).hexdigest()
        ):
            raise ValueError("history replay hashes or source identity disagree")
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


def utc_now() -> datetime:
    return datetime.now(UTC)


class HistoryReplayService:
    def __init__(self, *, clock: Callable[[], datetime] = utc_now) -> None:
        self._clock = clock

    def run(
        self,
        reader: HistoryReader,
        job_id: str,
        as_of: date,
        decision_at: datetime,
        policy: SelectionPolicy,
        *,
        codes: tuple[str, ...] = (),
        all_targets: bool = False,
    ) -> HistoryReplayResult:
        calculated_at = self._clock()
        if len(codes) > MAX_REPLAY_TARGETS:
            raise HistoryReplayError("TOO_MANY_TARGETS")
        if (
            type(as_of) is not date
            or decision_at.tzinfo is None
            or decision_at.utcoffset() is None
            or calculated_at.tzinfo is None
            or calculated_at.utcoffset() is None
        ):
            raise HistoryReplayError("INVALID_DECISION_TIME")
        try:
            decision_date = decision_at.astimezone(_MARKET_TIMEZONE).date()
            decision_after_replay = decision_at > calculated_at
        except (OverflowError, ValueError):
            raise HistoryReplayError("INVALID_DECISION_TIME") from None
        if decision_after_replay or as_of > decision_date:
            raise HistoryReplayError("INVALID_DECISION_TIME")
        job, states = reader.read_selected(job_id, codes=codes, all_targets=all_targets)
        if job.job_id != job_id or not states:
            raise HistoryReplayError("INCONSISTENT_HISTORY")
        if len(states) > MAX_REPLAY_TARGETS:
            raise HistoryReplayError("TOO_MANY_TARGETS")
        if len({state.ordinal for state in states}) != len(states):
            raise HistoryReplayError("INCONSISTENT_HISTORY")
        if not job.discovery_started_at <= job.discovery_completed_at <= job.created_at:
            raise HistoryReplayError("INCONSISTENT_HISTORY")
        if job.created_at > decision_at or job.discovery_completed_at > decision_at:
            raise HistoryReplayError("JOB_AFTER_DECISION")
        if not job.start <= as_of <= job.end:
            raise HistoryReplayError("INVALID_AS_OF")
        receipts: dict[int, tuple[datetime, int]] = {}
        for state in states:
            receipts[state.ordinal] = self._validate_receipt(job, state, decision_at)
        features = calculate_price_features(
            job, states, as_of=as_of, calculated_at=calculated_at
        )
        rows: list[ConsumedRowReceipt] = []
        for state, symbol in zip(states, features.symbols, strict=True):
            result = state.result
            assert result is not None
            eligible = tuple(bar for bar in result.bars if bar.trade_date <= as_of)
            count = symbol.used_observation_count
            used = eligible[-count:] if count else ()
            if (
                count != min(len(eligible), 253)
                or (used[0].trade_date if used else None) != symbol.used_start
                or (used[-1].trade_date if used else None) != symbol.used_end
                or symbol.source_price_sha256 != result.sha256
            ):
                raise HistoryReplayError("INCONSISTENT_HISTORY")
            finished_at, attempt_number = receipts[state.ordinal]
            rows.extend(
                ConsumedRowReceipt(
                    stock_code=bar.stock_code,
                    trade_date=bar.trade_date,
                    row_sha256=_row_hash(bar),
                    history_result_sha256=result.sha256,
                    fetch_completed_at=finished_at,
                    attempt_number=attempt_number,
                )
                for bar in used
            )
        feature_bytes = features.to_json_bytes()
        features_sha256 = hashlib.sha256(feature_bytes).hexdigest()
        selection = select_candidates(
            features, policy, input_sha256=features_sha256, evaluated_at=calculated_at
        )
        row_receipts = tuple(rows)
        return HistoryReplayResult(
            history_job_id=job_id,
            as_of=as_of,
            decision_at=decision_at,
            replayed_at=calculated_at,
            features=features,
            features_sha256=features_sha256,
            selection=selection,
            rows=row_receipts,
            row_evidence_sha256=hashlib.sha256(_receipt_bytes(row_receipts)).hexdigest(),
        )

    @staticmethod
    def export(result: HistoryReplayResult, output: Path) -> Path:
        payload = result.to_json_bytes()
        if sys.platform == "win32":
            from phalanx.platforms.windows_files import (
                ensure_private_directory,
                store_private_bytes,
            )

            try:
                ensure_private_directory(output.parent)
                return store_private_bytes(output, payload)
            except FileExistsError:
                raise PrivateJsonAlreadyExistsError("private JSON output already exists") from None
            except OSError:
                raise PrivateJsonStorageError("private JSON atomic write failed") from None
        return store_private_json_bytes(output, payload)

    @staticmethod
    def _validate_receipt(
        job: HistoryJob, state: SymbolHistory, decision_at: datetime
    ) -> tuple[datetime, int]:
        if (
            state.ordinal < 0
            or state.ordinal >= len(job.targets)
            or state.status not in (SymbolStatus.COMPLETED, SymbolStatus.EMPTY)
            or state.result is None
            or not state.attempts
        ):
            raise HistoryReplayError("MISSING_FETCH_RECEIPT")
        attempt = state.attempts[-1]
        expected_outcome = "completed" if state.status == SymbolStatus.COMPLETED else "empty"
        if (
            attempt.outcome != expected_outcome
            or attempt.finished_at is None
            or attempt.started_at < job.created_at
            or attempt.started_at > attempt.finished_at
        ):
            raise HistoryReplayError("MISSING_FETCH_RECEIPT")
        if attempt.finished_at > decision_at:
            raise HistoryReplayError("FETCH_AFTER_DECISION")
        result = state.result
        try:
            fetch_date = attempt.finished_at.astimezone(_MARKET_TIMEZONE).date()
        except (OverflowError, ValueError):
            raise HistoryReplayError("INCONSISTENT_HISTORY") from None
        if (
            result.sha256 != price_data_hash(result.bars)
            or any(
                bar.stock_code != job.targets[state.ordinal].short_code
                or not job.start <= bar.trade_date <= job.end
                or bar.trade_date > fetch_date
                for bar in result.bars
            )
        ):
            raise HistoryReplayError("INCONSISTENT_HISTORY")
        return attempt.finished_at, attempt.number
