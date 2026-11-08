import unittest
from decimal import Decimal

from arahint.inventory import InventoryService, ValidationError
from arahint.inventory.db import connect


class InventoryTestCase(unittest.TestCase):
    def setUp(self):
        self.conn = connect(":memory:")
        self.svc = InventoryService(self.conn)
        self.svc.create_company("AC", "Arahint Company")
        self.svc.create_uom("PCS", "Piece")
        self.svc.create_uom("BOX", "Box")
        self.svc.create_warehouse("AC", "WH1", "Main Warehouse")
        self.svc.create_warehouse("AC", "WH2", "Branch Warehouse")

    def tearDown(self):
        self.svc.close()

    def make_item(self, code="ITEM", method="moving_average"):
        self.svc.create_item(code, f"Item {code}", "PCS", method)
        self.svc.add_uom_conversion(code, "BOX", 12)
        return code

    def balance(self, **kwargs):
        rows = self.svc.stock_balance(**kwargs)
        return {(row["item_code"], row["warehouse_code"]): row for row in rows}


class ReceiptIssueTransferTest(InventoryTestCase):
    def test_receipt_updates_balance_per_item_and_warehouse(self):
        item = self.make_item()
        self.svc.post_stock_entry(
            "receipt",
            "2026-01-01",
            "AC",
            [{"item": item, "target_warehouse": "WH1", "qty": "10", "uom": "PCS", "rate": "1000"}],
        )

        row = self.balance()[("ITEM", "WH1")]
        self.assertEqual(row["qty"], Decimal("10.000000"))
        self.assertEqual(row["value"], Decimal("10000.00"))

    def test_uom_conversion_is_applied_to_stock_quantity(self):
        item = self.make_item()
        self.svc.post_stock_entry(
            "receipt",
            "2026-01-01",
            "AC",
            [{"item": item, "target_warehouse": "WH1", "qty": "2", "uom": "BOX", "rate": "12000"}],
        )

        row = self.balance()[("ITEM", "WH1")]
        self.assertEqual(row["qty"], Decimal("24.000000"))
        self.assertEqual(row["value"], Decimal("24000.00"))

    def test_issue_consumes_moving_average_value(self):
        item = self.make_item()
        self.svc.post_stock_entry(
            "receipt",
            "2026-01-01",
            "AC",
            [{"item": item, "target_warehouse": "WH1", "qty": "10", "uom": "PCS", "rate": "1000"}],
        )
        self.svc.post_stock_entry(
            "receipt",
            "2026-01-02",
            "AC",
            [{"item": item, "target_warehouse": "WH1", "qty": "10", "uom": "PCS", "rate": "2000"}],
        )
        self.svc.post_stock_entry(
            "issue",
            "2026-01-03",
            "AC",
            [{"item": item, "source_warehouse": "WH1", "qty": "4", "uom": "PCS"}],
        )

        row = self.balance()[("ITEM", "WH1")]
        self.assertEqual(row["qty"], Decimal("16.000000"))
        self.assertEqual(row["value"], Decimal("24000.00"))
        self.assertEqual(row["rate"], Decimal("1500.000000"))

    def test_transfer_moves_quantity_and_preserves_total_value(self):
        item = self.make_item()
        self.svc.post_stock_entry(
            "receipt",
            "2026-01-01",
            "AC",
            [{"item": item, "target_warehouse": "WH1", "qty": "10", "uom": "PCS", "rate": "1000"}],
        )
        self.svc.post_stock_entry(
            "transfer",
            "2026-01-02",
            "AC",
            [{"item": item, "source_warehouse": "WH1", "target_warehouse": "WH2", "qty": "4", "uom": "PCS"}],
        )

        balances = self.balance()
        self.assertEqual(balances[("ITEM", "WH1")]["qty"], Decimal("6.000000"))
        self.assertEqual(balances[("ITEM", "WH1")]["value"], Decimal("6000.00"))
        self.assertEqual(balances[("ITEM", "WH2")]["qty"], Decimal("4.000000"))
        self.assertEqual(balances[("ITEM", "WH2")]["value"], Decimal("4000.00"))

        report = self.svc.valuation_report(company="AC")
        self.assertEqual(report["items"][0]["qty"], Decimal("10.000000"))
        self.assertEqual(report["total_value"], Decimal("10000.00"))

    def test_issue_cannot_exceed_available_stock(self):
        item = self.make_item()
        with self.assertRaises(ValidationError):
            self.svc.post_stock_entry(
                "issue",
                "2026-01-01",
                "AC",
                [{"item": item, "source_warehouse": "WH1", "qty": "1", "uom": "PCS"}],
            )


class FifoValuationTest(InventoryTestCase):
    def test_fifo_issue_uses_oldest_layers(self):
        item = self.make_item(method="fifo")
        for day, rate in (("01", "100"), ("02", "200")):
            self.svc.post_stock_entry(
                "receipt",
                f"2026-01-{day}",
                "AC",
                [{"item": item, "target_warehouse": "WH1", "qty": "10", "uom": "PCS", "rate": rate}],
            )
        self.svc.post_stock_entry(
            "issue",
            "2026-01-03",
            "AC",
            [{"item": item, "source_warehouse": "WH1", "qty": "15", "uom": "PCS"}],
        )

        outgoing = self.svc.outgoing_valuation(company="AC")
        self.assertEqual(outgoing["total_value"], Decimal("2000.00"))
        self.assertEqual(outgoing["total_qty"], Decimal("15.000000"))

        row = self.balance()[("ITEM", "WH1")]
        self.assertEqual(row["qty"], Decimal("5.000000"))
        self.assertEqual(row["value"], Decimal("1000.00"))

    def test_fifo_issue_of_entire_stock_clears_old_layers(self):
        item = self.make_item(method="fifo")
        self.svc.post_stock_entry(
            "receipt",
            "2026-01-01",
            "AC",
            [{"item": item, "target_warehouse": "WH1", "qty": "10", "uom": "PCS", "rate": "100"}],
        )
        self.svc.post_stock_entry(
            "issue",
            "2026-01-02",
            "AC",
            [{"item": item, "source_warehouse": "WH1", "qty": "10", "uom": "PCS"}],
        )
        self.svc.post_stock_entry(
            "receipt",
            "2026-01-03",
            "AC",
            [{"item": item, "target_warehouse": "WH1", "qty": "5", "uom": "PCS", "rate": "300"}],
        )
        self.svc.post_stock_entry(
            "issue",
            "2026-01-04",
            "AC",
            [{"item": item, "source_warehouse": "WH1", "qty": "5", "uom": "PCS"}],
        )

        outgoing = self.svc.outgoing_valuation(company="AC")
        self.assertEqual(outgoing["total_value"], Decimal("2500.00"))
        self.assertEqual(self.balance(), {})

    def test_fifo_and_journal_report_the_same_outgoing_value(self):
        item = self.make_item(method="fifo")
        for day, rate in (("01", "100"), ("02", "200")):
            self.svc.post_stock_entry(
                "receipt",
                f"2026-01-{day}",
                "AC",
                [{"item": item, "target_warehouse": "WH1", "qty": "10", "uom": "PCS", "rate": rate}],
            )
        self.svc.post_stock_entry(
            "issue",
            "2026-01-03",
            "AC",
            [{"item": item, "source_warehouse": "WH1", "qty": "15", "uom": "PCS"}],
        )

        reconciliation = self.svc.valuation_reconciliation(company="AC")
        self.assertTrue(reconciliation["balanced"])
        self.assertEqual(reconciliation["outgoing_value"], Decimal("2000.00"))
        self.assertEqual(reconciliation["journal_cogs"], Decimal("2000.00"))
        self.assertEqual(reconciliation["difference"], Decimal("0.00"))


class StockBalanceReportTest(InventoryTestCase):
    def test_stock_balance_equals_sum_of_ledger_as_of_date(self):
        item = self.make_item()
        self.svc.post_stock_entry(
            "receipt",
            "2026-01-01",
            "AC",
            [{"item": item, "target_warehouse": "WH1", "qty": "10", "uom": "PCS", "rate": "1000"}],
        )
        self.svc.post_stock_entry(
            "issue",
            "2026-01-05",
            "AC",
            [{"item": item, "source_warehouse": "WH1", "qty": "4", "uom": "PCS"}],
        )

        early = self.balance(as_of="2026-01-03")[("ITEM", "WH1")]
        self.assertEqual(early["qty"], Decimal("10.000000"))
        self.assertEqual(early["value"], Decimal("10000.00"))

        latest = self.balance(as_of="2026-01-06")[("ITEM", "WH1")]
        self.assertEqual(latest["qty"], Decimal("6.000000"))
        self.assertEqual(latest["value"], Decimal("6000.00"))

        ledger = self.svc.stock_ledger(item=item, to_date="2026-01-06")
        self.assertEqual(
            sum((row["qty_change"] for row in ledger), Decimal("0")), latest["qty"]
        )
        self.assertEqual(
            sum((row["stock_value_change"] for row in ledger), Decimal("0")), latest["value"]
        )

    def test_backdated_entry_is_rejected(self):
        item = self.make_item()
        self.svc.post_stock_entry(
            "receipt",
            "2026-01-10",
            "AC",
            [{"item": item, "target_warehouse": "WH1", "qty": "1", "uom": "PCS", "rate": "100"}],
        )
        with self.assertRaises(ValidationError):
            self.svc.post_stock_entry(
                "receipt",
                "2026-01-09",
                "AC",
                [{"item": item, "target_warehouse": "WH1", "qty": "1", "uom": "PCS", "rate": "100"}],
            )

    def test_multi_line_entry_updates_each_item_and_warehouse(self):
        first = self.make_item("A")
        second = self.make_item("B")
        self.svc.post_stock_entry(
            "receipt",
            "2026-01-01",
            "AC",
            [
                {"item": first, "target_warehouse": "WH1", "qty": "5", "uom": "PCS", "rate": "100"},
                {"item": second, "target_warehouse": "WH2", "qty": "3", "uom": "PCS", "rate": "700"},
            ],
        )

        balances = self.balance()
        self.assertEqual(balances[("A", "WH1")]["qty"], Decimal("5.000000"))
        self.assertEqual(balances[("A", "WH1")]["value"], Decimal("500.00"))
        self.assertEqual(balances[("B", "WH2")]["qty"], Decimal("3.000000"))
        self.assertEqual(balances[("B", "WH2")]["value"], Decimal("2100.00"))

    def test_receipt_requires_a_rate(self):
        item = self.make_item()
        with self.assertRaises(ValidationError):
            self.svc.post_stock_entry(
                "receipt",
                "2026-01-01",
                "AC",
                [{"item": item, "target_warehouse": "WH1", "qty": "1", "uom": "PCS"}],
            )


class FifoTransferTest(InventoryTestCase):
    def test_fifo_transfer_carries_layer_value_to_target(self):
        item = self.make_item(method="fifo")
        for day, rate in (("01", "100"), ("02", "200")):
            self.svc.post_stock_entry(
                "receipt",
                f"2026-01-{day}",
                "AC",
                [{"item": item, "target_warehouse": "WH1", "qty": "10", "uom": "PCS", "rate": rate}],
            )
        self.svc.post_stock_entry(
            "transfer",
            "2026-01-03",
            "AC",
            [{"item": item, "source_warehouse": "WH1", "target_warehouse": "WH2", "qty": "12", "uom": "PCS"}],
        )

        balances = self.balance()
        self.assertEqual(balances[("ITEM", "WH1")]["qty"], Decimal("8.000000"))
        self.assertEqual(balances[("ITEM", "WH1")]["value"], Decimal("1600.00"))
        self.assertEqual(balances[("ITEM", "WH2")]["qty"], Decimal("12.000000"))
        self.assertEqual(balances[("ITEM", "WH2")]["value"], Decimal("1400.00"))

        reconciliation = self.svc.valuation_reconciliation(company="AC")
        self.assertTrue(reconciliation["balanced"])


if __name__ == "__main__":
    unittest.main()
