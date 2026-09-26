"""Optional Windows GUI boundary; no pywebview import during headless imports."""

from __future__ import annotations

import base64
import importlib
import secrets
import sys
import threading
from collections.abc import Callable, Mapping
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

from phalanx.desktop.storage import SettingsStore, app_data_directory
from phalanx.desktop.view import render_shell

if TYPE_CHECKING:
    from phalanx.desktop.application import DesktopApplication


class NativeBridge:
    """Expose only explicit operations, authorizing paths through native dialogs.

    All attributes and lifecycle helpers are private so pywebview's reflection
    cannot expose the application, window, filesystem, or arbitrary execution.
    """

    def __init__(
        self,
        application: DesktopApplication,
        settings: SettingsStore,
        choose: Callable[[str], Path | None],
        choose_save: Callable[[], Path | None],
    ) -> None:
        self._application = application
        self._settings = settings
        self._choose = choose
        self._choose_save = choose_save
        self._paths: dict[str, tuple[str, Path]] = {}
        self._lock = threading.RLock()
        self._dialog_lock = threading.Lock()
        self._settings_lock = threading.Lock()
        self._closing = False

    def _shutdown(self) -> None:
        with self._lock:
            self._closing = True
            self._paths.clear()

    def _error(self, message: str, **identity: object) -> dict[str, object]:
        return {"ok": False, "error": message, **identity}

    def _path(self, token: str, kind: str) -> Path:
        if self._closing:
            raise ValueError("종료 중에는 새 요청을 받을 수 없습니다.")
        if not isinstance(token, str) or len(token) > 128:
            raise ValueError("앱의 파일 선택 버튼으로 입력을 선택하세요.")
        entry = self._paths.get(token)
        if entry is None or entry[0] != kind:
            raise ValueError("앱의 파일 선택 버튼으로 입력을 다시 선택하세요.")
        return entry[1]

    def bootstrap(self) -> dict[str, object]:
        with self._lock:
            if self._closing:
                return self._error("앱을 종료하고 있습니다.")
        loaded = self._settings.load()
        return {"ok": True, "preferences": loaded.settings, "notice": loaded.notice}

    def choose_file(self, kind: str) -> dict[str, object]:
        if kind not in ("targets", "selection", "history"):
            return self._error("지원하지 않는 파일 종류입니다.")
        if not self._dialog_lock.acquire(blocking=False):
            return self._error("이미 파일 선택 창이 열려 있습니다.")
        try:
            with self._lock:
                if self._closing:
                    return self._error("앱을 종료하고 있습니다.")
            path = self._choose(kind)
            with self._lock:
                if self._closing:
                    return self._error("앱을 종료하고 있습니다.")
                if path is None:
                    return {"ok": True, "cancelled": True}
                token = secrets.token_urlsafe(24)
                self._paths[token] = (kind, path)
                if len(self._paths) > 32:
                    del self._paths[next(iter(self._paths))]
                return {"ok": True, "token": token, "name": path.name}
        except Exception:
            return self._error("파일 선택 창을 열지 못했습니다. Windows 실행 환경을 확인하세요.")
        finally:
            self._dialog_lock.release()

    def open_result(
        self, targets_token: str, selection_token: str | None, generation: int
    ) -> dict[str, object]:
        with self._lock:
            try:
                targets = self._path(targets_token, "targets")
                selection = (
                    None if selection_token is None else self._path(selection_token, "selection")
                )
            except ValueError as exc:
                return self._error(str(exc), generation=generation)
            return self._application.open_result(targets, selection, generation)

    def calculate(
        self, selection_token: str, history_token: str, generation: int
    ) -> dict[str, object]:
        with self._lock:
            try:
                selection = self._path(selection_token, "selection")
                history = self._path(history_token, "history")
            except ValueError as exc:
                return self._error(str(exc), generation=generation)
            return self._application.calculate(selection, history, generation)

    def job_status(self, job_id: str, generation: int) -> dict[str, object]:
        with self._lock:
            if self._closing:
                return self._error("앱을 종료하고 있습니다.", job_id=job_id, generation=generation)
            return self._application.job_status(job_id, generation)

    def save_result(self, job_id: str, generation: int) -> dict[str, object]:
        identity = {"job_id": job_id, "generation": generation}
        if not self._dialog_lock.acquire(blocking=False):
            return self._error("이미 파일 선택 창이 열려 있습니다.", **identity)
        try:
            with self._lock:
                if self._closing:
                    return self._error("앱을 종료하고 있습니다.", **identity)
                current = self._application.job_status(job_id, generation)
                if not current.get("ok") or current.get("state") != "complete":
                    return self._error("현재 표시 중인 완료 결과만 저장할 수 있습니다.", **identity)
            destination = self._choose_save()
            if destination is None:
                return {"ok": True, "cancelled": True, **identity}
            with self._lock:
                if self._closing:
                    return self._error("앱을 종료하고 있습니다.", **identity)
            return self._application.save_result(job_id, generation, destination)
        except Exception:
            return self._error(
                "저장 경로 또는 접근 권한을 확인하세요. 결과는 보존되어 있습니다.", **identity
            )
        finally:
            self._dialog_lock.release()

    def save_preferences(self, preferences: Mapping[str, object]) -> dict[str, object]:
        with self._settings_lock, self._lock:
            if self._closing:
                return self._error("앱을 종료하고 있습니다.")
            try:
                saved = self._settings.save(preferences)
                return {"ok": True, "preferences": saved}
            except (OSError, TypeError, ValueError):
                return self._error("설정 저장 실패 · 현재 화면의 설정은 유지됩니다.")


class _Lifecycle:
    """Serialize native events and finish worker cleanup before destroying the window."""

    def __init__(
        self,
        window: Any,
        application: DesktopApplication,
        bridge: NativeBridge,
        *,
        shell_html: str | None = None,
        dispatch: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        self._window = window
        self._application = application
        self._bridge = bridge
        self._dispatch = dispatch or self._native_dispatch
        trusted_shell = render_shell() if shell_html is None else shell_html
        self._shell_data_uri = "data:text/html;charset=utf-8;base64," + base64.b64encode(
            trusted_shell.encode("utf-8")
        ).decode("ascii")
        self._lock = threading.RLock()
        self._loaded = False
        self._closed = False
        self._finalizing = False
        self._finalizer: threading.Thread | None = None
        self._destroying = threading.Event()
        self.engine_error: str | None = None

    def initialized(self, renderer: str) -> bool:
        if renderer == "edgechromium":
            return True
        self.engine_error = (
            "Edge Chromium(WebView2)을 사용할 수 없습니다. Microsoft Edge WebView2 "
            "Evergreen Runtime과 .NET Framework 4.6.2 이상을 설치하고 다시 실행하세요. "
            "다른 렌더링 엔진으로 창을 열지 않았습니다."
        )
        return False

    def loaded(self) -> None:
        with self._lock:
            if not self._closed:
                self._loaded = True

    def _script(self, method: str) -> None:
        # Only fixed, package-owned calls; no user JSON, paths, or errors are interpolated.
        scripts = {
            "silence": "window.PhalanxDesktopLifecycle?.silence();",
            "closing": "window.PhalanxDesktopLifecycle?.closePending();",
        }

        def execute() -> None:
            # A native control can be disposed between BeginInvoke and execution.
            with self._lock, suppress(Exception):
                if self._closed or self._destroying.is_set() or not self._loaded:
                    return
                core = self._window.native.webview.CoreWebView2
                if core is not None:
                    # Fire and forget on the GUI thread. pywebview run_js waits
                    # for a continuation and can deadlock while the form closes.
                    core.ExecuteScriptAsync(scripts[method])

        with self._lock:
            if self._closed or self._destroying.is_set() or not self._loaded:
                return
        # Disposal can race a queued minimize notification; never resurrect
        # a window or call JS after the native control has gone away.
        with suppress(Exception):
            self._dispatch(execute)

    def _native_dispatch(self, callback: Callable[[], None]) -> None:
        action = importlib.import_module("System").Action(callback)
        self._window.native.BeginInvoke(action)

    def minimized(self) -> None:
        self._script("silence")

    def closing(self) -> bool:
        # pywebview closing is synchronous on the Windows GUI thread. run_js
        # waits for that thread's WebView2 continuation and MUST NOT run here.
        self._bridge._shutdown()
        immediate = self._application.request_close()
        if immediate:
            self._destroying.set()
        else:
            self._script("closing")
        return immediate

    def before_show(self) -> None:
        browser = self._window.native.webview
        browser.NavigationStarting += self.navigation_starting
        browser.CoreWebView2InitializationCompleted += self.webview_initialized

    def navigation_starting(self, _sender: object, event: Any) -> None:
        # WebView2 can report NavigateToString as a base64 data URI even though
        # the loaded document has about:blank as its URL. Allow only the exact
        # package HTML passed to create_window; other data/file/external URLs
        # must never replace the privileged document. srcdoc stays sandboxed.
        if str(event.Uri) not in ("about:blank", self._shell_data_uri):
            event.Cancel = True

    def webview_initialized(self, _sender: object, event: Any) -> None:
        if event.IsSuccess:
            return
        self.engine_error = (
            "WebView2 초기화가 실패했습니다. Microsoft Edge WebView2 Evergreen Runtime을 "
            "설치·복구하고 Windows 사용자 권한과 앱 데이터 접근 권한을 확인하세요."
        )
        self._bridge._shutdown()
        self.finish_close()

    def finish_close(self) -> None:
        # Never synchronously destroy a native window from the calculation worker:
        # its closed event may join that same worker.
        with self._lock:
            if self._closed or self._finalizing:
                return
            self._finalizing = True
            self._finalizer = threading.Thread(
                target=self._finish_close, name="phalanx-close", daemon=False
            )
            try:
                self._finalizer.start()
            except RuntimeError:
                self._finalizing = False
                self._finalizer = None
                print(
                    "종료 알림을 예약하지 못했습니다. 작업 완료 후 창 닫기를 다시 눌러 주세요.",
                    file=sys.stderr,
                )

    def _finish_close(self) -> None:
        self._application.closed()
        with self._lock:
            if self._closed:
                return
            self._destroying.set()
        self._window.destroy()

    def closed(self) -> None:
        with self._lock:
            self._closed = True
            self._loaded = False
        self._bridge._shutdown()
        self._application.closed()

    def cleanup(self) -> None:
        self.closed()
        if self._finalizer is not None and self._finalizer is not threading.current_thread():
            self._finalizer.join()


def _first_path(value: object) -> Path | None:
    if isinstance(value, str):
        return Path(value)
    if isinstance(value, (list, tuple)) and value and isinstance(value[0], str):
        return Path(value[0])
    return None


def _prepare_webview_storage(directory: Path) -> Path:
    from phalanx.platforms.windows_files import ensure_private_directory

    storage = directory / "webview2"
    ensure_private_directory(storage)
    return storage


def main() -> int:
    if sys.platform != "win32":
        print(
            "Windows 독립 앱은 네이티브 Windows Python에서 실행하세요. "
            "PowerShell에서 별도 가상환경에 uv sync --extra desktop 후 "
            "uv run --extra desktop python -m phalanx.desktop 을 실행하세요. "
            "WSL의 .venv와 Windows 가상환경을 공유하지 마세요.",
            file=sys.stderr,
        )
        return 2
    if threading.current_thread() is not threading.main_thread():
        print("GUI 진입점은 Windows Python의 주 스레드에서 실행해야 합니다.", file=sys.stderr)
        return 2
    try:
        webview = importlib.import_module("webview")
    except ImportError:
        print(
            "desktop 의존성이 없습니다. Windows PowerShell에서 "
            "uv sync --extra desktop 을 실행하세요. Microsoft Edge WebView2 "
            "Evergreen Runtime도 필요합니다.",
            file=sys.stderr,
        )
        return 2

    from phalanx.desktop.application import DesktopApplication

    lifecycle: _Lifecycle | None = None
    try:
        application = DesktopApplication()
        settings = SettingsStore()
        directory = app_data_directory()
        webview_storage = _prepare_webview_storage(directory)
        webview.settings["ALLOW_FILE_URLS"] = False
        webview.settings["ALLOW_DOWNLOADS"] = False
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False
        webview.settings["REMOTE_DEBUGGING_PORT"] = None
        webview.settings["OPEN_DEVTOOLS_IN_DEBUG"] = False
        window: Any = None

        def choose(kind: str) -> Path | None:
            types = (
                ("SQLite (*.db;*.sqlite;*.sqlite3)",) if kind == "history" else ("JSON (*.json)",)
            )
            return _first_path(
                window.create_file_dialog(
                    webview.FileDialog.OPEN, allow_multiple=False, file_types=types
                )
            )

        def choose_save() -> Path | None:
            return _first_path(
                window.create_file_dialog(
                    webview.FileDialog.SAVE,
                    directory=str(directory),
                    save_filename="allocation-targets.json",
                    file_types=("JSON (*.json)",),
                )
            )

        bridge = NativeBridge(application, settings, choose, choose_save)
        shell_html = render_shell()
        window = webview.create_window(
            "PHALANX · 편성실",
            html=shell_html,
            js_api=bridge,
            width=1440,
            height=900,
            min_size=(1000, 680),
            background_color="#091722",
            text_select=True,
            zoomable=False,
        )
        lifecycle = _Lifecycle(window, application, bridge, shell_html=shell_html)
        window.events.initialized += lifecycle.initialized
        window.events.before_show += lifecycle.before_show
        window.events.loaded += lifecycle.loaded
        window.events.minimized += lifecycle.minimized
        window.events.closing += lifecycle.closing
        window.events.closed += lifecycle.closed
        application.set_close_callback(lifecycle.finish_close)
        # Explicit engine plus initialized guard: pywebview can otherwise select
        # deprecated MSHTML when WebView2 is absent, even with this gui argument.
        webview.start(
            gui="edgechromium",
            debug=False,
            http_server=False,
            private_mode=True,
            storage_path=str(webview_storage),
        )
        if lifecycle.engine_error:
            print(lifecycle.engine_error, file=sys.stderr)
            return 2
        return 0
    except Exception as exc:
        print(
            f"Windows 편성실을 시작하지 못했습니다 ({type(exc).__name__}). "
            "네이티브 Windows Python, desktop 의존성, Microsoft Edge WebView2 Evergreen "
            "Runtime, .NET Framework 4.6.2 이상과 앱 데이터 폴더 접근 권한을 확인하세요.",
            file=sys.stderr,
        )
        return 2
    finally:
        if lifecycle is not None:
            lifecycle.cleanup()
