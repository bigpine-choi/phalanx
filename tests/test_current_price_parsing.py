from __future__ import annotations

import traceback
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from phalanx.domain import CurrentPriceMarket, CurrentPriceObservation
from phalanx.kis.errors import (
    InvalidMarketDataNumericFieldError,
    InvalidMarketDataResponseStructure,
    MarketDataDomainInvariantError,
    MissingMarketDataFieldError,
)
from phalanx.kis.market_data_parsing import parse_current_price_observation

SEOUL = ZoneInfo("Asia/Seoul")
STARTED_AT = datetime(2026, 9, 3, 9, 0, 0, tzinfo=SEOUL)
RECEIVED_AT = STARTED_AT + timedelta(milliseconds=125)


def _payload(
    *,
    stock_code: object = "005930",
    current_price: object = "70000.10",
    **output_extras: object,
) -> dict[str, object]:
    return {
        "rt_cd": "0",
        "msg_cd": "SYNTHETIC_SUCCESS",
        "msg1": "synthetic success",
        "output": {
            "stck_shrn_iscd": stock_code,
            "stck_prpr": current_price,
            **output_extras,
        },
    }


def _parse(payload: object) -> CurrentPriceObservation:
    return parse_current_price_observation(
        payload,
        stock_code="005930",
        market=CurrentPriceMarket.KRX,
        request_started_at=STARTED_AT,
        received_at=RECEIVED_AT,
    )


def _exception_surfaces(error: BaseException) -> str:
    return "\n".join(
        (
            str(error),
            repr(error),
            repr(error.args),
            *getattr(error, "__notes__", ()),
            *traceback.format_exception(error),
        )
    )


def test_parser_builds_exact_immutable_observation_without_mutating_payload() -> None:
    payload = {
        "rt_cd": "0",
        "msg_cd": "SYNTHETIC_SUCCESS",
        "msg1": "synthetic success",
        "output": {
            "iscd_stat_cls_code": "55",
            "rprs_mrkt_kor_name": "KOSPI",
            "temp_stop_yn": "N",
            "stck_prpr": "00070000.10",
            "prdy_vrss": "100",
            "prdy_ctrt": "0.14",
            "acml_tr_pbmn": "1234567890",
            "acml_vol": "987654",
            "stck_oprc": "69900",
            "stck_hgpr": "70500",
            "stck_lwpr": "69500",
            "stck_shrn_iscd": "005930",
            "vi_cls_code": "N",
            "ovtm_vi_cls_code": "N",
        },
    }
    original = deepcopy(payload)

    observation = _parse(payload)

    assert payload == original
    assert observation.stock_code == "005930"
    assert observation.current_price == Decimal("00070000.10")
    assert observation.current_price.as_tuple().exponent == -2
    assert observation.market is CurrentPriceMarket.KRX
    assert observation.request_started_at == STARTED_AT
    assert observation.received_at == RECEIVED_AT
    with pytest.raises(ValidationError, match="frozen"):
        observation.current_price = Decimal("1")


@pytest.mark.parametrize(
    ("payload", "field_name", "location"),
    (
        ({"rt_cd": "0", "msg_cd": "OK", "msg1": "ok"}, "output", "response"),
        (
            {"rt_cd": "0", "msg_cd": "OK", "msg1": "ok", "output": None},
            "output",
            "response",
        ),
        (_payload(stock_code=None), "stck_shrn_iscd", "output"),
        (_payload(stock_code=""), "stck_shrn_iscd", "output"),
        (_payload(current_price=None), "stck_prpr", "output"),
        (_payload(current_price=" "), "stck_prpr", "output"),
    ),
)
def test_parser_reports_missing_null_or_blank_contract_fields(
    payload: object,
    field_name: str,
    location: str,
) -> None:
    with pytest.raises(MissingMarketDataFieldError) as captured:
        _parse(payload)

    assert captured.value.field_name == field_name
    assert captured.value.location == location


@pytest.mark.parametrize(
    "payload",
    (
        [],
        {"rt_cd": "0", "msg_cd": "OK", "msg1": "ok", "output": []},
        {"rt_cd": "0", "msg_cd": "OK", "msg1": "ok", "output": {1: "bad"}},
        _payload(stock_code=5930),
    ),
)
def test_parser_rejects_invalid_response_structures(payload: object) -> None:
    with pytest.raises(InvalidMarketDataResponseStructure):
        _parse(payload)


def test_parser_rejects_response_stock_code_mismatch() -> None:
    with pytest.raises(InvalidMarketDataResponseStructure, match="exactly match"):
        _parse(_payload(stock_code="000660"))


@pytest.mark.parametrize(
    "value",
    (
        70000,
        True,
        "",
        " 70000",
        "70000 ",
        "+70000",
        "-70000",
        ".5",
        "1.",
        "70,000",
        "7e4",
        "NaN",
        "Infinity",
    ),
)
def test_parser_rejects_non_contract_current_price_values(value: object) -> None:
    with pytest.raises(
        (InvalidMarketDataNumericFieldError, MissingMarketDataFieldError)
    ) as captured:
        _parse(_payload(current_price=value))

    assert captured.value.field_name == "stck_prpr"
    assert captured.value.location == "output"


def test_parser_maps_zero_price_to_domain_invariant_error() -> None:
    with pytest.raises(MarketDataDomainInvariantError, match="CurrentPriceObservation"):
        _parse(_payload(current_price="0.00"))


def test_parser_operational_error_does_not_retain_raw_rejected_input() -> None:
    raw_secret = "synthetic-invalid-current-price-secret"

    with pytest.raises(InvalidMarketDataNumericFieldError) as captured:
        _parse(_payload(current_price=raw_secret))

    assert raw_secret not in _exception_surfaces(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


@pytest.mark.parametrize(
    ("started_at", "received_at"),
    (
        (STARTED_AT.replace(tzinfo=None), RECEIVED_AT),
        (STARTED_AT, RECEIVED_AT.replace(tzinfo=None)),
        (RECEIVED_AT, STARTED_AT),
    ),
)
def test_parser_maps_invalid_observation_timestamps_to_domain_error(
    started_at: datetime,
    received_at: datetime,
) -> None:
    with pytest.raises(MarketDataDomainInvariantError):
        parse_current_price_observation(
            _payload(),
            stock_code="005930",
            market=CurrentPriceMarket.KRX,
            request_started_at=started_at,
            received_at=received_at,
        )


def test_parser_reads_only_output_contract_and_discards_unknown_raw_fields() -> None:
    secret = "synthetic-sensitive-value"
    payload = {
        "not_an_envelope": f"ignored {secret}",
        "output": {
            "stck_shrn_iscd": "005930",
            "stck_prpr": "70000",
            "authorization": f"Bearer {secret}",
            "nested": {"appsecret": secret},
        },
    }

    observation = parse_current_price_observation(
        payload,
        stock_code="005930",
        market=CurrentPriceMarket.KRX,
        request_started_at=STARTED_AT,
        received_at=RECEIVED_AT,
    )

    displayed = observation.model_dump_json() + repr(observation)
    assert secret not in displayed
