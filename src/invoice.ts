import { DomainError } from "./errors.ts";
import type { Money } from "./money.ts";

export type InvoiceKind = "sales" | "purchase";

export type InvoiceStatus = "unpaid" | "partially_paid" | "paid";

/**
 * Invoice penjualan atau pembelian dalam bentuk paling yang dibutuhkan
 * modul pembayaran: total, jumlah yang sudah dialokasikan ke pembayaran, dan
 * sisa yang masih menjadi piutang atau utang.
 */
export interface Invoice {
  readonly id: string;
  readonly kind: InvoiceKind;
  readonly party: string;
  readonly companyId: string;
  readonly currency: string;
  readonly total: Money;
  /** Jumlah yang sudah dialokasikan ke payment entry yang sudah posting. */
  readonly paid: Money;
  readonly status: InvoiceStatus;
}

export function createInvoice(input: {
  id: string;
  kind: InvoiceKind;
  party: string;
  companyId: string;
  total: Money;
}): Invoice {
  if (!input.total.isPositive()) {
    throw new DomainError("payment_amount_not_positive", `Total invoice harus positif: ${input.id}`);
  }
  const zero = input.total.subtract(input.total);
  return {
    id: input.id,
    kind: input.kind,
    party: input.party,
    companyId: input.companyId,
    currency: input.total.currency.code,
    total: input.total,
    paid: zero,
    status: "unpaid",
  };
}

/** Sisa piutang (invoice penjualan) atau utang (invoice pembelian). */
export function outstanding(invoice: Invoice): Money {
  return invoice.total.subtract(invoice.paid);
}

/**
 * Status invoice diturunkan dari total dan jumlah yang dibayar, jadi tidak
 * bisa berbeda dengan sisa tagihannya.
 */
export function statusOf(total: Money, paid: Money): InvoiceStatus {
  const comparison = paid.compare(total);
  if (comparison >= 0) return "paid";
  if (paid.isZero()) return "unpaid";
  return "partially_paid";
}

/**
 * Mencatat pembayaran ke invoice dan mengembalikan invoice yang diperbarui.
 * Pembayaran tidak boleh melebihi total invoice; kelebihan dari pembayaran
 * dicatat sebagai uang muka, bukan sebagai sisa tagihan negatif.
 */
export function applyPayment(invoice: Invoice, amount: Money): Invoice {
  if (invoice.total.currency.code !== amount.currency.code) {
    throw new DomainError(
      "currency_mismatch",
      `Mata uang invoice ${invoice.currency} tidak sama dengan pembayaran ${amount.currency.code}`,
    );
  }
  if (!amount.isPositive()) {
    throw new DomainError("allocation_amount_not_positive", "Nominal alokasi harus positif");
  }
  const paid = invoice.paid.add(amount);
  if (paid.minor > invoice.total.minor) {
    throw new DomainError(
      "allocation_exceeds_invoice_outstanding",
      `Pembayaran ${amount} melebihi sisa tagihan invoice ${invoice.id}`,
    );
  }
  return {
    ...invoice,
    paid,
    status: statusOf(invoice.total, paid),
  };
}
