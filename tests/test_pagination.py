from __future__ import annotations

import copy
import json
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from phalanx.config import KisCredentials
from phalanx.kis.auth import AccessToken
from phalanx.kis.client import KisBalanceClient
from phalanx.kis.errors import (
    KisApiResponseError,
    KisBalanceHttpError,
    KisBalanceProtocolError,
)

SEOUL = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 8, 29, 12, 0, 0, tzinfo=SEOUL)
FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "kis"
CURSOR = ("SYNTHETIC-FK-PAGE-2", "SYNTHETIC-NK-PAGE-2")

Handler = Callable[[httpx.Request], httpx.Response]
ClientFactory = Callable[[Handler], httpx.Client]


class RecordingTokenManager:
    def __init__(self) -> None:
        self.token = AccessToken(
            access_token=SecretStr("synthetic-pagination-token"),
            token_type="Bearer",
            expires_at=NOW + timedelta(hours=1),
        )
        self.get_calls = 0
        self.invalidated: list[AccessToken] = []

    def get_access_token(self) -> AccessToken:
        self.get_calls += 1
        return self.token

    def invalidate_if_current(self, token: AccessToken) -> bool:
        self.invalidated.append(token)
        return True


@pytest.fixture
def client_factory() -> Iterator[ClientFactory]:
    clients: list[httpx.Client] = []

    def create(handler: Handler) -> httpx.Client:
        client = httpx.Client(transport=httpx.MockTransport(handler))
        clients.append(client)
        return client

    yield create

    for client in clients:
        client.close()


def _credentials() -> KisCredentials:
    return KisCredentials(
        app_key="synthetic-pagination-app-key",
        app_secret="synthetic-pagination-app-secret",
        account_number="11223344-01",
    )


def _fixture(name: str) -> dict[str, Any]:
    loaded = json.loads((FIXTURE_DIRECTORY / name).read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _pages() -> tuple[dict[str, Any], dict[str, Any]]:
    return (
        _fixture("balance_multi_page_1.json"),
        _fixture("balance_multi_page_2.json"),
    )


def _sequence_handler(
    payloads: tuple[object, ...],
    tr_cont_headers: tuple[str, ...],
    requests: list[httpx.Request],
) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        index = len(requests)
        requests.append(request)
        return httpx.Response(
            200,
            json=payloads[index],
            headers={"tr_cont": tr_cont_headers[index]},
            request=request,
        )

    return handler


@pytest.mark.parametrize("continuation_signal", ("M", "F"))
def test_m_and_f_continuation_fetch_all_pages_in_order(
    client_factory: ClientFactory,
    continuation_signal: str,
) -> None:
    page1, page2 = _pages()
    requests: list[httpx.Request] = []
    token_manager = RecordingTokenManager()
    client = KisBalanceClient(
        _credentials(),
        token_manager,
        client=client_factory(
            _sequence_handler((page1, page2), (continuation_signal, ""), requests)
        ),
        clock=lambda: NOW,
    )

    result = client.fetch_balance()

    assert [position.stock_code for position in result.positions] == ["SYNTH001", "SYNTH002"]
    assert [position.stock_code for position in result.zero_quantity_balances] == ["SYNTHZERO"]
    assert result.page_count == 2
    assert [page.page_number for page in result.evidence.pages] == [1, 2]
    assert [page.tr_cont for page in result.evidence.pages] == [continuation_signal, ""]
    assert token_manager.get_calls == 2
    assert token_manager.invalidated == []
    assert len(requests) == 2


def test_follow_up_request_uses_n_and_exact_response_cursors(
    client_factory: ClientFactory,
) -> None:
    page1, page2 = _pages()
    requests: list[httpx.Request] = []

    result = KisBalanceClient(
        _credentials(),
        RecordingTokenManager(),
        client=client_factory(_sequence_handler((page1, page2), ("M", ""), requests)),
        clock=lambda: NOW,
    ).fetch_balance()

    assert requests[0].headers["tr_cont"] == ""
    assert requests[0].url.params["CTX_AREA_FK100"] == ""
    assert requests[0].url.params["CTX_AREA_NK100"] == ""
    assert requests[1].headers["tr_cont"] == "N"
    assert requests[1].url.params["CTX_AREA_FK100"] == CURSOR[0]
    assert requests[1].url.params["CTX_AREA_NK100"] == CURSOR[1]
    assert result.evidence.pages[0].ctx_area_fk100 == CURSOR[0]
    assert result.evidence.pages[0].ctx_area_nk100 == CURSOR[1]


def test_repeated_cursor_pair_is_rejected_after_second_page(
    client_factory: ClientFactory,
) -> None:
    page1, page2 = _pages()
    page2["ctx_area_fk100"] = CURSOR[0]
    page2["ctx_area_nk100"] = CURSOR[1]
    requests: list[httpx.Request] = []

    with pytest.raises(KisBalanceProtocolError, match="repeated a cursor pair"):
        KisBalanceClient(
            _credentials(),
            RecordingTokenManager(),
            client=client_factory(_sequence_handler((page1, page2), ("M", "F"), requests)),
            clock=lambda: NOW,
        ).fetch_balance()

    assert len(requests) == 2


@pytest.mark.parametrize("blank_cursor", ("ctx_area_fk100", "ctx_area_nk100"))
def test_continuation_with_any_blank_cursor_is_rejected_without_partial_result(
    client_factory: ClientFactory,
    blank_cursor: str,
) -> None:
    page1, _ = _pages()
    page1[blank_cursor] = ""
    requests: list[httpx.Request] = []

    with pytest.raises(KisBalanceProtocolError, match="without complete cursors"):
        KisBalanceClient(
            _credentials(),
            RecordingTokenManager(),
            client=client_factory(_sequence_handler((page1,), ("M",), requests)),
            clock=lambda: NOW,
        ).fetch_balance()

    assert len(requests) == 1


def test_page_limit_stops_before_an_excess_request(client_factory: ClientFactory) -> None:
    page1, _ = _pages()
    requests: list[httpx.Request] = []

    with pytest.raises(KisBalanceProtocolError, match="page limit"):
        KisBalanceClient(
            _credentials(),
            RecordingTokenManager(),
            client=client_factory(_sequence_handler((page1,), ("M",), requests)),
            max_pages=1,
            clock=lambda: NOW,
        ).fetch_balance()

    assert len(requests) == 1


@pytest.mark.parametrize("invalid_limit", (0, -1, True, 1.5))
def test_page_limit_must_be_a_positive_integer(invalid_limit: object) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        KisBalanceClient(
            _credentials(),
            RecordingTokenManager(),
            max_pages=invalid_limit,  # type: ignore[arg-type]
            clock=lambda: NOW,
        )


def test_identical_page_summaries_record_no_mismatch(client_factory: ClientFactory) -> None:
    page1, page2 = _pages()
    requests: list[httpx.Request] = []

    result = KisBalanceClient(
        _credentials(),
        RecordingTokenManager(),
        client=client_factory(_sequence_handler((page1, page2), ("M", ""), requests)),
        clock=lambda: NOW,
    ).fetch_balance()

    assert result.summary.deposit_total == Decimal("100000.00")
    assert not result.summaries_differed_across_pages
    assert result.evidence.summary_consistency_warnings == ()


def test_different_page_summary_uses_final_and_records_mismatch(
    client_factory: ClientFactory,
) -> None:
    page1, page2 = _pages()
    page2_output2 = page2["output2"]
    assert isinstance(page2_output2, list)
    assert isinstance(page2_output2[0], dict)
    page2_output2[0]["dnca_tot_amt"] = "99999.25"
    requests: list[httpx.Request] = []

    result = KisBalanceClient(
        _credentials(),
        RecordingTokenManager(),
        client=client_factory(_sequence_handler((page1, page2), ("F", ""), requests)),
        clock=lambda: NOW,
    ).fetch_balance()

    assert result.summary.deposit_total == Decimal("99999.25")
    assert result.summaries_differed_across_pages
    assert result.evidence.summary_consistency_warnings == (
        "Account summaries differed across balance pages; the final page summary was used.",
    )


@pytest.mark.parametrize("duplicate_collection", ("positions", "across-collections"))
def test_duplicate_stock_codes_across_pages_are_rejected(
    client_factory: ClientFactory,
    duplicate_collection: str,
) -> None:
    page1, page2 = _pages()
    page2_output1 = page2["output1"]
    assert isinstance(page2_output1, list)
    duplicate_row = page2_output1[0] if duplicate_collection == "positions" else page2_output1[1]
    assert isinstance(duplicate_row, dict)
    duplicate_row["pdno"] = "SYNTH001"
    requests: list[httpx.Request] = []

    with pytest.raises(KisBalanceProtocolError, match="snapshot invariants"):
        KisBalanceClient(
            _credentials(),
            RecordingTokenManager(),
            client=client_factory(_sequence_handler((page1, page2), ("M", ""), requests)),
            clock=lambda: NOW,
        ).fetch_balance()

    assert len(requests) == 2


@pytest.mark.parametrize("failure_kind", ("http", "json", "api"))
def test_middle_page_failure_returns_no_partial_result(
    client_factory: ClientFactory,
    failure_kind: str,
) -> None:
    page1, _ = _pages()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(200, json=page1, headers={"tr_cont": "M"}, request=request)
        if failure_kind == "http":
            return httpx.Response(500, content=b"synthetic failure", request=request)
        if failure_kind == "json":
            return httpx.Response(200, content=b"not-json", request=request)
        return httpx.Response(
            200,
            json={"rt_cd": "1", "msg_cd": "SYNTHETIC_ERROR", "msg1": "failed"},
            request=request,
        )

    expected_error = {
        "http": KisBalanceHttpError,
        "json": KisBalanceProtocolError,
        "api": KisApiResponseError,
    }[failure_kind]
    with pytest.raises(expected_error):
        KisBalanceClient(
            _credentials(),
            RecordingTokenManager(),
            client=client_factory(handler),
            clock=lambda: NOW,
        ).fetch_balance()

    assert len(requests) == 2


def test_completed_result_is_deeply_immutable_and_detached_from_response_inputs(
    client_factory: ClientFactory,
) -> None:
    page1, page2 = _pages()
    original_pages = (copy.deepcopy(page1), copy.deepcopy(page2))
    requests: list[httpx.Request] = []
    result = KisBalanceClient(
        _credentials(),
        RecordingTokenManager(),
        client=client_factory(_sequence_handler((page1, page2), ("M", ""), requests)),
        clock=lambda: NOW,
    ).fetch_balance()

    page1.clear()
    page2_output1 = page2["output1"]
    assert isinstance(page2_output1, list)
    page2_output1.clear()

    assert [position.stock_code for position in result.positions] == ["SYNTH001", "SYNTH002"]
    assert result.evidence.pages[0].output1
    assert original_pages[0] != page1
    with pytest.raises(ValidationError):
        result.positions = ()
    with pytest.raises(ValidationError):
        result.evidence.pages[0].tr_cont = "changed"


def test_naive_clock_is_rejected_before_network_or_file_access(
    client_factory: ClientFactory,
) -> None:
    requests: list[httpx.Request] = []
    naive_now = NOW.replace(tzinfo=None)

    with pytest.raises(KisBalanceProtocolError, match="timezone-aware"):
        KisBalanceClient(
            _credentials(),
            RecordingTokenManager(),
            client=client_factory(
                lambda request: (
                    requests.append(request),
                    httpx.Response(500, request=request),
                )[1]
            ),
            clock=lambda: naive_now,
        ).fetch_balance()

    assert requests == []
