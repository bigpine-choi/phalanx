from __future__ import annotations

import json
import os
import re
import stat
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

import phalanx.snapshots as snapshot_storage
from phalanx.domain import (
    AccountPosition,
    AccountSnapshot,
    AccountSummary,
    ApiPageEvidence,
    RawEvidenceField,
    RawEvidenceRecord,
    SnapshotEvidence,
)
from phalanx.snapshots import (
    SnapshotAlreadyExistsError,
    SnapshotStorageError,
    SnapshotStore,
    UnsafeSnapshotPathError,
    default_snapshot_directory,
    save_snapshot,
)

KST = timezone(timedelta(hours=9))
QUERY_STARTED_AT = datetime(2026, 8, 29, 12, 0, 0, tzinfo=KST)
QUERY_COMPLETED_AT = datetime(2026, 8, 29, 12, 0, 1, 123456, tzinfo=KST)


def _snapshot() -> AccountSnapshot:
    return AccountSnapshot(
        account_number_masked="1234****-**",
        query_started_at=QUERY_STARTED_AT,
        query_completed_at=QUERY_COMPLETED_AT,
        summary=AccountSummary(
            deposit_total=Decimal("1234567.00"),
            securities_evaluation_amount=Decimal("750000"),
            purchase_amount_total=Decimal("700000"),
            evaluation_amount_total=Decimal("750000"),
            profit_loss_total=Decimal("50000"),
            total_assets=Decimal("1984567.00"),
            net_assets=Decimal("1984567.00"),
        ),
        positions=(
            AccountPosition(
                stock_code="005930",
                product_name="삼성전자",
                holding_quantity=Decimal("10"),
                sellable_quantity=Decimal("8"),
                purchase_amount=Decimal("700000"),
                evaluation_amount=Decimal("750000"),
                profit_loss=Decimal("50000"),
            ),
        ),
        zero_quantity_balances=(),
        evidence=SnapshotEvidence(
            pages=(
                ApiPageEvidence(
                    received_at=QUERY_COMPLETED_AT,
                    http_status=200,
                    tr_cont="",
                    ctx_area_fk100="",
                    ctx_area_nk100="",
                    rt_cd="0",
                    msg_cd="MCA00000",
                    msg1="정상처리 되었습니다.",
                    response_body_sha256="a" * 64,
                    output1=(
                        RawEvidenceRecord(fields=(RawEvidenceField(name="pdno", value="005930"),)),
                    ),
                ),
            )
        ),
    )


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat(follow_symlinks=False).st_mode)


def test_save_snapshot_writes_utf8_private_decimal_string_json(tmp_path: Path) -> None:
    directory = tmp_path / "snapshots"

    saved_path = save_snapshot(_snapshot(), directory)

    assert saved_path.parent == directory
    assert saved_path.exists()
    assert _mode(directory) == 0o700
    assert _mode(saved_path) == 0o600
    assert re.fullmatch(
        r"account_snapshot_20260829T120001123456\+0900_[0-9a-f]{16}\.json",
        saved_path.name,
    )

    serialized = saved_path.read_text(encoding="utf-8")
    payload = json.loads(serialized)
    assert "삼성전자" in serialized
    assert payload["provider"] == "korea_investment_securities"
    assert payload["currency"] == "KRW"
    assert payload["summary"]["deposit_total"] == "1234567.00"
    assert payload["summary"]["orderable_cash"] is None
    assert payload["summary"]["total_assets"] == "1984567.00"
    assert payload["positions"][0]["holding_quantity"] == "10"
    assert "cash" not in payload["summary"]
    assert "available_cash" not in payload["summary"]
    assert "12345678-01" not in serialized
    assert "authorization" not in serialized.lower()
    assert "access_token" not in serialized.lower()


def test_temporary_file_is_private_from_the_time_it_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed_modes: list[int] = []
    original_write_payload = snapshot_storage._write_payload

    def capture_mode(descriptor: int, payload: bytes) -> None:
        observed_modes.append(stat.S_IMODE(os.fstat(descriptor).st_mode))
        original_write_payload(descriptor, payload)

    monkeypatch.setattr(snapshot_storage, "_write_payload", capture_mode)

    saved_path = save_snapshot(_snapshot(), tmp_path / "snapshots")

    assert observed_modes == [0o600]
    assert _mode(saved_path) == 0o600


def test_existing_snapshot_is_never_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(snapshot_storage, "_random_identifier", lambda: "fixedidentifier")
    directory = tmp_path / "snapshots"
    saved_path = save_snapshot(_snapshot(), directory)
    original_bytes = saved_path.read_bytes()

    with pytest.raises(SnapshotAlreadyExistsError, match="refusing to overwrite"):
        save_snapshot(_snapshot(), directory)

    assert saved_path.read_bytes() == original_bytes
    assert list(directory.glob("*.json")) == [saved_path]
    assert not list(directory.glob("*.tmp"))


def test_snapshot_directory_symbolic_link_is_rejected(tmp_path: Path) -> None:
    real_directory = tmp_path / "real-snapshots"
    real_directory.mkdir(mode=0o700)
    linked_directory = tmp_path / "linked-snapshots"
    linked_directory.symlink_to(real_directory, target_is_directory=True)

    with pytest.raises(UnsafeSnapshotPathError, match="symbolic links"):
        save_snapshot(_snapshot(), linked_directory)

    assert not list(real_directory.iterdir())


def test_existing_target_symbolic_link_is_not_followed_or_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(snapshot_storage, "_random_identifier", lambda: "fixedidentifier")
    directory = tmp_path / "snapshots"
    directory.mkdir(mode=0o700)
    victim = tmp_path / "victim.json"
    victim.write_text("do not modify", encoding="utf-8")
    final_path = directory / ("account_snapshot_20260829T120001123456+0900_fixedidentifier.json")
    final_path.symlink_to(victim)

    with pytest.raises(SnapshotAlreadyExistsError):
        save_snapshot(_snapshot(), directory)

    assert final_path.is_symlink()
    assert victim.read_text(encoding="utf-8") == "do not modify"
    assert not list(directory.glob("*.tmp"))


def test_write_failure_leaves_no_temporary_or_final_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "snapshots"

    def fail_write(_descriptor: int, _payload: bytes) -> None:
        raise OSError("synthetic write failure")

    monkeypatch.setattr(snapshot_storage, "_write_payload", fail_write)

    with pytest.raises(SnapshotStorageError, match="could not safely store"):
        save_snapshot(_snapshot(), directory)

    assert directory.exists()
    assert not list(directory.iterdir())


def test_keyboard_interrupt_leaves_no_temporary_or_final_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "snapshots"

    def interrupt_write(_descriptor: int, _payload: bytes) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(snapshot_storage, "_write_payload", interrupt_write)

    with pytest.raises(KeyboardInterrupt):
        save_snapshot(_snapshot(), directory)

    assert directory.exists()
    assert not list(directory.iterdir())


def test_existing_insecure_snapshot_directory_is_rejected(tmp_path: Path) -> None:
    directory = tmp_path / "snapshots"
    directory.mkdir(mode=0o700)
    directory.chmod(0o755)

    with pytest.raises(UnsafeSnapshotPathError, match="mode 0700"):
        save_snapshot(_snapshot(), directory)

    assert not list(directory.iterdir())


def test_default_store_uses_fixed_home_data_path_and_private_application_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_home = tmp_path / "home"
    shared_data_directory = fake_home / ".local" / "share"
    shared_data_directory.mkdir(mode=0o755, parents=True)
    shared_data_directory.chmod(0o755)
    working_directory = tmp_path / "working-directory"
    working_directory.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    monkeypatch.chdir(working_directory)

    saved_path = SnapshotStore().save(_snapshot())

    expected_directory = fake_home / ".local" / "share" / "phalanx" / "snapshots"
    assert default_snapshot_directory() == expected_directory
    assert saved_path.parent == expected_directory
    assert _mode(shared_data_directory) == 0o755
    assert _mode(expected_directory.parent) == 0o700
    assert _mode(expected_directory) == 0o700
    assert _mode(saved_path) == 0o600
    assert not (working_directory / "runtime").exists()
    assert not (tmp_path / "xdg-data").exists()


def test_injected_store_path_never_resolves_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_home(cls: type[Path]) -> Path:
        raise AssertionError("Path.home must not be called for an injected snapshot directory")

    monkeypatch.setattr(Path, "home", classmethod(fail_home))
    directory = tmp_path / "injected-snapshots"

    saved_path = SnapshotStore(directory).save(_snapshot())

    assert saved_path.parent == directory
    assert _mode(directory) == 0o700
    assert _mode(saved_path) == 0o600


@pytest.mark.parametrize("linked_directory", ("phalanx", "snapshots"))
def test_default_store_rejects_application_directory_symbolic_links(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    linked_directory: str,
) -> None:
    fake_home = tmp_path / "home"
    shared_data_directory = fake_home / ".local" / "share"
    shared_data_directory.mkdir(mode=0o755, parents=True)
    actual_directory = tmp_path / "actual-directory"
    actual_directory.mkdir(mode=0o700)
    phalanx_directory = shared_data_directory / "phalanx"
    if linked_directory == "phalanx":
        phalanx_directory.symlink_to(actual_directory, target_is_directory=True)
    else:
        phalanx_directory.mkdir(mode=0o700)
        (phalanx_directory / "snapshots").symlink_to(
            actual_directory,
            target_is_directory=True,
        )
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    with pytest.raises(UnsafeSnapshotPathError, match="symbolic links"):
        SnapshotStore().save(_snapshot())

    assert not list(actual_directory.iterdir())


@pytest.mark.parametrize("unsafe_directory", ("phalanx", "snapshots"))
def test_default_store_does_not_repair_application_directory_permissions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unsafe_directory: str,
) -> None:
    fake_home = tmp_path / "home"
    shared_data_directory = fake_home / ".local" / "share"
    shared_data_directory.mkdir(mode=0o755, parents=True)
    phalanx_directory = shared_data_directory / "phalanx"
    phalanx_directory.mkdir(mode=0o755 if unsafe_directory == "phalanx" else 0o700)
    checked_directory = phalanx_directory
    if unsafe_directory == "snapshots":
        checked_directory = phalanx_directory / "snapshots"
        checked_directory.mkdir(mode=0o755)
    checked_directory.chmod(0o755)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    with pytest.raises(UnsafeSnapshotPathError, match="mode 0700"):
        SnapshotStore().save(_snapshot())

    assert _mode(checked_directory) == 0o755
    if unsafe_directory == "phalanx":
        assert not (phalanx_directory / "snapshots").exists()


def test_snapshot_store_rejects_directory_owned_by_another_user(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "snapshots"
    directory.mkdir(mode=0o700)
    monkeypatch.setattr(snapshot_storage.os, "geteuid", lambda: os.getuid() + 1)

    with pytest.raises(UnsafeSnapshotPathError, match="owned by the current user"):
        SnapshotStore(directory).save(_snapshot())

    assert not list(directory.iterdir())
