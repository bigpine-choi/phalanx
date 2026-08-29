from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from phalanx.domain import RawEvidenceRecord
from phalanx.kis.errors import (
    BalanceDomainInvariantError,
    InvalidNumericField,
    InvalidResponseStructure,
    KisApiResponseError,
    MissingRequiredNumericField,
)
from phalanx.kis.parsing import parse_balance_page, parse_optional_decimal

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "kis" / "balance_single_page.json"
MISSING = object()


def _payload() -> dict[str, Any]:
    loaded = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _fields(record: RawEvidenceRecord) -> dict[str, str | None]:
    return {field.name: field.value for field in record.fields}


def test_normal_single_page_is_normalized_with_exact_decimals() -> None:
    parsed = parse_balance_page(_payload())

    assert parsed.rt_cd == "0"
    assert parsed.msg_cd == "SYNTHETIC_SUCCESS"
    assert parsed.msg1 == "synthetic balance response"
    assert parsed.ctx_area_fk100 == "SYNTHETIC-FK-001"
    assert parsed.ctx_area_nk100 == "SYNTHETIC-NK-001"
    assert len(parsed.positions) == 1
    assert len(parsed.zero_quantity_balances) == 1
    assert len(parsed.placeholder_rows) == 1

    position = parsed.positions[0]
    assert position.stock_code == "TEST0001"
    assert position.holding_quantity == Decimal("2.5000")
    assert position.sellable_quantity == Decimal("1.2500")
    assert position.purchase_amount == Decimal("123456789012345678901234567890.1234")
    assert position.evaluation_amount == Decimal("123456789012345678901234567999.9999")
    assert position.profit_loss == Decimal("-109.8765")

    summary = parsed.summary
    assert summary.deposit_total == Decimal("-10.5000")
    assert summary.orderable_cash is None
    assert summary.securities_evaluation_amount == Decimal("123456789012345678901234567999.9999")
    assert summary.profit_loss_total == Decimal("-109.8765")
    assert summary.total_assets == Decimal("-42.125")
    assert summary.net_assets == Decimal("-1.500")


def test_placeholder_only_page_represents_an_empty_account() -> None:
    payload = _payload()
    payload["output1"] = [payload["output1"][2]]

    parsed = parse_balance_page(payload)

    assert parsed.positions == ()
    assert parsed.zero_quantity_balances == ()
    assert len(parsed.placeholder_rows) == 1
    assert len(parsed.raw_output1) == 1


def test_empty_output1_is_a_valid_empty_account_page() -> None:
    payload = _payload()
    payload["output1"] = []

    parsed = parse_balance_page(payload)

    assert parsed.positions == ()
    assert parsed.zero_quantity_balances == ()
    assert parsed.placeholder_rows == ()
    assert parsed.raw_output1 == ()


def test_zero_quantity_balance_is_separate_from_positive_positions() -> None:
    parsed = parse_balance_page(_payload())

    assert tuple(position.stock_code for position in parsed.positions) == ("TEST0001",)
    assert tuple(position.stock_code for position in parsed.zero_quantity_balances) == ("TEST0002",)
    assert parsed.zero_quantity_balances[0].holding_quantity == 0


@pytest.mark.parametrize("empty_value", (None, "", "   "))
def test_optional_decimal_preserves_empty_values_as_none(empty_value: object) -> None:
    assert parse_optional_decimal(empty_value, field_name="synthetic_optional") is None


def test_optional_decimal_parses_signed_fraction_without_float() -> None:
    assert parse_optional_decimal("+.000125", field_name="synthetic_optional") == Decimal(".000125")


@pytest.mark.parametrize(
    ("section", "field_name", "value"),
    (
        ("output1", "pchs_amt", MISSING),
        ("output1", "evlu_amt", ""),
        ("output1", "hldg_qty", "   "),
        ("output2", "dnca_tot_amt", MISSING),
        ("output2", "nass_amt", ""),
    ),
)
def test_required_numeric_fields_reject_missing_and_blank_values(
    section: str,
    field_name: str,
    value: object,
) -> None:
    payload = _payload()
    row_index = 0
    row = payload[section][row_index]
    if value is MISSING:
        row.pop(field_name)
    else:
        row[field_name] = value

    with pytest.raises(MissingRequiredNumericField) as error:
        parse_balance_page(payload)

    assert error.value.field_name == field_name
    assert error.value.location == f"{section}[0]"


@pytest.mark.parametrize(
    "invalid_value",
    ("1,000", "1e3", "1E3", "NaN", "Infinity", "-Infinity", True, 1, 1.5),
)
def test_numeric_fields_reject_non_decimal_strings_and_json_numbers(
    invalid_value: object,
) -> None:
    payload = _payload()
    payload["output1"][0]["hldg_qty"] = invalid_value

    with pytest.raises(InvalidNumericField) as error:
        parse_balance_page(payload)

    assert error.value.field_name == "hldg_qty"
    assert error.value.location == "output1[0]"
    assert str(error.value) == "Numeric field hldg_qty has an invalid format at output1[0]."


def test_summary_numeric_field_rejects_float() -> None:
    payload = _payload()
    payload["output2"][0]["tot_evlu_amt"] = 1.25

    with pytest.raises(InvalidNumericField) as error:
        parse_balance_page(payload)

    assert error.value.field_name == "tot_evlu_amt"


@pytest.mark.parametrize(
    ("product_name", "holding_quantity"),
    (("Corrupted Product", "0"), ("", "0.0001")),
)
def test_blank_product_code_with_meaningful_data_is_rejected(
    product_name: str,
    holding_quantity: str,
) -> None:
    payload = _payload()
    row = payload["output1"][0]
    row.update(
        {
            "pdno": "",
            "prdt_name": product_name,
            "hldg_qty": holding_quantity,
            "ord_psbl_qty": "0",
            "pchs_amt": "0",
            "evlu_amt": "0",
            "evlu_pfls_amt": "0",
        }
    )

    with pytest.raises(InvalidResponseStructure, match="blank pdno"):
        parse_balance_page(payload)


def test_product_code_with_blank_product_name_is_rejected() -> None:
    payload = _payload()
    payload["output1"][0]["prdt_name"] = "   "

    with pytest.raises(InvalidResponseStructure, match="prdt_name"):
        parse_balance_page(payload)


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    (
        ("output1", {}),
        ("output1", ["not-an-object"]),
        ("output2", {}),
        ("output2", []),
        ("output2", ["not-an-object"]),
    ),
)
def test_output_collections_require_documented_array_shapes(
    field_name: str,
    invalid_value: object,
) -> None:
    payload = _payload()
    payload[field_name] = invalid_value

    with pytest.raises(InvalidResponseStructure):
        parse_balance_page(payload)


def test_output2_rejects_multiple_summary_records() -> None:
    payload = _payload()
    payload["output2"].append(copy.deepcopy(payload["output2"][0]))

    with pytest.raises(InvalidResponseStructure, match="exactly one"):
        parse_balance_page(payload)


@pytest.mark.parametrize("invalid_payload", ([], "object", 1, None))
def test_top_level_response_must_be_a_json_object(invalid_payload: object) -> None:
    with pytest.raises(InvalidResponseStructure, match="JSON object"):
        parse_balance_page(invalid_payload)


@pytest.mark.parametrize("field_name", ("rt_cd", "msg_cd", "msg1", "ctx_area_fk100"))
def test_response_metadata_and_cursors_must_be_strings(field_name: str) -> None:
    payload = _payload()
    payload[field_name] = 1

    with pytest.raises(InvalidResponseStructure, match=field_name):
        parse_balance_page(payload)


def test_non_success_rt_cd_raises_sanitized_api_error_before_output_parsing() -> None:
    secret = "synthetic-sensitive-value"
    payload = {
        "rt_cd": "1",
        "msg_cd": "SYNTHETIC_ERROR",
        "msg1": f"rejected credential {secret}",
    }

    with pytest.raises(KisApiResponseError) as error:
        parse_balance_page(payload, sensitive_values=(secret,))

    assert error.value.rt_cd == "1"
    assert error.value.msg_cd == "SYNTHETIC_ERROR"
    assert error.value.msg1 == "rejected credential [REDACTED]"
    assert secret not in str(error.value)


def test_sensitive_values_and_sensitive_fields_are_removed_from_result() -> None:
    secret = "synthetic-sensitive-value"
    payload = _payload()
    payload["msg1"] = f"success for {secret}"
    payload["ctx_area_fk100"] = f"cursor-{secret}"
    payload["Authorization"] = f"Bearer {secret}"
    row = payload["output1"][0]
    row["app_key"] = secret
    row["safe_extra"] = f"prefix-{secret}-suffix"
    row["nested_extra"] = {
        "access_token": secret,
        "safe_note": f"nested-{secret}",
    }

    parsed = parse_balance_page(payload, sensitive_values=(secret,))

    row_evidence = _fields(parsed.raw_output1[0])
    top_evidence = _fields(parsed.raw_top_level)
    assert parsed.msg1 == "success for [REDACTED]"
    assert parsed.ctx_area_fk100 == "cursor-[REDACTED]"
    assert "app_key" not in row_evidence
    assert "Authorization" not in top_evidence
    assert row_evidence["safe_extra"] == "prefix-[REDACTED]-suffix"
    assert row_evidence["nested_extra"] == '{"safe_note":"nested-[REDACTED]"}'
    assert secret not in repr(parsed)


def test_unknown_fields_are_preserved_in_sanitized_raw_evidence() -> None:
    parsed = parse_balance_page(_payload())

    assert _fields(parsed.raw_output1[0])["synthetic_extra"] == "preserve-position-extra"
    assert _fields(parsed.raw_output2[0])["synthetic_summary_extra"] == (
        '{"count":1,"note":"preserve-summary-extra"}'
    )
    assert _fields(parsed.raw_top_level)["synthetic_top_level_extra"] == (
        '{"note":"preserve-top-level-extra"}'
    )


def test_parsed_page_and_evidence_are_deeply_immutable_copies() -> None:
    payload = _payload()
    parsed = parse_balance_page(payload)

    payload["output1"][0]["prdt_name"] = "mutated"
    payload["output1"][0]["synthetic_extra"] = "mutated"
    payload["output2"][0]["synthetic_summary_extra"]["note"] = "mutated"
    payload["synthetic_top_level_extra"]["note"] = "mutated"
    payload["output1"].clear()
    payload["output2"].clear()

    assert isinstance(parsed.positions, tuple)
    assert parsed.positions[0].product_name == "Synthetic Equity One"
    assert _fields(parsed.raw_output1[0])["synthetic_extra"] == "preserve-position-extra"
    assert "preserve-summary-extra" in _fields(parsed.raw_output2[0])["synthetic_summary_extra"]
    assert "preserve-top-level-extra" in _fields(parsed.raw_top_level)["synthetic_top_level_extra"]
    with pytest.raises(ValidationError):
        parsed.msg1 = "mutated"
    with pytest.raises(ValidationError):
        parsed.raw_output1[0].fields[0].value = "mutated"


@pytest.mark.parametrize(
    ("section", "field_name", "invalid_value"),
    (
        ("output1", "hldg_qty", "-1"),
        ("output1", "ord_psbl_qty", "999"),
        ("output1", "pchs_amt", "-1"),
        ("output1", "evlu_amt", "-1"),
        ("output2", "scts_evlu_amt", "-1"),
        ("output2", "pchs_amt_smtl_amt", "-1"),
    ),
)
def test_existing_domain_invariant_failures_are_converted_to_safe_parsing_errors(
    section: str,
    field_name: str,
    invalid_value: str,
) -> None:
    payload = _payload()
    payload[section][0][field_name] = invalid_value

    with pytest.raises(BalanceDomainInvariantError) as error:
        parse_balance_page(payload)

    assert invalid_value not in str(error.value)


def test_domain_error_does_not_expose_sensitive_product_text() -> None:
    secret = "synthetic-sensitive-value"
    payload = _payload()
    payload["output1"][0]["prdt_name"] = secret
    payload["output1"][0]["ord_psbl_qty"] = "999"

    with pytest.raises(BalanceDomainInvariantError) as error:
        parse_balance_page(payload, sensitive_values=(secret,))

    assert secret not in str(error.value)
    assert secret not in repr(error.value)


def test_parser_has_no_home_runtime_or_network_side_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_home(cls: type[Path]) -> Path:
        raise AssertionError("balance parser must not access the home directory")

    monkeypatch.setattr(Path, "home", classmethod(fail_home))
    monkeypatch.chdir(tmp_path)

    parsed = parse_balance_page(_payload())

    source = (ROOT / "src" / "phalanx" / "kis" / "parsing.py").read_text(encoding="utf-8")
    assert parsed.positions
    assert not (tmp_path / "runtime").exists()
    assert "httpx" not in source
    assert "requests" not in source
    assert "openapi.koreainvestment.com" not in source
