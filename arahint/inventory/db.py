"""SQLite schema and connection helpers for the inventory core."""

from __future__ import annotations

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'IDR'
);

CREATE TABLE IF NOT EXISTS uoms (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    base_uom_id INTEGER NOT NULL REFERENCES uoms(id),
    valuation_method TEXT NOT NULL CHECK (valuation_method IN ('fifo', 'moving_average'))
);

CREATE TABLE IF NOT EXISTS item_uom_conversions (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES items(id),
    uom_id INTEGER NOT NULL REFERENCES uoms(id),
    factor TEXT NOT NULL,
    UNIQUE (item_id, uom_id)
);

CREATE TABLE IF NOT EXISTS warehouses (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    UNIQUE (company_id, code)
);

CREATE TABLE IF NOT EXISTS stock_entries (
    id INTEGER PRIMARY KEY,
    entry_type TEXT NOT NULL CHECK (entry_type IN ('receipt', 'issue', 'transfer')),
    posting_date TEXT NOT NULL,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    reference TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stock_entry_lines (
    id INTEGER PRIMARY KEY,
    entry_id INTEGER NOT NULL REFERENCES stock_entries(id),
    line_no INTEGER NOT NULL,
    item_id INTEGER NOT NULL REFERENCES items(id),
    source_warehouse_id INTEGER REFERENCES warehouses(id),
    target_warehouse_id INTEGER REFERENCES warehouses(id),
    qty TEXT NOT NULL,
    uom_id INTEGER NOT NULL REFERENCES uoms(id),
    rate TEXT,
    UNIQUE (entry_id, line_no)
);

CREATE TABLE IF NOT EXISTS stock_ledger (
    id INTEGER PRIMARY KEY,
    entry_id INTEGER NOT NULL REFERENCES stock_entries(id),
    entry_line_id INTEGER NOT NULL REFERENCES stock_entry_lines(id),
    item_id INTEGER NOT NULL REFERENCES items(id),
    warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
    posting_date TEXT NOT NULL,
    qty_change TEXT NOT NULL,
    valuation_rate TEXT NOT NULL,
    stock_value_change TEXT NOT NULL,
    qty_after TEXT NOT NULL,
    stock_value_after TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_stock_ledger_item_warehouse
    ON stock_ledger (item_id, warehouse_id, posting_date, id);
CREATE INDEX IF NOT EXISTS idx_stock_ledger_date
    ON stock_ledger (posting_date, id);

CREATE TABLE IF NOT EXISTS stock_layers (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES items(id),
    warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
    entry_id INTEGER NOT NULL REFERENCES stock_entries(id),
    received_at TEXT NOT NULL,
    qty_remaining TEXT NOT NULL,
    value_remaining TEXT NOT NULL,
    rate TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_stock_layers_open
    ON stock_layers (item_id, warehouse_id, id);

CREATE TABLE IF NOT EXISTS journal_entries (
    id INTEGER PRIMARY KEY,
    entry_id INTEGER NOT NULL REFERENCES stock_entries(id),
    posting_date TEXT NOT NULL,
    reference TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS journal_lines (
    id INTEGER PRIMARY KEY,
    journal_entry_id INTEGER NOT NULL REFERENCES journal_entries(id),
    account TEXT NOT NULL,
    debit TEXT NOT NULL DEFAULT '0',
    credit TEXT NOT NULL DEFAULT '0',
    item_id INTEGER REFERENCES items(id),
    warehouse_id INTEGER REFERENCES warehouses(id)
);

CREATE INDEX IF NOT EXISTS idx_journal_lines_journal
    ON journal_lines (journal_entry_id);
"""


def connect(path: str = ":memory:") -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(SCHEMA)
    return connection
