from __future__ import annotations

import json
import stat
from dataclasses import replace
from decimal import Decimal

import pytest
from test_volatility_overlay_research import _conduct, _histories

from phalanx.domain import (
    VOLATILITY_OVERLAY_SCHEMA,
    VOLATILITY_OVERLAY_SCHEMA_VERSION,
    VolatilityOverlayFailure,
    VolatilityOverlayResearchTrial,
)
from phalanx.portfolio.allocation_backtest import (
    annual_cash_yield_to_daily_growth_factor,
)
from phalanx.portfolio.errors import (
    VolatilityOverlayTrialAlreadyExistsError,
    VolatilityOverlayTrialSerializationError,
)
from phalanx.portfolio.volatility_overlay_trial_registry import (
    JsonVolatilityOverlayTrialRegistry,
    safe_volatility_overlay_failure_display,
    serialize_volatility_overlay_trial,
)


@pytest.fixture
def trial() -> VolatilityOverlayResearchTrial:
    return _conduct(
        histories=_histories(23),
        target=Decimal("0.001"),
        cash_yield=Decimal("0.03"),
        trial_id="registry-overlay",
    )


def test_versioned_serialization_round_trip_preserves_exact_decimal_contract(
    trial: VolatilityOverlayResearchTrial,
) -> None:
    serialized = serialize_volatility_overlay_trial(trial)
    payload = json.loads(serialized.decode())

    assert serialized == serialize_volatility_overlay_trial(trial)
    assert json.loads(json.dumps(payload, ensure_ascii=False)) == payload
    assert payload["schema"] == VOLATILITY_OVERLAY_SCHEMA
    assert payload["schema_version"] == VOLATILITY_OVERLAY_SCHEMA_VERSION
    assert payload["source_constrained_erc_trial"]["schema"] == (
        "phalanx.constrained_erc_research_trial.v1"
    )
    overlay_config = payload["config"]["overlay"]
    assert overlay_config["target_annual_volatility"] == "0.001"
    assert overlay_config["annual_cash_yield"] == "0.03"
    assert overlay_config["daily_cash_growth_factor"] == str(
        annual_cash_yield_to_daily_growth_factor(Decimal("0.03"), 252)
    )
    contract = payload["config"]["overlay_contract"]
    assert contract["risk_free_rate_input"] is False
    assert contract["sharpe_hurdle_input"] is False
    assert contract["cash_yield_is_risk_free_rate"] is False
    assert contract["leverage"] is False
    assert contract["short"] is False
    assert contract["fallback_policy"] is None
    assert contract["automatic_winner_selection"] is False

    for outcome in payload["policy_outcomes"]:
        assert outcome["status"] == "succeeded"
        for target in outcome["overlay_targets"]:
            exact_weights = tuple(Decimal(value) for value in target["target_weights"])
            cash = Decimal(target["cash_residual"])
            assert sum(exact_weights, Decimal(0)) + cash == Decimal(1)
            assert all(isinstance(value, str) for value in target["target_weights"])
            assert isinstance(target["forecast_annual_volatility"], str)
            assert isinstance(target["target_annual_volatility"], str)
            assert isinstance(target["scalar"], str)
            assert isinstance(target["cash_residual"], str)
    assert payload["provenance"]["python_version"]
    assert payload["provenance"]["numpy_version"]
    assert payload["provenance"]["scikit_learn_version"]


def test_registry_is_private_atomic_and_no_overwrite(
    tmp_path,
    trial: VolatilityOverlayResearchTrial,
) -> None:
    output_dir = tmp_path / "overlay-trials"
    registry = JsonVolatilityOverlayTrialRegistry(output_dir)

    saved = registry.save(trial)

    assert saved.exists()
    assert stat.S_IMODE(saved.stat().st_mode) == 0o600
    assert stat.S_IMODE(output_dir.stat().st_mode) == 0o700
    assert not tuple(output_dir.glob("*.tmp"))
    with pytest.raises(VolatilityOverlayTrialAlreadyExistsError):
        registry.save(trial)
    assert saved.read_bytes() == serialize_volatility_overlay_trial(trial)


def test_fingerprint_tampering_is_rejected_before_storage(
    trial: VolatilityOverlayResearchTrial,
) -> None:
    tampered = replace(trial, config_fingerprint="0" * 64)

    with pytest.raises(VolatilityOverlayTrialSerializationError):
        serialize_volatility_overlay_trial(tampered)


def test_unknown_failure_text_is_never_returned_by_safe_projection() -> None:
    secret = "APP_SECRET=never-serialize-this"
    failure = VolatilityOverlayFailure(
        code="unknown_overlay_failure",
        message=secret,
    )

    code, message = safe_volatility_overlay_failure_display(failure)

    assert code == "volatility_overlay_calculation_error"
    assert message == "volatility overlay 정책 계산을 완료하지 못했습니다."
    assert secret not in message
