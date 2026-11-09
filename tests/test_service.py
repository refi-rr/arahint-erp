"""Service-level tests: masters, UOM boundary, posting, ledger, and reports."""

import unittest
from decimal import Decimal

from arahint.inventory import (
    DuplicateError,
    InventoryService,
    NotFoundError,
    ValidationError,
)
from arahint.inventory.db import connect
from arahint.inventory.valuation import MOVING_AVERAGE


class ServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.conn = connect(":memory:")
        self.svc = InventoryService(self.conn)
        self.svc.create_company("AC", "Arahint Company")
        self.svc.create_uom("PCS", "Piece")
        self.svc.create_uom("BOX", "Box")
        self.svc.create_uom("KG", "Kilogram")
        self.svc.create_warehouse("AC", "WH1", "Main Warehouse")
        self.svc.create_warehouse("AC", "WH2", "Branch Warehouse")

    def tearDown(self):
        self.svc.close()

    def make_item(self, code="ITEM", base_uom="PCS", method=MOVING_AVERAGE):
        self.svc.create_item(code, f"Item {code}", base_uom, method)
        return code

    def balance(self, **kwargs):
        rows = self.svc.stock_balance(**kwargs)
        return {(row["item_code"], row["warehouse_code"]): row for row in rows}


class MasterDataTest(ServiceTestCase):
    def test_item_exposes_one_base_uom_and_its_other_uoms(self):
        item = self.make_item()
        self.svc.add_uom_conversion(item, "BOX", 12)

        detail = self.svc.get_item(item)
        self.assertEqual(detail["base_uom"], "PCS")
        self.assertEqual(detail["valuation_method"], MOVING_AVERAGE)
        self.assertEqual(len(detail["uoms"]), 1)
        self.assertEqual(detail["uoms"][0]["uom_code"], "BOX")
        self.assertEqual(detail["uoms"][0]["factor"], Decimal("12"))

    def test_conversion_factor_must_be_positive(self):
        item = self.make_item()
        with self.assertRaises(ValidationError):
            self.svc.add_uom_conversion(item, "BOX", 0)

    def test_base_uom_does_not_take_a_conversion_factor(self):
        item = self.make_item()
        with self.assertRaises(ValidationError):
            self.svc.add_uom_conversion(item, "PCS", 2)

    def test_unknown_valuation_method_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.svc.create_item("X", "X", "PCS", "weighted_average")

    def test_duplicate_item_code_is_rejected(self):
        self.make_item()
        with self.assertRaises(DuplicateError):
            self.make_item()

    def test_unknown_item_is_reported_as_not_found(self):
        with self.assertRaises(NotFoundError):
            self.svc.get_item("NOPE")

    def test_warehouse_of_another_company_is_not_found(self):
        self.svc.create_company("OTHER", "Other Company")
        self.svc.create_warehouse("OTHER", "WHX", "Other")
        with self.assertRaises(NotFoundError):
            self.svc.post_stock_entry(
                "receipt",
                "2026-01-01",
                "AC",
                [{"item": self.make_item(), "target_warehouse": "WHX", "qty": "1",
                  "uom": "PCS", "rate": "10"}],
            )


class UomBoundaryTest(ServiceTestCase):
    def test_conversion_helper_reports_the_factor_and_base_quantity(self):
        item = self.make_item()
        self.svc.add_uom_conversion(item, "BOX", 12)

        result = self.svc.convert_to_base(item, "BOX", "3")
        self.assertEqual(result["quantity"], Decimal("3.000000"))
        self.assertEqual(result["factor"], Decimal("12"))
        self.assertEqual(result["base_quantity"], Decimal("36.000000"))
        self.assertEqual(result["base_uom_code"], "PCS")

    def test_uom_without_a_factor_is_rejected_at_the_boundary(self):
        item = self.make_item()
        with self.assertRaises(ValidationError):
            self.svc.post_stock_entry(
                "receipt",
                "2026-01-01",
                "AC",
                [{"item": item, "target_warehouse": "WH1", "qty": "1", "uom": "BOX",
                  "rate": "10"}],
            )

    def test_fractional_conversion_factor_is_applied(self):
        item = self.make_item()
        self.svc.add_uom_conversion(item, "KG", "0.5")
        self.svc.post_stock_entry(
            "receipt",
            "2026-01-01",
            "AC",
            [{"item": item, "target_warehouse": "WH1", "qty": "4", "uom": "KG",
              "rate": "2500"}],
        )

        row = self.balance()[("ITEM", "WH1")]
        self.assertEqual(row["qty"], Decimal("2.000000"))
        self.assertEqual(row["value"], Decimal("10000.00"))

    def test_transaction_value_is_preserved_by_the_conversion(self):
        item = self.make_item()
        self.svc.add_uom_conversion(item, "BOX", 12)
        self.svc.post_stock_entry(
            "receipt",
            "2026-01-01",
            "AC",
            [{"item": item, "target_warehouse": "WH1", "qty": "2", "uom": "BOX",
              "rate": "12000"}],
        )

        row = self.balance()[("ITEM", "WH1")]
        self.assertEqual(row["qty"], Decimal("24.000000"))
        self.assertEqual(row["value"], Decimal("24000.00"))
        self.assertEqual(row["rate"], Decimal("1000.000000"))


class StockMutationTest(ServiceTestCase):
    def test_receipt_writes_the_ledger_in_base_uom(self):
        item = self.make_item()
        self.svc.add_uom_conversion(item, "BOX", 12)
        entry_id = self.svc.post_stock_entry(
            "receipt",
            "2026-01-01",
            "AC",
            [{"item": item, "target_warehouse": "WH1", "qty": "2", "uom": "BOX",
              "rate": "12000"}],
        )

        ledger = self.svc.stock_ledger(item=item)
        self.assertEqual(len(ledger), 1)
        self.assertEqual(ledger[0]["qty_change"], Decimal("24.000000"))
        self.assertEqual(ledger[0]["stock_value_change"], Decimal("24000.00"))
        self.assertEqual(ledger[0]["qty_after"], Decimal("24.000000"))
        self.assertEqual(ledger[0]["stock_value_after"], Decimal("24000.00"))

        lines = self.svc.entry_lines(entry_id)
        self.assertEqual(lines[0]["uom_code"], "BOX")
        self.assertEqual(lines[0]["qty"], Decimal("2.000000"))
        self.assertEqual(lines[0]["rate"], Decimal("12000.000000"))
        self.assertEqual(lines[0]["base_qty"], Decimal("24.000000"))
        self.assertEqual(lines[0]["base_rate"], Decimal("1000.000000"))

    def test_issue_reduces_the_balance_by_the_base_quantity(self):
        item = self.make_item()
        self.svc.add_uom_conversion(item, "BOX", 12)
        self.svc.post_stock_entry(
            "receipt",
            "2026-01-01",
            "AC",
            [{"item": item, "target_warehouse": "WH1", "qty": "2", "uom": "BOX",
              "rate": "12000"}],
        )
        self.svc.post_stock_entry(
            "issue",
            "2026-01-02",
            "AC",
            [{"item": item, "source_warehouse": "WH1", "qty": "1", "uom": "BOX"}],
        )

        row = self.balance()[("ITEM", "WH1")]
        self.assertEqual(row["qty"], Decimal("12.000000"))
        self.assertEqual(row["value"], Decimal("12000.00"))

    def test_issue_beyond_the_balance_is_rejected(self):
        item = self.make_item()
        self.svc.post_stock_entry(
            "receipt",
            "2026-01-01",
            "AC",
            [{"item": item, "target_warehouse": "WH1", "qty": "5", "uom": "PCS",
              "rate": "100"}],
        )
        with self.assertRaises(ValidationError):
            self.svc.post_stock_entry(
                "issue",
                "2026-01-02",
                "AC",
                [{"item": item, "source_warehouse": "WH1", "qty": "6", "uom": "PCS"}],
            )

    def test_transfer_moves_the_same_value_to_the_target(self):
        item = self.make_item()
        self.svc.post_stock_entry(
            "receipt",
            "2026-01-01",
            "AC",
            [{"item": item, "target_warehouse": "WH1", "qty": "10", "uom": "PCS",
              "rate": "1000"}],
        )
        self.svc.post_stock_entry(
            "transfer",
            "2026-01-02",
            "AC",
            [{"item": item, "source_warehouse": "WH1", "target_warehouse": "WH2",
              "qty": "4", "uom": "PCS"}],
        )

        balances = self.balance()
        self.assertEqual(balances[("ITEM", "WH1")]["qty"], Decimal("6.000000"))
        self.assertEqual(balances[("ITEM", "WH1")]["value"], Decimal("6000.00"))
        self.assertEqual(balances[("ITEM", "WH2")]["qty"], Decimal("4.000000"))
        self.assertEqual(balances[("ITEM", "WH2")]["value"], Decimal("4000.00"))

    def test_transfer_to_the_same_warehouse_is_rejected(self):
        item = self.make_item()
        self.svc.post_stock_entry(
            "receipt",
            "2026-01-01",
            "AC",
            [{"item": item, "target_warehouse": "WH1", "qty": "10", "uom": "PCS",
              "rate": "1000"}],
        )
        with self.assertRaises(ValidationError):
            self.svc.post_stock_entry(
                "transfer",
                "2026-01-02",
                "AC",
                [{"item": item, "source_warehouse": "WH1", "target_warehouse": "WH1",
                  "qty": "1", "uom": "PCS"}],
            )

    def test_transfer_in_another_uom_moves_the_base_quantity(self):
        item = self.make_item()
        self.svc.add_uom_conversion(item, "BOX", 12)
        self.svc.post_stock_entry(
            "receipt",
            "2026-01-01",
            "AC",
            [{"item": item, "target_warehouse": "WH1", "qty": "24", "uom": "PCS",
              "rate": "1000"}],
        )
        self.svc.post_stock_entry(
            "transfer",
            "2026-01-02",
            "AC",
            [{"item": item, "source_warehouse": "WH1", "target_warehouse": "WH2",
              "qty": "1", "uom": "BOX"}],
        )

        balances = self.balance()
        self.assertEqual(balances[("ITEM", "WH1")]["qty"], Decimal("12.000000"))
        self.assertEqual(balances[("ITEM", "WH2")]["qty"], Decimal("12.000000"))
        self.assertEqual(balances[("ITEM", "WH2")]["value"], Decimal("12000.00"))

    def test_transfer_beyond_the_source_balance_is_rejected(self):
        item = self.make_item()
        self.svc.post_stock_entry(
            "receipt",
            "2026-01-01",
            "AC",
            [{"item": item, "target_warehouse": "WH1", "qty": "2", "uom": "PCS",
              "rate": "1000"}],
        )
        with self.assertRaises(ValidationError):
            self.svc.post_stock_entry(
                "transfer",
                "2026-01-02",
                "AC",
                [{"item": item, "source_warehouse": "WH1", "target_warehouse": "WH2",
                  "qty": "3", "uom": "PCS"}],
            )

    def test_unknown_entry_type_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.svc.post_stock_entry("adjust", "2026-01-01", "AC", [])

    def test_entry_without_lines_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.svc.post_stock_entry("receipt", "2026-01-01", "AC", [])

    def test_zero_quantity_is_rejected(self):
        item = self.make_item()
        with self.assertRaises(ValidationError):
            self.svc.post_stock_entry(
                "receipt",
                "2026-01-01",
                "AC",
                [{"item": item, "target_warehouse": "WH1", "qty": "0", "uom": "PCS",
                  "rate": "100"}],
            )

    def test_backdated_entry_is_rejected(self):
        item = self.make_item()
        self.svc.post_stock_entry(
            "receipt",
            "2026-01-05",
            "AC",
            [{"item": item, "target_warehouse": "WH1", "qty": "1", "uom": "PCS",
              "rate": "100"}],
        )
        with self.assertRaises(ValidationError):
            self.svc.post_stock_entry(
                "receipt",
                "2026-01-04",
                "AC",
                [{"item": item, "target_warehouse": "WH1", "qty": "1", "uom": "PCS",
                  "rate": "100"}],
            )


class MovingAverageTest(ServiceTestCase):
    def test_average_rate_follows_the_running_balance(self):
        item = self.make_item()
        self.svc.post_stock_entry(
            "receipt",
            "2026-01-01",
            "AC",
            [{"item": item, "target_warehouse": "WH1", "qty": "10", "uom": "PCS",
              "rate": "1000"}],
        )
        self.svc.post_stock_entry(
            "receipt",
            "2026-01-02",
            "AC",
            [{"item": item, "target_warehouse": "WH1", "qty": "10", "uom": "PCS",
              "rate": "2000"}],
        )

        row = self.balance()[("ITEM", "WH1")]
        self.assertEqual(row["value"], Decimal("30000.00"))
        self.assertEqual(row["rate"], Decimal("1500.000000"))

    def test_issue_is_valued_at_the_average_rate(self):
        item = self.make_item()
        self.svc.post_stock_entry(
            "receipt",
            "2026-01-01",
            "AC",
            [{"item": item, "target_warehouse": "WH1", "qty": "10", "uom": "PCS",
              "rate": "1000"}],
        )
        self.svc.post_stock_entry(
            "receipt",
            "2026-01-02",
            "AC",
            [{"item": item, "target_warehouse": "WH1", "qty": "10", "uom": "PCS",
              "rate": "2000"}],
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

        outgoing = self.svc.outgoing_valuation(company="AC")
        self.assertEqual(outgoing["total_value"], Decimal("6000.00"))

    def test_valuation_is_chosen_through_the_registry(self):
        item = self.make_item(method="fifo")
        self.svc.post_stock_entry(
            "receipt",
            "2026-01-01",
            "AC",
            [{"item": item, "target_warehouse": "WH1", "qty": "10", "uom": "PCS",
              "rate": "100"}],
        )
        self.svc.post_stock_entry(
            "receipt",
            "2026-01-02",
            "AC",
            [{"item": item, "target_warehouse": "WH1", "qty": "10", "uom": "PCS",
              "rate": "200"}],
        )
        self.svc.post_stock_entry(
            "issue",
            "2026-01-03",
            "AC",
            [{"item": item, "source_warehouse": "WH1", "qty": "15", "uom": "PCS"}],
        )

        # FIFO values the issue from the oldest layer, not at the average rate.
        outgoing = self.svc.outgoing_valuation(company="AC")
        self.assertEqual(outgoing["total_value"], Decimal("2000.00"))

    def test_issue_then_receipt_re_averages_the_balance(self):
        item = self.make_item()
        self.svc.post_stock_entry(
            "receipt",
            "2026-01-01",
            "AC",
            [{"item": item, "target_warehouse": "WH1", "qty": "10", "uom": "PCS",
              "rate": "1000"}],
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
            [{"item": item, "target_warehouse": "WH1", "qty": "10", "uom": "PCS",
              "rate": "3000"}],
        )

        row = self.balance()[("ITEM", "WH1")]
        self.assertEqual(row["qty"], Decimal("10.000000"))
        self.assertEqual(row["value"], Decimal("30000.00"))
        self.assertEqual(row["rate"], Decimal("3000.000000"))


class ReportTest(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.item = self.make_item()
        self.svc.post_stock_entry(
            "receipt",
            "2026-01-01",
            "AC",
            [{"item": self.item, "target_warehouse": "WH1", "qty": "10", "uom": "PCS",
              "rate": "1000"}],
        )
        self.svc.post_stock_entry(
            "issue",
            "2026-01-05",
            "AC",
            [{"item": self.item, "source_warehouse": "WH1", "qty": "4", "uom": "PCS"}],
        )

    def test_balance_report_matches_the_ledger_sum(self):
        ledger = self.svc.stock_ledger(item=self.item)
        row = self.balance()[("ITEM", "WH1")]
        self.assertEqual(
            sum((r["qty_change"] for r in ledger), Decimal("0")), row["qty"]
        )
        self.assertEqual(
            sum((r["stock_value_change"] for r in ledger), Decimal("0")), row["value"]
        )

    def test_balance_report_as_of_a_date(self):
        early = self.balance(as_of="2026-01-03")[("ITEM", "WH1")]
        self.assertEqual(early["qty"], Decimal("10.000000"))
        self.assertEqual(early["value"], Decimal("10000.00"))

    def test_valuation_report_totals_the_company_stock_value(self):
        report = self.svc.valuation_report(company="AC")
        self.assertEqual(report["total_value"], Decimal("6000.00"))
        self.assertEqual(report["items"][0]["item_code"], "ITEM")
        self.assertEqual(report["items"][0]["qty"], Decimal("6.000000"))

    def test_valuation_report_matches_the_ledger_value(self):
        ledger = self.svc.stock_ledger(item=self.item)
        report = self.svc.valuation_report(company="AC")
        self.assertEqual(
            report["total_value"],
            sum((r["stock_value_change"] for r in ledger), Decimal("0")),
        )

    def test_balance_report_can_include_empty_balances(self):
        self.svc.post_stock_entry(
            "issue",
            "2026-01-06",
            "AC",
            [{"item": self.item, "source_warehouse": "WH1", "qty": "6", "uom": "PCS"}],
        )
        self.assertEqual(self.balance(), {})
        self.assertEqual(len(self.balance(include_zero=True)), 1)

    def test_journal_entries_are_balanced(self):
        entries = self.svc.journal_entries(company="AC")
        self.assertEqual(len(entries), 2)
        for entry in entries:
            debits = sum((line["debit"] for line in entry["lines"]), Decimal("0"))
            credits = sum((line["credit"] for line in entry["lines"]), Decimal("0"))
            self.assertEqual(debits, credits)

    def test_journal_report_totals_the_accounts(self):
        report = self.svc.journal_report(company="AC")
        accounts = {row["account"]: row for row in report}
        self.assertEqual(accounts["1310"]["debit"], Decimal("10000.00"))
        self.assertEqual(accounts["1310"]["credit"], Decimal("4000.00"))
        self.assertEqual(accounts["5100"]["debit"], Decimal("4000.00"))
        self.assertEqual(accounts["2150"]["credit"], Decimal("10000.00"))

    def test_reconciliation_matches_the_ledger_and_the_journal(self):
        reconciliation = self.svc.valuation_reconciliation(company="AC")
        self.assertTrue(reconciliation["balanced"])
        self.assertEqual(reconciliation["outgoing_value"], Decimal("4000.00"))
        self.assertEqual(reconciliation["journal_cogs"], Decimal("4000.00"))
        self.assertEqual(reconciliation["difference"], Decimal("0.00"))

    def test_stock_entries_list_the_lines_in_both_uoms(self):
        entries = self.svc.stock_entries(company="AC")
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["entry_type"], "receipt")
        self.assertEqual(entries[0]["lines"][0]["base_qty"], Decimal("10.000000"))
        self.assertEqual(entries[1]["entry_type"], "issue")

    def test_ledger_can_be_filtered_by_warehouse_and_date(self):
        rows = self.svc.stock_ledger(warehouse="WH1", from_date="2026-01-02")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["entry_type"], "issue")


class SchemaTest(unittest.TestCase):
    def test_an_existing_database_gains_the_base_rate_column(self):
        import os
        import sqlite3
        import tempfile

        from arahint.inventory.db import SCHEMA, connect

        path = tempfile.mktemp(suffix=".db")
        try:
            old = sqlite3.connect(path)
            old.executescript(SCHEMA)
            old.execute("ALTER TABLE stock_entry_lines DROP COLUMN base_rate")
            old.commit()
            old.close()

            conn = connect(path)
            try:
                columns = [
                    row["name"]
                    for row in conn.execute("PRAGMA table_info(stock_entry_lines)")
                ]
                self.assertIn("base_rate", columns)
            finally:
                conn.close()
        finally:
            if os.path.exists(path):
                os.unlink(path)


if __name__ == "__main__":
    unittest.main()
