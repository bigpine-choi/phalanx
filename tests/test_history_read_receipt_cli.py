"""CLI round trip for a local post-commit history read receipt (Linux writer)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

if sys.platform == "win32":
    pytest.skip("root CLI and history repository import Unix-only fcntl", allow_module_level=True)

from feature_helpers import bars, history
from typer.testing import CliRunner

from phalanx.cli import app
from phalanx.domain.price_history import HistoryAttempt, HistoryView
from phalanx.market_data.history.repository import SqliteHistoryRepository


def _stored_job(tmp_path: Path) -> tuple[SqliteHistoryRepository, str]:
    view = history(
        (bars("005930", ["100"] * 60 + ["110"], start=date(2026, 6, 21)),),
        codes=("005930",),
    )
    completed = view.symbols[0].model_copy(
        update={
            "attempts": (
                HistoryAttempt(
                    number=1,
                    started_at=datetime(2026, 9, 13, 1, 0, tzinfo=UTC),
                    finished_at=datetime(2026, 9, 13, 1, 1, tzinfo=UTC),
                    outcome="completed",
                ),
            )
        }
    )
    repository = SqliteHistoryRepository(tmp_path / "private" / "history.sqlite3")
    repository.create(HistoryView(job=view.job, symbols=(completed,)))
    return repository, view.job.job_id


def _capture_args(repository: SqliteHistoryRepository, job_id: str, output: Path) -> list[str]:
    return [
        "market-data",
        "history",
        "read-receipt",
        job_id,
        "--history-db",
        str(repository.path),
        "--code",
        "005930",
        "--output",
        str(output),
    ]


def _replay_args(
    repository: SqliteHistoryRepository,
    job_id: str,
    decision_at: datetime,
    receipt: Path,
) -> list[str]:
    return [
        "candidates",
        "replay-history",
        "--history-db",
        str(repository.path),
        "--job-id",
        job_id,
        "--as-of",
        "2026-08-20",
        "--decision-at",
        decision_at.isoformat(),
        "--code",
        "005930",
        "--metric",
        "return_60",
        "--top",
        "1",
        "--max-age-days",
        "0",
        "--read-receipt",
        str(receipt),
    ]


def _capture(
    repository: SqliteHistoryRepository, job_id: str, receipt: Path
) -> tuple[bytes, dict[str, object]]:
    response = CliRunner().invoke(app, _capture_args(repository, job_id, receipt))
    assert response.exit_code == 0, response.output
    payload = receipt.read_bytes()
    assert response.stdout.encode("utf-8") == payload
    parsed = json.loads(payload)
    assert isinstance(parsed, dict)
    return payload, parsed


def test_read_receipt_cli_is_write_once_and_replay_confirms_exact_bytes(tmp_path: Path) -> None:
    repository, job_id = _stored_job(tmp_path)
    receipt = tmp_path / "private" / "history-read-receipt.json"
    receipt_bytes, captured = _capture(repository, job_id, receipt)

    assert captured["history_job_id"] == job_id
    assert captured["evidence_basis"] == "local_committed_snapshot_read"
    assert captured["trusted_timestamp_verified"] is False
    assert captured["symbols"][0]["stock_code"] == "005930"
    assert captured["symbols"][0]["attempt_number"] == 1

    duplicate = CliRunner().invoke(app, _capture_args(repository, job_id, receipt))
    assert duplicate.exit_code == 66, duplicate.output
    assert "OUTPUT_EXISTS" in duplicate.output
    assert duplicate.stdout == ""
    assert receipt.read_bytes() == receipt_bytes

    # The decision under review is after this newly observed read. The replay
    # timestamp is obtained inside the command, so never choose a future time.
    decision_at = datetime.now(UTC)
    replay = CliRunner().invoke(app, _replay_args(repository, job_id, decision_at, receipt))
    assert replay.exit_code == 0, replay.output
    result = json.loads(replay.stdout)
    assert result["local_snapshot_read_before_decision_confirmed"] is True
    assert result["receipt_check"] == "local_committed_snapshot_read_before_decision"
    assert result["read_receipt"] == captured
    assert result["read_receipt_sha256"] == hashlib.sha256(receipt_bytes).hexdigest()
    assert result["selection"]["selected_codes"] == ["005930"]
    assert result["database_commit_before_decision_verified"] is False
    assert result["point_in_time_backtest_guaranteed"] is False


def test_read_receipt_cli_rejects_decision_before_read(tmp_path: Path) -> None:
    repository, job_id = _stored_job(tmp_path)
    receipt = tmp_path / "private" / "history-read-receipt.json"
    _, captured = _capture(repository, job_id, receipt)
    read_completed = datetime.fromisoformat(str(captured["read_completed_at"]))
    decision_at = read_completed - timedelta(microseconds=1)

    response = CliRunner().invoke(app, _replay_args(repository, job_id, decision_at, receipt))
    assert response.exit_code == 65, response.output
    assert "READ_AFTER_DECISION" in response.output
    assert response.stdout == ""


@pytest.mark.parametrize("tamper", ["database", "receipt"])
def test_read_receipt_cli_rejects_changed_state_or_receipt(tmp_path: Path, tamper: str) -> None:
    repository, job_id = _stored_job(tmp_path)
    receipt = tmp_path / "private" / "history-read-receipt.json"
    _, captured = _capture(repository, job_id, receipt)

    if tamper == "database":
        with sqlite3.connect(repository.path) as connection:
            row = connection.execute(
                "SELECT state_json FROM symbols WHERE job_id=? AND ordinal=0", (job_id,)
            ).fetchone()
            assert row is not None
            state = json.loads(row[0])
            state["error_message"] = "changed after receipt"
            connection.execute(
                "UPDATE symbols SET state_json=? WHERE job_id=? AND ordinal=0",
                (json.dumps(state), job_id),
            )
    else:
        captured["job_sha256"] = "0" * 64
        receipt.write_text(json.dumps(captured), encoding="utf-8")

    response = CliRunner().invoke(
        app, _replay_args(repository, job_id, datetime.now(UTC), receipt)
    )
    assert response.exit_code == 65, response.output
    assert "RECEIPT_MISMATCH" in response.output
    assert response.stdout == ""
