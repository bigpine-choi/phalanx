"""CLI integration against one actual immutable history SQLite snapshot."""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from feature_helpers import bars, history
from typer.testing import CliRunner

if sys.platform == "win32":
    pytest.skip("root CLI and history repository import Unix-only fcntl", allow_module_level=True)

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


def _args(repository: SqliteHistoryRepository, job_id: str) -> list[str]:
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
        "2026-09-14T09:00:00+09:00",
        "--code",
        "005930",
        "--metric",
        "return_60",
        "--top",
        "1",
        "--max-age-days",
        "0",
    ]


def test_replay_history_cli_exports_exact_json_with_row_receipts(tmp_path: Path) -> None:
    repository, job_id = _stored_job(tmp_path)
    output = tmp_path / "private" / "decision.json"

    response = CliRunner().invoke(app, [*_args(repository, job_id), "--output", str(output)])

    assert response.exit_code == 0, response.output
    assert response.stdout.encode("utf-8") == output.read_bytes()
    payload = json.loads(response.stdout)
    assert payload["history_job_id"] == job_id
    assert payload["selection"]["selected_codes"] == ["005930"]
    assert payload["receipt_check"] == "local_fetch_completed_before_decision"
    assert len(payload["rows"]) == 61
    assert payload["rows"][-1]["trade_date"] == "2026-08-20"
    assert payload["rows"][-1]["fetch_completed_at"] == "2026-09-13T01:01:00Z"
    assert payload["rows"][-1]["attempt_number"] == 1
    assert re.fullmatch(r"[0-9a-f]{64}", payload["rows"][-1]["row_sha256"])
    assert payload["rows"][-1]["history_result_sha256"] == payload["features"]["symbols"][0][
        "source_price_sha256"
    ]
    assert payload["database_commit_before_decision_verified"] is False
    assert payload["vendor_release_time_verified"] is False
    assert payload["point_in_time_backtest_guaranteed"] is False


@pytest.mark.parametrize(
    "decision_at,error_code",
    [
        ("2026-09-14T09:00:00", "INVALID_DECISION_TIME"),
        ("2026-09-13T09:30:00+09:00", "FETCH_AFTER_DECISION"),
    ],
)
def test_replay_history_cli_rejects_naive_or_pre_fetch_decision(
    tmp_path: Path, decision_at: str, error_code: str
) -> None:
    repository, job_id = _stored_job(tmp_path)
    args = _args(repository, job_id)
    args[args.index("--decision-at") + 1] = decision_at

    response = CliRunner().invoke(app, args)

    assert response.exit_code == 65, response.output
    assert error_code in response.output
    assert response.stdout == ""
