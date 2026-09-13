"""One shared HTTP client, token manager and pacer per sequential history run."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx

from phalanx.config import load_kis_credentials
from phalanx.kis import KisTokenManager
from phalanx.kis.market_data_client import KisDailyPriceClient, KisRequestPacer
from phalanx.market_data.history.provider import KisHistoryReader
from phalanx.market_data.service import DailyBarReader


@contextmanager
def production_history_reader(
    *,
    credentials_path: Path | None = None,
    token_cache_path: Path | None = None,
    transport: httpx.BaseTransport | None = None,
    request_pacer: KisRequestPacer | None = None,
) -> Iterator[DailyBarReader]:
    credentials = load_kis_credentials(credentials_path)
    timeout = httpx.Timeout(10.0, connect=5.0)
    with httpx.Client(transport=transport, timeout=timeout) as http_client:
        token_manager = KisTokenManager(
            credentials, cache_path=token_cache_path, client=http_client, timeout=timeout
        )
        client = KisDailyPriceClient(
            credentials,
            token_manager,
            client=http_client,
            timeout=timeout,
            request_pacer=request_pacer if request_pacer is not None else KisRequestPacer(),
        )
        yield KisHistoryReader(client)
