from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from allocation_targets_helpers import target_inputs
from formation_room_helpers import saved_targets
from typer.testing import CliRunner

from phalanx.cli import app
from phalanx.portfolio.allocation_input.service import AllocationInputService
from phalanx.portfolio.allocation_targets.service import AllocationTargetsService
from phalanx.portfolio.constrained_erc import ConstrainedErcSolver
from phalanx.portfolio.dynamic_risk_model import DynamicRiskModel
from phalanx.portfolio.formation_room.parser import parse_targets
from phalanx.portfolio.formation_room.rendering import render_formation_room
from phalanx.portfolio.formation_room.service import FormationRoomService

runner = CliRunner()


@pytest.fixture(scope="module")
def saved_result(tmp_path_factory):
    directory = tmp_path_factory.mktemp("formation-cli")
    repository, selection, _, _ = target_inputs(directory)
    result = AllocationTargetsService(AllocationInputService(repository)).calculate(selection)
    assert result.complete
    return result.to_json_bytes()


def arguments(source, output):
    return ["portfolio", "formation-room", "--targets", str(source), "--output", str(output)]


def test_render_reads_once_is_offline_exact_and_preserves_source(
    tmp_path, monkeypatch, saved_result
):
    source = tmp_path / "targets.json"
    source.write_bytes(saved_result)
    output = tmp_path / "output" / "room.html"
    opened = []
    original_open = Path.open

    def observe_open(self, *args, **kwargs):
        if self == source:
            opened.append((args, kwargs))
        return original_open(self, *args, **kwargs)

    def forbidden(*args, **kwargs):
        pytest.fail("formation room accessed a calculation, database, network or credentials")

    monkeypatch.setattr(Path, "open", observe_open)
    monkeypatch.setattr(AllocationInputService, "prepare", forbidden)
    monkeypatch.setattr(DynamicRiskModel, "estimate", forbidden)
    monkeypatch.setattr(ConstrainedErcSolver, "solve_scenario", forbidden)
    monkeypatch.setattr("sqlite3.connect", forbidden)
    monkeypatch.setattr("phalanx.config.load_kis_credentials", forbidden)
    monkeypatch.setattr(httpx.Client, "request", forbidden)
    response = runner.invoke(app, arguments(source, output))
    assert response.exit_code == 0, response.output
    assert len(opened) == 1 and opened[0][0] == ("rb",)
    assert source.read_bytes() == saved_result
    model = parse_targets(saved_result, source_name=source.name)
    assert output.read_bytes() == render_formation_room(model)
    assert output.stat().st_mode & 0o777 == 0o600
    assert not list(output.parent.glob("*.tmp"))
    assert not list(tmp_path.glob("*.sqlite3"))


def test_existing_output_and_input_as_output_are_never_replaced(tmp_path, saved_result):
    source = tmp_path / "targets.json"
    source.write_bytes(saved_result)
    output = tmp_path / "existing.html"
    output.write_bytes(b"existing work")
    for destination in (source, output):
        response = runner.invoke(app, arguments(source, destination))
        assert response.exit_code == 66 and "OUTPUT_EXISTS" in response.stderr
        assert not response.stdout
    assert source.read_bytes() == saved_result
    assert output.read_bytes() == b"existing work"


@pytest.mark.parametrize("case", ["input_unavailable", "common_failure", "failed", "partial"])
def test_valid_failure_results_render_with_exit_zero(tmp_path, case):
    source = tmp_path / "targets.json"
    source.write_bytes(saved_targets(tmp_path, case))
    output = tmp_path / "room.html"
    response = runner.invoke(app, arguments(source, output))
    assert response.exit_code == 0, response.output
    assert output.read_bytes().startswith(b"<!doctype html>")


@pytest.mark.parametrize("kind", ["read", "invalid", "write", "internal"])
def test_cli_safe_failure_codes(tmp_path, monkeypatch, saved_result, kind):
    source = tmp_path / "targets.json"
    output = tmp_path / "room.html"
    source.write_bytes(b'{"private-marker":' if kind == "invalid" else saved_result)
    if kind == "read":
        source.unlink()

    def fail(*args, **kwargs):
        raise OSError("private-marker")

    if kind == "write":
        monkeypatch.setattr("phalanx.portfolio.private_json_storage._write_all", fail)
    elif kind == "internal":
        monkeypatch.setattr(FormationRoomService, "generate", fail)
    response = runner.invoke(app, arguments(source, output))
    assert response.exit_code == {"read": 66, "invalid": 65, "write": 66, "internal": 70}[kind]
    assert not response.stdout and not output.exists()
    assert "private-marker" not in response.output and "Traceback" not in response.output
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("option", ["--targets", "--output"])
def test_required_options(option):
    values = arguments("input.json", "room.html")
    index = values.index(option)
    del values[index : index + 2]
    response = runner.invoke(app, values)
    assert response.exit_code == 2 and option in response.stderr


def test_renderer_escapes_json_island_and_does_not_copy_matrices(saved_result):
    attack = "</script><script>window.pwned=1</script>&<>\u2028\u2029{{ROOM_JS}}"
    model = parse_targets(saved_result, source_name=attack)
    html = render_formation_room(model).decode("utf-8")
    assert attack not in html and "\\u003c/script\\u003e" in html
    assert "\\u0026" in html and "\\u2028" in html and "\\u2029" in html
    assert "annualized_covariance" not in html and '"matrix"' not in html
    start = html.index('<script id="room-data" type="application/json">')
    data = html[start:].split(">", 1)[1].split("</script>", 1)[0]
    projected = json.loads(data)
    assert projected["source_name"] == attack
    assert projected == model.to_payload()
