"""Controller tests run unchanged on Windows and Linux without loading a GUI."""

import hashlib
import os
import threading
import time

import pytest
from desktop_helpers import desktop_inputs

from phalanx.desktop.application import DesktopApplication
from phalanx.portfolio.allocation_input.service import AllocationInputService
from phalanx.portfolio.allocation_targets.service import AllocationTargetsService


def repository(path):
    if os.name == "nt":
        from phalanx.market_data.history.windows_repository import WindowsHistoryRepository

        return WindowsHistoryRepository(path)
    from phalanx.market_data.history.repository import SqliteHistoryRepository

    return SqliteHistoryRepository(path)


def wait(app, reply):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        status = app.job_status(reply["job_id"], reply["generation"])
        if status.get("state") != "running":
            return status
        time.sleep(0.01)
    pytest.fail("desktop job did not complete")


@pytest.fixture(scope="module")
def inputs(tmp_path_factory):
    db, selection = desktop_inputs(tmp_path_factory.mktemp("desktop 계산"))
    payload = (
        AllocationTargetsService(AllocationInputService(repository(db)))
        .calculate_bytes(selection.read_bytes())
        .to_json_bytes()
    )
    return db, selection, payload


def test_application_matches_direct_service_and_preserves_db(inputs, tmp_path):
    db, selection, expected = inputs
    before = hashlib.sha256(db.read_bytes()).digest()
    app = DesktopApplication(repository_factory=repository)
    try:
        reply = app.calculate(selection, db, 1)
        status = wait(app, reply)
        assert status["state"] == "complete", status
        assert status["status"] == "succeeded"
        assert status["mode"] == "calculated"
        assert status["targets_sha256"] == hashlib.sha256(expected).hexdigest()
        destination = tmp_path / "저장 결과.json"
        saved = app.save_result(reply["job_id"], 1, destination)
        assert saved["ok"], saved
        assert destination.read_bytes() == expected
        assert saved["save_state"] == "saved"
        conflict = app.save_result(reply["job_id"], 1, destination)
        assert conflict["ok"] is False
        assert conflict["state"] == "complete"
        assert conflict["save_state"] == "error"
        retry = app.save_result(reply["job_id"], 1, tmp_path / "재시도.json")
        assert retry["ok"]
        assert hashlib.sha256(db.read_bytes()).digest() == before
    finally:
        app.closed()


def test_open_optional_names_wrong_link_missing_and_retry(inputs, tmp_path):
    _, selection, expected = inputs
    target = tmp_path / "목표 비중.json"
    target.write_bytes(expected)
    app = DesktopApplication(repository_factory=repository)
    try:
        result = wait(app, app.open_result(target, None, 1))
        assert result["state"] == "complete"
        assert result["mode"] == "saved"
        assert "이름 미확인" in result["html"]
        linked = wait(app, app.open_result(target, selection, 2))
        assert "합성 삼성전자" in linked["html"]
        wrong = tmp_path / "잘못된 선정.json"
        wrong.write_bytes(selection.read_bytes() + b" ")
        assert wait(app, app.open_result(target, wrong, 3))["state"] == "error"
        assert wait(app, app.open_result(tmp_path / "없음.json", None, 4))["state"] == "error"
        assert wait(app, app.open_result(target, selection, 5))["state"] == "complete"
        assert app.job_status(result["job_id"], 1)["stale"]
    finally:
        app.closed()


def test_double_click_close_wait_and_frozen_selection(inputs, tmp_path):
    db, selection, expected = inputs
    entered = threading.Event()
    release = threading.Event()
    close = threading.Event()
    selected = tmp_path / "선정.json"
    selected.write_bytes(selection.read_bytes())

    def factory(path):
        entered.set()
        assert release.wait(30)
        return repository(path)

    app = DesktopApplication(repository_factory=factory)
    app.set_close_callback(close.set)
    try:
        first = app.calculate(selected, db, 1)
        assert entered.wait(30)
        # Path changes after capture cannot change calculation or name linkage.
        selected.write_bytes(b"{}")
        duplicate = app.calculate(selection, db, 2)
        assert duplicate["ok"] is False
        assert duplicate["state"] == "rejected"
        assert duplicate["generation"] == 2
        assert duplicate["job_id"] is None
        assert duplicate["active_job"] == {"job_id": first["job_id"], "generation": 1}
        assert app.job_status(first["job_id"], 1)["state"] == "running"
        assert app.request_close() is False
        assert not close.is_set()
        release.set()
        assert close.wait(60)
        result = app.job_status(first["job_id"], 1)
        assert result["targets_sha256"] == hashlib.sha256(expected).hexdigest()
        assert result["closing"]
        rejected_close = app.calculate(selection, db, 3)
        assert rejected_close["ok"] is False
        assert rejected_close["generation"] == 3
        assert rejected_close["job_id"] is None
    finally:
        release.set()
        app.closed()
    assert app.job_status(first["job_id"], 1)["stale"]
    assert not any(t.name.startswith("phalanx-") for t in threading.enumerate())


def test_invalid_database_failure_allows_retry(inputs, tmp_path):
    db, selection, _ = inputs
    invalid = tmp_path / "invalid.sqlite3"
    invalid.write_bytes(b"not sqlite")
    invalid.chmod(0o600)
    app = DesktopApplication(repository_factory=repository)
    try:
        assert wait(app, app.calculate(selection, invalid, 1))["state"] == "error"
        assert wait(app, app.calculate(selection, db, 2))["state"] == "complete"
    finally:
        app.closed()


def test_late_generation_cannot_replace_current_result(inputs, tmp_path):
    _, _, payload = inputs
    target = tmp_path / "result.json"
    target.write_bytes(payload)
    app = DesktopApplication(repository_factory=repository)
    try:
        first = wait(app, app.open_result(target, None, 5))
        for generation in (4, 5):
            rejected = app.open_result(target, None, generation)
            assert rejected["ok"] is False
            assert rejected["generation"] == generation
            assert rejected["job_id"] is None
            assert rejected["active_job"] is None
        second = wait(app, app.open_result(target, None, 6))
        assert app.job_status(first["job_id"], 5)["stale"]
        assert app.save_result(first["job_id"], 5, tmp_path / "stale.json")["stale"]
        assert app.job_status(second["job_id"], 6)["ok"]
    finally:
        app.closed()


def test_finished_result_is_not_reported_before_worker_stops(inputs, tmp_path, monkeypatch):
    _, _, payload = inputs
    target = tmp_path / "result.json"
    target.write_bytes(payload)
    app = DesktopApplication(repository_factory=repository)
    result_ready = threading.Event()
    release_worker = threading.Event()
    original_complete = app._complete

    def complete_then_pause(*args):
        original_complete(*args)
        result_ready.set()
        assert release_worker.wait(30)

    monkeypatch.setattr(app, "_complete", complete_then_pause)
    try:
        reply = app.open_result(target, None, 1)
        assert result_ready.wait(30)
        assert app.job_status(reply["job_id"], 1)["state"] == "running"
        rejected = app.open_result(target, None, 2)
        assert rejected["active_job"] == {"generation": 1, "job_id": reply["job_id"]}
        release_worker.set()
        assert wait(app, reply)["state"] == "complete"
        assert app.request_close() is True
    finally:
        release_worker.set()
        app.closed()


@pytest.mark.parametrize("outcome", ["input_unavailable", "common_failure", "partial", "failed"])
def test_valid_financial_failures_are_results(outcome, tmp_path):
    import gzip

    from desktop_helpers import FIXTURES

    payload = gzip.decompress((FIXTURES / f"{outcome}.json.gz").read_bytes())
    target = tmp_path / "failure.json"
    target.write_bytes(payload)
    app = DesktopApplication()
    try:
        reply = app.open_result(target, None, 1)
        result = wait(app, reply)
        assert result["state"] == "complete"
        assert result["status"] == outcome
        assert result["save_state"] == "source"
        saved = app.save_result(reply["job_id"], 1, tmp_path / "saved.json")
        assert saved["ok"]
        assert (tmp_path / "saved.json").read_bytes() == payload
    finally:
        app.closed()


def test_worker_start_failure_does_not_block_retry_or_close(inputs, tmp_path, monkeypatch):
    _, _, payload = inputs
    target = tmp_path / "result.json"
    target.write_bytes(payload)
    app = DesktopApplication(repository_factory=repository)
    original_start = threading.Thread.start

    def fail_start(self):
        raise RuntimeError("cannot create another thread")

    try:
        monkeypatch.setattr(threading.Thread, "start", fail_start)
        failed = app.open_result(target, None, 1)
        assert failed["ok"] is False
        assert failed["state"] == "error"
        monkeypatch.setattr(threading.Thread, "start", original_start)
        retried = wait(app, app.open_result(target, None, 2))
        assert retried["state"] == "complete"
        assert app.request_close() is True
    finally:
        app.closed()
