"""Godot's research view consumes bounded, display-only saved-result projections."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from formation_room_helpers import saved_targets

from phalanx.portfolio.allocation_targets.game_projection import project_saved_targets
from phalanx.portfolio.formation_room.errors import FormationRoomInputError

BRIDGE = Path(__file__).resolve().parents[1] / "game" / "tools" / "allocation_projection_bridge.py"
HEX = "a" * 64


@pytest.fixture(scope="module")
def targets(tmp_path_factory: pytest.TempPathFactory) -> bytes:
    return saved_targets(tmp_path_factory.mktemp("game-allocation-projection"))


def _with_replay(payload: bytes) -> bytes:
    raw = json.loads(payload)
    prepared = raw["prepared"]
    prepared["selection_file_sha256"] = None
    prepared["replay_provenance"] = {
        "evidence_kind": "recomputed_history_replay_with_local_read_receipt_v1",
        "replay_file_sha256": HEX,
        "selection_content_sha256": "b" * 64,
        "read_receipt_file_sha256": "c" * 64,
        "read_receipt_content_sha256": "d" * 64,
        "row_evidence_sha256": "e" * 64,
        "features_sha256": "f" * 64,
        "history_job_id": prepared["history_job_id"],
        "as_of": prepared["selection_as_of"],
        "selected_codes": prepared["selected_codes"],
        "read_completed_at": "2026-08-20T09:00:00+09:00",
        "decision_at": "2026-08-20T09:01:00+09:00",
        "replayed_at": "2026-08-20T09:02:00+09:00",
        "local_snapshot_read_before_decision_confirmed": True,
        "vendor_release_time_verified": False,
        "point_in_time_backtest_guaranteed": False,
    }
    return json.dumps(raw, ensure_ascii=False, sort_keys=True).encode()


def test_legacy_saved_result_projects_compact_read_only_view(targets: bytes) -> None:
    result = project_saved_targets(targets, source_name="saved-targets.json")
    assert result["source_semantics"] == "saved_file_unverified"
    assert result["source_sha256"] == hashlib.sha256(targets).hexdigest()
    assert result["schema"] == "phalanx.game_research_allocation_projection.v1"
    assert result["status"] == "succeeded"
    assert result["succeeded_count"] == 4
    assert result["selected_codes"]
    assert result["observation_count"] == 504
    assert result["reference_price_date"] == result["calculation_date"]
    assert result["replay_provenance"] is None
    scenarios = result["scenarios"]
    assert isinstance(scenarios, list) and len(scenarios) == 4
    assert all(item["status"] == "succeeded" for item in scenarios)
    assert all(
        [holding["code"] for holding in item["holdings"]] == result["selected_codes"]
        for item in scenarios
    )
    assert "matrix" not in json.dumps(result)
    assert "account_execution_target" not in result


def test_replay_provenance_is_displayed_as_file_reported_evidence(targets: bytes) -> None:
    replay = _with_replay(targets)
    result = project_saved_targets(replay, source_name="replay-targets.json")
    evidence = result["replay_provenance"]
    assert isinstance(evidence, dict)
    assert evidence["read_receipt_file_sha256"] == "c" * 64
    assert evidence["read_completed_at"] == "2026-08-20T09:00:00+09:00"
    assert result["source_semantics"] == "saved_file_unverified"


@pytest.mark.parametrize(
    "field,value",
    [
        ("history_job_id", "0" * 32),
        ("selected_codes", ["000001"]),
        ("read_receipt_file_sha256", "bad"),
        ("local_snapshot_read_before_decision_confirmed", False),
        ("decision_at", "2026-08-20T08:59:00+09:00"),
        ("vendor_release_time_verified", True),
    ],
)
def test_incoherent_replay_evidence_is_rejected(
    targets: bytes, field: str, value: object
) -> None:
    raw = json.loads(_with_replay(targets))
    raw["prepared"]["replay_provenance"][field] = value
    with pytest.raises(FormationRoomInputError):
        project_saved_targets(json.dumps(raw).encode(), source_name="bad.json")


def test_bridge_runs_from_checkout_and_returns_bounded_envelope(
    targets: bytes, tmp_path: Path
) -> None:
    source = tmp_path / "targets.json"
    output = tmp_path / "result.json"
    source.write_bytes(targets)
    before = source.read_bytes()
    completed = subprocess.run(
        [sys.executable, str(BRIDGE), str(source), str(output), "123-456"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert source.read_bytes() == before
    assert output.stat().st_size <= 512 * 1024
    envelope = json.loads(output.read_bytes())
    assert envelope["request_id"] == "123-456" and envelope["ok"] is True
    assert envelope["payload"]["source_sha256"] == hashlib.sha256(targets).hexdigest()
    assert not output.with_suffix(".json.pending").exists()


def test_bridge_rejects_invalid_source_without_exposing_contents(tmp_path: Path) -> None:
    source = tmp_path / "secret.json"
    output = tmp_path / "result.json"
    source.write_text('{"private":"TOP_SECRET"}', encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(BRIDGE), str(source), str(output), "123-457"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        timeout=30,
    )
    assert completed.returncode == 0
    envelope = json.loads(output.read_bytes())
    assert envelope == {
        "request_id": "123-457",
        "ok": False,
        "payload": {},
        "error": "INVALID_TARGETS",
    }
    assert b"TOP_SECRET" not in output.read_bytes()


def test_bridge_never_overwrites_source(targets: bytes, tmp_path: Path) -> None:
    source = tmp_path / "targets.json"
    source.write_bytes(targets)
    completed = subprocess.run(
        [sys.executable, str(BRIDGE), str(source), str(source), "123-458"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        timeout=30,
    )
    assert completed.returncode == 2
    assert source.read_bytes() == targets
