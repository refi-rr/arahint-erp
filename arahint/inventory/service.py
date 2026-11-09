"""Inventory core: items, warehouses, stock ledger, valuation, and journals.

The service owns the inventory workflow. It converts transactions into the
item's base UOM through the UOM converter, values every movement through the
valuation registry, and writes the result to an append-only stock ledger that
the reports read back.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from decimal import Decimal

from .errors import (
    DuplicateError,
    NotFoundError,
    ValidationError,
)
from .numeric import (
    quantize_money,
    quantize_qty,
    quantize_rate,
    to_decimal,
)
from .uom import UomConverter
from .valuation import (
    MOVING_AVERAGE,
    VALUATION_METHODS,
    Movement,
    ValuationRegistry,
    ValuationState,
)

ENTRY_TYPES = ("receipt", "issue", "transfer")


def _text(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be a non-empty string")
    return value.strip()


def _require_date(value, field: str) -> str:
    try:
        return datetime.strptime(_text(value, field), "%Y-%m-%d").date().isoformat()
    except ValueError as exc:
        raise ValidationError(f"{field} must use the YYYY-MM-DD format") from exc


def _now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat()


class InventoryService:
    """Transactional inventory operations backed by a SQLite connection."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        inventory_account: str = "1310",
        cogs_account: str = "5100",
        inventory_input_account: str = "2150",
    ) -> None:
        self.conn = connection
        self.inventory_account = inventory_account
        self.cogs_account = cogs_account
        self.inventory_input_account = inventory_input_account
        self.uom = UomConverter(connection)
        self.valuations = ValuationRegistry(connection)

    def close(self) -> None:
        self.conn.close()

    # ------------------------------------------------------------------ masters

    def create_company(self, code: str, name: str, currency: str = "IDR") -> int:
        return self._insert(
            "INSERT INTO companies (code, name, currency) VALUES (?, ?, ?)",
            (_text(code, "code"), _text(name, "name"), _text(currency, "currency")),
            f"company {code!r}",
        )

    def create_uom(self, code: str, name: str | None = None) -> int:
        return self._insert(
            "INSERT INTO uoms (code, name) VALUES (?, ?)",
            (_text(code, "code"), _text(name or code, "name")),
            f"uom {code!r}",
        )

    def create_item(
        self,
        code: str,
        name: str,
        base_uom: str,
        valuation_method: str = MOVING_AVERAGE,
    ) -> int:
        if valuation_method not in VALUATION_METHODS:
            raise ValidationError(
                f"valuation_method must be one of {', '.join(VALUATION_METHODS)}"
            )
        uom = self._get_uom(base_uom)
        return self._insert(
            "INSERT INTO items (code, name, base_uom_id, valuation_method) VALUES (?, ?, ?, ?)",
            (_text(code, "code"), _text(name, "name"), uom["id"], valuation_method),
            f"item {code!r}",
        )

    def add_uom_conversion(self, item: str, uom: str, factor) -> int:
        item_row = self._get_item(item)
        uom_row = self._get_uom(uom)
        if uom_row["id"] == item_row["base_uom_id"]:
            raise ValidationError("base UOM does not need a conversion factor")
        factor_value = to_decimal(factor)
        if factor_value <= 0:
            raise ValidationError("conversion factor must be greater than zero")
        return self._insert(
            "INSERT INTO item_uom_conversions (item_id, uom_id, factor) VALUES (?, ?, ?)",
            (item_row["id"], uom_row["id"], str(factor_value)),
            f"conversion for item {item!r} and uom {uom!r}",
        )

    def create_warehouse(self, company: str, code: str, name: str | None = None) -> int:
        company_row = self._get_company(company)
        return self._insert(
            "INSERT INTO warehouses (code, name, company_id) VALUES (?, ?, ?)",
            (_text(code, "code"), _text(name or code, "name"), company_row["id"]),
            f"warehouse {code!r} for company {company!r}",
        )

    # -------------------------------------------------------------- master reads

    def get_item(self, code: str) -> dict:
        """An item with its base UOM and the other UOMs it offers."""
        item = self._get_item(code)
        uom = self.conn.execute(
            "SELECT code, name FROM uoms WHERE id = ?", (item["base_uom_id"],)
        ).fetchone()
        conversions = [
            {
                "uom_code": row["code"],
                "uom_name": row["name"],
                "factor": to_decimal(row["factor"]),
            }
            for row in self.conn.execute(
                "SELECT u.code, u.name, c.factor FROM item_uom_conversions c "
                "JOIN uoms u ON u.id = c.uom_id WHERE c.item_id = ? ORDER BY u.code",
                (item["id"],),
            )
        ]
        return {
            "code": item["code"],
            "name": item["name"],
            "base_uom": uom["code"],
            "base_uom_name": uom["name"],
            "valuation_method": item["valuation_method"],
            "uoms": conversions,
        }

    def list_items(self) -> list[dict]:
        """Every item with its base UOM and conversion factors."""
        return [self.get_item(row["code"]) for row in
                self.conn.execute("SELECT code FROM items ORDER BY code")]

    def list_uoms(self) -> list[dict]:
        return [
            {"code": row["code"], "name": row["name"]}
            for row in self.conn.execute("SELECT code, name FROM uoms ORDER BY code")
        ]

    def list_warehouses(self, company: str) -> list[dict]:
        company_row = self._get_company(company)
        return [
            {"code": row["code"], "name": row["name"]}
            for row in self.conn.execute(
                "SELECT code, name FROM warehouses WHERE company_id = ? ORDER BY code",
                (company_row["id"],),
            )
        ]

    def convert_to_base(self, item: str, uom: str, quantity) -> dict:
        """Convert a quantity in ``uom`` into the item's base UOM."""
        item_row = self._get_item(item)
        uom_row = self._get_uom(uom)
        conversion = self.uom.convert(item_row, uom_row["id"], quantity)
        return {
            "item_code": item_row["code"],
            "uom_code": uom_row["code"],
            "base_uom_code": self._base_uom_code(item_row),
            "quantity": conversion.txn_qty,
            "factor": conversion.factor,
            "base_quantity": conversion.base_qty,
        }

    # -------------------------------------------------------------- stock posting

    def post_stock_entry(
        self,
        entry_type: str,
        posting_date: str,
        company: str,
        lines: list[dict],
        reference: str | None = None,
    ) -> int:
        if entry_type not in ENTRY_TYPES:
            raise ValidationError(f"entry_type must be one of {', '.join(ENTRY_TYPES)}")
        if not isinstance(lines, list) or not lines:
            raise ValidationError("a stock entry needs at least one line")
        posting = _require_date(posting_date, "posting_date")
        company_row = self._get_company(company)

        with self.conn:
            entry_id = self.conn.execute(
                "INSERT INTO stock_entries "
                "(entry_type, posting_date, company_id, reference, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (entry_type, posting, company_row["id"], reference, _now()),
            ).lastrowid
            journal_id = self.conn.execute(
                "INSERT INTO journal_entries "
                "(entry_id, posting_date, reference, created_at) VALUES (?, ?, ?, ?)",
                (entry_id, posting, reference, _now()),
            ).lastrowid

            journal_lines: list[tuple] = []
            for line_no, line in enumerate(lines, start=1):
                if not isinstance(line, dict):
                    raise ValidationError("every stock entry line must be a mapping")
                if entry_type == "receipt":
                    self._post_receipt(
                        entry_id, line_no, posting, company_row, line, journal_lines
                    )
                elif entry_type == "issue":
                    self._post_issue(
                        entry_id, line_no, posting, company_row, line, journal_lines
                    )
                else:
                    self._post_transfer(
                        entry_id, line_no, posting, company_row, line, journal_lines
                    )

            self._write_journal(journal_id, journal_lines)

        return entry_id

    def _post_receipt(
        self, entry_id, line_no, posting, company_row, line, journal_lines
    ) -> None:
        item = self._get_item(line.get("item"))
        warehouse = self._get_warehouse(company_row["id"], line.get("target_warehouse"))
        uom = self._get_uom(line.get("uom"))
        if "rate" not in line or line["rate"] is None:
            raise ValidationError("receipt needs a rate")
        rate = to_decimal(line["rate"])
        if rate < 0:
            raise ValidationError("receipt rate cannot be negative")

        conversion = self.uom.convert(item, uom["id"], line.get("qty"))
        if conversion.txn_qty <= 0:
            raise ValidationError("receipt quantity must be greater than zero")

        # The rate is given per transaction UOM, so the money value is known
        # before conversion and is preserved by it.
        value = quantize_money(conversion.txn_qty * rate)
        base_rate = self.uom.base_rate(value, conversion.base_qty)

        self._assert_chronological(item["id"], warehouse["id"], posting)
        state = self._state(item["id"], warehouse["id"])
        movement = Movement(item, warehouse["id"], entry_id, posting)
        result = self.valuations.for_item(item).receipt(
            movement, state, conversion.base_qty, value
        )

        line_id = self._insert_entry_line(
            entry_id, line_no, item["id"], None, warehouse["id"], conversion, base_rate
        )
        self._insert_ledger(
            entry_id,
            line_id,
            item["id"],
            warehouse["id"],
            posting,
            conversion.base_qty,
            base_rate,
            value,
            result.qty,
            result.value,
        )

        journal_lines.append(
            (self.inventory_account, value, Decimal("0"), item["id"], warehouse["id"])
        )
        journal_lines.append(
            (self.inventory_input_account, Decimal("0"), value, item["id"], warehouse["id"])
        )

    def _post_issue(
        self, entry_id, line_no, posting, company_row, line, journal_lines
    ) -> None:
        item = self._get_item(line.get("item"))
        warehouse = self._get_warehouse(company_row["id"], line.get("source_warehouse"))
        uom = self._get_uom(line.get("uom"))

        conversion = self.uom.convert(item, uom["id"], line.get("qty"))
        if conversion.txn_qty <= 0:
            raise ValidationError("issue quantity must be greater than zero")

        self._assert_chronological(item["id"], warehouse["id"], posting)
        state = self._state(item["id"], warehouse["id"])
        if conversion.base_qty > state.qty:
            raise ValidationError(
                f"insufficient stock for item {item['code']!r} in warehouse {warehouse['code']!r}"
            )

        movement = Movement(item, warehouse["id"], entry_id, posting)
        result = self.valuations.for_item(item).issue(movement, state, conversion.base_qty)
        value = quantize_money(abs(result.movement_value))

        line_id = self._insert_entry_line(
            entry_id, line_no, item["id"], warehouse["id"], None, conversion, None
        )
        self._insert_ledger(
            entry_id,
            line_id,
            item["id"],
            warehouse["id"],
            posting,
            -conversion.base_qty,
            result.rate,
            -value,
            result.qty,
            result.value,
        )

        journal_lines.append(
            (self.cogs_account, value, Decimal("0"), item["id"], warehouse["id"])
        )
        journal_lines.append(
            (self.inventory_account, Decimal("0"), value, item["id"], warehouse["id"])
        )

    def _post_transfer(
        self, entry_id, line_no, posting, company_row, line, journal_lines
    ) -> None:
        item = self._get_item(line.get("item"))
        source = self._get_warehouse(company_row["id"], line.get("source_warehouse"))
        target = self._get_warehouse(company_row["id"], line.get("target_warehouse"))
        uom = self._get_uom(line.get("uom"))

        conversion = self.uom.convert(item, uom["id"], line.get("qty"))
        if conversion.txn_qty <= 0:
            raise ValidationError("transfer quantity must be greater than zero")
        if source["id"] == target["id"]:
            raise ValidationError("transfer source and target warehouses must differ")

        self._assert_chronological(item["id"], source["id"], posting)
        self._assert_chronological(item["id"], target["id"], posting)
        source_state = self._state(item["id"], source["id"])
        if conversion.base_qty > source_state.qty:
            raise ValidationError(
                f"insufficient stock for item {item['code']!r} in warehouse {source['code']!r}"
            )
        target_state = self._state(item["id"], target["id"])

        # The value leaving the source is the value arriving at the target, so
        # a transfer never changes the total stock value of the company.
        source_movement = Movement(item, source["id"], entry_id, posting)
        source_result = self.valuations.for_item(item).issue(
            source_movement, source_state, conversion.base_qty
        )
        value = quantize_money(abs(source_result.movement_value))

        target_movement = Movement(item, target["id"], entry_id, posting)
        target_result = self.valuations.for_item(item).receipt(
            target_movement, target_state, conversion.base_qty, value
        )

        line_id = self._insert_entry_line(
            entry_id, line_no, item["id"], source["id"], target["id"], conversion, None
        )
        self._insert_ledger(
            entry_id,
            line_id,
            item["id"],
            source["id"],
            posting,
            -conversion.base_qty,
            source_result.rate,
            -value,
            source_result.qty,
            source_result.value,
        )
        self._insert_ledger(
            entry_id,
            line_id,
            item["id"],
            target["id"],
            posting,
            conversion.base_qty,
            target_result.rate,
            value,
            target_result.qty,
            target_result.value,
        )

        journal_lines.append(
            (self.inventory_account, value, Decimal("0"), item["id"], target["id"])
        )
        journal_lines.append(
            (self.inventory_account, Decimal("0"), value, item["id"], source["id"])
        )

    # -------------------------------------------------------------------- reports

    def stock_balance(
        self,
        as_of: str | None = None,
        company: str | None = None,
        include_zero: bool = False,
    ) -> list[dict]:
        as_of = _require_date(as_of, "as_of") if as_of else None
        sql = (
            "SELECT l.item_id, l.warehouse_id, l.qty_change, l.stock_value_change, "
            "i.code AS item_code, i.name AS item_name, "
            "w.code AS warehouse_code, w.name AS warehouse_name, "
            "c.code AS company_code "
            "FROM stock_ledger l "
            "JOIN items i ON i.id = l.item_id "
            "JOIN warehouses w ON w.id = l.warehouse_id "
            "JOIN companies c ON c.id = w.company_id "
            "WHERE 1 = 1"
        )
        params: list = []
        if as_of:
            sql += " AND l.posting_date <= ?"
            params.append(as_of)
        if company:
            sql += " AND c.code = ?"
            params.append(_text(company, "company"))
        sql += " ORDER BY i.code, w.code"

        aggregates: dict[tuple, dict] = {}
        for row in self.conn.execute(sql, params):
            key = (row["item_id"], row["warehouse_id"])
            bucket = aggregates.setdefault(
                key,
                {
                    "item_code": row["item_code"],
                    "item_name": row["item_name"],
                    "warehouse_code": row["warehouse_code"],
                    "warehouse_name": row["warehouse_name"],
                    "company_code": row["company_code"],
                    "qty": Decimal("0"),
                    "value": Decimal("0"),
                },
            )
            bucket["qty"] += to_decimal(row["qty_change"])
            bucket["value"] += to_decimal(row["stock_value_change"])

        result = []
        for bucket in aggregates.values():
            bucket["qty"] = quantize_qty(bucket["qty"])
            bucket["value"] = quantize_money(bucket["value"])
            bucket["rate"] = (
                quantize_rate(bucket["value"] / bucket["qty"]) if bucket["qty"] else Decimal("0.000000")
            )
            if not include_zero and bucket["qty"] == 0 and bucket["value"] == 0:
                continue
            result.append(bucket)
        return result

    def stock_ledger(
        self,
        item: str | None = None,
        warehouse: str | None = None,
        company: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict]:
        sql = (
            "SELECT l.*, i.code AS item_code, w.code AS warehouse_code, "
            "c.code AS company_code, e.entry_type, e.reference "
            "FROM stock_ledger l "
            "JOIN items i ON i.id = l.item_id "
            "JOIN warehouses w ON w.id = l.warehouse_id "
            "JOIN companies c ON c.id = w.company_id "
            "JOIN stock_entries e ON e.id = l.entry_id "
            "WHERE 1 = 1"
        )
        params: list = []
        if item:
            sql += " AND i.code = ?"
            params.append(_text(item, "item"))
        if warehouse:
            sql += " AND w.code = ?"
            params.append(_text(warehouse, "warehouse"))
        if company:
            sql += " AND c.code = ?"
            params.append(_text(company, "company"))
        if from_date:
            sql += " AND l.posting_date >= ?"
            params.append(_require_date(from_date, "from_date"))
        if to_date:
            sql += " AND l.posting_date <= ?"
            params.append(_require_date(to_date, "to_date"))
        sql += " ORDER BY l.posting_date, l.id"

        rows = []
        for row in self.conn.execute(sql, params):
            rows.append(
                {
                    "id": row["id"],
                    "entry_id": row["entry_id"],
                    "entry_type": row["entry_type"],
                    "reference": row["reference"],
                    "posting_date": row["posting_date"],
                    "item_code": row["item_code"],
                    "warehouse_code": row["warehouse_code"],
                    "company_code": row["company_code"],
                    "qty_change": quantize_qty(row["qty_change"]),
                    "valuation_rate": quantize_rate(row["valuation_rate"]),
                    "stock_value_change": quantize_money(row["stock_value_change"]),
                    "qty_after": quantize_qty(row["qty_after"]),
                    "stock_value_after": quantize_money(row["stock_value_after"]),
                }
            )
        return rows

    def valuation_report(
        self, as_of: str | None = None, company: str | None = None
    ) -> dict:
        balances = self.stock_balance(as_of=as_of, company=company)
        items: dict[str, dict] = {}
        for row in balances:
            bucket = items.setdefault(
                row["item_code"],
                {
                    "item_code": row["item_code"],
                    "item_name": row["item_name"],
                    "qty": Decimal("0"),
                    "value": Decimal("0"),
                },
            )
            bucket["qty"] += row["qty"]
            bucket["value"] += row["value"]

        result = []
        total_value = Decimal("0.00")
        for bucket in items.values():
            bucket["qty"] = quantize_qty(bucket["qty"])
            bucket["value"] = quantize_money(bucket["value"])
            bucket["rate"] = (
                quantize_rate(bucket["value"] / bucket["qty"]) if bucket["qty"] else Decimal("0.000000")
            )
            total_value += bucket["value"]
            result.append(bucket)
        result.sort(key=lambda row: row["item_code"])
        return {"items": result, "total_value": quantize_money(total_value)}

    def outgoing_valuation(
        self,
        from_date: str | None = None,
        to_date: str | None = None,
        company: str | None = None,
    ) -> dict:
        sql = (
            "SELECT l.item_id, i.code AS item_code, i.name AS item_name, "
            "l.qty_change, l.stock_value_change "
            "FROM stock_ledger l "
            "JOIN stock_entries e ON e.id = l.entry_id "
            "JOIN items i ON i.id = l.item_id "
            "JOIN warehouses w ON w.id = l.warehouse_id "
            "JOIN companies c ON c.id = w.company_id "
            "WHERE e.entry_type = 'issue'"
        )
        params: list = []
        if from_date:
            sql += " AND l.posting_date >= ?"
            params.append(_require_date(from_date, "from_date"))
        if to_date:
            sql += " AND l.posting_date <= ?"
            params.append(_require_date(to_date, "to_date"))
        if company:
            sql += " AND c.code = ?"
            params.append(_text(company, "company"))
        sql += " ORDER BY i.code"

        items: dict[str, dict] = {}
        total_qty = Decimal("0")
        total_value = Decimal("0")
        for row in self.conn.execute(sql, params):
            bucket = items.setdefault(
                row["item_code"],
                {
                    "item_code": row["item_code"],
                    "item_name": row["item_name"],
                    "qty": Decimal("0"),
                    "value": Decimal("0"),
                },
            )
            quantity = abs(to_decimal(row["qty_change"]))
            value = abs(to_decimal(row["stock_value_change"]))
            bucket["qty"] += quantity
            bucket["value"] += value
            total_qty += quantity
            total_value += value

        result = []
        for bucket in items.values():
            bucket["qty"] = quantize_qty(bucket["qty"])
            bucket["value"] = quantize_money(bucket["value"])
            bucket["rate"] = (
                quantize_rate(bucket["value"] / bucket["qty"]) if bucket["qty"] else Decimal("0.000000")
            )
            result.append(bucket)
        result.sort(key=lambda row: row["item_code"])
        return {
            "items": result,
            "total_qty": quantize_qty(total_qty),
            "total_value": quantize_money(total_value),
        }

    def journal_entries(
        self,
        from_date: str | None = None,
        to_date: str | None = None,
        company: str | None = None,
    ) -> list[dict]:
        sql = (
            "SELECT je.id, je.entry_id, je.posting_date, je.reference, "
            "e.entry_type, c.code AS company_code "
            "FROM journal_entries je "
            "JOIN stock_entries e ON e.id = je.entry_id "
            "JOIN companies c ON c.id = e.company_id "
            "WHERE 1 = 1"
        )
        params: list = []
        if from_date:
            sql += " AND je.posting_date >= ?"
            params.append(_require_date(from_date, "from_date"))
        if to_date:
            sql += " AND je.posting_date <= ?"
            params.append(_require_date(to_date, "to_date"))
        if company:
            sql += " AND c.code = ?"
            params.append(_text(company, "company"))
        sql += " ORDER BY je.posting_date, je.id"

        entries = []
        for row in self.conn.execute(sql, params):
            lines = []
            for line in self.conn.execute(
                "SELECT jl.account, jl.debit, jl.credit, "
                "i.code AS item_code, w.code AS warehouse_code "
                "FROM journal_lines jl "
                "LEFT JOIN items i ON i.id = jl.item_id "
                "LEFT JOIN warehouses w ON w.id = jl.warehouse_id "
                "WHERE jl.journal_entry_id = ? ORDER BY jl.id",
                (row["id"],),
            ):
                lines.append(
                    {
                        "account": line["account"],
                        "debit": quantize_money(line["debit"]),
                        "credit": quantize_money(line["credit"]),
                        "item_code": line["item_code"],
                        "warehouse_code": line["warehouse_code"],
                    }
                )
            entries.append(
                {
                    "id": row["id"],
                    "entry_id": row["entry_id"],
                    "entry_type": row["entry_type"],
                    "reference": row["reference"],
                    "posting_date": row["posting_date"],
                    "company_code": row["company_code"],
                    "lines": lines,
                }
            )
        return entries

    def journal_report(
        self,
        from_date: str | None = None,
        to_date: str | None = None,
        company: str | None = None,
    ) -> list[dict]:
        accounts: dict[str, dict] = {}
        for entry in self.journal_entries(from_date, to_date, company):
            for line in entry["lines"]:
                bucket = accounts.setdefault(
                    line["account"],
                    {"account": line["account"], "debit": Decimal("0"), "credit": Decimal("0")},
                )
                bucket["debit"] += line["debit"]
                bucket["credit"] += line["credit"]
        result = []
        for account in sorted(accounts):
            bucket = accounts[account]
            bucket["debit"] = quantize_money(bucket["debit"])
            bucket["credit"] = quantize_money(bucket["credit"])
            result.append(bucket)
        return result

    def valuation_reconciliation(
        self,
        from_date: str | None = None,
        to_date: str | None = None,
        company: str | None = None,
    ) -> dict:
        outgoing = self.outgoing_valuation(from_date, to_date, company)
        journal = {row["account"]: row for row in self.journal_report(from_date, to_date, company)}
        journal_cogs = journal.get(self.cogs_account, {}).get("debit", Decimal("0.00"))
        difference = quantize_money(outgoing["total_value"] - journal_cogs)
        return {
            "outgoing_value": outgoing["total_value"],
            "journal_cogs": quantize_money(journal_cogs),
            "difference": difference,
            "balanced": difference == 0,
        }

    # -------------------------------------------------------------------- helpers

    def _insert(self, sql: str, params: tuple, label: str) -> int:
        try:
            with self.conn:
                return self.conn.execute(sql, params).lastrowid
        except sqlite3.IntegrityError as exc:
            raise DuplicateError(f"{label} already exists") from exc

    def _get_company(self, code) -> sqlite3.Row:
        return self._get_one("SELECT * FROM companies WHERE code = ?", code, "company")

    def _get_uom(self, code) -> sqlite3.Row:
        return self._get_one("SELECT * FROM uoms WHERE code = ?", code, "uom")

    def _get_item(self, code) -> sqlite3.Row:
        return self._get_one("SELECT * FROM items WHERE code = ?", code, "item")

    def _base_uom_code(self, item: sqlite3.Row) -> str:
        row = self.conn.execute(
            "SELECT code FROM uoms WHERE id = ?", (item["base_uom_id"],)
        ).fetchone()
        return row["code"]

    def _get_warehouse(self, company_id: int, code) -> sqlite3.Row:
        if not isinstance(code, str) or not code.strip():
            raise ValidationError("warehouse code is required")
        row = self.conn.execute(
            "SELECT * FROM warehouses WHERE company_id = ? AND code = ?",
            (company_id, code.strip()),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"warehouse {code!r} not found for this company")
        return row

    def _get_one(self, sql: str, code, label: str) -> sqlite3.Row:
        if not isinstance(code, str) or not code.strip():
            raise ValidationError(f"{label} code is required")
        row = self.conn.execute(sql, (code.strip(),)).fetchone()
        if row is None:
            raise NotFoundError(f"{label} {code!r} not found")
        return row

    def _state(self, item_id: int, warehouse_id: int) -> ValuationState:
        row = self.conn.execute(
            "SELECT qty_after, stock_value_after FROM stock_ledger "
            "WHERE item_id = ? AND warehouse_id = ? "
            "ORDER BY posting_date DESC, id DESC LIMIT 1",
            (item_id, warehouse_id),
        ).fetchone()
        if row is None:
            return ValuationState(Decimal("0"), Decimal("0.00"))
        return ValuationState(
            to_decimal(row["qty_after"]), to_decimal(row["stock_value_after"])
        )

    def _assert_chronological(self, item_id: int, warehouse_id: int, posting: str) -> None:
        row = self.conn.execute(
            "SELECT posting_date FROM stock_ledger "
            "WHERE item_id = ? AND warehouse_id = ? "
            "ORDER BY posting_date DESC, id DESC LIMIT 1",
            (item_id, warehouse_id),
        ).fetchone()
        if row is not None and posting < row["posting_date"]:
            raise ValidationError(
                "backdated stock entries are not supported; "
                f"the latest posting date is {row['posting_date']}"
            )

    def _insert_entry_line(
        self, entry_id, line_no, item_id, source_id, target_id, conversion, rate
    ) -> int:
        """Store the line in the transaction UOM alongside its base quantity."""
        return self.conn.execute(
            "INSERT INTO stock_entry_lines "
            "(entry_id, line_no, item_id, source_warehouse_id, target_warehouse_id, "
            "qty, uom_id, rate, base_qty) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                entry_id,
                line_no,
                item_id,
                source_id,
                target_id,
                str(quantize_qty(conversion.txn_qty)),
                conversion.uom_id,
                str(quantize_rate(rate)) if rate is not None else None,
                str(conversion.base_qty),
            ),
        ).lastrowid

    def _insert_ledger(
        self,
        entry_id,
        line_id,
        item_id,
        warehouse_id,
        posting,
        qty_change,
        valuation_rate,
        value_change,
        qty_after,
        value_after,
    ) -> int:
        return self.conn.execute(
            "INSERT INTO stock_ledger "
            "(entry_id, entry_line_id, item_id, warehouse_id, posting_date, "
            "qty_change, valuation_rate, stock_value_change, qty_after, stock_value_after, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                entry_id,
                line_id,
                item_id,
                warehouse_id,
                posting,
                str(quantize_qty(qty_change)),
                str(quantize_rate(valuation_rate)),
                str(quantize_money(value_change)),
                str(quantize_qty(qty_after)),
                str(quantize_money(value_after)),
                _now(),
            ),
        ).lastrowid

    def _write_journal(self, journal_id: int, lines: list[tuple]) -> None:
        debit_total = sum((line[1] for line in lines), Decimal("0"))
        credit_total = sum((line[2] for line in lines), Decimal("0"))
        if quantize_money(debit_total) != quantize_money(credit_total):
            raise ValidationError("journal entry is not balanced")
        for account, debit, credit, item_id, warehouse_id in lines:
            self.conn.execute(
                "INSERT INTO journal_lines "
                "(journal_entry_id, account, debit, credit, item_id, warehouse_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    journal_id,
                    account,
                    str(quantize_money(debit)),
                    str(quantize_money(credit)),
                    item_id,
                    warehouse_id,
                ),
            )
