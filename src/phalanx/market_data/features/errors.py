"""Explicit input and arithmetic failures, distinct from insufficient history."""


class PriceFeatureError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
