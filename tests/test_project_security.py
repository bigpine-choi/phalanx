from __future__ import annotations

import ast
import subprocess
import tomllib
from importlib.util import resolve_name
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _is_git_ignored(path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", "--no-index", path],
        cwd=ROOT,
        check=False,
    )
    return result.returncode == 0


def _parse_source(relative_path: str) -> ast.Module:
    path = ROOT / relative_path
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_modules(tree: ast.AST, module_name: str) -> set[str]:
    package = module_name.rpartition(".")[0]
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module is not None:
                modules.add(node.module)
            elif node.module is not None:
                modules.add(resolve_name(f"{'.' * node.level}{node.module}", package))
            else:
                modules.update(
                    resolve_name(f"{'.' * node.level}{alias.name}", package) for alias in node.names
                )
    return modules


def _assigned_expression(tree: ast.Module, name: str) -> ast.expr:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return node.value
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
            and node.value is not None
        ):
            return node.value
    raise AssertionError(f"{name} is not assigned at module scope")


def _named_class(tree: ast.Module, name: str) -> ast.ClassDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is not defined at module scope")


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


def test_documentation_keeps_default_snapshots_outside_repository() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    plan = (ROOT / "docs" / "plans" / "kis-account-snapshot.md").read_text(encoding="utf-8")
    external_snapshots = "~/.local/share/phalanx/snapshots/"

    for document in (readme, plan):
        assert external_snapshots in document
        assert "`runtime/snapshots/`에 JSON" not in document

    snapshot_source = (ROOT / "src" / "phalanx" / "snapshots.py").read_text(encoding="utf-8")
    assert "runtime/snapshots" not in snapshot_source
    assert "XDG_DATA_HOME" not in snapshot_source


def test_cli_entry_points_and_options_remain_read_only_and_fixed() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    cli_source = (ROOT / "src" / "phalanx" / "cli.py").read_text(encoding="utf-8")
    module_entry = (ROOT / "src" / "phalanx" / "__main__.py").read_text(encoding="utf-8")

    assert pyproject["project"]["scripts"]["phalanx"] == "phalanx.cli:main"
    assert "from phalanx.cli import main" in module_entry
    forbidden_options = ("--environment", "--paper", "--demo", "--real")
    assert all(option not in cli_source for option in forbidden_options)


def test_automated_tests_disable_network_access() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert "--disable-socket" in pyproject["tool"]["pytest"]["ini_options"]["addopts"]


def test_current_price_domain_and_service_have_no_outward_dependencies() -> None:
    guarded_sources = (
        ("src/phalanx/domain/market_data.py", "phalanx.domain.market_data"),
        ("src/phalanx/market_data/service.py", "phalanx.market_data.service"),
    )
    forbidden_module_prefixes = (
        "aiohttp",
        "httpcore",
        "httpx",
        "requests",
        "urllib.request",
        "websocket",
        "websockets",
        "phalanx.application",
        "phalanx.auth",
        "phalanx.cli",
        "phalanx.config",
        "phalanx.execution",
        "phalanx.kis",
        "phalanx.market_data.application",
        "phalanx.orders",
        "phalanx.portfolio.application",
        "phalanx.portfolio.private_json_storage",
        "phalanx.portfolio.report_storage",
        "phalanx.snapshots",
        "phalanx.trading",
    )

    for relative_path, module_name in guarded_sources:
        tree = _parse_source(relative_path)
        imported_modules = _imported_modules(tree, module_name)
        forbidden_imports = {
            module
            for module in imported_modules
            if any(
                module == prefix or module.startswith(f"{prefix}.")
                for prefix in forbidden_module_prefixes
            )
        }
        assert forbidden_imports == set(), f"{relative_path}: {sorted(forbidden_imports)}"
        assert not any(
            isinstance(node, ast.Call)
            and (
                (isinstance(node.func, ast.Name) and node.func.id == "__import__")
                or (
                    isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "importlib"
                    and node.func.attr == "import_module"
                )
            )
            for node in ast.walk(tree)
        ), f"{relative_path} must not dynamically import outward dependencies"


def test_current_price_adapter_is_fixed_get_only_without_trading_capabilities() -> None:
    tree = _parse_source("src/phalanx/kis/market_data_client.py")
    expected_path = "/uapi/domestic-stock/v1/quotations/inquire-price"
    expected_tr_id = "FHKST01010100"

    forbidden_adapter_imports = (
        "aiohttp",
        "requests",
        "websocket",
        "websockets",
        "phalanx.cli",
        "phalanx.execution",
        "phalanx.orders",
        "phalanx.portfolio",
        "phalanx.snapshots",
        "phalanx.trading",
    )
    imported_modules = _imported_modules(tree, "phalanx.kis.market_data_client")
    assert not {
        module
        for module in imported_modules
        if any(
            module == prefix or module.startswith(f"{prefix}.")
            for prefix in forbidden_adapter_imports
        )
    }

    assert ast.literal_eval(_assigned_expression(tree, "KIS_CURRENT_PRICE_PATH")) == expected_path
    assert ast.literal_eval(_assigned_expression(tree, "KIS_CURRENT_PRICE_TR_ID")) == expected_tr_id
    expected_url_expression = ast.parse(
        'f"{KIS_REAL_BASE_URL}{KIS_CURRENT_PRICE_PATH}"',
        mode="eval",
    ).body
    assert ast.dump(
        _assigned_expression(tree, "KIS_CURRENT_PRICE_URL"),
        include_attributes=False,
    ) == ast.dump(expected_url_expression, include_attributes=False)

    client_class = _named_class(tree, "KisCurrentPriceClient")
    public_methods = {
        node.name
        for node in client_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
    }
    assert public_methods == {"fetch_current_price"}

    referenced_tr_ids = {
        node.id
        for node in ast.walk(client_class)
        if isinstance(node, ast.Name) and node.id.endswith("_TR_ID")
    }
    assert referenced_tr_ids == {"KIS_CURRENT_PRICE_TR_ID"}
    referenced_urls = {
        node.id
        for node in ast.walk(client_class)
        if isinstance(node, ast.Name) and node.id.endswith("_URL")
    }
    assert referenced_urls == {"KIS_CURRENT_PRICE_URL"}

    dynamic_or_mutating_http_calls = [
        node
        for node in ast.walk(client_class)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"delete", "patch", "post", "put", "request", "send", "stream"}
    ]
    assert dynamic_or_mutating_http_calls == []

    fixed_get_calls = [
        node
        for node in ast.walk(client_class)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and node.args
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == "KIS_CURRENT_PRICE_URL"
    ]
    assert len(fixed_get_calls) == 1
    client_get_calls = [
        node
        for node in ast.walk(client_class)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "client"
    ]
    assert client_get_calls == fixed_get_calls
    assert {keyword.arg for keyword in fixed_get_calls[0].keywords}.isdisjoint(
        {"content", "data", "files", "json"}
    )
    follow_redirects = next(
        keyword.value
        for keyword in fixed_get_calls[0].keywords
        if keyword.arg == "follow_redirects"
    )
    assert ast.literal_eval(follow_redirects) is False

    constructor = next(
        node
        for node in client_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "__init__"
    )
    constructor_parameters = {
        argument.arg
        for argument in (
            *constructor.args.posonlyargs,
            *constructor.args.args,
            *constructor.args.kwonlyargs,
        )
    }
    assert constructor_parameters.isdisjoint(
        {"base_url", "endpoint", "http_method", "method", "path", "tr_id", "url"}
    )

    forbidden_endpoint_literals = {
        "/uapi/domestic-stock/v1/trading/inquire-psbl-order",
        "/uapi/domestic-stock/v1/trading/order-cash",
        "/uapi/domestic-stock/v1/trading/order-rvsecncl",
        "/uapi/hashkey",
    }
    string_literals = {
        node.value
        for node in ast.walk(client_class)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert string_literals.isdisjoint(forbidden_endpoint_literals)
    assert "hashkey" not in {value.casefold() for value in string_literals}
    assert not any(value.startswith(("ws://", "wss://")) for value in string_literals)


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
