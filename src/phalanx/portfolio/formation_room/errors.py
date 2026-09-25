"""Safe, fixed public errors for the offline projection boundary."""


class FormationRoomInputError(ValueError):
    """An input is not a supported, coherent allocation-targets projection."""

    def __init__(self) -> None:
        super().__init__(
            "배분 결과 JSON의 형식·버전·상태 또는 화면에 표시할 계산 근거가 유효하지 않습니다."
        )
