from __future__ import annotations

import base64
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import phalanx.cli as cli
import phalanx.nav.cli as nav_cli
from phalanx.nav.models import NavError
from phalanx.nav.storage import NavStorageError

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "daily-nav"


def _import(db: Path, input_path: Path) -> list[str]:
    return ["nav", "import", "--db", str(db), "--input", str(input_path)]


def _command(command: str, db: Path) -> list[str]:
    arguments = [
        "nav",
        command,
        "--db",
        str(db),
        "--series",
        "synthetic-demo",
        "--environment",
        "development",
    ]
    if command == "restore":
        arguments.extend(("--through", "2026-01-09"))
    return arguments


def _json(arguments: list[str]) -> Any:
    result = CliRunner().invoke(cli.app, arguments)
    assert result.exit_code == 0, (result.stdout, result.stderr, result.exception)
    assert result.stderr == ""
    return json.loads(result.stdout)


def test_offline_example_import_gap_recovery_correction_and_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden_snapshot() -> None:
        pytest.fail("NAV commands must not call the account snapshot workflow")

    monkeypatch.setattr(cli, "run_production_snapshot", forbidden_snapshot)
    db = tmp_path / "private" / "nav.sqlite3"
    seed = EXAMPLES / "01-seed.json"

    imported = _json(_import(db, seed))
    assert imported["created_series"] == 1
    first = _json(_command("restore", db))
    assert [row["status"] for row in first] == [
        "confirmed",
        "confirmed",
        "pending",
        "pending",
        "pending",
    ]
    assert first[0]["nav"] == "20050"
    assert first[0]["units"] == "20.05"
    assert first[0]["unit_value"] == first[0]["benchmark_unit_value"] == "1000"
    assert first[0]["daily_return"] is None
    assert first[2]["nav"] is None
    assert first[2]["daily_return"] is None
    assert "missing_daily_input" in first[2]["reasons"]
    assert "preceding_day_pending" in first[3]["reasons"]
    assert _json(_command("query", db)) == first

    completion = _json(_import(db, EXAMPLES / "02-complete.json"))
    assert completion["inserted_days"] == 1
    assert _json(_command("query", db)) == []
    completed = _json(_command("restore", db))
    assert all(row["status"] == "confirmed" for row in completed)
    assert completed[-1]["nav"] == "21405"
    assert completed[1]["external_flow"] == "2000"
    assert completed[2]["external_flow"] == "-500"
    assert completed[-1]["benchmark_unit_value"] == "1040.00"
    assert Decimal(completed[-1]["mdd"]) < 0

    duplicate = _json(_import(db, seed))
    assert duplicate["created_series"] == duplicate["inserted_events"] == 0
    assert duplicate["invalidated_days"] == 0
    assert _json(_command("query", db)) == completed
    assert _json(_command("restore", db)) == completed

    corrected_import = _json(_import(db, EXAMPLES / "03-correction.json"))
    assert corrected_import["inserted_events"] == corrected_import["inserted_days"] == 1
    assert _json(_command("query", db)) == []
    corrected = _json(_command("restore", db))
    assert corrected[0] == completed[0]
    assert corrected[1]["unit_value"] != completed[1]["unit_value"]
    assert corrected[-1]["nav"] == "21415"
    assert corrected[-1]["state"]["receivables"] == {"dividend-1": "10"}
    assert _json(_command("query", db)) == corrected

    history = _json(_command("history", db))
    assert len(history["source_imports"]) == 3
    assert base64.b64decode(history["source_imports"][0]["raw_payload_base64"]) == (
        seed.read_bytes()
    )
    dividends = [
        event["input"] for event in history["events"] if event["input"]["event_id"] == "dividend-1"
    ]
    assert [event["revision"] for event in dividends] == [1, 2]
    assert [event["amount"] for event in dividends] == ["100", "110"]
    assert history["calculations"][0]["days"] == first
    assert history["calculations"][-1]["days"] == corrected


@pytest.mark.parametrize("command", ("restore", "query", "history"))
def test_existing_store_is_required_and_never_created_by_read_or_restore(
    command: str, tmp_path: Path
) -> None:
    db = tmp_path / "missing" / "nav.sqlite3"
    result = CliRunner().invoke(cli.app, _command(command, db))
    assert result.exit_code == 66
    assert result.stdout == ""
    assert "NAV 저장 오류" in result.stderr
    assert not db.exists()


@pytest.mark.parametrize("through", ("20260109", "2026-1-09", "2026-02-30", "today"))
def test_restore_requires_an_explicit_real_iso_date_before_opening_store(
    through: str, tmp_path: Path
) -> None:
    arguments = _command("restore", tmp_path / "absent.sqlite3")
    arguments[-1] = through
    result = CliRunner().invoke(cli.app, arguments)
    assert result.exit_code == 65
    assert result.stdout == ""


@pytest.mark.parametrize(
    "malformed",
    (
        b'{"schema_version":"1", "schema_version":"1"}',
        b'{"schema_version":"1", "environment":"development", "series_id":"x",'
        b' "days":[{"date":"2026-01-05", "ledger_complete":true,'
        b' "prices":{"SYN001":1000.25}, "benchmark_close":"5000", "source_ref":"test"}]}',
        b'{"private-secret":"synthetic-only-token"',
    ),
)
def test_invalid_input_is_safe_and_does_not_create_database(
    malformed: bytes, tmp_path: Path
) -> None:
    input_path = tmp_path / "invalid.json"
    input_path.write_bytes(malformed)
    db = tmp_path / "private" / "nav.sqlite3"
    result = CliRunner().invoke(cli.app, _import(db, input_path))
    assert result.exit_code == 65
    assert result.stdout == ""
    assert "synthetic-only-token" not in result.stderr
    assert not db.exists()


def test_unreadable_input_is_input_error_not_unexpected_error(tmp_path: Path) -> None:
    db = tmp_path / "private" / "nav.sqlite3"
    result = CliRunner().invoke(cli.app, _import(db, tmp_path / "absent.json"))
    assert result.exit_code == 65
    assert result.stdout == ""
    assert not db.exists()


@pytest.mark.parametrize(
    ("error", "exit_code", "message"),
    (
        (NavError("synthetic-sensitive-value"), 65, "NAV 입력·계산 오류"),
        (NavStorageError("synthetic-sensitive-value"), 66, "NAV 저장 오류"),
        (RuntimeError("synthetic-sensitive-value"), 70, "예기치 않은 오류"),
        (KeyboardInterrupt(), 130, "안전하게 종료"),
    ),
)
def test_cli_errors_never_echo_raw_exception_details(
    error: BaseException,
    exit_code: int,
    message: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(payload: bytes) -> None:
        raise error

    monkeypatch.setattr(nav_cli, "parse_bundle_bytes", fail)
    result = CliRunner().invoke(
        cli.app, _import(tmp_path / "private" / "nav.sqlite3", EXAMPLES / "01-seed.json")
    )
    assert result.exit_code == exit_code
    assert result.stdout == ""
    assert message in result.stderr
    assert "synthetic-sensitive-value" not in result.stderr


@pytest.mark.parametrize("option", ("--db", "--series", "--environment", "--through"))
def test_restore_never_defaults_required_storage_identity_or_date(
    option: str, tmp_path: Path
) -> None:
    arguments = _command("restore", tmp_path / "missing.sqlite3")
    position = arguments.index(option)
    del arguments[position : position + 2]
    result = CliRunner().invoke(cli.app, arguments)
    assert result.exit_code == 2
    assert option in result.stderr


def test_invalid_environment_is_rejected_by_cli(tmp_path: Path) -> None:
    arguments = _command("query", tmp_path / "missing.sqlite3")
    arguments[-1] = "production"
    result = CliRunner().invoke(cli.app, arguments)
    assert result.exit_code == 2
    assert "--environment" in result.stderr
