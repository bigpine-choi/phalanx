"""Offline, declared-availability evidence around the existing selection contract."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from feature_helpers import bars, history
from typer.testing import CliRunner

from phalanx.domain.candidate_selection import CandidateSelection, SelectionMetric, SelectionPolicy
from phalanx.market_data.features.calculation import calculate_price_features
from phalanx.portfolio.private_json_storage import PrivateJsonAlreadyExistsError
from phalanx.selection.decision_snapshot import (
    DecisionInputError,
    DecisionSnapshotService,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "candidate-selection"
DECISION_AT = datetime(2026, 9, 13, 0, 0, tzinfo=UTC)
POLICY = SelectionPolicy(metric=SelectionMetric.RETURN_60, top=1, max_age_days=0)


def manifest_payload(features: bytes, **changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "1",
        "snapshot_id": "synthetic-candidate-selection-20260820",
        "source_name": "synthetic-test-fixture",
        "source_revision": "v1",
        "features_sha256": hashlib.sha256(features).hexdigest(),
        "feature_schema_version": "1",
        "feature_policy_version": "candidate_price_features_v1",
        "price_basis": "adjusted_close_price_return_excluding_dividends",
        "return_unit": "simple_decimal_ratio",
        "market_timezone": "Asia/Seoul",
        "observed_at": "2026-08-20T15:30:00+09:00",
        "available_at": "2026-09-13T08:59:00+09:00",
        "decision_at": "2026-09-13T09:00:00+09:00",
        "availability_evidence": "declared",
    }
    payload.update(changes)
    return payload


def write_manifest(path: Path, features: bytes, **changes: object) -> Path:
    path.write_text(
        json.dumps(manifest_payload(features, **changes), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def test_checked_in_three_candidate_example_preserves_partial_selection(tmp_path: Path) -> None:
    features_path = EXAMPLE / "features.json"
    expected = CandidateSelection.model_validate_json((EXAMPLE / "selection.json").read_bytes())
    manifest_path = write_manifest(tmp_path / "manifest.json", features_path.read_bytes())

    result = DecisionSnapshotService(clock=lambda: DECISION_AT).run(
        manifest_path, features_path, expected.policy
    )

    assert result.selection.to_json_bytes() == expected.to_json_bytes()
    assert result.selection.selected_codes == ("0001A0",)
    assert [candidate.status for candidate in result.selection.candidates] == [
        "selected",
        "not_selected",
        "unavailable",
    ]
    assert [reason.code for reason in result.selection.candidates[2].reasons] == [
        "METRIC_UNAVAILABLE"
    ]
    assert result.selection.candidates[2].selected_feature.reason_code == (
        "INSUFFICIENT_OBSERVATIONS"
    )
    assert not result.selection.evaluation_complete
    assert result.selection.selection_filled
    assert not result.selection.complete
    assert result.selection.point_in_time_backtest_guaranteed is False
    assert result.manifest.features_sha256 == hashlib.sha256(features_path.read_bytes()).hexdigest()
    assert result.selection.source.input_sha256 == result.manifest.features_sha256


def test_checked_in_manifest_matches_exact_example_bytes() -> None:
    result = DecisionSnapshotService(clock=lambda: DECISION_AT).run(
        EXAMPLE / "decision-manifest.json", EXAMPLE / "features.json", POLICY
    )

    assert result.manifest.features_sha256 == hashlib.sha256(
        (EXAMPLE / "features.json").read_bytes()
    ).hexdigest()
    assert result.selection.selected_codes == ("0001A0",)


def test_same_inputs_and_clock_produce_identical_report_bytes(tmp_path: Path) -> None:
    features_path = EXAMPLE / "features.json"
    manifest_path = write_manifest(tmp_path / "manifest.json", features_path.read_bytes())
    service = DecisionSnapshotService(clock=lambda: DECISION_AT)

    first = service.run(manifest_path, features_path, POLICY)
    second = service.run(manifest_path, features_path, POLICY)

    assert first.to_json_bytes() == second.to_json_bytes()
    assert first.selection.to_json_bytes() == second.selection.to_json_bytes()


@pytest.mark.skipif(sys.platform == "win32", reason="main CLI imports Unix-only fcntl")
def test_replay_cli_returns_partial_result_as_json_and_exit_two(tmp_path: Path) -> None:
    from phalanx.cli import app

    features_path = EXAMPLE / "features.json"
    manifest_path = write_manifest(tmp_path / "manifest.json", features_path.read_bytes())

    response = CliRunner().invoke(
        app,
        [
            "candidates",
            "replay",
            "--manifest",
            str(manifest_path),
            "--features",
            str(features_path),
            "--metric",
            "return_60",
            "--top",
            "1",
            "--max-age-days",
            "0",
        ],
    )

    assert response.exit_code == 2, response.output
    payload = json.loads(response.stdout)
    assert payload["selection"]["selected_codes"] == ["0001A0"]
    assert payload["selection"]["unavailable_count"] == 1
    assert payload["selection"]["point_in_time_backtest_guaranteed"] is False
    assert payload["point_in_time_backtest_guaranteed"] is False
    assert payload["manifest"]["features_sha256"] == hashlib.sha256(
        features_path.read_bytes()
    ).hexdigest()


def test_exact_feature_file_hash_is_required(tmp_path: Path) -> None:
    features_path = EXAMPLE / "features.json"
    manifest_path = write_manifest(
        tmp_path / "manifest.json", features_path.read_bytes(), features_sha256="0" * 64
    )

    with pytest.raises(DecisionInputError):
        DecisionSnapshotService(clock=lambda: DECISION_AT).run(manifest_path, features_path, POLICY)


def test_features_calculated_after_decision_are_rejected(tmp_path: Path) -> None:
    raw = json.loads((EXAMPLE / "features.json").read_bytes())
    raw["calculated_at"] = "2026-09-13T00:01:00Z"
    features_path = tmp_path / "late-features.json"
    features_path.write_text(json.dumps(raw), encoding="utf-8")
    manifest_path = write_manifest(tmp_path / "manifest.json", features_path.read_bytes())

    with pytest.raises(DecisionInputError) as error:
        DecisionSnapshotService(clock=lambda: DECISION_AT).run(manifest_path, features_path, POLICY)
    assert error.value.code == "FEATURE_DECISION_MISMATCH"


@pytest.mark.parametrize(
    "changes",
    [
        {"observed_at": "2026-08-20T15:30:00"},
        {"available_at": "2026-09-13T08:59:00"},
        {"decision_at": "2026-09-13T09:00:00"},
        {"observed_at": "2026-09-13T09:00:01+09:00"},
        {"observed_at": "2026-08-19T15:30:00+09:00"},
        {"available_at": "2026-09-13T09:00:01+09:00"},
        {"decision_at": "2026-09-13T08:58:00+09:00"},
        {"decision_at": "2026-08-19T09:00:00+09:00", "available_at": "2026-08-19T08:59:00+09:00"},
    ],
)
def test_rejects_naive_reversed_late_or_pre_feature_decision(
    tmp_path: Path, changes: dict[str, str]
) -> None:
    features_path = EXAMPLE / "features.json"
    manifest_path = write_manifest(
        tmp_path / "manifest.json", features_path.read_bytes(), **changes
    )

    with pytest.raises(DecisionInputError):
        DecisionSnapshotService(clock=lambda: DECISION_AT).run(manifest_path, features_path, POLICY)


@pytest.mark.parametrize(
    "changes",
    [
        {"snapshot_id": "  "},
        {"source_revision": ""},
        {"return_unit": "percent"},
        {"market_timezone": "UTC"},
        {"feature_policy_version": "candidate_price_features_v2"},
        {"price_basis": "total_return_including_dividends"},
        {"unexpected_field": "not part of v1"},
    ],
)
def test_rejects_invalid_manifest_contract(tmp_path: Path, changes: dict[str, str]) -> None:
    features_path = EXAMPLE / "features.json"
    manifest_path = write_manifest(
        tmp_path / "manifest.json", features_path.read_bytes(), **changes
    )

    with pytest.raises(DecisionInputError):
        DecisionSnapshotService(clock=lambda: DECISION_AT).run(manifest_path, features_path, POLICY)


def test_rejects_duplicate_manifest_keys(tmp_path: Path) -> None:
    features_path = EXAMPLE / "features.json"
    payload = json.dumps(manifest_payload(features_path.read_bytes()))
    assert payload.startswith('{"schema_version": "1",')
    manifest_path = tmp_path / "manifest.json"
    malformed = payload.replace(
        '"schema_version": "1",', '"schema_version": "1", "schema_version": "1",', 1
    )
    manifest_path.write_text(malformed, encoding="utf-8")

    with pytest.raises(DecisionInputError):
        DecisionSnapshotService(clock=lambda: DECISION_AT).run(manifest_path, features_path, POLICY)


def test_six_symbols_ignore_a_future_bar_in_consumed_features(tmp_path: Path) -> None:
    codes = ("000001", "000002", "000003", "000004", "000005", "000006")
    last_closes = ("100", "105", "95", "110", "90", "102")
    start = date(2026, 6, 21)
    base = tuple(
        bars(code, ["100"] * 60 + [last_close], start=start)
        for code, last_close in zip(codes, last_closes, strict=True)
    )
    augmented = list(base)
    augmented[1] = (*augmented[1], *bars(codes[1], ["999999"], start=date(2026, 8, 21)))
    as_of = date(2026, 8, 20)
    view_before = history(base, codes=codes)
    view_after = history(tuple(augmented), codes=codes)
    before = calculate_price_features(
        view_before.job, view_before.symbols, as_of=as_of, calculated_at=DECISION_AT
    )
    after = calculate_price_features(
        view_after.job, view_after.symbols, as_of=as_of, calculated_at=DECISION_AT
    )
    before_path = tmp_path / "before-features.json"
    after_path = tmp_path / "after-features.json"
    before_path.write_bytes(before.to_json_bytes())
    after_path.write_bytes(after.to_json_bytes())
    before_manifest = write_manifest(tmp_path / "before-manifest.json", before_path.read_bytes())
    after_manifest = write_manifest(tmp_path / "after-manifest.json", after_path.read_bytes())
    service = DecisionSnapshotService(clock=lambda: DECISION_AT)

    before_result = service.run(before_manifest, before_path, POLICY)
    after_result = service.run(after_manifest, after_path, POLICY)

    assert len(before_result.selection.candidates) == 6
    assert before_result.selection.selected_codes == after_result.selection.selected_codes
    assert [item.score for item in before_result.selection.candidates] == [
        item.score for item in after_result.selection.candidates
    ]
    assert [item.consumed_input_sha256 for item in before_result.selection.candidates] == [
        item.consumed_input_sha256 for item in after_result.selection.candidates
    ]
    # The full source changed, and its provenance hash must still reveal that change.
    assert before_result.selection.candidates[1].source_price_sha256 != (
        after_result.selection.candidates[1].source_price_sha256
    )


def test_export_is_write_once(tmp_path: Path) -> None:
    features_path = EXAMPLE / "features.json"
    manifest_path = write_manifest(tmp_path / "manifest.json", features_path.read_bytes())
    service = DecisionSnapshotService(clock=lambda: DECISION_AT)
    result = service.run(manifest_path, features_path, POLICY)
    output = tmp_path / "out" / "decision.json"

    assert service.export(result, output) == output
    expected = result.to_json_bytes()
    assert output.read_bytes() == expected
    with pytest.raises(PrivateJsonAlreadyExistsError):
        service.export(result, output)
    assert output.read_bytes() == expected
