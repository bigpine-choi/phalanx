from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from allocation_targets_helpers import CODES, target_inputs
from typer.testing import CliRunner

from phalanx.cli import app
from phalanx.portfolio.allocation_input.service import AllocationInputService
from phalanx.portfolio.allocation_input.validation import parse_selection
from phalanx.portfolio.allocation_targets.service import AllocationTargetsService
from phalanx.portfolio.formation_room.errors import FormationRoomInputError
from phalanx.portfolio.formation_room.model import FormationRoomPresentation
from phalanx.portfolio.formation_room.parser import parse_targets
from phalanx.portfolio.formation_room.rendering import render_formation_room
from phalanx.portfolio.formation_room.selection import MAX_SELECTION_BYTES
from phalanx.portfolio.formation_room.service import FormationRoomService

runner = CliRunner()
ATTACK = "</script><script>window.nameAttack=1</script>&<>\u2028\u2029"
NAMES = dict(
    zip(CODES, [None, "  ", "동일 이름", "동일 이름", "긴 종목 이름 " * 80, ATTACK], strict=True)
)


@pytest.fixture(scope="module")
def named_pipeline(tmp_path_factory):
    directory = tmp_path_factory.mktemp("formation-selection")
    repo, path, selection, _ = target_inputs(directory, names=NAMES)
    result = AllocationTargetsService(AllocationInputService(repo)).calculate(path)
    assert result.complete
    return result.to_json_bytes(), path.read_bytes(), selection


def encode(raw):
    return json.dumps(raw, ensure_ascii=False).encode()


def linked(targets, selection):
    return parse_targets(targets, source_name="targets.json", selection_payload=selection)


def test_real_selection_names_follow_ranked_code_identity_and_raw_file_hash(named_pipeline):
    targets, selection, selected = named_pipeline
    model = linked(targets, selection)
    assert model.selection_linked is True
    assert model.selected_codes == list(selected.selected_codes)
    assert model.selected_codes != list(CODES)
    for symbol in model.symbols:
        name = NAMES[symbol["code"]]
        expected = name if name and name.strip() else None
        assert symbol["name"] == expected
        assert symbol["name_status"] == (
            "verified_selection" if expected is not None else "unconfirmed"
        )
    assert hashlib.sha256(selection).hexdigest() != selected.source.input_sha256
    raw = json.loads(targets)
    assert raw["prepared"]["selection_file_sha256"] == hashlib.sha256(selection).hexdigest()
    raw["prepared"]["selection_file_sha256"] = selected.source.input_sha256
    with pytest.raises(FormationRoomInputError):
        linked(encode(raw), selection)


def test_optional_absent_selection_is_backward_compatible_and_never_guesses_names(named_pipeline):
    targets, _, _ = named_pipeline
    model = parse_targets(targets, source_name="synthetic-demo-targets.json")
    assert model.selection_linked is False
    assert all(
        item["name"] is None and item["name_status"] == "unconfirmed" for item in model.symbols
    )
    assert model.presentation.synthetic_demo is False
    assert model.to_payload()["presentation"] == {"synthetic_demo": False}


def test_presentation_label_is_explicit_and_does_not_modify_source_evidence(named_pipeline):
    targets, selection, _ = named_pipeline
    baseline = linked(targets, selection)
    marked = parse_targets(
        targets,
        source_name="targets.json",
        selection_payload=selection,
        presentation=FormationRoomPresentation(synthetic_demo=True),
    )
    expected = baseline.to_payload()
    expected["presentation"] = {"synthetic_demo": True}
    assert marked.to_payload() == expected
    with pytest.raises(ValueError):
        FormationRoomPresentation(synthetic_demo=1)


def test_hash_mismatch_rejected_before_selection_parser_is_called(named_pipeline, monkeypatch):
    targets, selection, _ = named_pipeline

    def forbidden(*args, **kwargs):
        pytest.fail("selection bytes were parsed before their raw hash matched")

    monkeypatch.setattr("phalanx.portfolio.formation_room.selection.parse_selection", forbidden)
    with pytest.raises(FormationRoomInputError):
        linked(targets, selection + b"\n")
    with pytest.raises(FormationRoomInputError):
        linked(targets, b"invalid PRIVATE_MARKER")


@pytest.mark.parametrize("payload", [b"", b"{}", b"[]", b"\xff", b'{"x":NaN}', b'{"x":1,"x":2}'])
def test_matching_hash_does_not_bypass_existing_selection_validation(named_pipeline, payload):
    targets, _, _ = named_pipeline
    raw = json.loads(targets)
    raw["prepared"]["selection_file_sha256"] = hashlib.sha256(payload).hexdigest()
    with pytest.raises(FormationRoomInputError) as error:
        linked(encode(raw), payload)
    assert "PRIVATE_MARKER" not in str(error.value)


@pytest.mark.parametrize(
    "case",
    [
        "source",
        "policy",
        "completion",
        "date",
        "reference",
        "history",
        "discovery",
        "ordinal",
        "price_hash",
        "feature_hash",
    ],
)
def test_matched_selection_bytes_still_require_target_provenance_links(named_pipeline, case):
    targets, selection, _ = named_pipeline
    raw = json.loads(targets)
    prepared = raw["prepared"]
    if case == "source":
        prepared["selection_source"]["input_sha256"] = "0" * 64
    elif case == "policy":
        prepared["selection_policy"]["max_age_days"] += 1
    elif case == "completion":
        prepared["selection_completion"].update(evaluation_complete=False, complete=False)
    elif case == "date":
        raw["selection_as_of"] = "2026-08-23"
        prepared["selection_as_of"] = "2026-08-23"
        prepared["selection_source"]["as_of"] = "2026-08-23"
    elif case == "reference":
        prepared["selection_source"]["calculated_at"] = "2026-09-14T00:00:00Z"
    elif case == "history":
        prepared["history_job_id"] = "b" * 32
    elif case == "discovery":
        prepared["discovery_run_id"] = "other-run"
    elif case == "ordinal":
        prepared["symbols"][0]["ordinal"] = 100
    elif case == "price_hash":
        prepared["symbols"][0]["verified_source_price_sha256"] = "0" * 64
    else:
        prepared["symbols"][0]["selection_consumed_input_sha256"] = "0" * 64
    # Base presentation remains coherent; optional provenance catches these differences.
    parse_targets(encode(raw), source_name="targets.json")
    with pytest.raises(FormationRoomInputError):
        linked(encode(raw), selection)


def test_reordered_valid_target_projection_cannot_link_to_original_selection(named_pipeline):
    targets, selection, _ = named_pipeline
    raw = json.loads(targets)
    prepared = raw["prepared"]
    raw["selected_codes"].reverse()
    prepared["selected_codes"].reverse()
    prepared["symbols"].reverse()
    prepared["matrix"]["stock_codes"].reverse()
    raw["risk_snapshot"]["stock_codes"].reverse()
    for scenario in raw["risk_snapshot"]["scenarios"]:
        scenario["stock_codes"].reverse()
    for scenario in raw["scenarios"]:
        scenario["target"]["stock_codes"].reverse()
    parse_targets(encode(raw), source_name="targets.json")
    with pytest.raises(FormationRoomInputError):
        linked(encode(raw), selection)


def test_selection_reference_endpoint_is_compared_independently(named_pipeline):
    targets, selection_bytes, _ = named_pipeline
    raw = json.loads(targets)
    selection = json.loads(selection_bytes)
    for candidate in selection["candidates"]:
        candidate["used_end"] = "2026-08-19"
        candidate["calendar_days_since_last_observation"] = 1
        candidate["selected_feature"]["window_end"] = "2026-08-19"
    selection["reference_price_date"] = "2026-08-19"
    changed = encode(selection)
    assert parse_selection(changed).reference_price_date.isoformat() == "2026-08-19"
    raw["prepared"]["selection_file_sha256"] = hashlib.sha256(changed).hexdigest()
    with pytest.raises(FormationRoomInputError):
        linked(encode(raw), changed)


def test_long_duplicate_script_and_missing_names_are_not_filtered_or_inferred(named_pipeline):
    targets, selection, _ = named_pipeline
    model = linked(targets, selection)
    names = [item["name"] for item in model.symbols]
    assert names.count("동일 이름") == 2 and names.count(None) == 2
    assert "긴 종목 이름 " * 80 in names and ATTACK in names
    html = render_formation_room(model).decode()
    assert ATTACK not in html and "\\u003c/script\\u003e" in html
    assert "\\u2028" in html and "\\u2029" in html
    island = html.split('<script id="room-data" type="application/json">', 1)[1].split(
        "</script>", 1
    )[0]
    assert json.loads(island)["symbols"] == model.symbols


def test_service_reads_each_source_once_with_limit_and_preserves_both(
    named_pipeline, tmp_path, monkeypatch
):
    targets, selection, _ = named_pipeline
    target_path, selection_path = tmp_path / "targets.json", tmp_path / "selection.json"
    target_path.write_bytes(targets)
    selection_path.write_bytes(selection)
    output = tmp_path / "room.html"
    original_open = Path.open
    reads, opens = [], []

    class OnceReader:
        def __init__(self, path, handle):
            self.path, self.handle = path, handle

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.handle.close()

        def read(self, size):
            reads.append((self.path, size))
            return self.handle.read(size)

    def tracked_open(self, *args, **kwargs):
        handle = original_open(self, *args, **kwargs)
        if self in (target_path, selection_path):
            opens.append((self, args))
            return OnceReader(self, handle)
        return handle

    with monkeypatch.context() as context:
        context.setattr(Path, "open", tracked_open)
        model = FormationRoomService().generate(target_path, output, selection=selection_path)
    assert [path for path, _ in opens] == [target_path, selection_path]
    assert all(args == ("rb",) for _, args in opens)
    assert reads == [(target_path, 32 * 1024 * 1024 + 1), (selection_path, MAX_SELECTION_BYTES + 1)]
    assert target_path.read_bytes() == targets and selection_path.read_bytes() == selection
    assert output.read_bytes() == render_formation_room(model)


def test_selection_size_guard_and_typed_provenance(named_pipeline, monkeypatch):
    targets, selection, _ = named_pipeline
    with monkeypatch.context() as context:
        context.setattr("phalanx.portfolio.formation_room.selection.MAX_SELECTION_BYTES", 16)
        with pytest.raises(FormationRoomInputError):
            linked(targets, selection)
    raw = json.loads(targets)
    raw["prepared"]["selection_source"]["features_complete"] = 1
    with pytest.raises(FormationRoomInputError):
        linked(encode(raw), selection)


@pytest.mark.parametrize(
    "case,expected", [("valid", 0), ("invalid", 65), ("missing", 66), ("existing", 66)]
)
def test_cli_optional_selection_returns_safe_codes(named_pipeline, tmp_path, case, expected):
    targets, selection, _ = named_pipeline
    source = tmp_path / "targets.json"
    chosen = tmp_path / "selection.json"
    destination = tmp_path / "room.html"
    source.write_bytes(targets)
    chosen.write_bytes(selection if case != "invalid" else b"PRIVATE_MARKER")
    if case == "missing":
        chosen.unlink()
    if case == "existing":
        destination.write_bytes(b"existing work")
    response = runner.invoke(
        app,
        [
            "portfolio",
            "formation-room",
            "--targets",
            str(source),
            "--selection",
            str(chosen),
            "--output",
            str(destination),
        ],
    )
    assert response.exit_code == expected, response.output
    assert "PRIVATE_MARKER" not in response.output and "Traceback" not in response.output
    assert source.read_bytes() == targets
    if case == "existing":
        assert destination.read_bytes() == b"existing work"
    elif expected:
        assert not destination.exists()


def test_linked_names_do_not_access_history_engines_or_network(
    named_pipeline, tmp_path, monkeypatch
):
    targets, selection, _ = named_pipeline
    target_path, selection_path = tmp_path / "targets.json", tmp_path / "selection.json"
    target_path.write_bytes(targets)
    selection_path.write_bytes(selection)

    def forbidden(*args, **kwargs):
        pytest.fail("name linking must only read the two supplied JSON files")

    monkeypatch.setattr(AllocationInputService, "prepare", forbidden)
    monkeypatch.setattr("sqlite3.connect", forbidden)
    monkeypatch.setattr("phalanx.portfolio.dynamic_risk_model.DynamicRiskModel.estimate", forbidden)
    monkeypatch.setattr(
        "phalanx.portfolio.constrained_erc.ConstrainedErcSolver.solve_scenario", forbidden
    )
    monkeypatch.setattr("httpx.Client.request", forbidden)
    monkeypatch.setattr("phalanx.config.load_kis_credentials", forbidden)
    model = FormationRoomService().generate(
        target_path, tmp_path / "room.html", selection=selection_path
    )
    assert model.selection_linked


def test_selection_source_cannot_be_overwritten_by_html(named_pipeline, tmp_path):
    targets, selection, _ = named_pipeline
    target_path, selection_path = tmp_path / "targets.json", tmp_path / "selection.json"
    target_path.write_bytes(targets)
    selection_path.write_bytes(selection)
    response = runner.invoke(
        app,
        [
            "portfolio",
            "formation-room",
            "--targets",
            str(target_path),
            "--selection",
            str(selection_path),
            "--output",
            str(selection_path),
        ],
    )
    assert response.exit_code == 66 and "OUTPUT_EXISTS" in response.output
    assert target_path.read_bytes() == targets and selection_path.read_bytes() == selection
