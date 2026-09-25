"""Generate distinct synthetic prices and real features/selection, without live data.

Run from the repository root with PYTHONPATH=tests; choose a new directory.
"""

import argparse
from pathlib import Path

from allocation_targets_helpers import target_inputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument(
        "--case", choices=("ready", "four-assets", "five-assets", "short-history"), default="ready"
    )
    args = parser.parse_args()
    directory = args.directory.absolute()
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    size = {"four-assets": 4, "five-assets": 5}.get(args.case, 6)
    count = 504 if args.case == "short-history" else 505
    repository, selection_path, selection, _ = target_inputs(
        directory, size=size, count=count, failed_candidate=True
    )
    print(f"selection: {selection_path}")
    print(f"history-db: {repository.path}")
    print(f"selected codes: {', '.join(selection.selected_codes)}")
    print(f"case: {args.case}; synthetic inputs only")


if __name__ == "__main__":
    main()
