from __future__ import annotations

import hashlib
import importlib.util
import sys
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

PUBLIC_FILES = {
    ".env.example": (
        b"PHALANX_KIS_APP_KEY=\nPHALANX_KIS_APP_SECRET=\nPHALANX_KIS_ACCOUNT_NUMBER=\n"
    ),
    "docs/plans/kis-account-snapshot.md": b"# Existing public plan\n",
    "tests/fixtures/discovery/kospi.hex": b"4b4f535049\n",
    "tests/fixtures/discovery/kosdaq.hex": b"4b4f53444151\n",
}


def _review_tool() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "tools" / "prepare_desktop_review.py"
    spec = importlib.util.spec_from_file_location("desktop_review_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bundle_contains_worktree_bytes_and_filters_private_patch_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _review_tool()
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "src").mkdir()
    (root / "src" / "existing.py").write_bytes(b"# modified working tree\n")
    (root / "src" / "new.py").write_bytes(b"# untracked addition\n")
    for name, data in PUBLIC_FILES.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (root / ".env").write_text("not-for-archive", encoding="utf-8")
    (root / "src" / ".env.local").write_text("also-private", encoding="utf-8")
    (root / "reports").mkdir()
    (root / "reports" / "user.json").write_text("private-data", encoding="utf-8")
    context = tmp_path / "context.txt"
    context.write_text("synthetic test context", encoding="utf-8")
    output = tmp_path / "review.zip"
    monkeypatch.setattr(tool, "ROOT", root)

    def git(*args: str) -> bytes:
        if args[:2] == ("ls-files", "-z"):
            return (
                b"src/existing.py\0.env\0src/.env.local\0reports/user.json\0"
                + "\0".join(PUBLIC_FILES).encode()
                + b"\0"
            )
        if args[0] == "ls-files":
            return b"src/new.py\0"
        if args[0] == "diff":
            assert args == (
                "diff",
                "--binary",
                "HEAD",
                "--",
                *sorted(["src/existing.py", "src/new.py", *PUBLIC_FILES]),
            )
            return b"synthetic source-only diff\n"
        return b"synthetic-git-state\n"

    monkeypatch.setattr(tool, "git", git)
    monkeypatch.setattr(
        sys,
        "argv",
        ["prepare_desktop_review.py", "--output", str(output), "--context", str(context)],
    )
    tool.main()
    with zipfile.ZipFile(output) as archive:
        assert archive.read("src/existing.py") == b"# modified working tree\n"
        assert archive.read("src/new.py") == b"# untracked addition\n"
        assert archive.read("NEW_FILES.txt") == b"src/new.py\n"
        for name, data in PUBLIC_FILES.items():
            assert archive.read(name) == data
        assert not any(
            (".env" in name and name != ".env.example") or name.startswith("reports/")
            for name in archive.namelist()
        )
        for line in archive.read("MANIFEST.sha256").decode().splitlines():
            expected, name = line.split("  ", 1)
            assert hashlib.sha256(archive.read(name)).hexdigest() == expected


@pytest.mark.parametrize(
    "name",
    [
        "reports/synthetic-looking.json",
        "research/test.py",
        ".env",
        "tests/.env.private",
        ".env.example.local",
        "tests/.env.example",
        "tests/fixtures/discovery/private.hex",
        "docs/plans/user-research.md",
        "src/.venv/library.py",
        "tools/.venv-windows/example.py",
        "tests/__pycache__/test.pyc",
        "src/../secret.txt",
        "/src/absolute.py",
        "tools/private.sqlite3",
    ],
)
def test_review_policy_excludes_private_and_non_source_members(name: str) -> None:
    assert not _review_tool().allowed(name)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlink creation without privileges")
def test_review_rejects_symlinked_ancestor(tmp_path: Path) -> None:
    tool = _review_tool()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("not a source file", encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()
    (root / "src").symlink_to(outside, target_is_directory=True)
    assert not tool.inside_without_symlinks(root / "src" / "secret.py", root)


@pytest.mark.parametrize(
    "content",
    [
        PUBLIC_FILES[".env.example"].replace(b"APP_KEY=", b"APP_KEY=secret"),
        PUBLIC_FILES[".env.example"] + b"PRIVATE_SETTING=\n",
        PUBLIC_FILES[".env.example"] + b"PHALANX_KIS_APP_KEY=\n",
        b"PHALANX_KIS_APP_KEY=\n",
        b"\xff",
    ],
)
def test_bundle_rejects_nonempty_or_changed_settings_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: bytes
) -> None:
    tool = _review_tool()
    root = tmp_path / "checkout"
    root.mkdir()
    (root / ".env.example").write_bytes(content)
    output = tmp_path / "review.zip"
    monkeypatch.setattr(tool, "ROOT", root)
    monkeypatch.setattr(tool, "git", lambda *args: b".env.example\0")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prepare_desktop_review.py",
            "--output",
            str(output),
            "--context",
            str(tmp_path / "context.txt"),
        ],
    )
    with pytest.raises(SystemExit, match="only the known empty settings"):
        tool.main()
    assert not output.exists()
