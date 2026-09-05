from __future__ import annotations

import hashlib
import json
import stat
from decimal import ROUND_UP, Decimal, Inexact, localcontext
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

import phalanx.application as application
import phalanx.cli as cli
import phalanx.config as config
from phalanx.account_performance import AccountPerformanceError
from phalanx.application import run_account_performance
from phalanx.portfolio.private_json_storage import PrivateJsonAlreadyExistsError

FIXTURES = Path(__file__).parent / "fixtures" / "account_performance"


@pytest.fixture
def inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    paths = tuple(tmp_path / name for name in ("start.json", "end.json", "cash-flows.json"))
    for path in paths:
        path.write_bytes((FIXTURES / path.name).read_bytes())
    return paths[0], paths[1], paths[2]


def _update(path: Path, *location: str, value: Any) -> None:
    payload = json.loads(path.read_bytes())
    target = payload
    for key in location[:-1]:
        target = target[key]
    target[location[-1]] = value
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_exact_input_hashes_private_write_once_and_byte_reproducibility(
    inputs: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    output = tmp_path / "private-results" / "first.json"
    result = run_account_performance(*inputs, output_path=output)
    serialized = output.read_bytes()
    payload = json.loads(serialized)

    assert result.performance.profit_loss == Decimal("20")
    assert result.performance.average_invested_capital == Decimal("150")
    assert result.saved_path == output
    assert payload["schema_version"] == "1"
    assert payload["method"] == "modified_dietz"
    assert payload["scope"] == "whole_account"
    assert payload["profit_loss"] == "20"
    assert payload["estimated_return"].startswith("0.133333333333333333333333333333")
    assert payload["input_sha256"] == {
        key: hashlib.sha256(path.read_bytes()).hexdigest()
        for key, path in zip(("start_snapshot", "end_snapshot", "cash_flows"), inputs, strict=True)
    }
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert stat.S_IMODE(output.parent.stat().st_mode) == 0o700
    assert result.to_json_bytes() == serialized
    assert str(tmp_path).encode() not in serialized
    assert b"Synthetic example only; not an API response" not in serialized

    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_UP
        context.traps[Inexact] = True
        repeated = run_account_performance(*inputs, output_path=output.with_name("second.json"))
        assert repeated.to_json_bytes() == serialized
    with pytest.raises(PrivateJsonAlreadyExistsError):
        run_account_performance(*inputs, output_path=output)
    assert output.read_bytes() == serialized
    with pytest.raises(PrivateJsonAlreadyExistsError):
        run_account_performance(*inputs, output_path=inputs[0])


def test_hash_tracks_raw_bytes_even_when_semantic_inputs_match(
    inputs: tuple[Path, Path, Path],
) -> None:
    before = run_account_performance(*inputs)
    inputs[0].write_bytes(inputs[0].read_bytes() + b"\n")
    after = run_account_performance(*inputs)

    assert before.performance == after.performance
    assert before.input_sha256.start_snapshot != after.input_sha256.start_snapshot
    assert before.input_sha256.end_snapshot == after.input_sha256.end_snapshot
    assert before.input_sha256.cash_flows == after.input_sha256.cash_flows


@pytest.mark.parametrize("index", (0, 1, 2))
@pytest.mark.parametrize("payload", (b"{broken", b"\xff", b"[]", b"null", b"{}"))
def test_invalid_files_fail_before_any_result_write(
    inputs: tuple[Path, Path, Path], tmp_path: Path, index: int, payload: bytes
) -> None:
    inputs[index].write_bytes(payload)
    output = tmp_path / "not-created" / "result.json"
    with pytest.raises(AccountPerformanceError):
        run_account_performance(*inputs, output_path=output)
    assert not output.parent.exists()


@pytest.mark.parametrize("index", (0, 1, 2))
def test_missing_files_are_not_zero_flows(inputs: tuple[Path, Path, Path], index: int) -> None:
    inputs[index].unlink()
    with pytest.raises(AccountPerformanceError, match="파일을 읽지 못했습니다"):
        run_account_performance(*inputs)


@pytest.mark.parametrize("value", (False, 1, "true", None))
@pytest.mark.parametrize(
    "field", ("same_account_confirmed", "external_flows_complete", "no_in_kind_transfers")
)
def test_ledger_requires_actual_true_declarations(
    inputs: tuple[Path, Path, Path], field: str, value: Any
) -> None:
    _update(inputs[2], field, value=value)
    with pytest.raises(AccountPerformanceError, match=field):
        run_account_performance(*inputs)


@pytest.mark.parametrize("field", ("provider", "currency", "account_number_masked"))
def test_snapshot_identity_mismatch_is_rejected(
    inputs: tuple[Path, Path, Path], field: str
) -> None:
    value = {"provider": "other", "currency": "USD", "account_number_masked": "9999****-**"}
    _update(inputs[1], field, value=value[field])
    with pytest.raises(AccountPerformanceError):
        run_account_performance(*inputs)


@pytest.mark.parametrize("day", ("01", "11"))
@pytest.mark.parametrize("time", ("08:59:59", "08:59:59.500000", "09:00:00"))
def test_query_window_cash_flows_explain_nav_ambiguity_through_file_loading(
    inputs: tuple[Path, Path, Path], day: str, time: str
) -> None:
    _update(inputs[2], "events", value=[{
        "event_id": "ambiguous", "occurred_at": f"2026-08-{day}T{time}+09:00", "amount": "1",
    }])
    with pytest.raises(AccountPerformanceError, match=r"NAV.*모호"):
        run_account_performance(*inputs)


@pytest.mark.parametrize("index", (0, 1))
def test_existing_snapshot_invariants_and_warnings_are_enforced(
    inputs: tuple[Path, Path, Path], index: int
) -> None:
    _update(inputs[index], "evidence", "summary_consistency_warnings", value=["synthetic"])
    with pytest.raises(AccountPerformanceError):
        run_account_performance(*inputs)
    _update(inputs[index], "evidence", "summary_consistency_warnings", value=[])
    _update(inputs[index], "summary", "orderable_cash", value="100")
    with pytest.raises(AccountPerformanceError):
        run_account_performance(*inputs)


@pytest.mark.parametrize("index", (0, 2))
@pytest.mark.parametrize(
    "entry", ('"schema_version": "1",', '"unexpected": NaN,', '"unexpected": Infinity,')
)
def test_ambiguous_or_nonstandard_json_is_rejected(
    inputs: tuple[Path, Path, Path], index: int, entry: str
) -> None:
    inputs[index].write_bytes(inputs[index].read_bytes().replace(b"{", ("{" + entry).encode(), 1))
    with pytest.raises(AccountPerformanceError, match="JSON이 잘못되었습니다"):
        run_account_performance(*inputs)


def test_unavailable_return_serializes_null_but_keeps_profit_loss(
    inputs: tuple[Path, Path, Path],
) -> None:
    _update(inputs[0], "summary", "net_assets", value="0")
    _update(inputs[2], "events", value=[])
    result = run_account_performance(*inputs)
    payload = json.loads(result.to_json_bytes())
    assert payload["estimated_return"] is None
    assert payload["profit_loss"] == "220"
    assert payload["return_unavailable_reasons"]


def test_real_cli_reads_only_three_inputs_and_works_with_network_and_credentials_blocked(
    inputs: tuple[Path, Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("network, credential lookup or file discovery attempted")

    monkeypatch.setattr(config, "load_kis_credentials", forbidden)
    monkeypatch.setattr(application, "load_kis_credentials", forbidden)
    monkeypatch.setattr(application, "run_production_snapshot", forbidden)
    monkeypatch.setattr(httpx, "Client", forbidden)
    monkeypatch.setattr(Path, "home", forbidden)
    monkeypatch.setattr(Path, "glob", forbidden)
    monkeypatch.setattr(Path, "rglob", forbidden)
    original_read_bytes = Path.read_bytes
    reads: list[Path] = []

    def record_read(path: Path) -> bytes:
        assert path in inputs
        reads.append(path)
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", record_read)
    output = tmp_path / "results" / "performance.json"
    arguments = [
        "account", "performance", "--start-snapshot", str(inputs[0]),
        "--end-snapshot", str(inputs[1]), "--cash-flows", str(inputs[2]),
        "--output", str(output),
    ]
    result = CliRunner().invoke(cli.app, arguments)

    assert result.exit_code == 0, result.output
    assert reads == list(inputs)
    assert "실계좌 전체 기간 성과" in result.output
    assert "13.333333%" in result.output
    assert output.is_file()
    original_output = original_read_bytes(output)
    rerun = CliRunner().invoke(cli.app, arguments)
    assert rerun.exit_code == 66
    assert original_read_bytes(output) == original_output


@pytest.mark.parametrize("index", (0, 2))
def test_cli_validation_errors_do_not_echo_input_data(
    inputs: tuple[Path, Path, Path], index: int
) -> None:
    secret = "synthetic-secret-do-not-echo"
    _update(inputs[index], secret, value=secret)
    result = CliRunner().invoke(cli.app, [
        "account", "performance", "--start-snapshot", str(inputs[0]),
        "--end-snapshot", str(inputs[1]), "--cash-flows", str(inputs[2]),
    ])
    assert result.exit_code == 65
    assert secret not in result.output
    assert "Traceback" not in result.output
