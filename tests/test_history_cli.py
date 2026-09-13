from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from history_helpers import CODES, Reader, job
from typer.testing import CliRunner

from phalanx.cli import app
from phalanx.market_data.history.errors import HistoryFetchError

runner = CliRunner()
PREFIX = ["market-data", "history"]


def test_create_status_show_offline_without_credentials_and_persisted_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, original, discovery = job(tmp_path)
    preserved = discovery.path.read_bytes()

    def forbidden(*args, **kwargs):
        pytest.fail("offline command attempted credentials or HTTP")

    monkeypatch.setattr("phalanx.config.load_kis_credentials", forbidden)
    monkeypatch.setattr("phalanx.market_data.history.application.load_kis_credentials", forbidden)
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    created = runner.invoke(
        app,
        [
            *PREFIX,
            "create",
            "--discovery-run-id",
            original.job.discovery_run_id,
            "--start",
            "2026-08-01",
            "--end",
            "2026-08-31",
            "--code",
            "005930",
            "--code",
            "0001A0",
            "--discovery-db",
            str(discovery.path),
            "--history-db",
            str(service.repository.path),
        ],
    )
    assert created.exit_code == 0, created.output
    job_id = created.output.split("JOB_ID: ")[1].splitlines()[0]
    assert job_id != original.job.job_id
    assert all(code in created.output for code in CODES)
    path_args = ["--history-db", str(service.repository.path)]
    status = runner.invoke(app, [*PREFIX, "status", job_id, *path_args])
    assert status.exit_code == 0
    assert "pending: 2" in status.output and "unverified" in status.output
    show = runner.invoke(app, [*PREFIX, "show", job_id, "0001A0", *path_args])
    assert show.exit_code == 0
    payload = json.loads(show.output)
    assert payload["symbol"]["result"] is None
    assert payload["target"]["short_code"] == "0001A0"
    reader = Reader()
    monkeypatch.setattr("phalanx.market_data.history.cli.production_history_reader", reader.factory)
    first = runner.invoke(app, [*PREFIX, "run", job_id, "--max-symbols", "1", *path_args])
    assert first.exit_code == 2  # deliberately limited work is not reported as full completion
    assert "completed: 1" in first.output and "pending: 1" in first.output
    resumed = runner.invoke(app, [*PREFIX, "run", job_id, *path_args])
    assert resumed.exit_code == 0 and "completed: 2" in resumed.output
    assert reader.calls == list(CODES)
    show = runner.invoke(app, [*PREFIX, "show", job_id, "0001A0", *path_args])
    payload = json.loads(show.output)
    assert payload["symbol"]["result"]["bars"][0]["close_price"] == "110.0010"
    assert payload["symbol"]["attempts"][0]["finished_at"] is not None
    assert payload["target"]["source_files"]
    assert discovery.path.read_bytes() == preserved


@pytest.mark.parametrize(
    "options",
    [[], ["--all-eligible", "--code", "005930"], ["--code", "005930", "--code", "005930"]],
)
def test_cli_requires_exact_selection(tmp_path: Path, options: list[str]) -> None:
    service, view, discovery = job(tmp_path)
    result = runner.invoke(
        app,
        [
            *PREFIX,
            "create",
            "--discovery-run-id",
            view.job.discovery_run_id,
            "--start",
            "2026-08-01",
            "--end",
            "2026-08-31",
            *options,
            "--discovery-db",
            str(discovery.path),
            "--history-db",
            str(service.repository.path),
        ],
    )
    assert result.exit_code == 65


def test_cli_failure_retry_and_interrupt_exit_codes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, view, _ = job(tmp_path)
    reader = Reader(
        {"005930": HistoryFetchError("KIS_API_UNSUPPORTED", "조회 지원 미확인"), "0001A0": ()}
    )
    monkeypatch.setattr("phalanx.market_data.history.cli.production_history_reader", reader.factory)
    args = [*PREFIX, "run", view.job.job_id, "--history-db", str(service.repository.path)]
    first = runner.invoke(app, args)
    assert first.exit_code == 2
    assert "failed: 1" in first.output and "empty: 1" in first.output
    assert "KIS_API_UNSUPPORTED" in first.output
    skipped = runner.invoke(app, args)
    assert skipped.exit_code == 2 and reader.calls == list(CODES)
    reader.outcomes["005930"] = KeyboardInterrupt()
    interrupted = runner.invoke(app, [*args, "--retry-failed"])
    assert interrupted.exit_code == 130
    reader.outcomes["005930"] = ()
    resumed = runner.invoke(app, args)
    assert resumed.exit_code == 0
    assert reader.calls == [*CODES, "005930", "005930"]


def test_cli_lookup_and_storage_errors(tmp_path: Path) -> None:
    service, view, _ = job(tmp_path)
    args = ["--history-db", str(service.repository.path)]
    missing = runner.invoke(app, [*PREFIX, "status", "f" * 32, *args])
    assert missing.exit_code == 65 and "JOB_NOT_FOUND" in missing.output
    wrong_code = runner.invoke(app, [*PREFIX, "show", view.job.job_id, "0001a0", *args])
    assert wrong_code.exit_code == 65 and "SYMBOL_NOT_FOUND" in wrong_code.output
    invalid_limit = runner.invoke(
        app, [*PREFIX, "run", view.job.job_id, "--max-symbols", "0", *args]
    )
    assert invalid_limit.exit_code == 2
    service.repository.path.chmod(0o644)
    unsafe = runner.invoke(app, [*PREFIX, "status", view.job.job_id, *args])
    assert unsafe.exit_code == 66 and "STORAGE_FAILED" in unsafe.output
