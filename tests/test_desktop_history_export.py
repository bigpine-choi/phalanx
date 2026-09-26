"""Linux-only native backup checks; no copying a live database or sidecars."""

import sqlite3
import sys
from pathlib import Path

import pytest
from portable_history_helpers import CODES, JOB_ID, create_history_db

from phalanx.desktop.export_history import export_history_snapshot, main
from phalanx.market_data.history.errors import HistoryStorageError
from phalanx.market_data.history.reader import read_selected, validate_database
from phalanx.portfolio.private_json_storage import PrivateJsonAlreadyExistsError

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux source export")


def source_database(directory: Path) -> Path:
    path = directory / "source" / "history.sqlite3"
    create_history_db(path)
    path.parent.chmod(0o700)
    path.chmod(0o600)
    return path


def test_export_closed_consistent_readonly_validated_backup_without_touching_source(
    tmp_path: Path,
) -> None:
    source = source_database(tmp_path)
    output = tmp_path / "export" / "history.sqlite3"
    before = source.read_bytes()
    assert export_history_snapshot(source, output) == output
    assert source.read_bytes() == before
    assert output.stat().st_mode & 0o777 == 0o600
    assert output.parent.stat().st_mode & 0o777 == 0o700
    assert output.read_bytes()[18:20] == b"\x01\x01"
    with sqlite3.connect(output.as_uri() + "?mode=ro", uri=True) as connection:
        connection.execute("BEGIN")
        validate_database(connection)
        _, states = read_selected(connection, JOB_ID, codes=CODES)
        assert len(states) == len(CODES)
    assert not list(source.parent.glob("*-*"))
    assert not list(output.parent.glob("*-*"))
    assert not list(output.parent.glob("*.tmp"))


def test_export_never_overwrites_existing_files(tmp_path: Path) -> None:
    source = source_database(tmp_path)
    output = tmp_path / "existing.sqlite3"
    output.write_bytes(b"preserve output")
    with pytest.raises(PrivateJsonAlreadyExistsError):
        export_history_snapshot(source, output)
    assert output.read_bytes() == b"preserve output"
    with pytest.raises(PrivateJsonAlreadyExistsError):
        export_history_snapshot(source, source)


def test_export_preserves_source_permission_and_missing_file_policy(tmp_path: Path) -> None:
    source = source_database(tmp_path)
    source.chmod(0o644)
    output = tmp_path / "export.sqlite3"
    with pytest.raises(HistoryStorageError):
        export_history_snapshot(source, output)
    assert not output.exists()
    missing = tmp_path / "missing.sqlite3"
    with pytest.raises(HistoryStorageError):
        export_history_snapshot(missing, output)
    assert not missing.exists() and not output.exists()


def test_export_command_reports_failure_without_a_false_success(tmp_path: Path, capsys) -> None:
    result = main(["--source", str(tmp_path / "missing"), "--output", str(tmp_path / "out")])
    captured = capsys.readouterr()
    assert result == 2 and not captured.out
    assert "백업하지 못했습니다" in captured.err


def test_export_uses_sqlite_snapshot_with_an_active_uncommitted_writer(tmp_path: Path) -> None:
    source = source_database(tmp_path)
    output = tmp_path / "export.sqlite3"
    writer = sqlite3.connect(source, isolation_level=None)
    try:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("UPDATE jobs SET job_json='uncommitted invalid job'")
        assert source.with_name(source.name + "-journal").exists()
        export_history_snapshot(source, output)
        with sqlite3.connect(output.as_uri() + "?mode=ro", uri=True) as connection:
            validate_database(connection)
            job, _ = read_selected(connection, JOB_ID, codes=CODES)
            assert job.job_id == JOB_ID
        assert not output.with_name(output.name + "-journal").exists()
    finally:
        writer.rollback()
        writer.close()
