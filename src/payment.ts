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
 * Menggabungkan alokasi yang menunjuk invoice yang sama menjadi satu
 * alokasi. Tanpa penggabungan, satu invoice bisa muncul dua kali dalam satu
 * pembayaran: jurnal akan mem-post piutang dua kali, padahal hanya satu
 * yang bisa terpakai karena sisa tagihan sudah habis.
 */
function aggregateAllocations(allocations: readonly PaymentAllocation[]): PaymentAllocation[] {
  const merged = new Map<string, PaymentAllocation>();
  for (const allocation of allocations) {
    const existing = merged.get(allocation.invoiceId);
    if (existing === undefined) {
      merged.set(allocation.invoiceId, allocation);
      continue;
    }
    merged.set(allocation.invoiceId, {
      invoiceId: allocation.invoiceId,
      amount: existing.amount.add(allocation.amount),
    });
  }
  return [...merged.values()];
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
   *
   * Alokasi ke invoice yang sama digabung menjadi satu alokasi. Tanpa itu,
   * satu invoice bisa terisi dua kali dalam satu pembayaran sehingga jurnal
   * mem-post piutang dua kali sementara hanya satu yang terpakai.
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
    const rawAllocations = input.allocations ?? [];
    for (const allocation of rawAllocations) {
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
    const allocations = aggregateAllocations(rawAllocations);

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

    // Rencana posting dihitung lebih dulu untuk semua invoice, termasuk
    // invoice yang sudah diperbarui, supaya jurnal tidak pernah tersimpan
    // kalau ada alokasi yang tidak bisa diterapkan.
    const plan: { invoiceId: string; updated: Invoice }[] = [];
    const working = new Map<string, Invoice>();
    for (const allocation of payment.allocations) {
      const original = this.invoice(allocation.invoiceId);
      const invoice = working.get(original.id) ?? original;
      const left = outstanding(invoice);
      const applied = allocation.amount.minor <= left.minor ? allocation.amount : left;
      const excess = allocation.amount.subtract(applied);
      advanceTotal = advanceTotal.add(excess);
      if (applied.isPositive()) {
        const updated = applyPayment(invoice, applied);
        working.set(updated.id, updated);
        plan.push({ invoiceId: updated.id, updated });
        lines.push({
          accountId: invoiceAccount,
          debit: isReceive ? zero : applied,
          credit: isReceive ? applied : zero,
          party: invoice.party,
          reference: invoice.id,
        });
      }
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

    for (const item of plan) {
      this.invoices.set(item.invoiceId, item.updated);
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
