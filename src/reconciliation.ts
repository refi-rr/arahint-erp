import { DomainError } from "./errors.ts";
import { Money } from "./money.ts";
import type { PaymentEntry } from "./payment.ts";

/**
 * Baris mutasi bank yang diimpor dari rekening bank, misalnya hasil
 * impor mutasi rekening. `amount` positif berarti uang masuk ke bank,
 * negatif berarti uang keluar dari bank.
 */
export interface BankTransaction {
  readonly id: string;
  readonly date: string;
  readonly description: string;
  readonly amount: Money;
  readonly currency: string;
  /** Id payment entry yang sudah dicocokkan, bila ada. */
  readonly matchedPaymentId?: string;
}

export interface ReconciliationMatch {
  readonly bankTransactionId: string;
  readonly paymentId: string;
  readonly amount: Money;
  readonly matchedAt: string;
}

/**
 * Hasil rekonsiliasi: baris yang sudah cocok, baris yang belum cocok, dan
 * selisihnya. Baris yang belum cocok tetap terlihat sebagai selisih supaya
 * bisa ditindaklanjuti.
 */
export interface ReconciliationReport {
  readonly matches: readonly ReconciliationMatch[];
  readonly unmatched: readonly BankTransaction[];
  readonly difference: Money;
}

export interface ReconciliationOptions {
  currency: string;
  /** Sumber payment entry, dipakai saat pencocokan. */
  payments?: readonly PaymentEntry[];
  paymentLookup?: (id: string) => PaymentEntry | undefined;
}

/**
 * Rekonsiliasi bank: mencocokkan baris mutasi bank dengan payment entry.
 */
export class BankReconciliation {
  readonly currency: string;
  private readonly transactions = new Map<string, BankTransaction>();
  private readonly payments: Map<string, PaymentEntry>;
  private readonly lookup: (id: string) => PaymentEntry | undefined;
  private readonly matches: ReconciliationMatch[] = [];

  constructor(options: ReconciliationOptions) {
    this.currency = options.currency;
    this.payments = new Map((options.payments ?? []).map((payment) => [payment.id, payment]));
    this.lookup = options.paymentLookup ?? ((id) => this.payments.get(id));
  }

  addTransaction(transaction: BankTransaction): void {
    if (this.transactions.has(transaction.id)) {
      throw new DomainError("duplicate_id", `Mutasi bank sudah ada: ${transaction.id}`);
    }
    if (transaction.amount.currency.code !== this.currency) {
      throw new DomainError(
        "currency_mismatch",
        `Mutasi bank ${transaction.id} beda mata uang dengan rekening ${this.currency}`,
      );
    }
    this.transactions.set(transaction.id, transaction);
  }

  transaction(id: string): BankTransaction {
    const found = this.transactions.get(id);
    if (found === undefined) {
      throw new DomainError("transaction_not_found", `Mutasi bank tidak ditemukan: ${id}`);
    }
    return found;
  }

  /**
   * Mencocokkan sebuah payment entry ke baris mutasi bank. Nominal dan mata
   * uang harus sama, dan tidak ada yang boleh dicocokkan dua kali.
   */
  match(bankTransactionId: string, paymentId: string, matchedAt: string): ReconciliationMatch {
    const transaction = this.transaction(bankTransactionId);
    const payment = this.lookup(paymentId);
    if (payment === undefined) {
      throw new DomainError("payment_not_found", `Payment entry tidak ditemukan: ${paymentId}`);
    }
    if (transaction.matchedPaymentId !== undefined) {
      throw new DomainError(
        "transaction_already_matched",
        `Mutasi bank ${bankTransactionId} sudah dicocokkan dengan ${transaction.matchedPaymentId}`,
      );
    }
    if (this.matches.some((match) => match.paymentId === paymentId)) {
      throw new DomainError(
        "payment_already_matched",
        `Payment entry ${paymentId} sudah dicocokkan dengan mutasi bank lain`,
      );
    }
    if (payment.currency !== transaction.currency) {
      throw new DomainError(
        "match_currency_mismatch",
        `Mata uang payment ${payment.currency} tidak sama dengan mutasi bank ${transaction.currency}`,
      );
    }
    if (!payment.amount.equals(transaction.amount.abs())) {
      throw new DomainError(
        "match_amount_mismatch",
        `Nominal payment ${payment.amount} tidak sama dengan mutasi bank ${transaction.amount.abs()}`,
      );
    }
    const match: ReconciliationMatch = {
      bankTransactionId,
      paymentId,
      amount: transaction.amount.abs(),
      matchedAt,
    };
    this.matches.push(match);
    this.transactions.set(bankTransactionId, { ...transaction, matchedPaymentId: paymentId });
    return match;
  }

  /** Baris mutasi bank yang belum punya payment entry pencocok. */
  unmatchedTransactions(): BankTransaction[] {
    return [...this.transactions.values()].filter((item) => item.matchedPaymentId === undefined);
  }

  /**
   * Laporan rekonsiliasi. `difference` adalah total mutasi bank yang belum
   * cocok, tetap terlihat supaya selisih bisa ditindaklanjuti.
   */
  report(): ReconciliationReport {
    const unmatched = this.unmatchedTransactions();
    let difference = this.zero();
    for (const transaction of unmatched) {
      difference = difference.add(transaction.amount.abs());
    }
    return { matches: [...this.matches], unmatched, difference };
  }

  private zero(): Money {
    return Money.fromMinor(0, this.currency);
  }
}
