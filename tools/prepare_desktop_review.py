"""Package the actual uncommitted checkout, using a source-only allowlist.

No staging, git archive, secrets, user reports/research, caches or environments.
The manifest covers every payload member (not itself) with SHA-256.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOP_LEVEL = {"README.md", "pyproject.toml", "uv.lock", ".python-version", ".gitignore"}
# These exact public support files are needed by the source/test distribution.
# Do not broaden this into a suffix allowlist for settings, hex files or private docs.
PUBLIC_SUPPORT_FILES = {
    ".env.example",
    "docs/plans/kis-account-snapshot.md",
    "tests/fixtures/discovery/kospi.hex",
    "tests/fixtures/discovery/kosdaq.hex",
}
EMPTY_TEMPLATE_KEYS = {
    "PHALANX_KIS_APP_KEY",
    "PHALANX_KIS_APP_SECRET",
    "PHALANX_KIS_ACCOUNT_NUMBER",
}
PREFIXES = ("src/", "tests/", "examples/", "tools/")
SOURCE_SUFFIXES = {".py", ".json", ".gz", ".html", ".css", ".js", ".md", ".txt"}
PRIVATE_PARTS = {"__pycache__", ".git", ".venv", ".venv-windows", "venv", "reports", "research"}


def inside_without_symlinks(source: Path, root: Path) -> bool:
    try:
        source.relative_to(root)
    except ValueError:
        return False
    return not any(path.is_symlink() for path in (source, *source.parents) if path != root.parent)


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def allowed(name: str) -> bool:
    parts = Path(name).parts
    return (
        (
            name in TOP_LEVEL | PUBLIC_SUPPORT_FILES
            or name.startswith(PREFIXES)
            or name == "docs/windows-desktop.md"
        )
        and (name in TOP_LEVEL | PUBLIC_SUPPORT_FILES or Path(name).suffix in SOURCE_SUFFIXES)
        and not any(
            (part.startswith(".env") and name != ".env.example") or part in PRIVATE_PARTS
            for part in parts
        )
        and ".." not in parts
        and not Path(name).is_absolute()
    )


def empty_public_template(data: bytes) -> bool:
    """Only ship the public template if it still contains known empty settings."""
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return False
    assignments = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if separator != "=" or key not in EMPTY_TEMPLATE_KEYS or value:
            return False
        assignments.append(key)
    return len(assignments) == len(EMPTY_TEMPLATE_KEYS) and set(assignments) == EMPTY_TEMPLATE_KEYS


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument(
        "--evidence", type=Path, help="directory containing only synthetic captures/logs"
    )
    args = parser.parse_args()
    output = args.output.absolute()
    if output.exists():
        raise SystemExit("Review ZIP already exists; choose a new output.")
    names = set(git("ls-files", "-z").decode().split("\0"))
    untracked = git("ls-files", "--others", "--exclude-standard", "-z").decode().split("\0")
    names.update(untracked)
    payload: dict[str, bytes] = {}
    for name in sorted(names):
        source = ROOT / name
        if allowed(name) and source.is_file() and inside_without_symlinks(source, ROOT):
            data = source.read_bytes()
            if name == ".env.example" and not empty_public_template(data):
                raise SystemExit("Public .env.example must contain only the known empty settings.")
            payload[name] = data
    # Apply the same file policy to the patch: unrelated tracked credentials or
    # user material must never sneak in through an otherwise unrestricted diff.
    diff_paths = sorted(name for name in names if allowed(name))
    payload["WORKTREE.diff"] = git("diff", "--binary", "HEAD", "--", *diff_paths)
    payload["NEW_FILES.txt"] = (
        "\n".join(sorted(n for n in untracked if n in payload)) + "\n"
    ).encode()
    payload["REVIEW_CONTEXT.txt"] = args.context.read_bytes()
    payload["GIT_STATE.txt"] = (
        git("rev-parse", "HEAD") + git("branch", "--show-current") + git("status", "--short")
    )
    if args.evidence:
        for source in sorted(args.evidence.rglob("*")):
            if source.is_file() and inside_without_symlinks(source, args.evidence):
                if source.suffix.lower() not in {".png", ".json", ".txt", ".log", ".wav"}:
                    continue
                payload[f"evidence/{source.relative_to(args.evidence).as_posix()}"] = (
                    source.read_bytes()
                )
    manifest = "".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in sorted(payload.items())
    ).encode()
    payload["MANIFEST.sha256"] = manifest
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(payload.items()):
            archive.writestr(name, data)
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        for name, data in payload.items():
            assert archive.read(name) == data
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    print(f"{output}\n{len(payload)} members\nSHA256 {digest}")


if __name__ == "__main__":
    main()
