import { DomainError } from "./errors.ts";
import type { Invoice, InvoiceKind } from "./invoice.ts";
import { applyPayment, outstanding } from "./invoice.ts";
import type { Ledger } from "./ledger.ts";
import { Money } from "./money.ts";

export type PaymentMode = "receive" | "pay";

export interface PaymentAllocation {
  readonly invoiceId: string;
  readonly amount: Money;
}

export interface PaymentEntry {
  readonly id: string;
  readonly mode: PaymentMode;
  readonly party: string;
  readonly companyId: string;
  readonly currency: string;
  /** Total uang yang diterima atau dibayarkan, termasuk yang tidak dialokasikan. */
  readonly amount: Money;
  readonly allocations: readonly PaymentAllocation[];
  /** Sisa pembayaran yang tidak dialokasikan ke invoice (kelebihan bayar). */
  readonly unallocated: Money;
  readonly cashAccountId: string;
  readonly journalEntryId?: string;
  readonly postedAt?: string;
}

/**
 * Pemetaan akun per Company. Modul pembayaran butuh akun kas/bank untuk sisi
 * uang, akun piutang/utang untuk sisi invoice, dan akun uang muka untuk
 * kelebihan bayar.
 */
export interface AccountMap {
  cash?: string;
  bank?: string;
  receivable?: string;
  payable?: string;
  advance?: string;
}

export interface PaymentBookOptions {
  companyId: string;
  ledger: Ledger;
  invoices: Map<string, Invoice>;
  accounts: AccountMap;
}

/**
 * Buku pembayaran: menyimpan invoice dan payment entry, serta memposting
 * jurnal kas/bank ketika sebuah pembayaran disubmit.
 */
export class PaymentBook {
  readonly ledger: Ledger;
  readonly companyId: string;
  private readonly invoices: Map<string, Invoice>;
  private readonly accounts: AccountMap;
  private readonly payments = new Map<string, PaymentEntry>();

  constructor(options: PaymentBookOptions) {
    this.ledger = options.ledger;
    this.companyId = options.companyId;
    this.invoices = options.invoices;
    this.accounts = options.accounts;
  }

  invoice(id: string): Invoice {
    const found = this.invoices.get(id);
    if (found === undefined) {
      throw new DomainError("invoice_not_found", `Invoice tidak ditemukan: ${id}`);
    }
    return found;
  }

  payment(id: string): PaymentEntry {
    const found = this.payments.get(id);
    if (found === undefined) {
      throw new DomainError("payment_not_found", `Payment entry tidak ditemukan: ${id}`);
    }
    return found;
  }

  allPayments(): PaymentEntry[] {
    return [...this.payments.values()];
  }

  /**
   * Membuat payment entry dalam keadaan draft dan memvalidasinya: alokasi
   * tidak boleh melebihi nilai pembayaran, tidak boleh melebihi sisa invoice,
   * dan invoice yang dipakai harus cocok party serta jenisnya.
   */
  createPayment(input: {
    id: string;
    mode: PaymentMode;
    party: string;
    amount: Money;
    allocations?: readonly PaymentAllocation[];
    cashAccountId?: string;
  }): PaymentEntry {
    if (this.payments.has(input.id)) {
      throw new DomainError("duplicate_id", `Payment entry sudah ada: ${input.id}`);
    }
    if (!input.amount.isPositive()) {
      throw new DomainError("payment_amount_not_positive", "Nominal pembayaran harus positif");
    }
    const allocations = input.allocations ?? [];
    for (const allocation of allocations) {
      if (!allocation.amount.isPositive()) {
        throw new DomainError(
          "allocation_amount_not_positive",
          `Alokasi ke ${allocation.invoiceId} harus positif`,
        );
      }
      if (allocation.amount.currency.code !== input.amount.currency.code) {
        throw new DomainError(
          "currency_mismatch",
          `Alokasi ke ${allocation.invoiceId} beda mata uang dengan pembayaran`,
        );
      }
    }

    let allocatedTotal = input.amount.subtract(input.amount);
    for (const allocation of allocations) {
      allocatedTotal = allocatedTotal.add(allocation.amount);
    }
    if (allocatedTotal.minor > input.amount.minor) {
      throw new DomainError(
        "allocation_exceeds_payment",
        `Total alokasi (${allocatedTotal}) melebihi nilai pembayaran (${input.amount})`,
      );
    }

    for (const allocation of allocations) {
      const invoice = this.invoice(allocation.invoiceId);
      const expectedKind: InvoiceKind = input.mode === "receive" ? "sales" : "purchase";
      if (invoice.kind !== expectedKind) {
        throw new DomainError(
          "invoice_kind_mismatch",
          `Invoice ${invoice.id} (${invoice.kind}) tidak cocok dengan mode ${input.mode}`,
        );
      }
      if (invoice.party !== input.party) {
        throw new DomainError(
          "invoice_party_mismatch",
          `Invoice ${invoice.id} milik party ${invoice.party}, bukan ${input.party}`,
        );
      }
    }

    const cashAccountId = input.cashAccountId ?? this.defaultCashAccount();
    const unallocated = input.amount.subtract(allocatedTotal);
    const payment: PaymentEntry = {
      id: input.id,
      mode: input.mode,
      party: input.party,
      companyId: this.companyId,
      currency: input.amount.currency.code,
      amount: input.amount,
      allocations,
      unallocated,
      cashAccountId,
    };
    this.payments.set(payment.id, payment);
    return payment;
  }

  /**
   * Memposting pembayaran: memperbarui sisa piutang/utang invoice dan menulis
   * jurnal kas/bank. Kelebihan bayar — baik yang tidak dialokasikan ke invoice
   * maupun yang melebihi sisa tagihan — dicatat di akun uang muka.
   */
  postPayment(id: string, date: string): PaymentEntry {
    const payment = this.payment(id);
    if (payment.postedAt !== undefined) {
      throw new DomainError("payment_already_posted", `Payment entry sudah posting: ${id}`);
    }

    const invoiceAccount = payment.mode === "receive" ? this.accounts.receivable : this.accounts.payable;
    if (invoiceAccount === undefined) {
      throw new DomainError(
        "invalid_journal_line",
        `Akun ${payment.mode === "receive" ? "piutang" : "utang"} belum dipetakan`,
      );
    }
    const advanceAccount = this.accounts.advance;

    const lines: {
      accountId: string;
      debit: Money;
      credit: Money;
      party?: string;
      reference?: string;
    }[] = [];
    const zero = payment.amount.subtract(payment.amount);
    const isReceive = payment.mode === "receive";
    let advanceTotal = payment.unallocated;

    for (const allocation of payment.allocations) {
      const invoice = this.invoice(allocation.invoiceId);
      const left = outstanding(invoice);
      const applied = allocation.amount.minor <= left.minor ? allocation.amount : left;
      const excess = allocation.amount.subtract(applied);
      advanceTotal = advanceTotal.add(excess);
      lines.push({
        accountId: invoiceAccount,
        debit: isReceive ? zero : applied,
        credit: isReceive ? applied : zero,
        party: invoice.party,
        reference: invoice.id,
      });
    }

    if (advanceTotal.isPositive()) {
      if (advanceAccount === undefined) {
        throw new DomainError("invalid_journal_line", "Akun uang muka belum dipetakan");
      }
      lines.push({
        accountId: advanceAccount,
        debit: isReceive ? zero : advanceTotal,
        credit: isReceive ? advanceTotal : zero,
        party: payment.party,
        reference: payment.id,
      });
    }

    lines.push({
      accountId: payment.cashAccountId,
      debit: isReceive ? payment.amount : zero,
      credit: isReceive ? zero : payment.amount,
      party: payment.party,
      reference: payment.id,
    });

    const journalEntryId = `JE-${payment.id}`;
    this.ledger.post({
      id: journalEntryId,
      date,
      memo: `Payment ${payment.id} (${payment.mode})`,
      lines,
    });

    for (const allocation of payment.allocations) {
      const invoice = this.invoice(allocation.invoiceId);
      const left = outstanding(invoice);
      const applied = allocation.amount.minor <= left.minor ? allocation.amount : left;
      this.invoices.set(invoice.id, applyPayment(invoice, applied));
    }

    const posted: PaymentEntry = { ...payment, journalEntryId, postedAt: date };
    this.payments.set(posted.id, posted);
    return posted;
  }

  private defaultCashAccount(): string {
    const bank = this.accounts.bank;
    if (bank !== undefined) return bank;
    const cash = this.accounts.cash;
    if (cash !== undefined) return cash;
    throw new DomainError("invalid_journal_line", "Akun kas/bank belum dipetakan");
  }
}
