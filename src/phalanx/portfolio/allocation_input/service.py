"""Single-read selection and one read-only SQLite snapshot for reusable preparation."""

import hashlib
from pathlib import Path

from phalanx.domain.allocation_input import AllocationInput
from phalanx.market_data.history.reader import HistoryReader
from phalanx.portfolio.allocation_input.calculation import prepare_allocation_input
from phalanx.portfolio.allocation_input.errors import AllocationInputReadError
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

    @staticmethod
    def export(result: AllocationInput, output: Path) -> Path:
        return store_private_json_bytes(output, result.to_json_bytes())
