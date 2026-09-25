"""Capture matching before/after states in real Chromium for separate visual review.

This checks source/state equivalence and layout geometry. It does not decide
whether the design looks good; review the generated gallery and PNGs directly.
Install Playwright in a separate verification environment before running.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
from itertools import combinations
from pathlib import Path

from playwright.sync_api import sync_playwright

CASES = ("succeeded", "long-names", "no-selection", "partial", "settings")
VIEWPORTS = ((1440, 900), (1280, 720))
STYLE_SELECTORS = (
    "#room-title",
    ".subtitle",
    ".metrics",
    ".tab-label",
    ".tab-volatility",
    ".composition-help",
    ".holding-name",
    ".holding-code",
    ".holding-weight",
    "#detail-title",
    "#detail-code",
    ".detail-fields",
    ".detail-note",
    ".panel-foot",
    "#settings-dialog",
)


def sha256(value):
    return hashlib.sha256(value).hexdigest()


def measure(page):
    return page.evaluate(
        """selectors => {
          const rect = element => {
            const box = element.getBoundingClientRect();
            return {
              x: box.x, y: box.y, width: box.width, height: box.height,
              right: box.right, bottom: box.bottom
            };
          };
          const rows = selector => Array.from(document.querySelectorAll(selector))
            .filter(element => element.getClientRects().length)
            .map(element => ({code: element.dataset.code || null, ...rect(element)}));
          return {
            viewport: {width: innerWidth, height: innerHeight},
            document: {
              width: document.documentElement.scrollWidth,
              height: document.documentElement.scrollHeight,
              scrollX, scrollY
            },
            cards: rows('.holding-card'),
            tabs: rows('[role=tab]'),
            holdings: rows('.holdings-panel'),
            detail: rows('#holding-detail'),
            dialog: rows('#settings-dialog[open]'),
            styles: selectors.flatMap(selector =>
              Array.from(document.querySelectorAll(selector)).map(element => {
                const style = getComputedStyle(element);
                return {
                  selector, code: element.dataset.code || null,
                  visible: element.getClientRects().length > 0,
                  rect: rect(element), font_family: style.fontFamily,
                  font_size: style.fontSize, font_weight: style.fontWeight,
                  line_height: style.lineHeight, letter_spacing: style.letterSpacing,
                  color: style.color, background: style.backgroundColor,
                  border: style.borderColor, shadow: style.boxShadow
                };
              })
            )
          };
        }""",
        STYLE_SELECTORS,
    )


def overlaps(first, second):
    return (
        min(first["right"], second["right"]) - max(first["x"], second["x"]) > 1
        and min(first["bottom"], second["bottom"]) - max(first["y"], second["y"]) > 1
    )


def check_after_geometry(metrics, case):
    width = metrics["viewport"]["width"]
    height = metrics["viewport"]["height"]
    assert metrics["document"]["width"] <= width + 1, "Horizontal document overflow"
    assert metrics["document"]["scrollX"] == 0
    assert metrics["document"]["scrollY"] == 0
    cards = metrics["cards"]
    tabs = metrics["tabs"]
    assert len(cards) == 6 and len(tabs) == 4
    holdings, detail = metrics["holdings"][0], metrics["detail"][0]
    for box in [*cards, *tabs, holdings, detail, *metrics["dialog"]]:
        assert box["x"] >= -1 and box["right"] <= width + 1, "Panel/card outside viewport"
        assert box["width"] > 0 and box["height"] > 0
    assert not overlaps(holdings, detail), "Holdings and detail panels overlap"
    assert abs(holdings["y"] - detail["y"]) <= 2, "Panel top alignment differs"
    assert max(tab["y"] for tab in tabs) - min(tab["y"] for tab in tabs) <= 2
    assert max(tab["bottom"] for tab in tabs) - min(tab["bottom"] for tab in tabs) <= 2
    assert max(card["width"] for card in cards) - min(card["width"] for card in cards) <= 2
    for first, second in combinations(cards, 2):
        assert not overlaps(first, second), "Cards overlap"
    for card in cards:
        assert not overlaps(card, detail), "Card overlaps selected asset detail"
        assert holdings["x"] - 1 <= card["x"] and card["right"] <= holdings["right"] + 1
    rows = []
    for card in cards:
        if not rows or abs(rows[-1][0]["y"] - card["y"]) > 2:
            rows.append([card])
        else:
            rows[-1].append(card)
    assert len(rows) == 2 and all(len(row) == 3 for row in rows), "Expected desktop 3 x 2 cards"
    for row in rows:
        assert max(box["bottom"] for box in row) - min(box["bottom"] for box in row) <= 2
    for first, second in zip(rows[0], rows[1], strict=True):
        assert abs(first["x"] - second["x"]) <= 2, "Card columns are not aligned"
    if case in ("succeeded", "no-selection"):
        assert all(card["bottom"] <= height + 1 for card in cards), "Normal roster below fold"
        assert detail["bottom"] <= height + 1, "Normal asset detail below fold"
    if case == "settings":
        assert len(metrics["dialog"]) == 1
        dialog = metrics["dialog"][0]
        assert dialog["y"] >= 0 and dialog["bottom"] <= height + 1, "Settings dialog clipped"
    return {
        "horizontal_overflow": False,
        "panel_card_overlap": False,
        "desktop_card_grid": "3 x 2",
        "aligned_tabs_panels_card_rows": True,
        "ordinary_six_asset_above_fold": case in ("succeeded", "no-selection"),
        "long_name_vertical_scroll_allowed": case == "long-names",
        "aesthetic_verdict": "requires direct visual review",
    }


def capture(browser, directory, case, viewport, image_path):
    width, height = viewport
    context = browser.new_context(
        viewport={"width": width, "height": height},
        device_scale_factor=1,
        color_scheme="dark",
        reduced_motion="no-preference",
        offline=True,
    )
    requests, errors = [], []
    context.on("request", lambda request: requests.append(request.url))
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console", lambda message: errors.append(message.text) if message.type == "error" else None
    )
    source_case = "succeeded" if case == "settings" else case
    source_path = directory / source_case / "formation-room.html"
    page.goto(source_path.resolve().as_uri())
    page.wait_for_selector(".holding-card")
    page.evaluate("document.fonts.ready")
    raw_data = page.locator("#room-data").text_content()
    model = json.loads(raw_data)
    selected_code = model["selected_codes"][1]
    scenario_index = 1 if case == "partial" else 0
    page.locator(f"#scenario-tab-{scenario_index}").click()
    page.locator(f'.holding-card[data-code="{selected_code}"]').click()
    assert page.locator("#detail-code").text_content() == selected_code
    assert page.locator(f"#scenario-tab-{scenario_index}").get_attribute("aria-selected") == "true"
    assert (
        page.locator(f'.holding-card[data-code="{selected_code}"]').get_attribute("aria-pressed")
        == "true"
    )
    assert page.locator("#sound-state").inner_text() == "무음"
    assert page.locator("#sfx-volume").input_value() == "22"
    assert page.locator("#music-volume").input_value() == "16"
    assert not page.locator("#reduce-motion").is_checked()
    if case == "settings":
        page.locator("#settings-open").click()
        assert page.locator("#settings-dialog").is_visible()
    page.evaluate("window.scrollTo(0, 0)")
    page.mouse.move(1, 1)
    page.wait_for_timeout(250)
    state = {
        "scenario_index": scenario_index,
        "scenario_kind": model["scenarios"][scenario_index]["kind"],
        "selected_code": page.locator("#detail-code").text_content(),
        "selected_name": page.locator("#detail-title").text_content(),
        "selected_weight": page.locator("#detail-weight").text_content(),
        "selected_risk": page.locator("#detail-risk").text_content(),
        "volatility": page.locator("#volatility").text_content(),
        "card_codes": page.locator(".holding-card").evaluate_all(
            "cards => cards.map(card => card.dataset.code)"
        ),
        "card_names": page.locator(".holding-name").all_text_contents(),
        "card_weights": page.locator(".holding-weight").all_text_contents(),
        "composition_codes": page.locator(".composition-segment").evaluate_all(
            "segments => segments.map(segment => segment.dataset.code)"
        ),
        "settings_open": page.locator("#settings-dialog").is_visible(),
        "audio_state": page.locator("#sound-state").inner_text(),
        "sfx_volume": page.locator("#sfx-volume").input_value(),
        "music_volume": page.locator("#music-volume").input_value(),
        "reduce_motion": page.locator("#reduce-motion").is_checked(),
    }
    if case == "partial":
        assert state["selected_weight"] == "미산출" and state["selected_risk"] == "미산출"
        assert state["composition_codes"] == []
    metrics = measure(page)
    assert not [request for request in requests if not request.startswith("file://")], requests
    assert not errors, errors
    page.screenshot(path=str(image_path), full_page=False, animations="disabled")
    screenshot_bytes = image_path.read_bytes()
    context.close()
    return (
        {
            "source_html": str(source_path.resolve()),
            "source_html_sha256": sha256(source_path.read_bytes()),
            "json_island_sha256": sha256(raw_data.encode()),
            "canonical_json_sha256": sha256(
                json.dumps(model, sort_keys=True, ensure_ascii=False).encode()
            ),
            "state": state,
            "metrics": metrics,
            "screenshot": image_path.name,
            "screenshot_sha256": sha256(screenshot_bytes),
            "network_requests": [
                request for request in requests if not request.startswith("file://")
            ],
            "console_errors": errors,
        },
        raw_data,
        model,
    )


def gallery(pairs):
    policy = (
        "default-src 'none'; style-src 'unsafe-inline'; img-src 'self' file:; "
        "base-uri 'none'; form-action 'none'"
    )
    sections = []
    for pair in pairs:
        title = html.escape(f"{pair['case']} · {pair['width']} x {pair['height']}")
        columns = []
        for side, label in (("before", "수정 전"), ("after", "수정 후")):
            filename = html.escape(pair[side]["screenshot"], quote=True)
            columns.append(
                f'<figure><figcaption>{label}</figcaption><a href="{filename}">'
                f'<img src="{filename}" alt="{title} {label}" loading="lazy"></a></figure>'
            )
        sections.append(
            f"<section><h2>{title}</h2><div class='pair'>{''.join(columns)}</div></section>"
        )
    return (
        '<!doctype html><html lang="ko"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta http-equiv="Content-Security-Policy" content="{html.escape(policy, quote=True)}">'
        "<title>Formation Room · 동일 상태 시각 비교</title>"
        "<style>body{margin:28px;background:#101b27;color:#dfebf2;font-family:system-ui,sans-serif}"
        "h1{font-size:25px}h2{font-size:19px;margin-top:35px}p{max-width:1000px;line-height:1.7}"
        ".pair{display:grid;grid-template-columns:1fr 1fr;gap:18px}figure{margin:0;min-width:0}"
        "figcaption{padding:8px 0;color:#8fcec6}"
        "img{width:100%;height:auto;border:1px solid #3e566a}"
        "a{color:inherit}@media(max-width:850px){.pair{grid-template-columns:1fr}}</style>"
        "<h1>같은 데이터·선택 상태의 수정 전후 비교</h1>"
        "<p>두 화면은 JSON·시나리오·선택 종목·표시 수치·설정이 같습니다. "
        "이미지를 누르면 원본 크기로 볼 수 있습니다. 기하 검사와 기능 동등성은 자동 확인했지만 "
        "미적 품질은 자동 판정하지 않았습니다. 글자 가독성·위계·여백·색감·정렬을 직접 검토하세요. "
        "긴 이름은 세로 스크롤을 허용하며 캡처는 지정한 뷰포트의 첫 화면입니다.</p>"
        + "".join(sections)
        + "</html>"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before-directory", required=True, type=Path)
    parser.add_argument("--after-directory", required=True, type=Path)
    parser.add_argument("--artifacts", required=True, type=Path)
    args = parser.parse_args()
    args.artifacts.mkdir(parents=True, exist_ok=False)
    report = {
        "engine": "Chromium",
        "purpose": "identical-data actual-browser captures for separate visual review",
        "aesthetic_verdict": "not automatically assessed; inspect PNGs and gallery directly",
        "pairs": [],
    }
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        report["browser_version"] = browser.version
        for case in CASES:
            for width, height in VIEWPORTS:
                pair = {"case": case, "width": width, "height": height}
                raw, models = [], []
                for side, directory in (
                    ("before", args.before_directory),
                    ("after", args.after_directory),
                ):
                    filename = f"{case}-{width}x{height}-{side}.png"
                    captured, raw_json, model = capture(
                        browser, directory, case, (width, height), args.artifacts / filename
                    )
                    pair[side] = captured
                    raw.append(raw_json)
                    models.append(model)
                assert raw[0] == raw[1], f"JSON island bytes differ: {case}"
                assert models[0] == models[1], f"Source projection differs: {case}"
                assert pair["before"]["state"] == pair["after"]["state"], (
                    f"View states differ: {case}"
                )
                pair["identical_json_and_actual_state"] = True
                pair["after_geometry"] = check_after_geometry(pair["after"]["metrics"], case)
                report["pairs"].append(pair)
        browser.close()
    report["pair_count"] = len(report["pairs"])
    report["screenshot_count"] = report["pair_count"] * 2
    assert report["pair_count"] == 10 and report["screenshot_count"] == 20
    (args.artifacts / "comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.artifacts / "index.html").write_text(gallery(report["pairs"]), encoding="utf-8")
    print(
        json.dumps(
            {
                "pairs": report["pair_count"],
                "screenshots": report["screenshot_count"],
                "data_and_state": "identical",
                "after_geometry": "passed",
                "aesthetics": "requires direct visual review",
                "gallery": str(args.artifacts / "index.html"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
