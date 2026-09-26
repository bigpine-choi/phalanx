"""Real Windows/WebView2 smoke test using native dialogs and synthetic inputs.

Run from a native Windows environment with the desktop and dev extras installed:
  python tools/check_desktop_native.py --output C:\\Temp\\phalanx-native-review
No bridge responses, selected paths, services, storage or runtime lifecycle are mocked.
The only observation hook attaches a driver to the window created by runtime.main.
"""

from __future__ import annotations

import argparse
import base64
import faulthandler
import hashlib
import json
import os
import sys
import threading
import time
import traceback
from contextlib import suppress
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--relaunch", action="store_true")
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("This harness requires native Windows Python and WebView2.")

    import webview
    import win32con
    import win32gui
    import win32process

    sys.path.insert(0, str(ROOT / "tests"))
    from desktop_helpers import desktop_inputs

    from phalanx.desktop import runtime
    from phalanx.market_data.history.windows_repository import WindowsHistoryRepository
    from phalanx.portfolio.allocation_input.service import AllocationInputService
    from phalanx.portfolio.allocation_targets.service import AllocationTargetsService

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    work = output / "synthetic"
    work.mkdir(exist_ok=True)
    appdata = work / "appdata"
    appdata.mkdir(exist_ok=True)
    os.environ["LOCALAPPDATA"] = str(appdata)
    if args.relaunch:
        database = work / "inputs" / "합성 history.sqlite3"
        selection = work / "inputs" / "선정 selection.json"
    else:
        database, selection = desktop_inputs(work / "inputs")
    service = AllocationTargetsService(AllocationInputService(WindowsHistoryRepository(database)))
    expected = service.calculate_bytes(selection.read_bytes()).to_json_bytes()
    targets = work / "saved-targets.json"
    targets.write_bytes(expected)
    destination = appdata / "Phalanx" / "allocation-targets.json"
    if not args.relaunch and destination.exists():
        raise FileExistsError("Choose a fresh output directory for native verification.")
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    evidence = {
        "scope": "Native Windows runtime.main, actual WebView2, native open/save dialogs",
        "python_executable": sys.executable,
        "process_id": os.getpid(),
        "source_root": str(ROOT),
        "native_windows_webview2": True,
        "mocked_bridge_or_dialogs": False,
        "human_listening": False,
        "relaunch": args.relaunch,
        "steps": [],
    }
    finished = threading.Event()
    closed = threading.Event()
    state = {}
    started = time.monotonic()

    def record(step, **detail):
        evidence["steps"].append({"step": step, **detail})
        print(step, json.dumps(detail, ensure_ascii=True), flush=True)
        (output / "progress.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def wait_for(predicate, label, seconds=30):
        deadline = min(started + args.timeout, time.monotonic() + seconds)
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(0.1)
        raise TimeoutError(label)

    def owned_dialogs():
        dialogs = []

        def visit(handle, _):
            _, process = win32process.GetWindowThreadProcessId(handle)
            if (
                process == os.getpid()
                and win32gui.GetClassName(handle) == "#32770"
                and win32gui.IsWindowVisible(handle)
            ):
                dialogs.append(handle)

        win32gui.EnumWindows(visit, None)
        return dialogs

    def dialog_path(path, *, offered_default=False):
        dialog = wait_for(lambda: next(iter(owned_dialogs()), None), "native file dialog")
        edits = []
        controls = []

        def visit(handle, _):
            kind = win32gui.GetClassName(handle)
            identity = win32gui.GetDlgCtrlID(handle)
            controls.append((kind, identity, win32gui.GetWindowText(handle)))
            if kind == "Edit" and win32gui.IsWindowVisible(handle):
                edits.append(handle)

        win32gui.EnumChildWindows(dialog, visit, None)
        candidates = [handle for handle in edits if win32gui.GetDlgCtrlID(handle) == 1148]
        if not candidates and len(edits) == 1:
            candidates = edits
        if len(candidates) != 1:
            raise AssertionError(f"Cannot identify native filename field: {controls!r}")
        if not offered_default:
            win32gui.SendMessage(candidates[0], win32con.WM_SETTEXT, 0, str(path))
        button = win32gui.GetDlgItem(dialog, win32con.IDOK)
        if not button:
            raise AssertionError("Native file dialog has no OK button")
        win32gui.PostMessage(button, win32con.BM_CLICK, 0, 0)
        wait_for(lambda: not win32gui.IsWindow(dialog), "native file dialog completion")
        record("native-dialog", selected_name=path.name, offered_default=offered_default)

    def driver(window):
        try:
            wait_for(lambda: window.events.loaded.is_set(), "WebView2 loaded")
            from System import Func, Object

            def cdp(method, parameters):
                # Obtain the asynchronous task on the GUI thread, then wait only
                # on this driver thread so the native event loop remains live.
                task = window.native.Invoke(
                    Func[Object](
                        lambda: window.native.webview.CoreWebView2.CallDevToolsProtocolMethodAsync(
                            method, json.dumps(parameters)
                        )
                    )
                )
                # Waiting on Task.Result before completion can hold the Python
                # GIL while WebView2 needs it for a native event callback.
                wait_for(lambda: task.IsCompleted, f"native CDP {method}")
                return json.loads(str(task.Result))

            def js(expression):
                return window.evaluate_js(expression)

            def click(identity):
                record("click", control=identity)
                if identity in ("open-result", "calculate"):
                    state["frames"] = []
                assert js(f"!document.getElementById({json.dumps(identity)}).disabled"), identity
                js(f"document.getElementById({json.dumps(identity)}).click(); true")

            def capture(name):
                png = cdp("Page.captureScreenshot", {"format": "png"})["data"]
                (output / f"{name}.png").write_bytes(base64.b64decode(png))

            def result(label):
                record("await-result", label=label)
                wait_for(
                    lambda: js(
                        "!document.getElementById('save-result').disabled && "
                        "document.querySelector('#room-host iframe') !== null"
                    ),
                    label,
                    seconds=60,
                )
                frame = wait_for(
                    lambda: next(iter(state.get("frames", [])), None), "native result frame"
                )

                def frame_js(expression):
                    task = window.native.Invoke(
                        Func[Object](lambda: frame.ExecuteScriptAsync(expression))
                    )
                    wait_for(lambda: task.IsCompleted, "native frame script")
                    return json.loads(str(task.Result))

                wait_for(
                    lambda: (
                        frame_js("document.querySelectorAll('#scenario-tabs button').length") == 4
                    ),
                    "four rendered scenarios",
                )
                assert frame_js("document.getElementById('sound-state').textContent") == "무음"
                assert frame_js("typeof window.pywebview") == "undefined"
                assert (
                    js("document.querySelector('#room-host iframe').getAttribute('sandbox')")
                    == "allow-scripts"
                )
                assert frame_js(
                    "(() => {try {void parent.pywebview; return false;} "
                    "catch (error) {return error.name === 'SecurityError';}})()"
                )
                data = json.loads(frame_js("document.getElementById('room-data').textContent"))
                for index, scenario in enumerate(data["scenarios"]):
                    frame_js(f"document.querySelectorAll('#scenario-tabs button')[{index}].click()")
                    displayed = frame_js(
                        "Array.from(document.querySelectorAll('.exact-weight code'), "
                        "e => e.textContent)"
                    )
                    assert displayed == [item["weight"] for item in scenario["holdings"]]
                geometry = js(
                    "({width: innerWidth, height: innerHeight, dpr: devicePixelRatio, "
                    "documentWidth: document.documentElement.scrollWidth})"
                )
                assert geometry["documentWidth"] <= geometry["width"]
                capture(label)
                record(label, scenarios=4, exact_weights_match=True, geometry=geometry)

            wait_for(
                lambda: js(
                    "document.getElementById('pick-targets') !== null && "
                    "!document.getElementById('pick-targets').disabled"
                ),
                "native bridge ready",
            )
            evidence["webview2_version"] = str(
                window.native.Invoke(
                    Func[Object](
                        lambda: window.native.webview.CoreWebView2.Environment.BrowserVersionString
                    )
                )
            )
            evidence["renderer"] = str(window.gui.renderer)
            assert evidence["renderer"] == "edgechromium"
            record("boot", version=evidence["webview2_version"])
            capture("00-start-relaunch" if args.relaunch else "00-start")
            click("pick-targets")
            dialog_path(destination if args.relaunch else targets)
            wait_for(
                lambda: js("!document.getElementById('open-result').disabled"), "selected target"
            )
            click("open-result")
            result("01-reopened" if args.relaunch else "01-opened")
            if not args.relaunch:
                click("show-inputs")
                click("pick-calc-selection")
                dialog_path(selection)
                wait_for(
                    lambda: js("!document.getElementById('pick-history').disabled"),
                    "selected input",
                )
                click("pick-history")
                dialog_path(database)
                wait_for(
                    lambda: js("!document.getElementById('calculate').disabled"),
                    "ready to calculate",
                )
                click("calculate")
                result("02-calculated")
                click("save-result")
                dialog_path(destination, offered_default=True)
                wait_for(
                    lambda: js(
                        "document.getElementById('save-status').textContent.includes('저장 완료')"
                    ),
                    "native save completion",
                )
                assert destination.read_bytes() == expected
                capture("03-saved")
                record(
                    "saved",
                    saved_path=str(destination),
                    sha256=hashlib.sha256(expected).hexdigest(),
                    exact_bytes=True,
                )
                window.resize(1280, 720)
                wait_for(lambda: js("innerWidth <= 1280"), "native resized viewport")
                result("04-resized-1280x720")
            assert hashlib.sha256(database.read_bytes()).hexdigest() == before
            record("database-preserved", sha256=before)
            evidence["passed"] = True
        except BaseException:
            with suppress(Exception):
                capture("failure")
            with suppress(Exception):
                evidence["failure_document"] = window.evaluate_js(
                    "({url: location.href, body: document.body?.innerText, "
                    "html: document.documentElement.outerHTML.slice(0, 4000)})"
                )
            evidence["passed"] = False
            evidence["error"] = traceback.format_exc()
            print(evidence["error"], file=sys.stderr, flush=True)
        finally:
            finished.set()
            for dialog in owned_dialogs():
                win32gui.PostMessage(dialog, win32con.WM_CLOSE, 0, 0)
            handle = state.get("handle")
            if handle and win32gui.IsWindow(handle):
                win32gui.PostMessage(handle, win32con.WM_CLOSE, 0, 0)

    original = webview.create_window

    def observe_window(*positional, **keywords):
        window = original(*positional, **keywords)
        state["window"] = window

        def ready():
            state["handle"] = window.native.Handle.ToInt64()
            threading.Thread(target=driver, args=(window,), daemon=True).start()

        def observe_navigation():
            def frame_created(_sender, event):
                state.setdefault("frames", []).append(event.Frame)

            def webview_ready(sender, event):
                if event.IsSuccess:
                    sender.CoreWebView2.FrameCreated += frame_created

            window.native.webview.CoreWebView2InitializationCompleted += webview_ready

            def navigation_starting(_sender, event):
                uri = str(event.Uri)
                record(
                    "navigation-starting",
                    uri_prefix=uri[:64],
                    uri_sha256=hashlib.sha256(uri.encode()).hexdigest(),
                )

            def navigation_completed(_sender, event):
                record(
                    "navigation-completed",
                    success=bool(event.IsSuccess),
                    error=str(event.WebErrorStatus),
                )

            window.native.webview.NavigationStarting += navigation_starting
            window.native.webview.NavigationCompleted += navigation_completed

        window.events.before_show += observe_navigation
        window.events.shown += ready
        window.events.closed += lambda: closed.set()
        return window

    def watchdog():
        if not closed.wait(args.timeout):
            evidence["passed"] = False
            evidence["watchdog"] = "timeout; requested close for only the owned application/dialogs"
            for handle in owned_dialogs():
                win32gui.PostMessage(handle, win32con.WM_CLOSE, 0, 0)
            handle = state.get("handle")
            if handle and win32gui.IsWindow(handle):
                win32gui.PostMessage(handle, win32con.WM_CLOSE, 0, 0)
            if not closed.wait(10):
                evidence["error"] = "Owned application did not close after the watchdog request."
                (output / "watchdog.json").write_text(
                    json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                os._exit(124)

    webview.create_window = observe_window
    threading.Thread(target=watchdog, daemon=True).start()
    stacklog = (output / "thread-stacks.log").open("w", encoding="utf-8")
    faulthandler.dump_traceback_later(args.timeout + 15, file=stacklog, exit=True)
    try:
        evidence["runtime_exit"] = runtime.main()
    finally:
        faulthandler.cancel_dump_traceback_later()
        stacklog.close()
        webview.create_window = original
        evidence["closed"] = closed.is_set()
        evidence["driver_finished"] = finished.is_set()
        evidence["elapsed_seconds"] = round(time.monotonic() - started, 3)
        name = "validation-relaunch.json" if args.relaunch else "validation.json"
        (output / name).write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return (
        0 if evidence.get("passed") and evidence["closed"] and evidence["runtime_exit"] == 0 else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
