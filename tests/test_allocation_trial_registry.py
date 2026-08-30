from __future__ import annotations

import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

import phalanx.portfolio.allocation_trial_registry as trial_registry
from phalanx.domain import (
    AllocationBacktestConfig,
    AllocationBacktestResult,
    AllocationPolicyFailure,
    AllocationPolicyOutcome,
    AllocationPolicyOutcomeStatus,
    AllocationRebalanceRecord,
    AllocationResearchTrial,
    AllocationTarget,
    AllocationTrialStatus,
    DailyBar,
    KoreanStock,
    StockMarket,
)
from phalanx.market_data.service import StockDailyBars
from phalanx.portfolio.allocation_policies import default_allocation_policies
from phalanx.portfolio.allocation_trial_registry import (
    JsonAllocationTrialRegistry,
    fingerprint_allocation_config,
    fingerprint_allocation_policies,
    fingerprint_market_data,
    serialize_allocation_trial,
)
from phalanx.portfolio.errors import (
    AllocationTrialAlreadyExistsError,
    AllocationTrialStorageError,
)

_POLICY_ID = "weekly_equal_weight"
_CODE_MODEL_VERSION = "allocation-research-v1"
_SIGNAL_DATE = date(2026, 1, 2)
_EXECUTION_DATE = date(2026, 1, 3)
_FINAL_DATE = date(2026, 1, 4)


def _bar(
    stock_code: str,
    trade_date: date,
    price: str,
) -> DailyBar:
    value = Decimal(price)
    return DailyBar(
        stock_code=stock_code,
        trade_date=trade_date,
        open_price=value,
        high_price=value,
        low_price=value,
        close_price=value,
        volume=1_000,
    )


def _history(
    stock_code: str = "005930",
    stock_name: str = "삼성전자",
    first_price: str = "100",
) -> StockDailyBars:
    stock = KoreanStock(stock_code, stock_name, StockMarket.KOSPI)
    return StockDailyBars(
        stock=stock,
        bars=(
            _bar(stock_code, _SIGNAL_DATE, first_price),
            _bar(stock_code, _EXECUTION_DATE, "101"),
            _bar(stock_code, _FINAL_DATE, "102"),
        ),
    )


def _success_result() -> AllocationBacktestResult:
    target = AllocationTarget(
        signal_date=_SIGNAL_DATE,
        stock_codes=("005930",),
        target_weights=(Decimal("0.995"),),
        policy_id=_POLICY_ID,
        target_equity_weight=Decimal("0.995"),
    )
    rebalance = AllocationRebalanceRecord(
        target=target,
        execution_date=_EXECUTION_DATE,
        realized_weights=(Decimal("0.995"),),
        realized_cash_weight=Decimal("0.005"),
        buy_gross_turnover=Decimal("0.995"),
        sell_gross_turnover=Decimal("0"),
        transaction_cost=Decimal("0.001"),
        transaction_cost_rate=Decimal("0.001"),
        pre_trade_nav=Decimal("1"),
        post_trade_nav=Decimal("0.999"),
        cash_after=Decimal("0.004995"),
    )
    return AllocationBacktestResult(
        policy_id=_POLICY_ID,
        stock_codes=("005930",),
        dates=(_EXECUTION_DATE, _FINAL_DATE),
        net_asset_values=(Decimal("0.999"), Decimal("1.01")),
        realized_weights=(
            (Decimal("0.995"),),
            (Decimal("0.996"),),
        ),
        realized_cash_weights=(Decimal("0.005"), Decimal("0.004")),
        rebalances=(rebalance,),
        buy_gross_turnover=Decimal("0.995"),
        sell_gross_turnover=Decimal("0"),
        cumulative_transaction_cost=Decimal("0.001"),
        cumulative_cost_rate=Decimal("0.001"),
        total_return=Decimal("0.01"),
        annualized_return=Decimal("0.20"),
        annualized_volatility=Decimal("0.12"),
        max_drawdown=Decimal("-0.03"),
    )


def _trial(
    *,
    trial_id: str = "trial-001",
    failure_secret: str | None = None,
) -> AllocationResearchTrial:
    config = AllocationBacktestConfig()
    history = (_history(),)
    if failure_secret is None:
        status = AllocationTrialStatus.SUCCEEDED
        actual_start: date | None = _EXECUTION_DATE
        actual_end: date | None = _FINAL_DATE
        outcomes = (
            AllocationPolicyOutcome(
                policy_id=_POLICY_ID,
                status=AllocationPolicyOutcomeStatus.SUCCEEDED,
                result=_success_result(),
            ),
        )
    else:
        status = AllocationTrialStatus.FAILED
        actual_start = None
        actual_end = None
        outcomes = (
            AllocationPolicyOutcome(
                policy_id=_POLICY_ID,
                status=AllocationPolicyOutcomeStatus.FAILED,
                failure=AllocationPolicyFailure(
                    code=failure_secret,
                    message=f"합성 계산 오류에 비밀값 포함: {failure_secret}",
                ),
            ),
        )
    return AllocationResearchTrial(
        trial_id=trial_id,
        status=status,
        executed_at=datetime(2026, 1, 5, 12, 30, tzinfo=UTC),
        requested_start=date(2024, 1, 1),
        requested_end=_FINAL_DATE,
        actual_evaluation_start=actual_start,
        actual_evaluation_end=actual_end,
        stock_codes=("005930",),
        config=config,
        policy_fingerprint=fingerprint_allocation_policies(
            default_allocation_policies(),
            _CODE_MODEL_VERSION,
        ),
        config_fingerprint=fingerprint_allocation_config(config),
        market_data_fingerprint=fingerprint_market_data(history),
        policy_outcomes=outcomes,
        code_model_version=_CODE_MODEL_VERSION,
    )


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat(follow_symlinks=False).st_mode)


def test_fingerprints_are_canonical_deterministic_and_order_sensitive() -> None:
    default_config = AllocationBacktestConfig()
    equivalent_config = AllocationBacktestConfig(
        target_equity_weight=Decimal("0.9950"),
        buy_cost_rate=Decimal("0.0010"),
        sell_cost_rate=Decimal("0.00250"),
    )
    policies = default_allocation_policies()
    samsung = _history()
    hynix = _history("000660", "SK하이닉스", "200")

    assert fingerprint_allocation_config(default_config) == fingerprint_allocation_config(
        equivalent_config
    )
    assert fingerprint_allocation_policies(
        policies,
        _CODE_MODEL_VERSION,
    ) == fingerprint_allocation_policies(default_allocation_policies(), _CODE_MODEL_VERSION)
    assert fingerprint_allocation_policies(
        policies,
        _CODE_MODEL_VERSION,
    ) != fingerprint_allocation_policies(tuple(reversed(policies)), _CODE_MODEL_VERSION)
    assert fingerprint_market_data((samsung, hynix)) == fingerprint_market_data((samsung, hynix))
    assert fingerprint_market_data((samsung, hynix)) != fingerprint_market_data((hynix, samsung))


def test_explicit_trial_projection_keeps_decimal_values_as_strings() -> None:
    payload = json.loads(serialize_allocation_trial(_trial()))

    assert payload["schema_version"] == "1"
    assert payload["config"]["target_equity_weight"] == "0.995"
    outcome = payload["policy_outcomes"][0]
    assert outcome["status"] == "succeeded"
    assert outcome["failure"] is None
    result = outcome["result"]
    assert result["net_asset_values"] == ["0.999", "1.01"]
    assert result["rebalances"][0]["target"]["target_weights"] == ["0.995"]
    assert result["annualized_volatility"] == "0.12"


def test_failure_projection_never_persists_arbitrary_secret_text() -> None:
    secret = "synthetic-app-secret-access-token-123"

    serialized = serialize_allocation_trial(_trial(failure_secret=secret)).decode("utf-8")
    payload = json.loads(serialized)

    assert secret not in serialized
    failure = payload["policy_outcomes"][0]["failure"]
    assert failure == {
        "code": "allocation_policy_error",
        "message": "정책 계산을 완료하지 못했습니다.",
    }
    assert "Traceback" not in serialized


def test_registry_saves_unique_private_json_and_lock_file(tmp_path: Path) -> None:
    trial = _trial()
    registry = JsonAllocationTrialRegistry(tmp_path / "trials")

    saved_path = registry.save(trial)

    assert saved_path == tmp_path / "trials" / "allocation_research_trial_trial-001.json"
    assert json.loads(saved_path.read_bytes())["trial_id"] == trial.trial_id
    assert _mode(saved_path.parent) == 0o700
    assert _mode(saved_path) == 0o600
    assert _mode(saved_path.parent / f".{saved_path.name}.lock") == 0o600


def test_registry_refuses_to_overwrite_existing_trial(tmp_path: Path) -> None:
    output_dir = tmp_path / "trials"
    output_dir.mkdir()
    output = output_dir / "allocation_research_trial_trial-001.json"
    output.write_text("existing trial", encoding="utf-8")

    with pytest.raises(AllocationTrialAlreadyExistsError, match="덮어쓰지"):
        JsonAllocationTrialRegistry(output_dir).save(_trial())

    assert output.read_text(encoding="utf-8") == "existing trial"


def test_temporary_file_is_0600_before_atomic_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "trials"
    original_replace = os.replace
    observed_modes: list[int] = []

    def inspect_then_replace(source: Path, target: Path) -> None:
        observed_modes.append(_mode(source))
        original_replace(source, target)

    monkeypatch.setattr(trial_registry.os, "replace", inspect_then_replace)

    JsonAllocationTrialRegistry(output_dir).save(_trial())

    assert observed_modes == [0o600]


def test_replace_failure_preserves_racing_file_and_cleans_temporary_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "trials"
    output = output_dir / "allocation_research_trial_trial-001.json"

    def fail_replace(source: Path, target: Path) -> None:
        assert source.name.startswith(f".{output.name}.")
        assert target == output
        output.write_text("racing existing trial", encoding="utf-8")
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(trial_registry.os, "replace", fail_replace)

    with pytest.raises(AllocationTrialStorageError, match="원자적으로"):
        JsonAllocationTrialRegistry(output_dir).save(_trial())

    assert output.read_text(encoding="utf-8") == "racing existing trial"
    assert list(output_dir.glob(f".{output.name}.*.tmp")) == []


def test_write_failure_leaves_no_partial_trial_or_temporary_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "trials"
    output = output_dir / "allocation_research_trial_trial-001.json"

    def fail_write(descriptor: int, payload: bytes) -> None:
        raise OSError("synthetic write failure")

    monkeypatch.setattr(trial_registry, "_write_all", fail_write)

    with pytest.raises(AllocationTrialStorageError, match="원자적으로"):
        JsonAllocationTrialRegistry(output_dir).save(_trial())

    assert not output.exists()
    assert list(output_dir.glob(f".{output.name}.*.tmp")) == []


def test_concurrent_same_trial_save_has_exactly_one_winner(tmp_path: Path) -> None:
    output_dir = tmp_path / "trials"
    registries = (
        JsonAllocationTrialRegistry(output_dir),
        JsonAllocationTrialRegistry(output_dir),
    )
    trial = _trial()

    def save(registry: JsonAllocationTrialRegistry) -> Path:
        return registry.save(trial)

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
    assert isinstance(failures[0], AllocationTrialAlreadyExistsError)
    assert successes[0].read_bytes() == serialize_allocation_trial(trial)
