import { Ledger } from "../src/ledger.ts";
import type { Invoice } from "../src/invoice.ts";
import { createInvoice } from "../src/invoice.ts";
import { Money } from "../src/money.ts";
import { PaymentBook } from "../src/payment.ts";

/**
 * Chart of accounts minimal untuk pengujian dan contoh: kas, bank, piutang,
 * utang, dan uang muka.
 */
export function setupLedger(): Ledger {
  const ledger = new Ledger();
  ledger.addAccount({ id: "Cash", name: "Kas", type: "asset", subtype: "cash", companyId: "PT A" });
  ledger.addAccount({ id: "Bank", name: "Bank", type: "asset", subtype: "bank", companyId: "PT A" });
  ledger.addAccount({ id: "AR", name: "Piutang Usaha", type: "asset", subtype: "receivable", companyId: "PT A" });
  ledger.addAccount({ id: "AP", name: "Utang Usaha", type: "liability", subtype: "payable", companyId: "PT A" });
  ledger.addAccount({ id: "Advance", name: "Uang Muka", type: "liability", subtype: "advance", companyId: "PT A" });
  return ledger;
}

export function setupBook(): { ledger: Ledger; invoices: Map<string, Invoice>; book: PaymentBook } {
  const ledger = setupLedger();
  const invoices = new Map<string, Invoice>();
  const book = new PaymentBook({
    companyId: "PT A",
    ledger,
    invoices,
    accounts: {
      cash: "Cash",
      bank: "Bank",
      receivable: "AR",
      payable: "AP",
      advance: "Advance",
    },
  });
  return { ledger, invoices, book };
}

export function addInvoice(
  invoices: Map<string, Invoice>,
  input: { id: string; kind: "sales" | "purchase"; party: string; total: Money },
): Invoice {
  const invoice = createInvoice({
    id: input.id,
    kind: input.kind,
    party: input.party,
    companyId: "PT A",
    total: input.total,
  });
  invoices.set(invoice.id, invoice);
  return invoice;
}

export function idr(amount: number): Money {
  return Money.fromMajor(amount, "IDR");
}
