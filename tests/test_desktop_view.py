"""Presentation isolation and package assets; no financial calculations are duplicated."""

from __future__ import annotations

import json
import re

import pytest

from phalanx.desktop.view import render_result, render_shell
from phalanx.portfolio.formation_room.model import FormationRoomModel
from phalanx.portfolio.formation_room.rendering import render_formation_room


@pytest.fixture
def model():
    return FormationRoomModel(
        source_name="한글 이름 </script><img src=x>.json",
        source_sha256="a" * 64,
        status="input_unavailable",
        status_label="입력 사용 불가",
        selected_codes=[],
        selection_as_of="2026-01-02",
        calculation_date=None,
        reference_price_date=None,
        selected_count=0,
        return_observation_count=0,
        succeeded_count=0,
        used_start=None,
        used_end=None,
        symbols=[],
        scenarios=[],
        reasons=[],
        fingerprints=[],
        limitations=[
            "저장된 결과를 조회하는 오프라인 화면 시제품입니다. "
            "실시간 분석이나 재계산을 하지 않습니다.",
            "원본 연구 계산의 제약을 유지합니다.",
        ],
    )


def test_shell_has_package_code_only_and_sandbox_without_same_origin():
    shell = render_shell()
    assert "{{SHELL_" not in shell
    assert 'setAttribute("sandbox", "allow-scripts")' in shell
    assert "allow-same-origin" not in shell
    assert "pywebviewready" in shell
    assert ".srcdoc = response.html" in shell
    assert "http://" not in shell and "https://" not in shell
    assert "phalanx-desktop-dispose" in shell


@pytest.mark.parametrize("mode", ["saved", "calculated"])
def test_render_result_is_escaped_and_preserves_financial_payload(model, mode):
    source = model.to_payload()
    rendered = render_result(model, mode)
    assert f'data-desktop-mode="{mode}"' in rendered
    assert "<img src=x>" not in rendered
    island = re.search(r'<script id="room-data" type="application/json">(.*?)</script>', rendered)
    payload = json.loads(island.group(1))
    assert payload["limitations"][-1] == source["limitations"][-1]
    assert "실시간 분석이나 재계산을 하지 않습니다" not in payload["limitations"][0]
    assert {k: v for k, v in payload.items() if k != "limitations"} == {
        k: v for k, v in source.items() if k != "limitations"
    }
    assert model.to_payload() == source
    offline = render_formation_room(model).decode()
    assert 'data-desktop-mode=""' in offline
    assert "실시간 분석이나 재계산을 하지 않습니다" in offline
