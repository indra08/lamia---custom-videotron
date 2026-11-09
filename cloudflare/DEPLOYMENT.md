# Status deployment Cloudflare

Dicatat 9 November 2026.

- URL utama: **https://lamia-id.pages.dev**
- Pages project: `lamia-id`, production branch `main`
- Pages deployment: `b6a3e941-ad44-488e-9919-05aabefe8ecc`
- Worker: `lamia-cloudflare-free`
- Versi Worker terverifikasi: `a14bdaad-bbef-4113-85d1-7a6cb28bd289`
- D1: `lamia-cloudflare-free` (`d41ab3f6-a81b-41b6-b3b6-ff524f61c8a5`)
- KV: `lamia-cloudflare-free-media` (`edffe331ce524c348967d3f8cdebaa67`)
- Cron: `* * * * *` (setiap menit)
- Paket Workers Free dikonfirmasi pemilik akun. R2 tidak diaktifkan/dibuat oleh deployment ini.

Pages melayani aset statis dan meneruskan route API/halaman privat ke Worker melalui service binding `APP`. D1, KV, secrets, dan Cron tetap berada pada Worker yang sama. URL browser lama di `workers.dev` mengarah ke domain Pages; API perangkat pada endpoint Worker tetap tersedia.

## Validasi

| Pemeriksaan | Hasil |
| --- | --- |
| `cd cloudflare && npm test` | 17 tes lulus, termasuk routing Pages, redirect domain lama, dan password admin hasil import `.env` |
| Wrangler dry-run | Lulus; bundle sekitar 1,1 MiB, gzip 375 KiB |
| `.venv/bin/python -m pytest tests/ -q` | 43 tes lulus; satu peringatan deprecation TestClient |
| `node --test tests/test_form_ui.cjs` | 7 tes lulus |
| `cd cloudflare && npm run smoke` | HTTPS, aset, health, katalog, quote, akses privat, login, jadwal admin, dan logout lulus di `lamia-id.pages.dev` |
| `cd cloudflare && npm run smoke:env` | Login/logout live lulus dengan username/password yang dibaca langsung dari `.env` utama |
| Tampilan beranda di Chrome headless | Diperiksa; [screenshot Pages lokal](.generated/lamia-id-pages-home.png) |

Tes checkout bersamaan, hold kedaluwarsa, konflik blackout, OTP/login rate limit, pembaruan versi materi, token status khusus baca, KV privat/range/quota, dan outbox dijalankan di emulator. Pengiriman email/ponsel nyata serta kampanye ke perangkat fisik belum diverifikasi. SMTP sudah dikonfigurasi dari `.env`; adapter ponsel dan perangkat fisik belum dikonfigurasi.

## Akses dan konfigurasi berikutnya

Buka `/login` dengan `ADMIN_USERNAME` dan `ADMIN_PASSWORD` dari `.env` utama. Nilainya diterapkan sebagai konfigurasi/secrets Cloudflare melalui `npm run import:env`. Salinan password tersimpan lokal pada `.secrets.json`; file ini tidak masuk Git dan nilainya tidak dicetak dalam dokumentasi/log deployment. `config.local.json`, `.secrets.json`, dan `.dev.vars` berada di folder `cloudflare/` serta terpisah dari `.env` utama. File sumber `.env` tidak diubah.

**Belum siap menerima pesanan sungguhan** sampai konfigurasi berikut dilengkapi:

1. Verifikasi pengiriman SMTP. Host, port, pengirim, serta username/password sudah diterapkan dari `.env`; tidak ada email percobaan yang dikirim oleh proses deployment.
2. Isi URL dan token adapter OTP ponsel HTTPS.
3. Isi rekening pembayaran sungguhan. Nomor rekening contoh development tidak dipublikasikan pada konfigurasi Cloudflare.

`npm run import:env` menyalin pengaturan relevan dari `.env` utama ke vars/secrets Cloudflare, tanpa mengubah file sumber. `PUBLIC_BASE_URL` tetap `https://lamia-id.pages.dev`; mode development, path SQLite, port lokal, dan switch demo tidak disalin. `APP_SECRET` sumber berukuran 28 karakter, di bawah minimum 32 karakter, sehingga tetap memakai secret Cloudflare sebelumnya. Password admin sumber 10 karakter diterapkan dengan `ADMIN_PASSWORD_MIN_LENGTH=10` khusus Cloudflare. Batas default tetap 12 bila pengaturan tersebut tidak dipilih; setup Python tidak berubah.

Untuk memeriksa login menggunakan kredensial yang dibaca langsung dari `.env`, jalankan `npm run smoke:env`. Perintah ini tidak mencetak nilai kredensial.

Draft dapat dibuat, tetapi OTP mengembalikan `503` bila provider belum diisi; checkout mengembalikan `503` bila rekening belum diisi. Tidak ada bypass OTP atau simulasi pembayaran pada Worker.

Lihat [panduan Cloudflare](README.md) untuk format konfigurasi, batas Free, konsistensi KV, backup, dan redeploy. Setup FastAPI development/production tidak diubah oleh implementasi Cloudflare ini.
