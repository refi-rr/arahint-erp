/**
 * Error domain untuk modul pembayaran dan rekonsiliasi.
 *
 * Kode error stabil supaya pemanggil (API, CLI, pengujian) bisa membedakan
 * jenis pelanggaran aturan tanpa mem-parsing pesan.
 */
export type DomainErrorCode =
  | "currency_mismatch"
  | "payment_amount_not_positive"
  | "allocation_amount_not_positive"
  | "allocation_exceeds_payment"
  | "allocation_exceeds_invoice_outstanding"
  | "invoice_not_found"
  | "invoice_kind_mismatch"
  | "invoice_party_mismatch"
  | "invoice_already_settled"
  | "payment_not_found"
  | "payment_already_posted"
  | "unbalanced_journal"
  | "invalid_journal_line"
  | "transaction_not_found"
  | "transaction_already_matched"
  | "payment_already_matched"
  | "match_amount_mismatch"
  | "match_currency_mismatch"
  | "duplicate_id";

export class DomainError extends Error {
  readonly code: DomainErrorCode;

  constructor(code: DomainErrorCode, message: string) {
    super(message);
    this.name = "DomainError";
    this.code = code;
  }
}
