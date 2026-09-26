"""Package-owned assets and an escaped, compact presentation-only JSON island."""

from __future__ import annotations

import json
import re
from importlib.resources import files
from typing import Literal

from phalanx.portfolio.formation_room.model import FormationRoomModel


def render_formation_room(
    model: FormationRoomModel, *, desktop_mode: Literal["saved", "calculated"] | None = None
) -> bytes:
    """Render one self-contained document; substitutions never process input twice."""
    if desktop_mode not in (None, "saved", "calculated"):
        raise ValueError("invalid desktop presentation mode")
    assets = files("phalanx.portfolio.formation_room").joinpath("assets")
    data = json.dumps(
        model.to_payload(), ensure_ascii=False, allow_nan=False, separators=(",", ":")
    )
    for character, escaped in (
        ("&", "\\u0026"),
        ("<", "\\u003c"),
        (">", "\\u003e"),
        ("\u2028", "\\u2028"),
        ("\u2029", "\\u2029"),
    ):
        data = data.replace(character, escaped)
    substitutions = {
        "ROOM_DATA": data,
        "ROOM_MODE": desktop_mode or "",
        "ROOM_CSS": assets.joinpath("room.css").read_text(encoding="utf-8"),
        "ROOM_AUDIO": assets.joinpath("audio.js").read_text(encoding="utf-8"),
        "ROOM_JS": assets.joinpath("room.js").read_text(encoding="utf-8"),
    }
    template = assets.joinpath("template.html").read_text(encoding="utf-8")
    for key in substitutions:
        if template.count("{{" + key + "}}") != 1:
            raise ValueError("formation room asset placeholder mismatch")
    return re.sub(
        r"\{\{(ROOM_DATA|ROOM_MODE|ROOM_CSS|ROOM_AUDIO|ROOM_JS)\}\}",
        lambda match: substitutions[match[1]],
        template,
    ).encode("utf-8")
