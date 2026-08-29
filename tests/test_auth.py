from __future__ import annotations

import hashlib
import json
import os
import stat
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from phalanx.config import KisCredentials
from phalanx.kis.auth import KIS_TOKEN_URL, KisTokenManager
from phalanx.kis.errors import KisHttpError, KisProtocolError, KisTimeoutError, TokenCacheError

SEOUL = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 8, 29, 12, 0, 0, tzinfo=SEOUL)
APP_KEY = "synthetic-app-key"
APP_SECRET = "synthetic-app-secret"
ACCOUNT_NUMBER = "12345678-01"
ACCESS_TOKEN_VALUE = "synthetic-access-token"

Handler = Callable[[httpx.Request], httpx.Response]
ClientFactory = Callable[[Handler], httpx.Client]


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


def _credentials(app_key: str = APP_KEY) -> KisCredentials:
    return KisCredentials(
        app_key=app_key,
        app_secret=APP_SECRET,
        account_number=ACCOUNT_NUMBER,
    )


def _token_payload(
    *,
    access_token: str = ACCESS_TOKEN_VALUE,
    expires_at: datetime = NOW + timedelta(days=1),
    expires_in: object = 86400,
) -> dict[str, object]:
    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "access_token_token_expired": expires_at.strftime("%Y-%m-%d %H:%M:%S"),
        "expires_in": expires_in,
    }


def _json_handler(payload: object, status_code: int = 200) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        if payload is None:
            return httpx.Response(
                status_code,
                content=b"null",
                headers={"content-type": "application/json"},
                request=request,
            )
        return httpx.Response(status_code, json=payload, request=request)

    return handler


def _cache_path(tmp_path: Path) -> Path:
    return tmp_path / "runtime" / "token-cache" / "kis-access-token.json"


def _write_with_mode(path: Path, contents: str, mode: int) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        os.write(descriptor, contents.encode("utf-8"))
    finally:
        os.close(descriptor)


def test_oauth_uses_only_the_fixed_real_post_contract(
    tmp_path: Path, client_factory: ClientFactory
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_token_payload(), request=request)

    manager = KisTokenManager(
        _credentials(),
        cache_path=_cache_path(tmp_path),
        client=client_factory(handler),
        clock=lambda: NOW,
    )

    token = manager.get_access_token()

    assert token.access_token.get_secret_value() == ACCESS_TOKEN_VALUE
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == KIS_TOKEN_URL
    assert json.loads(request.content) == {
        "grant_type": "client_credentials",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
    }
    timeout = request.extensions["timeout"]
    assert isinstance(timeout, dict)
    assert all(value is not None for value in timeout.values())
    assert not hasattr(manager, "request")
    assert not hasattr(manager, "post")


def test_oauth_source_has_no_paper_url_or_environment_branch() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "src" / "phalanx" / "kis" / "auth.py"
    ).read_text(encoding="utf-8")

    forbidden = ("openapivts", "paper", "demo", "vps", "environment")
    assert all(fragment not in source.lower() for fragment in forbidden)
    assert "base_url:" not in source.lower()


def test_explicit_expiration_is_interpreted_in_asia_seoul(
    tmp_path: Path, client_factory: ClientFactory
) -> None:
    payload = _token_payload()
    payload.pop("expires_in")
    manager = KisTokenManager(
        _credentials(),
        cache_path=_cache_path(tmp_path),
        client=client_factory(_json_handler(payload)),
        clock=lambda: NOW,
    )

    token = manager.get_access_token()

    assert token.expires_at == NOW + timedelta(days=1)
    assert isinstance(token.expires_at.tzinfo, ZoneInfo)
    assert token.expires_at.tzinfo.key == "Asia/Seoul"


@pytest.mark.parametrize("expires_in", (0, -1, True, 86400.0, "86400", None))
def test_expires_in_must_be_a_positive_json_integer(
    tmp_path: Path, client_factory: ClientFactory, expires_in: object
) -> None:
    manager = KisTokenManager(
        _credentials(),
        cache_path=_cache_path(tmp_path),
        client=client_factory(_json_handler(_token_payload(expires_in=expires_in))),
        clock=lambda: NOW,
    )

    with pytest.raises(KisProtocolError, match="positive integer"):
        manager.get_access_token()


def test_expires_in_cannot_contradict_explicit_expiration_by_more_than_five_minutes(
    tmp_path: Path, client_factory: ClientFactory
) -> None:
    payload = _token_payload(expires_at=NOW + timedelta(hours=1), expires_in=1)
    manager = KisTokenManager(
        _credentials(),
        cache_path=_cache_path(tmp_path),
        client=client_factory(_json_handler(payload)),
        clock=lambda: NOW,
    )

    with pytest.raises(KisProtocolError, match="inconsistent"):
        manager.get_access_token()


@pytest.mark.parametrize(
    "expiration",
    ("2026-8-30 12:00:00", "2026-08-30T12:00:00", "2026-02-30 12:00:00", ""),
)
def test_explicit_expiration_requires_the_official_format_and_valid_datetime(
    tmp_path: Path, client_factory: ClientFactory, expiration: str
) -> None:
    payload = _token_payload()
    payload["access_token_token_expired"] = expiration
    manager = KisTokenManager(
        _credentials(),
        cache_path=_cache_path(tmp_path),
        client=client_factory(_json_handler(payload)),
        clock=lambda: NOW,
    )

    with pytest.raises(KisProtocolError):
        manager.get_access_token()


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    (
        ("access_token", ""),
        ("access_token", None),
        ("token_type", "   "),
        ("access_token_token_expired", None),
    ),
)
def test_oauth_rejects_missing_or_empty_required_fields(
    tmp_path: Path,
    client_factory: ClientFactory,
    field_name: str,
    field_value: object,
) -> None:
    payload = _token_payload()
    payload[field_name] = field_value
    manager = KisTokenManager(
        _credentials(),
        cache_path=_cache_path(tmp_path),
        client=client_factory(_json_handler(payload)),
        clock=lambda: NOW,
    )

    with pytest.raises(KisProtocolError):
        manager.get_access_token()


def test_oauth_rejects_an_actually_missing_required_field(
    tmp_path: Path, client_factory: ClientFactory
) -> None:
    payload = _token_payload()
    payload.pop("access_token")
    manager = KisTokenManager(
        _credentials(),
        cache_path=_cache_path(tmp_path),
        client=client_factory(_json_handler(payload)),
        clock=lambda: NOW,
    )

    with pytest.raises(KisProtocolError):
        manager.get_access_token()


@pytest.mark.parametrize("payload", ([], "not-an-object", 1, None))
def test_oauth_rejects_non_object_json(
    tmp_path: Path, client_factory: ClientFactory, payload: object
) -> None:
    manager = KisTokenManager(
        _credentials(),
        cache_path=_cache_path(tmp_path),
        client=client_factory(_json_handler(payload)),
        clock=lambda: NOW,
    )

    with pytest.raises(KisProtocolError, match="JSON object"):
        manager.get_access_token()


def test_oauth_maps_invalid_json_without_including_response_body(
    tmp_path: Path, client_factory: ClientFactory
) -> None:
    leaked_body = f"not-json {APP_KEY} {APP_SECRET} {ACCOUNT_NUMBER}"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=leaked_body, request=request)

    manager = KisTokenManager(
        _credentials(),
        cache_path=_cache_path(tmp_path),
        client=client_factory(handler),
        clock=lambda: NOW,
    )

    with pytest.raises(KisProtocolError) as error:
        manager.get_access_token()

    assert all(secret not in str(error.value) for secret in (APP_KEY, APP_SECRET, ACCOUNT_NUMBER))


def test_oauth_maps_http_error_without_including_response_body(
    tmp_path: Path, client_factory: ClientFactory
) -> None:
    leaked_body = f"failure {APP_KEY} {APP_SECRET} {ACCOUNT_NUMBER}"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=leaked_body, request=request)

    manager = KisTokenManager(
        _credentials(),
        cache_path=_cache_path(tmp_path),
        client=client_factory(handler),
        clock=lambda: NOW,
    )

    with pytest.raises(KisHttpError) as error:
        manager.get_access_token()

    display = f"{error.value!s} {error.value!r}"
    assert all(secret not in display for secret in (APP_KEY, APP_SECRET, ACCOUNT_NUMBER))
    assert leaked_body not in display


def test_oauth_maps_timeout_without_including_original_exception(
    tmp_path: Path, client_factory: ClientFactory
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(f"timeout {APP_SECRET}", request=request)

    manager = KisTokenManager(
        _credentials(),
        cache_path=_cache_path(tmp_path),
        client=client_factory(handler),
        clock=lambda: NOW,
    )

    with pytest.raises(KisTimeoutError) as error:
        manager.get_access_token()

    assert APP_SECRET not in str(error.value)


def test_access_token_display_is_secret_safe(tmp_path: Path, client_factory: ClientFactory) -> None:
    manager = KisTokenManager(
        _credentials(),
        cache_path=_cache_path(tmp_path),
        client=client_factory(_json_handler(_token_payload())),
        clock=lambda: NOW,
    )

    token = manager.get_access_token()

    assert ACCESS_TOKEN_VALUE not in str(token)
    assert ACCESS_TOKEN_VALUE not in repr(token)


def test_valid_cache_reuse_performs_zero_network_calls(
    tmp_path: Path, client_factory: ClientFactory
) -> None:
    cache_path = _cache_path(tmp_path)
    first_manager = KisTokenManager(
        _credentials(),
        cache_path=cache_path,
        client=client_factory(_json_handler(_token_payload())),
        clock=lambda: NOW,
    )
    first_token = first_manager.get_access_token()

    def unexpected_network(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected network call to {request.url}")

    second_manager = KisTokenManager(
        _credentials(),
        cache_path=cache_path,
        client=client_factory(unexpected_network),
        clock=lambda: NOW + timedelta(hours=1),
    )

    second_token = second_manager.get_access_token()

    assert second_token.access_token == first_token.access_token


def test_near_expiration_cache_is_refreshed(tmp_path: Path, client_factory: ClientFactory) -> None:
    cache_path = _cache_path(tmp_path)
    first_payload = _token_payload(
        access_token="near-expiration-token",
        expires_at=NOW + timedelta(minutes=6),
        expires_in=360,
    )
    KisTokenManager(
        _credentials(),
        cache_path=cache_path,
        client=client_factory(_json_handler(first_payload)),
        clock=lambda: NOW,
    ).get_access_token()

    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200, json=_token_payload(access_token="refreshed-token"), request=request
        )

    refreshed = KisTokenManager(
        _credentials(),
        cache_path=cache_path,
        client=client_factory(handler),
        clock=lambda: NOW + timedelta(minutes=2),
    ).get_access_token()

    assert calls == 1
    assert refreshed.access_token.get_secret_value() == "refreshed-token"


def test_app_key_fingerprint_mismatch_refreshes_cache(
    tmp_path: Path, client_factory: ClientFactory
) -> None:
    cache_path = _cache_path(tmp_path)
    KisTokenManager(
        _credentials("first-app-key"),
        cache_path=cache_path,
        client=client_factory(_json_handler(_token_payload(access_token="first-token"))),
        clock=lambda: NOW,
    ).get_access_token()

    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200, json=_token_payload(access_token="second-token"), request=request
        )

    refreshed = KisTokenManager(
        _credentials("second-app-key"),
        cache_path=cache_path,
        client=client_factory(handler),
        clock=lambda: NOW,
    ).get_access_token()

    assert calls == 1
    assert refreshed.access_token.get_secret_value() == "second-token"


def test_cache_directory_cache_and_lock_are_created_with_private_modes(
    tmp_path: Path, client_factory: ClientFactory
) -> None:
    cache_path = _cache_path(tmp_path)
    KisTokenManager(
        _credentials(),
        cache_path=cache_path,
        client=client_factory(_json_handler(_token_payload())),
        clock=lambda: NOW,
    ).get_access_token()

    assert stat.S_IMODE(cache_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(cache_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(cache_path.with_name(f"{cache_path.name}.lock").stat().st_mode) == 0o600


def test_atomic_temporary_file_is_private_from_creation(
    tmp_path: Path, client_factory: ClientFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_path = _cache_path(tmp_path)
    original_replace = os.replace
    observed_modes: list[int] = []

    def inspect_then_replace(
        source: str,
        destination: str,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        temporary_files = tuple(cache_path.parent.glob(f".{cache_path.name}.*.tmp"))
        assert len(temporary_files) == 1
        observed_modes.append(stat.S_IMODE(temporary_files[0].stat().st_mode))
        original_replace(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    monkeypatch.setattr("phalanx.kis.auth.os.replace", inspect_then_replace)
    KisTokenManager(
        _credentials(),
        cache_path=cache_path,
        client=client_factory(_json_handler(_token_payload())),
        clock=lambda: NOW,
    ).get_access_token()

    assert observed_modes == [0o600]


def test_atomic_save_failure_preserves_existing_cache(
    tmp_path: Path, client_factory: ClientFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_path = _cache_path(tmp_path)
    first_payload = _token_payload(
        access_token="existing-token",
        expires_at=NOW + timedelta(minutes=6),
        expires_in=360,
    )
    KisTokenManager(
        _credentials(),
        cache_path=cache_path,
        client=client_factory(_json_handler(first_payload)),
        clock=lambda: NOW,
    ).get_access_token()
    existing_contents = cache_path.read_bytes()

    def fail_replace(*args: object, **kwargs: object) -> None:
        raise OSError("synthetic atomic replace failure")

    monkeypatch.setattr("phalanx.kis.auth.os.replace", fail_replace)
    manager = KisTokenManager(
        _credentials(),
        cache_path=cache_path,
        client=client_factory(_json_handler(_token_payload(access_token="replacement-token"))),
        clock=lambda: NOW + timedelta(minutes=2),
    )

    with pytest.raises(TokenCacheError):
        manager.get_access_token()

    assert cache_path.read_bytes() == existing_contents
    assert not tuple(cache_path.parent.glob(f".{cache_path.name}.*.tmp"))


def test_corrupt_cache_is_a_safe_miss_and_is_replaced(
    tmp_path: Path, client_factory: ClientFactory
) -> None:
    cache_path = _cache_path(tmp_path)
    cache_path.parent.mkdir(mode=0o700, parents=True)
    _write_with_mode(cache_path, f"invalid-json {APP_SECRET}", 0o600)

    refreshed = KisTokenManager(
        _credentials(),
        cache_path=cache_path,
        client=client_factory(_json_handler(_token_payload(access_token="fresh-token"))),
        clock=lambda: NOW,
    ).get_access_token()

    assert refreshed.access_token.get_secret_value() == "fresh-token"
    assert APP_SECRET not in cache_path.read_text(encoding="utf-8")


def test_cache_json_contains_only_the_allowlisted_fields_and_app_key_hash(
    tmp_path: Path, client_factory: ClientFactory
) -> None:
    cache_path = _cache_path(tmp_path)
    KisTokenManager(
        _credentials(),
        cache_path=cache_path,
        client=client_factory(_json_handler(_token_payload())),
        clock=lambda: NOW,
    ).get_access_token()

    payload = json.loads(cache_path.read_text(encoding="utf-8"))

    assert set(payload) == {
        "schema_version",
        "access_token",
        "token_type",
        "expires_at",
        "app_key_fingerprint",
    }
    assert payload["app_key_fingerprint"] == hashlib.sha256(APP_KEY.encode()).hexdigest()
    serialized = json.dumps(payload)
    assert APP_KEY not in serialized
    assert APP_SECRET not in serialized
    assert ACCOUNT_NUMBER not in serialized


@pytest.mark.parametrize("unsafe_target", ("directory", "cache", "lock"))
def test_cache_rejects_symbolic_links(
    tmp_path: Path, client_factory: ClientFactory, unsafe_target: str
) -> None:
    cache_path = _cache_path(tmp_path)
    cache_directory = cache_path.parent
    actual_directory = tmp_path / "actual-cache"
    actual_directory.mkdir(mode=0o700)

    if unsafe_target == "directory":
        cache_directory.parent.mkdir(parents=True)
        cache_directory.symlink_to(actual_directory, target_is_directory=True)
    else:
        cache_directory.mkdir(mode=0o700, parents=True)
        target = actual_directory / "target"
        _write_with_mode(target, "{}", 0o600)
        unsafe_path = (
            cache_path
            if unsafe_target == "cache"
            else cache_path.with_name(f"{cache_path.name}.lock")
        )
        unsafe_path.symlink_to(target)

    manager = KisTokenManager(
        _credentials(),
        cache_path=cache_path,
        client=client_factory(_json_handler(_token_payload())),
        clock=lambda: NOW,
    )

    with pytest.raises(TokenCacheError):
        manager.get_access_token()


@pytest.mark.parametrize(
    ("target", "mode"),
    (("directory", 0o755), ("cache", 0o644), ("lock", 0o644)),
)
def test_cache_rejects_and_does_not_repair_unsafe_permissions(
    tmp_path: Path,
    client_factory: ClientFactory,
    target: str,
    mode: int,
) -> None:
    cache_path = _cache_path(tmp_path)
    cache_path.parent.mkdir(mode=0o700, parents=True)
    if target == "directory":
        cache_path.parent.chmod(mode)
        checked_path = cache_path.parent
    elif target == "cache":
        _write_with_mode(cache_path, "{}", mode)
        checked_path = cache_path
    else:
        checked_path = cache_path.with_name(f"{cache_path.name}.lock")
        _write_with_mode(checked_path, "", mode)

    manager = KisTokenManager(
        _credentials(),
        cache_path=cache_path,
        client=client_factory(_json_handler(_token_payload())),
        clock=lambda: NOW,
    )

    with pytest.raises(TokenCacheError):
        manager.get_access_token()

    assert stat.S_IMODE(checked_path.stat().st_mode) == mode


def test_cache_requires_current_effective_user_ownership(
    tmp_path: Path, client_factory: ClientFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_path = _cache_path(tmp_path)
    cache_path.parent.mkdir(mode=0o700, parents=True)
    monkeypatch.setattr("phalanx.kis.auth.os.geteuid", lambda: os.getuid() + 1)
    manager = KisTokenManager(
        _credentials(),
        cache_path=cache_path,
        client=client_factory(_json_handler(_token_payload())),
        clock=lambda: NOW,
    )

    with pytest.raises(TokenCacheError, match="owner"):
        manager.get_access_token()


def test_current_token_can_be_invalidated_conditionally(
    tmp_path: Path, client_factory: ClientFactory
) -> None:
    cache_path = _cache_path(tmp_path)
    manager = KisTokenManager(
        _credentials(),
        cache_path=cache_path,
        client=client_factory(_json_handler(_token_payload())),
        clock=lambda: NOW,
    )
    current = manager.get_access_token()

    assert manager.invalidate_if_current(current) is True
    assert not cache_path.exists()


def test_conditional_invalidation_preserves_a_newer_process_token(
    tmp_path: Path, client_factory: ClientFactory
) -> None:
    cache_path = _cache_path(tmp_path)
    first_manager = KisTokenManager(
        _credentials(),
        cache_path=cache_path,
        client=client_factory(_json_handler(_token_payload(access_token="first-token"))),
        clock=lambda: NOW,
    )
    first_token = first_manager.get_access_token()
    assert first_manager.invalidate_if_current(first_token) is True

    second_manager = KisTokenManager(
        _credentials(),
        cache_path=cache_path,
        client=client_factory(_json_handler(_token_payload(access_token="newer-token"))),
        clock=lambda: NOW,
    )
    newer_token = second_manager.get_access_token()

    assert first_manager.invalidate_if_current(first_token) is False
    assert cache_path.exists()
    assert newer_token.access_token.get_secret_value() in cache_path.read_text(encoding="utf-8")


def test_cache_lock_prevents_concurrent_duplicate_issuance(
    tmp_path: Path, client_factory: ClientFactory
) -> None:
    cache_path = _cache_path(tmp_path)
    calls = 0
    calls_lock = threading.Lock()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.05)
        return httpx.Response(200, json=_token_payload(), request=request)

    client = client_factory(handler)
    managers = (
        KisTokenManager(_credentials(), cache_path=cache_path, client=client, clock=lambda: NOW),
        KisTokenManager(_credentials(), cache_path=cache_path, client=client, clock=lambda: NOW),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        tokens = tuple(executor.map(lambda manager: manager.get_access_token(), managers))

    assert calls == 1
    assert all(token.access_token.get_secret_value() == ACCESS_TOKEN_VALUE for token in tokens)


def test_token_cache_errors_never_include_credentials_or_tokens(
    tmp_path: Path, client_factory: ClientFactory
) -> None:
    cache_path = _cache_path(tmp_path)
    cache_path.parent.mkdir(mode=0o700, parents=True)
    _write_with_mode(cache_path, ACCESS_TOKEN_VALUE, 0o644)
    manager = KisTokenManager(
        _credentials(),
        cache_path=cache_path,
        client=client_factory(_json_handler(_token_payload())),
        clock=lambda: NOW,
    )

    with pytest.raises(TokenCacheError) as error:
        manager.get_access_token()

    display = f"{error.value!s} {error.value!r}"
    secrets = (APP_KEY, APP_SECRET, ACCOUNT_NUMBER, ACCESS_TOKEN_VALUE)
    assert all(secret not in display for secret in secrets)
