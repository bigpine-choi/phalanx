"""Package-owned desktop shell and isolated, in-memory formation room rendering."""

from dataclasses import replace
from importlib.resources import files
from typing import Literal

from phalanx.portfolio.formation_room.model import FormationRoomModel
from phalanx.portfolio.formation_room.rendering import render_formation_room


def render_shell() -> str:
    assets = files("phalanx.desktop").joinpath("assets")
    template = assets.joinpath("shell.html").read_text(encoding="utf-8")
    # Substitute only trusted package assets, never filesystem paths or user JSON.
    return template.replace(
        "{{SHELL_CSS}}", assets.joinpath("shell.css").read_text(encoding="utf-8")
    ).replace("{{SHELL_JS}}", assets.joinpath("shell.js").read_text(encoding="utf-8"))


def render_result(model: FormationRoomModel, mode: Literal["saved", "calculated"]) -> str:
    limitations = list(model.limitations)
    offline_notice = (
        "저장된 결과를 조회하는 오프라인 화면 시제품입니다. 실시간 분석이나 재계산을 하지 않습니다."
    )
    desktop_notice = (
        "이번 작업에서 기존 Python 계산 서비스가 산출한 결과입니다. "
        "실시간 시세나 계좌를 조회하지 않습니다."
        if mode == "calculated"
        else "저장된 결과를 조회하고 있습니다. 이 결과를 열 때 재계산하지 않았습니다."
    )
    limitations = [desktop_notice if item == offline_notice else item for item in limitations]
    return render_formation_room(replace(model, limitations=limitations), desktop_mode=mode).decode(
        "utf-8"
    )
