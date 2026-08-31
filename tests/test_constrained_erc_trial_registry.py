from __future__ import annotations

import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from filelock import FileLock

import phalanx.portfolio.private_json_storage as private_storage
from phalanx.domain import (
    CONSTRAINED_ERC_POLICY_ORDER,
    CONSTRAINED_ERC_SCHEMA,
    SCENARIO_KIND_ORDER,
    AllocationBacktestConfig,
    ConstrainedErcFailure,
    ConstrainedErcOutcomeStatus,
    ConstrainedErcPolicyOutcome,
    ConstrainedErcResearchStatus,
    ConstrainedErcResearchTrial,
    DailyBar,
    DynamicRiskModelConfig,
    KoreanStock,
    StockMarket,
)
from phalanx.market_data.service import StockDailyBars
from phalanx.portfolio.constrained_erc_research import conduct_constrained_erc_research
from phalanx.portfolio.constrained_erc_trial_registry import (
    JsonConstrainedErcTrialRegistry,
    fingerprint_constrained_erc_config,
    fingerprint_constrained_erc_covariances,
    fingerprint_constrained_erc_market_data,
    fingerprint_constrained_erc_trial,
    safe_constrained_erc_failure_display,
    serialize_constrained_erc_trial,
)
from phalanx.portfolio.errors import (
    ConstrainedErcTrialAlreadyExistsError,
    ConstrainedErcTrialLockTimeoutError,
    ConstrainedErcTrialSerializationError,
    ConstrainedErcTrialStorageError,
)

_START = date(2025, 1, 1)
_EXECUTED_AT = datetime(2026, 1, 1, 9, 30, tzinfo=UTC)
_TRIAL_ID = "constrained-registry-001"
_STOCK_CODES = ("000001", "000002", "000003", "000004", "000005")


def _allocation_config() -> AllocationBacktestConfig:
    return AllocationBacktestConfig(
        minimum_training_returns=20,
        maximum_training_returns=22,
        rebalance_interval=2,
        target_equity_weight=Decimal(1),
    )


def _risk_config() -> DynamicRiskModelConfig:
    return DynamicRiskModelConfig(
        minimum_observations=20,
        maximum_observations=22,
        rebalance_interval=2,
        fast_volatility_half_life=2,
        fast_correlation_half_life=4,
        slow_volatility_half_life=3,
        slow_correlation_half_life=6,
        minimum_volatility_seed_observations=2,
        minimum_correlation_observations=3,
        downside_fraction=Decimal("0.50"),
        minimum_downside_observations=3,
    )


def _histories(count: int = 27) -> tuple[StockDailyBars, ...]:
    histories: list[StockDailyBars] = []
    for column, stock_code in enumerate(_STOCK_CODES):
        bars: list[DailyBar] = []
        for index in range(count):
            trade_date = _START + timedelta(days=index)
            trend = Decimal(index * (column + 1))
            cycle = Decimal(((index + column) % 4) - 2) / Decimal(3)
            close = Decimal(100 + column * 20) + trend + cycle
            overnight = Decimal((index + column) % 3 - 1) / Decimal(5)
            open_price = close - overnight
            bars.append(
                DailyBar(
                    stock_code=stock_code,
                    trade_date=trade_date,
                    open_price=open_price,
                    high_price=max(open_price, close) + Decimal(1),
                    low_price=min(open_price, close) - Decimal(1),
                    close_price=close,
                    volume=1_000 + index,
                )
            )
        histories.append(
            StockDailyBars(
                stock=KoreanStock(
                    stock_code,
                    f"종목-{column + 1}",
                    StockMarket.KOSPI,
                ),
                bars=tuple(bars),
            )
        )
    return tuple(histories)


@pytest.fixture(scope="module")
def successful_trial() -> ConstrainedErcResearchTrial:
    trial = conduct_constrained_erc_research(
        _histories(),
        _START,
        _START + timedelta(days=26),
        allocation_config=_allocation_config(),
        risk_model_config=_risk_config(),
        trial_id_factory=lambda: _TRIAL_ID,
        clock=lambda: _EXECUTED_AT,
    )
    assert trial.status is ConstrainedErcResearchStatus.SUCCEEDED
    return trial


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat(follow_symlinks=False).st_mode)


def _all_mapping_keys(value: object) -> tuple[str, ...]:
    if isinstance(value, dict):
        return tuple(str(key) for key in value) + tuple(
            nested_key for item in value.values() for nested_key in _all_mapping_keys(item)
        )
    if isinstance(value, list):
        return tuple(nested_key for item in value for nested_key in _all_mapping_keys(item))
    return ()


def _failure_outcome(message: str) -> ConstrainedErcPolicyOutcome:
    return ConstrainedErcPolicyOutcome(
        policy_id=CONSTRAINED_ERC_POLICY_ORDER[0],
        status=ConstrainedErcOutcomeStatus.FAILED,
        failure=ConstrainedErcFailure(
            code="constrained_erc_calculation_error",
            message=message,
        ),
    )


def _trial_with_failure_message(
    trial: ConstrainedErcResearchTrial,
    message: str,
) -> ConstrainedErcResearchTrial:
    outcomes = (_failure_outcome(message), *trial.policy_outcomes[1:])
    trial_fingerprint = fingerprint_constrained_erc_trial(
        config_fingerprint=trial.config_fingerprint,
        market_data_fingerprint=trial.market_data_fingerprint,
        covariance_fingerprint=trial.covariance_fingerprint,
        signal_dates=trial.signal_dates,
        execution_dates=trial.execution_dates,
        policy_outcomes=outcomes,
    )
    return replace(
        trial,
        status=ConstrainedErcResearchStatus.FAILED,
        policy_outcomes=outcomes,
        trial_fingerprint=trial_fingerprint,
    )


def test_serialization_projects_full_audit_schema_and_decimal_text(
    successful_trial: ConstrainedErcResearchTrial,
) -> None:
    serialized = serialize_constrained_erc_trial(successful_trial)
    payload = json.loads(serialized)

    assert serialized.endswith(b"\n")
    assert serialized == serialize_constrained_erc_trial(successful_trial)
    assert set(payload) == {
        "actual_evaluation_period",
        "aligned_market_data",
        "aligned_returns",
        "code_model_version",
        "config",
        "executed_at",
        "fingerprints",
        "policy_outcomes",
        "provenance",
        "requested_period",
        "research_scope",
        "risk_snapshot_outcomes",
        "schedule",
        "schema",
        "schema_version",
        "solver_version",
        "status",
        "stock_codes",
        "trial_id",
    }
    assert payload["schema"] == CONSTRAINED_ERC_SCHEMA
    assert payload["schema_version"] == successful_trial.schema_version
    assert payload["code_model_version"] == successful_trial.code_model_version
    assert payload["solver_version"] == successful_trial.solver_config.solver_version
    assert payload["stock_codes"] == list(_STOCK_CODES)
    assert payload["research_scope"] == "current-universe conditional allocation-only"
    assert payload["actual_evaluation_period"] == {
        "start": successful_trial.actual_evaluation_start.isoformat(),
        "end": successful_trial.actual_evaluation_end.isoformat(),
    }

    market_data = payload["aligned_market_data"]
    assert market_data["missing_value_adjustment"] == "none"
    assert market_data["stock_codes"] == list(_STOCK_CODES)
    assert successful_trial.price_panel is not None
    first_open = format(successful_trial.price_panel.open_prices[0][0], "f").rstrip("0").rstrip(".")
    assert market_data["adjusted_open_prices"][0][0] == first_open
    assert isinstance(market_data["adjusted_close_prices"][0][0], str)
    assert payload["aligned_returns"]["stock_codes"] == list(_STOCK_CODES)
    assert all(
        isinstance(value, str) for row in payload["aligned_returns"]["values"] for value in row
    )

    config = payload["config"]
    assert config["allocation"]["target_equity_weight"] == "1"
    assert config["allocation"]["buy_cost_rate"] == "0.001"
    assert config["allocation"]["sell_cost_rate"] == "0.0025"
    assert config["allocation"]["execution_price"] == "next_common_adjusted_open"
    assert config["solver"]["weight_quantum"] == "0.000000000001"
    assert config["solver"]["fallback_policy"] is None
    assert config["erc_contract"] == {
        "alpha_tilt": False,
        "expected_return_input": False,
        "leverage": False,
        "long_only": True,
        "lower_bound": "0",
        "per_asset_upper_bound": "0.2",
        "risk_budgets": "equal_1_over_n",
        "risk_free_rate_input": False,
        "risky_weight_sum": "1",
        "short": False,
        "strategic_cash_target": "0",
        "turnover_constraint": False,
        "volatility_target": False,
    }
    assert config["erc_per_asset_target_cap"] == "0.2"
    assert config["policy_order"] == list(CONSTRAINED_ERC_POLICY_ORDER)

    assert tuple(item["signal_number"] for item in payload["schedule"]) == (0, 1, 2)
    assert tuple(item["training_period"]["observation_count"] for item in payload["schedule"]) == (
        20,
        22,
        22,
    )
    assert tuple(item["signal_date"] for item in payload["schedule"]) == tuple(
        value.isoformat() for value in successful_trial.signal_dates
    )
    assert tuple(item["execution_date"] for item in payload["schedule"]) == tuple(
        value.isoformat() for value in successful_trial.execution_dates
    )

    risk_outcomes = payload["risk_snapshot_outcomes"]
    assert len(risk_outcomes) == len(successful_trial.signal_dates)
    assert all(item["status"] == "succeeded" and item["failure"] is None for item in risk_outcomes)
    first_snapshot = risk_outcomes[0]["snapshot"]
    assert first_snapshot["consumed_period"]["observation_count"] == 20
    assert tuple(item["kind"] for item in first_snapshot["scenarios"]) == tuple(
        kind.value for kind in SCENARIO_KIND_ORDER
    )
    assert tuple(item["metadata"]["type"] for item in first_snapshot["scenarios"]) == (
        "ledoit_wolf",
        "iewma",
        "iewma",
        "downside_stress_ledoit_wolf",
    )
    assert {
        "annualized_covariance",
        "annualized_volatilities",
        "correlation_matrix",
        "kind",
        "metadata",
        "observation_dates",
        "psd_diagnostics",
        "stock_codes",
    } <= set(first_snapshot["scenarios"][0])

    policy_outcomes = payload["policy_outcomes"]
    assert tuple(item["policy_id"] for item in policy_outcomes) == CONSTRAINED_ERC_POLICY_ORDER
    assert all(item["status"] == "succeeded" for item in policy_outcomes)
    assert all(len(item["erc_targets"]) == 3 for item in policy_outcomes[:4])
    assert all(item["erc_targets"] == [] for item in policy_outcomes[4:])
    target = policy_outcomes[0]["erc_targets"][0]
    assert target["risk_budgets"] == ["0.2"] * 5
    assert target["lower_bounds"] == ["0"] * 5
    assert target["upper_bounds"] == ["0.2"] * 5
    assert target["reconciled_decimal_weights"] == ["0.2"] * 5
    assert len(target["raw_float_weights"]) == 5
    assert target["weight_sum_residual_after"] == "0"
    assert target["all_assets_bound_degeneracy"] is True
    assert {
        "bisection_iterations",
        "bracket_expansions",
        "ccd_sweeps",
        "covariance_fingerprint",
        "diagnostics_after_reconciliation",
        "diagnostics_before_reconciliation",
        "lambda",
        "reconciliation_max_error",
        "solver_config_fingerprint",
        "solver_version",
        "weight_sum_residual_before",
    } <= set(target)
    for name in ("diagnostics_before_reconciliation", "diagnostics_after_reconciliation"):
        diagnostics = target[name]
        assert len(diagnostics["marginal_risks"]) == 5
        assert len(diagnostics["absolute_risk_contributions"]) == 5
        assert len(diagnostics["relative_risk_contributions"]) == 5
        assert "normalized_max_kkt_residual" in diagnostics
        assert "free_asset_rc_dispersion" in diagnostics
    result = policy_outcomes[0]["result"]
    assert result["stock_codes"] == list(_STOCK_CODES)
    assert result["net_asset_values"]
    assert result["realized_weights"]
    assert result["rebalances"]
    assert "buy_gross_turnover" in result
    assert "sell_gross_turnover" in result
    assert "cumulative_cost_rate" in result

    assert payload["fingerprints"] == {
        "config_sha256": successful_trial.config_fingerprint,
        "covariance_sha256": successful_trial.covariance_fingerprint,
        "market_data_sha256": successful_trial.market_data_fingerprint,
        "trial_sha256": successful_trial.trial_fingerprint,
    }
    assert payload["provenance"]["risk_model_version"] == (
        successful_trial.provenance.model_version
    )
    assert payload["provenance"]["solver_version"] == (
        successful_trial.solver_config.solver_version
    )


def test_common_input_failure_is_explicit_and_policy_failures_are_marked_not_run() -> None:
    trial = conduct_constrained_erc_research(
        (),
        _START,
        _START + timedelta(days=26),
        allocation_config=_allocation_config(),
        risk_model_config=_risk_config(),
        trial_id_factory=lambda: "common-input-failure",
        clock=lambda: _EXECUTED_AT,
    )

    payload = json.loads(serialize_constrained_erc_trial(trial))

    assert payload["common_failure"] == {
        "stage": "input_preparation",
        "failure": {
            "as_of_date": None,
            "code": "constrained_erc_input_error",
            "message": "Constrained ERC 공통 시장데이터 입력을 구성하지 못했습니다.",
            "scenario_kind": None,
        },
    }
    assert {outcome["failure"]["code"] for outcome in payload["policy_outcomes"]} == {
        "constrained_erc_not_run_common_failure"
    }
    assert all(outcome["erc_targets"] == [] for outcome in payload["policy_outcomes"])
    assert all(outcome["result"] is None for outcome in payload["policy_outcomes"])


def test_failure_display_uses_stable_allow_list_and_discards_raw_message() -> None:
    failure = ConstrainedErcFailure(
        code="unknown_internal_failure",
        message="synthetic-app-secret-access-token-account-number",
    )

    code, reason = safe_constrained_erc_failure_display(failure)

    assert code == "constrained_erc_calculation_error"
    assert reason == "Constrained ERC 정책 계산을 완료하지 못했습니다."
    assert "synthetic" not in reason


def test_fingerprint_excludes_uuid_time_and_failure_text_but_is_input_sensitive(
    successful_trial: ConstrainedErcResearchTrial,
) -> None:
    metadata_variant = replace(
        successful_trial,
        trial_id="different-trial-id",
        executed_at=successful_trial.executed_at + timedelta(days=30),
    )
    assert metadata_variant.trial_fingerprint == successful_trial.trial_fingerprint

    first_failure = _failure_outcome("first arbitrary failure text")
    second_failure = _failure_outcome("second arbitrary failure text")
    first_outcomes = (first_failure, *successful_trial.policy_outcomes[1:])
    second_outcomes = (second_failure, *successful_trial.policy_outcomes[1:])
    fingerprint_arguments = {
        "config_fingerprint": successful_trial.config_fingerprint,
        "market_data_fingerprint": successful_trial.market_data_fingerprint,
        "covariance_fingerprint": successful_trial.covariance_fingerprint,
        "signal_dates": successful_trial.signal_dates,
        "execution_dates": successful_trial.execution_dates,
    }
    assert fingerprint_constrained_erc_trial(
        **fingerprint_arguments,
        policy_outcomes=first_outcomes,
    ) == fingerprint_constrained_erc_trial(
        **fingerprint_arguments,
        policy_outcomes=second_outcomes,
    )

    changed_allocation_config = replace(
        successful_trial.allocation_config,
        buy_cost_rate=Decimal("0.0011"),
    )
    assert (
        fingerprint_constrained_erc_config(
            changed_allocation_config,
            successful_trial.risk_model_config,
            successful_trial.solver_config,
        )
        != successful_trial.config_fingerprint
    )

    assert successful_trial.price_panel is not None
    assert successful_trial.aligned_returns is not None
    changed_first_open = (
        successful_trial.price_panel.open_prices[0][0] + Decimal("0.01"),
        *successful_trial.price_panel.open_prices[0][1:],
    )
    changed_panel = replace(
        successful_trial.price_panel,
        open_prices=(changed_first_open, *successful_trial.price_panel.open_prices[1:]),
    )
    assert (
        fingerprint_constrained_erc_market_data(
            successful_trial.stock_codes,
            changed_panel,
            successful_trial.aligned_returns,
        )
        != successful_trial.market_data_fingerprint
    )

    assert (
        fingerprint_constrained_erc_covariances(
            tuple(reversed(successful_trial.risk_snapshot_outcomes))
        )
        != successful_trial.covariance_fingerprint
    )
    changed_execution_dates = (
        *successful_trial.execution_dates[:-1],
        successful_trial.execution_dates[-1] + timedelta(days=1),
    )
    assert (
        fingerprint_constrained_erc_trial(
            config_fingerprint=successful_trial.config_fingerprint,
            market_data_fingerprint=successful_trial.market_data_fingerprint,
            covariance_fingerprint=successful_trial.covariance_fingerprint,
            signal_dates=successful_trial.signal_dates,
            execution_dates=changed_execution_dates,
            policy_outcomes=successful_trial.policy_outcomes,
        )
        != successful_trial.trial_fingerprint
    )


@pytest.mark.parametrize(
    "field",
    (
        "config_fingerprint",
        "market_data_fingerprint",
        "covariance_fingerprint",
        "trial_fingerprint",
    ),
)
def test_serialization_rejects_a_fingerprint_not_matching_canonical_payload(
    successful_trial: ConstrainedErcResearchTrial,
    field: str,
) -> None:
    tampered = replace(successful_trial, **{field: "0" * 64})

    with pytest.raises(ConstrainedErcTrialSerializationError, match="fingerprint"):
        serialize_constrained_erc_trial(tampered)


def test_serialization_is_explicitly_secret_free_even_for_direct_failure_message(
    successful_trial: ConstrainedErcResearchTrial,
) -> None:
    secrets = (
        "synthetic-app-key-123",
        "synthetic-app-secret-456",
        "synthetic-access-token-789",
        "12345678-01",
        "openapi.koreainvestment.com",
    )
    secret_message = "failure contained " + " ".join(secrets)
    failed_trial = _trial_with_failure_message(successful_trial, secret_message)

    serialized = serialize_constrained_erc_trial(failed_trial).decode("utf-8")
    payload = json.loads(serialized)
    failure = payload["policy_outcomes"][0]["failure"]

    assert failure == {
        "as_of_date": None,
        "code": "constrained_erc_calculation_error",
        "message": "Constrained ERC 정책 계산을 완료하지 못했습니다.",
        "scenario_kind": None,
    }
    assert all(secret not in serialized for secret in secrets)
    assert secret_message not in serialized
    assert "Traceback" not in serialized
    forbidden_keys = {
        "authorization",
        "appkey",
        "app_key",
        "appsecret",
        "app_secret",
        "access_token",
        "token",
        "account",
        "account_number",
        "account_no",
        "cano",
        "acnt_prdt_cd",
        "credentials",
        "headers",
        "http",
        "request",
        "response",
        "url",
    }
    normalized_keys = {key.lower().replace("-", "_") for key in _all_mapping_keys(payload)}
    assert normalized_keys.isdisjoint(forbidden_keys)


def test_registry_saves_exact_bytes_with_private_modes_and_atomic_fsync(
    successful_trial: ConstrainedErcResearchTrial,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "constrained-trials"
    expected = output_dir / f"constrained_erc_research_trial_{_TRIAL_ID}.json"
    original_link = os.link
    original_fsync_directory = private_storage._fsync_directory
    observed_temporary_modes: list[int] = []
    fsynced_directories: list[Path] = []

    def inspect_then_link(source: Path, target: Path) -> None:
        assert target == expected
        observed_temporary_modes.append(_mode(source))
        original_link(source, target)

    def record_directory_fsync(directory: Path) -> None:
        assert expected.read_bytes() == serialize_constrained_erc_trial(successful_trial)
        fsynced_directories.append(directory)
        original_fsync_directory(directory)

    monkeypatch.setattr(private_storage.os, "link", inspect_then_link)
    monkeypatch.setattr(private_storage, "_fsync_directory", record_directory_fsync)

    saved = JsonConstrainedErcTrialRegistry(output_dir).save(successful_trial)

    assert saved == expected
    assert saved.read_bytes() == serialize_constrained_erc_trial(successful_trial)
    assert _mode(output_dir) == 0o700
    assert _mode(saved) == 0o600
    assert _mode(output_dir / f".{saved.name}.lock") == 0o600
    assert observed_temporary_modes == [0o600]
    assert fsynced_directories == [output_dir]


def test_registry_preserves_corrupt_existing_destination(
    successful_trial: ConstrainedErcResearchTrial,
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "constrained-trials"
    output_dir.mkdir()
    output = output_dir / f"constrained_erc_research_trial_{_TRIAL_ID}.json"
    corrupt_bytes = b'{"schema": not-valid-json'
    output.write_bytes(corrupt_bytes)

    with pytest.raises(ConstrainedErcTrialAlreadyExistsError, match="덮어쓰지"):
        JsonConstrainedErcTrialRegistry(output_dir).save(successful_trial)

    assert output.read_bytes() == corrupt_bytes
    assert list(output_dir.glob(f".{output.name}.*.tmp")) == []


def test_write_failure_leaves_no_partial_output_or_temporary_file(
    successful_trial: ConstrainedErcResearchTrial,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "constrained-trials"
    output = output_dir / f"constrained_erc_research_trial_{_TRIAL_ID}.json"

    def fail_write(descriptor: int, payload: bytes) -> None:
        raise OSError("synthetic write failure")

    monkeypatch.setattr(private_storage, "_write_all", fail_write)

    with pytest.raises(ConstrainedErcTrialStorageError, match="원자적으로"):
        JsonConstrainedErcTrialRegistry(output_dir).save(successful_trial)

    assert not output.exists()
    assert list(output_dir.glob(f".{output.name}.*.tmp")) == []


def test_exclusive_publish_preserves_racing_destination_and_cleans_temporary_file(
    successful_trial: ConstrainedErcResearchTrial,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "constrained-trials"
    output = output_dir / f"constrained_erc_research_trial_{_TRIAL_ID}.json"
    racing_bytes = b'{"existing":"racing-corrupt-output"}'
    original_link = os.link

    def race_then_link(source: Path, target: Path) -> None:
        assert source.name.startswith(f".{output.name}.")
        assert target == output
        output.write_bytes(racing_bytes)
        original_link(source, target)

    monkeypatch.setattr(private_storage.os, "link", race_then_link)

    with pytest.raises(ConstrainedErcTrialAlreadyExistsError, match="덮어쓰지"):
        JsonConstrainedErcTrialRegistry(output_dir).save(successful_trial)

    assert output.read_bytes() == racing_bytes
    assert list(output_dir.glob(f".{output.name}.*.tmp")) == []


def test_output_specific_lock_timeout_uses_dedicated_error(
    successful_trial: ConstrainedErcResearchTrial,
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "constrained-trials"
    output_dir.mkdir()
    output = output_dir / f"constrained_erc_research_trial_{_TRIAL_ID}.json"
    lock_path = output_dir / f".{output.name}.lock"

    with FileLock(lock_path, mode=0o600), pytest.raises(ConstrainedErcTrialLockTimeoutError):
        JsonConstrainedErcTrialRegistry(output_dir, lock_timeout=0).save(successful_trial)

    assert not output.exists()
    assert list(output_dir.glob(f".{output.name}.*.tmp")) == []


def test_concurrent_same_trial_save_has_exactly_one_winner(
    successful_trial: ConstrainedErcResearchTrial,
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "constrained-trials"
    registries = (
        JsonConstrainedErcTrialRegistry(output_dir),
        JsonConstrainedErcTrialRegistry(output_dir),
    )

    def save(registry: JsonConstrainedErcTrialRegistry) -> Path:
        return registry.save(successful_trial)

    successes: list[Path] = []
    failures: list[Exception] = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        for future in (executor.submit(save, registry) for registry in registries):
            try:
                successes.append(future.result())
            except Exception as error:
                failures.append(error)

    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], ConstrainedErcTrialAlreadyExistsError)
    assert successes[0].read_bytes() == serialize_constrained_erc_trial(successful_trial)
