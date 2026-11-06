# Pemetaan sebelum migrasi
Dasar awal adalah bagian 2, 4 dan 7 dokumen MVP perusahaan. Matriks ini membedakan metadata yang dilaporkan dalam MVP dan keputusan desain. Hasil pencocokan langsung dengan workbook asli tercatat dalam verifikasi-sumber.md. Tidak ada impor transaksi atau identitas dari Excel.

| Workbook / lembar | Kolom atau blok menurut MVP | Satuan / tujuan aplikasi |
| --- | --- | --- |
| UPDATE TUTUP BUKU 2025 / PRICE LIST | Merek, netto, kemasan, isi karton, muatan, harga pabrik, transport, fee bongkar, HPP, harga jual, margin, harga per liter/kemasan, rentang pengambilan | SKU per varian; netto dengan satuan volume; konversi per SKU; harga bertingkat dalam rupiah per satuan dasar |
| MODAL PEMBELIAN | Tanggal, keterangan, Sanky, Kita, jumlah, pelunasan, transport, pengembalian, stok akhir | Pisahkan penerimaan dalam satuan dasar, modal, biaya perolehan, utang dan pembayarannya |
| KARTU STOCK (MINYAK) | Blok produk, tanggal, deskripsi, masuk, keluar, sisa | Gerakan satuan dasar bertanggal dan dokumen sumber; hitung saldo |
| PEMBAYARAN MINYAK / PEMBAYARAN SANKY 800 ML | Konsumen, tanggal, cash, tempo, status, jumlah karton, keterangan (lembar minyak) | Pelanggan, faktur dengan beberapa SKU, penyerahan, jatuh tempo, alokasi cicilan per faktur |
| LAP KEUANGAN GLOBAL / LAPORAN KEUANGAN | Tanggal, keterangan, kriteria beban, masuk, keluar, saldo, rekening CV, perantara, cash; rekap penjualan, bank, tunai, piutang dan biaya | Mutasi rupiah kas/bank, akun perantara, piutang dan kelompok beban |
| RUGI LABA CV DHANA PUTRA MANDIRI / NOV 2025 dan DES 2025 | Rincian harian menurut MVP | Transaksi dan tanggal efektif; bulan berasal dari tanggal bukti |
| LR / LAPORAN KEUANGAN 2025 | Penjualan, retur, diskon, beban pokok, pendapatan lain, kelompok beban | Bruto, diskon, retur, HPP, pemasaran/distribusi, tenaga kerja, administrasi/umum, lainnya, luar usaha, pajak |
 
Keputusan untuk dikonfirmasi: arti Q dan konversi karton/jeriken, rentang harga, saldo awal serta akun perantara. Angka demo bersifat sintetis. Usulan: unit dasar utuh, rupiah utuh, pembulatan setengah ke atas, rata-rata bergerak, pendapatan saat barang diserahkan. Untuk muatan campuran, keuangan mengisi alokasi aktual per baris; total per jenis biaya harus tepat sama dengan bukti. Bongkar perolehan dan bongkar operasional memakai referensi biaya unik. Retur setelah lunas menjadi kredit pelanggan. Hari lengkap dikonfirmasi gudang. Hari kosong stok berpotensi merendahkan estimasi. Setujui metode dan klasifikasi pajak bersama pemilik sebelum penggunaan riil.
