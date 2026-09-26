"""Reuse one input preparation; no saved allocation-input JSON parser or live data."""

from decimal import localcontext
from pathlib import Path

from phalanx.decimal_math import financial_decimal_context
from phalanx.domain.allocation_targets import AllocationTargets
from phalanx.portfolio.allocation_input.service import AllocationInputService
from phalanx.portfolio.allocation_targets.calculation import calculate_allocation_targets
from phalanx.portfolio.private_json_storage import store_private_json_bytes


class AllocationTargetsService:
    def __init__(self, input_service: AllocationInputService) -> None:
        self.input_service = input_service

    def calculate(self, selection_path: Path) -> AllocationTargets:
        with localcontext(financial_decimal_context()):
            prepared = self.input_service.prepare(selection_path)
            return calculate_allocation_targets(prepared)

    def calculate_bytes(self, payload: bytes) -> AllocationTargets:
        """Use one preparation and the same Decimal context as the path API."""
        with localcontext(financial_decimal_context()):
            prepared = self.input_service.prepare_bytes(payload)
            return calculate_allocation_targets(prepared)

    @staticmethod
    def export(result: AllocationTargets, output: Path) -> Path:
        return store_private_json_bytes(output, result.to_json_bytes())
