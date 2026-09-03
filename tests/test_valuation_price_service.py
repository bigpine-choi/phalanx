from __future__ import annotations

import traceback
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

import phalanx.market_data.service as market_data_service
from phalanx.domain import (
    CurrentPriceMarket,
    CurrentPriceObservation,
    ValuationPriceBundle,
)
from phalanx.market_data.errors import (
    CurrentPriceObservationReadError,
    InvalidValuationPriceAcquisitionRecencyError,
    InvalidValuationPriceRequestError,
    UnsupportedCurrentPriceMarketError,
    ValuationPriceBundleAcquisitionTooOldError,
    ValuationPriceBundleCoherenceError,
)
from phalanx.market_data.service import (
    ValuationPriceService,
    validate_valuation_price_bundle_acquisition_recency,
)

STARTED = datetime(2026, 9, 3, 1, 0, tzinfo=UTC)


def _observation(
    stock_code: str,
    *,
    market: CurrentPriceMarket = CurrentPriceMarket.KRX,
    price: Decimal = Decimal("100"),
    started_offset: timedelta = timedelta(0),
    received_offset: timedelta = timedelta(milliseconds=100),
) -> CurrentPriceObservation:
    return CurrentPriceObservation(
        stock_code=stock_code,
        current_price=price,
        market=market,
        request_started_at=STARTED + started_offset,
        received_at=STARTED + received_offset,
    )


class FakeCurrentPriceReader:
    def __init__(self, results: dict[str, object]) -> None:
        self.results = results
        self.calls: list[tuple[str, CurrentPriceMarket]] = []

    def fetch_current_price(
        self,
        stock_code: str,
        market: CurrentPriceMarket,
    ) -> CurrentPriceObservation:
        self.calls.append((stock_code, market))
        result = self.results[stock_code]
        if isinstance(result, BaseException):
            raise result
        return result  # type: ignore[return-value]


def _bundle() -> ValuationPriceBundle:
    observations = (
        _observation("005930"),
        _observation(
            "000660",
            price=Decimal("200"),
            started_offset=timedelta(seconds=1),
            received_offset=timedelta(seconds=1, milliseconds=100),
        ),
    )
    return ValuationPriceBundle(
        stock_codes=("005930", "000660"),
        observations=observations,
        currency="KRW",
    )


def _exception_surfaces(error: BaseException) -> str:
    pending = [error]
    seen: set[int] = set()
    surfaces: list[str] = []
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        surfaces.extend((str(current), repr(current), repr(current.args)))
        surfaces.extend(getattr(current, "__notes__", ()))
        surfaces.extend(traceback.format_exception(current))
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
    return "\n".join(surfaces)


def test_service_reads_sequentially_and_preserves_exact_requested_order() -> None:
    reader = FakeCurrentPriceReader(
        {
            "005930": _observation("005930", price=Decimal("71000.40")),
            "000660": _observation(
                "000660",
                price=Decimal("201000"),
                started_offset=timedelta(seconds=1),
                received_offset=timedelta(seconds=1, milliseconds=100),
            ),
        }
    )

    bundle = ValuationPriceService(reader).fetch_valuation_price_bundle(
        ("005930", "000660"),
        market=CurrentPriceMarket.KRX,
        maximum_acquisition_span=timedelta(seconds=1, milliseconds=100),
    )

    assert reader.calls == [
        ("005930", CurrentPriceMarket.KRX),
        ("000660", CurrentPriceMarket.KRX),
    ]
    assert bundle.stock_codes == ("005930", "000660")
    assert bundle.valuation_prices == (Decimal("71000.40"), Decimal("201000"))
    assert bundle.currency == "KRW"
    assert bundle.market is CurrentPriceMarket.KRX
    assert bundle.acquisition_span == timedelta(seconds=1, milliseconds=100)


@pytest.mark.parametrize(
    ("stock_codes", "market", "maximum_acquisition_span"),
    (
        ([], CurrentPriceMarket.KRX, timedelta(seconds=1)),
        ((), CurrentPriceMarket.KRX, timedelta(seconds=1)),
        (("5930",), CurrentPriceMarket.KRX, timedelta(seconds=1)),
        (("\uff10\uff10\uff15\uff19\uff13\uff10",), CurrentPriceMarket.KRX, timedelta(seconds=1)),
        (("005930", "005930"), CurrentPriceMarket.KRX, timedelta(seconds=1)),
        (("005930",), "KRX", timedelta(seconds=1)),
        (("005930",), CurrentPriceMarket.KRX, timedelta(0)),
        (("005930",), CurrentPriceMarket.KRX, timedelta(microseconds=-1)),
        (("005930",), CurrentPriceMarket.KRX, 1),
    ),
)
def test_service_rejects_invalid_complete_request_before_reader_use(
    stock_codes: object,
    market: object,
    maximum_acquisition_span: object,
) -> None:
    reader = FakeCurrentPriceReader({})

    with pytest.raises(InvalidValuationPriceRequestError):
        ValuationPriceService(reader).fetch_valuation_price_bundle(
            stock_codes,  # type: ignore[arg-type]
            market=market,  # type: ignore[arg-type]
            maximum_acquisition_span=maximum_acquisition_span,  # type: ignore[arg-type]
        )

    assert reader.calls == []


@pytest.mark.parametrize("market", (CurrentPriceMarket.NXT, CurrentPriceMarket.INTEGRATED))
def test_provider_neutral_service_delegates_every_exact_market_enum(
    market: CurrentPriceMarket,
) -> None:
    reader = FakeCurrentPriceReader({"005930": _observation("005930", market=market)})

    bundle = ValuationPriceService(reader).fetch_valuation_price_bundle(
        ("005930",),
        market=market,
        maximum_acquisition_span=timedelta(seconds=1),
    )

    assert bundle.market is market
    assert reader.calls == [("005930", market)]


def test_service_reconstructs_a_fresh_valid_reader_observation() -> None:
    returned_observation = _observation("005930", price=Decimal("71000.40"))
    reader = FakeCurrentPriceReader({"005930": returned_observation})

    bundle = ValuationPriceService(reader).fetch_valuation_price_bundle(
        ("005930",),
        market=CurrentPriceMarket.KRX,
        maximum_acquisition_span=timedelta(seconds=1),
    )

    assert bundle.observations[0] == returned_observation
    assert bundle.observations[0] is not returned_observation


@pytest.mark.parametrize(
    "forged_observation",
    (
        CurrentPriceObservation.model_construct(
            stock_code="005930",
            current_price=Decimal("-1"),
            market=CurrentPriceMarket.KRX,
            request_started_at=STARTED,
            received_at=STARTED,
        ),
        CurrentPriceObservation.model_construct(
            stock_code="005930",
            current_price=Decimal("1"),
            market=CurrentPriceMarket.KRX,
            request_started_at=STARTED,
        ),
    ),
)
def test_service_rejects_invalid_model_construct_observation(
    forged_observation: CurrentPriceObservation,
) -> None:
    reader = FakeCurrentPriceReader({"005930": forged_observation})

    with pytest.raises(ValuationPriceBundleCoherenceError):
        ValuationPriceService(reader).fetch_valuation_price_bundle(
            ("005930",),
            market=CurrentPriceMarket.KRX,
            maximum_acquisition_span=timedelta(seconds=1),
        )

    assert reader.calls == [("005930", CurrentPriceMarket.KRX)]


def test_forged_reader_values_do_not_enter_operational_error_state() -> None:
    raw_secret = "synthetic-forged-current-price-secret"
    forged_observation = CurrentPriceObservation.model_construct(
        stock_code="005930",
        current_price=raw_secret,
        market=CurrentPriceMarket.KRX,
        request_started_at=STARTED,
        received_at=STARTED,
    )
    reader = FakeCurrentPriceReader({"005930": forged_observation})

    with pytest.raises(ValuationPriceBundleCoherenceError) as captured:
        ValuationPriceService(reader).fetch_valuation_price_bundle(
            ("005930",),
            market=CurrentPriceMarket.KRX,
            maximum_acquisition_span=timedelta(seconds=1),
        )

    assert raw_secret not in _exception_surfaces(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert getattr(captured.value, "__notes__", ()) == ()
    current_traceback = captured.value.__traceback__
    while current_traceback is not None:
        frame = current_traceback.tb_frame
        if frame.f_globals.get("__name__", "").startswith("phalanx."):
            assert all(value is not forged_observation for value in frame.f_locals.values())
            assert not any(
                isinstance(value, ValidationError) for value in frame.f_locals.values()
            )
        current_traceback = current_traceback.tb_next


def test_reader_failure_reports_zero_based_index_without_arbitrary_exception_context() -> None:
    secret = "synthetic-secret-reader-detail"
    reader = FakeCurrentPriceReader(
        {
            "005930": _observation("005930"),
            "000660": RuntimeError(secret),
            "035420": _observation("035420"),
        }
    )

    with pytest.raises(CurrentPriceObservationReadError) as captured:
        ValuationPriceService(reader).fetch_valuation_price_bundle(
            ("005930", "000660", "035420"),
            market=CurrentPriceMarket.KRX,
            maximum_acquisition_span=timedelta(seconds=10),
        )

    assert reader.calls == [
        ("005930", CurrentPriceMarket.KRX),
        ("000660", CurrentPriceMarket.KRX),
    ]
    assert captured.value.stock_code == "000660"
    assert captured.value.request_index == 1
    assert secret not in str(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_reader_unsupported_market_error_passes_through_unchanged() -> None:
    expected = UnsupportedCurrentPriceMarketError(CurrentPriceMarket.NXT)
    reader = FakeCurrentPriceReader({"005930": expected})

    with pytest.raises(UnsupportedCurrentPriceMarketError) as captured:
        ValuationPriceService(reader).fetch_valuation_price_bundle(
            ("005930",),
            market=CurrentPriceMarket.KRX,
            maximum_acquisition_span=timedelta(seconds=1),
        )

    assert captured.value is expected


@pytest.mark.parametrize("failure", (KeyboardInterrupt(), SystemExit(7)))
def test_reader_base_exceptions_are_not_converted_and_stop_later_reads(
    failure: BaseException,
) -> None:
    reader = FakeCurrentPriceReader(
        {
            "005930": failure,
            "000660": _observation("000660"),
        }
    )

    with pytest.raises(type(failure)) as captured:
        ValuationPriceService(reader).fetch_valuation_price_bundle(
            ("005930", "000660"),
            market=CurrentPriceMarket.KRX,
            maximum_acquisition_span=timedelta(seconds=1),
        )

    assert captured.value is failure
    assert reader.calls == [("005930", CurrentPriceMarket.KRX)]


@pytest.mark.parametrize(
    "result",
    (
        object(),
        _observation("000660"),
        _observation("005930", market=CurrentPriceMarket.NXT),
    ),
)
def test_reader_contract_mismatch_fails_with_typed_coherence_error(result: object) -> None:
    reader = FakeCurrentPriceReader({"005930": result})

    with pytest.raises(ValuationPriceBundleCoherenceError):
        ValuationPriceService(reader).fetch_valuation_price_bundle(
            ("005930",),
            market=CurrentPriceMarket.KRX,
            maximum_acquisition_span=timedelta(seconds=1),
        )


def test_service_rejects_only_acquisition_span_strictly_above_the_limit() -> None:
    observation = _observation("005930", received_offset=timedelta(seconds=1))
    reader = FakeCurrentPriceReader({"005930": observation})
    service = ValuationPriceService(reader)

    exact = service.fetch_valuation_price_bundle(
        ("005930",),
        market=CurrentPriceMarket.KRX,
        maximum_acquisition_span=timedelta(seconds=1),
    )
    assert exact.acquisition_span == timedelta(seconds=1)

    with pytest.raises(ValuationPriceBundleCoherenceError):
        service.fetch_valuation_price_bundle(
            ("005930",),
            market=CurrentPriceMarket.KRX,
            maximum_acquisition_span=timedelta(seconds=1) - timedelta(microseconds=1),
        )


def test_acquisition_recency_uses_earliest_start_and_accepts_exact_age_limit() -> None:
    bundle = _bundle()
    evaluated_at = STARTED + timedelta(seconds=5)

    result = validate_valuation_price_bundle_acquisition_recency(
        bundle,
        evaluated_at=evaluated_at,
        maximum_acquisition_age=timedelta(seconds=5),
    )

    assert result == bundle
    assert result is not bundle


def test_acquisition_recency_rejects_one_microsecond_over_with_exact_evidence() -> None:
    bundle = _bundle()
    maximum_age = timedelta(seconds=5)
    evaluated_at = STARTED + maximum_age + timedelta(microseconds=1)

    with pytest.raises(ValuationPriceBundleAcquisitionTooOldError) as captured:
        validate_valuation_price_bundle_acquisition_recency(
            bundle,
            evaluated_at=evaluated_at,
            maximum_acquisition_age=maximum_age,
        )

    assert captured.value.acquisition_age == maximum_age + timedelta(microseconds=1)
    assert captured.value.maximum_acquisition_age == maximum_age


def test_acquisition_recency_orders_dst_fold_instants_in_utc() -> None:
    new_york = ZoneInfo("America/New_York")
    request_started_at = datetime(2026, 11, 1, 1, 30, tzinfo=new_york, fold=0)
    received_at = datetime(2026, 11, 1, 1, 45, tzinfo=new_york, fold=0)
    evaluated_at = datetime(2026, 11, 1, 1, 15, tzinfo=new_york, fold=1)
    observation = CurrentPriceObservation(
        stock_code="005930",
        current_price=Decimal("100"),
        market=CurrentPriceMarket.KRX,
        request_started_at=request_started_at,
        received_at=received_at,
    )
    bundle = ValuationPriceBundle(
        stock_codes=("005930",),
        observations=(observation,),
        currency="KRW",
    )

    result = validate_valuation_price_bundle_acquisition_recency(
        bundle,
        evaluated_at=evaluated_at,
        maximum_acquisition_age=timedelta(minutes=45),
    )
    assert result == bundle
    assert result is not bundle


def test_acquisition_recency_age_is_elapsed_utc_time_across_dst_fold() -> None:
    new_york = ZoneInfo("America/New_York")
    request_started_at = datetime(2026, 11, 1, 1, 45, tzinfo=new_york, fold=0)
    received_at = datetime(2026, 11, 1, 1, 15, tzinfo=new_york, fold=1)
    evaluated_at = datetime(2026, 11, 1, 1, 30, tzinfo=new_york, fold=1)
    observation = CurrentPriceObservation(
        stock_code="005930",
        current_price=Decimal("100"),
        market=CurrentPriceMarket.KRX,
        request_started_at=request_started_at,
        received_at=received_at,
    )
    bundle = ValuationPriceBundle(
        stock_codes=("005930",),
        observations=(observation,),
        currency="KRW",
    )

    with pytest.raises(ValuationPriceBundleAcquisitionTooOldError) as captured:
        validate_valuation_price_bundle_acquisition_recency(
            bundle,
            evaluated_at=evaluated_at,
            maximum_acquisition_age=timedelta(minutes=45) - timedelta(microseconds=1),
        )

    assert captured.value.acquisition_age == timedelta(minutes=45)


def test_acquisition_recency_age_supports_mixed_timezone_offsets() -> None:
    seoul = ZoneInfo("Asia/Seoul")
    new_york = ZoneInfo("America/New_York")
    request_started_at = datetime(2026, 9, 3, 9, 0, tzinfo=seoul)
    received_at = datetime(2026, 9, 3, 9, 5, tzinfo=seoul)
    evaluated_at = datetime(2026, 9, 2, 20, 30, tzinfo=new_york)
    observation = CurrentPriceObservation(
        stock_code="005930",
        current_price=Decimal("100"),
        market=CurrentPriceMarket.KRX,
        request_started_at=request_started_at,
        received_at=received_at,
    )
    bundle = ValuationPriceBundle(
        stock_codes=("005930",),
        observations=(observation,),
        currency="KRW",
    )

    with pytest.raises(ValuationPriceBundleAcquisitionTooOldError) as captured:
        validate_valuation_price_bundle_acquisition_recency(
            bundle,
            evaluated_at=evaluated_at,
            maximum_acquisition_age=timedelta(minutes=30) - timedelta(microseconds=1),
        )

    assert captured.value.acquisition_age == timedelta(minutes=30)


@pytest.mark.parametrize(
    ("bundle", "evaluated_at", "maximum_acquisition_age"),
    (
        (object(), STARTED + timedelta(seconds=2), timedelta(seconds=2)),
        (_bundle(), datetime(2026, 9, 3, 1, 0, 2), timedelta(seconds=2)),
        (_bundle(), "2026-09-03T01:00:02Z", timedelta(seconds=2)),
        (_bundle(), STARTED + timedelta(seconds=2), timedelta(microseconds=-1)),
        (_bundle(), STARTED + timedelta(seconds=2), 2),
        (_bundle(), STARTED + timedelta(seconds=1), timedelta(seconds=2)),
    ),
)
def test_acquisition_recency_rejects_invalid_evaluation_inputs(
    bundle: object,
    evaluated_at: object,
    maximum_acquisition_age: object,
) -> None:
    with pytest.raises(InvalidValuationPriceAcquisitionRecencyError):
        validate_valuation_price_bundle_acquisition_recency(
            bundle,  # type: ignore[arg-type]
            evaluated_at=evaluated_at,  # type: ignore[arg-type]
            maximum_acquisition_age=maximum_acquisition_age,  # type: ignore[arg-type]
        )


def test_acquisition_recency_rejects_a_forged_bundle() -> None:
    forged_bundle = ValuationPriceBundle.model_construct(
        stock_codes=("005930",),
        observations=[_observation("005930")],
        currency="USD",
    )

    with pytest.raises(InvalidValuationPriceAcquisitionRecencyError) as captured:
        validate_valuation_price_bundle_acquisition_recency(
            forged_bundle,
            evaluated_at=STARTED + timedelta(seconds=1),
            maximum_acquisition_age=timedelta(seconds=1),
        )

    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_zero_acquisition_age_and_zero_limit_are_valid() -> None:
    observation = _observation("005930", received_offset=timedelta(0))
    bundle = ValuationPriceBundle(
        stock_codes=("005930",),
        observations=(observation,),
        currency="KRW",
    )

    result = validate_valuation_price_bundle_acquisition_recency(
        bundle,
        evaluated_at=STARTED,
        maximum_acquisition_age=timedelta(0),
    )
    assert result == bundle
    assert result is not bundle


def test_service_module_exports_current_and_historical_boundaries() -> None:
    assert {
        "CurrentPriceReader",
        "DailyBarReader",
        "MarketDataService",
        "StockDailyBars",
        "UniverseReader",
        "ValuationPriceService",
        "validate_valuation_price_bundle_acquisition_recency",
    } <= set(market_data_service.__all__)
    assert {"BuyingPowerQuote", "ProposedTrade", "RebalanceProposal"}.isdisjoint(
        market_data_service.__all__
    )
