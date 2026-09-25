"""Saved target bytes from the real synthetic features→selection→input→ERC path."""

from allocation_targets_helpers import target_inputs

from phalanx.domain.risk_model import CovarianceScenarioKind
from phalanx.portfolio.allocation_input.service import AllocationInputService
from phalanx.portfolio.allocation_targets.calculation import calculate_allocation_targets
from phalanx.portfolio.constrained_erc import ConstrainedErcSolver
from phalanx.portfolio.errors import ConstrainedErcCcdConvergenceError


def saved_targets(directory, case="succeeded"):
    options = {
        "succeeded": {},
        "boundary": {"size": 5},
        "input_unavailable": {"count": 504},
        "common_failure": {"degenerate": True},
        "failed": {"size": 4},
        "partial": {},
    }[case]
    repository, selection_path, _, _ = target_inputs(directory, **options)
    prepared = AllocationInputService(repository).prepare(selection_path)
    solver = None
    if case == "partial":

        class PartialSolver(ConstrainedErcSolver):
            def solve_scenario(self, scenario, *, as_of_date):
                if scenario.kind == CovarianceScenarioKind.FAST_IEWMA:
                    raise ConstrainedErcCcdConvergenceError("synthetic failure")
                return super().solve_scenario(scenario, as_of_date=as_of_date)

        solver = PartialSolver()
    return calculate_allocation_targets(prepared, solver=solver).to_json_bytes()
