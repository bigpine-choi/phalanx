"""Native Windows path, sharing, readonly and service checks (never OS spoofing)."""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from desktop_helpers import desktop_inputs
from portable_history_helpers import CODES, JOB_ID, create_history_db

from phalanx.market_data.history.errors import HistoryStorageError
from phalanx.market_data.history.windows_repository import WindowsHistoryRepository
from phalanx.portfolio.allocation_input.service import AllocationInputService
from phalanx.portfolio.allocation_targets.service import AllocationTargetsService

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="requires native Win32 handles")


def test_native_read_preserves_order_bytes_and_readonly_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "한글 공백 자료" / "일봉.sqlite3"
    view = create_history_db(path)
    before = path.read_bytes()
    repository = WindowsHistoryRepository(path)
    job, states = repository.read_selected(JOB_ID, codes=(CODES[2], CODES[0]))
    assert job == view.job and states == (view.symbols[2], view.symbols[0])
    with repository._connect() as connection:
        assert connection.in_transaction
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("DELETE FROM jobs")
    assert before == path.read_bytes()
    assert sorted(p.name for p in path.parent.iterdir()) == [path.name]


def test_native_bytes_and_path_calculations_match_all_four_scenarios(tmp_path: Path) -> None:
    database, selection = desktop_inputs(tmp_path)
    before = {path: path.read_bytes() for path in (database, selection)}
    service = AllocationTargetsService(AllocationInputService(WindowsHistoryRepository(database)))
    via_path = service.calculate(selection)
    via_bytes = service.calculate_bytes(before[selection])
    assert via_path.to_json_bytes() == via_bytes.to_json_bytes()
    assert len(via_bytes.scenarios) == 4
    assert all(path.read_bytes() == payload for path, payload in before.items())


@pytest.mark.parametrize("suffix", ["-journal", "-wal", "-shm"])
def test_native_rejects_every_sqlite_sidecar(tmp_path: Path, suffix: str) -> None:
    path = tmp_path / "history.sqlite3"
    create_history_db(path)
    sidecar = path.with_name(path.name + suffix)
    sidecar.write_bytes(b"reject without opening")
    before = path.read_bytes()
    with pytest.raises(HistoryStorageError):
        WindowsHistoryRepository(path).read_selected(JOB_ID, codes=CODES)
    assert path.read_bytes() == before
    assert sidecar.read_bytes() == b"reject without opening"


@pytest.mark.parametrize("kind", ["missing", "invalid", "hardlink", "relative", "unc", "ads"])
def test_native_rejects_missing_invalid_or_unsafe_input(tmp_path: Path, kind: str) -> None:
    path = tmp_path / "history.sqlite3"
    if kind != "missing":
        create_history_db(path)
    if kind == "invalid":
        path.write_bytes(b"not sqlite")
    elif kind == "hardlink":
        os.link(path, tmp_path / "other.sqlite3")
    elif kind == "relative":
        path = Path("history.sqlite3")
    elif kind == "unc":
        path = Path(r"\\localhost\share\history.sqlite3")
    elif kind == "ads":
        path = Path(str(path) + ":hidden")
    with pytest.raises(HistoryStorageError):
        WindowsHistoryRepository(path).read_selected(JOB_ID, codes=CODES)
    if kind == "missing":
        assert not path.exists()


def test_native_rejects_junction_ancestor(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    path = source / "history.sqlite3"
    create_history_db(path)
    junction = tmp_path / "junction"
    subprocess.run(
        ["cmd.exe", "/c", "mklink", "/J", str(junction), str(source)],
        check=True,
        capture_output=True,
    )
    try:
        with pytest.raises(HistoryStorageError):
            WindowsHistoryRepository(junction / path.name).read_selected(JOB_ID, codes=CODES)
    finally:
        junction.rmdir()


def test_native_held_handles_deny_replacement_writes_and_ancestor_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "pinned" / "history.sqlite3"
    create_history_db(path)
    replacement = tmp_path / "replacement.sqlite3"
    create_history_db(replacement)
    real_connect = sqlite3.connect
    attempted = []

    def connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        with pytest.raises(PermissionError):
            os.replace(replacement, path)
        with pytest.raises(PermissionError):
            path.open("r+b")
        with pytest.raises(PermissionError):
            path.parent.rename(tmp_path / "moved")
        attempted.append(True)
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)
    WindowsHistoryRepository(path).read_selected(JOB_ID, codes=CODES)
    assert attempted == [True]
    assert path.exists() and replacement.exists()


def test_native_already_open_writer_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "history.sqlite3"
    create_history_db(path)
    with path.open("r+b"), pytest.raises(HistoryStorageError):
        WindowsHistoryRepository(path).read_selected(JOB_ID, codes=CODES)
