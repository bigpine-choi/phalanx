"""Optional actual Chromium verification, separate from offline Python pytest.

Run with Playwright installed in a separate environment. No application server.
"""

from __future__ import annotations

import argparse
import json
from decimal import Decimal, localcontext
from pathlib import Path

from playwright.sync_api import sync_playwright

CASES = (
    "succeeded",
    "five-assets",
    "unavailable",
    "common-failure",
    "failed",
    "partial",
    "long-names",
    "no-selection",
    "missing-names",
    "duplicate-names",
    "script-names",
)


def percent(value):
    with localcontext() as context:
        context.prec = 50
        return f"{Decimal(str(value)) * 100:.2f}%"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--hostile-html", type=Path)
    parser.add_argument("--ordinary-html", type=Path)
    args = parser.parse_args()
    args.artifacts.mkdir(parents=True, exist_ok=True)
    report = {"engine": "Chromium", "cases": {}, "requests": [], "console_errors": []}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        report["browser_version"] = browser.version
        context = browser.new_context(viewport={"width": 1440, "height": 900}, offline=True)
        context.on("request", lambda request: report["requests"].append(request.url))
        for case in CASES:
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
            source = json.loads(
                (args.directory / case / "synthetic-allocation-targets.json").read_text()
            )
            selection = json.loads((args.directory / case / "selection.json").read_text())
            names = (
                {
                    candidate["target"]["short_code"]: candidate["target"]["name"]
                    for candidate in selection["candidates"]
                    if candidate["status"] == "selected"
                }
                if case != "no-selection"
                else {}
            )
            expected_names = [names.get(code) or "이름 미확인" for code in source["selected_codes"]]
            page.goto((args.directory / case / "formation-room.html").resolve().as_uri())
            page.wait_for_selector(".holding-card")
            assert page.locator("[role=tab]").count() == 4
            assert page.locator("#scenario-tab-0").get_attribute("aria-selected") == "true"
            assert page.locator("#sound-state").inner_text() == "무음"
            assert page.locator("#selected-count").inner_text() == str(
                len(source["selected_codes"])
            )
            assert page.locator("#success-count").inner_text() == str(source["succeeded_count"])
            assert page.locator(".holding-code").all_text_contents() == source["selected_codes"]
            assert page.locator(".holding-name").all_text_contents() == expected_names
            assert page.locator("#demo-badge").is_visible()
            assert page.locator("#demo-badge").inner_text() == "합성 데이터 데모"
            assert page.evaluate("window.__injected === undefined")
            assert page.locator("img").count() == 0
            for card, name in zip(page.locator(".holding-card").all(), expected_names, strict=True):
                assert name in card.get_attribute("aria-label")
            assert page.locator("#calculation-date").inner_text() == (
                source["calculation_date"] or "미산출"
            )
            page.locator(".holding-card").nth(1).click()
            selected_code = source["selected_codes"][1]
            for index, scenario in enumerate(source["scenarios"]):
                page.locator(f"#scenario-tab-{index}").click()
                assert page.locator("#detail-code").inner_text() == selected_code
                assert page.locator("#detail-title").text_content() == expected_names[1]
                tab_text = page.locator(f"#scenario-tab-{index}").inner_text()
                expected_volatility = (
                    percent(
                        scenario["target"]["diagnostics_after_reconciliation"][
                            "portfolio_volatility"
                        ]
                    )
                    if scenario["target"]
                    else "미산출"
                )
                assert expected_volatility in tab_text
                if scenario["target"]:
                    target = scenario["target"]
                    diagnostics = target["diagnostics_after_reconciliation"]
                    assert page.locator(".holding-weight").all_text_contents() == [
                        percent(weight) for weight in target["reconciled_decimal_weights"]
                    ]
                    assert page.locator("#detail-risk").inner_text() == percent(
                        diagnostics["relative_risk_contributions"][1]
                    )
                    assert page.locator("#volatility").inner_text() == percent(
                        diagnostics["portfolio_volatility"]
                    )
                    assert (
                        page.locator(".exact-weight code").all_text_contents()
                        == target["reconciled_decimal_weights"]
                    )
                    for name, row in zip(
                        expected_names, page.locator(".exact-weight").all(), strict=True
                    ):
                        assert name in row.text_content()
                    segments = page.locator(".composition-segment")
                    assert segments.count() == len(source["selected_codes"])
                    colors = []
                    for position, segment in enumerate(segments.all()):
                        assert (
                            segment.get_attribute("data-code") == source["selected_codes"][position]
                        )
                        weight = target["reconciled_decimal_weights"][position]
                        assert weight in segment.get_attribute("aria-label")
                        assert expected_names[position] in segment.get_attribute("aria-label")
                        width = segment.evaluate("e => parseFloat(e.style.width)")
                        # CSSOM serializes visual percentages with limited precision.
                        assert abs(width - float(Decimal(weight) * 100)) < 0.0001
                        colors.append(segment.evaluate("e => getComputedStyle(e).backgroundColor"))
                    if index == 0:
                        stable_colors = colors
                    else:
                        assert colors == stable_colors
                    segments.nth(2).click()
                    assert page.locator("#detail-code").inner_text() == source["selected_codes"][2]
                    assert (
                        page.locator(".holding-card").nth(2).get_attribute("aria-pressed") == "true"
                    )
                    segments.nth(2).focus()
                    page.keyboard.press("Home")
                    assert page.locator("#detail-code").inner_text() == source["selected_codes"][0]
                    page.keyboard.press("ArrowRight")
                    assert page.locator("#detail-code").inner_text() == selected_code
                    assert segments.nth(1).evaluate("e => e === document.activeElement")
                    page.locator(".holding-card").nth(1).click()
                    assert segments.nth(1).get_attribute("aria-pressed") == "true"
                else:
                    assert page.locator("#detail-weight").inner_text() == "미산출"
                    assert page.locator("#volatility").inner_text() == "미산출"
                    assert all(
                        text == "미산출"
                        for text in page.locator(".holding-weight").all_text_contents()
                    )
                    assert page.locator(".exact-weight").count() == 0
                    assert page.locator(".composition-segment").count() == 0
                    assert page.locator("#detail-risk").inner_text() == "미산출"
                    assert page.locator("#scenario-notice").is_visible()
                    if scenario["failure"]:
                        assert (
                            scenario["failure"]["message"]
                            in page.locator("#scenario-notice").inner_text()
                        )
            page.locator("#scenario-tab-0").focus()
            page.keyboard.press("ArrowRight")
            assert page.locator("#scenario-tab-1").get_attribute("aria-selected") == "true"
            assert page.locator("#scenario-tab-1").evaluate("e => e === document.activeElement")
            page.keyboard.press("End")
            assert page.locator("#scenario-tab-3").get_attribute("aria-selected") == "true"
            page.keyboard.press("Home")
            page.locator(".holding-card").nth(1).focus()
            page.keyboard.press("ArrowRight")
            assert page.locator("#detail-code").inner_text() == source["selected_codes"][2]
            page.keyboard.press("Home")
            assert page.locator("#detail-code").inner_text() == source["selected_codes"][0]
            page.locator("#evidence-panel summary").focus()
            page.keyboard.press("Enter")
            assert page.locator("#evidence-panel").get_attribute("open") is not None
            page.keyboard.press("Enter")
            page.locator("#scenario-tab-0").click()
            if case == "partial":
                page.locator("#scenario-tab-1").click()
            page.evaluate("window.scrollTo(0, 0)")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(args.artifacts / f"{case}-1440x900.png"), full_page=False)
            if case in ("long-names", "partial", "script-names"):
                page.screenshot(path=str(args.artifacts / f"{case}-full.png"), full_page=True)
            page.set_viewport_size({"width": 1280, "height": 720})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(args.artifacts / f"{case}-1280x720.png"), full_page=False)
            if case == "succeeded":
                page.locator("#settings-open").click()
                assert page.locator("#settings-dialog").is_visible()
                page.locator("#reduce-motion").check()
                assert page.locator("html").evaluate("e => e.classList.contains('reduced-motion')")
                page.locator("#sfx-volume").fill("12")
                page.locator("#music-volume").fill("9")
                saved = page.evaluate(
                    "JSON.parse(localStorage.getItem('phalanx.formation-room.preferences.v1'))"
                )
                assert set(saved) == {"sfxVolume", "musicVolume", "reduceMotion"}
                assert saved["sfxVolume"] == 12 and saved["musicVolume"] == 9
                page.screenshot(path=str(args.artifacts / "settings-1280x720.png"), full_page=False)
                page.keyboard.press("Escape")
                assert not page.locator("#settings-dialog").is_visible()
                assert page.locator("#settings-open").evaluate("e => e === document.activeElement")
                page.emulate_media(reduced_motion="reduce")
                assert (
                    page.locator(".holding-card").first.evaluate(
                        "e => getComputedStyle(e).transitionDuration"
                    )
                    == "0s"
                )
                page.reload()
                assert page.locator("#sound-state").inner_text() == "무음"
                report["preferences"] = (
                    "volumes/motion only; session starts silent; reduced motion verified"
                )
            report["cases"][case] = (
                "source names/weights, composition segments/colors/keyboard, "
                "tabs/volatility, preserved selection, evidence passed"
            )
            page.close()
        if args.hostile_html:
            hostile = context.new_page()
            hostile.on("pageerror", lambda error: report["console_errors"].append(str(error)))
            hostile.goto(args.hostile_html.resolve().as_uri())
            assert hostile.locator("#scenario-notice").is_visible()
            assert "<script>" in hostile.locator("#scenario-notice").inner_text()
            assert hostile.evaluate("window.__injected === undefined")
            assert hostile.locator("img").count() == 0
            hostile.locator("#evidence-panel summary").click()
            assert "<script>" in hostile.locator("#evidence-reasons").inner_text()
            hostile.close()
            report["hostile_input"] = "HTML/script source strings remained inert text in actual DOM"
        if args.ordinary_html:
            ordinary = context.new_page()
            ordinary.goto(args.ordinary_html.resolve().as_uri())
            assert not ordinary.locator("#demo-badge").is_visible()
            assert "synthetic" in ordinary.locator("#source-name").inner_text()
            assert all(
                name == "이름 미확인"
                for name in ordinary.locator(".holding-name").all_text_contents()
            )
            ordinary.close()
            report["ordinary_cli"] = "legacy CLI works; filename does not imply names or demo label"
        assert not [url for url in report["requests"] if not url.startswith("file://")]
        assert not report["console_errors"], report["console_errors"]
        context.close()
        browser.close()
    (args.artifacts / "browser-verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
