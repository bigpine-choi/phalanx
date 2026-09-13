from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import httpx
import pytest
from feature_helpers import NOW, bars, history
from selection_helpers import AS_OF, CODES, features, scores
from typer.testing import CliRunner

from phalanx.cli import app
from phalanx.discovery.repository import SqliteDiscoveryRepository
from phalanx.domain.candidate_selection import CandidateSelection, SelectionMetric, SelectionPolicy
from phalanx.kis import KisTokenManager
from phalanx.market_data.history.repository import SqliteHistoryRepository
from phalanx.selection.errors import SelectionInputError, SelectionStorageError
from phalanx.selection.service import CandidateSelectionService

runner = CliRunner()


def args(path: Path):
    return [
        "candidates",
        "select",
        "--features",
        str(path),
        "--metric",
        "return_60",
        "--top",
        "1",
        "--max-age-days",
        "7",
    ]


def test_one_read_supplies_both_hash_and_parse_without_mutating_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = scores(features(), ("0.1", "0.2", "0.3"))
    # Noncanonical whitespace demonstrates hashing the exact file bytes.
    payload = b" \n" + source.to_json_bytes() + b"\n\t"
    path = tmp_path / "features.json"
    path.write_bytes(payload)
    original_read = Path.read_bytes
    calls = []

    def read_once(self):
        assert self == path
        calls.append(self)
        assert len(calls) == 1, "input reopened for parsing or hashing"
        return original_read(self)

    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "read_bytes", read_once)
        result = CandidateSelectionService(clock=lambda: NOW).select(
            path, SelectionPolicy(metric=SelectionMetric.RETURN_60, top=1, max_age_days=7)
        )
    assert calls == [path]
    assert path.read_bytes() == payload
    assert result.source.input_sha256 == hashlib.sha256(payload).hexdigest()
    assert result.source.input_sha256 != hashlib.sha256(source.to_json_bytes()).hexdigest()
    assert result.selected_codes == (CODES[2],)
    assert result.source.source_price_hashes_verified is False
    assert result.comparison_scope == "provided_features_candidates"
    assert result.trading_day_completeness == "unverified"
    assert result.point_in_time_backtest_guaranteed is False
    again = CandidateSelectionService(clock=lambda: NOW).select(path, result.policy)
    assert again.to_json_bytes() == result.to_json_bytes()


@pytest.mark.parametrize("counts,top,exit_code", [((253, 253, 253), 1, 0), ((61, 21, 61), 3, 2)])
def test_cli_is_offline_and_stdout_matches_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, counts, top, exit_code
) -> None:
    path = tmp_path / "features.json"
    path.write_bytes(features(counts=counts).to_json_bytes())
    before = path.read_bytes()

    def forbidden(*args, **kwargs):
        pytest.fail("selection accessed DB, credentials, OAuth or HTTP")

    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(SqliteHistoryRepository, "read_selected", forbidden)
    monkeypatch.setattr(SqliteDiscoveryRepository, "load", forbidden)
    monkeypatch.setattr("phalanx.config.load_kis_credentials", forbidden)
    monkeypatch.setattr("phalanx.market_data.history.application.load_kis_credentials", forbidden)
    monkeypatch.setattr(KisTokenManager, "get_access_token", forbidden)
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    output = tmp_path / "out" / "selection.json"
    response = runner.invoke(app, [*args(path), "--top", str(top), "--output", str(output)])
    assert response.exit_code == exit_code, response.output
    assert response.stderr == ""
    assert output.read_bytes() == response.stdout.encode()
    result = CandidateSelection.model_validate_json(output.read_bytes())
    assert result.complete is (exit_code == 0)
    assert path.read_bytes() == before
    assert output.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("count,feature_exit", [(253, 0), (61, 2)])
def test_real_features_cli_complete_and_partial_json_are_accepted(
    tmp_path: Path, count, feature_exit
) -> None:
    from datetime import timedelta

    start = AS_OF - timedelta(days=count - 1)
    view = history(tuple(bars(code, ["100"] * count, start=start) for code in CODES), codes=CODES)
    repository = SqliteHistoryRepository(tmp_path / "history" / "history.sqlite3")
    repository.create(view)
    path = tmp_path / "features.json"
    feature_response = runner.invoke(
        app,
        [
            "market-data",
            "features",
            "calculate",
            view.job.job_id,
            "--as-of",
            AS_OF.isoformat(),
            "--all-targets",
            "--history-db",
            str(repository.path),
            "--output",
            str(path),
        ],
    )
    assert feature_response.exit_code == feature_exit, feature_response.output
    assert path.read_bytes() == feature_response.stdout.encode()
    response = runner.invoke(app, args(path))
    assert response.exit_code == 0, response.output
    selection = CandidateSelection.model_validate_json(response.stdout)
    assert selection.source.features_complete is (feature_exit == 0)
    assert selection.source.history_job_id == view.job.job_id
    assert selection.source.input_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("option", ["--features", "--metric", "--top", "--max-age-days"])
def test_all_policy_and_input_options_are_required(tmp_path: Path, option: str) -> None:
    arguments = args(tmp_path / "unused.json")
    offset = arguments.index(option)
    del arguments[offset : offset + 2]
    response = runner.invoke(app, arguments)
    assert response.exit_code == 2
    assert not response.stdout and option in response.stderr


@pytest.mark.parametrize(
    "option,value",
    [("--metric", "score"), ("--top", "0"), ("--top", "-1"), ("--max-age-days", "-1")],
)
def test_invalid_policy_is_input_error_before_file_read(tmp_path: Path, option, value) -> None:
    response = runner.invoke(app, [*args(tmp_path / "missing.json"), option, value])
    assert response.exit_code == 65
    assert "INVALID_POLICY" in response.stderr and not response.stdout


def test_file_read_errors_differ_from_malformed_content_and_hide_input(tmp_path: Path) -> None:
    path = tmp_path / "features.json"
    service = CandidateSelectionService()
    policy = SelectionPolicy(metric=SelectionMetric.RETURN_60, top=1, max_age_days=7)
    with pytest.raises(SelectionStorageError):
        service.select(path, policy)
    missing = runner.invoke(app, args(path))
    assert missing.exit_code == 66 and "INPUT_READ_FAILED" in missing.stderr
    path.write_bytes(b'{"secret":"SENSITIVE_TEST_MARKER","complete":NaN}')
    with pytest.raises(SelectionInputError):
        service.select(path, policy)
    malformed = runner.invoke(app, args(path))
    assert malformed.exit_code == 65 and "INVALID_FEATURES" in malformed.stderr
    assert "SENSITIVE_TEST_MARKER" not in malformed.output
    assert "Traceback" not in malformed.output


def test_existing_output_preserved_and_atomic_write_failure_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "features.json"
    path.write_bytes(features(counts=(61, 21, 61)).to_json_bytes())
    before = path.read_bytes()
    # Using the input as output must preserve the exact original input bytes.
    same = runner.invoke(app, [*args(path), "--output", str(path)])
    assert same.exit_code == 66 and "OUTPUT_EXISTS" in same.stderr
    assert path.read_bytes() == before
    output = tmp_path / "out" / "selection.json"

    def fail_write(descriptor, payload):
        raise OSError("synthetic atomic write failure")

    monkeypatch.setattr("phalanx.portfolio.private_json_storage._write_all", fail_write)
    failed = runner.invoke(app, [*args(path), "--output", str(output)])
    assert failed.exit_code == 66 and "OUTPUT_STORAGE_FAILED" in failed.stderr
    assert not failed.stdout and not output.exists()
    assert not list(output.parent.glob("*.tmp"))
    assert path.read_bytes() == before


def test_score_decimal_strings_survive_json_export(tmp_path: Path) -> None:
    path = tmp_path / "features.json"
    source = scores(features(), ("0.1000", "0.2000", "0"))
    path.write_bytes(source.to_json_bytes())
    result = runner.invoke(app, args(path))
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert [c["score"] for c in payload["candidates"]] == ["0.1000", "0.2000", "0"]


@pytest.mark.parametrize("with_output", [False, True])
@pytest.mark.parametrize("surrogate", ["\ud800", "\udfff"], ids=["high", "low"])
def test_cli_rejects_unpaired_surrogates_before_any_output(
    tmp_path: Path, surrogate: str, with_output: bool
) -> None:
    path = tmp_path / "features.json"
    raw = json.loads(features().to_json_bytes())
    raw["symbols"][0]["target"]["name"] = "SENSITIVE_TEST_MARKER" + surrogate
    before = json.dumps(raw).encode()
    path.write_bytes(before)
    output = tmp_path / "out" / "selection.json"
    response = runner.invoke(
        app, [*args(path), *(["--output", str(output)] if with_output else [])]
    )
    assert response.exit_code == 65, response.output
    assert "INVALID_FEATURES" in response.stderr
    assert isinstance(response.exception, SystemExit)
    assert "Traceback" not in response.output and "UnicodeEncodeError" not in response.output
    assert "SENSITIVE_TEST_MARKER" not in response.output
    assert not response.stdout and not output.exists() and not output.parent.exists()
    assert sorted(tmp_path.iterdir()) == [path]
    assert path.read_bytes() == before


@pytest.mark.parametrize("escaped", [True, False], ids=["surrogate-pair", "utf8"])
def test_cli_preserves_korean_and_emoji_in_json_output(tmp_path: Path, escaped: bool) -> None:
    path = tmp_path / "features.json"
    raw = json.loads(features().to_json_bytes())
    name = "한글 종목 😀"
    raw["symbols"][0]["target"]["name"] = name
    before = json.dumps(raw, ensure_ascii=escaped).encode("utf-8")
    path.write_bytes(before)
    output = tmp_path / "selection.json"
    response = runner.invoke(app, [*args(path), "--output", str(output)])
    assert response.exit_code == 0, response.output
    assert not response.stderr
    assert json.loads(response.stdout)["candidates"][0]["target"]["name"] == name
    assert name.encode("utf-8") in output.read_bytes() == response.stdout.encode("utf-8")
    assert path.read_bytes() == before
