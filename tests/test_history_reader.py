"""The exact validators shared by the Linux and Windows repositories."""

import json
import sqlite3
from pathlib import Path

import pytest
from portable_history_helpers import CODES, JOB_ID, create_history_db
from pydantic import ValidationError

from phalanx.market_data.history.errors import HistoryError, HistoryStorageError
from phalanx.market_data.history.reader import read_selected, validate_database


def test_selected_read_preserves_order_and_only_parses_selected_states(tmp_path: Path) -> None:
    path = tmp_path / "history.sqlite3"
    view = create_history_db(path)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE symbols SET state_json='broken' WHERE ordinal=1")
        validate_database(connection)
        job, states = read_selected(connection, JOB_ID, codes=(CODES[2], CODES[0]))
        assert job == view.job
        assert states == (view.symbols[2], view.symbols[0])
        with pytest.raises(ValidationError):
            read_selected(connection, JOB_ID, all_targets=True)


@pytest.mark.parametrize(
    "mutation",
    [
        "PRAGMA application_id=0",
        "PRAGMA user_version=2",
        "PRAGMA journal_mode=WAL",
        "CREATE TABLE unexpected (value TEXT)",
        "CREATE VIEW extra AS SELECT * FROM jobs",
        "ALTER TABLE symbols RENAME COLUMN state_json TO payload",
        "DROP TABLE symbols",
    ],
)
def test_metadata_and_schema_are_validated(tmp_path: Path, mutation: str) -> None:
    path = tmp_path / "history.sqlite3"
    create_history_db(path)
    with sqlite3.connect(path) as connection:
        connection.execute(mutation)
        with pytest.raises(HistoryStorageError):
            validate_database(connection)


@pytest.mark.parametrize("damage", ["hash", "ordinal", "code", "date", "missing", "job_id"])
def test_shared_reader_rejects_mismatched_frozen_rows(tmp_path: Path, damage: str) -> None:
    path = tmp_path / "history.sqlite3"
    view = create_history_db(path)
    with sqlite3.connect(path) as connection:
        if damage == "missing":
            connection.execute("DELETE FROM symbols WHERE ordinal=0")
        elif damage == "job_id":
            raw = view.job.model_dump(mode="json")
            raw["job_id"] = "b" * 32
            connection.execute("UPDATE jobs SET job_json=?", (json.dumps(raw),))
        else:
            raw = view.symbols[0].model_dump(mode="json")
            if damage == "hash":
                raw["result"]["sha256"] = "0" * 64
            elif damage == "ordinal":
                raw["ordinal"] = 2
            elif damage == "code":
                raw["result"]["bars"][0]["stock_code"] = CODES[1]
            else:
                raw["result"]["bars"][0]["trade_date"] = "2026-08-19"
            connection.execute(
                "UPDATE symbols SET state_json=? WHERE ordinal=0", (json.dumps(raw),)
            )
        with pytest.raises((ValidationError, HistoryStorageError)):
            read_selected(connection, JOB_ID, codes=(CODES[0],))


@pytest.mark.parametrize(
    "job_id,codes,all_targets,error",
    [
        (JOB_ID, (), False, "TARGET_SELECTION_REQUIRED"),
        (JOB_ID, CODES, True, "TARGET_SELECTION_REQUIRED"),
        (JOB_ID, (CODES[0], CODES[0]), False, "DUPLICATE_CODE"),
        (JOB_ID, ("999999",), False, "SYMBOL_NOT_FOUND"),
        ("b" * 32, CODES, False, "JOB_NOT_FOUND"),
    ],
)
def test_shared_lookup_contract(
    tmp_path: Path, job_id: str, codes: tuple[str, ...], all_targets: bool, error: str
) -> None:
    path = tmp_path / "history.sqlite3"
    create_history_db(path)
    with sqlite3.connect(path) as connection, pytest.raises(HistoryError) as caught:
        read_selected(connection, job_id, codes=codes, all_targets=all_targets)
    assert caught.value.code == error
