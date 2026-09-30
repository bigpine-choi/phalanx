"""Replay and post-commit read evidence must survive the allocation boundary."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

if sys.platform == "win32":
    pytest.skip("SQLite history repository imports Unix-only fcntl", allow_module_level=True)

from allocation_targets_helpers import AS_OF, CODES, target_inputs
from feature_helpers import NOW

from phalanx.domain.candidate_selection import SelectionMetric, SelectionPolicy
from phalanx.domain.price_history import price_data_hash
from phalanx.market_data.history.read_receipt import HistoryReadReceiptService
from phalanx.market_data.history.repository import SqliteHistoryRepository
from phalanx.portfolio.allocation_input.errors import AllocationInputError
from phalanx.portfolio.allocation_input.service import AllocationInputService
from phalanx.portfolio.allocation_targets.service import AllocationTargetsService
from phalanx.selection.history_replay import HistoryReplayService

READ_STARTED = NOW + timedelta(minutes=2)
READ_COMPLETED = NOW + timedelta(minutes=3)
DECISION_AT = NOW + timedelta(minutes=4)
REPLAYED_AT = NOW + timedelta(minutes=5)


@dataclass(frozen=True)
class ReplayCase:
    repository: SqliteHistoryRepository
    selection_path: Path
    replay_bytes: bytes
    receipt_bytes: bytes
    selected_codes: tuple[str, ...]


def _case(directory: Path, *, top: int = 6) -> ReplayCase:
    repository, selection_path, selection, view = target_inputs(
        directory, top=top, fetch_receipts=True
    )
    times = iter((READ_STARTED, READ_COMPLETED))
    receipt = HistoryReadReceiptService(clock=lambda: next(times)).capture(
        repository, view.job.job_id, codes=CODES
    )
    receipt_bytes = receipt.to_json_bytes()
    replay = HistoryReplayService(clock=lambda: REPLAYED_AT).run(
        repository,
        view.job.job_id,
        AS_OF,
        DECISION_AT,
        SelectionPolicy(metric=SelectionMetric.RETURN_60, top=top, max_age_days=7),
        codes=CODES,
        read_receipt_bytes=receipt_bytes,
    )
    assert replay.selection.selected_codes == selection.selected_codes
    return ReplayCase(
        repository=repository,
        selection_path=selection_path,
        replay_bytes=replay.to_json_bytes(),
        receipt_bytes=receipt_bytes,
        selected_codes=selection.selected_codes,
    )


@pytest.fixture(scope="module")
def full_case(tmp_path_factory: pytest.TempPathFactory) -> ReplayCase:
    return _case(tmp_path_factory.mktemp("allocation-replay"))


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")


def _alter_stored_price(repository: SqliteHistoryRepository, code: str) -> None:
    job, states = repository.read_selected("a" * 32, codes=(code,))
    state = states[0]
    assert state.result is not None
    bar = state.result.bars[0]
    changed_close = bar.close_price + Decimal("1")
    changed_bar = bar.model_copy(
        update={
            "open_price": changed_close,
            "high_price": changed_close,
            "low_price": changed_close,
            "close_price": changed_close,
        }
    )
    changed_bars = (changed_bar, *state.result.bars[1:])
    changed_result = state.result.model_copy(
        update={"bars": changed_bars, "sha256": price_data_hash(changed_bars)}
    )
    changed_state = state.model_copy(update={"result": changed_result})
    with sqlite3.connect(repository.path) as connection:
        connection.execute(
            "UPDATE symbols SET state_json=? WHERE job_id=? AND ordinal=?",
            (changed_state.model_dump_json(), job.job_id, state.ordinal),
        )
    # This is a coherent changed history, not a malformed SQLite fixture.
    _, reread = repository.read_selected(job.job_id, codes=(code,))
    assert reread[0].result == changed_result


def test_replay_evidence_reaches_prepared_input_and_all_target_scenarios(
    full_case: ReplayCase,
) -> None:
    case = full_case
    service = AllocationInputService(case.repository)
    prepared = service.prepare_replay_bytes(case.replay_bytes, case.receipt_bytes)
    assert prepared.input_ready and prepared.selected_codes == case.selected_codes
    provenance = prepared.replay_provenance
    assert provenance is not None
    assert provenance.replay_file_sha256 == hashlib.sha256(case.replay_bytes).hexdigest()
    assert provenance.read_receipt_file_sha256 == hashlib.sha256(case.receipt_bytes).hexdigest()
    assert provenance.history_job_id == "a" * 32
    assert provenance.decision_at == DECISION_AT
    assert provenance.replayed_at == REPLAYED_AT
    assert provenance.read_completed_at == READ_COMPLETED
    assert provenance.local_snapshot_read_before_decision_confirmed is True
    assert provenance.point_in_time_backtest_guaranteed is False

    targets = AllocationTargetsService(service).calculate_replay_bytes(
        case.replay_bytes, case.receipt_bytes
    )
    assert targets.complete and targets.succeeded_count == 4
    assert targets.prepared.replay_provenance == provenance
    raw = json.loads(targets.to_json_bytes())
    assert raw["prepared"]["replay_provenance"] == provenance.model_dump(mode="json")
    assert all(item["target"] is not None for item in raw["scenarios"])


def test_existing_selection_route_keeps_its_original_serialized_shape(
    full_case: ReplayCase,
) -> None:
    old = AllocationInputService(full_case.repository).prepare(full_case.selection_path)
    assert old.input_ready
    assert "replay_provenance" not in json.loads(old.to_json_bytes())


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_key",
        "nonfinite_number",
        "missing_field",
        "missing_embedded_receipt",
        "wrong_receipt_file_hash",
        "wrong_job",
        "wrong_selected_source_price",
        "forged_row_with_matching_aggregate_hash",
    ],
)
def test_replay_json_tampering_fails_before_allocation(
    full_case: ReplayCase, mutation: str
) -> None:
    case = full_case
    raw = json.loads(case.replay_bytes)
    if mutation == "duplicate_key":
        payload = b'{"schema_version":"1",' + case.replay_bytes[1:]
    elif mutation == "nonfinite_number":
        payload = b'{"unexpected":NaN,' + case.replay_bytes[1:]
    else:
        if mutation == "missing_field":
            del raw["receipt_check"]
        elif mutation == "missing_embedded_receipt":
            raw["read_receipt"] = None
        elif mutation == "wrong_receipt_file_hash":
            raw["read_receipt_sha256"] = "0" * 64
        elif mutation == "wrong_job":
            raw["selection"]["source"]["history_job_id"] = "b" * 32
        elif mutation == "wrong_selected_source_price":
            selected = next(c for c in raw["selection"]["candidates"] if c["status"] == "selected")
            selected["source_price_sha256"] = "0" * 64
        elif mutation == "forged_row_with_matching_aggregate_hash":
            raw["rows"][0]["row_sha256"] = "0" * 64
            encoded = json.dumps(
                raw["rows"], sort_keys=True, ensure_ascii=True, separators=(",", ":")
            ).encode("ascii")
            raw["row_evidence_sha256"] = hashlib.sha256(encoded).hexdigest()
        payload = _json_bytes(raw)
    with pytest.raises(AllocationInputError):
        AllocationInputService(case.repository).prepare_replay_bytes(payload, case.receipt_bytes)


def test_sidecar_receipt_must_match_exact_embedded_file_bytes(full_case: ReplayCase) -> None:
    same_content_different_bytes = json.dumps(json.loads(full_case.receipt_bytes)).encode("utf-8")
    assert same_content_different_bytes != full_case.receipt_bytes
    with pytest.raises(AllocationInputError):
        AllocationInputService(full_case.repository).prepare_replay_bytes(
            full_case.replay_bytes, same_content_different_bytes
        )


def test_replay_without_read_confirmation_is_rejected(tmp_path: Path) -> None:
    case = _case(tmp_path)
    raw = json.loads(case.replay_bytes)
    raw["read_receipt"] = None
    raw["read_receipt_sha256"] = None
    raw["read_receipt_content_sha256"] = None
    raw["local_snapshot_read_before_decision_confirmed"] = False
    raw["receipt_check"] = "local_fetch_completed_before_decision"
    with pytest.raises(AllocationInputError):
        AllocationInputService(case.repository).prepare_replay_bytes(
            _json_bytes(raw), case.receipt_bytes
        )


def test_selected_price_changed_after_replay_is_rejected(tmp_path: Path) -> None:
    case = _case(tmp_path)
    _alter_stored_price(case.repository, case.selected_codes[0])
    with pytest.raises(AllocationInputError):
        AllocationInputService(case.repository).prepare_replay_bytes(
            case.replay_bytes, case.receipt_bytes
        )


def test_unselected_price_changed_after_replay_is_rejected(tmp_path: Path) -> None:
    case = _case(tmp_path, top=5)
    code = next(code for code in CODES if code not in case.selected_codes)
    _alter_stored_price(case.repository, code)
    with pytest.raises(AllocationInputError):
        AllocationInputService(case.repository).prepare_replay_bytes(
            case.replay_bytes, case.receipt_bytes
        )


@pytest.mark.skipif(sys.platform == "win32", reason="root CLI imports Unix-only history writer")
def test_allocation_targets_cli_accepts_replay_evidence_and_keeps_inputs(
    tmp_path: Path,
) -> None:
    from typer.testing import CliRunner

    from phalanx.cli import app

    case = _case(tmp_path)
    replay_path = tmp_path / "replay.json"
    receipt_path = tmp_path / "receipt.json"
    output_path = tmp_path / "targets.json"
    replay_path.write_bytes(case.replay_bytes)
    receipt_path.write_bytes(case.receipt_bytes)
    before = {p: p.read_bytes() for p in (replay_path, receipt_path, case.repository.path)}
    response = CliRunner().invoke(
        app,
        [
            "portfolio",
            "allocation-targets",
            "--replay-history",
            str(replay_path),
            "--read-receipt",
            str(receipt_path),
            "--history-db",
            str(case.repository.path),
            "--output",
            str(output_path),
        ],
    )
    assert response.exit_code == 0, response.output
    assert response.stdout.encode("utf-8") == output_path.read_bytes()
    assert json.loads(response.stdout)["prepared"]["replay_provenance"] is not None
    assert all(path.read_bytes() == data for path, data in before.items())


@pytest.mark.skipif(sys.platform == "win32", reason="root CLI imports Unix-only history writer")
@pytest.mark.parametrize("command", ["allocation-input", "allocation-targets"])
def test_replay_cli_requires_the_matching_sidecar(tmp_path: Path, command: str) -> None:
    from typer.testing import CliRunner

    from phalanx.cli import app

    case = _case(tmp_path)
    replay_path = tmp_path / "replay.json"
    replay_path.write_bytes(case.replay_bytes)
    response = CliRunner().invoke(
        app,
        [
            "portfolio",
            command,
            "--replay-history",
            str(replay_path),
            "--history-db",
            str(case.repository.path),
        ],
    )
    assert response.exit_code != 0
    assert not response.stdout
