"""Headless native boundary contracts. These are not Windows/WebView2 execution tests."""

from __future__ import annotations

import base64
import inspect
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from phalanx.desktop import runtime
from phalanx.desktop.application import DesktopApplication
from phalanx.desktop.runtime import NativeBridge, _Lifecycle
from phalanx.desktop.storage import DEFAULT_SETTINGS, SettingsStore


def test_import_does_not_load_gui_cli_or_posix_history():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import phalanx.desktop.runtime; import phalanx.desktop.application; "
            "assert 'webview' not in sys.modules; assert 'phalanx.cli' not in sys.modules; "
            "assert 'phalanx.market_data.history.repository' not in sys.modules",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_native_bridge_exposes_only_explicit_operations():
    public = {name for name, value in inspect.getmembers(NativeBridge) if not name.startswith("_")}
    assert public == {
        "bootstrap",
        "choose_file",
        "open_result",
        "calculate",
        "job_status",
        "save_result",
        "save_preferences",
    }


def make_bridge(tmp_path, choose=lambda kind: None):
    app = DesktopApplication()
    store = SettingsStore(tmp_path / "settings")
    return app, NativeBridge(app, store, choose, lambda: tmp_path / "result.json")


def test_bridge_requires_native_tokens_and_matching_kind(tmp_path, monkeypatch):
    app, bridge = make_bridge(tmp_path, lambda kind: tmp_path / "한글 파일.json")
    called = []
    monkeypatch.setattr(app, "open_result", lambda *args: called.append(args) or {"ok": True})
    assert bridge.open_result(str(tmp_path / "secret.json"), None, 1)["ok"] is False
    selection = bridge.choose_file("selection")
    targets = bridge.choose_file("targets")
    assert "path" not in targets and targets["name"] == "한글 파일.json"
    assert bridge.open_result(selection["token"], None, 1)["ok"] is False
    assert bridge.open_result(targets["token"], selection["token"], 1)["ok"] is True
    assert called == [(tmp_path / "한글 파일.json", tmp_path / "한글 파일.json", 1)]
    assert bridge.choose_file("arbitrary")["ok"] is False
    bridge._shutdown()
    assert bridge.open_result(targets["token"], None, 2)["ok"] is False
    assert bridge.choose_file("targets")["ok"] is False
    assert bridge.save_preferences(DEFAULT_SETTINGS)["ok"] is False


def test_bridge_dialog_cancellation_and_duplicate_requests(tmp_path):
    started, release = threading.Event(), threading.Event()

    def choose(kind):
        started.set()
        assert release.wait(2)
        return None

    _, bridge = make_bridge(tmp_path, choose)
    replies = []
    worker = threading.Thread(target=lambda: replies.append(bridge.choose_file("targets")))
    worker.start()
    assert started.wait(2)
    assert bridge.choose_file("targets")["ok"] is False
    release.set()
    worker.join(2)
    assert not worker.is_alive()
    assert replies == [{"ok": True, "cancelled": True}]
    assert bridge.save_result("unknown", 1)["ok"] is False


def test_bridge_rejects_extra_settings(tmp_path):
    _, bridge = make_bridge(tmp_path)
    assert bridge.bootstrap()["preferences"] == DEFAULT_SETTINGS
    assert bridge.save_preferences({**DEFAULT_SETTINGS, "token": "credential"})["ok"] is False
    changed = {"sfxVolume": 31, "musicVolume": 7, "reduceMotion": True}
    assert bridge.save_preferences(changed)["ok"] is True
    assert bridge.bootstrap()["preferences"] == changed


class FakeWindow:
    def __init__(self):
        self.scripts = []
        self.destroyed = threading.Event()
        self.native = SimpleNamespace(
            webview=SimpleNamespace(
                CoreWebView2=SimpleNamespace(ExecuteScriptAsync=self.scripts.append)
            )
        )

    def run_js(self, script):
        self.scripts.append(script)

    def destroy(self):
        self.destroyed.set()


def test_lifecycle_rejects_fallback_and_never_calls_js_after_closed(tmp_path):
    app, bridge = make_bridge(tmp_path)
    window = FakeWindow()
    lifecycle = _Lifecycle(window, app, bridge, dispatch=lambda callback: callback())
    assert not lifecycle.initialized("mshtml")
    assert "WebView2" in lifecycle.engine_error
    assert lifecycle.initialized("edgechromium")
    lifecycle.minimized()
    assert window.scripts == []
    lifecycle.loaded()
    lifecycle.minimized()
    assert window.scripts == ["window.PhalanxDesktopLifecycle?.silence();"]
    assert lifecycle.closing()
    lifecycle.closed()
    scripts = list(window.scripts)
    lifecycle.minimized()
    lifecycle.loaded()
    lifecycle.finish_close()
    lifecycle.cleanup()
    assert window.scripts == scripts
    assert not window.destroyed.is_set()


def test_close_waits_for_worker_then_destroys_without_worker_deadlock(tmp_path):
    app, bridge = make_bridge(tmp_path)
    entered, release = threading.Event(), threading.Event()
    window = FakeWindow()
    lifecycle = _Lifecycle(window, app, bridge, dispatch=lambda callback: callback())
    app.set_close_callback(lifecycle.finish_close)

    def work():
        entered.set()
        assert release.wait(2)

    response = app._start(1, work)
    assert response["state"] == "running"
    assert entered.wait(2)
    assert lifecycle.closing() is False
    assert not window.destroyed.is_set()
    release.set()
    assert window.destroyed.wait(2)
    lifecycle.cleanup()
    assert not any(t.name.startswith("phalanx-") for t in threading.enumerate())


def test_non_native_entry_returns_actionable_message(monkeypatch, capsys):
    monkeypatch.setattr(runtime.sys, "platform", "linux")
    assert runtime.main() == 2
    assert "PowerShell" in capsys.readouterr().err


def test_main_thread_required_even_on_windows(monkeypatch, capsys):
    monkeypatch.setattr(runtime.sys, "platform", "win32")
    results = []
    thread = threading.Thread(target=lambda: results.append(runtime.main()))
    thread.start()
    thread.join()
    assert results == [2]
    assert "주 스레드" in capsys.readouterr().err


@pytest.mark.parametrize("renderer,code", [("edgechromium", 0), ("mshtml", 2)])
def test_start_forces_engine_and_aborts_fallback_before_show(
    tmp_path, monkeypatch, capsys, renderer, code
):
    # Model the documented pywebview initialized event, not the Windows implementation.
    class Event:
        def __init__(self):
            self.callbacks = []

        def __iadd__(self, callback):
            self.callbacks.append(callback)
            return self

        def fire(self, *args):
            return all(callback(*args) is not False for callback in self.callbacks)

    window = FakeWindow()
    window.events = SimpleNamespace(
        **{
            name: Event()
            for name in ("initialized", "before_show", "loaded", "minimized", "closing", "closed")
        }
    )
    created, starts, shown = [], [], []

    def create(*args, **kwargs):
        created.append(kwargs)
        return window

    def start(**kwargs):
        starts.append(kwargs)
        if not window.events.initialized.fire(renderer):
            return
        shown.append(True)
        window.events.loaded.fire()
        assert window.events.closing.fire()
        window.events.closed.fire()

    fake = SimpleNamespace(settings={}, create_window=create, start=start)
    monkeypatch.setattr(runtime.sys, "platform", "win32")
    original_import = runtime.importlib.import_module
    monkeypatch.setattr(
        runtime.importlib,
        "import_module",
        lambda name, *args: fake if name == "webview" else original_import(name, *args),
    )
    monkeypatch.setattr(runtime, "SettingsStore", lambda: object())
    monkeypatch.setattr(runtime, "app_data_directory", lambda: tmp_path)
    monkeypatch.setattr(
        runtime, "_prepare_webview_storage", lambda directory: directory / "webview2"
    )
    assert runtime.main() == code
    assert starts == [
        {
            "gui": "edgechromium",
            "debug": False,
            "http_server": False,
            "private_mode": True,
            "storage_path": str(tmp_path / "webview2"),
        }
    ]
    assert bool(shown) == (renderer == "edgechromium")
    assert created[0]["html"].startswith("<!doctype html>")
    assert fake.settings["ALLOW_FILE_URLS"] is False
    if code:
        assert "WebView2" in capsys.readouterr().err


def test_queued_native_audio_notification_is_discarded_after_close(tmp_path):
    app, bridge = make_bridge(tmp_path)
    window = FakeWindow()
    pending = []
    lifecycle = _Lifecycle(window, app, bridge, dispatch=pending.append)
    lifecycle.loaded()
    lifecycle.minimized()
    assert len(pending) == 1 and not window.scripts
    assert lifecycle.closing() is True
    lifecycle.closed()
    pending.pop()()
    assert not window.scripts
    lifecycle.cleanup()


def test_native_navigation_keeps_bridge_document_package_owned(tmp_path):
    app, bridge = make_bridge(tmp_path)
    lifecycle = _Lifecycle(FakeWindow(), app, bridge)
    shell = runtime.render_shell()
    data_prefix = "data:text/html;charset=utf-8;base64,"
    trusted_uri = data_prefix + base64.b64encode(shell.encode("utf-8")).decode("ascii")
    modified_uri = data_prefix + base64.b64encode((shell + " ").encode("utf-8")).decode("ascii")
    for uri in (
        "https://example.com",
        "file:///private.json",
        "data:text/html,hello",
        data_prefix,
        data_prefix + base64.b64encode(b"<script>parent.pywebview</script>").decode("ascii"),
        modified_uri,
        trusted_uri + "#fragment",
        "about:blank#fragment",
    ):
        event = SimpleNamespace(Uri=uri, Cancel=False)
        lifecycle.navigation_starting(None, event)
        assert event.Cancel is True
    for uri in ("about:blank", trusted_uri):
        initial = SimpleNamespace(Uri=uri, Cancel=False)
        lifecycle.navigation_starting(None, initial)
        assert initial.Cancel is False
    lifecycle.cleanup()


def test_close_finalizer_start_failure_allows_manual_close(tmp_path, monkeypatch, capsys):
    app, bridge = make_bridge(tmp_path)
    lifecycle = _Lifecycle(FakeWindow(), app, bridge)

    def reject_start(self):
        raise RuntimeError("no thread resources")

    monkeypatch.setattr(threading.Thread, "start", reject_start)
    lifecycle.finish_close()
    assert lifecycle._finalizer is None
    assert lifecycle.closing() is True
    lifecycle.cleanup()
    assert "창 닫기를 다시" in capsys.readouterr().err
