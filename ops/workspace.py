"""Halaman operasional yang menghubungkan data dan pembukuan yang sama."""

from decimal import ROUND_CEILING, Decimal

from django import forms
from django.shortcuts import redirect, render
from django.utils import timezone

from . import books as b
from .insights import analysis, outstanding
from .models import Doc, Entry, Line, Party
from .views import FIN, SALES, WARE, dates, doc_url, gate, idr, link, row, table


@gate(*SALES)
def customers(request):
    start, end = dates(request)
    balances = {}
    for invoice, amount in outstanding("Piutang", end):
        balances[invoice.party_id] = balances.get(invoice.party_id, 0) + amount
    parties = Party.objects.filter(
        kind="Pelanggan", name__icontains=request.GET.get("q", "")
    ).order_by("name")
    rows = [
        row(
            [p.name, idr(balances.get(p.pk, 0))],
            link("/dokumen/", mitra=p.pk, awal=start, akhir=end),
        )
        for p in parties
    ]
    return table(
        request,
        "Pelanggan",
        ["Pelanggan", "Piutang per tanggal akhir"],
        rows,
        search=True,
        start=start,
        end=end,
    )


@gate(*WARE)
def restock(request):
    start, end = dates(request)
    result = analysis(start, end, request.user.role)
    rows = []
    for item in result["rows"]:
        p = item["product"]
        if request.GET.get("risiko") and item["risk"] != "Berisiko":
            continue
        rate, lead = item["rate"], item["lead"]
        suggested = "—"
        if end == timezone.localdate():
            pending = b.balance(
                Line.objects.filter(
                    product=p,
                    doc__kind="Penerimaan",
                    doc__status="Draf",
                    doc__date__lte=end,
                ),
                "qty",
            )
            if rate is not None and lead is not None:
                suggested = max(
                    0,
                    int(
                        (
                            Decimal(str(rate)) * lead - item["stock"] - pending
                        ).to_integral_value(rounding=ROUND_CEILING)
                    ),
                )
        else:
            pending = "—"
        rows.append(
            row(
                [
                    p.code,
                    str(p),
                    item["stock"],
                    p.unit,
                    round(rate, 2) if rate is not None else "Data belum cukup",
                    lead if lead is not None else "Belum diisi",
                    pending,
                    suggested,
                    item["risk"],
                ],
                link("/stok/", produk=p.pk, awal=start, akhir=end),
            )
        )
    args = {"awal": start, "akhir": end}
    return table(
        request,
        "Pengisian Stok",
        [
            "Kode",
            "Produk",
            "Stok",
            "Satuan",
            "Unit/hari",
            "Tunggu (hari)",
            "Penerimaan draf",
            "Kebutuhan tambahan",
            "Status",
        ],
        rows,
        start=start,
        end=end,
        tabs=[
            ("Semua produk", link("/pengisian/", **args)),
            ("Produk berisiko", link("/pengisian/", risiko=1, **args)),
            ("Dasar estimasi", link("/analisis/", **args)),
        ],
        actions=[("Buka pembelian", link("/dokumen/", alur="pembelian", **args))],
    )


@gate("Admin", *FIN)
def settings_page(request):
    role = request.user.role
    choices = []
    if role == "Admin":
        choices = [
            row(
                ["Pengguna dan peran", "Undangan pegawai, akses, dan status akun"],
                "/master/?jenis=pegawai",
            ),
            row(
                [
                    "Waktu tunggu pemasok",
                    "Parameter perhitungan kebutuhan stok per produk",
                ],
                "/master/?jenis=tunggu",
            ),
        ]
    else:
        choices = [
            row(
                ["Periode pembukuan", "Rekonsiliasi dan keputusan penutupan periode"],
                "/periode/",
            ),
            row(["Log Audit", "Riwayat persetujuan dan perubahan"], "/aktivitas/"),
        ]
        if role == "Keuangan":
            choices.append(
                row(
                    ["Saldo awal", "Ajukan saldo awal untuk diperiksa pemilik"],
                    "/pembukaan/",
                )
            )
    return table(request, "Pengaturan", ["Pengaturan", "Kegunaan"], choices)


class FeeForm(forms.Form):
    day = forms.DateField(
        label="Tanggal pembayaran",
        initial=timezone.localdate,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    payee = forms.CharField(label="Penerima fee", max_length=80)
    invoice = forms.ModelChoiceField(
        label="Faktur asal",
        queryset=Doc.objects.filter(kind="Penjualan", status=b.POSTED).order_by("-pk"),
    )
    amount = forms.IntegerField(label="Fee yang disetujui (Rp)", min_value=1)
    fund = forms.ChoiceField(label="Akun pembayaran", choices=[(v, v) for v in b.FUNDS])
    proof = forms.CharField(label="Nomor bukti pembayaran", max_length=80)


@gate(*FIN)
def fees(request):
    from uuid import uuid4

    if request.GET.get("baru") or request.method == "POST":
        b.require(request.user, "Keuangan")
        form = FeeForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            data = form.cleaned_data
            doc = b.cash(
                request.user,
                "Beban",
                data["day"],
                data["amount"],
                data["fund"],
                category="Distribusi dan pemasaran",
                ref=data["invoice"],
                note="Fee pemasaran · " + data["payee"],
                proof=data["proof"],
                token=request.POST.get("token"),
            )
            return redirect(doc_url(doc))
        return render(
            request,
            "form.html",
            {"title": "Catat pembayaran fee", "form": form, "token": uuid4().hex},
        )
    start, end = dates(request)
    ledger = (
        Entry.objects.filter(
            doc__kind="Beban",
            doc__note__startswith="Fee pemasaran · ",
            doc__date__range=(start, end),
            account="Distribusi dan pemasaran",
        )
        .select_related("doc__ref")
        .order_by("-doc__date", "-id")
    )
    rows = [
        row(
            [
                str(e.doc),
                e.doc.date,
                e.doc.note.removeprefix("Fee pemasaran · "),
                str(e.doc.ref or "—"),
                idr(e.amount),
                e.doc.status,
            ],
            doc_url(e.doc),
        )
        for e in ledger
    ]
    return table(
        request,
        "Fee Pemasaran",
        ["Bukti", "Tanggal", "Penerima", "Faktur asal", "Fee dibayar", "Status"],
        rows,
        start=start,
        end=end,
        actions=[("Catat pembayaran fee", "/fee/?baru=1")]
        if request.user.role == "Keuangan"
        else [],
    )
