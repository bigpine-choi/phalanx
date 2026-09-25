from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import httpx
import pytest
from allocation_input_helpers import AS_OF, CODES, create_inputs, make_view
from typer.testing import CliRunner

from phalanx.cli import app
from phalanx.kis import KisTokenManager
from phalanx.market_data.history.repository import SqliteHistoryRepository
from phalanx.portfolio.allocation_input.service import AllocationInputService

runner = CliRunner()


def args(path, db):
    return ["portfolio", "allocation-input", "--selection", str(path), "--history-db", str(db)]


@pytest.mark.parametrize("count,status", [(505, 0), (504, 2)])
def test_offline_cli_exact_output_and_immutable_sources(tmp_path, monkeypatch, count, status):
    repo, path, _, _ = create_inputs(tmp_path, make_view(counts=(count, count), failed=True))
    before = {p: p.read_bytes() for p in (repo.path, path)}

    def forbidden(*args, **kwargs):
        pytest.fail("allocation input accessed credentials, OAuth, HTTP, or wrote to history")

    monkeypatch.setattr("phalanx.config.load_kis_credentials", forbidden)
    monkeypatch.setattr("phalanx.market_data.history.application.load_kis_credentials", forbidden)
    monkeypatch.setattr(KisTokenManager, "get_access_token", forbidden)
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    monkeypatch.setattr(SqliteHistoryRepository, "create", forbidden)
    monkeypatch.setattr(SqliteHistoryRepository, "save_symbol", forbidden)
    connect = sqlite3.connect
    connects = []

    def read_only(database, **kwargs):
        assert "mode=ro" in database and kwargs["uri"] is True
        connects.append(database)
        return connect(database, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", read_only)
    output = tmp_path / "output" / "allocation-input.json"
    response = runner.invoke(app, [*args(path, repo.path), "--output", str(output)])
    assert response.exit_code == status, response.output
    assert not response.stderr
    assert response.stdout.encode() == output.read_bytes()
    raw = json.loads(response.stdout)
    assert raw["input_ready"] is (status == 0)
    assert (raw["matrix"] is None) is (status == 2)
    assert len(connects) == 1
    assert output.stat().st_mode & 0o777 == 0o600
    assert all(p.read_bytes() == payload for p, payload in before.items())


def test_single_file_read_and_single_hash_validation_per_selected_symbol(tmp_path, monkeypatch):
    repo, path, _, _ = create_inputs(tmp_path, make_view(failed=True))
    original_read = Path.read_bytes
    original_hash = __import__(
        "phalanx.domain.price_history", fromlist=["price_data_hash"]
    ).price_data_hash
    payload = path.read_bytes()
    reads, hashes = [], []

    def read_once(self):
        assert self == path
        reads.append(self)
        assert len(reads) == 1
        return original_read(self)

    def hash_once(bars):
        hashes.append(bars[0].stock_code)
        return original_hash(bars)

    monkeypatch.setattr(Path, "read_bytes", read_once)
    monkeypatch.setattr("phalanx.domain.price_history.price_data_hash", hash_once)
    result = AllocationInputService(repo).prepare(path)
    assert reads == [path] and hashes == list(CODES)
    assert result.selection_file_sha256 == hashlib.sha256(payload).hexdigest()


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("source_price_sha256", "0" * 64, "SOURCE_PRICE_HASH_MISMATCH"),
        ("ordinal", 5, "HISTORY_TARGET_MISMATCH"),
        ("target", None, "HISTORY_TARGET_MISMATCH"),
        ("discovery_run_id", "different-discovery", "HISTORY_INPUT_MISMATCH"),
        ("history_job_id", "b" * 32, "JOB_NOT_FOUND"),
    ],
)
def test_selection_db_link_mismatches_are_input_errors(tmp_path, field, value, code):
    repo, path, _, _ = create_inputs(tmp_path)
    raw = json.loads(path.read_bytes())
    if field in ("history_job_id", "discovery_run_id"):
        raw["source"][field] = value
    elif field == "target":
        raw["candidates"][0]["target"]["name"] = "different frozen target"
    else:
        raw["candidates"][0][field] = value
    path.write_bytes(json.dumps(raw).encode())
    response = runner.invoke(app, args(path, repo.path))
    assert response.exit_code == 65, response.output
    assert code in response.stderr and not response.stdout


def mutate_db(repo, mutate, *, ordinal=0, job=False):
    with sqlite3.connect(repo.path) as connection:
        if job:
            raw = json.loads(connection.execute("SELECT job_json FROM jobs").fetchone()[0])
            mutate(raw)
            connection.execute("UPDATE jobs SET job_json=?", (json.dumps(raw),))
        else:
            raw = json.loads(
                connection.execute(
                    "SELECT state_json FROM symbols WHERE ordinal=?", (ordinal,)
                ).fetchone()[0]
            )
            mutate(raw)
            connection.execute(
                "UPDATE symbols SET state_json=? WHERE ordinal=?", (json.dumps(raw), ordinal)
            )


@pytest.mark.parametrize(
    "case",
    [
        "hash",
        "ordinal",
        "code",
        "duplicate",
        "reverse",
        "zero",
        "nonfinite",
        "float",
        "provider",
        "adjustment",
        "job_id",
    ],
)
def test_repository_corruption_keeps_existing_storage_error_classification(tmp_path, case):
    repo, path, _, _ = create_inputs(tmp_path)

    def mutate(raw):
        if case in ("provider", "adjustment", "job_id"):
            raw[case] = {"provider": "OTHER", "adjustment": "1", "job_id": "b" * 32}[case]
        elif case == "ordinal":
            raw["ordinal"] = 9
        elif case == "hash":
            raw["result"]["sha256"] = "0" * 64
        elif case == "duplicate":
            raw["result"]["bars"][1] = raw["result"]["bars"][0]
        elif case == "reverse":
            raw["result"]["bars"].reverse()
        else:
            bar = raw["result"]["bars"][0]
            if case == "code":
                bar["stock_code"] = "999999"
            else:
                bar["close_price"] = {"zero": "0", "nonfinite": "NaN", "float": 10000.0}[case]

    mutate_db(repo, mutate, job=case in ("provider", "adjustment", "job_id"))
    response = runner.invoke(app, args(path, repo.path))
    assert response.exit_code == 66, response.output
    assert "STORAGE_FAILED" in response.stderr and not response.stdout


def test_not_completed_selected_result_is_inconsistent_input(tmp_path):
    repo, path, _, _ = create_inputs(tmp_path)
    mutate_db(repo, lambda raw: raw.update(status="pending", result=None))
    response = runner.invoke(app, args(path, repo.path))
    assert response.exit_code == 65 and "HISTORY_RESULT_MISMATCH" in response.stderr


def test_unselected_corrupt_state_does_not_block_selected_prices(tmp_path):
    repo, path, _, _ = create_inputs(tmp_path, make_view(failed=True))
    with sqlite3.connect(repo.path) as connection:
        connection.execute("UPDATE symbols SET state_json='invalid' WHERE ordinal=2")
    assert AllocationInputService(repo).prepare(path).input_ready


def test_missing_file_db_and_invalid_json_have_distinct_errors(tmp_path):
    repo, path, _, _ = create_inputs(tmp_path)
    missing = tmp_path / "missing" / "history.sqlite3"
    response = runner.invoke(app, args(path, missing))
    assert response.exit_code == 66 and "STORAGE_FAILED" in response.stderr
    assert not missing.parent.exists()
    response = runner.invoke(app, args(tmp_path / "missing.json", repo.path))
    assert response.exit_code == 66 and "INPUT_READ_FAILED" in response.stderr
    path.write_bytes(b'{"secret":"SENSITIVE_TEST_MARKER","complete":NaN}')
    response = runner.invoke(app, args(path, repo.path))
    assert response.exit_code == 65 and "INVALID_SELECTION" in response.stderr
    assert "SENSITIVE_TEST_MARKER" not in response.output and "Traceback" not in response.output


@pytest.mark.parametrize("target", ["selection", "db", "existing"])
def test_existing_files_and_inputs_are_never_overwritten(tmp_path, target):
    repo, path, _, _ = create_inputs(tmp_path)
    existing = tmp_path / "existing.json"
    existing.write_bytes(b"keep existing bytes")
    output = {"selection": path, "db": repo.path, "existing": existing}[target]
    before = output.read_bytes()
    response = runner.invoke(app, [*args(path, repo.path), "--output", str(output)])
    assert response.exit_code == 66 and "OUTPUT_EXISTS" in response.stderr
    assert not response.stdout and output.read_bytes() == before


def test_atomic_write_failure_is_reported_without_success_stdout(tmp_path, monkeypatch):
    repo, path, _, _ = create_inputs(tmp_path)
    output = tmp_path / "output" / "allocation.json"

    def fail(*args):
        raise OSError("synthetic disk failure")

    monkeypatch.setattr("phalanx.portfolio.private_json_storage._write_all", fail)
    response = runner.invoke(app, [*args(path, repo.path), "--output", str(output)])
    assert response.exit_code == 66 and "OUTPUT_STORAGE_FAILED" in response.stderr
    assert not response.stdout and not output.exists()
    assert not list(output.parent.glob("*.tmp"))


@pytest.mark.parametrize("option", ["--selection", "--history-db"])
def test_required_cli_options_are_usage_errors_without_json(tmp_path, option):
    arguments = args(tmp_path / "missing.json", tmp_path / "missing.db")
    index = arguments.index(option)
    del arguments[index : index + 2]
    response = runner.invoke(app, arguments)
    assert response.exit_code == 2 and option in response.stderr and not response.stdout


@pytest.mark.parametrize(
    "option,value",
    [("--as-of", AS_OF.isoformat()), ("--job-id", "a" * 32), ("--minimum-observations", "1")],
)
def test_cli_does_not_offer_policy_or_provenance_overrides(tmp_path, option, value):
    response = runner.invoke(
        app, [*args(tmp_path / "missing", tmp_path / "missing"), option, value]
    )
    assert response.exit_code == 2 and not response.stdout
