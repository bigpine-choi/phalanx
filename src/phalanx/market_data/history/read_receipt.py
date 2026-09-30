"""Write-once evidence that a committed history snapshot was read locally.

This is a local-clock observation, not a vendor publication timestamp or a
signature. A receipt is useful only for decisions after the recorded read.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator

from phalanx.domain.price_history import HistoryJob, SymbolHistory, SymbolStatus, price_data_hash
from phalanx.market_data.history.reader import HistoryReader
from phalanx.portfolio.private_json_storage import (
    PrivateJsonAlreadyExistsError,
    PrivateJsonStorageError,
    store_private_json_bytes,
)

MAX_READ_RECEIPT_TARGETS = 25
MAX_READ_RECEIPT_BYTES = 1_000_000


class HistoryReadReceiptError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__("저장 일봉 읽기 기록과 입력을 확인해 주세요.")
        self.code = code


class SymbolReadReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ordinal: int = Field(ge=0)
    stock_code: str
    status: Literal["completed", "empty"]
    attempt_number: int = Field(ge=1)
    fetch_completed_at: AwareDatetime
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class HistoryReadReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"]
    history_job_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    job_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    read_started_at: AwareDatetime
    read_completed_at: AwareDatetime
    symbols: tuple[SymbolReadReceipt, ...] = Field(min_length=1, max_length=25)
    evidence_basis: Literal["local_committed_snapshot_read"]
    trusted_timestamp_verified: Literal[False]

    @model_validator(mode="after")
    def _coherent_read(self) -> Self:
        try:
            reversed_time = self.read_started_at > self.read_completed_at
            late_fetch = any(
                symbol.fetch_completed_at > self.read_started_at for symbol in self.symbols
            )
        except OverflowError:
            raise ValueError("receipt times cannot be compared") from None
        if reversed_time or len({symbol.ordinal for symbol in self.symbols}) != len(
            self.symbols
        ) or len({symbol.stock_code for symbol in self.symbols}) != len(self.symbols):
            raise ValueError("read time or selected symbol identity is inconsistent")
        if late_fetch:
            raise ValueError("fetch must precede committed snapshot read")
        return self

    def to_json_bytes(self) -> bytes:
        return (
            json.dumps(
                self.model_dump(mode="json"),
                sort_keys=True,
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")


def _canonical_hash(model: BaseModel) -> str:
    payload = json.dumps(
        model.model_dump(mode="json"),
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate receipt key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("nonfinite JSON number")


def parse_read_receipt(payload: bytes) -> HistoryReadReceipt:
    try:
        raw = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
        if not isinstance(raw, dict):
            raise ValueError("receipt must be an object")
        return HistoryReadReceipt.model_validate(raw)
    except (ValueError, ValidationError, UnicodeError, RecursionError, OverflowError):
        raise HistoryReadReceiptError("INVALID_RECEIPT") from None


def _validated_symbol(
    job: HistoryJob, state: SymbolHistory, *, read_started_at: datetime
) -> SymbolReadReceipt:
    if (
        state.ordinal < 0
        or state.ordinal >= len(job.targets)
        or state.status not in (SymbolStatus.COMPLETED, SymbolStatus.EMPTY)
        or state.result is None
        or not state.attempts
    ):
        raise HistoryReadReceiptError("MISSING_FETCH_RECEIPT")
    attempt = state.attempts[-1]
    expected: Literal["completed", "empty"] = (
        "completed" if state.status == SymbolStatus.COMPLETED else "empty"
    )
    if (
        attempt.outcome != expected
        or attempt.finished_at is None
        or attempt.started_at < job.created_at
        or attempt.started_at > attempt.finished_at
        or attempt.finished_at > read_started_at
    ):
        raise HistoryReadReceiptError("MISSING_FETCH_RECEIPT")
    result = state.result
    code = job.targets[state.ordinal].short_code
    if (
        code is None
        or result.sha256 != price_data_hash(result.bars)
        or any(
            bar.stock_code != code or not job.start <= bar.trade_date <= job.end
            for bar in result.bars
        )
    ):
        raise HistoryReadReceiptError("RECEIPT_MISMATCH")
    return SymbolReadReceipt(
        ordinal=state.ordinal,
        stock_code=code,
        status=expected,
        attempt_number=attempt.number,
        fetch_completed_at=attempt.finished_at,
        result_sha256=result.sha256,
        state_sha256=_canonical_hash(state),
    )


def validate_read_receipt(
    receipt: HistoryReadReceipt,
    job: HistoryJob,
    states: tuple[SymbolHistory, ...],
    decision_at: datetime,
) -> None:
    if decision_at.tzinfo is None or decision_at.utcoffset() is None:
        raise HistoryReadReceiptError("INVALID_DECISION_TIME")
    try:
        read_after_decision = receipt.read_completed_at > decision_at
        job_after_read = job.created_at > receipt.read_started_at
    except OverflowError:
        raise HistoryReadReceiptError("INVALID_RECEIPT") from None
    if read_after_decision:
        raise HistoryReadReceiptError("READ_AFTER_DECISION")
    if (
        receipt.history_job_id != job.job_id
        or receipt.job_sha256 != _canonical_hash(job)
        or job_after_read
        or len(states) != len(receipt.symbols)
        or len({state.ordinal for state in states}) != len(states)
    ):
        raise HistoryReadReceiptError("RECEIPT_MISMATCH")
    for state, saved in zip(states, receipt.symbols, strict=True):
        current = _validated_symbol(job, state, read_started_at=receipt.read_started_at)
        if current != saved:
            raise HistoryReadReceiptError("RECEIPT_MISMATCH")


def utc_now() -> datetime:
    return datetime.now(UTC)


class HistoryReadReceiptService:
    def __init__(self, *, clock: Callable[[], datetime] = utc_now) -> None:
        self._clock = clock

    def capture(
        self,
        reader: HistoryReader,
        job_id: str,
        *,
        codes: tuple[str, ...],
    ) -> HistoryReadReceipt:
        if not 1 <= len(codes) <= MAX_READ_RECEIPT_TARGETS or len(set(codes)) != len(codes):
            raise HistoryReadReceiptError("INVALID_SELECTION")
        started_at = self._clock()
        if started_at.tzinfo is None or started_at.utcoffset() is None:
            raise HistoryReadReceiptError("INVALID_CLOCK")
        job, states = reader.read_selected(job_id, codes=codes)
        completed_at = self._clock()
        if (
            completed_at.tzinfo is None
            or completed_at.utcoffset() is None
            or completed_at < started_at
            or job.job_id != job_id
            or len(states) != len(codes)
            or job.created_at > started_at
        ):
            raise HistoryReadReceiptError("INVALID_CLOCK")
        symbols = tuple(
            _validated_symbol(job, state, read_started_at=started_at) for state in states
        )
        if tuple(symbol.stock_code for symbol in symbols) != codes:
            raise HistoryReadReceiptError("RECEIPT_MISMATCH")
        receipt = HistoryReadReceipt(
            schema_version="1",
            history_job_id=job_id,
            job_sha256=_canonical_hash(job),
            read_started_at=started_at,
            read_completed_at=completed_at,
            symbols=symbols,
            evidence_basis="local_committed_snapshot_read",
            trusted_timestamp_verified=False,
        )
        validate_read_receipt(receipt, job, states, completed_at)
        return receipt

    @staticmethod
    def export(receipt: HistoryReadReceipt, output: Path) -> Path:
        payload = receipt.to_json_bytes()
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
        from phalanx.desktop.storage import _ensure_private_directory

        _ensure_private_directory(output.parent)
        return store_private_json_bytes(output, payload)
