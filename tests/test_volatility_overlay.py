from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from decimal import ROUND_DOWN, ROUND_UP, Decimal, getcontext, setcontext

import pytest
from pydantic import ValidationError

from phalanx.domain import (
    SCENARIO_KIND_ORDER,
    VOLATILITY_OVERLAY_CODE_MODEL_VERSION,
    VOLATILITY_OVERLAY_RESEARCH_SCOPE,
    VOLATILITY_OVERLAY_SCENARIO_IDS,
    VOLATILITY_OVERLAY_SCENARIO_POLICY_IDS,
    VOLATILITY_OVERLAY_SCHEMA,
    VOLATILITY_OVERLAY_SCHEMA_VERSION,
    ConstrainedErcKktDiagnostics,
    CovarianceScenarioKind,
    VolatilityOverlayConfig,
    VolatilityOverlayTarget,
    overlay_policy_id,
)
from phalanx.portfolio.constrained_erc import solve_constrained_erc
from phalanx.portfolio.errors import InvalidVolatilityOverlayDomainError
from phalanx.portfolio.volatility_overlay import (
    apply_volatility_overlay,
    calculate_volatility_overlay,
)

_CODES = tuple(f"{index:06d}" for index in range(1, 7))
_AS_OF = date(2026, 8, 28)


def _identity(size: int) -> tuple[tuple[float, ...], ...]:
    return tuple(
        tuple(1.0 if row == column else 0.0 for column in range(size)) for row in range(size)
    )


def _source(
    kind: CovarianceScenarioKind = CovarianceScenarioKind.LONG_RUN_LEDOIT_WOLF,
):
    return solve_constrained_erc(
        _identity(6),
        _CODES,
        scenario_kind=kind,
        as_of_date=_AS_OF,
    )


def _config(
    target: Decimal = Decimal("0.10"),
    cash_yield: Decimal = Decimal("0"),
) -> VolatilityOverlayConfig:
    return VolatilityOverlayConfig(
        target_annual_volatility=target,
        annual_cash_yield=cash_yield,
    )


def test_version_scenario_and_policy_contracts_are_fixed() -> None:
    assert VOLATILITY_OVERLAY_SCHEMA == "phalanx.volatility_overlay_research_trial.v1"
    assert VOLATILITY_OVERLAY_SCHEMA_VERSION == "1"
    assert VOLATILITY_OVERLAY_CODE_MODEL_VERSION == "volatility-overlay-research-v1"
    assert VOLATILITY_OVERLAY_RESEARCH_SCOPE == (
        "current-universe conditional allocation-only research overlay"
    )
    assert tuple(kind.value for kind in SCENARIO_KIND_ORDER) == VOLATILITY_OVERLAY_SCENARIO_IDS
    assert tuple(overlay_policy_id(kind) for kind in SCENARIO_KIND_ORDER) == (
        VOLATILITY_OVERLAY_SCENARIO_POLICY_IDS
    )
    assert len(set(VOLATILITY_OVERLAY_SCENARIO_POLICY_IDS)) == 4


def test_decimal_only_overlay_preserves_risky_sleeve_and_exact_accounting() -> None:
    source = _source()

    result = calculate_volatility_overlay(source, Decimal("0.20"), _config())

    assert isinstance(result, VolatilityOverlayTarget)
    assert result.source_policy_id == "constrained_erc_long_run_ledoit_wolf"
    assert result.policy_id == "volatility_overlay_long_run_ledoit_wolf"
    assert result.source_covariance_fingerprint == source.covariance_fingerprint
    assert result.source_solver_config_fingerprint == source.solver_config_fingerprint
    assert result.forecast_annual_volatility == Decimal("0.20")
    assert result.target_annual_volatility == Decimal("0.10")
    assert result.scalar == result.volatility_scalar == Decimal("0.5")
    assert result.risky_sleeve_weights == source.reconciled_weights
    assert result.target_weights == tuple(
        weight * Decimal("0.5") for weight in source.reconciled_weights
    )
    assert result.target_equity_weight == Decimal("0.5")
    assert result.cash_residual == Decimal("0.5")
    assert sum(result.risky_sleeve_weights, Decimal(0)) == Decimal(1)
    assert sum(result.target_weights, Decimal(0)) == result.target_equity_weight
    assert sum(result.target_weights, Decimal(0)) + result.cash_residual == Decimal(1)
    assert all(Decimal(0) <= weight <= Decimal("0.20") for weight in result.target_weights)


def test_common_scalar_preserves_every_pairwise_relative_weight_exactly() -> None:
    source = _source()
    result = calculate_volatility_overlay(source, Decimal("0.30"), _config())

    for left in range(len(_CODES)):
        for right in range(len(_CODES)):
            assert (
                result.target_weights[left] * result.risky_sleeve_weights[right]
                == result.target_weights[right] * result.risky_sleeve_weights[left]
            )


@pytest.mark.parametrize(
    ("target", "forecast", "expected"),
    (
        (Decimal("0.10"), Decimal("0.20"), Decimal("0.5")),
        (Decimal("0.20"), Decimal("0.20"), Decimal(1)),
        (Decimal("0.30"), Decimal("0.20"), Decimal(1)),
    ),
)
def test_scalar_clamps_at_one_without_short_or_leverage(
    target: Decimal,
    forecast: Decimal,
    expected: Decimal,
) -> None:
    result = calculate_volatility_overlay(source := _source(), forecast, _config(target))

    assert result.scalar == expected
    assert result.target_equity_weight == expected
    assert result.cash_residual == Decimal(1) - expected
    assert all(
        Decimal(0) <= final <= risky <= Decimal("0.20")
        for final, risky in zip(result.target_weights, source.reconciled_weights, strict=True)
    )


@pytest.mark.parametrize(
    "value",
    (
        Decimal(0),
        Decimal("-0.01"),
        Decimal("NaN"),
        Decimal("Infinity"),
        0.10,
        True,
        "0.10",
    ),
)
def test_config_rejects_nonpositive_nonfinite_or_non_decimal_target(value: object) -> None:
    with pytest.raises(InvalidVolatilityOverlayDomainError):
        VolatilityOverlayConfig(target_annual_volatility=value)


@pytest.mark.parametrize(
    "value",
    (
        Decimal("1E+10000"),
        Decimal("1E-10000"),
        Decimal("0.1234567890123"),
        Decimal("1.000000000001"),
    ),
)
def test_target_contract_rejects_excessive_range_or_precision(value: Decimal) -> None:
    with pytest.raises(InvalidVolatilityOverlayDomainError):
        VolatilityOverlayConfig(target_annual_volatility=value)


@pytest.mark.parametrize(
    "value",
    (
        Decimal("1E+10000"),
        Decimal("0.1234567890123"),
        Decimal("-0.000000000001"),
        Decimal("1.000000000001"),
    ),
)
def test_cash_yield_contract_rejects_excessive_range_or_precision(value: Decimal) -> None:
    with pytest.raises(InvalidVolatilityOverlayDomainError):
        VolatilityOverlayConfig(
            target_annual_volatility=Decimal("0.10"),
            annual_cash_yield=value,
        )


def test_economic_inputs_are_canonicalized_before_storage() -> None:
    config = VolatilityOverlayConfig(
        target_annual_volatility=Decimal("0.123456789012000000"),
        annual_cash_yield=Decimal("0E-10000"),
    )
    equivalent = VolatilityOverlayConfig(
        target_annual_volatility=Decimal("0.123456789012"),
        annual_cash_yield=Decimal("0"),
    )

    assert config == equivalent
    assert config.target_annual_volatility.as_tuple() == Decimal("0.123456789012").as_tuple()
    assert config.annual_cash_yield.as_tuple() == Decimal("0").as_tuple()
    assert json.loads(config.model_dump_json()) == {
        "target_annual_volatility": "0.123456789012",
        "annual_cash_yield": "0",
        "code_model_version": VOLATILITY_OVERLAY_CODE_MODEL_VERSION,
    }


def test_one_is_allowed_for_both_economic_inputs() -> None:
    config = VolatilityOverlayConfig(
        target_annual_volatility=Decimal("1.0000000000000"),
        annual_cash_yield=Decimal("1.0000000000000"),
    )

    assert config.target_annual_volatility.as_tuple() == Decimal("1").as_tuple()
    assert config.annual_cash_yield.as_tuple() == Decimal("1").as_tuple()


@pytest.mark.parametrize(
    "value",
    (
        Decimal(0),
        Decimal("-0.01"),
        Decimal("NaN"),
        Decimal("Infinity"),
        0.20,
        True,
        "0.20",
    ),
)
def test_decimal_calculation_api_rejects_invalid_forecast(value: object) -> None:
    with pytest.raises(InvalidVolatilityOverlayDomainError):
        calculate_volatility_overlay(_source(), value, _config())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "value",
    (
        Decimal("-0.01"),
        Decimal("-1"),
        Decimal("-1.01"),
        Decimal("1.01"),
        Decimal("NaN"),
        Decimal("Infinity"),
        0.03,
        True,
        "0.03",
    ),
)
def test_cash_yield_requires_decimal_in_the_closed_unit_interval(value: object) -> None:
    with pytest.raises(InvalidVolatilityOverlayDomainError):
        VolatilityOverlayConfig(
            target_annual_volatility=Decimal("0.10"),
            annual_cash_yield=value,
        )


def test_cash_yield_default_boundary_and_positive_value_do_not_change_scalar() -> None:
    default = calculate_volatility_overlay(_source(), Decimal("0.20"), _config())
    upper_boundary = calculate_volatility_overlay(
        _source(),
        Decimal("0.20"),
        _config(cash_yield=Decimal("1")),
    )
    positive = calculate_volatility_overlay(
        _source(),
        Decimal("0.20"),
        _config(cash_yield=Decimal("0.03")),
    )

    assert default.annual_cash_yield == Decimal(0)
    assert upper_boundary.annual_cash_yield == Decimal("1")
    assert positive.annual_cash_yield == Decimal("0.03")
    assert default.scalar == upper_boundary.scalar == positive.scalar == Decimal("0.5")
    assert default.target_weights == upper_boundary.target_weights == positive.target_weights


def test_adapter_converts_the_validated_erc_float_forecast_once() -> None:
    source = _source(CovarianceScenarioKind.FAST_IEWMA)

    result = apply_volatility_overlay(source, _config())

    assert result.forecast_annual_volatility == Decimal(str(source.expected_portfolio_volatility))
    assert type(result.forecast_annual_volatility) is Decimal
    assert result.source_policy_id == "constrained_erc_fast_iewma"
    assert result.policy_id == "volatility_overlay_fast_iewma"


@pytest.mark.parametrize("value", (0.0, -0.1, float("nan"), float("inf")))
def test_adapter_rejects_invalid_float_forecast(value: float) -> None:
    source = _source()
    corrupted = replace(
        source.diagnostics_after_reconciliation,
        portfolio_volatility=source.diagnostics_after_reconciliation.portfolio_volatility,
    )
    object.__setattr__(corrupted, "portfolio_volatility", value)
    object.__setattr__(source, "diagnostics_after_reconciliation", corrupted)

    with pytest.raises(InvalidVolatilityOverlayDomainError):
        apply_volatility_overlay(source, _config())


def test_source_must_be_a_valid_fully_invested_twenty_percent_erc_target() -> None:
    with pytest.raises(InvalidVolatilityOverlayDomainError):
        calculate_volatility_overlay(object(), Decimal("0.20"), _config())  # type: ignore[arg-type]

    source = solve_constrained_erc(
        _identity(4),
        _CODES[:4],
        upper_bounds=(Decimal("0.30"),) * 4,
    )
    with pytest.raises(InvalidVolatilityOverlayDomainError, match="20%"):
        calculate_volatility_overlay(source, Decimal("0.20"), _config())


def test_corrupted_source_weight_sum_cap_and_policy_are_rejected() -> None:
    bad_sum = _source()
    object.__setattr__(bad_sum, "reconciled_weights", (Decimal("0.1"),) * 6)
    with pytest.raises(InvalidVolatilityOverlayDomainError, match="합계"):
        calculate_volatility_overlay(bad_sum, Decimal("0.20"), _config())

    bad_cap = _source()
    object.__setattr__(
        bad_cap,
        "reconciled_weights",
        (
            Decimal("0.21"),
            Decimal("0.19"),
            Decimal("0.15"),
            Decimal("0.15"),
            Decimal("0.15"),
            Decimal("0.15"),
        ),
    )
    with pytest.raises(InvalidVolatilityOverlayDomainError, match="20%"):
        calculate_volatility_overlay(bad_cap, Decimal("0.20"), _config())

    bad_policy = _source()
    object.__setattr__(bad_policy, "policy_id", "weekly_equal_weight")
    with pytest.raises(InvalidVolatilityOverlayDomainError, match="source policy"):
        calculate_volatility_overlay(bad_policy, Decimal("0.20"), _config())


def test_target_model_rejects_broken_exact_sum_cash_and_relative_weight_contracts() -> None:
    result = calculate_volatility_overlay(_source(), Decimal("0.20"), _config())
    values = result.model_dump()

    with pytest.raises(InvalidVolatilityOverlayDomainError):
        VolatilityOverlayTarget(
            **{
                **values,
                "target_weights": (
                    result.target_weights[0] + Decimal("0.01"),
                    *result.target_weights[1:],
                ),
            }
        )
    with pytest.raises(InvalidVolatilityOverlayDomainError):
        VolatilityOverlayTarget(**{**values, "cash_residual": Decimal("0.49")})
    with pytest.raises(InvalidVolatilityOverlayDomainError):
        VolatilityOverlayTarget(**{**values, "target_equity_weight": Decimal("0.6")})


def test_models_are_frozen_extra_forbidden_and_decimal_json_is_text() -> None:
    config = _config(cash_yield=Decimal("0.0300"))
    result = calculate_volatility_overlay(_source(), Decimal("0.20"), config)
    payload = json.loads(result.model_dump_json())

    assert payload["forecast_annual_volatility"] == "0.20"
    assert payload["target_annual_volatility"] == "0.1"
    assert payload["scalar"] == "0.5"
    assert isinstance(payload["cash_residual"], str)
    assert Decimal(payload["cash_residual"]) == Decimal("0.5")
    assert payload["annual_cash_yield"] == "0.03"
    assert all(isinstance(value, str) for value in payload["target_weights"])
    assert VolatilityOverlayTarget.model_validate_json(result.model_dump_json()) == result
    with pytest.raises(ValidationError):
        config.target_annual_volatility = Decimal("0.20")
    with pytest.raises(ValidationError):
        VolatilityOverlayConfig(
            target_annual_volatility=Decimal("0.10"),
            unknown=Decimal(0),
        )


def test_overlay_is_independent_of_the_process_decimal_context() -> None:
    source = _source()
    original = getcontext().copy()
    try:
        getcontext().prec = 4
        getcontext().rounding = ROUND_DOWN
        low = calculate_volatility_overlay(source, Decimal("0.3"), _config())

        getcontext().prec = 80
        getcontext().rounding = ROUND_UP
        high = calculate_volatility_overlay(source, Decimal("0.3"), _config())
    finally:
        setcontext(original)

    assert high == low


def test_overlay_policy_mapping_rejects_non_scenario_values() -> None:
    with pytest.raises(InvalidVolatilityOverlayDomainError):
        overlay_policy_id("fast_iewma")  # type: ignore[arg-type]


def test_diagnostics_type_remains_the_existing_erc_contract() -> None:
    source = _source()
    assert isinstance(source.diagnostics_after_reconciliation, ConstrainedErcKktDiagnostics)
