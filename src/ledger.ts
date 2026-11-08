import { DomainError } from "./errors.ts";
import type { Money } from "./money.ts";

export type AccountType = "asset" | "liability" | "equity" | "income" | "expense";

/**
 * Akun dalam buku besar. `subtype` membedakan peran operasional yang
 * dibutuhkan modul pembayaran: kas, bank, piutang, utang, dan uang muka.
 */
export interface Account {
  readonly id: string;
  readonly name: string;
  readonly type: AccountType;
  readonly subtype?: "cash" | "bank" | "receivable" | "payable" | "advance";
  readonly companyId: string;
}

export interface JournalLine {
  readonly accountId: string;
  readonly debit: Money;
  readonly credit: Money;
  readonly party?: string;
  readonly reference?: string;
}

export interface JournalEntry {
  readonly id: string;
  readonly date: string;
  readonly memo: string;
  readonly lines: readonly JournalLine[];
}

export interface AccountBalance {
  readonly debit: Money;
  readonly credit: Money;
  readonly net: Money;
}

/**
 * Buku besar in-memory: menyimpan akun dan jurnal yang sudah posting, lalu
 * menyediakan saldo per akun. Posting dijaga seimbang agar tidak ada jurnal
 * gantung yang nanti merusak laporan.
 */
export class Ledger {
  private readonly accounts = new Map<string, Account>();
  private readonly entries = new Map<string, JournalEntry>();

  addAccount(account: Account): void {
    if (this.accounts.has(account.id)) {
      throw new DomainError("duplicate_id", `Akun sudah ada: ${account.id}`);
    }
    this.accounts.set(account.id, account);
  }

  account(id: string): Account {
    const found = this.accounts.get(id);
    if (found === undefined) {
      throw new DomainError("invalid_journal_line", `Akun tidak ditemukan: ${id}`);
    }
    return found;
  }

  accountsOfSubtype(subtype: NonNullable<Account["subtype"]>): Account[] {
    return [...this.accounts.values()].filter((item) => item.subtype === subtype);
  }

  entry(id: string): JournalEntry {
    const found = this.entries.get(id);
    if (found === undefined) {
      throw new DomainError("invalid_journal_line", `Jurnal tidak ditemukan: ${id}`);
    }
    return found;
  }

  allEntries(): JournalEntry[] {
    return [...this.entries.values()];
  }

  post(entry: JournalEntry): JournalEntry {
    if (this.entries.has(entry.id)) {
      throw new DomainError("duplicate_id", `Jurnal sudah ada: ${entry.id}`);
    }
    if (entry.lines.length < 2) {
      throw new DomainError("invalid_journal_line", "Jurnal minimal punya dua baris");
    }
    let currencyCode: string | undefined;
    let totalDebit: Money | undefined;
    let totalCredit: Money | undefined;
    for (const line of entry.lines) {
      if (line.debit.currency.code !== line.credit.currency.code) {
        throw new DomainError("currency_mismatch", "Debit dan kredit dalam satu baris beda mata uang");
      }
      if (line.debit.minor < 0 || line.credit.minor < 0) {
        throw new DomainError("invalid_journal_line", "Nilai jurnal harus tidak negatif");
      }
      if (line.debit.isPositive() && line.credit.isPositive()) {
        throw new DomainError("invalid_journal_line", "Satu baris tidak boleh debit dan kredit sekaligus");
      }
      if (!line.debit.isZero() && !line.credit.isZero()) {
        throw new DomainError("invalid_journal_line", "Satu baris harus nol di debit atau di kredit");
      }
      this.account(line.accountId);
      currencyCode ??= line.debit.currency.code;
      if (currencyCode !== line.debit.currency.code) {
        throw new DomainError("currency_mismatch", "Satu jurnal hanya boleh satu mata uang");
      }
      totalDebit = totalDebit === undefined ? line.debit : totalDebit.add(line.debit);
      totalCredit = totalCredit === undefined ? line.credit : totalCredit.add(line.credit);
    }
    if (totalDebit === undefined || totalCredit === undefined || !totalDebit.equals(totalCredit)) {
      throw new DomainError("unbalanced_journal", "Jurnal tidak seimbang");
    }
    this.entries.set(entry.id, entry);
    return entry;
  }

  /** Saldo akun: total debit, total kredit, dan selisihnya (debit - kredit). */
  balance(accountId: string): AccountBalance {
    this.account(accountId);
    let debit: Money | undefined;
    let credit: Money | undefined;
    for (const entry of this.entries.values()) {
      for (const line of entry.lines) {
        if (line.accountId !== accountId) continue;
        if (!line.debit.isZero()) debit = debit === undefined ? line.debit : debit.add(line.debit);
        if (!line.credit.isZero()) credit = credit === undefined ? line.credit : credit.add(line.credit);
      }
    }
    if (debit === undefined && credit === undefined) {
      throw new DomainError("invalid_journal_line", `Akun ${accountId} belum punya jurnal`);
    }
    const anchor = debit ?? credit!;
    const zero = anchor.subtract(anchor);
    const d = debit ?? zero;
    const c = credit ?? zero;
    return { debit: d, credit: c, net: d.subtract(c) };
  }
}
