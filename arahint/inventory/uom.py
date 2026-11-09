"""Unit-of-measure conversion for the transaction boundary.

Every item has exactly one base UOM. A transaction may use any other UOM that
the item offers, as long as the item registers a conversion factor for it. The
factor states how many base units one unit of the transaction UOM holds, so
a factor of 12 for a BOX of PCS means one BOX is twelve pieces.

Quantities cross the transaction boundary once, here, and everything the
ledger stores is in the base UOM. Prices are converted the other way round:
the value of the transaction is preserved, and the rate recorded per base unit
is derived from it.
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from typing import NamedTuple

from .errors import ValidationError
from .numeric import quantize_qty, quantize_rate, to_decimal


class UomConversion(NamedTuple):
    """The outcome of converting a transaction quantity into the base UOM."""

    uom_id: int
    txn_qty: Decimal
    factor: Decimal
    base_qty: Decimal


class UomConverter:
    """Converts quantities and prices between an item's UOMs and its base UOM."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.conn = connection

    def factor_for(self, item: sqlite3.Row, uom_id: int) -> Decimal:
        """The number of base units one unit of ``uom_id`` holds for ``item``."""
        if uom_id == item["base_uom_id"]:
            return Decimal("1")
        row = self.conn.execute(
            "SELECT factor FROM item_uom_conversions WHERE item_id = ? AND uom_id = ?",
            (item["id"], uom_id),
        ).fetchone()
        if row is None:
            available = [
                r["code"]
                for r in self.conn.execute(
                    "SELECT u.code FROM item_uom_conversions c "
                    "JOIN uoms u ON u.id = c.uom_id WHERE c.item_id = ? ORDER BY u.code",
                    (item["id"],),
                )
            ]
            raise ValidationError(
                f"UOM is not available for item {item['code']!r}; "
                f"available UOMs: {', '.join(available) or 'none besides the base UOM'}"
            )
        factor = to_decimal(row["factor"])
        if factor <= 0:
            raise ValidationError("conversion factor must be greater than zero")
        return factor

    def convert(self, item: sqlite3.Row, uom_id: int, quantity) -> UomConversion:
        """Convert a transaction quantity into the item's base UOM."""
        txn_qty = to_decimal(quantity)
        if txn_qty < 0:
            raise ValidationError("quantity cannot be negative")
        factor = self.factor_for(item, uom_id)
        return UomConversion(
            uom_id=uom_id,
            txn_qty=txn_qty,
            factor=factor,
            base_qty=quantize_qty(txn_qty * factor),
        )

    def transaction_value(self, quantity, rate) -> Decimal:
        """The money value of a transaction, priced per its own transaction UOM."""
        return quantize_qty(to_decimal(quantity) * to_decimal(rate))

    def base_rate(self, value, base_qty) -> Decimal:
        """The rate per base unit that keeps the transaction value intact."""
        value = to_decimal(value)
        base_qty = to_decimal(base_qty)
        if base_qty == 0:
            raise ValidationError("cannot price a zero quantity")
        return quantize_rate(value / base_qty)
