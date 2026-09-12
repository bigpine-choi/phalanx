from __future__ import annotations

import io
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass

import httpx
import pytest
from discovery_helpers import archive, master, provider

import phalanx.kis.master_client as module
from phalanx.discovery.errors import DiscoveryError
from phalanx.domain.discovery import Market
from phalanx.kis.master_client import KisMasterProvider


@dataclass
class _Clock:
    now: float = 0.0

    def __call__(self) -> float:
        return self.now


class _TimedStream(httpx.SyncByteStream):
    def __init__(
        self, clock: _Clock, count: int, *, delay: float = 1.0, end_delay: float = 0.0
    ) -> None:
        self.clock = clock
        self.count = count
        self.delay = delay
        self.end_delay = end_delay
        self.consumed = 0
        self.closed = False

    def __iter__(self) -> Iterator[bytes]:
        for _ in range(self.count):
            self.clock.now += self.delay
            self.consumed += 1
            yield b"x"
        self.clock.now += self.end_delay

    def close(self) -> None:
        self.closed = True


def test_small_receives_check_deadline_before_consuming_entire_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Clock()
    monkeypatch.setattr(module.time, "monotonic", clock)
    stream = _TimedStream(clock, 120)
    response = httpx.Response(200, headers={"Content-Length": "120"}, stream=stream)
    source = KisMasterProvider(transport=httpx.MockTransport(lambda request: response))

    with pytest.raises(DiscoveryError) as error:
        source.download(Market.KOSPI)

    assert error.value.code == "DOWNLOAD_TIMEOUT"
    assert stream.consumed == 61  # One byte each second; no 64 KiB aggregation.
    assert stream.consumed < stream.count
    assert clock.now == 61.0
    assert response.is_closed and stream.closed


def test_deadline_after_headers_does_not_start_reading_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Clock()
    monkeypatch.setattr(module.time, "monotonic", clock)
    stream = _TimedStream(clock, 120)
    response = httpx.Response(200, stream=stream)

    def delayed_headers(request: httpx.Request) -> httpx.Response:
        clock.now = 61.0
        return response

    with pytest.raises(DiscoveryError) as error:
        KisMasterProvider(transport=httpx.MockTransport(delayed_headers)).download(Market.KOSPI)

    assert error.value.code == "DOWNLOAD_TIMEOUT"
    assert stream.consumed == 0
    assert response.is_closed and stream.closed


@pytest.mark.parametrize("count", [0, 1])
def test_deadline_at_end_of_stream_including_empty_body(
    monkeypatch: pytest.MonkeyPatch, count: int
) -> None:
    clock = _Clock()
    monkeypatch.setattr(module.time, "monotonic", clock)
    stream = _TimedStream(clock, count, end_delay=10.0)
    response = httpx.Response(200, headers={"Content-Length": str(count)}, stream=stream)

    def delayed_headers(request: httpx.Request) -> httpx.Response:
        clock.now = 55.0
        return response

    with pytest.raises(DiscoveryError) as error:
        KisMasterProvider(transport=httpx.MockTransport(delayed_headers)).download(Market.KOSPI)

    assert error.value.code == "DOWNLOAD_TIMEOUT"
    assert response.is_closed and stream.closed


def test_small_receives_complete_normally_within_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Clock()
    monkeypatch.setattr(module.time, "monotonic", clock)
    stream = _TimedStream(clock, 30)
    response = httpx.Response(
        200,
        headers={"Content-Length": "30", "Last-Modified": "Fri, 11 Sep 2026 22:00:00 GMT"},
        stream=stream,
    )
    result = KisMasterProvider(transport=httpx.MockTransport(lambda request: response)).download(
        Market.KOSPI
    )

    assert result.payload == b"x" * 30
    assert result.last_modified == "Fri, 11 Sep 2026 22:00:00 GMT"
    assert stream.consumed == 30
    assert response.is_closed and stream.closed


def test_small_receives_check_size_before_consuming_entire_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Clock()
    monkeypatch.setattr(module.time, "monotonic", clock)
    monkeypatch.setattr(module, "MAX_DOWNLOAD_BYTES", 4)
    stream = _TimedStream(clock, 120, delay=0.0)
    response = httpx.Response(200, stream=stream)

    with pytest.raises(DiscoveryError) as error:
        KisMasterProvider(transport=httpx.MockTransport(lambda request: response)).download(
            Market.KOSPI
        )

    assert error.value.code == "DOWNLOAD_SIZE"
    assert stream.consumed == 5
    assert response.is_closed and stream.closed


@pytest.mark.parametrize("market", list(Market))
def test_public_get_download_and_unpack(market: Market) -> None:
    source = provider()
    downloaded = source.download(market)
    assert downloaded.last_modified == "Fri, 11 Sep 2026 22:00:00 GMT"
    assert source.unpack(market, downloaded.payload) == master(market)


@pytest.mark.parametrize(
    "failure", [httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError]
)
def test_download_transport_failures_are_safe(failure: type[httpx.HTTPError]) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise failure("potentially unsafe remote error", request=request)

    with pytest.raises(DiscoveryError) as error:
        KisMasterProvider(transport=httpx.MockTransport(fail)).download(Market.KOSPI)
    assert "unsafe" not in str(error.value)
    assert error.value.code.startswith("DOWNLOAD_")


@pytest.mark.parametrize(
    ("status", "headers", "payload", "code"),
    [
        (500, {}, b"", "DOWNLOAD_HTTP"),
        (302, {"location": "https://example.org"}, b"", "DOWNLOAD_HTTP"),
        (200, {"content-length": "999999999"}, b"", "DOWNLOAD_SIZE"),
        (200, {"content-length": "-1"}, b"", "DOWNLOAD_SIZE"),
        (200, {"content-length": "10"}, b"a", "DOWNLOAD_TRUNCATED"),
    ],
)
def test_http_failures(status: int, headers: dict[str, str], payload: bytes, code: str) -> None:
    client = KisMasterProvider(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status, headers=headers, content=payload)
        )
    )
    with pytest.raises(DiscoveryError) as error:
        client.download(Market.KOSPI)
    assert error.value.code == code


def test_size_limit_applies_to_stream_without_length(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "MAX_DOWNLOAD_BYTES", 4)

    class Chunks(httpx.SyncByteStream):
        def __iter__(self):  # type: ignore[no-untyped-def]
            yield b"abc"
            yield b"def"

    client = KisMasterProvider(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=Chunks()))
    )
    with pytest.raises(DiscoveryError, match="크기 제한"):
        client.download(Market.KOSPI)


def test_download_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    times = iter([0.0, 100.0])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(times))
    with pytest.raises(DiscoveryError) as error:
        provider().download(Market.KOSPI)
    assert error.value.code == "DOWNLOAD_TIMEOUT"


@pytest.mark.parametrize("payload", [b"", b"not a zip", b"PK\x03\x04"])
def test_corrupt_archive(payload: bytes) -> None:
    with pytest.raises(DiscoveryError) as error:
        KisMasterProvider().unpack(Market.KOSPI, payload)
    assert error.value.code == "ZIP_INVALID"


@pytest.mark.parametrize(
    "names", [["../kospi_code.mst"], ["kosdaq_code.mst"], ["kospi_code.mst", "extra"], []]
)
def test_only_expected_member_is_accepted(names: list[str]) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as output:
        for name in names:
            output.writestr(name, b"contents")
    with pytest.raises(DiscoveryError) as error:
        KisMasterProvider().unpack(Market.KOSPI, buffer.getvalue())
    assert error.value.code == "ZIP_MEMBERS"


def test_duplicate_archive_members() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as output:
        output.writestr("kospi_code.mst", b"one")
        with pytest.warns(UserWarning):
            output.writestr("kospi_code.mst", b"two")
    with pytest.raises(DiscoveryError) as error:
        KisMasterProvider().unpack(Market.KOSPI, buffer.getvalue())
    assert error.value.code == "ZIP_MEMBERS"


def test_zip_decompression_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "MAX_MASTER_BYTES", 100)
    with pytest.raises(DiscoveryError) as error:
        KisMasterProvider().unpack(Market.KOSPI, archive(Market.KOSPI, b"0" * 1000))
    assert error.value.code == "ZIP_LIMIT"


def test_zip_crc_failure_is_reported() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as output:
        output.writestr("kospi_code.mst", b"known-content")
    corrupt = buffer.getvalue().replace(b"known-content", b"wrong-content")
    with pytest.raises(DiscoveryError) as error:
        KisMasterProvider().unpack(Market.KOSPI, corrupt)
    assert error.value.code == "ZIP_INVALID"
