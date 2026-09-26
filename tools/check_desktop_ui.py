"""Chromium integration checks with real Python services and mocked native dialogs.

This is NOT native Windows/WebView2 validation or human listening. Run with an
isolated Playwright environment and an installed phalanx working tree:
  uv run --with playwright python tools/check_desktop_ui.py --output /tmp/desktop-ui
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tests" / "browser"))

from desktop_helpers import FIXTURES, desktop_inputs  # noqa: E402
from verify_desktop_recovery import verify_desktop_recovery  # noqa: E402
from verify_formation_room_audio import INSTRUMENT  # noqa: E402

from phalanx.desktop.application import DesktopApplication  # noqa: E402
from phalanx.desktop.runtime import NativeBridge  # noqa: E402
from phalanx.desktop.storage import SettingsStore  # noqa: E402
from phalanx.desktop.view import render_shell  # noqa: E402
from phalanx.portfolio.allocation_input.service import AllocationInputService  # noqa: E402
from phalanx.portfolio.allocation_targets.service import AllocationTargetsService  # noqa: E402

METHODS = (
    "bootstrap",
    "choose_file",
    "open_result",
    "calculate",
    "job_status",
    "save_result",
    "save_preferences",
)


def repository(path):
    if sys.platform == "win32":
        from phalanx.market_data.history.windows_repository import WindowsHistoryRepository

        return WindowsHistoryRepository(path)
    from phalanx.market_data.history.repository import SqliteHistoryRepository

    return SqliteHistoryRepository(path)


def result_frame(page):
    expect(page.locator("#save-result")).to_be_enabled(timeout=60000)
    page.frame_locator("#room-host iframe").locator("#scenario-tabs button").first.wait_for()
    return page.locator("#room-host iframe").element_handle().content_frame()


def capture(page, directory, name):
    page.screenshot(path=str(directory / f"{name}.png"), full_page=False)
    geometry = page.evaluate(
        """() => ({viewport: [innerWidth, innerHeight], dpr: devicePixelRatio,
        documentWidth: document.documentElement.scrollWidth,
        zoom: getComputedStyle(document.documentElement).zoom})"""
    )
    assert geometry["documentWidth"] <= geometry["viewport"][0]
    if page.locator("#room-host iframe").count():
        frame = page.locator("#room-host iframe").element_handle().content_frame()
        geometry["room"] = frame.evaluate(
            """() => ({width: innerWidth, documentWidth: document.documentElement.scrollWidth,
            scrollHeight: document.documentElement.scrollHeight,
            cards: [...document.querySelectorAll('.holding-card')].map(e => {
                const r = e.getBoundingClientRect();
                return {code: e.dataset.code, width: r.width, right: r.right};
            })})"""
        )
        assert geometry["room"]["documentWidth"] <= geometry["room"]["width"]
        assert all(card["right"] <= geometry["room"]["width"] for card in geometry["room"]["cards"])
    return geometry


def run_viewport(browser, output, width, height, inputs):
    database, selection, targets, expected, long_selection, invalid, partial = inputs
    directory = output / f"{width}x{height}"
    directory.mkdir(parents=True, exist_ok=True)
    choices = {"history": database, "selection": selection, "targets": targets}
    work = database.parent.parent / f"ui-{width}x{height}"
    work.mkdir(mode=0o700, exist_ok=True)
    save_path = work / "합성 저장 결과.json"
    app = DesktopApplication(repository_factory=repository)
    settings = SettingsStore(work / "settings")
    bridge = NativeBridge(app, settings, lambda kind: choices[kind], lambda: save_path)
    calls = []
    context = browser.new_context(
        viewport={"width": width, "height": height},
        device_scale_factor=1,
        locale="ko-KR",
        reduced_motion="no-preference",
    )
    context.add_init_script(INSTRUMENT)
    page = context.new_page()
    errors = []
    requests = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("request", lambda request: requests.append(request.url))
    captures = {}
    try:
        for method in METHODS:

            def invoke(*args, method=method):
                calls.append(method)
                return getattr(bridge, method)(*args)

            page.expose_function("native_" + method, invoke)
        page.set_content(render_shell())
        expect(page.locator("#pick-targets")).to_be_disabled()
        page.evaluate(
            """methods => {
                window.pywebview = {api: Object.fromEntries(methods.map(name =>
                    [name, (...args) => window['native_' + name](...args)]))};
                window.dispatchEvent(new Event('pywebviewready'));
            }""",
            list(METHODS),
        )
        expect(page.locator("#pick-targets")).to_be_enabled()
        captures["start"] = capture(page, directory, "01-start")

        page.locator("#pick-calc-selection").click()
        expect(page.locator("#calc-selection-name")).to_have_text(selection.name)
        page.locator("#pick-history").click()
        expect(page.locator("#calculate")).to_be_enabled()
        page.evaluate(
            """() => {const form = document.getElementById('calculate-form');
            form.dispatchEvent(new Event('submit', {cancelable:true}));
            form.dispatchEvent(new Event('submit', {cancelable:true}));} """
        )
        frame = result_frame(page)
        assert calls.count("calculate") == 1
        assert frame.locator("#overall-status").inner_text() == "네 시나리오 산출 완료"
        assert frame.locator("#sound-state").inner_text() == "무음"
        assert frame.evaluate("window.__audioProbe.contexts") == 0
        assert frame.evaluate("typeof window.pywebview") == "undefined"
        assert frame.evaluate(
            """() => {try {void parent.pywebview; return false;} catch(e) {return true;}}"""
        )
        captures["calculated"] = capture(page, directory, "02-calculated")
        source = frame.locator("#room-data").text_content()
        payload = json.loads(source)
        assert payload["selected_codes"] == json.loads(expected)["selected_codes"]
        tabs = frame.locator("#scenario-tabs button")
        tabs.nth(0).focus()
        tabs.nth(0).press("ArrowRight")
        expect(tabs.nth(1)).to_have_attribute("aria-selected", "true")
        for index in range(4):
            tabs.nth(index).click()
            displayed = frame.locator(".exact-weight code").all_text_contents()
            assert displayed == [
                holding["weight"] for holding in payload["scenarios"][index]["holdings"]
            ]
        frame.locator(".holding-card").nth(0).focus()
        frame.locator(".holding-card").nth(0).press("ArrowRight")
        expect(frame.locator(".holding-card").nth(1)).to_have_attribute("aria-pressed", "true")
        frame.locator("#evidence-panel summary").click()
        expect(frame.locator("#evidence-panel")).to_have_attribute("open", "")

        page.locator("#save-result").click()
        expect(page.locator("#save-status")).to_contain_text("저장 완료")
        assert save_path.read_bytes() == expected
        page.locator("#save-result").click()
        expect(page.locator("#save-status")).to_contain_text("저장 실패")
        assert page.locator("#room-host iframe").count() == 1
        assert save_path.read_bytes() == expected
        captures["save_failure"] = capture(page, directory, "03-save-conflict")
        save_path = work / "재시도 결과.json"
        page.locator("#save-result").click()
        expect(page.locator("#save-status")).to_contain_text("저장 완료")
        assert save_path.read_bytes() == expected

        frame.locator("#settings-open").click()
        frame.locator("#sfx-volume").fill("37")
        frame.locator("#reduce-motion").check()
        frame.locator("#music-start").click()
        frame.wait_for_function("window.__roomAudio.getState().musicPlaying")
        assert frame.evaluate("window.__audioProbe.maxTimers") == 1
        page.evaluate("window.PhalanxDesktopLifecycle.silence()")
        frame.wait_for_function("!window.__roomAudio.getState().enabled")
        assert frame.evaluate("window.__roomAudio.getState().scheduledTimer") is False
        page.wait_for_timeout(100)
        assert frame.evaluate("window.__roomAudio.getState().musicPlaying") is False
        captures["settings"] = capture(page, directory, "04-settings-muted")
        frame.locator("#settings-done").click()
        assert settings.load().settings["sfxVolume"] == 37
        assert settings.load().settings["reduceMotion"] is True

        page.locator("#show-inputs").click()
        choices["targets"] = targets
        page.locator("#pick-targets").click()
        page.locator("#open-result").click()
        frame = result_frame(page)
        assert frame.locator(".holding-name").first.inner_text() == "이름 미확인"
        assert frame.locator("#sound-state").inner_text() == "무음"
        assert frame.evaluate("window.__audioProbe.contexts") == 0
        assert frame.locator("#sfx-volume").input_value() == "37"
        captures["no_selection"] = capture(page, directory, "05-saved-no-selection")

        page.locator("#show-inputs").click()
        choices["selection"] = selection
        page.locator("#pick-open-selection").click()
        page.locator("#open-result").click()
        frame = result_frame(page)
        assert "합성" in frame.locator(".holding-name").first.inner_text()

        page.locator("#show-inputs").click()
        choices["selection"] = long_selection
        page.locator("#pick-open-selection").click()
        page.locator("#open-result").click()
        expect(page.locator("#notice")).to_be_visible(timeout=60000)
        assert page.locator("#room-host iframe").count() == 0
        expect(page.locator("#save-result")).to_be_disabled()
        captures["bad_selection"] = capture(page, directory, "06-selection-mismatch")

        # Retry with the producer fixture, which already contains a long Korean name.
        choices["selection"] = selection
        page.locator("#pick-calc-selection").click()
        page.locator("#calculate").click()
        frame = result_frame(page)
        long_card = frame.locator(".holding-card").filter(has_text="아주 긴").first
        long_card.click()
        assert "아주 긴" in frame.locator("#detail-title").inner_text()
        captures["long_names"] = capture(page, directory, "07-long-names")

        page.locator("#show-inputs").click()
        choices["targets"] = partial
        page.locator("#pick-targets").click()
        page.locator("#clear-open-selection").click()
        page.locator("#open-result").click()
        frame = result_frame(page)
        assert json.loads(frame.locator("#room-data").text_content())["status"] == "partial"
        failed_tab = (
            frame.locator("#scenario-tabs .scenario-tab")
            .filter(has=frame.locator(".failure"))
            .first
        )
        failed_tab.click()
        expect(frame.locator("#scenario-notice")).to_be_visible()
        captures["partial"] = capture(page, directory, "08-partial")

        page.locator("#show-inputs").click()
        choices["targets"] = invalid
        page.locator("#pick-targets").click()
        page.locator("#open-result").click()
        expect(page.locator("#notice")).to_be_visible(timeout=60000)
        assert page.locator("#room-host iframe").count() == 0
        expect(page.locator("#open-result")).to_be_enabled()
        captures["invalid"] = capture(page, directory, "09-invalid-result")
        assert not errors, errors
        assert not requests, requests
        return {
            "captures": captures,
            "calls": calls,
            "page_errors": errors,
            "network_requests": requests,
        }
    except Exception:
        page.screenshot(path=str(directory / "failure-debug.png"), full_page=False)
        raise
    finally:
        bridge._shutdown()
        app.request_close()
        app.closed()
        context.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    results = {
        "scope": "Chromium, real DesktopApplication/services, mocked native file dialogs",
        "native_windows_webview2": False,
        "human_listening": False,
        "display_scale": "DPR 1, browser zoom 100%",
    }
    with tempfile.TemporaryDirectory(prefix="phalanx-desktop-ui-") as temporary:
        directory = Path(temporary)
        database, selection = desktop_inputs(directory / "합성 입력")
        service = AllocationTargetsService(AllocationInputService(repository(database)))
        expected = service.calculate_bytes(selection.read_bytes()).to_json_bytes()
        targets = directory / "저장된 목표비중.json"
        targets.write_bytes(expected)
        long_data = json.loads(selection.read_bytes())
        for item in long_data["candidates"]:
            item["target"]["name"] = "합성 아주 긴 기업명 가나다라 첨단기술연구개발 주식회사"
        long_selection = directory / "긴 기업명 selection.json"
        long_selection.write_text(json.dumps(long_data, ensure_ascii=False), encoding="utf-8")
        invalid = directory / "잘못된 결과.json"
        invalid.write_bytes(b"{}")
        partial = directory / "일부 실패 결과.json"
        partial.write_bytes(gzip.decompress((FIXTURES / "partial.json.gz").read_bytes()))
        db_before = hashlib.sha256(database.read_bytes()).hexdigest()
        inputs = (database, selection, targets, expected, long_selection, invalid, partial)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            results["chromium_version"] = browser.version
            try:
                results["transport_recovery"] = verify_desktop_recovery(
                    browser, output, database, selection, expected, repository
                )
                for width, height in ((1440, 900), (1280, 720)):
                    results[f"{width}x{height}"] = run_viewport(
                        browser, output, width, height, inputs
                    )
            finally:
                browser.close()
        assert hashlib.sha256(database.read_bytes()).hexdigest() == db_before
        results["database_unchanged_sha256"] = db_before
    (output / "validation.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Chromium desktop integration passed: {output}")


if __name__ == "__main__":
    main()
