"""Destinasi ruang kerja, dalam urutan proses perusahaan."""

from urllib.parse import parse_qs, urlsplit

FIN = ("Keuangan", "Pemilik")
STOCK = ("Gudang", *FIN)
SALES = ("Penjualan", *FIN)
OPS = ("Gudang", "Penjualan", *FIN)
MENU = [
    ("Operasional", "Ringkasan", "grid", "/", OPS),
    ("Operasional", "Pesanan", "bag", "/dokumen/?alur=pesanan", OPS),
    ("Operasional", "Pelanggan", "people", "/pelanggan/", SALES),
    ("Operasional", "Stok & Gudang", "box", "/stok/", STOCK),
    ("Operasional", "Pembelian", "cart", "/dokumen/?alur=pembelian", STOCK),
    ("Operasional", "Pengiriman", "truck", "/dokumen/?alur=pengiriman", OPS),
    ("Operasional", "Retur", "undo", "/dokumen/?alur=retur", OPS),
    ("Keuangan", "Piutang", "receipt", "/laporan/?jenis=piutang&tunggak=1", SALES),
    ("Keuangan", "Kas & Bank", "wallet", "/laporan/?jenis=dana", FIN),
    ("Perencanaan", "Pengisian Stok", "layers", "/pengisian/", STOCK),
    ("Perencanaan", "Fee Pemasaran", "percent", "/fee/", FIN),
    ("Perusahaan", "Laporan", "report", "/laporan/", SALES),
    ("Perusahaan", "Log Audit", "clock", "/aktivitas/", FIN),
    ("Perusahaan", "Data Master", "database", "/master/", ("Admin", "Pemilik")),
    ("Perusahaan", "Pengaturan", "settings", "/pengaturan/", ("Admin", *FIN)),
]


def sidebar(request, role, overdue):
    items = []
    section = ""
    for group, label, icon, url, allowed in MENU:
        if role not in allowed:
            continue
        parts = urlsplit(url)
        criteria = parse_qs(parts.query)
        match = request.path == parts.path and all(
            request.GET.get(k) == v[0] for k, v in criteria.items() if k != "tunggak"
        )
        if label == "Laporan" and request.GET.get("jenis") in ("piutang", "dana"):
            match = False
        if label == "Kas & Bank" and request.path in ("/dana/", "/pembukaan/"):
            match = True
        if label == "Pengaturan" and request.path == "/periode/":
            match = True
        if label == "Stok & Gudang" and request.path in ("/hari/", "/analisis/"):
            match = True
        if getattr(request, "document_kind", None):
            section_for_kind = {
                "Penjualan": "Pengiriman" if role == "Gudang" else "Pesanan",
                "Penerimaan": "Pembelian",
                "Retur": "Retur",
                "Retur pemasok": "Retur",
                "Opname": "Stok & Gudang",
                "Saldo awal": "Pengaturan",
            }
            match = label == section_for_kind.get(request.document_kind, "Kas & Bank")
        if request.path.endswith("/surat-jalan/"):
            match = label == "Pengiriman"
        items.append(
            {
                "group": group if section != group else "",
                "label": label,
                "icon": icon,
                "url": url,
                "active": match,
                "badge": overdue if label == "Piutang" else 0,
            }
        )
        section = group
    return items
