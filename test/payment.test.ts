import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { DomainError } from "../src/errors.ts";
import { outstanding } from "../src/invoice.ts";
import { addInvoice, idr, setupBook } from "./helpers.ts";

describe("pembayaran sebagian", () => {
  it("memperbarui sisa piutang dan status invoice", () => {
    const { ledger, invoices, book } = setupBook();
    addInvoice(invoices, { id: "INV-001", kind: "sales", party: "Customer A", total: idr(1_000_000) });

    const payment = book.createPayment({
      id: "PAY-001",
      mode: "receive",
      party: "Customer A",
      amount: idr(400_000),
      allocations: [{ invoiceId: "INV-001", amount: idr(400_000) }],
    });
    book.postPayment(payment.id, "2026-01-05");

    const invoice = book.invoice("INV-001");
    assert.equal(invoice.status, "partially_paid");
    assert.equal(invoice.paid.major(), 400_000);
    assert.equal(outstanding(invoice).major(), 600_000);
    assert.equal(book.invoice("INV-001").total.major(), 1_000_000);

    const balance = ledger.balance("AR");
    assert.equal(balance.credit.major(), 400_000);
    const cash = ledger.balance("Bank");
    assert.equal(cash.debit.major(), 400_000);
  });

  it("menutup invoice dan sisa piutang jadi nol saat dibayar penuh", () => {
    const { invoices, book } = setupBook();
    addInvoice(invoices, { id: "INV-002", kind: "sales", party: "Customer A", total: idr(250_000) });

    const payment = book.createPayment({
      id: "PAY-002",
      mode: "receive",
      party: "Customer A",
      amount: idr(250_000),
      allocations: [{ invoiceId: "INV-002", amount: idr(250_000) }],
    });
    book.postPayment(payment.id, "2026-01-06");

    const invoice = book.invoice("INV-002");
    assert.equal(invoice.status, "paid");
    assert.equal(outstanding(invoice).major(), 0);
  });

  it("memperbarui sisa utang pada invoice pembelian", () => {
    const { ledger, invoices, book } = setupBook();
    addInvoice(invoices, { id: "BILL-001", kind: "purchase", party: "Supplier X", total: idr(800_000) });

    const payment = book.createPayment({
      id: "PAY-003",
      mode: "pay",
      party: "Supplier X",
      amount: idr(300_000),
      allocations: [{ invoiceId: "BILL-001", amount: idr(300_000) }],
    });
    book.postPayment(payment.id, "2026-01-07");

    const invoice = book.invoice("BILL-001");
    assert.equal(invoice.status, "partially_paid");
    assert.equal(outstanding(invoice).major(), 500_000);
    assert.equal(ledger.balance("AP").debit.major(), 300_000);
    assert.equal(ledger.balance("Bank").credit.major(), 300_000);
  });
});

describe("alokasi ke beberapa invoice", () => {
  it("membagi satu pembayaran ke beberapa invoice", () => {
    const { ledger, invoices, book } = setupBook();
    addInvoice(invoices, { id: "INV-010", kind: "sales", party: "Customer B", total: idr(500_000) });
    addInvoice(invoices, { id: "INV-011", kind: "sales", party: "Customer B", total: idr(300_000) });

    const payment = book.createPayment({
      id: "PAY-010",
      mode: "receive",
      party: "Customer B",
      amount: idr(600_000),
      allocations: [
        { invoiceId: "INV-010", amount: idr(500_000) },
        { invoiceId: "INV-011", amount: idr(100_000) },
      ],
    });
    book.postPayment(payment.id, "2026-01-10");

    assert.equal(book.invoice("INV-010").status, "paid");
    assert.equal(book.invoice("INV-011").status, "partially_paid");
    assert.equal(outstanding(book.invoice("INV-011")).major(), 200_000);
    assert.equal(ledger.balance("AR").credit.major(), 600_000);
  });

  it("menolak total alokasi yang melebihi nilai pembayaran", () => {
    const { invoices, book } = setupBook();
    addInvoice(invoices, { id: "INV-020", kind: "sales", party: "Customer C", total: idr(500_000) });
    addInvoice(invoices, { id: "INV-021", kind: "sales", party: "Customer C", total: idr(500_000) });

    assert.throws(
      () =>
        book.createPayment({
          id: "PAY-020",
          mode: "receive",
          party: "Customer C",
          amount: idr(600_000),
          allocations: [
            { invoiceId: "INV-020", amount: idr(500_000) },
            { invoiceId: "INV-021", amount: idr(300_000) },
          ],
        }),
      (error: unknown) => {
        assert.ok(error instanceof DomainError);
        assert.equal(error.code, "allocation_exceeds_payment");
        return true;
      },
    );
  });

  it("menolak alokasi ke invoice dengan party atau jenis yang salah", () => {
    const { invoices, book } = setupBook();
    addInvoice(invoices, { id: "INV-030", kind: "sales", party: "Customer D", total: idr(100_000) });
    addInvoice(invoices, { id: "BILL-030", kind: "purchase", party: "Customer D", total: idr(100_000) });

    assert.throws(
      () =>
        book.createPayment({
          id: "PAY-030",
          mode: "receive",
          party: "Customer D",
          amount: idr(100_000),
          allocations: [{ invoiceId: "BILL-030", amount: idr(100_000) }],
        }),
      (error: unknown) => error instanceof DomainError && error.code === "invoice_kind_mismatch",
    );

    assert.throws(
      () =>
        book.createPayment({
          id: "PAY-031",
          mode: "receive",
          party: "Customer lain",
          amount: idr(100_000),
          allocations: [{ invoiceId: "INV-030", amount: idr(100_000) }],
        }),
      (error: unknown) => error instanceof DomainError && error.code === "invoice_party_mismatch",
    );
  });
});

describe("kelebihan bayar", () => {
  it("mencatat kelebihan bayar di akun uang muka dan menutup invoice", () => {
    const { ledger, invoices, book } = setupBook();
    addInvoice(invoices, { id: "INV-040", kind: "sales", party: "Customer E", total: idr(400_000) });

    const payment = book.createPayment({
      id: "PAY-040",
      mode: "receive",
      party: "Customer E",
      amount: idr(500_000),
      allocations: [{ invoiceId: "INV-040", amount: idr(400_000) }],
    });
    assert.equal(payment.unallocated.major(), 100_000);

    book.postPayment(payment.id, "2026-01-12");

    assert.equal(book.invoice("INV-040").status, "paid");
    assert.equal(ledger.balance("Advance").credit.major(), 100_000);
    assert.equal(ledger.balance("Bank").debit.major(), 500_000);
  });

  it("mencatat kelebihan alokasi di atas sisa tagihan sebagai uang muka", () => {
    const { ledger, invoices, book } = setupBook();
    addInvoice(invoices, { id: "INV-041", kind: "sales", party: "Customer F", total: idr(200_000) });

    const payment = book.createPayment({
      id: "PAY-041",
      mode: "receive",
      party: "Customer F",
      amount: idr(300_000),
      allocations: [{ invoiceId: "INV-041", amount: idr(300_000) }],
    });
    book.postPayment(payment.id, "2026-01-13");

    assert.equal(book.invoice("INV-041").status, "paid");
    assert.equal(outstanding(book.invoice("INV-041")).major(), 0);
    assert.equal(ledger.balance("AR").credit.major(), 200_000);
    assert.equal(ledger.balance("Advance").credit.major(), 100_000);
  });
});
