# Merilis arahint-erp single-tenant lebih dulu, multi-tenant ditunda

Versi pertama arahint-erp dirilis self-hosted, satu instance per perusahaan pelanggan; arsitektur SaaS multi-tenant ditunda.

## Considered Options

- SaaS multi-tenant sejak awal: satu instance melayani banyak perusahaan.
- Single-tenant self-hosted lebih dulu, dengan isolasi data per pelanggan yang paling sederhana.

## Consequences

- Setiap pelanggan butuh instalasi dan jalur upgrade sendiri, jadi paket rilis dan migrasi harus rapi sejak awal.
- Menambahkan multi-tenant di kemudian hari berarti mengubah lapisan data dan otorisasi secara menyeluruh, bukan tambalan.
