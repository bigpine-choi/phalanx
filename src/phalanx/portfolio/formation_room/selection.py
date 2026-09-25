"""Names from an optionally supplied, byte-linked selection; no market lookups."""

from __future__ import annotations

import hashlib
import json
from typing import cast

from phalanx.domain.allocation_input import SelectionCompletion
from phalanx.portfolio.allocation_input.errors import AllocationInputError
from phalanx.portfolio.allocation_input.validation import parse_selection
from phalanx.portfolio.formation_room.errors import FormationRoomInputError

MAX_SELECTION_BYTES = 32 * 1024 * 1024


def _same(actual: object, expected: object) -> None:
    # JSON equality preserves bool/int distinctions that Python equality does not.
    if json.dumps(actual, sort_keys=True, allow_nan=False) != json.dumps(
        expected, sort_keys=True, allow_nan=False
    ):
        raise FormationRoomInputError()


def linked_names(payload: bytes, prepared: dict[str, object]) -> dict[str, str | None]:
    """Verify raw bytes before invoking the existing strict selection validator."""
    if type(payload) is not bytes or not 0 < len(payload) <= MAX_SELECTION_BYTES:
        raise FormationRoomInputError()
    if hashlib.sha256(payload).hexdigest() != prepared["selection_file_sha256"]:
        raise FormationRoomInputError()
    try:
        selection = parse_selection(payload)
    except AllocationInputError:
        raise FormationRoomInputError() from None
    _same(list(selection.selected_codes), prepared["selected_codes"])
    _same(selection.source.as_of.isoformat(), prepared["selection_as_of"])
    _same(
        selection.reference_price_date.isoformat() if selection.reference_price_date else None,
        prepared["reference_price_date"],
    )
    _same(selection.source.model_dump(mode="json"), prepared["selection_source"])
    _same(selection.policy.model_dump(mode="json"), prepared["selection_policy"])
    _same(
        SelectionCompletion.from_selection(selection).model_dump(mode="json"),
        prepared["selection_completion"],
    )
    _same(selection.source.history_job_id, prepared["history_job_id"])
    _same(selection.source.discovery_run_id, prepared["discovery_run_id"])
    _same(selection.price_basis, prepared["price_basis"])
    symbols = cast(list[dict[str, object]], prepared["symbols"])
    by_code = {cast(str, item["code"]): item for item in symbols}
    names: dict[str, str | None] = {}
    for candidate in selection.candidates:
        if candidate.status != "selected":
            continue
        code = candidate.target.short_code
        if code is None or code not in by_code:
            raise FormationRoomInputError()
        symbol = by_code[code]
        _same(candidate.ordinal, symbol["ordinal"])
        _same(candidate.source_price_sha256, symbol["verified_source_price_sha256"])
        _same(candidate.consumed_input_sha256, symbol["selection_consumed_input_sha256"])
        _same(candidate.eligible_observation_count, symbol["eligible_price_count"])
        _same(
            candidate.used_end.isoformat() if candidate.used_end else None,
            symbol["last_eligible_date"],
        )
        name = candidate.target.name
        names[code] = name if name is not None and name.strip() else None
    _same(sorted(names), sorted(selection.selected_codes))
    return names
