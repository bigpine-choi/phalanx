from pathlib import Path

from phalanx.domain.candidate_selection import CandidateSelection
from phalanx.selection.service import CandidateSelectionService


def test_synthetic_example_reproduces_checked_in_selection_bytes() -> None:
    directory = Path(__file__).resolve().parents[1] / "examples" / "candidate-selection"
    expected_bytes = (directory / "selection.json").read_bytes()
    expected = CandidateSelection.model_validate_json(expected_bytes)
    actual = CandidateSelectionService(clock=lambda: expected.evaluated_at).select(
        directory / "features.json", expected.policy
    )
    assert actual.to_json_bytes() == expected_bytes
    assert actual.selected_codes == ("0001A0",)
    assert [candidate.status for candidate in actual.candidates] == [
        "selected",
        "not_selected",
        "unavailable",
    ]
    assert actual.selection_filled and not actual.evaluation_complete and not actual.complete
