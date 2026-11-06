# Pengujian dan penerimaan pengguna

## Hasil eksekusi lokal, 6 November 2026

Django 5.2.19, Authlib 1.9.5, Python 3.13, SQLite file sementara terpisah dari demo. Perintah `python manage.py test --verbosity=2` menjalankan 14 kasus otomatis. Masing-masing memakai saldo awal terisolasi. Dua penulis dalam uji persaingan memakai koneksi database yang berbeda.

| Pemeriksaan | Hasil teramati |
| --- | --- |
| 100 karton diterima tempo, barang Rp17.000.000, transport Rp800.000, bongkar Rp200.000; 40 karton dikirim tempo @Rp195.000; bank menerima Rp5.000.000 dan membayar antar Rp250.000 | Stok 60 karton senilai Rp10.800.000, HPP Rp7.200.000, piutang Rp2.800.000, utang Rp18.000.000, bank Rp4.750.000, laba bersih Rp350.000. Pada tanggal sebelum cicilan, piutang Rp7.800.000. Nilai laba pada workbook hasil ekspor dapat dibaca kembali sebagai angka. |
| Biaya antar menjadi Rp750.000 | Rugi bersih Rp150.000. |
| Rata-rata bergerak, dua penerimaan 10 karton @Rp180.000 dan @Rp200.000 lalu jual 5 | HPP Rp950.000, persediaan Rp2.850.000. Ketidaksesuaian total alokasi membatalkan seluruh pembukuan. |
| ABC tiga nilai pemakaian proporsional 82, 14, 4 serta satu SKU kosong | Kontribusi 82%, 14%, 4% menghasilkan A, B, C. Nilai nol masuk Tinjau. |
| 28 hari lengkap, keluar 280 karton, sisa 40, waktu tunggu 7 | Estimasi 10 karton/hari, cakupan 4 hari, status Berisiko. Tujuh hari berikutnya pada 5 karton/hari menghasilkan MAE 5. Saldo serta laju historis tetap identik setelah realisasi ditambahkan. |
| Hari hilang, laju nol, stok kosong atau waktu tunggu kosong | Kondisi dibedakan. Cakupan tetap tersedia jika hanya waktu tunggu yang kosong. Perubahan pengiriman pada hari lengkap meminta konfirmasi ulang. |
| Pengiriman ganda dan perebutan stok 5 karton untuk dua pengiriman masing-masing 4 | Hanya satu pengiriman bersaing dibukukan; saldo akhir 1 karton. Pengulangan konfirmasi tidak menggandakan stok, HPP, atau tagihan. |
| Login OIDC dengan penyedia uji | Authorization Code, PKCE S256 dan pasangan verifier/challenge diperiksa. State, nonce, issuer, audience, kedaluwarsa, dan tanda tangan salah ditolak. Undangan aktif berhasil. Akun asing atau nonaktif ditolak. Penandatanganan ID token sungguhan memakai kunci uji; pertukaran kode ke jaringan disubstitusi. |
| Akses langsung dan keamanan sesi | Gudang ditolak pada API keuangan, dana, master, tutup buku, dan ekspor laba rugi. Respons analitik Gudang menyembunyikan nilai pemakaian, kontribusi dan dokumen biaya. Permintaan perubahan tanpa CSRF ditolak. Logout mengakhiri akses sesi. |
| Pembukaan dan penutupan | Saldo awal memerlukan pemilik. Pembatalan yang diizinkan menyeimbangkan stok, laba dan ABC. Pengajuan tutup buku, persetujuan, penolakan perubahan tanggal terkunci dan pembukaan ulang beralasan diuji. |
| Retur, konversi dan alokasi | Retur layak jual dan rusak dibedakan, kredit pelanggan dialokasikan, harga faktur bertahan setelah perubahan tier, transfer menjaga total dana, pembayaran pemasok melunasi utang tanpa menambah beban. |
| Alur lewat endpoint formulir | Tiga peran melakukan penerimaan, pengiriman, cicilan dan pengeluaran lewat HTTP; laba Rp350.000. Bukti bongkar terpisah ditolak saat dicatat lagi sebagai beban. Surat jalan hanya memuat rincian penyerahan. |

Chromium membuka halaman kerja kelima peran melalui login demo lokal. Dashboard Pemilik diuji pada lebar 1440, 1024, 768, dan 390 piksel, termasuk render grafik, navigasi, dan pemeriksaan lebar halaman. Uji browser dapat diulang dengan server demo berjalan, Playwright dan Chromium tersedia, melalui `node qa/browser.cjs`. Isi `PLAYWRIGHT_MODULE` dan `CHROME_BIN` bila keduanya berada di luar instalasi standar.

## UAT perusahaan yang masih menunggu

| Pelaksana | Langkah pada lingkungan uji perusahaan | Bukti atau keputusan yang diperlukan |
| --- | --- | --- |
| Admin TI | Daftarkan URI lokal dan HTTPS produksi, undang pegawai uji, login, keluar, nonaktifkan akun, lalu coba ulang. Periksa akses langsung sebagai Gudang. | Client ID dan secret penyedia asli, hasil callback, konfigurasi TLS/proxy, dan bukti penolakan akses. |
| Gudang dan penjualan | Cocokkan varian, arti Q, konversi, harga bertingkat serta waktu tunggu. Jalankan penerimaan campuran, serah, cetak surat jalan, retur dan opname melalui UI. | Faktor konversi dan lead time disetujui, surat jalan cocok dengan kuantitas fisik. |
| Keuangan | Cocokkan saldo awal dan satu bulan bukti riil dalam lingkungan perusahaan. Periksa dasar alokasi muatan campuran, bukti bongkar, akun perantara, diskon, kredit retur, klasifikasi pajak, dan pembulatan. | Persetujuan metode serta rekonsiliasi selisih. Uji pemulihan cadangan di lingkungan target. |
| Pemilik | Telusuri satu angka laba hingga bukti, periksa rekonsiliasi, setujui tutup buku, lalu verifikasi alur pembukaan kembali beralasan. | Nama penguji berwenang, build, tanggal, hasil, bukti dan keputusan rilis. |

Status persetujuan pengguna bisnis dan peluncuran produksi **menunggu UAT perusahaan**. Lingkungan demo dan pengujian otomatis memakai data sintetis.
