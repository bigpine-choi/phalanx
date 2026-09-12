"""Safe errors shared by discovery adapters and application callers."""


class DiscoveryError(Exception):
    """A failure with a stable machine code and safe Korean explanation."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class DiscoveryStorageError(DiscoveryError):
    """The discovery store could not be read or committed safely."""

    def __init__(self) -> None:
        super().__init__("STORAGE_FAILED", "후보 저장소 오류: 경로·권한·저장 공간을 확인해 주세요.")
