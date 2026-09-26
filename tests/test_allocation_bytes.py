"""Byte entry points preserve preparation, provenance and financial contexts."""

import hashlib
import sqlite3
from decimal import ROUND_DOWN, localcontext
from pathlib import Path

from desktop_helpers import desktop_inputs

from phalanx.domain.price_history import HistoryJob, SymbolHistory
from phalanx.market_data.history.reader import read_selected, validate_database
from phalanx.portfolio.allocation_input.service import AllocationInputService
from phalanx.portfolio.allocation_targets.service import AllocationTargetsService


class FixtureReader:
    """Portable fixture reader; production Windows handle policy is tested natively."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.reads = 0

    def read_selected(
        self, job_id: str, *, codes: tuple[str, ...] = (), all_targets: bool = False
    ) -> tuple[HistoryJob, tuple[SymbolHistory, ...]]:
        self.reads += 1
        with sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True) as connection:
            connection.execute("BEGIN")
            validate_database(connection)
            return read_selected(connection, job_id, codes=codes, all_targets=all_targets)


def test_frozen_bytes_ignore_subsequent_selection_replacement_and_prepare_once(
    tmp_path: Path,
) -> None:
    database, selection = desktop_inputs(tmp_path)
    payload = selection.read_bytes()
    reader = FixtureReader(database)
    service = AllocationTargetsService(AllocationInputService(reader))
    expected = service.calculate(selection)
    assert reader.reads == 1
    selection.write_bytes(b"changed after the UI captured the bytes")
    with localcontext() as context:
        context.prec = 5
        context.rounding = ROUND_DOWN
        actual = service.calculate_bytes(payload)
    assert reader.reads == 2
    assert actual.to_json_bytes() == expected.to_json_bytes()


def test_preparation_provenance_hashes_the_exact_captured_bytes(tmp_path: Path) -> None:
    database, selection = desktop_inputs(tmp_path)
    payload = selection.read_bytes() + b"\n"
    reader = FixtureReader(database)
    prepared = AllocationInputService(reader).prepare_bytes(payload)
    assert prepared.selection_file_sha256 == hashlib.sha256(payload).hexdigest()
    assert reader.reads == 1
