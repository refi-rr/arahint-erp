"""Tests for the UOM conversion layer."""

import unittest
from decimal import Decimal

from arahint.inventory import ValidationError
from arahint.inventory.db import connect
from arahint.inventory.uom import UomConverter


class UomConverterTest(unittest.TestCase):
    def setUp(self):
        self.conn = connect(":memory:")
        self.converter = UomConverter(self.conn)
        self.conn.execute("INSERT INTO uoms (id, code, name) VALUES (1, 'PCS', 'Piece')")
        self.conn.execute("INSERT INTO uoms (id, code, name) VALUES (2, 'BOX', 'Box')")
        self.conn.execute("INSERT INTO uoms (id, code, name) VALUES (3, 'KG', 'Kilogram')")
        self.conn.execute(
            "INSERT INTO items (id, code, name, base_uom_id, valuation_method) "
            "VALUES (1, 'ITEM', 'Item', 1, 'moving_average')"
        )
        self.conn.execute(
            "INSERT INTO item_uom_conversions (item_id, uom_id, factor) VALUES (1, 2, '12')"
        )
        self.item = self.conn.execute("SELECT * FROM items WHERE id = 1").fetchone()

    def tearDown(self):
        self.conn.close()

    def test_base_uom_converts_with_a_factor_of_one(self):
        conversion = self.converter.convert(self.item, 1, "10")
        self.assertEqual(conversion.factor, Decimal("1"))
        self.assertEqual(conversion.base_qty, Decimal("10.000000"))
        self.assertEqual(conversion.txn_qty, Decimal("10"))

    def test_other_uom_converts_with_its_factor(self):
        conversion = self.converter.convert(self.item, 2, "3")
        self.assertEqual(conversion.factor, Decimal("12"))
        self.assertEqual(conversion.base_qty, Decimal("36.000000"))
        self.assertEqual(conversion.txn_qty, Decimal("3"))

    def test_fractional_factor_is_honoured(self):
        self.conn.execute(
            "INSERT INTO item_uom_conversions (item_id, uom_id, factor) VALUES (1, 3, '0.5')"
        )
        conversion = self.converter.convert(self.item, 3, "10")
        self.assertEqual(conversion.base_qty, Decimal("5.000000"))

    def test_uom_without_a_conversion_factor_is_rejected(self):
        with self.assertRaises(ValidationError) as caught:
            self.converter.convert(self.item, 3, "1")
        self.assertIn("not available for item", str(caught.exception))

    def test_rejection_names_the_available_uoms(self):
        with self.assertRaises(ValidationError) as caught:
            self.converter.convert(self.item, 3, "1")
        self.assertIn("BOX", str(caught.exception))

    def test_negative_quantity_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.converter.convert(self.item, 1, "-1")

    def test_base_rate_preserves_the_transaction_value(self):
        value = self.converter.transaction_value(2, "12000")
        self.assertEqual(value, Decimal("24000.00"))
        rate = self.converter.base_rate(value, Decimal("24"))
        self.assertEqual(rate, Decimal("1000.000000"))

    def test_base_rate_of_a_zero_quantity_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.converter.base_rate(Decimal("100"), Decimal("0"))


if __name__ == "__main__":
    unittest.main()
