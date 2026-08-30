"""Dedicated errors for the local investment universe boundary."""


class UniverseError(Exception):
    """Base class for expected universe failures safe to show to users."""


class UniverseValidationError(UniverseError):
    """Base class for invalid human-supplied universe values."""


class InvalidStockCodeError(UniverseValidationError):
    """Raised when a domestic stock code is not six ASCII digits."""


class InvalidStockNameError(UniverseValidationError):
    """Raised when a stock name is blank or unexpectedly large."""


class InvalidMarketError(UniverseValidationError):
    """Raised when a market is neither KOSPI nor KOSDAQ."""


class InvalidStockNoteError(UniverseValidationError):
    """Raised when an optional stock note has an invalid type or size."""


class InvalidEnabledStateError(UniverseValidationError):
    """Raised when an enabled state is not a boolean."""


class DuplicateStockError(UniverseError):
    """Raised when a stock code is already registered."""


class StockNotFoundError(UniverseError):
    """Raised when a requested stock code is not registered."""


class UniverseStorageError(UniverseError):
    """Base class for safe local universe persistence failures."""


class UnsupportedPlatformError(UniverseStorageError):
    """Raised when the POSIX repository is used outside Linux or WSL."""


class UnsafeUniversePathError(UniverseStorageError):
    """Raised when the universe path cannot be accessed safely."""


class CorruptUniverseError(UniverseStorageError):
    """Raised when persisted universe data violates its schema."""


__all__ = [
    "CorruptUniverseError",
    "DuplicateStockError",
    "InvalidEnabledStateError",
    "InvalidMarketError",
    "InvalidStockCodeError",
    "InvalidStockNameError",
    "InvalidStockNoteError",
    "StockNotFoundError",
    "UniverseError",
    "UniverseStorageError",
    "UniverseValidationError",
    "UnsafeUniversePathError",
    "UnsupportedPlatformError",
]
