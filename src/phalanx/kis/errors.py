"""Secret-safe exception types for the narrow KIS authentication boundary."""


class KisAuthError(RuntimeError):
    """Base failure for real-account KIS OAuth token handling."""


class KisHttpError(KisAuthError):
    """The KIS OAuth HTTP exchange failed without exposing request or response bodies."""


class KisTimeoutError(KisHttpError):
    """The KIS OAuth request exceeded its explicit timeout."""


class KisProtocolError(KisAuthError):
    """The KIS OAuth response did not satisfy the documented token contract."""


class TokenCacheError(KisAuthError):
    """The local token cache could not be accessed without weakening security."""
