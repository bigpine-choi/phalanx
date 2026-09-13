from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import httpx
import pytest
from feature_helpers import CODES, END, NOW, bars, history
from typer.testing import CliRunner

from phalanx.cli import app
from phalanx.domain.price_features import CandidatePriceFeatures
from phalanx.kis import KisTokenManager
from phalanx.market_data.features.service import PriceFeatureService
from phalanx.market_data.history.repository import SqliteHistoryRepository
from phalanx.portfolio.private_json_storage import PrivateJsonAlreadyExistsError

runner = CliRunner()
PREFIX = ["market-data", "features", "calculate"]


def setup(tmp_path: Path):
    view = history((bars(CODES[0], ["100"] * 253), bars(CODES[1], ["100"] * 20 + ["110"])))
    repository = SqliteHistoryRepository(tmp_path / "private" / "history.sqlite3")
    repository.create(view)
    args = [
        *PREFIX,
        view.job.job_id,
        "--history-db",
        str(repository.path),
        "--as-of",
        END.isoformat(),
    ]
    return view, repository, args


@pytest.mark.parametrize("selection,exit_code", [(["--code", CODES[0]], 0), (["--all-targets"], 2)])
def test_offline_cli_displays_and_exports_complete_or_partial_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, selection: list[str], exit_code: int
) -> None:
    view, repository, args = setup(tmp_path)
    before = repository.path.read_bytes()

    def forbidden(*args, **kwargs):
        pytest.fail("feature calculation accessed credentials, OAuth or HTTP")

    monkeypatch.setattr("phalanx.config.load_kis_credentials", forbidden)
    monkeypatch.setattr("phalanx.market_data.history.application.load_kis_credentials", forbidden)
    monkeypatch.setattr(KisTokenManager, "get_access_token", forbidden)
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    output = tmp_path / "export" / "features.json"
    response = runner.invoke(app, [*args, *selection, "--output", str(output)])
    assert response.exit_code == exit_code, response.output
    assert response.stderr == ""
    assert output.read_bytes() == response.stdout.encode("utf-8")
    result = CandidatePriceFeatures.model_validate_json(output.read_bytes())
    assert result.history_job_id == view.job.job_id
    assert result.complete == (exit_code == 0)
    assert output.stat().st_mode & 0o777 == 0o600
    assert repository.path.read_bytes() == before
    if exit_code == 2:
        assert result.symbols[1].metrics[0].available
        assert result.symbols[1].metrics[1].value is None


def test_explicit_code_order_and_export_reproducibility(tmp_path: Path) -> None:
    view, repository, args = setup(tmp_path)
    response = runner.invoke(app, [*args, "--code", CODES[1], "--code", CODES[0]])
    assert response.exit_code == 2
    assert [s["target"]["short_code"] for s in json.loads(response.stdout)["symbols"]] == list(
        CODES[::-1]
    )
    service = PriceFeatureService(repository, clock=lambda: NOW)
    first = service.calculate(view.job.job_id, as_of=END, all_targets=True)
    second = service.calculate(view.job.job_id, as_of=END, all_targets=True)
    paths = [tmp_path / "exports" / name for name in ("a.json", "b.json")]
    service.export(first, paths[0])
    service.export(second, paths[1])
    assert paths[0].read_bytes() == paths[1].read_bytes()
    with pytest.raises(PrivateJsonAlreadyExistsError):
        service.export(second, paths[0])
    assert paths[0].read_bytes() == first.to_json_bytes()


@pytest.mark.parametrize(
    "options,error",
    [
        ([], "TARGET_SELECTION_REQUIRED"),
        (["--code", CODES[0], "--all-targets"], "TARGET_SELECTION_REQUIRED"),
        (["--code", CODES[0], "--code", CODES[0]], "DUPLICATE_CODE"),
        (["--code", "999999"], "SYMBOL_NOT_FOUND"),
        (["--all-targets", "--as-of", "20250101"], "INVALID_AS_OF"),
        (["--all-targets", "--as-of", "2026-02-30"], "INVALID_AS_OF"),
        (["--all-targets", "--as-of", "2024-12-31"], "INVALID_AS_OF"),
        (["--all-targets", "--as-of", "2026-09-01"], "INVALID_AS_OF"),
    ],
)
def test_cli_input_errors_create_no_output(tmp_path: Path, options: list[str], error: str) -> None:
    _, _, args = setup(tmp_path)
    output = tmp_path / "unwritten.json"
    response = runner.invoke(app, [*args, *options, "--output", str(output)])
    assert response.exit_code == 65, response.output
    assert error in response.stderr
    assert not output.exists()


def test_cli_requires_as_of_and_reports_missing_job(tmp_path: Path) -> None:
    _, _, args = setup(tmp_path)
    no_date = runner.invoke(app, [*args[:-2], "--all-targets"])
    assert no_date.exit_code == 2
    args[3] = "f" * 32
    missing = runner.invoke(app, [*args, "--all-targets"])
    assert missing.exit_code == 65 and "JOB_NOT_FOUND" in missing.stderr


def test_cli_existing_output_and_source_corruption_are_storage_errors(tmp_path: Path) -> None:
    _, repository, args = setup(tmp_path)
    output = tmp_path / "existing.json"
    output.write_bytes(b"preserve existing output")
    response = runner.invoke(app, [*args, "--all-targets", "--output", str(output)])
    assert response.exit_code == 66 and "OUTPUT_EXISTS" in response.stderr
    assert output.read_bytes() == b"preserve existing output"
    with sqlite3.connect(repository.path) as connection:
        connection.execute("UPDATE symbols SET state_json='invalid-json' WHERE ordinal=0")
    output = tmp_path / "must-not-exist.json"
    corrupted = runner.invoke(app, [*args, "--all-targets", "--output", str(output)])
    assert corrupted.exit_code == 66 and "STORAGE_FAILED" in corrupted.stderr
    assert not output.exists()


def test_cli_atomic_write_failure_leaves_no_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, args = setup(tmp_path)

    def fail_write(descriptor, payload):
        raise OSError("synthetic write failure")

    monkeypatch.setattr("phalanx.portfolio.private_json_storage._write_all", fail_write)
    output = tmp_path / "export" / "failed.json"
    response = runner.invoke(app, [*args, "--all-targets", "--output", str(output)])
    assert response.exit_code == 66 and "OUTPUT_STORAGE_FAILED" in response.stderr
    assert not output.exists()
    assert not list(output.parent.glob("*.tmp"))
