"""Shared exact calculation context, independent of process Decimal defaults."""

from decimal import (
    ROUND_HALF_EVEN,
    Context,
    DivisionByZero,
    FloatOperation,
    InvalidOperation,
    Overflow,
    Underflow,
)


def financial_decimal_context() -> Context:
    """Return a fresh 50-digit, half-even context with explicit bounds and traps."""
    return Context(
        prec=50,
        rounding=ROUND_HALF_EVEN,
        Emin=-999999,
        Emax=999999,
        capitals=1,
        clamp=0,
        flags=[],
        traps=[InvalidOperation, DivisionByZero, Overflow, Underflow, FloatOperation],
    )
