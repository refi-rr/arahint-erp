# arahint-erp
Erp

## Modul pembayaran dan rekonsiliasi

Implementasi domain (TypeScript, tanpa dependensi runtime) untuk payment entry
dan rekonsiliasi bank:

- `src/money.ts` — nilai uang dalam minor unit sebagai integer, per mata uang.
- `src/ledger.ts` — akun dan jurnal yang harus seimbang saat posting.
- `src/invoice.ts` — invoice penjualan/pembelian, sisa piutang/utang, dan status.
- `src/payment.ts` — payment entry: alokasi ke satu atau beberapa invoice, jurnal kas/bank, kelebihan bayar.
- `src/reconciliation.ts` — baris mutasi bank, pencocokan ke payment entry, dan selisih yang belum cocok.

Perintah pemeriksaan:

```
npm test        # node --test test/*.test.ts
npm run typecheck
```
