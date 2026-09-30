"""Single-read selection and one read-only SQLite snapshot for reusable preparation."""

import hashlib
from pathlib import Path

from phalanx.desktop.storage import StorageError, read_selected_file
from phalanx.domain.allocation_input import AllocationInput, ReplayAllocationProvenance
from phalanx.market_data.history.read_receipt import MAX_READ_RECEIPT_BYTES
from phalanx.market_data.history.reader import HistoryReader
from phalanx.portfolio.allocation_input.calculation import prepare_allocation_input
from phalanx.portfolio.allocation_input.errors import AllocationInputReadError
from phalanx.portfolio.allocation_input.replay_evidence import (
    MAX_REPLAY_BYTES,
    verify_replay_evidence,
)
from phalanx.portfolio.allocation_input.validation import parse_selection
from phalanx.portfolio.private_json_storage import store_private_json_bytes


class AllocationInputService:
    def __init__(self, repository: HistoryReader) -> None:
        self.repository = repository

    def prepare(self, selection_path: Path) -> AllocationInput:
        try:
            payload = selection_path.read_bytes()
        except OSError:
            raise AllocationInputReadError() from None
        return self.prepare_bytes(payload)

    def prepare_bytes(self, payload: bytes) -> AllocationInput:
        """Prepare from the exact selection bytes captured by the calling job."""
        selection = parse_selection(payload)
        # Empty selections have no prices to verify; never claim otherwise.
        job, states = (
            self.repository.read_selected(
                selection.source.history_job_id, codes=selection.selected_codes
            )
            if selection.selected_codes
            else (None, ())
        )
        return prepare_allocation_input(
            selection, job, states, selection_file_sha256=hashlib.sha256(payload).hexdigest()
        )

    def prepare_replay(self, replay_path: Path, receipt_path: Path) -> AllocationInput:
        try:
            replay_bytes = read_selected_file(replay_path, MAX_REPLAY_BYTES)
            receipt_bytes = read_selected_file(receipt_path, MAX_READ_RECEIPT_BYTES)
        except (OSError, StorageError):
            raise AllocationInputReadError() from None
        return self.prepare_replay_bytes(replay_bytes, receipt_bytes)

    def prepare_replay_bytes(self, replay_bytes: bytes, receipt_bytes: bytes) -> AllocationInput:
        """Recompute the full replay from one DB snapshot before preparing returns."""
        verified = verify_replay_evidence(self.repository, replay_bytes, receipt_bytes)
        replay = verified.replay
        receipt = replay.read_receipt
        assert receipt is not None and replay.read_receipt_content_sha256 is not None
        provenance = ReplayAllocationProvenance(
            replay_file_sha256=verified.replay_file_sha256,
            selection_content_sha256=verified.selection_content_sha256,
            read_receipt_file_sha256=verified.receipt_file_sha256,
            read_receipt_content_sha256=replay.read_receipt_content_sha256,
            row_evidence_sha256=replay.row_evidence_sha256,
            features_sha256=replay.features_sha256,
            history_job_id=replay.history_job_id,
            as_of=replay.as_of,
            selected_codes=replay.selection.selected_codes,
            decision_at=replay.decision_at,
            replayed_at=replay.replayed_at,
            read_completed_at=receipt.read_completed_at,
        )
        return prepare_allocation_input(
            replay.selection,
            verified.job,
            verified.selected_states,
            selection_file_sha256=None,
            replay_provenance=provenance,
        )

    @staticmethod
    def export(result: AllocationInput, output: Path) -> Path:
        return store_private_json_bytes(output, result.to_json_bytes())
