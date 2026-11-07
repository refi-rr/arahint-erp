# Tolong kamu research tentang erpnext [frappe]

| | |
|---|---|
| **Status** | Draft, from Grilling Session 3 |
| **Glossary** | [`GLOSSARY.md`](../../GLOSSARY.md) |

## Destination

Membangun arahint-erp — ERP in-house yang dijual sebagai produk ke perusahaan lain, dengan arahint sebagai pengguna pertama — yang seluruh fiturnya setara secara fungsional dengan ERPNext, termasuk kerangka dasarnya, dengan ERPNext (di atas Frappe) dipakai sebagai acuan dan instance observasi.

## Not yet specified

Bentuk paket instalasi dan jalur upgrade bagi pelanggan single-tenant; serta cara instance observasi dibersihkan dan diisi ulang antar sesi riset — keduanya belum bisa dirumuskan sebelum stack diputuskan lewat tiket keputusan tersendiri.

## Notes

Acuan tunggal adalah ERPNext; tidak ada pembanding eksternal. Riset mencakup seluruh modul bisnis ERPNext v15 tanpa terkecuali, dan kerangka dasar Frappe ikut dibangun karena modul bisnisnya tidak berjalan tanpa itu. Paritas yang dituju adalah paritas fungsional: model data, nama field, dan UI dirancang sendiri, dan tidak ada kode, skema, atau file ERPNext yang disalin — ERPNext hanya dijadikan acuan perilaku lewat instance observasi. Riset per modul berhenti di tingkat inventaris (daftar fitur, entitas inti, alur utama), dengan rincian field per entitas menjadi tiket per modul. Versi pertama dirilis single-tenant per perusahaan, dengan multi-company dan multi-currency masuk sejak awal dan lokalisasi Indonesia (PPN, e-Faktur) menyusul sebagai tiket tersendiri setelah modul inti. arahint-erp dijual sebagai produk proprietary (closed source), dan hanya memakai lisensi pihak ketiga yang permisif. Antarmuka tersedia dalam bahasa Indonesia dan Inggris sejak versi pertama. Pembangunan diurutkan berdasarkan ketergantungan, dengan modul inti (Accounting, Stock, Buying, Selling) lebih dulu, sedangkan Website dan eCommerce dipetakan tetapi berprioritas terendah. Pilihan teknologi dasar dibiarkan terbuka sebagai tiket keputusan sendiri. Hasil riset ditujukan langsung untuk dipakai Agent Floor arahint-erp sebagai batch issue.

## Out of scope

Perbandingan dengan ERP lain (Odoo dan sejenisnya) — Owner memilih ERPNext saja sebagai acuan. Instance observasi ERPNext sebagai bagian dari deployment arahint-erp — ia hanya untuk pengamatan, tidak ikut dirilis. SaaS multi-tenant — ditunda; versi pertama single-tenant per perusahaan. Migrasi data dari sistem yang dipakai arahint sekarang — menjadi tiket tersendiri setelah modul inti berjalan.

## Hasil yang diharapkan

Satu PRD sebagai peta modul, ditambah satu tiket build per modul yang diurutkan berdasarkan ketergantungan — modul inti (Accounting, Stock, Buying, Selling) lebih dulu, modul lain menyusul, Website dan eCommerce paling akhir — tanpa tiket riset terpisah kecuali yang benar-benar membuka keputusan. Tiket-tiket ini siap dijadikan batch issue oleh Agent Floor arahint-erp tanpa tafsir ulang.

## Decisions

Settled in Grilling Session 3, word for word:

1. Tujuan peta ini adalah membangun arahint-erp sebagai ERP in-house dengan seluruh fitur disamakan dengan ERPNext.
2. Riset mencakup seluruh modul fitur ERPNext, bukan sebagian.
3. Riset hanya membahas ERPNext; perbandingan dengan ERP lain seperti Odoo tidak dilakukan.
4. Uji pasang langsung, yaitu instance ERPNext yang benar-benar dijalankan, termasuk dalam peta ini.
5. Hasil riset ditulis untuk dipakai langsung oleh Agent di Floor arahint-erp sebagai batch issue, tanpa tafsir ulang.
6. Paritas arahint-erp terhadap ERPNext adalah paritas fungsional: setiap kapabilitas dan alur kerja ERPNext tersedia, sementara model data, nama field, dan UI dirancang sendiri.
7. Kerangka dasar di bawah modul bisnis (model dokumen, permission, workflow, report, print) ikut dibangun di arahint-erp, bukan hanya modul bisnisnya.
8. Inventaris riset memakai seluruh modul bisnis ERPNext v15 apa adanya sebagai acuan, tanpa terkecuali.
9. ERPNext dipakai sebagai acuan yang diikuti arahint-erp, dengan batas konkret mengenai penyalinan kode ditetapkan lewat pertanyaan lanjutan.
10. arahint-erp dijual sebagai produk ke perusahaan lain, dengan arahint sebagai pengguna pertama.
11. arahint-erp dibangun di repo dan Floor ini sebagai arahint-erp itu sendiri, bukan sebagai produk baru di samping aplikasi yang sudah ada.
12. Pilihan teknologi dasar tidak dikunci sekarang: riset mengumpulkan kriteria dan opsinya, dan pemilihan stack menjadi tiket keputusan tersendiri.
13. Ada satu instance ERPNext v15 (Frappe bench) yang berjalan hanya untuk observasi — inventaris fitur, alur, dan tangkapan layar — dan bukan bagian dari deployment arahint-erp.
14. Riset per modul berhenti di tingkat inventaris: daftar fitur, entitas inti, dan alur utama; rincian field per entitas menjadi tiket per modul.
15. Peta ini menghasilkan satu PRD sebagai peta modul plus satu tiket build per modul yang diurutkan berdasarkan ketergantungan (Accounting, Stock, Buying, Selling lebih dulu), tanpa tiket riset terpisah kecuali yang benar-benar membuka keputusan.
16. arahint-erp dirilis single-tenant per perusahaan (self-hosted) lebih dulu, dan SaaS multi-tenant ditunda serta dicatat sebagai out of scope.
17. Multi-company dan multi-currency masuk cakupan sejak awal, sedangkan lokalisasi Indonesia (PPN dan e-Faktur) menjadi tiket tersendiri setelah modul inti.
18. ERPNext dipakai sebagai acuan perilaku saja: tidak ada kode, skema, atau file ERPNext yang disalin ke arahint-erp, dan ERPNext hanya dijalankan sebagai instance observasi untuk melihat perilakunya.
19. arahint-erp dijual sebagai produk proprietary (closed source), dan lisensi pihak ketiga yang dipakai dicatat serta dibatasi pada yang permisif saja.
20. Modul Website dan eCommerce ikut dipetakan tetapi bertanda prioritas terendah, dan dibangun setelah modul inti berjalan.
21. Migrasi data dari sistem yang dipakai arahint sekarang tidak termasuk peta ini, dan menjadi tiket tersendiri setelah modul inti berjalan.
22. Antarmuka arahint-erp tersedia dalam bahasa Indonesia dan Inggris sejak versi pertama.
