"""Unauthenticated, bounded HTTPS access to the public KIS stock master archives."""

from __future__ import annotations

import io
import time
import zipfile
import zlib

import httpx

from phalanx.discovery.errors import DiscoveryError
from phalanx.discovery.provider import Download
from phalanx.domain.discovery import Market, ParsedMaster
from phalanx.kis.master_parsing import parse_master
from phalanx.kis.master_schema import PARSER_VERSION, SCHEMA_VERSION

MAX_DOWNLOAD_BYTES = 8 * 1024 * 1024
MAX_MASTER_BYTES = 32 * 1024 * 1024
MAX_DOWNLOAD_SECONDS = 60.0
DOWNLOAD_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


class KisMasterProvider:
    name = "kis-public-master"
    schema_version = SCHEMA_VERSION
    parser_version = PARSER_VERSION

    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        self._transport = transport

    def source_url(self, market: Market) -> str:
        return (
            f"https://new.real.download.dws.co.kr/common/master/{market.value.lower()}_code.mst.zip"
        )

    def download(self, market: Market) -> Download:
        deadline = time.monotonic() + MAX_DOWNLOAD_SECONDS

        def check_deadline() -> None:
            if time.monotonic() > deadline:
                raise DiscoveryError(
                    "DOWNLOAD_TIMEOUT", "마스터 다운로드 제한 시간을 초과했습니다."
                )

        try:
            with (
                httpx.Client(
                    timeout=DOWNLOAD_TIMEOUT,
                    verify=True,
                    follow_redirects=False,
                    transport=self._transport,
                ) as client,
                client.stream(
                    "GET", self.source_url(market), headers={"Accept-Encoding": "identity"}
                ) as response,
            ):
                check_deadline()
                response.raise_for_status()
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise DiscoveryError("HTTP_ENCODING", "지원하지 않는 HTTP 압축입니다.")
                size_header = response.headers.get("content-length")
                if size_header is not None and (
                    not size_header.isdecimal() or int(size_header) > MAX_DOWNLOAD_BYTES
                ):
                    raise DiscoveryError(
                        "DOWNLOAD_SIZE", "다운로드 크기 제한 또는 Content-Length 오류"
                    )
                payload = bytearray()
                # HTTP encoding was rejected above. Without chunk_size, identity bytes
                # reach these checks per receive, without waiting for a 64 KiB buffer.
                for chunk in response.iter_bytes():
                    check_deadline()
                    if len(payload) + len(chunk) > MAX_DOWNLOAD_BYTES:
                        raise DiscoveryError(
                            "DOWNLOAD_SIZE", "마스터 다운로드 크기 제한을 초과했습니다."
                        )
                    payload.extend(chunk)
                check_deadline()
                if size_header is not None and len(payload) != int(size_header):
                    raise DiscoveryError(
                        "DOWNLOAD_TRUNCATED", "다운로드 크기가 HTTP 메타데이터와 다릅니다."
                    )
                return Download(bytes(payload), response.headers.get("last-modified"))
        except httpx.TimeoutException:
            raise DiscoveryError(
                "DOWNLOAD_TIMEOUT", "마스터 다운로드 시간이 초과되었습니다."
            ) from None
        except httpx.HTTPError:
            raise DiscoveryError("DOWNLOAD_HTTP", "마스터 HTTPS 다운로드에 실패했습니다.") from None

    def unpack(self, market: Market, payload: bytes) -> bytes:
        expected_name = f"{market.value.lower()}_code.mst"
        if len(payload) > MAX_DOWNLOAD_BYTES:
            raise DiscoveryError("DOWNLOAD_SIZE", "ZIP 크기 제한을 초과했습니다.")
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                entries = archive.infolist()
                if len(entries) != 1 or entries[0].filename != expected_name:
                    raise DiscoveryError(
                        "ZIP_MEMBERS", "ZIP에 예상한 마스터 파일 하나만 있어야 합니다."
                    )
                entry = entries[0]
                if entry.file_size > MAX_MASTER_BYTES or entry.flag_bits & 1:
                    raise DiscoveryError(
                        "ZIP_LIMIT", "마스터 압축 해제 크기 제한 또는 암호화 ZIP 오류"
                    )
                # Never extract paths. Bound actual decompressed reads as well as ZIP metadata.
                with archive.open(entry) as source:
                    result = source.read(MAX_MASTER_BYTES + 1)
                if len(result) > MAX_MASTER_BYTES or len(result) != entry.file_size:
                    raise DiscoveryError("ZIP_LIMIT", "마스터 압축 해제 크기가 올바르지 않습니다.")
                return result
        except (
            zipfile.BadZipFile,
            zlib.error,
            RuntimeError,
            NotImplementedError,
            EOFError,
            OSError,
        ):
            raise DiscoveryError(
                "ZIP_INVALID", "손상되었거나 지원하지 않는 ZIP 파일입니다."
            ) from None

    def parse(self, market: Market, payload: bytes) -> ParsedMaster:
        return parse_master(market, payload)
