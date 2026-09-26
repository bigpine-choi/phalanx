"""UI/controller transport regression run by tools/check_desktop_ui.py in Chromium.

Only transport failures and native dialogs are simulated. Every job reply comes
from DesktopApplication through NativeBridge, including duplicate rejections.
"""

from __future__ import annotations

import threading

from playwright.sync_api import expect

from phalanx.desktop.application import DesktopApplication
from phalanx.desktop.runtime import NativeBridge
from phalanx.desktop.storage import SettingsStore
from phalanx.desktop.view import render_shell

METHODS = ("bootstrap", "choose_file", "calculate", "job_status", "save_result")


def verify_desktop_recovery(browser, output, database, selection, expected, repository_factory):
    return {
        name: _verify_recovery_case(
            browser, output, database, selection, expected, repository_factory, lost_start
        )
        for lost_start, name in ((False, "failed-poll-requery"), (True, "lost-start-rejection"))
    }


def _verify_recovery_case(
    browser, output, database, selection, expected, repository_factory, lost_start
):
    case = "lost-start-rejection" if lost_start else "failed-poll-requery"
    directory = output / case
    directory.mkdir(parents=True, exist_ok=True)
    entered, release = threading.Event(), threading.Event()
    workers = []

    def repository(path):
        workers.append(path)
        entered.set()
        assert release.wait(60), "test did not release the calculation worker"
        return repository_factory(path)

    app = DesktopApplication(repository_factory=repository)
    saved_path = directory / "복구된 결과.json"
    bridge = NativeBridge(
        app,
        SettingsStore(directory / "settings"),
        lambda kind: {"selection": selection, "history": database}[kind],
        lambda: saved_path,
    )
    calls, starts, queries = [], [], []
    failures_remaining = 0 if lost_start else 2
    context = browser.new_context(viewport={"width": 1280, "height": 720}, locale="ko-KR")
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        for method in METHODS:

            def invoke(*args, method=method):
                nonlocal failures_remaining
                calls.append(method)
                response = getattr(bridge, method)(*args)
                if method == "calculate":
                    starts.append(response)
                    if lost_start and len(starts) == 1:
                        raise RuntimeError("Injected start-response transport failure")
                if method == "job_status":
                    queries.append((args, response))
                    if failures_remaining:
                        failures_remaining -= 1
                        raise RuntimeError("Injected job_status transport failure")
                return response

            page.expose_function("native_" + method, invoke)
        page.set_content(render_shell())
        page.evaluate(
            """methods => {
                window.pywebview = {api: Object.fromEntries(methods.map(name =>
                    [name, (...args) => window['native_' + name](...args)]))};
                window.dispatchEvent(new Event('pywebviewready'));
            }""",
            list(METHODS),
        )
        page.locator("#pick-calc-selection").click()
        page.locator("#pick-history").click()
        page.locator("#calculate").click()
        expect(page.locator("#notice")).to_be_visible()
        assert entered.wait(5)
        assert starts[0]["ok"] and starts[0]["generation"] == 1
        first_job = starts[0]["job_id"]
        assert len(workers) == 1

        if lost_start:
            # The server accepted generation 1 but its response was lost.
            # Retrying generation 2 must receive an identifiable rejection
            # rather than leaving the shell waiting on generation 1 forever.
            expect(page.locator("#calculate")).to_be_enabled()
            page.locator("#calculate").click()
            expect(page.locator("#notice")).to_contain_text("현재 작업이 끝난 후")
            expect(page.locator("#calculate")).to_be_enabled()
            expect(page.locator("#calculate-form")).to_have_attribute("aria-busy", "false")
            assert len(starts) == 2
            refused = starts[1]
            assert refused["ok"] is False and refused["state"] == "rejected"
            assert refused["generation"] == 2 and refused["job_id"] is None
            assert refused["active_job"] == {"job_id": first_job, "generation": 1}
            assert app.job_status(first_job, 1)["state"] == "running"
            assert len(workers) == 1
            page.screenshot(path=str(directory / "identifiable-rejection.png"))
            release.set()
            # Poll the real job via the transport without feeding it to the
            # shell: this must not display an older generation's result.
            page.evaluate(
                """async job => {
                    for (let attempt = 0; attempt < 1200; attempt++) {
                        const response = await window.pywebview.api.job_status(job, 1);
                        if (response.state === 'complete') return;
                        if (response.state === 'error') throw new Error(response.error);
                        await new Promise(resolve => setTimeout(resolve, 50));
                    }
                    throw new Error('Calculation did not finish');
                }""",
                first_job,
            )
            assert page.locator("#room-host iframe").count() == 0
            expect(page.locator("#save-result")).to_be_disabled()
            page.locator("#calculate").click()
        else:
            expect(page.locator("#retry-status")).to_be_enabled()
            expect(page.locator("#calculate")).to_be_disabled()
            expect(page.locator("#pick-history")).to_be_disabled()
            expect(page.locator("#calculate-form")).to_have_attribute("aria-busy", "true")
            assert app.job_status(first_job, 1)["state"] == "running"
            # Even scripted submit attempts cannot create a second worker.
            page.evaluate(
                """() => {const form = document.getElementById('calculate-form');
                form.dispatchEvent(new Event('submit', {cancelable:true}));
                form.dispatchEvent(new Event('submit', {cancelable:true}));} """
            )
            assert len(starts) == 1
            assert len(workers) == 1
            page.screenshot(path=str(directory / "status-query-failed.png"))
            page.locator("#retry-status").click()
            expect(page.locator("#retry-status")).to_be_enabled()
            assert len(queries) == 2
            assert all(args == (first_job, 1) for args, _ in queries)
            assert len(starts) == 1
            # A successful requery resumes normal polling of the same job.
            page.locator("#retry-status").click()
            expect(page.locator("#retry-status")).to_be_hidden()
            expect(page.locator("#calculate")).to_be_disabled()
            assert len(queries) >= 3
            release.set()

        expect(page.locator("#save-result")).to_be_enabled(timeout=60000)
        assert page.locator("#room-host iframe").count() == 1
        frame = page.frame_locator("#room-host iframe")
        expect(frame.locator("#overall-status")).to_have_text("네 시나리오 산출 완료")
        expect(page.locator("#retry-status")).to_be_hidden()
        if not lost_start:
            assert len(starts) == len(workers) == 1
            assert all(args == (first_job, 1) for args, _ in queries)
        else:
            assert len(starts) == 3 and len(workers) == 2
            assert starts[-1]["generation"] == 3
            assert starts[-1]["job_id"] != first_job
            assert app.job_status(first_job, 1)["stale"]
        page.locator("#save-result").click()
        expect(page.locator("#save-status")).to_contain_text("저장 완료")
        assert saved_path.read_bytes() == expected
        page.screenshot(path=str(directory / "recovered-and-saved.png"))
        assert not errors, errors
        outcome = {
            "calculate_requests": len(starts),
            "workers": len(workers),
            "queried_generations": sorted({args[1] for args, _ in queries}),
            "saved_exact_payload": True,
            "page_errors": errors,
        }
    except Exception:
        page.screenshot(path=str(directory / "failure-debug.png"))
        raise
    finally:
        release.set()
        bridge._shutdown()
        app.request_close()
        app.closed()
        context.close()
    return outcome
