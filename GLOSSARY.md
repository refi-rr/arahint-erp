# Glossary

## Tolong kamu research tentang erpnext [frappe]

**arahint-erp**:
ERP in-house yang dibangun di Floor ini, dijual sebagai produk ke perusahaan lain dengan arahint sebagai pengguna pertama, dan seluruh fiturnya setara secara fungsional dengan ERPNext.
_Avoid_: ERPNext, sistem lama

**Paritas fungsional**:
Keadaan ketika setiap kapabilitas dan alur kerja ERPNext tersedia di arahint-erp, sementara model data, nama field, dan UI dirancang sendiri.
_Avoid_: cloning, paritas struktural, sama persis

**Instance observasi**:
Satu instance ERPNext v15 yang dijalankan hanya untuk mengamati fitur, alur, dan tangkapan layar, dan bukan bagian dari deployment arahint-erp.
_Avoid_: staging, server produksi, lingkungan uji

**Single-tenant**:
Model rilis arahint-erp di mana setiap perusahaan pelanggan menjalankan instance-nya sendiri (self-hosted) untuk versi pertama. Avoid: multi-tenant, SaaS.

**Lokalisasi Indonesia**:
Lapisan aturan pajak dan dokumen resmi Indonesia (PPN, e-Faktur) yang dibangun sebagai tiket tersendiri setelah modul inti. Avoid: l10n, localisation.
