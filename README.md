# LAMIA — Videotron Advertising Workspace

LAMIA adalah aplikasi pemesanan iklan videotron dengan FastAPI, SQLite, antarmuka berbahasa Indonesia, dan player berbasis browser. Pengiklan dapat memilih layar, memesan jadwal, memverifikasi kontak, mengajukan materi, dan memantau penayangan. Operator mengelola review, pembayaran, perangkat, serta jadwal.

Ringkasan kebutuhan dan implementasi tersedia di repository ini; dokumen PRD asli tidak disertakan.

## Menjalankan aplikasi

Memerlukan Python 3.10+ dan Node.js untuk pemeriksaan JavaScript. Tidak ada proses build frontend.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
# Buat konfigurasi hanya jika belum ada. Pertahankan konfigurasi SMTP Anda.
[ -f .env ] || cp .env.example .env
sh run.sh
```

Lengkapi `.env` sebelum menjalankan aplikasi. Launcher memilih `.venv`, lalu `venv` jika `.venv` tidak tersedia, membaca `.env` melalui path eksplisit, dan memakai `HOST` serta `PORT`. Variabel lingkungan yang sudah diekspor lebih diprioritaskan daripada `.env`. Restart aplikasi setelah mengubah konfigurasi.

| Halaman | Alamat lokal |
| --- | --- |
| Workspace pengiklan | `http://127.0.0.1:8000/` |
| Admin | `http://127.0.0.1:8000/admin` |
| Player videotron | `http://127.0.0.1:8000/player` |
| Dokumentasi API | `http://127.0.0.1:8000/docs` |
| Ketentuan dan privasi | `/terms`, `/privacy` |

Logo dan favicon LAMIA menggunakan `icon/logo.webp` serta `icon/logo.ico`. Panduan enam langkah berilustrasi tersedia melalui tombol **Panduan** di header dan sidebar.

## Login dan akses operasional

Menu **Jadwal & perangkat**, **Admin console**, serta pembukaan halaman **Player** memerlukan login admin. Sebelum login, workspace menampilkan **Masuk operasional**. Akses langsung ke `/admin`, `/schedule`, atau `/player` diarahkan ke halaman login; semua API `/api/v1/admin/` juga memeriksa sesi di server.

```dotenv
ADMIN_USERNAME=admin
ADMIN_PASSWORD=isi-kata-sandi-admin-yang-kuat
```

Jika `ADMIN_USERNAME` belum diisi, nama pengguna adalah `admin`; kata sandi tetap menggunakan `ADMIN_PASSWORD` yang sudah ada. Tidak ada lagi token admin di sessionStorage atau respons login. Token admin lama tidak berlaku untuk akses operasional.

- Login membuat sesi acak yang hash-nya tersimpan pada database. Browser menerima cookie **HttpOnly**, **SameSite=Strict**, dan **Secure** ketika production.
- Sesi berakhir setelah **30 menit tidak aktif**, dengan batas mutlak **8 jam**. Logout mencabut sesi di database. Perubahan username/password atau application secret mengakhiri sesi lama.
- Tindakan admin seperti review, konfirmasi pembayaran, pengelolaan perangkat, dan logout memerlukan pemeriksaan CSRF serta origin bila dikirim browser.
- Lima login gagal dari satu alamat klien memblokir percobaan login selama 15 menit. Pembatasan disimpan di database.
- Production harus diakses melalui HTTPS agar cookie Secure dapat digunakan. Atur `PUBLIC_BASE_URL` sesuai origin publik aplikasi, termasuk skema HTTPS. Satu akun operator berbasis environment digunakan saat ini; MFA dan pengelolaan akun/RBAC terpisah belum tersedia.

Login admin diperlukan saat membuka player/setup. Setelah terhubung, player tetap memakai kredensial perangkat yang terikat pada layar untuk komunikasi mesin, sehingga penayangan tidak berhenti hanya karena sesi admin berakhir. Token perangkat tidak memberikan akses ke API admin.

## Aturan jadwal: development dan production

Semua tanggal dan jam pada form pemesanan menggunakan **WIB (Asia/Jakarta, UTC+7)**, terlepas dari zona waktu perangkat.

| Aturan | `APP_ENV=development` | `APP_ENV=production` |
| --- | --- | --- |
| Mulai tayang | Dapat menggunakan waktu sekarang | Minimal 24 jam ke depan |
| Toleransi waktu mulai saat membuat pesanan | Maksimal 5 menit sebelum waktu server, untuk mengakomodasi pengisian form | Tanpa toleransi |
| Durasi minimum | 24 menit | 24 jam |
| Tombol kalender | **Sekarang** dan pilihan durasi **24 menit** | Waktu paling awal sesuai batas 24 jam |
| Checkout setelah waktu mulai terlewati | Diizinkan selama periode belum berakhir | Ditolak |
| Aktivasi setelah pembayaran | Langsung `LIVE` jika waktu mulai sudah tercapai | `SCHEDULED`, lalu `LIVE` ketika waktu mulai tercapai |

Aturan development berlaku khusus untuk nilai `development`; lingkungan lain menggunakan batas jadwal production. Aturan yang sama digunakan oleh kalender, estimasi biaya, dan pembuatan pesanan. Selesai tayang harus berada setelah waktu sekarang; periode yang sudah berakhir tidak dapat dibayar.

Contoh uji penayangan langsung: pilih **Sekarang**, atur durasi 30 menit atau lebih, selesaikan verifikasi serta review, lalu konfirmasikan pembayaran sebelum periode berakhir. Pemilihan waktu sekarang tidak melewati kewajiban verifikasi, persetujuan materi, atau pembayaran.

## Verifikasi email melalui SMTP

**Email selalu dikirim melalui SMTP, termasuk pada development. Tidak ada kode email dummy, pengisian kode otomatis, atau pengembalian kode email pada respons pengiriman.**

Konfigurasi yang telah ada di `.env` tetap dipakai. Contoh pengaturan SSL:

```dotenv
SMTP_HOST=smtp.domain-anda.id
SMTP_PORT=465
SMTP_SECURE=true
SMTP_ENCRYPTION=ssl
SMTP_FROM=noreply@domain-anda.id
SMTP_USERNAME=isi-username-smtp
SMTP_PASSWORD=isi-password-smtp
```

- `SMTP_ENCRYPTION=ssl`: TLS langsung, umumnya port 465.
- `SMTP_ENCRYPTION=starttls` atau `tls`: koneksi SMTP yang ditingkatkan ke TLS, umumnya port 587.
- Jika `SMTP_ENCRYPTION` kosong, `SMTP_SECURE=true` memilih SSL; selain itu digunakan STARTTLS. Nilai `SMTP_ENCRYPTION` yang diisi memiliki prioritas.
- Sertifikat server diverifikasi. `SMTP_FROM` digunakan sebagai pengirim; sesuaikan dengan identitas pengirim yang diizinkan penyedia SMTP.

Email memiliki desain HTML LAMIA, logo tertanam, kode enam digit, petunjuk pengisian, dan alternatif teks biasa. Kode berlaku **5 menit**, pengiriman ulang memiliki jeda sekitar **60 detik**, dan kode salah dibatasi hingga **5 percobaan**. Kode disimpan sebagai hash pada database.

Di halaman verifikasi, klik **Kirim kode**, periksa inbox atau spam, masukkan kode dari email, lalu pilih **Verifikasi email**. Tersedia indikator masa berlaku, hitung mundur kirim ulang, pesan kesalahan di kolom, dan status terverifikasi. Jika SMTP gagal, aplikasi menampilkan kegagalan pengiriman dan tidak beralih ke kode dummy.

## Email tagihan dan konfirmasi pembayaran

LAMIA mengirim email otomatis melalui SMTP pada peristiwa berikut:

| Peristiwa | Isi email |
| --- | --- |
| Materi masuk antrean review | Nomor pesanan, layar, periode, status menunggu, serta tautan cek status |
| Materi disetujui | Konfirmasi persetujuan, tautan status, dan petunjuk melanjutkan checkout |
| Materi ditolak atau perlu revisi | Alasan/catatan revisi, tautan status, dan petunjuk pengajuan ulang |
| Tagihan berhasil dibuat | Nomor pesanan, layar, periode WIB, subtotal, pajak, total, rekening transfer yang tersedia, dan batas pembayaran |
| Pembayaran dikonfirmasi operator | Konfirmasi pembayaran, referensi bank, jadwal kampanye, dan invoice PDF terlampir |

Pembayaran simulasi development diberi penanda **SIMULASI**, termasuk pada email dan lampiran. Email OTP, tagihan, dan pembayaran memakai layout tabel, CSS inline, logo PNG dengan Content-ID, serta versi teks biasa. Template tidak bergantung pada flexbox atau pemuatan gambar eksternal.

Email review, tagihan, dan pembayaran dicatat ke tabel `email_outbox` dalam transaksi yang sama dengan perubahan pesanan. SMTP dijalankan setelah commit melalui background task. Worker terpisah dari rekonsiliasi jadwal mencoba ulang pengiriman yang gagal, maksimal lima percobaan dengan jeda bertambah. Antrean tersimpan tetap tersedia setelah restart; scheduler container juga memprosesnya. Kegagalan SMTP tidak membatalkan tagihan atau pembayaran.

Kunci event unik mencegah email baru untuk pengulangan checkout yang sama, dan lease database mencegah dua worker mengirim item yang sama secara bersamaan. Message-ID dipertahankan saat retry. Seperti pengiriman SMTP pada umumnya, kegagalan proses tepat setelah server menerima pesan masih dapat menyebabkan pengiriman ulang; ini bukan jaminan exactly-once. Tagihan yang sudah dibayar atau kedaluwarsa tidak dikirim ulang dari antrean. Notifikasi menunggu review yang sudah tidak relevan, atau keputusan untuk versi materi yang sudah diganti, dibatalkan sebelum retry. Aktivitas `EMAIL_SENT`, `EMAIL_RETRY`, `EMAIL_FAILED`, dan `EMAIL_CANCELLED` dapat dilihat pada audit admin.

Isi email menggunakan snapshot transaksi, bukan perubahan tarif/rekening setelahnya. Antrean email tidak menyimpan token sesi atau hash NPWP. Isi `PUBLIC_BASE_URL` dengan URL workspace publik agar email transaksi menyertakan tombol ke aplikasi. Email review menggunakan tautan `/status` dengan akses khusus baca-status yang berlaku **7 hari**. Tautan menampilkan perkembangan terbaru dan catatan revisi tanpa membuka informasi kontak, data pajak, perubahan materi, pembayaran, atau akses admin. Halaman diperbarui otomatis setiap 20 detik. Gunakan tautan dari email terbaru jika akses telah berakhir.

Untuk email review di production, `PUBLIC_BASE_URL` harus berupa URL HTTPS publik agar tombol status tersedia. Pada development dengan host localhost/127.0.0.1, alamat lokal dapat digunakan otomatis. Jika domain publik belum diatur, email tetap menjelaskan cara memeriksa Pesanan saya, tetapi tidak membuat tautan berbasis Host yang tidak dipercaya.

## Verifikasi ponsel dan pembayaran lokal

`ENABLE_DEMO_OTP` sekarang **hanya berlaku untuk ponsel**. Variabel tersebut tidak mengubah pengiriman email.

| Konfigurasi | Perilaku |
| --- | --- |
| `ENABLE_DEMO_OTP=true` di development | Kode ponsel ditampilkan untuk pengujian lokal; email tetap dikirim melalui SMTP |
| `ENABLE_DEMO_OTP=false` | Kode ponsel dikirim melalui adapter HTTPS yang dikonfigurasi |
| `ENABLE_DEMO_PAYMENTS=true` di development | Tombol simulasi pembayaran tersedia tanpa memproses uang sungguhan |
| `APP_ENV=production` | Kedua mode simulasi selalu dinonaktifkan |

Pengiriman ponsel memakai `PHONE_OTP_WEBHOOK_URL` dan `PHONE_OTP_WEBHOOK_TOKEN`. Adapter menerima `{"to":"+62…","code":"123456","expires_in":300}` dengan Bearer authentication dan harus menghubungkannya ke penyedia SMS/WhatsApp. Alamat adapter wajib HTTPS.

## Alur pemesanan

1. **Pilih layar dan jadwal.** Cari lokasi, pilih videotron, lalu atur waktu pada kalender. Periksa ketersediaan dan estimasi biaya. Membuat draft belum mengunci slot.
2. **Isi data bisnis.** Nama perusahaan, alamat, PIC, email aktif, nomor ponsel Indonesia, serta NPWP **15 atau 16 digit** wajib diisi. Titik, spasi, dan tanda hubung NPWP diperbolehkan; huruf ditolak. Angka nol di depan tetap dihitung. Validasi frontend dan backend mengikuti aturan yang sama.
3. **Setujui ketentuan.** Versi syarat dan timestamp persetujuan dicatat bersama pesanan. Simpan nomor pesanan.
4. **Verifikasi kedua kontak.** Email memakai SMTP sungguhan; ponsel mengikuti konfigurasi adapter atau mode pengujian ponsel. Keduanya harus terverifikasi sebelum melanjutkan.
5. **Ajukan materi.** Pilih template teks atau unggah gambar/video. Operator melihat materi asli melalui Admin, kemudian menyetujui atau mengembalikan catatan revisi.
6. **Buat tagihan.** Setelah materi disetujui, checkout mengunci slot selama **15 menit**. Ketersediaan diperiksa kembali dalam transaksi database; kunci idempotensi mencegah tagihan ganda untuk permintaan yang sama.
7. **Bayar dan konfirmasi.** Transfer nominal sesuai tagihan, lalu hubungi operator dengan nomor pesanan dan bukti transfer. Operator mencocokkan dana di mutasi bank dan mencatat referensi transaksi unik. Ini merupakan rekonsiliasi bank manual, bukan integrasi payment gateway. Tagihan kedaluwarsa tidak dapat dikonfirmasi; pembayaran terlambat perlu direkonsiliasi operator sebelum membayar ulang.
8. **Pantau kampanye.** Pembayaran terkonfirmasi mengaktifkan jadwal. Status bergerak dari `SCHEDULED` ke `LIVE`, kemudian `COMPLETED`. Pada development, kampanye langsung `LIVE` setelah pembayaran jika waktu mulai telah tercapai.

Lanjutkan melalui **Pesanan saya** dalam sesi browser yang sama. Token sesi bukan akun pelanggan; jika sesi hilang, hubungi operator menggunakan nomor pesanan. Operator dapat meninjau pesanan, melihat audit, dan menghentikan kampanye dengan alasan yang tercatat.

## Materi iklan dan perhitungan biaya

- JPG/PNG atau MP4 H.264, maksimal **20 MB**.
- Rasio mengikuti layar, dengan minimum 320×180 dan maksimum 16 megapiksel.
- Gambar didekode, diperiksa, dan disimpan ulang tanpa metadata asli.
- Video harus memiliki durasi positif. Server Linux memakai **FFmpeg/ffprobe**, yang sudah disertakan pada Dockerfile. Jika `ffprobe` lokal macOS hilang atau gagal berjalan, aplikasi dapat menggunakan AVFoundation melalui Swift sebagai cadangan. Codec, resolusi, orientasi, dan durasi tetap diperiksa. File tidak dikonversi. Kegagalan validator server dilaporkan sebagai HTTP 503, bukan dianggap sebagai file yang melanggar format. File rusak atau format tidak sesuai ditolak dengan HTTP 422.
- Semua materi memerlukan persetujuan manusia sebelum checkout; template teks bukan layanan generasi gambar AI.

Biaya dihitung prorata berdasarkan hari kalender WIB dan jumlah hari dalam bulan. Perhitungan menggunakan Decimal dengan pembulatan `ROUND_HALF_UP` per hari. Pajak mengikuti nilai pada data layar/pesanan; nilai awal 11% adalah konfigurasi operator, bukan penetapan tarif pajak yang berlaku bagi bisnis Anda.

## Invoice profesional

Invoice PDF A4 tersedia setelah pembayaran tercatat, termasuk untuk kampanye berbayar yang kemudian dihentikan. Dokumen memuat logo LAMIA, nomor invoice dan pesanan, identitas pengiklan, NPWP tersamarkan, jadwal WIB, rincian biaya per hari, pajak, total, serta referensi bank jika tersedia.

Kampanye panjang menggunakan tabel bersambung dengan header berulang dan nomor halaman. Pembayaran sungguhan ditandai **LUNAS**; pembayaran simulasi ditandai **SIMULASI**. Nilai diambil dari data pesanan tersimpan. Invoice ini merupakan bukti pembayaran, **bukan faktur pajak**.

Lengkapi `OPERATOR_NAME`, `OPERATOR_ADDRESS` (opsional), dan `SUPPORT_EMAIL` untuk identitas penerbit. File unduhan menggunakan pola `invoice-LAMIA-ORD-….pdf`.

## Scheduler, perangkat, dan player

Scheduler berjalan setiap **5 detik**, merekonsiliasi status yang tersimpan, dan melanjutkan keadaan setelah restart. Halaman **Jadwal & perangkat** menampilkan kalender tujuh hari, status koneksi, laporan penayangan, dan jadwal pemeliharaan. Blokir pemeliharaan tidak dapat menimpa reservasi aktif.

Untuk menjalankan scheduler sebagai proses terpisah:

```sh
# Atur DISABLE_EMBEDDED_SCHEDULER=true pada .env untuk proses API.
. .venv/bin/activate
python scheduler.py
```

Kedua proses harus menggunakan `DB_PATH` dan konfigurasi yang sama. Gunakan process supervisor pada mesin deployment untuk menjalankan dan memulai ulang proses.

Daftarkan perangkat melalui **Jadwal & perangkat → Kelola token**. Setiap token terikat pada satu layar, disimpan sebagai hash HMAC, dan dapat dicabut. Token asli hanya ditampilkan sekali saat dibuat; daftar perangkat berikutnya menampilkan identitas dan status, bukan token asli. `DEVICE_TOKEN` bersama hanya diterima di development, tidak di production.

Pada komputer layar, login admin terlebih dahulu, lalu buka `/player`, pilih layar, masukkan token, dan mulai dalam fullscreen. Player:

- Memeriksa manifest 48 jam setiap 10 detik dan mengikuti waktu server.
- Menampilkan gambar, video yang diulang tanpa suara, atau template teks pada periode yang disetujui.
- Mengirim heartbeat setiap 20 detik dan segmen laporan penayangan setiap 30 detik.
- Menampilkan materi bawaan di luar kampanye aktif dan menghentikan iklan jika izin server tidak diperbarui selama 30 detik.

Takedown diterapkan pada sinkronisasi berikutnya atau saat izin berakhir ketika koneksi putus. Laporan penayangan disimpan sementara di localStorage dan dikirim ulang dengan ID yang sama. Laporan berasal dari klien, bukan bukti tampilan yang diverifikasi secara independen. Belum ada pemutaran offline tanpa batas atau cache media service worker. Token player berada di sessionStorage; sesi baru memerlukan koneksi ulang. Jalankan browser kiosk dengan supervisor untuk perangkat tanpa operator.

## Konfigurasi dan penyimpanan

Lihat `.env.example` tanpa menyalin kredensial ke file yang dibagikan.

- `APP_ENV`: pilih `development` atau `production` secara eksplisit.
- `ADMIN_USERNAME`: nama pengguna operator, default `admin`.
- `APP_SECRET`, `ADMIN_PASSWORD`: gunakan nilai unik. Production menolak nilai bawaan/placeholder dan memerlukan secret minimal 32 karakter serta password admin minimal 12 karakter.
- `HOST`, `PORT`: alamat bind dan port; default `127.0.0.1:8000`.
- `DB_PATH`: lokasi SQLite. Cadangkan database dan `uploads/` secara bersamaan.
- `OPERATOR_NAME`, `SUPPORT_EMAIL`: identitas/kontak layanan. Ketentuan tetap diberi label draf hingga keduanya diisi; pengisian identitas tidak menggantikan review legal.
- `BANK_NAME`, `BANK_ACCOUNT`, `BANK_HOLDER`: instruksi transfer. Checkout pembayaran bank memerlukan rekening yang dikonfigurasi.
- `SMTP_*`, `PHONE_OTP_*`: pengiriman kode sesuai penjelasan di atas. SMTP yang sama dipakai untuk tagihan dan konfirmasi pembayaran.
- `PUBLIC_BASE_URL`: URL workspace publik opsional untuk tombol pada email transaksi.

Jangan commit `.env`, database, unggahan pelanggan, token, atau virtual environment. Setelah memperbarui frontend, muat ulang browser tanpa cache bila tampilan lama masih muncul.

## Pemeriksaan

```sh
python -m pytest tests/ -q
node --test tests/test_form_ui.cjs
node --check static/app.js
node --check static/date-picker.js
node --check static/dropdown.js
node --check static/player.js
node --check static/guide.js
```

Pengujian mengisolasi database, unggahan, dan pengiriman pesan dari data operator. SMTP dipalsukan hanya dalam automated test sehingga test tidak mengirim email ke alamat fixture; aplikasi yang dijalankan pengguna tetap memakai SMTP sungguhan untuk email. Cakupan meliputi harga, validasi form, perbedaan aturan jadwal, OTP, login/sesi admin, CSRF, pembatasan login, email review dan akses status, checkout, pembayaran, invoice panjang, scheduler, takedown, token perangkat, dan laporan penayangan.

## Pekerjaan sebelum peluncuran publik

Lengkapi identitas bisnis, review ketentuan dan retensi data, HTTPS, MFA/RBAC admin, akun serta pemulihan pelanggan, pembatasan permintaan bersama, pemindaian malware, decoding/transcoding video menyeluruh, backup, monitoring, dan penilaian beban. SQLite ditujukan untuk deployment lokal/kecil; deployment booking lintas server memerlukan PostgreSQL, exclusion constraints, dan migrasi terkelola. Refund, rekonsiliasi pembayaran terlambat, payment gateway/webhook, serta faktur pajak belum diotomatisasi.

## Referensi antarmuka

Alur inventaris dan kampanye mengacu pada pola [AdQuick](https://www.adquick.com/products/), sementara pemisahan konten, layar, dan penjadwalan mengacu pada [Broadsign](https://docs.broadsign.com/broadsign-control/latest/en/content-and-scheduling.html). Ilustrasi lokasi dan panduan merupakan aset vektor lokal, bukan foto instalasi sebenarnya.
