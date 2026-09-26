"""Native Windows entry point, independent of the aggregate CLI."""

from phalanx.desktop.runtime import main

if __name__ == "__main__":
    raise SystemExit(main())
