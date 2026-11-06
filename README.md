# Distribusi minyak goreng CV Dhana Putra Mandiri

Aplikasi internal satu perusahaan dan satu gudang. Django menyimpan dokumen, gerakan stok, jurnal, pengguna, dan sesi di SQLite. Semua nilai uang berupa rupiah utuh. Tanggal bisnis dan tampilan waktu menggunakan Asia/Jakarta.

## Jalankan demo lokal

Pada mesin pengembangan ini dependensi dan database demo sudah disiapkan. Dari direktori aplikasi di PowerShell, jalankan `.\demo.ps1` bila server berhenti. Buka [ruang kerja lokal](http://127.0.0.1:18765/), pilih **Pemilik**, lalu **Masuk ke ruang kerja**. Gunakan ikon keluar di bawah menu untuk mencoba peran lain. Bila port itu sudah digunakan server demo, cukup buka alamatnya.

Untuk instalasi baru dengan Python 3.13:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\demo.ps1
```

Di Linux atau macOS gunakan `python3 -m venv .venv`, aktifkan environment, pasang requirements, lalu jalankan:

```sh
export APP_ENV=local DEMO_MODE=1
python manage.py migrate --noinput
python manage.py demo_seed
python -m waitress --listen=127.0.0.1:18765 portal.wsgi:application
```

Generator memakai identitas dan transaksi sintetis, mengisi 42 hari operasional relatif terhadap inisialisasi pertama, dan dapat dijalankan ulang tanpa menduplikasi dokumen. Jika tanggal demo telah lama berlalu, pilih periode sesuai tanggal dokumennya. Database demo adalah `demo.sqlite3`. Pemilih peran hanya tersedia dalam mode demo dari loopback. Gunakan mode OIDC untuk menguji akses pegawai dengan penyedia identitas.

## Login pegawai dengan OpenID Connect

1. Salin `.env.example` menjadi `.env`. Gunakan `DEMO_MODE=0` dan hapus override demo pada shell yang digunakan. Database pegawai adalah `distribusi.sqlite3`.
2. Siapkan satu aplikasi OAuth jenis web di penyedia identitas, misalnya Google Workspace. Izinkan scope `openid email profile`. Untuk Workspace internal, pilih audiens pegawai perusahaan. Admin aplikasi tetap harus mengundang setiap email.
3. Isi `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, dan `OIDC_REDIRECT_URI` pada server. Issuer harus menerbitkan discovery pada `/.well-known/openid-configuration` serta JWKS. Daftarkan URI persis, termasuk garis miring akhir. Untuk lokal gunakan `http://localhost:8000/auth/callback/`. Jika port 8000 dicadangkan Windows, ganti kedua URI dan port server bersama-sama.
4. Jalankan migrasi, undang admin pertama, lalu mulai server.

```powershell
$env:DEMO_MODE='0'
.\.venv\Scripts\python.exe manage.py migrate --noinput
.\.venv\Scripts\python.exe manage.py invite_admin admin@perusahaan.example
.\.venv\Scripts\python.exe -m waitress --listen=127.0.0.1:8000 portal.wsgi:application
```

Ganti email contoh dengan akun perusahaan yang terverifikasi. Buka `http://localhost:8000/masuk/`. Admin masuk melalui penyedia, kemudian membuka **Data master → Pengguna dan peran → Tambah data**. Nama pengguna adalah email undangan. Setelah login pertama, pasangan issuer dan subject terikat pada akun tersebut. Menonaktifkan akun menutup akses pada permintaan berikutnya.

Authlib menjalankan Authorization Code dengan PKCE S256 dan memeriksa state, nonce, tanda tangan, issuer, audience dan masa berlaku. Aplikasi mensyaratkan ID token, email terverifikasi dan undangan aktif. Django menyimpan sesi di database, merotasi ID ketika login, memeriksa CSRF untuk perubahan, dan menghapus sesi aplikasi saat keluar. [Dokumentasi Authlib untuk web client](https://docs.authlib.org/en/latest/oauth2/client/web/)

## Produksi internal

- Gunakan `APP_ENV=production`, `DEMO_MODE=0`, `ALLOWED_HOSTS=distribusi.perusahaan.example`, dan `SECRET_KEY` acak yang disimpan melalui pengelola rahasia. Nilai contoh domain harus diganti. Daftarkan `https://distribusi.perusahaan.example/auth/callback/` pada penyedia dan `OIDC_REDIRECT_URI`. Aktifkan HTTPS pada reverse proxy internal. Konfigurasi produksi mengaktifkan redirect HTTPS, HSTS dan cookie Secure; sesi juga memakai HttpOnly dan SameSite=Lax.
- Jalankan migrasi dan bootstrap admin pada database produksi yang dicadangkan. Ikat Waitress ke loopback di belakang proxy TLS. Jika proxy lokal mengirim skema lewat header, buang header klien lalu tetapkan `X-Forwarded-Proto: https` pada proxy. Jalankan `python -m waitress --listen=127.0.0.1:8081 --trusted-proxy=127.0.0.1 --trusted-proxy-headers=x-forwarded-proto portal.wsgi:application`. Batasi akses ke jaringan pegawai. Sajikan direktori `static/` dari proxy atau melalui rute aset aplikasi.
- Pasang database di disk lokal dengan akses hanya untuk akun layanan. Gunakan satu instans penulis. SQLite mengunci penulisan dengan `BEGIN IMMEDIATE`; seluruh perubahan dokumen berhasil atau dibatalkan bersama. Cadangkan melalui SQLite backup API atau saat layanan dihentikan. Uji pemulihan pada salinan sebelum perubahan migrasi. Cadangan data pegawai dan rahasia konfigurasi dikelola terpisah.
- Periksa `python manage.py check --deploy` dengan environment produksi yang sebenarnya. Uji login, callback HTTPS, pencabutan akses, logout, dan pemulihan sebelum mengisi data perusahaan.

## Navigasi ruang kerja

Pemilik memiliki 15 tujuan menu sesuai urutan brief. Staf melihat tujuan dan tindakan sesuai perannya. Pesanan menampilkan faktur dan draf penjualan yang ada. Pengiriman menampilkan muatan dalam satuan dasar, membuka konfirmasi untuk draf, dan membuka surat jalan untuk penyerahan yang sudah dibukukan. Badge Piutang membuka faktur lewat tempo yang masih bersaldo. Pengisian Stok menghubungkan estimasi dengan penerimaan yang masih draf. Fee Pemasaran menampilkan pembayaran manual yang tercatat sebagai beban distribusi dan pemasaran.

## Alur kerja

| Peran | Langkah utama |
| --- | --- |
| Admin | Siapkan SKU terpisah per merek, netto, kemasan dan satuan dasar; isi konversi terkonfirmasi, harga bertingkat, tanggal berlaku waktu tunggu, mitra dan pegawai. |
| Keuangan dan Pemilik | Bila ada saldo pembukaan, Keuangan mengajukan tiap akun, SKU, atau faktur melalui **Pengaturan → Saldo awal**. Pemilik memeriksa lalu membukukan atau menolak draf sebelum transaksi pertama. Pada saldo nol langsung mulai penerimaan. |
| Gudang dan Keuangan | Gudang membuat penerimaan beserta jumlah. Keuangan membuka draf, mengisi harga per satuan dasar, akun tunai atau tempo, total transport dan bongkar serta alokasi per produk. Isi bukti biaya tersendiri jika nomornya berbeda dari faktur pemasok. |
| Penjualan dan Gudang | Penjualan membuat draf faktur tunai atau tempo, memilih pelanggan, jatuh tempo, produk, kuantitas dan diskon per baris. Harga kosong memakai tingkat harga yang berlaku untuk kuantitas dasar. Gudang memasukkan jumlah yang diserahkan lalu membukukan. Jika berbeda, batalkan draf dan buat draf pengganti sebelum penyerahan. Cetak surat jalan dari dokumen yang sudah dibukukan. |
| Keuangan | Catat pembayaran tunai maupun cicilan melalui **Kas & Bank → Catat mutasi → Cicilan**, dengan tanggal pembayaran dan faktur asal. Gunakan **Bayar pemasok**, **Uang muka**, **Alokasi uang muka**, **Transfer**, **Modal** atau **Beban** sesuai transaksi. |
| Gudang dan Keuangan | Gudang mengajukan retur dengan faktur asal dan kondisi barang, atau opname dengan alasan dan arah koreksi. Keuangan memeriksa lalu membukukan. Pengembalian pada tagihan lunas menjadi kredit pelanggan yang dapat dialokasikan. |
| Pemilik, Keuangan | Gunakan laporan periode, klik pos atau nomor bukti, lalu ekspor Excel. Jumlah piutang, utang dan stok adalah saldo sampai tanggal akhir. Laba rugi dan mutasi memakai rentang tanggal. Perbandingan laba rugi memakai satu bulan kalender penuh sebelum bulan tanggal awal. |
| Gudang | Setelah hari selesai, konfirmasi kelengkapan pencatatan, termasuk bila pengiriman nol. Pembukuan atau pembatalan penjualan mundur membatalkan konfirmasi hari itu. Buka **Stok & Gudang → Analisis ABC dan risiko** untuk prioritas ABC, cakupan, status risiko, kualitas data dan evaluasi historis. |
| Keuangan dan Pemilik | Pilih bulan yang telah selesai. Cocokkan saldo hasil pemeriksaan kas, bank, perantara, persediaan, piutang dan utang, lalu ajukan. Periode diajukan terkunci sampai pemilik menyetujui atau membuka kembali dengan alasan. Bukti dan riwayat tersedia pada **Log Audit**. |

## Perhitungan dan batas operasi

- Buku stok menyimpan kuantitas dan nilai per gerakan. Harga pokok keluar memakai rata-rata bergerak saat penyerahan, dibulatkan ke rupiah terdekat. Penjualan bruto, diskon, HPP, stok, serta tagihan terposting bersamaan. Saat pembayaran, hanya akun dana dan saldo tagihan yang bergerak.
- Harga beli dan alokasi berada di baris penerimaan. Transport masuk dan bongkar dapat tercantum pada bukti penerimaan yang sama. Pengeluaran dengan nomor bukti biaya yang sudah dikapitalisasi ditolak. Model tagihan pembelian menganggap pemasok menagih seluruh biaya perolehan yang dialokasikan pada penerimaan itu.
- Gudang menggunakan satuan transaksi dengan faktor bilangan bulat terkonfirmasi. Pecahan unit dapat diwakili dengan satuan dasar yang lebih kecil sebelum SKU dipakai. Koreksi opname tambah memakai nilai rata-rata tersedia. Stok nol tanpa riwayat nilai memerlukan penerimaan atau saldo awal bernilai.
- Koreksi dokumen aktif dapat membentuk jurnal pembalik pada tanggal asal jika periode terbuka dan belum ada gerakan stok atau alokasi berikutnya yang bergantung padanya. Pembukuan persediaan mundur melewati gerakan lebih baru ditolak untuk menjaga HPP historis. Retur pemasok mengurangi utang terbuka; penyelesaian pengembalian uang pemasok setelah lunas membutuhkan keputusan perusahaan.
- ABC memakai HPP barang keluar dikurangi nilai kembali layak jual. Ambang A dan B adalah 80% dan 95%. Produk yang menembus ambang menyelesaikan kelas itu. Nilai seri diurutkan menurut kode. Nilai nonpositif ditandai Tinjau. Gudang hanya menerima kelas dan kuantitas serta estimasi berbasis unit.
- Estimasi memakai 28 hari kalender selesai. Stok dan waktu tunggu dibaca pada tanggal akhir filter, termasuk pada filter historis. Pengiriman setelah tanggal prediksi hanya masuk evaluasi. Jika tujuh hari sesudah tanggal pilihan belum selesai, evaluasi memakai jendela latih historis berakhir tujuh hari sebelum hari lengkap terakhir, lalu menguji prediksi tetap pada tujuh hari berikutnya. MAE dihitung per SKU dalam satuan dasar per hari. Kekurangan data, stok kosong, laju nol dan waktu tunggu kosong ditampilkan tersendiri.

## Berkas dan verifikasi

- [Pemetaan sumber ke entitas](docs/pemetaan.md) dan [hasil pemeriksaan 11 lembar](docs/verifikasi-sumber.md). Data demo dibuat oleh perintah `demo_seed`; workbook asli tetap di luar sumber aplikasi.
- [Hasil pengujian dan UAT](docs/pengujian.md). Jalankan ulang dari direktori aplikasi dengan `.\.venv\Scripts\python.exe manage.py test --verbosity=2`.
- `ops/models.py` dan `ops/migrations/` memuat skema. `ops/books.py` menangani transaksi dan penguncian periode. `ops/insights.py` menghitung laporan dan analitik. `ops/auth.py` menangani login. Template, CSS, dan JavaScript berjalan tanpa proses build.
