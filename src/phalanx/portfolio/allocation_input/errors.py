"""Invalid evidence is distinct from normal insufficient history and storage errors."""


class AllocationInputError(Exception):
    def __init__(
        self,
        code: str = "INVALID_SELECTION",
        message: str = "selection 입력 구조·값·정책의 일관성을 확인해 주세요.",
    ) -> None:
        super().__init__(message)
        self.code = code


class AllocationInputReadError(Exception):
    """The selection file could not be read."""
