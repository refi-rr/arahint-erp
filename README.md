# arahint-erp

Core inventory for arahint-erp, built as a small dependency-free Python
package. It covers the item master with UOM conversion, warehouses per company,
stock entries (receipt, issue, transfer), an append-only stock ledger, and the
stock balance, valuation, and journal reports.

## Layout

```
arahint/
  inventory/
    db.py        SQLite schema and connection setup
    service.py   InventoryService: masters, posting, valuation, reports
tests/
  test_inventory.py
```

Python 3.11+ is the only requirement. There are no third-party dependencies.

## Quick start

```python
from arahint.inventory import InventoryService
from arahint.inventory.db import connect

service = InventoryService(connect("arahint.db"))
service.create_company("AC", "Arahint Company")
service.create_uom("PCS", "Piece")
service.create_uom("BOX", "Box")
service.create_warehouse("AC", "WH1", "Main Warehouse")
service.create_warehouse("AC", "WH2", "Branch Warehouse")
service.create_item("ITEM-1", "Widget", "PCS", valuation_method="fifo")
service.add_uom_conversion("ITEM-1", "BOX", 12)

service.post_stock_entry(
    "receipt",
    "2026-01-01",
    "AC",
    [{"item": "ITEM-1", "target_warehouse": "WH1", "qty": "2", "uom": "BOX", "rate": "12000"}],
)
service.post_stock_entry(
    "issue",
    "2026-01-02",
    "AC",
    [{"item": "ITEM-1", "source_warehouse": "WH1", "qty": "6", "uom": "PCS"}],
)
service.post_stock_entry(
    "transfer",
    "2026-01-03",
    "AC",
    [{"item": "ITEM-1", "source_warehouse": "WH1", "target_warehouse": "WH2", "qty": "6", "uom": "PCS"}],
)

service.stock_balance(as_of="2026-01-03", company="AC")
service.valuation_report(as_of="2026-01-03", company="AC")
service.outgoing_valuation(company="AC")
service.journal_entries(company="AC")
```

Quantities are stored in the item's base UOM. A line may use any UOM registered
for the item, with `qty * factor` converted to the base UOM. Receipt rates are
per line UOM; everything stored in the ledger is per base UOM.

## Behaviour

- **Stock ledger is the source of truth.** Every posting writes an immutable
  ledger row with the signed quantity, signed value, valuation rate, and the
  running balance per item and warehouse. Reports aggregate these rows.
- **Stock balance** sums the ledger up to (and including) the selected date,
  grouped by item and warehouse.
- **Valuation** supports `moving_average` and `fifo` per item. Outgoing value is
  computed when the issue or transfer-out is posted, using the item's method.
  Transfers move the same value from source to target.
- **Journal** entries are written for every stock entry and stay balanced:
  receipts debit inventory and credit the inventory-input account; issues debit
  COGS and credit inventory; transfers debit inventory in the target and credit
  inventory in the source. Received, issued, and transferred values always equal
  the ledger's stock value change.
- **Reconciliation.** `valuation_reconciliation()` reports the outgoing value
  from the ledger, the COGS debit from the journal, and whether they differ.
- **Chronology.** Backdated entries are rejected so the running balances in the
  ledger remain valid. Post each item/warehouse in non-decreasing date order.
- Money is quantised to 2 decimals, quantities to 6, and rates to 6. Decimals
  are used throughout; no binary floating point is involved.

## Tests

```
python3 -m unittest discover -s tests -v
```
