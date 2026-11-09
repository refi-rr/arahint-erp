"""Decimal helpers shared by the inventory modules.

Quantities, money, and rates are stored as text in SQLite, so every value that
enters or leaves the database passes through one of these functions.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

QTY_QUANT = Decimal("0.000001")
MONEY_QUANT = Decimal("0.01")
RATE_QUANT = Decimal("0.000001")


def to_decimal(value) -> Decimal:
    """Convert a value to Decimal without going through binary float."""
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def quantize_qty(value) -> Decimal:
    return to_decimal(value).quantize(QTY_QUANT, rounding=ROUND_HALF_UP)


def quantize_money(value) -> Decimal:
    return to_decimal(value).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def quantize_rate(value) -> Decimal:
    return to_decimal(value).quantize(RATE_QUANT, rounding=ROUND_HALF_UP)
