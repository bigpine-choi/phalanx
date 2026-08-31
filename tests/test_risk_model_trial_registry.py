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

import phalanx.portfolio.private_json_storage as private_storage
from phalanx.domain import (
    SCENARIO_KIND_ORDER,
    AlignedReturnMatrix,
    DynamicRiskModelConfig,
    RiskModelResearchTrial,
)
from phalanx.portfolio.errors import (
    RiskModelTrialAlreadyExistsError,
    RiskModelTrialCorruptionError,
    RiskModelTrialStorageError,
)
from phalanx.portfolio.risk_model_research import (
    create_failed_risk_model_trial,
    create_risk_model_research_trial,
    fingerprint_aligned_return_matrix,
    fingerprint_risk_model_config,
    fingerprint_risk_model_trial,
)
from phalanx.portfolio.risk_model_trial_registry import (
    JsonRiskModelTrialRegistry,
    serialize_risk_model_trial,
)

_TRIAL_ID = "risk-test-001"
_EXECUTED_AT = datetime(2026, 2, 1, 12, 30, tzinfo=UTC)


def _config() -> DynamicRiskModelConfig:
    return DynamicRiskModelConfig(
        minimum_observations=10,
        maximum_observations=12,
        rebalance_interval=5,
        fast_volatility_half_life=2,
        fast_correlation_half_life=4,
        slow_volatility_half_life=3,
        slow_correlation_half_life=6,
        minimum_volatility_seed_observations=2,
        minimum_correlation_observations=3,
        downside_fraction=Decimal("0.50"),
        minimum_downside_observations=4,
    )


def _matrix() -> AlignedReturnMatrix:
    dates = tuple(date(2026, 1, 1) + timedelta(days=index) for index in range(11))
    values = tuple(
        (
            Decimal(index - 5) / Decimal(1_000),
            Decimal((index * 3) % 7 - 3) / Decimal(1_000),
        )
        for index in range(11)
    )
    return AlignedReturnMatrix(
        stock_codes=("005930", "000660"),
        dates=dates,
        values=values,
    )


@pytest.fixture(scope="module")
def successful_trial() -> RiskModelResearchTrial:
    matrix = _matrix()
    return create_risk_model_research_trial(
        matrix,
        matrix.dates[0],
        matrix.dates[-1],
        config=_config(),
        trial_id_factory=lambda: _TRIAL_ID,
        clock=lambda: _EXECUTED_AT,
    )


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat(follow_symlinks=False).st_mode)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _all_mapping_keys(value: object) -> tuple[str, ...]:
    if isinstance(value, dict):
        return tuple(str(key) for key in value) + tuple(
            nested_key for item in value.values() for nested_key in _all_mapping_keys(item)
        )
    if isinstance(value, list):
        return tuple(nested_key for item in value for nested_key in _all_mapping_keys(item))
    return ()


def test_successful_trial_serializes_and_loads_as_equal_domain(
    successful_trial: RiskModelResearchTrial,
    tmp_path: Path,
) -> None:
    registry = JsonRiskModelTrialRegistry(tmp_path / "risk-trials")

    saved = registry.save(successful_trial)
    loaded = registry.load(saved)

    assert saved.name == f"risk_model_research_trial_{_TRIAL_ID}.json"
    assert loaded == successful_trial
    assert saved.read_bytes() == serialize_risk_model_trial(successful_trial)


def test_fingerprints_and_serialized_bytes_are_canonical_and_deterministic(
    successful_trial: RiskModelResearchTrial,
) -> None:
    config = _config()
    equivalent_config = replace(config, downside_fraction=Decimal("0.5000"))
    matrix = _matrix()
    equivalent_matrix = AlignedReturnMatrix(
        stock_codes=matrix.stock_codes,
        dates=matrix.dates,
        values=tuple(
            tuple(Decimal(f"{format(value, 'f')}0") for value in row) for row in matrix.values
        ),
    )

    assert fingerprint_risk_model_config(config) == fingerprint_risk_model_config(equivalent_config)
    assert fingerprint_aligned_return_matrix(
        matrix,
        config,
    ) == fingerprint_aligned_return_matrix(equivalent_matrix, equivalent_config)
    assert successful_trial.trial_fingerprint == fingerprint_risk_model_trial(
        successful_trial.config_fingerprint,
        successful_trial.input_fingerprint,
    )
    assert serialize_risk_model_trial(successful_trial) == serialize_risk_model_trial(
        successful_trial
    )


def test_json_retains_all_decimal_rows_provenance_and_four_scenarios(
    successful_trial: RiskModelResearchTrial,
) -> None:
    payload = json.loads(serialize_risk_model_trial(successful_trial))
    matrix = _matrix()

    assert payload["aligned_returns"]["dates"] == [value.isoformat() for value in matrix.dates]
    assert payload["aligned_returns"]["values"] == [
        [format(value, "f").rstrip("0").rstrip(".") or "0" for value in row]
        for row in matrix.values
    ]
    assert payload["provenance"] == {
        "model_version": successful_trial.provenance.model_version,
        "numpy_version": successful_trial.provenance.numpy_version,
        "python_version": successful_trial.provenance.python_version,
        "schema_version": successful_trial.provenance.schema_version,
        "scikit_learn_version": successful_trial.provenance.scikit_learn_version,
    }
    snapshots = payload["result"]["snapshots"]
    assert len(snapshots) == 1
    assert tuple(scenario["kind"] for scenario in snapshots[0]["scenarios"]) == tuple(
        kind.value for kind in SCENARIO_KIND_ORDER
    )
    assert len(snapshots[0]["scenarios"]) == 4


def test_condition_number_none_round_trips(
    successful_trial: RiskModelResearchTrial,
    tmp_path: Path,
) -> None:
    assert successful_trial.result is not None
    snapshot = successful_trial.result.snapshots[0]
    scenario = snapshot.scenarios[0]
    scenario_without_condition = replace(
        scenario,
        psd_diagnostics=replace(scenario.psd_diagnostics, condition_number=None),
    )
    changed_snapshot = replace(
        snapshot,
        scenarios=(scenario_without_condition, *snapshot.scenarios[1:]),
    )
    changed_result = replace(successful_trial.result, snapshots=(changed_snapshot,))
    changed_trial = replace(successful_trial, result=changed_result)
    registry = JsonRiskModelTrialRegistry(tmp_path)

    loaded = registry.load(registry.save(changed_trial))

    assert loaded.result is not None
    assert loaded.result.snapshots[0].scenarios[0].psd_diagnostics.condition_number is None
    assert loaded == changed_trial


def test_registry_uses_private_modes_and_refuses_overwrite(
    successful_trial: RiskModelResearchTrial,
    tmp_path: Path,
) -> None:
    registry = JsonRiskModelTrialRegistry(tmp_path / "risk-trials")
    saved = registry.save(successful_trial)

    assert _mode(saved.parent) == 0o700
    assert _mode(saved) == 0o600
    assert _mode(saved.parent / f".{saved.name}.lock") == 0o600
    original = saved.read_bytes()
    with pytest.raises(RiskModelTrialAlreadyExistsError, match="덮어쓰지"):
        registry.save(successful_trial)
    assert saved.read_bytes() == original


def test_concurrent_same_trial_has_exactly_one_winner(
    successful_trial: RiskModelResearchTrial,
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "risk-trials"
    registries = (
        JsonRiskModelTrialRegistry(output_dir),
        JsonRiskModelTrialRegistry(output_dir),
    )

    def save(registry: JsonRiskModelTrialRegistry) -> Path:
        return registry.save(successful_trial)

    successes: list[Path] = []
    failures: list[Exception] = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(save, registry) for registry in registries]
        for future in futures:
            try:
                successes.append(future.result())
            except Exception as error:
                failures.append(error)

    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], RiskModelTrialAlreadyExistsError)
    assert successes[0].read_bytes() == serialize_risk_model_trial(successful_trial)


def test_write_failure_leaves_no_partial_file_or_temporary_file(
    successful_trial: RiskModelResearchTrial,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "risk-trials"
    output = output_dir / f"risk_model_research_trial_{_TRIAL_ID}.json"

    def fail_write(descriptor: int, payload: bytes) -> None:
        raise OSError("synthetic write failure")

    monkeypatch.setattr(private_storage, "_write_all", fail_write)

    with pytest.raises(RiskModelTrialStorageError, match="원자적으로"):
        JsonRiskModelTrialRegistry(output_dir).save(successful_trial)

    assert not output.exists()
    assert list(output_dir.glob(f".{output.name}.*.tmp")) == []


def test_exclusive_publish_preserves_racing_file_and_cleans_temporary_file(
    successful_trial: RiskModelResearchTrial,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "risk-trials"
    output = output_dir / f"risk_model_research_trial_{_TRIAL_ID}.json"
    original_link = os.link

    def race_then_link(source: Path, target: Path) -> None:
        assert source.name.startswith(f".{output.name}.")
        assert target == output
        output.write_bytes(b"racing existing trial")
        original_link(source, target)

    monkeypatch.setattr(private_storage.os, "link", race_then_link)

    with pytest.raises(RiskModelTrialAlreadyExistsError, match="덮어쓰지"):
        JsonRiskModelTrialRegistry(output_dir).save(successful_trial)

    assert output.read_bytes() == b"racing existing trial"
    assert list(output_dir.glob(f".{output.name}.*.tmp")) == []


def test_load_rejects_malformed_json(tmp_path: Path) -> None:
    path = tmp_path / "malformed.json"
    path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(RiskModelTrialCorruptionError, match="손상"):
        JsonRiskModelTrialRegistry(tmp_path).load(path)


def test_load_rejects_domain_inconsistent_scenario_count(
    successful_trial: RiskModelResearchTrial,
    tmp_path: Path,
) -> None:
    payload = json.loads(serialize_risk_model_trial(successful_trial))
    payload["result"]["snapshots"][0]["scenarios"].pop()
    path = tmp_path / "corrupt.json"
    _write_json(path, payload)

    with pytest.raises(RiskModelTrialCorruptionError):
        JsonRiskModelTrialRegistry(tmp_path).load(path)


@pytest.mark.parametrize(
    ("fingerprint_key", "message"),
    (
        ("config_sha256", "설정 fingerprint"),
        ("input_sha256", "입력 fingerprint"),
        ("trial_sha256", "trial fingerprint"),
    ),
)
def test_load_rejects_fingerprint_mismatch(
    successful_trial: RiskModelResearchTrial,
    tmp_path: Path,
    fingerprint_key: str,
    message: str,
) -> None:
    payload = json.loads(serialize_risk_model_trial(successful_trial))
    payload["fingerprints"][fingerprint_key] = "0" * 64
    path = tmp_path / f"mismatch-{fingerprint_key}.json"
    _write_json(path, payload)

    with pytest.raises(RiskModelTrialCorruptionError, match=message):
        JsonRiskModelTrialRegistry(tmp_path).load(path)


def test_serialized_trials_recursively_exclude_credentials_accounts_http_and_secrets(
    successful_trial: RiskModelResearchTrial,
) -> None:
    secrets = (
        "synthetic-app-key-123",
        "synthetic-app-secret-456",
        "synthetic-access-token-789",
        "12345678-01",
        "openapi.koreainvestment.com",
    )
    failed_trial = create_failed_risk_model_trial(
        successful_trial.stock_codes,
        successful_trial.requested_start,
        successful_trial.requested_end,
        RuntimeError(" ".join(secrets)),
        config=_config(),
        trial_id_factory=lambda: "risk-secret-failure",
        clock=lambda: _EXECUTED_AT,
    )
    forbidden_keys = {
        "authorization",
        "appkey",
        "app_key",
        "appsecret",
        "app_secret",
        "access_token",
        "token",
        "account_number",
        "account_no",
        "cano",
        "acnt_prdt_cd",
        "http",
        "headers",
        "request",
        "response",
        "url",
    }

    for trial in (successful_trial, failed_trial):
        serialized = serialize_risk_model_trial(trial).decode("utf-8")
        payload = json.loads(serialized)
        normalized_keys = {key.lower().replace("-", "_") for key in _all_mapping_keys(payload)}
        assert normalized_keys.isdisjoint(forbidden_keys)
        assert all(secret not in serialized for secret in secrets)
        assert "Traceback" not in serialized
