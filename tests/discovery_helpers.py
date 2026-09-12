"""Synthetic, independently positioned master fixtures; never import parser layouts."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import httpx

from phalanx.domain.discovery import Market
from phalanx.kis.master_client import KisMasterProvider

FIXTURES = Path(__file__).parent / "fixtures" / "discovery"


def master(market: Market = Market.KOSPI, patches: dict[int, bytes] | None = None) -> bytes:
    row = bytearray(bytes.fromhex((FIXTURES / f"{market.value.lower()}.hex").read_text()))
    for offset, value in (patches or {}).items():
        row[offset : offset + len(value)] = value
    return bytes(row)


def archive(market: Market, payload: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as output:
        output.writestr(f"{market.value.lower()}_code.mst", payload)
    return buffer.getvalue()


def provider(payloads: dict[Market, bytes | int] | None = None) -> KisMasterProvider:
    selected = payloads or {market: archive(market, master(market)) for market in Market}

    def respond(request: httpx.Request) -> httpx.Response:
        market = Market.KOSPI if request.url.path.endswith("/kospi_code.mst.zip") else Market.KOSDAQ
        value = selected[market]
        assert request.method == "GET"
        assert "authorization" not in request.headers
        assert request.extensions["timeout"] == {
            "connect": 5.0,
            "read": 15.0,
            "write": 15.0,
            "pool": 15.0,
        }
        if isinstance(value, int):
            return httpx.Response(value)
        return httpx.Response(
            200, content=value, headers={"Last-Modified": "Fri, 11 Sep 2026 22:00:00 GMT"}
        )

    return KisMasterProvider(transport=httpx.MockTransport(respond))
