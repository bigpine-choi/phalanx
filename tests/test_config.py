from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from pydantic import ValidationError

from phalanx.config import ConfigError, KisCredentials, load_kis_credentials

APP_KEY = "synthetic-app-key"
APP_SECRET = "synthetic-secret=with=equals"
ACCOUNT_NUMBER = "12345678-01"


def _credential_contents(**updates: str) -> str:
    values = {
        "PHALANX_KIS_APP_KEY": APP_KEY,
        "PHALANX_KIS_APP_SECRET": APP_SECRET,
        "PHALANX_KIS_ACCOUNT_NUMBER": ACCOUNT_NUMBER,
    }
    values.update(updates)
    return "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"


def _write_private_file(path: Path, contents: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, contents.encode("utf-8"))
    finally:
        os.close(descriptor)


def test_external_credentials_file_loads_and_preserves_equals_in_values(tmp_path: Path) -> None:
    credentials_path = tmp_path / "config" / "phalanx" / "credentials.env"
    _write_private_file(credentials_path, "# real account only\n" + _credential_contents())

    credentials = load_kis_credentials(credentials_path)

    assert credentials.app_key.get_secret_value() == APP_KEY
    assert credentials.app_secret.get_secret_value() == APP_SECRET
    assert credentials.account_number.get_secret_value() == ACCOUNT_NUMBER


def test_project_dotenv_and_process_environment_are_never_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".env").write_text(
        _credential_contents(
            PHALANX_KIS_APP_KEY="project-dotenv-key",
            PHALANX_KIS_APP_SECRET="project-dotenv-secret",
            PHALANX_KIS_ACCOUNT_NUMBER="99999999-99",
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(project)
    monkeypatch.setenv("PHALANX_KIS_APP_KEY", "process-environment-key")
    monkeypatch.setenv("PHALANX_KIS_APP_SECRET", "process-environment-secret")
    monkeypatch.setenv("PHALANX_KIS_ACCOUNT_NUMBER", "88888888-88")

    external_path = tmp_path / "external" / "credentials.env"
    _write_private_file(external_path, _credential_contents())

    credentials = load_kis_credentials(external_path)

    assert credentials.app_key.get_secret_value() == APP_KEY
    assert credentials.account_number.get_secret_value() == ACCOUNT_NUMBER


def test_missing_default_file_does_not_create_any_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_home = tmp_path / "unused-home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    with pytest.raises(ConfigError, match="will not create"):
        load_kis_credentials()

    assert not fake_home.exists()


@pytest.mark.parametrize(
    ("directory_mode", "file_mode"),
    ((0o755, 0o600), (0o700, 0o640)),
)
def test_credentials_require_exact_directory_and_file_permissions(
    tmp_path: Path, directory_mode: int, file_mode: int
) -> None:
    credentials_path = tmp_path / "config" / "credentials.env"
    _write_private_file(credentials_path, _credential_contents())
    credentials_path.parent.chmod(directory_mode)
    credentials_path.chmod(file_mode)

    with pytest.raises(ConfigError):
        load_kis_credentials(credentials_path)

    assert stat.S_IMODE(credentials_path.parent.stat().st_mode) == directory_mode
    assert stat.S_IMODE(credentials_path.stat().st_mode) == file_mode


def test_credentials_require_current_effective_user_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    credentials_path = tmp_path / "config" / "credentials.env"
    _write_private_file(credentials_path, _credential_contents())
    monkeypatch.setattr("phalanx.config.os.geteuid", lambda: os.getuid() + 1)

    with pytest.raises(ConfigError):
        load_kis_credentials(credentials_path)


def test_credentials_reject_symbolic_link_directory(tmp_path: Path) -> None:
    actual_directory = tmp_path / "actual"
    actual_path = actual_directory / "credentials.env"
    _write_private_file(actual_path, _credential_contents())
    linked_directory = tmp_path / "linked"
    linked_directory.symlink_to(actual_directory, target_is_directory=True)

    with pytest.raises(ConfigError):
        load_kis_credentials(linked_directory / "credentials.env")


def test_credentials_reject_symbolic_link_file(tmp_path: Path) -> None:
    credentials_directory = tmp_path / "config"
    actual_path = credentials_directory / "actual.env"
    _write_private_file(actual_path, _credential_contents())
    linked_path = credentials_directory / "credentials.env"
    linked_path.symlink_to(actual_path)

    with pytest.raises(ConfigError):
        load_kis_credentials(linked_path)


@pytest.mark.parametrize(
    "contents",
    (
        "PHALANX_KIS_APP_KEY=key\nPHALANX_KIS_APP_SECRET=secret\n",
        _credential_contents(PHALANX_KIS_APP_SECRET="   "),
        _credential_contents() + "PHALANX_KIS_APP_KEY=duplicate\n",
        _credential_contents() + "UNKNOWN=value\n",
        _credential_contents() + "not-an-assignment\n",
    ),
)
def test_credentials_reject_missing_empty_duplicate_unknown_and_malformed_rows(
    tmp_path: Path, contents: str
) -> None:
    credentials_path = tmp_path / "config" / "credentials.env"
    _write_private_file(credentials_path, contents)

    with pytest.raises(ConfigError) as error:
        load_kis_credentials(credentials_path)

    assert APP_KEY not in str(error.value)
    assert APP_SECRET not in str(error.value)
    assert ACCOUNT_NUMBER not in str(error.value)


@pytest.mark.parametrize("account_number", ("1234567801", "1234567-01", "12345678-1"))
def test_account_number_requires_eight_digits_hyphen_two_digits(account_number: str) -> None:
    with pytest.raises(ValidationError) as error:
        KisCredentials(
            app_key=APP_KEY,
            app_secret=APP_SECRET,
            account_number=account_number,
        )

    error_text = str(error.value)
    assert APP_KEY not in error_text
    assert APP_SECRET not in error_text
    assert account_number not in error_text


def test_account_number_is_split_and_masked_without_public_plaintext() -> None:
    credentials = KisCredentials(
        app_key=APP_KEY,
        app_secret=APP_SECRET,
        account_number=ACCOUNT_NUMBER,
    )

    assert credentials.cano == "12345678"
    assert credentials.acnt_prdt_cd == "01"
    assert credentials.masked_account_number == "1234****-**"
    for display in (str(credentials), repr(credentials)):
        assert APP_KEY not in display
        assert APP_SECRET not in display
        assert ACCOUNT_NUMBER not in display


def test_credentials_reject_extra_fields_without_disclosing_secrets() -> None:
    with pytest.raises(ValidationError) as error:
        KisCredentials(
            app_key=APP_KEY,
            app_secret=APP_SECRET,
            account_number=ACCOUNT_NUMBER,
            environment="real",
        )

    display = f"{error.value!s} {error.value!r}"
    assert APP_KEY not in display
    assert APP_SECRET not in display
    assert ACCOUNT_NUMBER not in display


@pytest.mark.parametrize("field_name", ("app_key", "app_secret", "account_number"))
def test_credentials_reject_blank_values_without_disclosing_them(field_name: str) -> None:
    values = {
        "app_key": APP_KEY,
        "app_secret": APP_SECRET,
        "account_number": ACCOUNT_NUMBER,
    }
    values[field_name] = "   "

    with pytest.raises(ValidationError) as error:
        KisCredentials(**values)

    display = f"{error.value!s} {error.value!r}"
    assert APP_KEY not in display
    assert APP_SECRET not in display
    assert ACCOUNT_NUMBER not in display


def test_explicit_test_path_never_resolves_the_real_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    credentials_path = tmp_path / "config" / "credentials.env"
    _write_private_file(credentials_path, _credential_contents())

    def fail_home(cls: type[Path]) -> Path:
        raise AssertionError("Path.home must not be called for an injected test path")

    monkeypatch.setattr(Path, "home", classmethod(fail_home))

    assert load_kis_credentials(credentials_path).masked_account_number == "1234****-**"
