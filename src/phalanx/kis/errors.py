"""Secret-safe exception types for narrow KIS integration boundaries."""


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


class KisBalanceParsingError(RuntimeError):
    """Base failure for strict domestic-stock balance response parsing."""


class MissingRequiredNumericField(KisBalanceParsingError):
    """A required numeric response field was absent, null, or blank."""

    def __init__(self, field_name: str, location: str) -> None:
        self.field_name = field_name
        self.location = location
        super().__init__(f"Required numeric field {field_name} is missing at {location}.")


class InvalidNumericField(KisBalanceParsingError):
    """A response field was not an accepted decimal string."""

    def __init__(self, field_name: str, location: str) -> None:
        self.field_name = field_name
        self.location = location
        super().__init__(f"Numeric field {field_name} has an invalid format at {location}.")


class InvalidResponseStructure(KisBalanceParsingError):
    """The decoded KIS body did not have the documented JSON structure."""


class KisApiResponseError(KisBalanceParsingError):
    """KIS returned a non-success rt_cd with sanitized response metadata."""

    def __init__(self, rt_cd: str, msg_cd: str, msg1: str) -> None:
        self.rt_cd = rt_cd
        self.msg_cd = msg_cd
        self.msg1 = msg1
        super().__init__(f"KIS API rejected the balance request ({rt_cd}, {msg_cd}): {msg1}")


class BalanceDomainInvariantError(KisBalanceParsingError):
    """Parsed values violated an existing immutable account-domain invariant."""
