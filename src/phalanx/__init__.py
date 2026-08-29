"""Phalanx read-only account snapshot package."""


def main() -> None:
    """Backward-compatible package entry point."""

    from phalanx.cli import main as cli_main

    cli_main()


__all__ = ["main"]
