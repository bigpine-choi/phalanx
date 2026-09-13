"""Safe selection failures distinguish malformed inputs from storage errors."""


class SelectionInputError(Exception):
    def __init__(
        self,
        code: str = "INVALID_FEATURES",
        message: str = "features 입력 구조·값·정책의 일관성을 확인해 주세요.",
    ) -> None:
        super().__init__(message)
        self.code = code


class SelectionStorageError(Exception):
    """The input bytes could not be read safely."""
