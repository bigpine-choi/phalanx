"""Safe, stable application errors; credentials and transport objects never persist."""


class HistoryError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class HistoryStorageError(HistoryError):
    def __init__(self) -> None:
        super().__init__("STORAGE_FAILED", "일봉 저장소의 경로·권한·저장 공간을 확인해 주세요.")


class HistoryFetchError(HistoryError):
    def __init__(self, code: str, message: str, *, common: bool = False) -> None:
        super().__init__(code, message)
        self.common = common
