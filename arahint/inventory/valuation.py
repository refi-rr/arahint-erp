"""Stock valuation through a single, centralised mechanism.

Every item names the method used to value its stock. The service never values
stock itself: it asks the registry for the item's valuation and hands it the
movement. Two methods are available:

``moving_average``
    The default. Outgoing stock is worth the current average cost per base
    unit, which is the running value divided by the running quantity. Each
    receipt re-averages the balance.

``fifo``
    Outgoing stock is worth the value of the oldest layers first. Layers are
    kept in ``stock_layers`` and consumed as stock leaves.

Both methods share the same contract, so a caller that only knows the
interface can post against either one.
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from typing import NamedTuple, Protocol

from .errors import ValidationError
from .numeric import quantize_money, quantize_qty, quantize_rate, to_decimal

MOVING_AVERAGE = "moving_average"
FIFO = "fifo"
VALUATION_METHODS = (MOVING_AVERAGE, FIFO)


class ValuationState(NamedTuple):
    """The balance a valuation starts from, in base UOM."""

    qty: Decimal
    value: Decimal


class ValuationResult(NamedTuple):
    """What a valuation decided about one movement.

    ``qty`` and ``value`` are the balance after the movement, ``rate`` is the
    rate per base unit at which the movement itself was valued, and
    ``movement_value`` is the money value of the movement, positive for stock
    coming in and negative for stock going out.
    """

    qty: Decimal
    value: Decimal
    rate: Decimal
    movement_value: Decimal


class Movement(NamedTuple):
    """The context of one stock movement, handed to the valuation."""

    item: sqlite3.Row
    warehouse_id: int
    entry_id: int
    posting_date: str


class Valuation(Protocol):
    """The contract every valuation method fulfils."""

    method: str

    def receipt(
        self,
        movement: Movement,
        state: ValuationState,
        base_qty: Decimal,
        value: Decimal,
    ) -> ValuationResult:
        """Value stock coming in and return the resulting balance."""

    def issue(
        self,
        movement: Movement,
        state: ValuationState,
        base_qty: Decimal,
    ) -> ValuationResult:
        """Value stock going out and return the resulting balance."""


def _rate_of(value: Decimal, qty: Decimal) -> Decimal:
    """The rate per base unit a movement was valued at."""
    if qty == 0:
        return Decimal("0.000000")
    return quantize_rate(value / qty)


class MovingAverageValuation:
    """Values stock at the running average cost per base unit."""

    method = MOVING_AVERAGE

    def receipt(self, movement, state, base_qty, value) -> ValuationResult:
        return ValuationResult(
            qty=quantize_qty(state.qty + base_qty),
            value=quantize_money(state.value + value),
            rate=_rate_of(value, base_qty),
            movement_value=quantize_money(value),
        )

    def issue(self, movement, state, base_qty) -> ValuationResult:
        value = self._outgoing_value(state, base_qty)
        new_qty = quantize_qty(state.qty - base_qty)
        new_value = quantize_money(state.value - value)
        if new_qty == 0:
            new_value = Decimal("0.00")
        return ValuationResult(
            qty=new_qty,
            value=new_value,
            rate=_rate_of(value, base_qty),
            movement_value=quantize_money(-value),
        )

    def _outgoing_value(self, state: ValuationState, base_qty: Decimal) -> Decimal:
        """The value of ``base_qty`` at the balance's current average cost."""
        if state.qty <= 0:
            raise ValidationError("cannot value outgoing stock from an empty balance")
        if base_qty > state.qty:
            raise ValidationError(
                "cannot value outgoing stock beyond the available balance"
            )
        if base_qty == state.qty:
            return quantize_money(state.value)
        value = quantize_money(base_qty * (state.value / state.qty))
        if value > state.value:
            value = quantize_money(state.value)
        return value


class FifoValuation:
    """Values stock from the oldest layers first."""

    method = FIFO

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.conn = connection

    def receipt(self, movement, state, base_qty, value) -> ValuationResult:
        self.conn.execute(
            "INSERT INTO stock_layers "
            "(item_id, warehouse_id, entry_id, received_at, qty_remaining, value_remaining, rate) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                movement.item["id"],
                movement.warehouse_id,
                movement.entry_id,
                movement.posting_date,
                str(quantize_qty(base_qty)),
                str(quantize_money(value)),
                str(_rate_of(value, base_qty)),
            ),
        )
        return ValuationResult(
            qty=quantize_qty(state.qty + base_qty),
            value=quantize_money(state.value + value),
            rate=_rate_of(value, base_qty),
            movement_value=quantize_money(value),
        )

    def issue(self, movement, state, base_qty) -> ValuationResult:
        value = self._consume(movement.item["id"], movement.warehouse_id, base_qty)
        new_qty = quantize_qty(state.qty - base_qty)
        new_value = quantize_money(state.value - value)
        if new_qty == 0:
            new_value = Decimal("0.00")
        return ValuationResult(
            qty=new_qty,
            value=new_value,
            rate=_rate_of(value, base_qty),
            movement_value=quantize_money(-value),
        )

    def _consume(self, item_id: int, warehouse_id: int, base_qty: Decimal) -> Decimal:
        """Take value from the oldest layers until ``base_qty`` is covered."""
        remaining = base_qty
        total = Decimal("0")
        rows = self.conn.execute(
            "SELECT id, qty_remaining, value_remaining FROM stock_layers "
            "WHERE item_id = ? AND warehouse_id = ? ORDER BY id",
            (item_id, warehouse_id),
        ).fetchall()
        for row in rows:
            if remaining <= 0:
                break
            layer_qty = to_decimal(row["qty_remaining"])
            layer_value = to_decimal(row["value_remaining"])
            if layer_qty <= 0:
                continue
            take = min(layer_qty, remaining)
            take_value = (
                quantize_money(layer_value)
                if take == layer_qty
                else quantize_money(layer_value * take / layer_qty)
            )
            new_qty = quantize_qty(layer_qty - take)
            new_value = layer_value - take_value
            if new_qty == 0:
                new_value = Decimal("0.00")
            self.conn.execute(
                "UPDATE stock_layers SET qty_remaining = ?, value_remaining = ? WHERE id = ?",
                (str(new_qty), str(quantize_money(new_value)), row["id"]),
            )
            total += take_value
            remaining -= take
        if remaining > 0:
            raise ValidationError("stock layers do not cover the requested quantity")
        return total


class ValuationRegistry:
    """Hands out the valuation method an item asked for.

    This is the one place that knows which methods exist, so the service posts
    against a single mechanism instead of branching per method.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.conn = connection
        self._moving_average = MovingAverageValuation()
        self._fifo = FifoValuation(connection)

    def for_item(self, item: sqlite3.Row) -> Valuation:
        method = item["valuation_method"]
        if method == MOVING_AVERAGE:
            return self._moving_average
        if method == FIFO:
            return self._fifo
        raise ValidationError(
            f"valuation method {method!r} is not supported; "
            f"choose one of {', '.join(VALUATION_METHODS)}"
        )
