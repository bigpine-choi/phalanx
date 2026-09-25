"""Integration contract failures are distinct from unavailable source history."""

from phalanx.portfolio.errors import ConstrainedErcScenarioScheduleError


class AllocationTargetsContractError(ConstrainedErcScenarioScheduleError):
    """An engine returned evidence inconsistent with the input it received."""
