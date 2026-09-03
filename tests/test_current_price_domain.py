from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

import phalanx.domain.market_data as market_data_domain
from phalanx.domain import (
    CurrentPriceMarket,
    CurrentPriceObservation,
    ValuationPriceBundle,
)

STARTED = datetime(2026, 9, 3, 1, 2, 3, tzinfo=UTC)


def _observation(
    stock_code: str = "005930",
    *,
    price: Decimal = Decimal("71000.40"),
    market: CurrentPriceMarket = CurrentPriceMarket.KRX,
    request_started_at: datetime = STARTED,
    received_at: datetime = STARTED + timedelta(milliseconds=250),
) -> CurrentPriceObservation:
    return CurrentPriceObservation(
        stock_code=stock_code,
        current_price=price,
        market=market,
        request_started_at=request_started_at,
        received_at=received_at,
    )


def _bundle(
    observations: tuple[CurrentPriceObservation, ...] | None = None,
    *,
    stock_codes: tuple[str, ...] | None = None,
) -> ValuationPriceBundle:
    selected = (
        (
            _observation("005930"),
            _observation(
                "000660",
                price=Decimal("201000"),
                request_started_at=STARTED + timedelta(seconds=1),
                received_at=STARTED + timedelta(seconds=1, milliseconds=300),
            ),
        )
        if observations is None
        else observations
    )
    return ValuationPriceBundle(
        stock_codes=tuple(observation.stock_code for observation in selected)
        if stock_codes is None
        else stock_codes,
        observations=selected,
        currency="KRW",
    )


def test_current_price_public_contract_has_exact_fields_and_closed_markets() -> None:
    assert tuple(CurrentPriceObservation.model_fields) == (
        "stock_code",
        "current_price",
        "market",
        "request_started_at",
        "received_at",
    )
    assert tuple(ValuationPriceBundle.model_fields) == (
        "stock_codes",
        "observations",
        "currency",
    )
    assert {
        name for name, value in vars(ValuationPriceBundle).items() if isinstance(value, property)
    } == {
        "acquisition_span",
        "market",
        "received_at",
        "request_started_at",
        "valuation_prices",
    }
    assert tuple(CurrentPriceMarket) == (
        CurrentPriceMarket.KRX,
        CurrentPriceMarket.NXT,
        CurrentPriceMarket.INTEGRATED,
    )
    assert {
        "CurrentPriceMarket",
        "CurrentPriceObservation",
        "DailyBar",
        "PositivePrice",
        "ValuationPriceBundle",
    } <= set(market_data_domain.__all__)
    assert {"BuyingPowerQuote", "ProposedTrade", "RebalanceProposal"}.isdisjoint(
        market_data_domain.__all__
    )
    assert "provider_timestamp" not in CurrentPriceObservation.model_fields


def test_observation_preserves_exact_decimal_is_immutable_and_rejects_extras() -> None:
    observation = _observation()

    assert observation.current_price == Decimal("71000.40")
    assert observation.market is CurrentPriceMarket.KRX
    assert observation.request_started_at == STARTED
    assert observation.received_at == STARTED + timedelta(milliseconds=250)
    payload = json.loads(observation.model_dump_json())
    assert payload["current_price"] == "71000.40"
    assert set(payload) == {
        "stock_code",
        "current_price",
        "market",
        "request_started_at",
        "received_at",
    }

    with pytest.raises(ValidationError):
        observation.current_price = Decimal("1")
    with pytest.raises(ValidationError):
        CurrentPriceObservation(
            **observation.model_dump(),
            authorization="secret",
        )


def test_direct_validation_hides_input_only_from_human_readable_text() -> None:
    raw_secret = "synthetic-raw-secret-current-price"

    with pytest.raises(ValidationError) as captured:
        CurrentPriceObservation(
            stock_code="005930",
            current_price=raw_secret,
            market=CurrentPriceMarket.KRX,
            request_started_at=STARTED,
            received_at=STARTED,
        )

    assert raw_secret not in str(captured.value)
    for model_type in (CurrentPriceObservation, ValuationPriceBundle):
        documentation = model_type.__doc__ or ""
        assert "structured Pydantic validation details are not safe operational errors" in (
            " ".join(documentation.split())
        )
        assert "model_construct" in documentation


@pytest.mark.parametrize(
    "update",
    (
        {"current_price": Decimal("-1")},
        {"stock_code": "000660"},
        {"market": CurrentPriceMarket.NXT},
        {"received_at": STARTED + timedelta(seconds=1)},
    ),
)
def test_observation_model_copy_rejects_every_nonempty_update(
    update: dict[str, object],
) -> None:
    with pytest.raises(TypeError, match="model_copy updates are unsupported"):
        _observation().model_copy(update=update)


@pytest.mark.parametrize("deep", (False, True))
def test_observation_model_copy_without_updates_preserves_valid_value(deep: bool) -> None:
    observation = _observation()

    copied = observation.model_copy(update={}, deep=deep)

    assert copied == observation
    assert copied is not observation
    with pytest.raises(ValidationError, match="frozen"):
        copied.current_price = Decimal("1")


@pytest.mark.parametrize(
    "stock_code",
    (
        "5930",
        "0005930",
        "005 930",
        " 005930",
        "005930 ",
        "\uff10\uff10\uff15\uff19\uff13\uff10",
        5930,
        True,
    ),
)
def test_observation_rejects_every_nonexact_stock_code(stock_code: object) -> None:
    with pytest.raises(ValidationError):
        CurrentPriceObservation(
            stock_code=stock_code,
            current_price=Decimal("1"),
            market=CurrentPriceMarket.KRX,
            request_started_at=STARTED,
            received_at=STARTED,
        )


@pytest.mark.parametrize(
    "price",
    (
        Decimal("0"),
        Decimal("-1"),
        Decimal("NaN"),
        Decimal("sNaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        1,
        1.0,
        True,
        "1",
    ),
)
def test_observation_requires_an_exact_positive_finite_decimal(price: object) -> None:
    with pytest.raises(ValidationError):
        CurrentPriceObservation(
            stock_code="005930",
            current_price=price,
            market=CurrentPriceMarket.KRX,
            request_started_at=STARTED,
            received_at=STARTED,
        )


@pytest.mark.parametrize("market", ("KRX", "J", "NXT", object()))
def test_observation_requires_an_exact_market_enum(market: object) -> None:
    with pytest.raises(ValidationError):
        CurrentPriceObservation(
            stock_code="005930",
            current_price=Decimal("1"),
            market=market,
            request_started_at=STARTED,
            received_at=STARTED,
        )


@pytest.mark.parametrize(
    ("started", "received"),
    (
        (datetime(2026, 9, 3), STARTED),
        (STARTED, datetime(2026, 9, 3)),
        ("2026-09-03T01:02:03Z", STARTED),
        (STARTED, STARTED - timedelta(microseconds=1)),
    ),
)
def test_observation_requires_aware_ordered_exact_datetimes(
    started: object,
    received: object,
) -> None:
    with pytest.raises(ValidationError):
        CurrentPriceObservation(
            stock_code="005930",
            current_price=Decimal("1"),
            market=CurrentPriceMarket.KRX,
            request_started_at=started,
            received_at=received,
        )


def test_observation_orders_dst_fold_timestamps_by_absolute_instant() -> None:
    new_york = ZoneInfo("America/New_York")
    valid_started = datetime(2026, 11, 1, 1, 45, tzinfo=new_york, fold=0)
    valid_received = datetime(2026, 11, 1, 1, 15, tzinfo=new_york, fold=1)

    observation = _observation(
        request_started_at=valid_started,
        received_at=valid_received,
    )

    assert observation.request_started_at is valid_started
    assert observation.received_at is valid_received
    assert observation.received_at.astimezone(UTC) > observation.request_started_at.astimezone(UTC)

    invalid_started = datetime(2026, 11, 1, 1, 30, tzinfo=new_york, fold=1)
    invalid_received = datetime(2026, 11, 1, 1, 45, tzinfo=new_york, fold=0)
    with pytest.raises(ValidationError, match="received_at"):
        _observation(
            request_started_at=invalid_started,
            received_at=invalid_received,
        )


def test_bundle_preserves_exact_order_and_exposes_only_derived_alignment_values() -> None:
    bundle = _bundle()

    assert bundle.stock_codes == ("005930", "000660")
    assert bundle.valuation_prices == (Decimal("71000.40"), Decimal("201000"))
    assert bundle.currency == "KRW"
    assert bundle.market is CurrentPriceMarket.KRX
    assert bundle.request_started_at == STARTED
    assert bundle.received_at == STARTED + timedelta(seconds=1, milliseconds=300)
    assert bundle.acquisition_span == timedelta(seconds=1, milliseconds=300)
    assert set(bundle.model_dump()) == {"stock_codes", "observations", "currency"}

    with pytest.raises(ValidationError):
        bundle.stock_codes = ("000660", "005930")
    with pytest.raises(ValidationError):
        bundle.observations[0].current_price = Decimal("2")


def test_bundle_derives_bounds_and_span_from_absolute_dst_fold_instants() -> None:
    new_york = ZoneInfo("America/New_York")
    first_started = datetime(2026, 11, 1, 1, 45, tzinfo=new_york, fold=0)
    first_received = datetime(2026, 11, 1, 1, 15, tzinfo=new_york, fold=1)
    second_started = datetime(2026, 11, 1, 1, 20, tzinfo=new_york, fold=1)
    second_received = datetime(2026, 11, 1, 1, 30, tzinfo=new_york, fold=1)
    bundle = _bundle(
        (
            _observation(
                "005930",
                request_started_at=first_started,
                received_at=first_received,
            ),
            _observation(
                "000660",
                request_started_at=second_started,
                received_at=second_received,
            ),
        )
    )

    assert bundle.request_started_at is first_started
    assert bundle.received_at is second_received
    assert bundle.acquisition_span == timedelta(minutes=45)


def test_bundle_derives_bounds_and_span_across_mixed_timezone_offsets() -> None:
    seoul = ZoneInfo("Asia/Seoul")
    new_york = ZoneInfo("America/New_York")
    first_started = datetime(2026, 9, 3, 9, 0, tzinfo=seoul)
    first_received = datetime(2026, 9, 3, 9, 5, tzinfo=seoul)
    second_started = datetime(2026, 9, 2, 20, 10, tzinfo=new_york)
    second_received = datetime(2026, 9, 2, 20, 20, tzinfo=new_york)
    bundle = _bundle(
        (
            _observation(
                "005930",
                request_started_at=first_started,
                received_at=first_received,
            ),
            _observation(
                "000660",
                request_started_at=second_started,
                received_at=second_received,
            ),
        )
    )

    assert bundle.request_started_at is first_started
    assert bundle.received_at is second_received
    assert bundle.acquisition_span == timedelta(minutes=20)


@pytest.mark.parametrize(
    "values",
    (
        {"stock_codes": (), "observations": ()},
        {
            "stock_codes": ("005930", "005930"),
            "observations": (_observation(), _observation()),
        },
        {"stock_codes": ("005930", "000660"), "observations": (_observation(),)},
        {
            "stock_codes": ("000660", "005930"),
            "observations": (_observation(), _observation("000660")),
        },
        {
            "stock_codes": ("005930", "000660"),
            "observations": (
                _observation(),
                _observation("000660", market=CurrentPriceMarket.NXT),
            ),
        },
    ),
)
def test_bundle_rejects_empty_duplicate_incomplete_reordered_or_mixed_market_values(
    values: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ValuationPriceBundle(**values, currency="KRW")


def test_bundle_requires_exact_immutable_containers_and_fixed_currency() -> None:
    observation = _observation()
    invalid_values = (
        {"stock_codes": ["005930"], "observations": (observation,), "currency": "KRW"},
        {"stock_codes": ("005930",), "observations": [observation], "currency": "KRW"},
        {"stock_codes": ("005930",), "observations": (observation,), "currency": "USD"},
    )

    for values in invalid_values:
        with pytest.raises(ValidationError):
            ValuationPriceBundle(**values)


@pytest.mark.parametrize(
    "update",
    (
        {"stock_codes": ("000660", "005930")},
        {"observations": (_observation(),)},
        {"observations": [_observation()]},
        {"currency": "USD"},
    ),
)
def test_bundle_model_copy_rejects_every_nonempty_update(
    update: dict[str, object],
) -> None:
    with pytest.raises(TypeError, match="model_copy updates are unsupported"):
        _bundle().model_copy(update=update)


@pytest.mark.parametrize("deep", (False, True))
def test_bundle_model_copy_without_updates_preserves_valid_value(deep: bool) -> None:
    bundle = _bundle()

    copied = bundle.model_copy(deep=deep)

    assert copied == bundle
    assert copied is not bundle
    assert type(copied.observations) is tuple
    with pytest.raises(ValidationError, match="frozen"):
        copied.currency = "USD"  # type: ignore[assignment]


def test_normal_validation_rejects_forged_models_and_nested_observations() -> None:
    forged_observation = CurrentPriceObservation.model_construct(
        stock_code="005930",
        current_price=Decimal("-1"),
        market=CurrentPriceMarket.KRX,
        request_started_at=STARTED,
        received_at=STARTED,
    )

    with pytest.raises(ValidationError):
        CurrentPriceObservation.model_validate(forged_observation)
    with pytest.raises(ValidationError):
        ValuationPriceBundle(
            stock_codes=("005930",),
            observations=(forged_observation,),
            currency="KRW",
        )

    forged_bundle = ValuationPriceBundle.model_construct(
        stock_codes=("005930",),
        observations=[_observation()],
        currency="USD",
    )
    with pytest.raises(ValidationError):
        ValuationPriceBundle.model_validate(forged_bundle)
