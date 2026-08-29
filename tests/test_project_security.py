from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _is_git_ignored(path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", "--no-index", path],
        cwd=ROOT,
        check=False,
    )
    return result.returncode == 0


def test_secret_and_runtime_paths_are_ignored() -> None:
    ignored_paths = (
        ".env",
        ".env.local",
        "kis_devlp.yaml",
        "secrets/kis.txt",
        "runtime/token-cache/kis-access-token.json",
        "runtime/token-cache/.token.tmp",
        "runtime/snapshots/account.json",
    )

    assert all(_is_git_ignored(path) for path in ignored_paths)
    assert not _is_git_ignored(".env.example")


def test_env_example_has_only_empty_real_account_settings() -> None:
    assignments = {}
    for raw_line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        assert separator == "="
        assignments[key] = value

    assert assignments == {
        "PHALANX_KIS_APP_KEY": "",
        "PHALANX_KIS_APP_SECRET": "",
        "PHALANX_KIS_ACCOUNT_NUMBER": "",
    }


def test_documentation_requires_external_credentials_file() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    plan = (ROOT / "docs" / "plans" / "kis-account-snapshot.md").read_text(encoding="utf-8")

    assert "~/.config/phalanx/credentials.env" in readme
    assert "~/.config/phalanx/credentials.env" in plan
    assert "프로젝트 루트의 `.env` 파일은 저장하거나 읽지 않습니다" in readme
    assert "cp .env.example .env" not in readme
    assert "프로젝트 루트에서 `.env`를 탐색하거나 읽지 않는다" in plan
    assert "dotenv 자동 탐색을 사용하지 않는다" in plan

    setup_commands = (
        'install -d -m 700 "$HOME/.config/phalanx"',
        'install -m 600 .env.example "$HOME/.config/phalanx/credentials.env"',
    )
    for command in setup_commands:
        assert command in readme
        assert command in plan


def test_documentation_requires_private_credential_permissions() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    plan = (ROOT / "docs" / "plans" / "kis-account-snapshot.md").read_text(encoding="utf-8")

    for document in (readme, plan):
        assert "0700" in document or "`700`" in document
        assert "0600" in document or "`600`" in document

    assert "자격증명 경로가 없으면" in plan
    assert "자동 생성하지 않고" in plan


def test_documentation_keeps_default_token_cache_outside_repository() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    plan = (ROOT / "docs" / "plans" / "kis-account-snapshot.md").read_text(encoding="utf-8")
    external_cache = "~/.cache/phalanx/token-cache/kis-access-token.json"

    for document in (readme, plan):
        assert external_cache in document
        assert "`runtime/token-cache/`의 안전성" not in document

    assert "XDG_CACHE_HOME" in readme
    assert "기존 `~/.cache`의 권한은 변경하지 않는다" in plan


def test_automated_tests_disable_network_access() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert "--disable-socket" in pyproject["tool"]["pytest"]["ini_options"]["addopts"]


def test_source_has_no_paper_or_order_endpoints() -> None:
    forbidden_fragments = (
        "openapivts.koreainvestment.com",
        "VTTC8434R",
        "/uapi/domestic-stock/v1/trading/order-cash",
        "/uapi/domestic-stock/v1/trading/order-rvsecncl",
        "/uapi/hashkey",
    )
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in (ROOT / "src" / "phalanx").rglob("*.py")
    )

    assert all(fragment not in source for fragment in forbidden_fragments)


def test_readme_documents_read_only_contract() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    required_statements = (
        "실전투자 환경만 지원",
        "READ ONLY",
        "예수금 총액",
        "orderable_cash",
        "자동 테스트와 CI에서는 실제 한국투자증권 API를 호출하지 않습니다",
    )
    assert all(statement in readme for statement in required_statements)
