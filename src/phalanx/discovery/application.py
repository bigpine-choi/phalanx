"""Default composition without account configuration, credentials, or OAuth."""

from pathlib import Path

from phalanx.discovery.repository import SqliteDiscoveryRepository
from phalanx.discovery.service import DiscoveryService
from phalanx.kis.master_client import KisMasterProvider


def build_service(path: Path | None = None) -> DiscoveryService:
    return DiscoveryService(SqliteDiscoveryRepository(path), KisMasterProvider())
