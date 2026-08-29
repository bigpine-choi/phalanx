"""Strict, side-effect-free parsing for one KIS domestic balance response page."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, ValidationError

from phalanx.domain import AccountPosition, AccountSummary, RawEvidenceField, RawEvidenceRecord
from phalanx.kis.errors import (
    BalanceDomainInvariantError,
    InvalidNumericField,
    InvalidResponseStructure,
    KisApiResponseError,
    MissingRequiredNumericField,
)

_POSITION_NUMERIC_FIELDS = (
    "hldg_qty",
    "ord_psbl_qty",
    "pchs_amt",
    "evlu_amt",
    "evlu_pfls_amt",
)
_SUMMARY_NUMERIC_FIELDS = {
    "deposit_total": "dnca_tot_amt",
    "securities_evaluation_amount": "scts_evlu_amt",
    "purchase_amount_total": "pchs_amt_smtl_amt",
    "evaluation_amount_total": "evlu_amt_smtl_amt",
    "profit_loss_total": "evlu_pfls_smtl_amt",
    "total_assets": "tot_evlu_amt",
    "net_assets": "nass_amt",
}
_DECIMAL_PATTERN = re.compile(r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)$")
_SENSITIVE_FIELD_NAMES = frozenset(
    {
        "authorization",
        "appkey",
        "appsecret",
        "accesstoken",
        "token",
        "accountnumber",
        "accountno",
        "cano",
        "acntprdtcd",
    }
)
_REDACTED = "[REDACTED]"


class ParsedBalancePage(BaseModel):
    """Deeply immutable normalized values and sanitized evidence for one page."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    positions: tuple[AccountPosition, ...]
    zero_quantity_balances: tuple[AccountPosition, ...]
    summary: AccountSummary
    raw_output1: tuple[RawEvidenceRecord, ...]
    raw_output2: tuple[RawEvidenceRecord, ...]
    placeholder_rows: tuple[RawEvidenceRecord, ...]
    raw_top_level: RawEvidenceRecord
    rt_cd: str
    msg_cd: str
    msg1: str
    ctx_area_fk100: str
    ctx_area_nk100: str


def parse_balance_page(
    payload: object,
    *,
    sensitive_values: Iterable[str] = (),
) -> ParsedBalancePage:
    """Validate and normalize one already-decoded KIS balance response body."""

    secrets = _normalize_sensitive_values(sensitive_values)
    response = _require_object(payload, "response")
    rt_cd = _require_string(response, "rt_cd", "response", secrets=secrets)
    msg_cd = _require_string(response, "msg_cd", "response", secrets=secrets)
    msg1 = _require_string(
        response,
        "msg1",
        "response",
        allow_blank=True,
        secrets=secrets,
    )
    if rt_cd != "0":
        raise KisApiResponseError(rt_cd=rt_cd, msg_cd=msg_cd, msg1=msg1)

    ctx_area_fk100 = _require_string(
        response,
        "ctx_area_fk100",
        "response",
        allow_blank=True,
        secrets=secrets,
    )
    ctx_area_nk100 = _require_string(
        response,
        "ctx_area_nk100",
        "response",
        allow_blank=True,
        secrets=secrets,
    )
    output1 = _require_record_list(response.get("output1"), "output1")
    output2 = _require_record_list(response.get("output2"), "output2")
    if len(output2) != 1:
        raise InvalidResponseStructure("output2 must contain exactly one account summary record.")

    positions: list[AccountPosition] = []
    zero_quantity_balances: list[AccountPosition] = []
    raw_output1: list[RawEvidenceRecord] = []
    placeholder_rows: list[RawEvidenceRecord] = []
    for index, row in enumerate(output1):
        location = f"output1[{index}]"
        raw_row = _raw_evidence_record(row, secrets)
        raw_output1.append(raw_row)
        stock_code, product_name, is_placeholder = _classify_row(
            row,
            location,
            secrets,
        )
        if is_placeholder:
            placeholder_rows.append(raw_row)
            continue

        values = {
            field_name: _parse_required_decimal(row, field_name, location)
            for field_name in _POSITION_NUMERIC_FIELDS
        }
        try:
            position = AccountPosition(
                stock_code=stock_code,
                product_name=product_name,
                holding_quantity=values["hldg_qty"],
                sellable_quantity=values["ord_psbl_qty"],
                purchase_amount=values["pchs_amt"],
                evaluation_amount=values["evlu_amt"],
                profit_loss=values["evlu_pfls_amt"],
            )
        except ValidationError:
            raise BalanceDomainInvariantError(
                f"KIS balance values violate account position invariants at {location}."
            ) from None

        if position.holding_quantity > 0:
            positions.append(position)
        else:
            zero_quantity_balances.append(position)

    summary_row = output2[0]
    summary_values = {
        model_field: _parse_required_decimal(summary_row, kis_field, "output2[0]")
        for model_field, kis_field in _SUMMARY_NUMERIC_FIELDS.items()
    }
    try:
        summary = AccountSummary(
            deposit_total=summary_values["deposit_total"],
            orderable_cash=None,
            securities_evaluation_amount=summary_values["securities_evaluation_amount"],
            purchase_amount_total=summary_values["purchase_amount_total"],
            evaluation_amount_total=summary_values["evaluation_amount_total"],
            profit_loss_total=summary_values["profit_loss_total"],
            total_assets=summary_values["total_assets"],
            net_assets=summary_values["net_assets"],
        )
    except ValidationError:
        raise BalanceDomainInvariantError(
            "KIS balance values violate account summary invariants at output2[0]."
        ) from None

    top_level_fields = {
        key: value for key, value in response.items() if key not in {"output1", "output2"}
    }
    return ParsedBalancePage(
        positions=tuple(positions),
        zero_quantity_balances=tuple(zero_quantity_balances),
        summary=summary,
        raw_output1=tuple(raw_output1),
        raw_output2=(_raw_evidence_record(summary_row, secrets),),
        placeholder_rows=tuple(placeholder_rows),
        raw_top_level=_raw_evidence_record(top_level_fields, secrets),
        rt_cd=rt_cd,
        msg_cd=msg_cd,
        msg1=msg1,
        ctx_area_fk100=ctx_area_fk100,
        ctx_area_nk100=ctx_area_nk100,
    )


def parse_optional_decimal(value: object, *, field_name: str) -> Decimal | None:
    """Parse an optional KIS decimal string, preserving an empty value as None."""

    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return _parse_decimal_value(value, field_name, "optional field")


def _parse_required_decimal(
    record: Mapping[str, Any],
    field_name: str,
    location: str,
) -> Decimal:
    if field_name not in record:
        raise MissingRequiredNumericField(field_name, location)
    value = record[field_name]
    if value is None or (isinstance(value, str) and not value.strip()):
        raise MissingRequiredNumericField(field_name, location)
    return _parse_decimal_value(value, field_name, location)


def _parse_decimal_value(value: object, field_name: str, location: str) -> Decimal:
    if not isinstance(value, str) or _DECIMAL_PATTERN.fullmatch(value) is None:
        raise InvalidNumericField(field_name, location)
    return Decimal(value)


def _classify_row(
    row: Mapping[str, Any],
    location: str,
    secrets: tuple[str, ...],
) -> tuple[str, str, bool]:
    stock_code = _require_string(
        row,
        "pdno",
        location,
        allow_blank=True,
        secrets=secrets,
    )
    product_name = _require_string(
        row,
        "prdt_name",
        location,
        allow_blank=True,
        secrets=secrets,
    )
    if stock_code.strip():
        if not product_name.strip():
            raise InvalidResponseStructure(
                f"prdt_name must be non-empty when pdno is present at {location}."
            )
        return stock_code, product_name, False

    if product_name.strip():
        raise InvalidResponseStructure(f"A blank pdno row contains a product name at {location}.")

    for field_name in _POSITION_NUMERIC_FIELDS:
        if field_name not in row:
            raise InvalidResponseStructure(
                f"Placeholder row is missing {field_name} at {location}."
            )
        value = row[field_name]
        if isinstance(value, str) and not value.strip():
            continue
        number = _parse_required_decimal(row, field_name, location)
        if number != 0:
            raise InvalidResponseStructure(
                f"A blank pdno row contains a non-zero balance at {location}."
            )
    return stock_code, product_name, True


def _require_object(value: object, location: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise InvalidResponseStructure(f"{location} must be a JSON object.")
    return cast(dict[str, Any], value)


def _require_record_list(value: object, location: str) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        raise InvalidResponseStructure(f"{location} must be a JSON array.")
    return tuple(_require_object(item, f"{location}[{index}]") for index, item in enumerate(value))


def _require_string(
    record: Mapping[str, Any],
    field_name: str,
    location: str,
    *,
    allow_blank: bool = False,
    secrets: tuple[str, ...],
) -> str:
    if field_name not in record or not isinstance(record[field_name], str):
        raise InvalidResponseStructure(f"{field_name} must be a string at {location}.")
    value = cast(str, record[field_name])
    if not allow_blank and not value.strip():
        raise InvalidResponseStructure(f"{field_name} must be non-empty at {location}.")
    return _mask_text(value, secrets)


def _raw_evidence_record(
    record: Mapping[str, Any],
    secrets: tuple[str, ...],
) -> RawEvidenceRecord:
    fields: list[RawEvidenceField] = []
    seen_names: set[str] = set()
    for name, value in record.items():
        stripped_name = name.strip()
        if (
            not stripped_name
            or len(stripped_name) > 100
            or stripped_name in seen_names
            or _is_sensitive_field_name(stripped_name)
        ):
            continue
        seen_names.add(stripped_name)
        fields.append(
            RawEvidenceField(
                name=stripped_name,
                value=_evidence_value(value, secrets),
            )
        )
    return RawEvidenceRecord(fields=tuple(fields))


def _evidence_value(value: object, secrets: tuple[str, ...]) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return _mask_text(value, secrets)
    sanitized = _sanitize_nested_value(value, secrets)
    try:
        return json.dumps(
            sanitized,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
    except (TypeError, ValueError):
        return _mask_text(str(sanitized), secrets)


def _sanitize_nested_value(value: object, secrets: tuple[str, ...]) -> object:
    if isinstance(value, str):
        return _mask_text(value, secrets)
    if isinstance(value, dict):
        return {
            key: _sanitize_nested_value(item, secrets)
            for key, item in value.items()
            if isinstance(key, str) and not _is_sensitive_field_name(key)
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_nested_value(item, secrets) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _mask_text(str(value), secrets)


def _is_sensitive_field_name(field_name: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", field_name.lower())
    return normalized in _SENSITIVE_FIELD_NAMES


def _normalize_sensitive_values(sensitive_values: Iterable[str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {value for value in sensitive_values if isinstance(value, str) and value},
            key=len,
            reverse=True,
        )
    )


def _mask_text(value: str, secrets: tuple[str, ...]) -> str:
    masked = value
    for secret in secrets:
        masked = masked.replace(secret, _REDACTED)
    return masked


__all__ = [
    "ParsedBalancePage",
    "parse_balance_page",
    "parse_optional_decimal",
]
