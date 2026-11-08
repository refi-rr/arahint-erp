import { DomainError } from "./errors.ts";

/**
 * Definisi mata uang. `exponent` adalah jumlah digit desimal; IDR 0, USD 2.
 */
export interface Currency {
  readonly code: string;
  readonly exponent: number;
}

const CURRENCIES: ReadonlyMap<string, Currency> = new Map<string, Currency>([
  ["IDR", { code: "IDR", exponent: 0 }],
  ["USD", { code: "USD", exponent: 2 }],
  ["EUR", { code: "EUR", exponent: 2 }],
  ["SGD", { code: "SGD", exponent: 2 }],
  ["MYR", { code: "MYR", exponent: 2 }],
]);

export function currency(code: string): Currency {
  const found = CURRENCIES.get(code.toUpperCase());
  if (found === undefined) {
    throw new DomainError("currency_mismatch", `Mata uang tidak dikenal: ${code}`);
  }
  return found;
}

export function isSameCurrency(a: Currency, b: Currency): boolean {
  return a.code === b.code;
}

/**
 * Nilai uang disimpan dalam satuan terkecil (minor unit) sebagai integer,
 * supaya penjumlahan tidak pernah gagal karena pembulatan floating point.
 */
export class Money {
  readonly minor: number;
  readonly currency: Currency;

  private constructor(minor: number, currency: Currency) {
    this.minor = minor;
    this.currency = currency;
  }

  static fromMinor(minor: number, code: string): Money {
    if (!Number.isInteger(minor)) {
      throw new DomainError("currency_mismatch", `Nilai uang harus bulat dalam minor unit: ${minor}`);
    }
    return new Money(minor, currency(code));
  }

  /** Nilai dalam satuan utama, misalnya 1500.50 untuk USD. */
  static fromMajor(amount: number, code: string): Money {
    const cur = currency(code);
    const factor = 10 ** cur.exponent;
    const scaled = Number(amount.toFixed(cur.exponent)) * factor;
    return new Money(Math.round(scaled), cur);
  }

  major(): number {
    return this.minor / 10 ** this.currency.exponent;
  }

  add(other: Money): Money {
    this.assertSameCurrency(other);
    return new Money(this.minor + other.minor, this.currency);
  }

  subtract(other: Money): Money {
    this.assertSameCurrency(other);
    return new Money(this.minor - other.minor, this.currency);
  }

  negate(): Money {
    return new Money(-this.minor, this.currency);
  }

  abs(): Money {
    return new Money(Math.abs(this.minor), this.currency);
  }

  isZero(): boolean {
    return this.minor === 0;
  }

  isPositive(): boolean {
    return this.minor > 0;
  }

  compare(other: Money): number {
    this.assertSameCurrency(other);
    if (this.minor === other.minor) return 0;
    return this.minor < other.minor ? -1 : 1;
  }

  equals(other: Money): boolean {
    return this.currency.code === other.currency.code && this.minor === other.minor;
  }

  private assertSameCurrency(other: Money): void {
    if (!isSameCurrency(this.currency, other.currency)) {
      throw new DomainError(
        "currency_mismatch",
        `Mata uang tidak sama: ${this.currency.code} vs ${other.currency.code}`,
      );
    }
  }

  toString(): string {
    return `${this.currency.code} ${this.major().toFixed(this.currency.exponent)}`;
  }
}

export function sumMoney(amounts: readonly Money[]): Money {
  if (amounts.length === 0) {
    throw new DomainError("currency_mismatch", "Tidak bisa menjumlahkan daftar kosong");
  }
  const first = amounts[0]!;
  return amounts.slice(1).reduce((acc, item) => acc.add(item), first);
}
