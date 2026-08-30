from __future__ import annotations

import os
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import phalanx.portfolio.report_storage as report_storage
from phalanx.portfolio.errors import (
    HistoricalReportAlreadyExistsError,
    HistoricalReportStorageError,
)
from phalanx.portfolio.report_storage import HistoricalReportStore


def test_stores_new_report_with_mode_0600(tmp_path: Path) -> None:
    output = tmp_path / "reports" / "analysis.html"

    saved = HistoricalReportStore(output).save("<!doctype html><p>safe</p>")

    assert saved == output
    assert output.read_text(encoding="utf-8") == "<!doctype html><p>safe</p>"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


def test_refuses_to_overwrite_an_existing_report(tmp_path: Path) -> None:
    output = tmp_path / "analysis.html"
    output.write_text("existing", encoding="utf-8")

    with pytest.raises(HistoricalReportAlreadyExistsError, match="덮어쓰지"):
        HistoricalReportStore(output).save("replacement")

    assert output.read_text(encoding="utf-8") == "existing"


def test_atomic_replace_failure_preserves_racing_file_and_cleans_temporary_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "analysis.html"

    def fail_replace(source: Path, target: Path) -> None:
        assert target == output
        output.write_text("racing existing report", encoding="utf-8")
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(report_storage.os, "replace", fail_replace)

    with pytest.raises(HistoricalReportStorageError, match="원자적으로"):
        HistoricalReportStore(output).save("new report")

    assert output.read_text(encoding="utf-8") == "racing existing report"
    assert list(tmp_path.glob(".analysis.html.*.tmp")) == []


def test_temporary_file_is_private_before_atomic_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "analysis.html"
    original_replace = os.replace
    observed_modes: list[int] = []

    def inspect_then_replace(source: Path, target: Path) -> None:
        observed_modes.append(stat.S_IMODE(source.stat().st_mode))
        original_replace(source, target)

    monkeypatch.setattr(report_storage.os, "replace", inspect_then_replace)

    HistoricalReportStore(output).save("safe report")

    assert observed_modes == [0o600]


def test_concurrent_saves_allow_exactly_one_success_without_overwrite(
    tmp_path: Path,
) -> None:
    output = tmp_path / "analysis.html"

    def save(payload: str) -> str:
        HistoricalReportStore(output).save(payload)
        return payload

    successes: list[str] = []
    failures: list[Exception] = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(save, payload) for payload in ("first", "second")]
        for future in futures:
            try:
                successes.append(future.result())
            except Exception as error:
                failures.append(error)

    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], HistoricalReportAlreadyExistsError)
    assert output.read_text(encoding="utf-8") == successes[0]
