from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from phalanx.domain import (
    AccountPosition,
    AccountSnapshot,
    AccountSummary,
    ApiPageEvidence,
    RawEvidenceField,
    SnapshotEvidence,
)

KST = timezone(timedelta(hours=9))
QUERY_STARTED_AT = datetime(2026, 8, 29, 12, 0, 0, tzinfo=KST)
QUERY_COMPLETED_AT = datetime(2026, 8, 29, 12, 0, 1, 123456, tzinfo=KST)


def _position(stock_code: str = "005930", holding_quantity: str = "10") -> AccountPosition:
    quantity = Decimal(holding_quantity)
    return AccountPosition(
        stock_code=stock_code,
        product_name="삼성전자",
        holding_quantity=quantity,
        sellable_quantity=min(quantity, Decimal("8")),
        purchase_amount=Decimal("700000" if holding_quantity != "0" else "0"),
        evaluation_amount=Decimal("750000" if holding_quantity != "0" else "0"),
        profit_loss=Decimal("50000" if holding_quantity != "0" else "0"),
    )


def _summary(**updates: Any) -> AccountSummary:
    values: dict[str, Any] = {
        "deposit_total": Decimal("1234567"),
        "securities_evaluation_amount": Decimal("750000"),
        "purchase_amount_total": Decimal("700000"),
        "evaluation_amount_total": Decimal("750000"),
        "profit_loss_total": Decimal("50000"),
        "total_assets": Decimal("1984567"),
        "net_assets": Decimal("1984567"),
    }
    values.update(updates)
    return AccountSummary(**values)


def _evidence() -> SnapshotEvidence:
    return SnapshotEvidence(
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
                output1=(),
                output2=(),
                placeholder_rows=(),
            ),
        )
    )


def _snapshot(**updates: Any) -> AccountSnapshot:
    values: dict[str, Any] = {
        "account_number_masked": "1234****-**",
        "query_started_at": QUERY_STARTED_AT,
        "query_completed_at": QUERY_COMPLETED_AT,
        "summary": _summary(),
        "positions": (_position(),),
        "zero_quantity_balances": (_position("000660", "0"),),
        "evidence": _evidence(),
    }
    values.update(updates)
    return AccountSnapshot(**values)


def test_snapshot_uses_fixed_provider_currency_and_uncomputed_orderable_cash() -> None:
    snapshot = _snapshot()

    assert snapshot.provider == "korea_investment_securities"
    assert snapshot.currency == "KRW"
    assert snapshot.summary.deposit_total == Decimal("1234567")
    assert snapshot.summary.orderable_cash is None
    assert not hasattr(snapshot.summary, "cash")
    assert not hasattr(snapshot.summary, "available_cash")

    with pytest.raises(ValidationError):
        _summary(orderable_cash=Decimal("1234567"))
    with pytest.raises(ValidationError):
        _summary(cash=Decimal("1234567"))
    with pytest.raises(ValidationError):
        _snapshot(provider="another_provider")
    with pytest.raises(ValidationError):
        _snapshot(currency="USD")


def test_decimal_values_reject_float_and_serialize_as_json_strings() -> None:
    with pytest.raises(ValidationError):
        _summary(deposit_total=123.45)

    payload = json.loads(_snapshot().model_dump_json())

    assert payload["summary"]["deposit_total"] == "1234567"
    assert payload["summary"]["profit_loss_total"] == "50000"
    assert payload["summary"]["orderable_cash"] is None
    assert payload["positions"][0]["holding_quantity"] == "10"
    assert payload["positions"][0]["purchase_amount"] == "700000"
    assert payload["zero_quantity_balances"][0]["holding_quantity"] == "0"


@pytest.mark.parametrize("field_name", ("purchase_amount", "evaluation_amount"))
def test_position_purchase_and_evaluation_amounts_must_be_non_negative(
    field_name: str,
) -> None:
    values = _position().model_dump()
    values[field_name] = Decimal("-0.01")

    with pytest.raises(ValidationError):
        AccountPosition(**values)


@pytest.mark.parametrize(
    "field_name",
    (
        "securities_evaluation_amount",
        "purchase_amount_total",
        "evaluation_amount_total",
    ),
)
def test_summary_evaluation_and_purchase_amounts_must_be_non_negative(
    field_name: str,
) -> None:
    with pytest.raises(ValidationError):
        _summary(**{field_name: Decimal("-0.01")})


def test_sellable_quantity_must_not_exceed_holding_quantity() -> None:
    values = _position().model_dump()
    values["holding_quantity"] = Decimal("7")
    values["sellable_quantity"] = Decimal("8")

    with pytest.raises(ValidationError, match="must not exceed holding_quantity"):
        AccountPosition(**values)


def test_losses_and_negative_deposit_total_are_allowed() -> None:
    position_values = _position().model_dump()
    position_values["profit_loss"] = Decimal("-50000")

    position = AccountPosition(**position_values)
    summary = _summary(
        deposit_total=Decimal("-1234567"),
        profit_loss_total=Decimal("-50000"),
    )

    assert position.profit_loss == Decimal("-50000")
    assert summary.profit_loss_total == Decimal("-50000")
    assert summary.deposit_total == Decimal("-1234567")


def test_balance_collections_enforce_holding_quantity_invariants() -> None:
    with pytest.raises(ValidationError, match="positive holding quantities"):
        _snapshot(positions=(_position(holding_quantity="0"),))

    with pytest.raises(ValidationError, match="only zero holding quantities"):
        _snapshot(zero_quantity_balances=(_position("000660", "1"),))

    with pytest.raises(ValidationError):
        _position(holding_quantity="-1")
    with pytest.raises(ValidationError):
        AccountPosition(
            stock_code="005930",
            product_name="삼성전자",
            holding_quantity=Decimal("1"),
            sellable_quantity=Decimal("-1"),
            purchase_amount=Decimal("70000"),
            evaluation_amount=Decimal("75000"),
            profit_loss=Decimal("5000"),
        )


def test_stock_codes_must_be_unique_across_and_within_collections() -> None:
    with pytest.raises(ValidationError, match="both balance collections"):
        _snapshot(zero_quantity_balances=(_position("005930", "0"),))

    with pytest.raises(ValidationError, match="duplicate stock codes"):
        _snapshot(positions=(_position(), _position()))


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    (
        ("query_started_at", datetime(2026, 8, 29, 12, 0, 0)),
        ("query_completed_at", datetime(2026, 8, 29, 12, 0, 1)),
    ),
)
def test_query_timestamps_must_be_timezone_aware(field_name: str, field_value: datetime) -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        _snapshot(**{field_name: field_value})


def test_query_completion_must_not_precede_start() -> None:
    with pytest.raises(ValidationError, match="must not be earlier"):
        _snapshot(query_completed_at=QUERY_STARTED_AT - timedelta(microseconds=1))


@pytest.mark.parametrize(
    "masked_account",
    ("12345678-01", "1234****-01", "12345***-**", "1234****-***"),
)
def test_only_masked_account_number_format_is_accepted(masked_account: str) -> None:
    with pytest.raises(ValidationError):
        _snapshot(account_number_masked=masked_account)

    with pytest.raises(ValidationError):
        AccountSnapshot(
            account_number_masked="1234****-**",
            account_number="12345678-01",
            query_started_at=QUERY_STARTED_AT,
            query_completed_at=QUERY_COMPLETED_AT,
            summary=_summary(),
            evidence=_evidence(),
        )


def test_models_and_nested_collections_are_deeply_immutable() -> None:
    position_input: dict[str, Any] = {
        "stock_code": "005930",
        "product_name": "삼성전자",
        "holding_quantity": Decimal("10"),
        "sellable_quantity": Decimal("8"),
        "purchase_amount": Decimal("700000"),
        "evaluation_amount": Decimal("750000"),
        "profit_loss": Decimal("50000"),
    }
    raw_field_input = {"name": "pdno", "value": "005930"}
    raw_fields = [raw_field_input]
    output_records = [{"fields": raw_fields}]
    consistency_warnings = ["page summaries differed"]
    page_input: dict[str, Any] = {
        "received_at": QUERY_COMPLETED_AT,
        "http_status": 200,
        "tr_cont": "",
        "ctx_area_fk100": "",
        "ctx_area_nk100": "",
        "rt_cd": "0",
        "msg_cd": "MCA00000",
        "msg1": "정상처리 되었습니다.",
        "response_body_sha256": "a" * 64,
        "output1": output_records,
        "output2": [],
        "placeholder_rows": [],
    }
    pages = [page_input]
    positions = [position_input]

    snapshot = AccountSnapshot(
        account_number_masked="1234****-**",
        query_started_at=QUERY_STARTED_AT,
        query_completed_at=QUERY_COMPLETED_AT,
        summary=_summary(),
        positions=positions,
        zero_quantity_balances=(),
        evidence={"pages": pages, "summary_consistency_warnings": consistency_warnings},
    )

    position_input["product_name"] = "변경됨"
    raw_field_input["value"] = "000000"
    raw_fields.clear()
    output_records.clear()
    pages.clear()
    positions.clear()
    consistency_warnings.clear()

    assert isinstance(snapshot.positions, tuple)
    assert isinstance(snapshot.evidence.pages, tuple)
    assert isinstance(snapshot.evidence.pages[0].output1, tuple)
    assert isinstance(snapshot.evidence.pages[0].output1[0].fields, tuple)
    assert snapshot.positions[0].product_name == "삼성전자"
    assert snapshot.evidence.pages[0].output1[0].fields[0].value == "005930"
    assert snapshot.evidence.summary_consistency_warnings == ("page summaries differed",)

    with pytest.raises(ValidationError):
        snapshot.summary.deposit_total = Decimal("0")
    with pytest.raises(ValidationError):
        snapshot.evidence.pages[0].msg1 = "변경됨"


@pytest.mark.parametrize(
    "sensitive_name",
    ("Authorization", "appkey", "app_secret", "access-token", "CANO", "account_number"),
)
def test_evidence_rejects_sensitive_field_names(sensitive_name: str) -> None:
    with pytest.raises(ValidationError, match="sensitive fields"):
        RawEvidenceField(name=sensitive_name, value="must-not-be-stored")


def test_evidence_received_at_must_be_timezone_aware() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        ApiPageEvidence(
            received_at=datetime(2026, 8, 29, 12, 0, 1),
            http_status=200,
            tr_cont="",
            ctx_area_fk100="",
            ctx_area_nk100="",
            rt_cd="0",
            msg_cd="MCA00000",
            msg1="정상처리 되었습니다.",
            response_body_sha256="a" * 64,
        )
