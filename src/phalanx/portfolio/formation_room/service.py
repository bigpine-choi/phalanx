"""One bounded input read, display projection, and existing write-once atomic save."""

from pathlib import Path

from phalanx.portfolio.formation_room.model import FormationRoomModel, FormationRoomPresentation
from phalanx.portfolio.formation_room.parser import MAX_TARGETS_BYTES, parse_targets
from phalanx.portfolio.formation_room.rendering import render_formation_room
from phalanx.portfolio.formation_room.selection import MAX_SELECTION_BYTES
from phalanx.portfolio.private_json_storage import store_private_json_bytes


class FormationRoomReadError(Exception):
    """A saved result could not be read; no source details are exposed."""


class FormationRoomService:
    def generate(
        self,
        targets: Path,
        output: Path,
        *,
        selection: Path | None = None,
        presentation: FormationRoomPresentation | None = None,
    ) -> FormationRoomModel:
        """Generate HTML for every valid outcome, including failed calculations."""
        try:
            with targets.open("rb") as source:
                payload = source.read(MAX_TARGETS_BYTES + 1)
            selection_payload = None
            if selection is not None:
                with selection.open("rb") as source:
                    selection_payload = source.read(MAX_SELECTION_BYTES + 1)
        except OSError:
            raise FormationRoomReadError("목표비중 또는 선정 파일을 읽지 못했습니다.") from None
        model = parse_targets(
            payload,
            source_name=targets.name,
            selection_payload=selection_payload,
            presentation=presentation,
        )
        store_private_json_bytes(output, render_formation_room(model))
        return model
