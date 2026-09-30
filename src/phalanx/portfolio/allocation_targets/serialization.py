"""Reuse existing finite-float and exact-Decimal risk/ERC evidence projections."""

import json
from dataclasses import asdict

from phalanx.domain.allocation_targets import (
    ALLOCATION_TARGETS_SCHEMA,
    ALLOCATION_TARGETS_VERSION,
    AllocationTargetFailure,
    AllocationTargets,
)
from phalanx.portfolio.constrained_erc_trial_registry import (
    _erc_target_payload,
    _snapshot_payload,
    _solver_config_payload,
    safe_constrained_erc_failure_display,
)
from phalanx.portfolio.dynamic_risk_model import risk_model_config_payload


def _failure_payload(value: AllocationTargetFailure | None) -> dict[str, object] | None:
    if value is None:
        return None
    code, message = safe_constrained_erc_failure_display(value.failure)
    return {
        "stage": value.stage,
        "category": value.category,
        "code": code,
        "message": message,
        "as_of_date": value.failure.as_of_date.isoformat() if value.failure.as_of_date else None,
        "scenario_kind": value.failure.scenario_kind,
    }


def serialize_allocation_targets(result: AllocationTargets) -> bytes:
    payload = {
        "schema": ALLOCATION_TARGETS_SCHEMA,
        "schema_version": "1",
        "code_model_version": ALLOCATION_TARGETS_VERSION,
        "research_scope": "selected_universe_single_date_risky_asset_allocation",
        "account_execution_target": False,
        "recommended_scenario": None,
        "status": result.status,
        "complete": result.complete,
        "succeeded_count": result.succeeded_count,
        "prepared": result.prepared.to_json_object(),
        "selection_as_of": result.prepared.selection_as_of.isoformat(),
        "reference_price_date": result.prepared.reference_price_date.isoformat()
        if result.prepared.reference_price_date
        else None,
        "calculation_date": result.calculation_date.isoformat()
        if result.calculation_date
        else None,
        "selected_codes": result.prepared.selected_codes,
        "risk_config": risk_model_config_payload(result.risk_config),
        "solver_config": _solver_config_payload(result.solver_config),
        "solver_psd_config": risk_model_config_payload(result.risk_config),
        "library_provenance": asdict(result.library_provenance),
        "risk_config_fingerprint": result.risk_config_fingerprint,
        "solver_config_fingerprint": result.solver_config_fingerprint,
        "risk_input_fingerprint": result.risk_input_fingerprint,
        "risk_snapshot": _snapshot_payload(result.risk_snapshot) if result.risk_snapshot else None,
        "common_failure": _failure_payload(result.common_failure),
        "scenarios": [
            {
                "scenario_kind": item.scenario_kind,
                "status": item.status,
                "covariance_fingerprint": item.covariance_fingerprint,
                "target": _erc_target_payload(item.target) if item.target else None,
                "failure": _failure_payload(item.failure),
            }
            for item in result.scenarios
        ],
    }
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")
