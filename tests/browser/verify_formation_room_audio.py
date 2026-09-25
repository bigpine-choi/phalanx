"""Optional Chromium audio verification and deterministic synthetic WAV export.

Install Playwright in a separate environment. This script never claims that a
person heard the soundtrack. Visibility is an explicitly injected browser event.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import time
import wave
from pathlib import Path

from playwright.sync_api import sync_playwright

INSTRUMENT = r"""
(() => {
  const NativeContext = window.AudioContext || window.webkitAudioContext;
  window.__audioProbe = {contexts: 0, scheduled: [], actions: [], timers: new Set(), maxTimers: 0};
  window.__resumeQueue = [];
  window.__audioTestMode = "normal";
  if (NativeContext) {
    class ObservedContext extends NativeContext {
      constructor(...args) {
        super(...args);
        window.__audioProbe.contexts += 1;
      }
      resume() {
        if (window.__audioTestMode === "resume-reject") {
          return Promise.reject(new Error("Injected resume failure"));
        }
        if (window.__audioTestMode === "resume-pending") {
          return new Promise((resolve, reject) => {
            const request = {
              resolve: () => super.resume().then(resolve, reject),
              reject: () => reject(new Error("Injected delayed resume failure"))
            };
            window.__resumeQueue.push(request);
            window.__resolveResume = request.resolve;
          });
        }
        return super.resume();
      }
      createOscillator() {
        if (window.__audioTestMode === "oscillator-throw") {
          throw new Error("Injected oscillator creation failure");
        }
        const oscillator = super.createOscillator();
        const nativeSet = oscillator.frequency.setValueAtTime.bind(oscillator.frequency);
        oscillator.frequency.setValueAtTime = (frequency, time) => {
          window.__audioProbe.scheduled.push(frequency);
          return nativeSet(frequency, time);
        };
        if (window.__audioTestMode === "start-throw") {
          oscillator.start = () => { throw new Error("Injected oscillator start failure"); };
        }
        return oscillator;
      }
    }
    window.AudioContext = ObservedContext;
    window.webkitAudioContext = ObservedContext;
  }
  const nativeSetInterval = window.setInterval.bind(window);
  const nativeClearInterval = window.clearInterval.bind(window);
  window.setInterval = (...args) => {
    const id = nativeSetInterval(...args);
    window.__audioProbe.timers.add(id);
    window.__audioProbe.maxTimers = Math.max(
      window.__audioProbe.maxTimers, window.__audioProbe.timers.size
    );
    return id;
  };
  window.clearInterval = (id) => {
    window.__audioProbe.timers.delete(id);
    return nativeClearInterval(id);
  };
  Object.defineProperty(window, "PhalanxAudio", {
    configurable: true,
    set(library) {
      const wrapped = {
        ...library,
        createController(options) {
          const controller = library.createController(options);
          const effect = controller.effect;
          controller.effect = (kind) => {
            const card = document.querySelector('.holding-card[aria-pressed="true"]');
            const segment = document.querySelector('.composition-segment[aria-pressed="true"]');
            const detail = document.getElementById('holding-detail');
            const tab = document.querySelector('[role="tab"][aria-selected="true"]');
            window.__audioProbe.actions.push({
              kind, cardCode: card?.dataset.code, segmentCode: segment?.dataset.code,
              detailCode: detail.dataset.code, selectedTab: tab?.id,
              phase: detail.dataset.selectionPhase,
              colors: [card, segment, detail].map(
                (element) => element?.style.getPropertyValue('--asset-color')
              )
            });
            return effect(kind);
          };
          window.__roomAudio = controller;
          return controller;
        }
      };
      Object.defineProperty(window, "PhalanxAudio", {value: wrapped, configurable: true});
    }
  });
})();
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html", required=True, type=Path)
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    args.artifacts.mkdir(parents=True, exist_ok=True)
    uri = args.html.resolve().as_uri()
    html_bytes = args.html.read_bytes()
    audio_source = (
        Path(__file__).resolve().parents[2] / "src/phalanx/portfolio/formation_room/assets/audio.js"
    ).read_bytes()
    assert audio_source in html_bytes, "HTML must embed the current audio source bytes"
    report = {
        "engine": "Chromium",
        "html_sha256": hashlib.sha256(html_bytes).hexdigest(),
        "embedded_audio_sha256": hashlib.sha256(audio_source).hexdigest(),
        "checks": {},
        "requests": [],
        "console_errors": [],
        "human_listening": "not performed",
        "windows_browser": "not verified by this automated run",
        "real_os_tab_visibility": "not verified; visibility event injected explicitly",
    }
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not args.headed)
        report["browser_version"] = browser.version

        def new_page(extra=""):
            context = browser.new_context(viewport={"width": 1280, "height": 720}, offline=True)
            context.add_init_script(INSTRUMENT + "\n" + extra)
            context.on("request", lambda request: report["requests"].append(request.url))
            page = context.new_page()
            page.on("pageerror", lambda error: report["console_errors"].append(str(error)))
            page.on(
                "console",
                lambda message: (
                    report["console_errors"].append(message.text)
                    if message.type == "error"
                    else None
                ),
            )
            page.goto(uri)
            page.wait_for_selector("#scenario-tab-0")
            assert page.evaluate("window.__audioProbe.contexts") == 0
            assert not page.evaluate("window.__roomAudio.getState().enabled")
            page.locator("#settings-open").click()
            return context, page

        def wait_until(page, expression):
            # Poll through CDP evaluation: the page intentionally disallows eval,
            # including Playwright's delayed in-page string predicate evaluation.
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                if page.evaluate(expression):
                    return
                page.wait_for_timeout(25)
            raise AssertionError(f"Audio condition did not become true: {expression}")

        def assert_stopped(page):
            wait_until(
                page,
                """() => {
                    const s = window.__roomAudio.getState();
                    return !s.starting && !s.musicPlaying && !s.scheduledTimer &&
                        s.activeMusicVoices === 0 && s.activeEffectVoices === 0 &&
                        window.__audioProbe.timers.size === 0;
                }""",
            )

        context, page = new_page()
        assert page.locator("#sound-state").inner_text() == "무음"
        page.locator("#audio-enable").click()
        wait_until(page, "window.__roomAudio.getState().enabled")
        assert page.evaluate("window.__audioProbe.contexts") == 1
        assert not page.evaluate("window.__roomAudio.getState().musicPlaying")
        report["checks"]["explicit_enable_without_music"] = "passed"
        page.wait_for_timeout(500)
        effects = []
        for _ in range(6):
            page.evaluate("window.__audioProbe.scheduled = []")
            page.locator("#audio-preview").click()
            page.wait_for_timeout(500)
            effects.append(page.evaluate("window.__audioProbe.scheduled"))
        assert all(effects)
        assert len({tuple(effect) for effect in effects}) == 6
        report["checks"]["six_distinct_preview_effects"] = effects

        page.locator("#settings-done").click()
        page.wait_for_timeout(150)
        page.evaluate("window.__audioProbe.actions = []; window.__audioProbe.scheduled = []")
        selected_code = page.locator(".holding-card").nth(1).get_attribute("data-code")
        page.locator(".holding-card").nth(1).click()
        action = page.evaluate("window.__audioProbe.actions.at(-1)")
        assert action["kind"] == "select"
        assert action["cardCode"] == action["segmentCode"] == action["detailCode"] == selected_code
        assert len(set(action["colors"])) == 1 and action["colors"][0]
        assert page.evaluate("window.__audioProbe.scheduled.length") > 0
        previous_phase = action["phase"]
        page.wait_for_timeout(150)
        page.locator(".holding-card").nth(1).click()
        page.locator(".composition-segment").nth(1).click()
        page.locator("#scenario-tab-0").click()
        assert page.evaluate("window.__audioProbe.actions.length") == 1
        assert (
            page.locator("#holding-detail").get_attribute("data-selection-phase") == previous_phase
        )
        page.locator("#scenario-tab-2").focus()
        page.keyboard.press("Home")
        assert page.locator("#scenario-tab-0").evaluate("e => e === document.activeElement")
        assert page.evaluate("window.__audioProbe.actions.length") == 1
        assert (
            page.locator("#holding-detail").get_attribute("data-selection-phase") == previous_phase
        )
        selected_code = page.locator(".composition-segment").nth(2).get_attribute("data-code")
        page.locator(".composition-segment").nth(2).click()
        action = page.evaluate("window.__audioProbe.actions.at(-1)")
        assert action["kind"] == "select"
        assert action["cardCode"] == action["segmentCode"] == action["detailCode"] == selected_code
        assert len(set(action["colors"])) == 1 and action["phase"] != previous_phase
        page.wait_for_timeout(150)
        page.locator("#scenario-tab-1").click()
        action = page.evaluate("window.__audioProbe.actions.at(-1)")
        assert action["kind"] == "tab" and action["selectedTab"] == "scenario-tab-1"
        assert action["cardCode"] == action["segmentCode"] == action["detailCode"] == selected_code
        assert len(set(action["colors"])) == 1
        report["interaction_synchrony"] = (
            "actual card/composition/tab clicks update selected code/color before SFX call; "
            "current code/tab clicks preserve phase and make no SFX call; "
            "keyboard still focuses an already-selected destination"
        )
        page.locator("#settings-open").click()
        page.locator("#music-start").click()
        wait_until(page, "window.__roomAudio.getState().musicPlaying")
        page.wait_for_timeout(1100)
        running = page.evaluate("window.__roomAudio.getState()")
        assert running["activeMusicVoices"] > 0
        assert running["scheduledTimer"]
        page.locator("#music-stop").click()
        assert_stopped(page)
        report["checks"]["explicit_music_start_stop"] = "passed"
        cycle_counts = []
        for _ in range(8):
            page.evaluate(
                "Promise.all(Array.from({length: 8}, () => window.__roomAudio.startMusic()))"
            )
            page.wait_for_timeout(110)
            state = page.evaluate("window.__roomAudio.getState()")
            assert state["musicPlaying"] and state["activeMusicVoices"] <= 12
            assert page.evaluate("window.__audioProbe.timers.size") == 1
            cycle_counts.append(state["activeMusicVoices"])
            page.evaluate("window.__roomAudio.stopMusic()")
            assert_stopped(page)
        assert page.evaluate("window.__audioProbe.maxTimers") == 1
        report["checks"]["repeated_start_stop_no_accumulation"] = {
            "cycles": 8,
            "simultaneous_starts_per_cycle": 8,
            "active_music_nodes": cycle_counts,
            "maximum_scheduler_timers": 1,
        }
        page.evaluate("Array.from({length: 100}, () => window.__roomAudio.effect('confirm'))")
        assert page.evaluate("window.__roomAudio.getState().activeEffectVoices") <= 12
        page.locator("#audio-mute").click()
        assert_stopped(page)
        assert not page.evaluate("window.__roomAudio.getState().enabled")
        report["checks"]["rapid_clicks_and_master_mute"] = "passed"
        for slider, value in [("sfx-volume", "13"), ("music-volume", "9")]:
            page.locator(f"#{slider}").fill(value)
            assert page.locator(f"#{slider}-label").inner_text() == f"{value}%"
        saved = page.evaluate(
            "JSON.parse(localStorage.getItem('phalanx.formation-room.preferences.v1'))"
        )
        assert saved == {"sfxVolume": 13, "musicVolume": 9, "reduceMotion": False}
        page.evaluate(
            """localStorage.setItem('phalanx.formation-room.preferences.v1',
                JSON.stringify({sfxVolume:13,musicVolume:9,reduceMotion:false,
                    enabled:true,musicPlaying:true}))"""
        )
        page.reload()
        page.wait_for_selector("#scenario-tab-0")
        assert page.evaluate("window.__audioProbe.contexts") == 0
        assert not page.evaluate("window.__roomAudio.getState().enabled")
        assert page.locator("#sound-state").inner_text() == "무음"
        report["checks"]["volumes_persist_reload_silent_even_saved_on"] = "passed"
        page.locator("#settings-open").click()
        page.locator("#music-start").click()
        wait_until(page, "window.__roomAudio.getState().musicPlaying")
        page.evaluate(
            """() => {
                Object.defineProperty(document, 'hidden', {value:true,configurable:true});
                document.dispatchEvent(new Event('visibilitychange'));
            }"""
        )
        assert_stopped(page)
        assert not page.evaluate("window.__roomAudio.getState().enabled")
        page.evaluate(
            """() => {
                Object.defineProperty(document, 'hidden', {value:false,configurable:true});
                document.dispatchEvent(new Event('visibilitychange'));
            }"""
        )
        page.wait_for_timeout(150)
        assert not page.evaluate("window.__roomAudio.getState().enabled")
        page.locator("#music-start").click()
        wait_until(page, "window.__roomAudio.getState().musicPlaying")
        page.evaluate("window.dispatchEvent(new PageTransitionEvent('pagehide', {persisted:true}))")
        assert_stopped(page)
        page.evaluate("window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted:true}))")
        assert not page.evaluate("window.__roomAudio.getState().enabled")
        page.locator("#music-start").click()
        wait_until(page, "window.__roomAudio.getState().musicPlaying")
        page.locator("#audio-mute").click()
        assert_stopped(page)
        report["checks"]["injected_visibility_bfcache_and_manual_resume"] = "passed"

        wav_path = args.artifacts / "formation-room-synthetic-ambient-preview.wav"
        with wave.open(str(wav_path), "wb") as wav:
            wav.setnchannels(2)
            wav.setsampwidth(2)
            wav.setframerate(44100)
            page.expose_function(
                "__writeWaveChunk",
                lambda encoded: wav.writeframesraw(base64.b64decode(encoded)),
            )
            metrics = page.evaluate(
                """async () => {
                    const buffer = await window.PhalanxAudio.renderPreview(32);
                    const channels = [buffer.getChannelData(0), buffer.getChannelData(1)];
                    let peak = 0, squareSum = 0;
                    const segmentSquares = Array(8).fill(0);
                    const segmentCounts = Array(8).fill(0);
                    for (let start=0; start<buffer.length; start+=8192) {
                        const end = Math.min(buffer.length, start+8192);
                        const bytes = new Uint8Array((end-start)*4);
                        const view = new DataView(bytes.buffer);
                        for (let i=start; i<end; i++) {
                            const segment = Math.min(7, Math.floor(i/buffer.sampleRate/4));
                            for (let channel=0; channel<2; channel++) {
                                const value = channels[channel][i];
                                if (!Number.isFinite(value)) throw new Error('Nonfinite audio');
                                peak = Math.max(peak, Math.abs(value));
                                squareSum += value*value;
                                segmentSquares[segment] += value*value;
                                segmentCounts[segment]++;
                                // Only the export gets a 150ms tail fade to avoid WAV truncation.
                                const fade = Math.min(1, (buffer.length-i)/(buffer.sampleRate*.15));
                                view.setInt16((i-start)*4+channel*2,
                                    Math.round(Math.max(-1,Math.min(1,value*fade))*32767),true);
                            }
                        }
                        await window.__writeWaveChunk(btoa(String.fromCharCode(...bytes)));
                    }
                    return {seconds:32,sample_rate:buffer.sampleRate,channels:2,
                        frames:buffer.length,peak,rms:Math.sqrt(squareSum/(buffer.length*2)),
                        rms_by_four_seconds:segmentSquares.map((v,i)=>Math.sqrt(v/segmentCounts[i])),
                        export_tail_fade_seconds:.15};
                }"""
            )
        assert 0.001 < metrics["peak"] < 0.2
        assert metrics["rms"] > 0.0001
        assert all(value > 0.0001 for value in metrics["rms_by_four_seconds"])
        assert max(metrics["rms_by_four_seconds"]) > min(metrics["rms_by_four_seconds"]) * 1.05
        metrics["file"] = wav_path.name
        metrics["method"] = "actual Chromium OfflineAudioContext; no audible listening claim"
        report["offline_waveform"] = metrics
        context.close()

        failure_cases = {}
        for mode in ["resume-reject", "oscillator-throw", "start-throw"]:
            context, page = new_page()
            page.evaluate("mode => { window.__audioTestMode = mode; }", mode)
            page.locator("#audio-preview").click()
            wait_until(page, "document.getElementById('audio-notice').textContent.length > 0")
            assert_stopped(page)
            assert not page.evaluate("window.__roomAudio.getState().enabled")
            assert "못" in page.locator("#audio-notice").inner_text()
            page.locator("#settings-done").click()
            page.locator("#scenario-tab-1").click()
            assert page.locator("#scenario-tab-1").get_attribute("aria-selected") == "true"
            failure_cases[mode] = "stopped, safe notice, navigation retained"
            context.close()
        report["checks"]["injected_backend_failures"] = failure_cases

        cancellations = {}
        for cancel in ["mute", "stopMusic"]:
            context, page = new_page()
            page.evaluate("window.__audioTestMode = 'resume-pending'")
            page.evaluate("() => { window.__pendingStart = window.__roomAudio.startMusic(); }")
            wait_until(page, "typeof window.__resolveResume === 'function'")
            page.evaluate("method => window.__roomAudio[method]()", cancel)
            page.evaluate("window.__resolveResume()")
            page.evaluate("window.__pendingStart")
            assert_stopped(page)
            assert not page.evaluate("window.__roomAudio.getState().enabled")
            cancellations[cancel] = "pending resume cancelled"
            context.close()
        ui_cancellations = {}
        for button in ["audio-enable", "music-start"]:
            context, page = new_page()
            page.evaluate("window.__audioTestMode = 'resume-pending'")
            page.locator(f"#{button}").click()
            wait_until(page, "window.__roomAudio.getState().starting")
            assert "대기" in page.locator("#audio-status").inner_text()
            assert page.locator("#audio-mute").is_enabled()
            assert not page.evaluate("window.__roomAudio.getState().enabled")
            page.locator("#audio-mute").click()
            assert_stopped(page)
            assert not page.evaluate("window.__roomAudio.getState().enabled")
            page.evaluate("window.__resolveResume()")
            assert_stopped(page)
            assert not page.evaluate("window.__roomAudio.getState().enabled")
            assert page.locator("#audio-enable").is_enabled()
            ui_cancellations[button] = (
                "actual start/cancel button clicks; waiting state visible and cancel enabled; "
                "late resolution leaves enabled/music/voices/timers stopped"
            )
            context.close()
        cancellations["actual_ui_buttons"] = ui_cancellations

        restart_races = []
        for settlement in ["resolve", "reject"]:
            for old_first in [True, False]:
                context, page = new_page()
                page.evaluate("window.__audioTestMode = 'resume-pending'")
                page.locator("#music-start").click()
                wait_until(page, "window.__resumeQueue.length === 1")
                page.locator("#audio-mute").click()
                assert_stopped(page)
                page.locator("#music-start").click()
                wait_until(page, "window.__resumeQueue.length === 2")
                assert page.evaluate("window.__roomAudio.getState().starting")
                assert "대기" in page.locator("#audio-status").inner_text()
                if old_first:
                    page.evaluate("method => window.__resumeQueue[0][method]()", settlement)
                    page.wait_for_timeout(100)
                    pending = page.evaluate("window.__roomAudio.getState()")
                    assert pending["starting"] and not pending["enabled"]
                    assert not pending["musicPlaying"] and not pending["scheduledTimer"]
                    assert pending["activeMusicVoices"] == pending["activeEffectVoices"] == 0
                    assert page.locator("#audio-mute").is_enabled()
                page.evaluate("window.__resumeQueue[1].resolve()")
                wait_until(page, "window.__roomAudio.getState().musicPlaying")
                if not old_first:
                    page.evaluate("method => window.__resumeQueue[0][method]()", settlement)
                    page.wait_for_timeout(100)
                current = page.evaluate("window.__roomAudio.getState()")
                assert current["enabled"] and current["musicPlaying"] and not current["starting"]
                assert page.evaluate("window.__audioProbe.timers.size") == 1
                assert page.locator("#audio-notice").inner_text() == ""
                page.locator("#audio-mute").click()
                assert_stopped(page)
                assert not page.evaluate("window.__roomAudio.getState().enabled")
                restart_races.append(
                    {
                        "stale_settlement": settlement,
                        "stale_settled_before_fresh_resume": old_first,
                        "result": "fresh pending/playback retained; final UI mute clears all",
                    }
                )
                context.close()
        cancellations["cancel_restart_stale_settlement"] = restart_races
        report["checks"]["pending_resume_cancellation"] = cancellations

        context, page = new_page(
            "window.AudioContext = undefined; window.webkitAudioContext = undefined;"
        )
        assert page.locator("#audio-enable").is_disabled()
        assert page.locator("#audio-preview").is_disabled()
        assert "지원하지" in page.locator("#audio-status").inner_text()
        page.locator("#settings-done").click()
        page.locator("#scenario-tab-2").click()
        assert page.locator("#scenario-tab-2").get_attribute("aria-selected") == "true"
        report["checks"]["unsupported_audio_navigation_retained"] = "passed"
        context.close()

        for access in ["read", "write"]:
            method = "getItem" if access == "read" else "setItem"
            context, page = new_page(
                f"Storage.prototype.{method} = () => {{"
                "throw new DOMException('Injected blocked storage', 'SecurityError'); };"
            )
            assert "세션 설정" in page.locator("#settings-storage").inner_text()
            page.locator("#audio-preview").click()
            wait_until(page, "window.__roomAudio.getState().enabled")
            page.locator("#reduce-motion").check()
            assert page.locator("html").get_attribute("class") == "reduced-motion"
            page.locator("#audio-mute").click()
            assert_stopped(page)
            context.close()
        report["checks"]["blocked_storage_read_and_write_session_fallback"] = "passed"
        browser.close()
    assert not report["console_errors"], report["console_errors"]
    assert all(url.startswith("file:") for url in report["requests"]), report["requests"]
    report["checks"]["external_requests"] = 0
    report["checks"]["console_errors"] = 0
    report_path = args.artifacts / "audio-verification.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {"report": str(report_path), "checks": len(report["checks"]), "wav": str(wav_path)},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
