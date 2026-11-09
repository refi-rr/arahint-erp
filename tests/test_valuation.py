"""Tests for the centralised valuation layer."""

import unittest
from decimal import Decimal

from arahint.inventory import ValidationError
from arahint.inventory.db import connect
from arahint.inventory.valuation import (
    FIFO,
    MOVING_AVERAGE,
    FifoValuation,
    MovingAverageValuation,
    ValuationRegistry,
    ValuationState,
)


class MovingAverageValuationTest(unittest.TestCase):
    def setUp(self):
        self.valuation = MovingAverageValuation()
        self.state = ValuationState(Decimal("10"), Decimal("10000.00"))

    def test_receipt_extends_the_balance_at_the_given_value(self):
        result = self.valuation.receipt(None, self.state, Decimal("10"), Decimal("20000.00"))
        self.assertEqual(result.qty, Decimal("20.000000"))
        self.assertEqual(result.value, Decimal("30000.00"))
        self.assertEqual(result.rate, Decimal("2000.000000"))
        self.assertEqual(result.movement_value, Decimal("20000.00"))

    def test_issue_is_valued_at_the_current_average_rate(self):
        result = self.valuation.issue(None, self.state, Decimal("4"))
        self.assertEqual(result.movement_value, Decimal("-4000.00"))
        self.assertEqual(result.qty, Decimal("6.000000"))
        self.assertEqual(result.value, Decimal("6000.00"))
        self.assertEqual(result.rate, Decimal("1000.000000"))

    def test_issue_of_the_whole_balance_clears_it(self):
        result = self.valuation.issue(None, self.state, Decimal("10"))
        self.assertEqual(result.movement_value, Decimal("-10000.00"))
        self.assertEqual(result.qty, Decimal("0.000000"))
        self.assertEqual(result.value, Decimal("0.00"))

    def test_issue_beyond_the_balance_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.valuation.issue(None, self.state, Decimal("11"))

    def test_issue_from_an_empty_balance_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.valuation.issue(None, ValuationState(Decimal("0"), Decimal("0")), Decimal("1"))

    def test_average_rate_follows_the_running_balance(self):
        state = ValuationState(Decimal("0"), Decimal("0.00"))
        state = self.valuation.receipt(None, state, Decimal("10"), Decimal("10000.00"))._replace()
        state = ValuationState(Decimal("10"), Decimal("10000.00"))
        result = self.valuation.receipt(None, state, Decimal("10"), Decimal("20000.00"))
        self.assertEqual(result.value, Decimal("30000.00"))
        self.assertEqual(result.value / result.qty, Decimal("1500"))


class FifoValuationTest(unittest.TestCase):
    def setUp(self):
        self.conn = connect(":memory:")
        self.valuation = FifoValuation(self.conn)
        self.conn.execute(
            "INSERT INTO companies (id, code, name, currency) VALUES (1, 'AC', 'AC', 'IDR')"
        )
        self.conn.execute("INSERT INTO uoms (id, code, name) VALUES (1, 'PCS', 'Piece')")
        self.conn.execute(
            "INSERT INTO items (id, code, name, base_uom_id, valuation_method) "
            "VALUES (1, 'ITEM', 'Item', 1, 'fifo')"
        )
        self.item = self.conn.execute("SELECT * FROM items WHERE id = 1").fetchone()
        self.conn.execute(
            "INSERT INTO warehouses (id, code, name, company_id) VALUES (1, 'WH1', 'WH1', 1)"
        )
        self.conn.execute(
            "INSERT INTO stock_entries (id, entry_type, posting_date, company_id, created_at) "
            "VALUES (1, 'receipt', '2026-01-01', 1, '2026-01-01')"
        )

    def tearDown(self):
        self.conn.close()

    def _receipt(self, qty, value):
        movement = _movement(self.item, 1, 1)
        return self.valuation.receipt(movement, ValuationState(Decimal("0"), Decimal("0")), qty, value)

    def test_issue_consumes_the_oldest_layer_first(self):
        self._receipt(Decimal("10"), Decimal("1000.00"))
        self._receipt(Decimal("10"), Decimal("2000.00"))
        movement = _movement(self.item, 1, 3)
        result = self.valuation.issue(
            movement, ValuationState(Decimal("20"), Decimal("3000.00")), Decimal("15")
        )
        self.assertEqual(result.movement_value, Decimal("-2000.00"))

    def test_layers_are_kept_per_warehouse(self):
        self._receipt(Decimal("10"), Decimal("1000.00"))
        rows = self.conn.execute("SELECT qty_remaining, value_remaining FROM stock_layers").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(Decimal(rows[0]["qty_remaining"]), Decimal("10.000000"))


class ValuationRegistryTest(unittest.TestCase):
    def setUp(self):
        self.conn = connect(":memory:")
        self.registry = ValuationRegistry(self.conn)
        self.conn.execute("INSERT INTO uoms (id, code, name) VALUES (1, 'PCS', 'Piece')")
        self.conn.execute(
            "INSERT INTO items (id, code, name, base_uom_id, valuation_method) "
            "VALUES (1, 'MA', 'Moving average', 1, 'moving_average')"
        )
        self.conn.execute(
            "INSERT INTO items (id, code, name, base_uom_id, valuation_method) "
            "VALUES (2, 'FI', 'Fifo', 1, 'fifo')"
        )

    def tearDown(self):
        self.conn.close()

    def test_registry_returns_the_moving_average_valuation(self):
        item = self.conn.execute("SELECT * FROM items WHERE id = 1").fetchone()
        self.assertEqual(self.registry.for_item(item).method, MOVING_AVERAGE)

    def test_registry_returns_the_fifo_valuation(self):
        item = self.conn.execute("SELECT * FROM items WHERE id = 2").fetchone()
        self.assertEqual(self.registry.for_item(item).method, FIFO)

    def test_registry_rejects_an_unknown_method(self):
        # The schema forbids other methods, so the registry is checked against a
        # row that carries one anyway.
        item = {"id": 3, "valuation_method": "weighted_average"}
        with self.assertRaises(ValidationError):
            self.registry.for_item(item)


def _movement(item, warehouse_id, entry_id):
    from arahint.inventory.valuation import Movement

    return Movement(item, warehouse_id, entry_id, "2026-01-01")


if __name__ == "__main__":
    unittest.main()
