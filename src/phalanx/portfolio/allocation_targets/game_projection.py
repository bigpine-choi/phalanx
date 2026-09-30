"""Compact read-only display data from a saved allocation-targets artifact."""

from __future__ import annotations

from typing import cast

from phalanx.portfolio.formation_room.parser import parse_targets


def project_saved_targets(payload: bytes, *, source_name: str) -> dict[str, object]:
    """Validate display relationships without reopening market data or recomputing a model.

    All evidence values in the source remain file-reported. The result's SHA-256
    identifies the bytes read here; it is not a signature or a freshness check.
    """
    model = parse_targets(payload, source_name=source_name)
    scenarios: list[dict[str, object]] = []
    for scenario in model.scenarios:
        holdings = cast(list[dict[str, object]], scenario["holdings"])
        scenarios.append(
            {
                "kind": scenario["kind"],
                "label": scenario["label"],
                "status": scenario["status"],
                "failure": scenario["failure"],
                "holdings": [
                    {"code": holding["code"], "weight_display": holding["weight_display"]}
                    for holding in holdings
                ],
            }
        )
    provenance = model.replay_provenance
    replay: dict[str, object] | None = None
    if provenance is not None:
        replay = {
            key: provenance[key]
            for key in (
                "evidence_kind",
                "replay_file_sha256",
                "read_receipt_file_sha256",
                "read_completed_at",
                "decision_at",
                "replayed_at",
                "local_snapshot_read_before_decision_confirmed",
            )
        }
    return {
        "schema": "phalanx.game_research_allocation_projection.v1",
        "source_semantics": "saved_file_unverified",
        "source_name": model.source_name,
        "source_sha256": model.source_sha256,
        "status": model.status,
        "status_label": model.status_label,
        "selection_as_of": model.selection_as_of,
        "calculation_date": model.calculation_date,
        "reference_price_date": model.reference_price_date,
        "selected_codes": model.selected_codes,
        "succeeded_count": model.succeeded_count,
        "observation_count": model.return_observation_count,
        "scenarios": scenarios,
        "replay_provenance": replay,
    }
