"""Create synthetic history/features/selection through the production services.

Run from the repository root with PYTHONPATH=tests. Never uses real market data.
"""

import argparse
from pathlib import Path

from allocation_input_helpers import create_inputs, make_view


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--case", choices=("ready", "short-history"), default="ready")
    args = parser.parse_args()
    directory = args.directory.absolute()
    # Require a new directory so repeated examples cannot alter existing inputs.
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    count = 505 if args.case == "ready" else 504
    repository, selection_path, _, _ = create_inputs(
        directory, make_view(counts=(count, count), failed=True)
    )
    print(f"selection: {selection_path}")
    print(f"history-db: {repository.path}")
    print(f"case: {args.case}; synthetic inputs only")


if __name__ == "__main__":
    main()
