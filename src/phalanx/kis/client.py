"""Read-only real-account KIS domestic-stock balance retrieval."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import httpx
from pydantic import ValidationError

from phalanx.config import KisCredentials
from phalanx.domain import AccountSnapshot, ApiPageEvidence, SnapshotEvidence
from phalanx.kis.auth import KIS_REAL_BASE_URL, AccessToken
from phalanx.kis.errors import (
    KisAuthError,
    KisBalanceAuthenticationError,
    KisBalanceHttpError,
    KisBalanceProtocolError,
    KisBalanceTimeoutError,
)
from phalanx.kis.parsing import ParsedBalancePage, parse_balance_page

KIS_BALANCE_PATH = "/uapi/domestic-stock/v1/trading/inquire-balance"
KIS_BALANCE_URL = f"{KIS_REAL_BASE_URL}{KIS_BALANCE_PATH}"
KIS_BALANCE_TR_ID = "TTTC8434R"

_CUSTOMER_TYPE = "P"
_DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_DEFAULT_MAX_PAGES = 10
_CONTINUATION_SIGNALS = frozenset({"M", "F"})
_TOKEN_EXPIRED_MESSAGE_CODES = frozenset({"EGW00123"})
_SUMMARY_WARNING = (
    "Account summaries differed across balance pages; the final page summary was used."
)
_REDACTED = "[REDACTED]"

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


class _TokenManager(Protocol):
    def get_access_token(self) -> AccessToken: ...

    def invalidate_if_current(self, token: AccessToken) -> bool: ...


@dataclass(frozen=True)
class _FetchedPage:
    parsed: ParsedBalancePage
    evidence: ApiPageEvidence


class KisBalanceClient:
    """Fetch a complete KIS balance without exposing a general HTTP surface.

    An injected ``httpx.Client`` remains owned by its caller and is never closed
    here. When no client is injected, one short-lived client is created and
    closed around each complete balance retrieval.
    """

    def __init__(
        self,
        credentials: KisCredentials,
        token_manager: _TokenManager,
        *,
        client: httpx.Client | None = None,
        timeout: httpx.Timeout | float = _DEFAULT_TIMEOUT,
        max_pages: int = _DEFAULT_MAX_PAGES,
        clock: Clock = _utc_now,
    ) -> None:
        if type(max_pages) is not int or max_pages < 1:
            raise ValueError("max_pages must be a positive integer")
        self._credentials = credentials
        self._token_manager = token_manager
        self._client = client
        self._timeout = timeout
        self._max_pages = max_pages
        self._clock = clock

    def fetch_balance(self) -> AccountSnapshot:
        """Fetch every balance page and return one deeply immutable result."""

        query_started_at = self._now("query start")
        if self._client is not None:
            return self._fetch_all_pages(self._client, query_started_at)
        with httpx.Client() as client:
            return self._fetch_all_pages(client, query_started_at)

    def _fetch_all_pages(
        self,
        client: httpx.Client,
        query_started_at: datetime,
    ) -> AccountSnapshot:
        pages: list[_FetchedPage] = []
        requested_cursors = {("", "")}
        cursor = ("", "")
        request_tr_cont = ""

        while True:
            page_number = len(pages) + 1
            fetched = self._fetch_page(
                client,
                page_number=page_number,
                cursor=cursor,
                request_tr_cont=request_tr_cont,
            )
            pages.append(fetched)

            if fetched.evidence.tr_cont not in _CONTINUATION_SIGNALS:
                break
            if page_number >= self._max_pages:
                raise KisBalanceProtocolError(
                    "The KIS balance response exceeded the configured page limit."
                )

            next_cursor = (
                fetched.parsed.ctx_area_fk100,
                fetched.parsed.ctx_area_nk100,
            )
            if not all(value.strip() for value in next_cursor):
                raise KisBalanceProtocolError(
                    "The KIS balance response requested continuation without complete cursors."
                )
            if next_cursor in requested_cursors:
                raise KisBalanceProtocolError("The KIS balance response repeated a cursor pair.")
            requested_cursors.add(next_cursor)
            cursor = next_cursor
            request_tr_cont = "N"

        query_completed_at = self._now("query completion")
        return self._combine_pages(pages, query_started_at, query_completed_at)

    def _fetch_page(
        self,
        client: httpx.Client,
        *,
        page_number: int,
        cursor: tuple[str, str],
        request_tr_cont: str,
    ) -> _FetchedPage:
        for attempt in range(2):
            token = self._get_access_token()
            response = self._send_request(
                client,
                token=token,
                cursor=cursor,
                request_tr_cont=request_tr_cont,
            )
            received_at = self._now("response receipt")
            response_body = response.content

            if response.status_code == 401:
                if attempt == 0:
                    self._invalidate_token(token)
                    continue
                raise KisBalanceAuthenticationError(
                    "The KIS balance request remained unauthorized after reauthentication."
                )
            if not 200 <= response.status_code < 300:
                raise KisBalanceHttpError(
                    f"The KIS balance request failed with HTTP {response.status_code}."
                )

            payload = self._decode_json(response_body)
            if self._is_expired_token_response(payload):
                if attempt == 0:
                    self._invalidate_token(token)
                    continue
                raise KisBalanceAuthenticationError(
                    "KIS rejected the renewed token for the balance request."
                )

            secrets = self._sensitive_values(token)
            parsed = parse_balance_page(payload, sensitive_values=secrets)
            raw_response_tr_cont = response.headers.get("tr_cont")
            if raw_response_tr_cont is None:
                raise KisBalanceProtocolError(
                    "The KIS balance response omitted the tr_cont header."
                )
            response_tr_cont = _mask_text(raw_response_tr_cont, secrets)
            try:
                evidence = ApiPageEvidence(
                    page_number=page_number,
                    received_at=received_at,
                    http_status=response.status_code,
                    tr_cont=response_tr_cont,
                    ctx_area_fk100=parsed.ctx_area_fk100,
                    ctx_area_nk100=parsed.ctx_area_nk100,
                    rt_cd=parsed.rt_cd,
                    msg_cd=parsed.msg_cd,
                    msg1=parsed.msg1,
                    response_body_sha256=hashlib.sha256(response_body).hexdigest(),
                    output1=parsed.raw_output1,
                    output2=parsed.raw_output2,
                    placeholder_rows=parsed.placeholder_rows,
                )
            except ValidationError:
                raise KisBalanceProtocolError(
                    "The KIS balance page evidence violated domain invariants."
                ) from None
            return _FetchedPage(parsed=parsed, evidence=evidence)

        raise AssertionError("the fixed authentication retry loop did not terminate")

    def _send_request(
        self,
        client: httpx.Client,
        *,
        token: AccessToken,
        cursor: tuple[str, str],
        request_tr_cont: str,
    ) -> httpx.Response:
        headers = {
            "authorization": f"Bearer {token.access_token.get_secret_value()}",
            "appkey": self._credentials.app_key.get_secret_value(),
            "appsecret": self._credentials.app_secret.get_secret_value(),
            "tr_id": KIS_BALANCE_TR_ID,
            "custtype": _CUSTOMER_TYPE,
            "tr_cont": request_tr_cont,
        }
        params = {
            "CANO": self._credentials.cano,
            "ACNT_PRDT_CD": self._credentials.acnt_prdt_cd,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "00",
            "CTX_AREA_FK100": cursor[0],
            "CTX_AREA_NK100": cursor[1],
        }
        try:
            return client.get(
                KIS_BALANCE_URL,
                headers=headers,
                params=params,
                timeout=self._timeout,
            )
        except httpx.TimeoutException:
            raise KisBalanceTimeoutError("The KIS balance request timed out.") from None
        except httpx.HTTPError:
            raise KisBalanceHttpError(
                "The KIS balance request failed before a response was received."
            ) from None

    def _get_access_token(self) -> AccessToken:
        try:
            return self._token_manager.get_access_token()
        except KisAuthError:
            raise KisBalanceAuthenticationError(
                "A KIS access token could not be obtained safely."
            ) from None

    def _invalidate_token(self, token: AccessToken) -> None:
        try:
            self._token_manager.invalidate_if_current(token)
        except KisAuthError:
            raise KisBalanceAuthenticationError(
                "The rejected KIS access token could not be invalidated safely."
            ) from None

    def _decode_json(self, response_body: bytes) -> object:
        try:
            return json.loads(response_body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise KisBalanceProtocolError("The KIS balance response was not valid JSON.") from None

    def _sensitive_values(self, token: AccessToken) -> tuple[str, ...]:
        return (
            self._credentials.app_key.get_secret_value(),
            self._credentials.app_secret.get_secret_value(),
            self._credentials.account_number.get_secret_value(),
            self._credentials.cano,
            token.access_token.get_secret_value(),
        )

    def _now(self, event: str) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise KisBalanceProtocolError(f"The {event} clock value must be timezone-aware.")
        return value

    @staticmethod
    def _is_expired_token_response(payload: object) -> bool:
        if not isinstance(payload, dict) or payload.get("rt_cd") == "0":
            return False
        message_code = payload.get("msg_cd")
        return isinstance(message_code, str) and message_code in _TOKEN_EXPIRED_MESSAGE_CODES

    def _combine_pages(
        self,
        pages: list[_FetchedPage],
        query_started_at: datetime,
        query_completed_at: datetime,
    ) -> AccountSnapshot:
        positions = tuple(position for page in pages for position in page.parsed.positions)
        zero_quantity_balances = tuple(
            position for page in pages for position in page.parsed.zero_quantity_balances
        )
        final_summary = pages[-1].parsed.summary
        summaries_differed = any(page.parsed.summary != final_summary for page in pages[:-1])
        warnings = (_SUMMARY_WARNING,) if summaries_differed else ()
        try:
            return AccountSnapshot(
                account_number_masked=self._credentials.masked_account_number,
                query_started_at=query_started_at,
                query_completed_at=query_completed_at,
                summary=final_summary,
                positions=positions,
                zero_quantity_balances=zero_quantity_balances,
                evidence=SnapshotEvidence(
                    pages=tuple(page.evidence for page in pages),
                    summary_consistency_warnings=warnings,
                ),
            )
        except ValidationError:
            raise KisBalanceProtocolError(
                "Combined KIS balance pages violate account snapshot invariants."
            ) from None


def _mask_text(value: str, secrets: tuple[str, ...]) -> str:
    masked = value
    for secret in sorted(set(secrets), key=len, reverse=True):
        if secret:
            masked = masked.replace(secret, _REDACTED)
    return masked


__all__ = [
    "KIS_BALANCE_PATH",
    "KIS_BALANCE_TR_ID",
    "KIS_BALANCE_URL",
    "KisBalanceClient",
]
