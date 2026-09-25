"""Generate synthetic PR #23 results and offline Formation Room examples.

Run from the repository root with PYTHONPATH=tests and a new output directory.
The partial case explicitly injects one solver error; it never edits saved results.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path

from allocation_targets_helpers import CODES, target_inputs

from phalanx.domain.constrained_erc import ConstrainedErcTarget
from phalanx.domain.risk_model import CovarianceScenario, CovarianceScenarioKind
from phalanx.portfolio.allocation_input.service import AllocationInputService
from phalanx.portfolio.allocation_targets.calculation import calculate_allocation_targets
from phalanx.portfolio.allocation_targets.service import AllocationTargetsService
from phalanx.portfolio.constrained_erc import ConstrainedErcSolver
from phalanx.portfolio.errors import ConstrainedErcCcdConvergenceError

CASES = (
    "succeeded",
    "five-assets",
    "unavailable",
    "common-failure",
    "failed",
    "partial",
    "long-names",
    "no-selection",
    "missing-names",
    "duplicate-names",
    "script-names",
)
SYNTHETIC_NAMES = (
    "모의 루멘 시스템",
    "모의 아크 소재",
    "모의 노바 항법",
    "모의 리프 에너지",
    "모의 오르빗 통신",
    "모의 테라 정밀",
)
EXPECTED = {
    "succeeded": ("succeeded", 4),
    "five-assets": ("succeeded", 4),
    "unavailable": ("input_unavailable", 0),
    "common-failure": ("common_failure", 0),
    "failed": ("failed", 0),
    "partial": ("partial", 3),
    "long-names": ("succeeded", 4),
    "no-selection": ("succeeded", 4),
    "missing-names": ("succeeded", 4),
    "duplicate-names": ("succeeded", 4),
    "script-names": ("succeeded", 4),
}


class OneScenarioFailure:
    """Demonstration-only fault injection around the unchanged production solver."""

    def __init__(self) -> None:
        self.solver = ConstrainedErcSolver()

    def solve_scenario(
        self, scenario: CovarianceScenario, *, as_of_date: date
    ) -> ConstrainedErcTarget:
        if scenario.kind == CovarianceScenarioKind.FAST_IEWMA:
            raise ConstrainedErcCcdConvergenceError("Synthetic example fault injection")
        return self.solver.solve_scenario(scenario, as_of_date=as_of_date)


def generate_case(directory: Path, case: str) -> None:
    from phalanx.portfolio.formation_room.model import FormationRoomPresentation
    from phalanx.portfolio.formation_room.service import FormationRoomService

    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    size = {"five-assets": 5, "failed": 4}.get(case, 6)
    count = 504 if case == "unavailable" else 505
    names = dict(zip(CODES, SYNTHETIC_NAMES, strict=True))
    if case == "long-names":
        names = {
            code: f"{name} 장거리 심우주 관측과 공동 연구를 위한 합성 기술 협력 회사"
            for code, name in names.items()
        }
    elif case == "missing-names":
        names = {code: None for code in CODES}
    elif case == "duplicate-names":
        names = {code: "모의 공동 연구 회사" for code in CODES}
    elif case == "script-names":
        names = {
            code: (
                "</script><script>window.__injected=1</script>"
                '<img src="https://example.invalid/name"> 모의 & 회사'
            )
            for code in CODES
        }
    repository, selection_path, _, _ = target_inputs(
        directory,
        size=size,
        count=count,
        degenerate=case == "common-failure",
        failed_candidate=True,
        names=names,
    )
    inputs = AllocationInputService(repository)
    if case == "partial":
        result = calculate_allocation_targets(
            inputs.prepare(selection_path), solver=OneScenarioFailure()
        )
    else:
        result = AllocationTargetsService(inputs).calculate(selection_path)
    if (result.status, result.succeeded_count) != EXPECTED[case]:
        raise RuntimeError(f"Unexpected synthetic result for {case}: {result.status}")

    targets_path = directory / "synthetic-allocation-targets.json"
    html_path = directory / "formation-room.html"
    AllocationTargetsService.export(result, targets_path)
    targets_bytes = targets_path.read_bytes()
    selection_bytes = selection_path.read_bytes()
    linked_selection = None if case == "no-selection" else selection_path
    FormationRoomService().generate(
        targets=targets_path,
        output=html_path,
        selection=linked_selection,
        presentation=FormationRoomPresentation(synthetic_demo=True),
    )
    if targets_path.read_bytes() != targets_bytes or selection_path.read_bytes() != selection_bytes:
        raise RuntimeError("Formation Room modified the source JSON")
    manifest = {
        "synthetic_data": True,
        "research_only": True,
        "case": case,
        "presentation": {"synthetic_demo": True},
        "names_assigned_at": "original history targets before SQLite/features/selection",
        "selection_linked": linked_selection is not None,
        "selection_file": selection_path.name,
        "selection_file_sha256": hashlib.sha256(selection_bytes).hexdigest(),
        "source_pipeline": "features -> selection -> input -> risk -> ERC",
        "fault_injection": {
            "scenario": "fast_iewma",
            "exception": "ConstrainedErcCcdConvergenceError",
            "remaining_scenarios": "unchanged production solver",
            "saved_output_edited": False,
        }
        if case == "partial"
        else None,
        "selected_count": len(result.prepared.selected_codes),
        "price_observations_per_selected_code": count,
        "return_observation_count": result.prepared.return_observation_count,
        "selection_as_of": result.prepared.selection_as_of.isoformat(),
        "calculation_date": result.calculation_date.isoformat()
        if result.calculation_date
        else None,
        "status": result.status,
        "succeeded_count": result.succeeded_count,
        "targets_file": targets_path.name,
        "targets_sha256": hashlib.sha256(targets_bytes).hexdigest(),
        "html_file": html_path.name,
        "html_sha256": hashlib.sha256(html_path.read_bytes()).hexdigest(),
        "source_json_unchanged": True,
    }
    manifest_path = directory / "synthetic-manifest.json"
    with manifest_path.open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(f"{case}: {result.status} ({result.succeeded_count}/4); {html_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--case", choices=("all", *CASES), default="all")
    args = parser.parse_args()
    directory = args.directory.absolute()
    if args.case == "all":
        directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        for case in CASES:
            generate_case(directory / case, case)
    else:
        generate_case(directory, args.case)


if __name__ == "__main__":
    main()
