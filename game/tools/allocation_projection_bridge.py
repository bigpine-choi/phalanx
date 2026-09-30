"""One-shot, local-only projection of a saved research allocation file for Godot."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# Godot runs the bridge from a source checkout, which need not be pip-installed.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from phalanx.portfolio.allocation_targets.game_projection import project_saved_targets  # noqa: E402
from phalanx.portfolio.formation_room.errors import FormationRoomInputError  # noqa: E402
from phalanx.portfolio.formation_room.parser import MAX_TARGETS_BYTES  # noqa: E402

MAX_RESULT_BYTES = 512 * 1024


def _envelope(identifier: str, source: Path) -> dict[str, object]:
    result: dict[str, object] = {"request_id": identifier, "ok": False, "payload": {}}
    try:
        with source.open("rb") as file:
            payload = file.read(MAX_TARGETS_BYTES + 1)
    except OSError:
        result["error"] = "INPUT_UNAVAILABLE"
        return result
    try:
        result["payload"] = project_saved_targets(payload, source_name=source.name)
        result["ok"] = True
    except FormationRoomInputError:
        result["error"] = "INVALID_TARGETS"
    except Exception:
        result["error"] = "PROJECTION_FAILED"
    return result


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 3:
        return 2
    source, output = (Path(item) for item in args[:2])
    identifier = args[2]
    if re.fullmatch(r"[0-9]+-[0-9]+(?:-[0-9]+)?", identifier) is None:
        return 2
    try:
        if os.path.normcase(str(source.resolve())) == os.path.normcase(str(output.resolve())):
            return 2
    except OSError:
        return 2
    result = _envelope(identifier, source)
    encoded = json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(
        "utf-8"
    )
    if len(encoded) > MAX_RESULT_BYTES:
        encoded = json.dumps(
            {
                "request_id": identifier,
                "ok": False,
                "payload": {},
                "error": "PROJECTION_TOO_LARGE",
            },
            separators=(",", ":"),
        ).encode("utf-8")
    pending = output.with_suffix(output.suffix + ".pending")
    try:
        with pending.open("wb") as file:
            file.write(encoded)
        os.replace(pending, output)
    except OSError:
        try:
            pending.unlink(missing_ok=True)
        except OSError:
            pass
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
