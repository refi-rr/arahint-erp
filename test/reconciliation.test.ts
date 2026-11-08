import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { DomainError } from "../src/errors.ts";
import { BankReconciliation } from "../src/reconciliation.ts";
import { addInvoice, idr, setupBook } from "./helpers.ts";

function setup(): { book: ReturnType<typeof setupBook>["book"]; reconciliation: BankReconciliation } {
  const { book } = setupBook();
  return {
    book,
    reconciliation: new BankReconciliation({ currency: "IDR", payments: [] }),
  };
}

describe("rekonsiliasi bank", () => {
  it("mencocokkan baris mutasi bank dengan pembayaran", () => {
    const { invoices, book } = setupBook();
    addInvoice(invoices, { id: "INV-100", kind: "sales", party: "Customer A", total: idr(500_000) });

    const payment = book.createPayment({
      id: "PAY-100",
      mode: "receive",
      party: "Customer A",
      amount: idr(500_000),
      allocations: [{ invoiceId: "INV-100", amount: idr(500_000) }],
    });
    book.postPayment(payment.id, "2026-02-01");

    const reconciliation = new BankReconciliation({ currency: "IDR", payments: book.allPayments() });
    reconciliation.addTransaction({
      id: "BNK-1",
      date: "2026-02-02",
      description: "Kredit transaksi",
      amount: idr(500_000),
      currency: "IDR",
    });

    const match = reconciliation.match("BNK-1", "PAY-100", "2026-02-03");
    assert.equal(match.paymentId, "PAY-100");
    assert.equal(match.amount.major(), 500_000);

    const report = reconciliation.report();
    assert.equal(report.matches.length, 1);
    assert.equal(report.unmatched.length, 0);
    assert.equal(report.difference.major(), 0);
    assert.equal(reconciliation.transaction("BNK-1").matchedPaymentId, "PAY-100");
  });

  it("menampilkan baris yang belum cocok sebagai selisih", () => {
    const { invoices, book } = setupBook();
    addInvoice(invoices, { id: "INV-110", kind: "sales", party: "Customer A", total: idr(500_000) });

    const payment = book.createPayment({
      id: "PAY-110",
      mode: "receive",
      party: "Customer A",
      amount: idr(500_000),
      allocations: [{ invoiceId: "INV-110", amount: idr(500_000) }],
    });
    book.postPayment(payment.id, "2026-02-04");

    const reconciliation = new BankReconciliation({ currency: "IDR", payments: book.allPayments() });
    reconciliation.addTransaction({
      id: "BNK-2",
      date: "2026-02-05",
      description: "Kredit transaksi",
      amount: idr(500_000),
      currency: "IDR",
    });
    reconciliation.addTransaction({
      id: "BNK-3",
      date: "2026-02-05",
      description: "Biaya bank",
      amount: idr(-25_000),
      currency: "IDR",
    });

    reconciliation.match("BNK-2", "PAY-110", "2026-02-06");

    const report = reconciliation.report();
    assert.equal(report.matches.length, 1);
    assert.equal(report.unmatched.length, 1);
    assert.equal(report.unmatched[0]?.id, "BNK-3");
    assert.equal(report.difference.major(), 25_000);
  });

  it("menolak pencocokan dengan nominal atau mata uang yang berbeda", () => {
    const { invoices, book } = setupBook();
    addInvoice(invoices, { id: "INV-120", kind: "sales", party: "Customer A", total: idr(500_000) });

    const payment = book.createPayment({
      id: "PAY-120",
      mode: "receive",
      party: "Customer A",
      amount: idr(500_000),
      allocations: [{ invoiceId: "INV-120", amount: idr(500_000) }],
    });
    book.postPayment(payment.id, "2026-02-07");

    const reconciliation = new BankReconciliation({ currency: "IDR", payments: book.allPayments() });
    reconciliation.addTransaction({
      id: "BNK-4",
      date: "2026-02-08",
      description: "Kredit transaksi",
      amount: idr(400_000),
      currency: "IDR",
    });

    assert.throws(
      () => reconciliation.match("BNK-4", "PAY-120", "2026-02-09"),
      (error: unknown) => error instanceof DomainError && error.code === "match_amount_mismatch",
    );
  });

  it("mencocokkan pembayaran yang di-resolve saat pencocokan", () => {
    const { invoices, book } = setupBook();
    addInvoice(invoices, { id: "INV-140", kind: "sales", party: "Customer A", total: idr(500_000) });

    const reconciliation = new BankReconciliation({
      currency: "IDR",
      paymentLookup: (id) => (id === "PAY-140" ? book.payment("PAY-140") : undefined),
    });

    const payment = book.createPayment({
      id: "PAY-140",
      mode: "receive",
      party: "Customer A",
      amount: idr(500_000),
      allocations: [{ invoiceId: "INV-140", amount: idr(500_000) }],
    });
    book.postPayment(payment.id, "2026-02-13");

    reconciliation.addTransaction({
      id: "BNK-7",
      date: "2026-02-14",
      description: "Kredit transaksi",
      amount: idr(500_000),
      currency: "IDR",
    });

    const match = reconciliation.match("BNK-7", "PAY-140", "2026-02-15");
    assert.equal(match.bankTransactionId, "BNK-7");
    assert.equal(reconciliation.report().unmatched.length, 0);
  });

  it("menolak satu pembayaran atau mutasi dicocokkan dua kali", () => {    const { invoices, book } = setupBook();
    addInvoice(invoices, { id: "INV-130", kind: "sales", party: "Customer A", total: idr(500_000) });

    const payment = book.createPayment({
      id: "PAY-130",
      mode: "receive",
      party: "Customer A",
      amount: idr(500_000),
      allocations: [{ invoiceId: "INV-130", amount: idr(500_000) }],
    });
    book.postPayment(payment.id, "2026-02-10");

    const reconciliation = new BankReconciliation({ currency: "IDR", payments: book.allPayments() });
    for (const id of ["BNK-5", "BNK-6"]) {
      reconciliation.addTransaction({
        id,
        date: "2026-02-11",
        description: "Kredit transaksi",
        amount: idr(500_000),
        currency: "IDR",
      });
    }

    reconciliation.match("BNK-5", "PAY-130", "2026-02-12");

    assert.throws(
      () => reconciliation.match("BNK-6", "PAY-130", "2026-02-12"),
      (error: unknown) => error instanceof DomainError && error.code === "payment_already_matched",
    );
    assert.throws(
      () => reconciliation.match("BNK-5", "PAY-130", "2026-02-12"),
      (error: unknown) => error instanceof DomainError && error.code === "transaction_already_matched",
    );
  });
});
