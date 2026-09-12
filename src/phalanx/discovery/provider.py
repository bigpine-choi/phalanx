"""Provider contracts and byte artifacts, independent of transport and storage."""

from dataclasses import dataclass
from typing import Protocol

from phalanx.domain.discovery import Market, ParsedMaster


@dataclass(frozen=True)
class Download:
    payload: bytes
    last_modified: str | None = None


class MasterProvider(Protocol):
    name: str
    schema_version: str
    parser_version: str

    def source_url(self, market: Market) -> str: ...

    def download(self, market: Market) -> Download: ...

    def unpack(self, market: Market, payload: bytes) -> bytes: ...

    def parse(self, market: Market, payload: bytes) -> ParsedMaster: ...
