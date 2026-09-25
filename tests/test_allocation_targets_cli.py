from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from allocation_targets_helpers import target_inputs
from typer.testing import CliRunner

from phalanx.cli import app
from phalanx.kis import KisTokenManager
from phalanx.portfolio.allocation_input.errors import AllocationInputError
from phalanx.portfolio.allocation_targets.service import AllocationTargetsService
from phalanx.portfolio.constrained_erc import ConstrainedErcSolver
from phalanx.portfolio.errors import ConstrainedErcCcdConvergenceError

runner = CliRunner()


def args(path, db):
    return ["portfolio", "allocation-targets", "--selection", str(path), "--history-db", str(db)]


@pytest.mark.parametrize(
    "options,status,exit_code",
    [
        ({}, "succeeded", 0),
        ({"count": 504}, "input_unavailable", 2),
        ({"size": 4}, "failed", 2),
        ({"degenerate": True}, "common_failure", 2),
    ],
)
def test_cli_exact_bytes_safe_offline_scope_and_immutable_inputs(
    tmp_path, monkeypatch, options, status, exit_code
):
    repo, path, _, _ = target_inputs(tmp_path, **options)
    original = {p: p.read_bytes() for p in (repo.path, path, tmp_path / "features.json")}

    def forbidden(*args, **kwargs):
        pytest.fail(
            "single-date allocation targets accessed network/credentials or ran rolling research"
        )

    monkeypatch.setattr("phalanx.config.load_kis_credentials", forbidden)
    monkeypatch.setattr("phalanx.market_data.history.application.load_kis_credentials", forbidden)
    monkeypatch.setattr(KisTokenManager, "get_access_token", forbidden)
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    monkeypatch.setattr(
        "phalanx.portfolio.constrained_erc_research.conduct_constrained_erc_research", forbidden
    )
    monkeypatch.setattr("phalanx.portfolio.allocation_backtest.run_allocation_backtest", forbidden)
    output = tmp_path / "output" / "targets.json"
    response = runner.invoke(app, [*args(path, repo.path), "--output", str(output)])
    assert response.exit_code == exit_code, response.output
    assert not response.stderr
    assert response.stdout.encode() == output.read_bytes()
    assert json.loads(response.stdout)["status"] == status
    assert all(p.read_bytes() == data for p, data in original.items())
    assert output.stat().st_mode & 0o777 == 0o600


def test_partial_scenario_failure_is_saved_with_exit_two(tmp_path, monkeypatch):
    repo, path, _, _ = target_inputs(tmp_path)
    solve = ConstrainedErcSolver.solve_scenario

    def fail_one(self, scenario, *, as_of_date):
        if scenario.kind == "fast_iewma":
            raise ConstrainedErcCcdConvergenceError("SENSITIVE_TEST_MARKER")
        return solve(self, scenario, as_of_date=as_of_date)

    monkeypatch.setattr(ConstrainedErcSolver, "solve_scenario", fail_one)
    output = tmp_path / "targets.json"
    response = runner.invoke(app, [*args(path, repo.path), "--output", str(output)])
    assert response.exit_code == 2
    raw = json.loads(response.stdout)
    assert raw["status"] == "partial" and raw["succeeded_count"] == 3
    assert raw["scenarios"][1]["target"] is None
    assert response.stdout.encode() == output.read_bytes()
    assert "SENSITIVE_TEST_MARKER" not in response.output


@pytest.mark.parametrize("target", ["selection", "db", "existing"])
def test_output_never_overwrites_existing_input_or_file(tmp_path, target):
    repo, path, _, _ = target_inputs(tmp_path)
    existing = tmp_path / "existing.json"
    existing.write_bytes(b"preserve user data")
    output = {"selection": path, "db": repo.path, "existing": existing}[target]
    before = output.read_bytes()
    response = runner.invoke(app, [*args(path, repo.path), "--output", str(output)])
    assert response.exit_code == 66 and "OUTPUT_EXISTS" in response.stderr
    assert not response.stdout and output.read_bytes() == before


def test_storage_failure_propagates_without_partial_json(tmp_path, monkeypatch):
    repo, path, _, _ = target_inputs(tmp_path)
    output = tmp_path / "output" / "targets.json"

    def fail(*args):
        raise OSError("SENSITIVE_TEST_MARKER")

    monkeypatch.setattr("phalanx.portfolio.private_json_storage._write_all", fail)
    response = runner.invoke(app, [*args(path, repo.path), "--output", str(output)])
    assert response.exit_code == 66 and "OUTPUT_STORAGE_FAILED" in response.stderr
    assert not response.stdout and not output.exists()
    assert not list(output.parent.glob("*.tmp"))
    assert "SENSITIVE_TEST_MARKER" not in response.output


@pytest.mark.parametrize(
    "case,expected,code",
    [
        ("missing-selection", 66, "INPUT_READ_FAILED"),
        ("missing-db", 66, "STORAGE_FAILED"),
        ("input-error", 65, "INVALID_SELECTION"),
        ("internal-error", 2, "ALLOCATION_TARGETS_INTERNAL_ERROR"),
    ],
)
def test_existing_input_errors_keep_exit_semantics_and_internal_errors_are_safe(
    tmp_path, monkeypatch, case, expected, code
):
    repo, path, _, _ = target_inputs(tmp_path)
    db = repo.path
    if case == "missing-selection":
        path = tmp_path / "missing.json"
    elif case == "missing-db":
        db = tmp_path / "missing" / "history.sqlite3"
    else:

        def fail(*args):
            if case == "input-error":
                raise AllocationInputError()
            raise RuntimeError("SENSITIVE_TEST_MARKER")

        monkeypatch.setattr(AllocationTargetsService, "calculate", fail)
    response = runner.invoke(app, args(path, db))
    assert response.exit_code == expected and code in response.stderr
    assert not response.stdout and "SENSITIVE_TEST_MARKER" not in response.output
    assert "Traceback" not in response.output
    assert not (tmp_path / "missing").exists()


@pytest.mark.parametrize("option", ["--selection", "--history-db"])
def test_required_options_are_usage_errors(option):
    arguments = args(Path("missing"), Path("missing"))
    index = arguments.index(option)
    del arguments[index : index + 2]
    response = runner.invoke(app, arguments)
    assert response.exit_code == 2 and not response.stdout and option in response.stderr
