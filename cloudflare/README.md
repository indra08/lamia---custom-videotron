# LAMIA — Cloudflare Free

Deployment ini berdiri sendiri: **Pages + Workers + D1 + Workers KV**, tanpa VPS, Docker, Tunnel, R2, atau subscription baru. Akun harus tetap menggunakan **Workers Free**. Beralih ke Workers Paid mengubah perilaku billing D1/KV; kode aplikasi bukan pembatas tagihan akun.

Lihat [status deployment dan validasi](DEPLOYMENT.md) untuk alamat live, resource yang sudah dibuat, kredensial lokal, dan konfigurasi pengirim yang masih perlu diisi.

`app.py`, `.env`, `run.sh`, `requirements.txt`, Docker Compose, SQLite, dan `uploads/` pada repository utama tetap digunakan oleh development/production yang sudah ada. Semua perintah berikut dijalankan dari **folder `cloudflare/`**. Jangan menjalankan migrasi Cloudflare terhadap SQLite utama.

## Resource terpisah

| Komponen | Resource |
| --- | --- |
| Backend dan aset | Worker `lamia-cloudflare-free` |
| Domain publik dan aset statis | Pages project `lamia-id` |
| SQL dan transaksi booking | D1 `lamia-cloudflare-free` |
| Gambar, video, invoice | KV `lamia-cloudflare-free-media` |
| Rekonsiliasi dan retry email | Satu Cron Trigger setiap menit |
| Alamat aplikasi | `https://lamia-id.pages.dev` |

Pages meneruskan API dan halaman privat ke Worker melalui service binding `APP`. Secrets, sesi, SQL, KV, dan Cron tetap ditangani Worker; Pages tidak memerlukan salinan secrets. URL browser Worker lama diarahkan ke URL publik pada `PUBLIC_BASE_URL` saat `CANONICAL_REDIRECT=true`. API pada Worker tetap tersedia bagi perangkat yang sudah menggunakannya.

Database baru berisi tiga layar contoh, tanpa menyalin pesanan atau unggahan lokal. Migrasi data lama memerlukan proses terpisah. Jangan mengganti `APP_SECRET` saat redeploy biasa karena token pelanggan, OTP, hash identitas, dan token perangkat bergantung padanya.

## Instalasi dan konfigurasi

Gunakan Node.js 22 atau lebih baru:

```sh
cd cloudflare
npm ci
cp config.example.json config.local.json
wrangler login
wrangler whoami
```

Buat resource hanya sekali. Untuk checkout yang sudah mempunyai `config.local.json`, gunakan resource yang tercatat di situ; jangan membuat duplikat setiap deploy:

```sh
wrangler d1 create lamia-cloudflare-free --location apac --update-config=false
wrangler kv namespace create lamia-cloudflare-free-media --update-config=false
```

Isi `account_id`, `database_id`, dan `media_namespace_id` hasil perintah pada `config.local.json`. Isi `vars.PUBLIC_BASE_URL` dengan URL HTTPS Worker yang benar. Lengkapi identitas operator dan rekening melalui `vars`. Konfigurasi lokal ini diabaikan Git.

Simpan rahasia khusus Cloudflare di `.secrets.json`, dengan struktur berikut. Ganti seluruh placeholder; jangan menyalin secret development:

```json
{
  "APP_SECRET": "replace-with-a-unique-random-secret-of-at-least-32-characters",
  "ADMIN_PASSWORD": "replace-with-a-unique-password-of-at-least-12-characters",
  "SMTP_USERNAME": "replace-with-your-smtp-username",
  "SMTP_PASSWORD": "replace-with-your-smtp-password",
  "PHONE_OTP_WEBHOOK_TOKEN": "replace-with-your-phone-adapter-token"
}
```

```sh
chmod 600 .secrets.json config.local.json
```

File `.secrets.json` tidak masuk Git dan dikirim sebagai encrypted Worker secrets saat deploy. `APP_SECRET` dibuat khusus Cloudflare; username/password operasional pada deployment sekarang mengikuti `.env` utama setelah import. Username juga berada di `config.local.json` (`admin` secara default). Jangan membagikan file rahasianya.

Untuk emulator saja, buat `.dev.vars` berisi secrets Cloudflare dengan format dotenv. `prepare:assets` menyalinnya ke `.generated/.dev.vars`; file `.env` utama tidak dimuat oleh kode Cloudflare. Jangan menaruh secrets pada `vars` konfigurasi Wrangler.

## Email, OTP ponsel, dan pembayaran

Sebelum menerima pesanan sungguhan, lengkapi:

| Lokasi | Pengaturan |
| --- | --- |
| `config.local.json → vars` | `SMTP_HOST`, `SMTP_PORT`, `SMTP_ENCRYPTION`, `SMTP_FROM` |
| `.secrets.json` | `SMTP_USERNAME`, `SMTP_PASSWORD` |
| `config.local.json → vars` | `PHONE_OTP_WEBHOOK_URL` berupa HTTPS |
| `.secrets.json` | `PHONE_OTP_WEBHOOK_TOKEN` |
| `config.local.json → vars` | `BANK_NAME`, `BANK_ACCOUNT`, `BANK_HOLDER` |

SMTP memakai TLS 465 atau STARTTLS 587, tidak memakai port 25. Adapter ponsel menerima `POST {"to":"+62…","code":"123456","expires_in":300}` dengan header Bearer token. Email/OTP tidak memakai kode dummy pada versi Cloudflare. Layanan pengirim tersebut memiliki biaya dan kuota sendiri; Workers Free tidak mencakup biaya penyedia SMS/WhatsApp/SMTP eksternal.

Jika SMTP/adapter belum diisi, pengiriman OTP mengembalikan `503`; verifikasi tidak dapat dilanjutkan. Draft masih bisa dibuat. Operator harus melengkapi pengiriman sebelum menerima transaksi. Tagihan menggunakan transfer bank dengan konfirmasi dana manual, tanpa simulasi pembayaran.

## Pengujian, migrasi, dan deploy

Untuk menerapkan `.env` utama pada deployment ini:

```sh
npm run import:env
```

Perintah tersebut menyalin identitas usaha, kredensial operasional, SMTP, rekening yang valid, dan adapter OTP ke `config.local.json`/`.secrets.json` Cloudflare. File `.env` sumber tidak diubah. Import menerima password admin minimal 10 karakter; untuk panjang 10–11, `ADMIN_PASSWORD_MIN_LENGTH=10` dipilih secara eksplisit pada konfigurasi Cloudflare. Batas default tetap 12. `APP_SECRET` tetap membutuhkan 32 karakter; source yang lebih pendek tidak mengganti secret Cloudflare. Nomor rekening contoh tidak diterapkan. URL publik, `APP_ENV`, `DB_PATH`, bind/port lokal, dan switch demo tetap mengikuti konfigurasi Cloudflare. Periksa daftar nama key yang diimpor/dilewati pada output; nilai secrets tidak dicetak.

```sh
npm test
npm run build
npm run migrate:remote
npm run deploy
npm run deploy:pages
npm run smoke
```

`npm run build` adalah **dry-run**, belum memublikasikan aplikasi. `npm run deploy` menjalankan tes, dry-run, pemeriksaan konfigurasi, lalu memublikasikan Worker bersama secrets dari `.secrets.json`. Aset disalin dari `../static` dan `../icon` ke `.generated/public`; tidak ada perubahan pada aset asli. Salinan Cloudflare menyesuaikan teks frekuensi scheduler dan membatasi kiriman laporan player menjadi 20 entri agar sesuai batas query D1 Free.

`npm run deploy:pages` mempersiapkan aset Pages dan `_worker.js` penghubung ke Worker, lalu mengunggah ke branch production `main` dari project pada `pages_project` di `config.local.json` (default `lamia-id`). Jalankan deploy Worker terlebih dahulu jika vars/secrets/API berubah. `npm run smoke` memeriksa URL pada `PUBLIC_BASE_URL`, termasuk login/logout, tanpa mencetak kredensial.

Project `lamia-id` sudah dibuat. Pada akun baru, buat project satu kali dengan `wrangler pages project create lamia-id --production-branch main`. Jika CLI mencoba mengalihkan pembuatan ke Workers dan Anda membutuhkan domain `.pages.dev`, opsi `--force` dapat dipakai pada pembuatan awal sesuai instruksi CLI; tidak diperlukan untuk redeploy project Pages yang sudah ada. [Service bindings Pages](https://developers.cloudflare.com/pages/functions/bindings/#service-bindings).

Untuk emulator dengan data khusus Cloudflare:

```sh
npm run prepare:assets
npm run migrate:local
npm run dev
```

Emulator menyimpan datanya di `.wrangler/` dalam folder ini. Tes otomatis memakai D1/KV sementara, tidak mengakses database utama atau mengirim email sungguhan.

## Verifikasi sesudah deploy

```sh
curl -fsS https://ALAMAT-WORKER/api/v1/health
curl -fsS https://ALAMAT-WORKER/api/v1/screens
curl -sS -o /dev/null -w '%{http_code}\n' https://ALAMAT-WORKER/api/v1/admin/orders
```

Harapkan `ok: true`, tiga layar pada database baru, dan `401` pada API admin tanpa login. Buka `/login` dengan kredensial Cloudflare. `/admin`, `/schedule`, `/player`, dan `/static/player.html` meminta sesi admin. API player tetap memakai token perangkat tersendiri.

Verifikasi berikutnya setelah integrasi pengirim diisi: buat draft, terima kedua OTP, ajukan materi, review melalui admin, checkout, konfirmasi dana, unduh invoice, daftarkan perangkat, jalankan player, lalu uji takedown/revocation. Manifest dan aset selalu memeriksa izin dari D1; KV tidak dipakai untuk keputusan otorisasi.

## Batas free tier dan perbedaan implementasi

Angka berikut dicek terhadap dokumentasi Cloudflare pada 9 November 2026; kuota berlaku bersama resource lain dalam akun.

| Layanan | Kuota Free yang relevan |
| --- | --- |
| Workers | 100.000 request/hari; CPU 10 ms/request; 5 Cron Trigger/akun |
| D1 | 5 GB total; 5 juta baris dibaca/hari; 100.000 baris ditulis/hari |
| KV | 1 GB; 100.000 baca/hari; 1.000 tulis, hapus, dan list per hari masing-masing; 25 MiB/value |

Pada Workers Free, operasi KV yang melewati kuota gagal, bukan otomatis beralih ke tarif Paid. Pastikan paket akun tidak di-upgrade jika tujuan Anda tanpa tagihan. [Workers limits](https://developers.cloudflare.com/workers/platform/limits/), [D1 pricing](https://developers.cloudflare.com/d1/platform/pricing/), [KV pricing](https://developers.cloudflare.com/kv/platform/pricing/), [KV limits](https://developers.cloudflare.com/kv/platform/limits/).

- Aplikasi membatasi **20 MiB/file** dan **800 MiB total media/invoice** melalui reservasi D1 atomik sebelum menulis KV. Batas aplikasi tidak menghitung pemakaian namespace lain. Sediakan ruang akun untuk resource lain dan pantau dashboard. Kuota penuh menghentikan upload; tidak mengaktifkan R2 atau paket berbayar.
- KV bersifat eventually consistent. Media/invoice baru dapat memerlukan **60 detik atau lebih** sebelum terbaca dari lokasi lain. Aplikasi menggunakan key unik untuk setiap versi materi. Respons media privat `no-store`; izin dan pencabutan diperiksa di D1 pada setiap permintaan. [Konsistensi KV](https://developers.cloudflare.com/kv/concepts/how-kv-works/).
- JPG/PNG/MP4 diperiksa struktur metadata, resolusi, rasio, dan codec yang dideklarasikan. **Tidak ada decoding penuh, sanitasi ulang gambar, antivirus, FFmpeg, atau transcoding** pada versi ini. Operator wajib meninjau materi. Ini berbeda dari validator Python; jangan menganggap pemeriksaan metadata setara dengan decoding.
- Scheduler berjalan setiap menit. Permintaan manifest/admin/pesanan juga memicu rekonsiliasi jika tick terakhir sudah satu menit. Player memeriksa waktu mulai/akhir dan lease 30 detik sendiri.
- Satu item outbox diproses per invocation untuk membatasi CPU. Mutasi pesanan memulai pemrosesan lewat `waitUntil`; Cron mencoba ulang maksimal lima kali. Lease dan event key mencegah klaim serentak dan event ganda. SMTP tetap dapat mengirim ulang jika koneksi gagal setelah pesan diterima provider.
- Invoice menggunakan font/logo yang sudah di-embed pada waktu build; PDF dibuat sekali dan disimpan di KV. Ini mengurangi CPU request, tetapi batas 10 ms tetap perlu dipantau pada data panjang/beban nyata. Invoice tersedia setelah outbox memproses pembayaran dan KV menyinkronkan file.
- Player saat ini memakai sekitar **15.840 request/hari per layar** ketika aktif 24 jam: manifest setiap 10 detik, heartbeat 20 detik, serta laporan 30 detik saat kampanye tayang, belum termasuk media/admin/pelanggan/retry. Batasi jumlah layar sesuai sisa kuota akun; jangan menganggap Free mencukupi banyak layar.
- Data asli FastAPI dan data Cloudflare tidak tersinkron otomatis. Token pelanggan/perangkat dari deployment lain tidak berlaku di sini.

## Operasional dan backup

```sh
wrangler deployments list --config .generated/wrangler.json
wrangler tail --config .generated/wrangler.json
wrangler d1 export DB --remote --config .generated/wrangler.json --output .generated/d1-backup.sql
wrangler kv key list --binding MEDIA --config .generated/wrangler.json
```

Export D1 tidak mencadangkan file KV. Simpan media/invoice beserta database dan secrets melalui prosedur backup tersendiri. Jangan memasukkan export atau media pelanggan ke Git. Jika upload gagal setelah reservasi D1 tetapi proses terhenti sebelum commit pesanan, reservasi orphan dapat tetap ada; periksa sebelum membersihkan. Reservasi yang tertinggal mengurangi kapasitas, tidak menambah kuota.

`wrangler tail` dapat menampilkan informasi operasional. Hindari membagikan log mentah. Jangan menjalankan perintah penghapusan D1/KV atau mengganti ID resource ketika redeploy rutin.
