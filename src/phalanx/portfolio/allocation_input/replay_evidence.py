"""Verify a history replay and its read receipt against one frozen history read.

Only the selected states are passed to allocation preparation, but the replay
evidence covers every candidate. The sidecar receipt is required so its raw
file hash, as well as its embedded canonical content, can be checked.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from phalanx.domain.price_history import HistoryJob, SymbolHistory
from phalanx.market_data.history.errors import HistoryStorageError
from phalanx.market_data.history.read_receipt import (
    MAX_READ_RECEIPT_BYTES,
    parse_read_receipt,
)
from phalanx.market_data.history.reader import HistoryReader
from phalanx.portfolio.allocation_input.errors import AllocationInputError
from phalanx.portfolio.allocation_input.validation import parse_selection
from phalanx.selection.history_replay import (
    MAX_REPLAY_TARGETS,
    HistoryReplayResult,
    HistoryReplayService,
)

MAX_REPLAY_BYTES = 16_000_000
_MISMATCH_MESSAGE = "재실행 결과·읽기 영수증·저장 일봉 근거가 일치하지 않습니다."


@dataclass(frozen=True, slots=True)
class VerifiedReplay:
    replay: HistoryReplayResult
    job: HistoryJob
    selected_states: tuple[SymbolHistory, ...]
    replay_file_sha256: str
    receipt_file_sha256: str
    selection_content_sha256: str


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate replay JSON key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("nonfinite replay JSON number")


def _validate_strings(value: object) -> None:
    """The JSON decoder accepts escaped unpaired surrogates; UTF-8 does not."""
    if isinstance(value, str):
        value.encode("utf-8")
    elif isinstance(value, dict):
        for key, child in value.items():
            _validate_strings(key)
            _validate_strings(child)
    elif isinstance(value, list):
        for child in value:
            _validate_strings(child)


def _parse_replay(payload: bytes) -> HistoryReplayResult:
    if not payload or len(payload) > MAX_REPLAY_BYTES:
        raise ValueError("replay file size is invalid")
    raw = json.loads(
        payload.decode("utf-8"),
        object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
    )
    _validate_strings(raw)
    if not isinstance(raw, dict) or set(raw) != set(HistoryReplayResult.model_fields):
        raise ValueError("replay fields are missing or unexpected")
    replay = HistoryReplayResult.model_validate(raw)
    if replay.to_json_bytes() != payload:
        raise ValueError("replay bytes differ from canonical producer output")
    # The nested selection has a stricter evidence parser than its Pydantic
    # model alone. Reuse it before granting the selection to allocation.
    if parse_selection(replay.selection.to_json_bytes()) != replay.selection:
        raise ValueError("nested selection is inconsistent")
    return replay


@dataclass(frozen=True, slots=True)
class _FrozenReader:
    job: HistoryJob
    states: tuple[SymbolHistory, ...]
    codes: tuple[str, ...]

    def read_selected(
        self, job_id: str, *, codes: tuple[str, ...] = (), all_targets: bool = False
    ) -> tuple[HistoryJob, tuple[SymbolHistory, ...]]:
        if job_id != self.job.job_id or codes != self.codes or all_targets:
            raise ValueError("replay requested a different frozen history snapshot")
        return self.job, self.states


def verify_replay_evidence(
    reader: HistoryReader, replay_bytes: bytes, receipt_bytes: bytes
) -> VerifiedReplay:
    """Reject changed replay, receipt or DB evidence before allocation runs."""
    try:
        replay = _parse_replay(replay_bytes)
        if not receipt_bytes or len(receipt_bytes) > MAX_READ_RECEIPT_BYTES:
            raise ValueError("receipt file size is invalid")
        receipt = parse_read_receipt(receipt_bytes)
        receipt_sha256 = hashlib.sha256(receipt_bytes).hexdigest()
        if (
            replay.read_receipt is None
            or not replay.local_snapshot_read_before_decision_confirmed
            or replay.receipt_check != "local_committed_snapshot_read_before_decision"
            or replay.read_receipt != receipt
            or replay.read_receipt_sha256 != receipt_sha256
            or replay.read_receipt_content_sha256
            != hashlib.sha256(receipt.to_json_bytes()).hexdigest()
        ):
            raise ValueError("replay and sidecar receipt differ")
        codes = tuple(candidate.target.short_code for candidate in replay.selection.candidates)
        if (
            not 1 <= len(codes) <= MAX_REPLAY_TARGETS
            or any(not isinstance(code, str) for code in codes)
            or len(set(codes)) != len(codes)
        ):
            raise ValueError("replay candidate codes are invalid")
        # The preceding type check makes the cast safe for the HistoryReader contract.
        verified_codes = tuple(code for code in codes if isinstance(code, str))
        job, states = reader.read_selected(replay.history_job_id, codes=verified_codes)
        if len(states) != len(verified_codes) or job.job_id != replay.history_job_id:
            raise ValueError("history reader returned a different candidate set")
        if any(
            state.ordinal < 0
            or state.ordinal >= len(job.targets)
            or job.targets[state.ordinal].short_code != code
            for code, state in zip(verified_codes, states, strict=True)
        ):
            raise ValueError("history reader returned candidates in the wrong order")
        recomputed = HistoryReplayService(clock=lambda: replay.replayed_at).run(
            _FrozenReader(job, states, verified_codes),
            replay.history_job_id,
            replay.as_of,
            replay.decision_at,
            replay.selection.policy,
            codes=verified_codes,
            read_receipt_bytes=receipt_bytes,
        )
        if recomputed.to_json_bytes() != replay_bytes:
            raise ValueError("replay does not match the frozen history snapshot")
        by_code = dict(zip(verified_codes, states, strict=True))
        return VerifiedReplay(
            replay=replay,
            job=job,
            selected_states=tuple(by_code[code] for code in replay.selection.selected_codes),
            replay_file_sha256=hashlib.sha256(replay_bytes).hexdigest(),
            receipt_file_sha256=receipt_sha256,
            selection_content_sha256=hashlib.sha256(replay.selection.to_json_bytes()).hexdigest(),
        )
    except HistoryStorageError:
        raise
    except Exception:
        raise AllocationInputError("REPLAY_EVIDENCE_MISMATCH", _MISMATCH_MESSAGE) from None
