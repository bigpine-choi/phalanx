from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from pydantic import SecretStr

from phalanx.config import KisCredentials
from phalanx.kis.auth import AccessToken
from phalanx.kis.client import (
    KIS_BALANCE_PATH,
    KIS_BALANCE_TR_ID,
    KIS_BALANCE_URL,
    KisBalanceClient,
)
from phalanx.kis.errors import (
    InvalidResponseStructure,
    KisApiResponseError,
    KisBalanceAuthenticationError,
    KisBalanceHttpError,
    KisBalanceProtocolError,
    KisBalanceTimeoutError,
)

SEOUL = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 8, 29, 12, 0, 0, tzinfo=SEOUL)
APP_KEY = "synthetic-balance-app-key"
APP_SECRET = "synthetic-balance-app-secret"
ACCOUNT_NUMBER = "87654321-01"
FIRST_TOKEN = "synthetic-balance-token-one"
SECOND_TOKEN = "synthetic-balance-token-two"
FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "kis"

Handler = Callable[[httpx.Request], httpx.Response]
ClientFactory = Callable[[Handler], httpx.Client]


class StubTokenManager:
    def __init__(self, tokens: tuple[AccessToken, ...] | None = None) -> None:
        self.tokens = tokens or (_access_token(FIRST_TOKEN),)
        self.current_index = 0
        self.get_calls = 0
        self.invalidated: list[AccessToken] = []

    def get_access_token(self) -> AccessToken:
        self.get_calls += 1
        return self.tokens[self.current_index]

    def invalidate_if_current(self, token: AccessToken) -> bool:
        self.invalidated.append(token)
        current = self.tokens[self.current_index]
        if token.access_token.get_secret_value() != current.access_token.get_secret_value():
            return False
        if self.current_index + 1 < len(self.tokens):
            self.current_index += 1
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
        app_key=APP_KEY,
        app_secret=APP_SECRET,
        account_number=ACCOUNT_NUMBER,
    )


def _access_token(value: str) -> AccessToken:
    return AccessToken(
        access_token=SecretStr(value),
        token_type="Bearer",
        expires_at=NOW + timedelta(hours=1),
    )


def _page_fixture(name: str = "balance_single_page.json") -> dict[str, Any]:
    loaded = json.loads((FIXTURE_DIRECTORY / name).read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _success_response(
    request: httpx.Request,
    *,
    payload: object | None = None,
    tr_cont: str = "",
) -> httpx.Response:
    return httpx.Response(
        200,
        json=_page_fixture() if payload is None else payload,
        headers={"tr_cont": tr_cont},
        request=request,
    )


def test_balance_client_uses_exact_fixed_real_get_contract(
    client_factory: ClientFactory,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _success_response(request)

    token_manager = StubTokenManager()
    http_client = client_factory(handler)
    result = KisBalanceClient(
        _credentials(),
        token_manager,
        client=http_client,
        clock=lambda: NOW,
    ).fetch_balance()

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert str(request.url).split("?", maxsplit=1)[0] == KIS_BALANCE_URL
    assert request.url.scheme == "https"
    assert request.url.host == "openapi.koreainvestment.com"
    assert request.url.port == 9443
    assert request.url.path == KIS_BALANCE_PATH
    assert request.content == b""
    assert request.headers["authorization"] == f"Bearer {FIRST_TOKEN}"
    assert request.headers["appkey"] == APP_KEY
    assert request.headers["appsecret"] == APP_SECRET
    assert request.headers["tr_id"] == KIS_BALANCE_TR_ID == "TTTC8434R"
    assert request.headers["custtype"] == "P"
    assert request.headers["tr_cont"] == ""
    assert dict(request.url.params) == {
        "CANO": "87654321",
        "ACNT_PRDT_CD": "01",
        "AFHR_FLPR_YN": "N",
        "OFL_YN": "",
        "INQR_DVSN": "02",
        "UNPR_DVSN": "01",
        "FUND_STTL_ICLD_YN": "N",
        "FNCG_AMT_AUTO_RDPT_YN": "N",
        "PRCS_DVSN": "00",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": "",
    }
    assert result.account_number_masked == "8765****-**"
    assert result.page_count == 1
    assert token_manager.get_calls == 1


def test_single_page_result_preserves_exact_response_hash_and_evidence(
    client_factory: ClientFactory,
) -> None:
    payload = _page_fixture()
    raw_body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=raw_body,
            headers={"tr_cont": ""},
            request=request,
        )

    result = KisBalanceClient(
        _credentials(),
        StubTokenManager(),
        client=client_factory(handler),
        clock=lambda: NOW,
    ).fetch_balance()

    page = result.evidence.pages[0]
    assert page.page_number == 1
    assert page.received_at == NOW
    assert page.http_status == 200
    assert page.tr_cont == ""
    assert page.rt_cd == "0"
    assert page.msg_cd == "SYNTHETIC_SUCCESS"
    assert page.response_body_sha256 == hashlib.sha256(raw_body).hexdigest()
    assert page.output1
    assert page.output2
    assert page.placeholder_rows
    assert result.query_started_at == NOW
    assert result.query_completed_at == NOW
    assert not result.summaries_differed_across_pages


def test_success_response_requires_explicit_tr_cont_header(
    client_factory: ClientFactory,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_page_fixture(), request=request)

    with pytest.raises(KisBalanceProtocolError, match="omitted the tr_cont header"):
        KisBalanceClient(
            _credentials(),
            StubTokenManager(),
            client=client_factory(handler),
            clock=lambda: NOW,
        ).fetch_balance()


def test_injected_http_client_remains_caller_owned(client_factory: ClientFactory) -> None:
    http_client = client_factory(lambda request: _success_response(request))

    KisBalanceClient(
        _credentials(),
        StubTokenManager(),
        client=http_client,
        clock=lambda: NOW,
    ).fetch_balance()

    assert not http_client.is_closed


@pytest.mark.parametrize("status_code", (400, 403, 429, 500))
def test_non_success_http_status_is_safe_and_not_retried(
    client_factory: ClientFactory,
    status_code: int,
) -> None:
    requests: list[httpx.Request] = []
    token_manager = StubTokenManager()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            status_code,
            content=f"response echoes {ACCOUNT_NUMBER} {APP_SECRET}".encode(),
            request=request,
        )

    with pytest.raises(KisBalanceHttpError) as captured:
        KisBalanceClient(
            _credentials(),
            token_manager,
            client=client_factory(handler),
            clock=lambda: NOW,
        ).fetch_balance()

    assert len(requests) == 1
    assert token_manager.invalidated == []
    assert ACCOUNT_NUMBER not in str(captured.value)
    assert APP_SECRET not in str(captured.value)


def test_timeout_is_converted_without_original_request_details(
    client_factory: ClientFactory,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(
            f"timeout for {request.url} using {FIRST_TOKEN}",
            request=request,
        )

    with pytest.raises(KisBalanceTimeoutError) as captured:
        KisBalanceClient(
            _credentials(),
            StubTokenManager(),
            client=client_factory(handler),
            clock=lambda: NOW,
        ).fetch_balance()

    message = str(captured.value)
    assert ACCOUNT_NUMBER not in message
    assert FIRST_TOKEN not in message
    assert KIS_BALANCE_URL not in message


def test_transport_error_is_converted_without_original_url(
    client_factory: ClientFactory,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}", request=request)

    with pytest.raises(KisBalanceHttpError) as captured:
        KisBalanceClient(
            _credentials(),
            StubTokenManager(),
            client=client_factory(handler),
            clock=lambda: NOW,
        ).fetch_balance()

    assert ACCOUNT_NUMBER not in str(captured.value)
    assert KIS_BALANCE_URL not in str(captured.value)


def test_invalid_json_is_rejected_without_echoing_body(client_factory: ClientFactory) -> None:
    secret_body = f"not json {APP_KEY} {APP_SECRET} {FIRST_TOKEN} {ACCOUNT_NUMBER}".encode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=secret_body, request=request)

    with pytest.raises(KisBalanceProtocolError) as captured:
        KisBalanceClient(
            _credentials(),
            StubTokenManager(),
            client=client_factory(handler),
            clock=lambda: NOW,
        ).fetch_balance()

    message = str(captured.value)
    for secret in (APP_KEY, APP_SECRET, FIRST_TOKEN, ACCOUNT_NUMBER):
        assert secret not in message


def test_non_authentication_api_failure_is_not_retried_or_invalidated(
    client_factory: ClientFactory,
) -> None:
    token_manager = StubTokenManager()
    requests: list[httpx.Request] = []
    payload = {
        "rt_cd": "1",
        "msg_cd": "SYNTHETIC_BALANCE_ERROR",
        "msg1": f"rejected {APP_KEY} {APP_SECRET} {FIRST_TOKEN} {ACCOUNT_NUMBER}",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _success_response(request, payload=payload)

    with pytest.raises(KisApiResponseError) as captured:
        KisBalanceClient(
            _credentials(),
            token_manager,
            client=client_factory(handler),
            clock=lambda: NOW,
        ).fetch_balance()

    assert len(requests) == 1
    assert token_manager.invalidated == []
    for secret in (APP_KEY, APP_SECRET, FIRST_TOKEN, ACCOUNT_NUMBER, "87654321"):
        assert secret not in str(captured.value)
    assert "[REDACTED]" in str(captured.value)


def test_http_401_invalidates_only_used_token_and_reauthenticates_once(
    client_factory: ClientFactory,
) -> None:
    token_manager = StubTokenManager((_access_token(FIRST_TOKEN), _access_token(SECOND_TOKEN)))
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(401, content=b"unauthorized", request=request)
        return _success_response(request)

    result = KisBalanceClient(
        _credentials(),
        token_manager,
        client=client_factory(handler),
        clock=lambda: NOW,
    ).fetch_balance()

    assert result.page_count == 1
    assert len(requests) == 2
    assert requests[0].headers["authorization"] == f"Bearer {FIRST_TOKEN}"
    assert requests[1].headers["authorization"] == f"Bearer {SECOND_TOKEN}"
    assert token_manager.invalidated == [_access_token(FIRST_TOKEN)]
    assert token_manager.get_calls == 2


def test_official_expired_token_code_triggers_exactly_one_reauthentication(
    client_factory: ClientFactory,
) -> None:
    token_manager = StubTokenManager((_access_token(FIRST_TOKEN), _access_token(SECOND_TOKEN)))
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return _success_response(
                request,
                payload={
                    "rt_cd": "1",
                    "msg_cd": "EGW00123",
                    "msg1": "synthetic explicitly expired token",
                },
            )
        return _success_response(request)

    result = KisBalanceClient(
        _credentials(),
        token_manager,
        client=client_factory(handler),
        clock=lambda: NOW,
    ).fetch_balance()

    assert result.page_count == 1
    assert len(requests) == 2
    assert len(token_manager.invalidated) == 1


def test_message_words_do_not_guess_token_expiration(client_factory: ClientFactory) -> None:
    token_manager = StubTokenManager((_access_token(FIRST_TOKEN), _access_token(SECOND_TOKEN)))
    payload = {
        "rt_cd": "1",
        "msg_cd": "SYNTHETIC_NOT_AUTH",
        "msg1": "access token expired invalid unauthorized",
    }
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _success_response(request, payload=payload)

    with pytest.raises(KisApiResponseError):
        KisBalanceClient(
            _credentials(),
            token_manager,
            client=client_factory(handler),
            clock=lambda: NOW,
        ).fetch_balance()

    assert len(requests) == 1
    assert token_manager.invalidated == []


def test_malformed_message_code_is_a_parsing_error_not_an_authentication_retry(
    client_factory: ClientFactory,
) -> None:
    token_manager = StubTokenManager((_access_token(FIRST_TOKEN), _access_token(SECOND_TOKEN)))
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _success_response(
            request,
            payload={"rt_cd": "1", "msg_cd": ["EGW00123"], "msg1": "malformed"},
        )

    with pytest.raises(InvalidResponseStructure):
        KisBalanceClient(
            _credentials(),
            token_manager,
            client=client_factory(handler),
            clock=lambda: NOW,
        ).fetch_balance()

    assert len(requests) == 1
    assert token_manager.invalidated == []


@pytest.mark.parametrize("failure_kind", ("401", "expired-code"))
def test_failed_reauthentication_never_sends_a_third_request(
    client_factory: ClientFactory,
    failure_kind: str,
) -> None:
    token_manager = StubTokenManager((_access_token(FIRST_TOKEN), _access_token(SECOND_TOKEN)))
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if failure_kind == "401":
            return httpx.Response(401, request=request)
        return _success_response(
            request,
            payload={"rt_cd": "1", "msg_cd": "EGW00123", "msg1": "expired"},
        )

    with pytest.raises(KisBalanceAuthenticationError):
        KisBalanceClient(
            _credentials(),
            token_manager,
            client=client_factory(handler),
            clock=lambda: NOW,
        ).fetch_balance()

    assert len(requests) == 2
    assert token_manager.get_calls == 2
    assert len(token_manager.invalidated) == 1


def test_result_evidence_and_errors_never_expose_secrets_or_request_url(
    client_factory: ClientFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    payload = _page_fixture()
    payload["msg1"] = f"echo {APP_KEY} {APP_SECRET} {FIRST_TOKEN} {ACCOUNT_NUMBER}"
    payload["authorization"] = f"Bearer {FIRST_TOKEN}"
    payload["unknown_echo"] = {
        "appsecret": APP_SECRET,
        "note": f"nested {APP_KEY} {ACCOUNT_NUMBER}",
    }

    result = KisBalanceClient(
        _credentials(),
        StubTokenManager(),
        client=client_factory(lambda request: _success_response(request, payload=payload)),
        clock=lambda: NOW,
    ).fetch_balance()
    displayed = result.model_dump_json() + repr(result) + caplog.text

    for secret in (APP_KEY, APP_SECRET, FIRST_TOKEN, ACCOUNT_NUMBER, "87654321"):
        assert secret not in displayed
    assert KIS_BALANCE_URL not in displayed
    assert "[REDACTED]" in displayed


def test_client_does_not_access_home_runtime_or_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    client_factory: ClientFactory,
) -> None:
    def fail_home(cls: type[Path]) -> Path:
        raise AssertionError("the balance client must not resolve the real home directory")

    monkeypatch.setattr(Path, "home", classmethod(fail_home))
    monkeypatch.chdir(tmp_path)

    result = KisBalanceClient(
        _credentials(),
        StubTokenManager(),
        client=client_factory(lambda request: _success_response(request)),
        clock=lambda: NOW,
    ).fetch_balance()

    assert result.page_count == 1
    assert list(tmp_path.iterdir()) == []


def test_client_has_no_demo_order_or_general_request_surface() -> None:
    source = Path("src/phalanx/kis/client.py").read_text(encoding="utf-8")
    public_callables = {
        name
        for name, value in vars(KisBalanceClient).items()
        if not name.startswith("_") and callable(value)
    }

    assert public_callables == {"fetch_balance"}
    assert "openapivts" not in source
    assert "VTTC8434R" not in source
    assert "order-cash" not in source
    assert "order-rvsecncl" not in source
    assert "hashkey" not in source.lower()
    assert ".post(" not in source
