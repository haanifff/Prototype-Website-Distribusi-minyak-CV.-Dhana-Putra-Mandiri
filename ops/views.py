from calendar import monthrange
from datetime import date, timedelta
from functools import wraps
from urllib.parse import urlencode
from uuid import uuid4

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from openpyxl import Workbook
from openpyxl.styles import Font

from . import books as b
from .forms import MASTERS, CashForm
from .insights import METRICS, actuals, analysis, date_series, outstanding
from .models import (
    ROLES,
    Audit,
    Conversion,
    Day,
    Doc,
    Employee,
    Entry,
    Lead,
    Movement,
    Party,
    Period,
    Product,
    Tier,
)
from .navigation import sidebar

FIN = b.FINANCE
WARE = ("Gudang", *FIN)
SALES = ("Penjualan", *FIN)
OPER = ("Gudang", "Penjualan", *FIN)
SCOPES = {
    "Gudang": ["Penerimaan", "Penjualan", "Opname", "Retur", "Retur pemasok"],
    "Penjualan": ["Penjualan", "Retur"],
    "Admin": [],
}


def context(request):
    role = getattr(request.user, "role", "")
    today = timezone.localdate()
    overdue = 0
    if role in SALES:
        overdue = (
            Entry.objects.filter(
                account="Piutang", doc__date__lte=today, item__due__lt=today
            )
            .values("item_id")
            .annotate(saldo=Sum("amount"))
            .filter(saldo__gt=0)
            .count()
        )
    return {
        "demo_mode": settings.DEMO,
        "today": today,
        "sidebar": sidebar(request, role, overdue),
        "finance": getattr(request.user, "role", "") in FIN,
    }


def gate(*roles):
    def decorate(fn):
        @never_cache
        @login_required
        @wraps(fn)
        def call(request, *args, **kwargs):
            b.require(request.user, *roles)
            try:
                return fn(request, *args, **kwargs)
            except (
                ValidationError,
                ObjectDoesNotExist,
                IntegrityError,
                ValueError,
                KeyError,
            ) as e:
                msg = (
                    " ".join(e.messages)
                    if isinstance(e, ValidationError)
                    else "Nilai, referensi, atau kombinasi data tidak sah."
                )
                return render(request, "error.html", {"message": msg}, status=400)

        return call

    return decorate


def dates(request):
    end = b.as_day(request.GET.get("akhir") or timezone.localdate())
    start = b.as_day(request.GET.get("awal") or end.replace(day=1))
    b.check(
        start <= end and (end - start).days <= 731,
        "Rentang maksimum dua tahun. Periksa urutan tanggal.",
    )
    return start, end


def link(path, **params):
    return path + "?" + urlencode(params)


def visible(user):
    q = Doc.objects.select_related("party", "actor")
    if user.role in FIN:
        return q
    permitted = SCOPES[user.role]
    return q.filter(
        Q(kind__in=permitted) | Q(kind="Pembatalan", ref__kind__in=permitted)
    )


def idr(value):
    return "Rp " + format(int(value), ",").replace(",", ".")


def table(request, title, headers, rows, **extra):
    if request.path == "/stok/":
        params = request.GET.copy()
        if params.get("ekspor") == "xlsx":
            return export(request, title, headers, rows, extra["start"], extra["end"])
        params["ekspor"] = "xlsx"
        extra["actions"] = [("Ekspor Excel", "?" + params.urlencode())]
        if request.user.role == "Gudang":
            extra["actions"].insert(0, ("Ajukan opname", "/buat/?jenis=Opname"))
    page = Paginator(rows, 25).get_page(request.GET.get("hal"))
    extra["page"] = page
    rows = page.object_list
    return render(
        request, "table.html", dict(title=title, headers=headers, rows=rows, **extra)
    )


def row(cells, url=""):
    return {"cells": cells, "url": url}


def doc_url(d):
    return f"/dokumen/{d.pk}/"


@gate(*ROLES)
def home(request):
    role = request.user.role
    if role == "Admin":
        return redirect("/master/")
    start, end = dates(request)
    docs = (
        visible(request.user).filter(date__range=(start, end)).order_by("-date", "-pk")
    )
    metrics = actuals(start, end) if role in FIN else {}
    chart = date_series(start, end) if role in FIN else []
    if role in WARE:
        result = analysis(start, end, role)
        priorities = result["rows"]
    else:
        priorities = []
    kpis = []
    args = {"awal": start, "akhir": end}
    prompt = None
    pending = docs.filter(kind="Penjualan", status="Draf").count()
    alerts = []
    risk = sum(r["risk"] == "Berisiko" for r in priorities)
    if role in FIN:
        for label, icon in [
            ("Penjualan bersih", "sales"),
            ("Laba kotor", "layers"),
            ("Laba bersih", "trend"),
        ]:
            kpis.append(
                (
                    label,
                    idr(metrics[label]),
                    icon,
                    link("/laporan/", jenis="rincian", pos=label, **args),
                    "Selama periode",
                )
            )
        cash_balance = b.balance(
            Entry.objects.filter(account__in=["Bank", "Kas"], doc__date__lte=end)
        )
        kpis.append(
            (
                "Kas & bank",
                idr(cash_balance),
                "wallet",
                link("/laporan/", jenis="dana", akun="kas-bank", **args),
                "Saldo per " + end.strftime("%d/%m"),
            )
        )
    else:
        for kind in SCOPES[role][:3]:
            kpis.append(
                (
                    kind,
                    str(docs.filter(kind=kind).count()),
                    "doc",
                    link("/dokumen/", jenis=kind, **args),
                    "Dokumen periode ini",
                )
            )
    if role in SALES:
        late = [
            v for d, v in outstanding("Piutang", end) if v > 0 and d.due and d.due < end
        ]
        alerts.append(
            (
                "receipt",
                "Piutang lewat tempo",
                idr(sum(late)),
                str(len(late)) + " faktur",
                link("/laporan/", jenis="piutang", tunggak=1, **args),
            )
        )
    if role in WARE:
        alerts.append(
            (
                "box",
                "Risiko kehabisan stok",
                str(risk) + " produk",
                "Estimasi 28 hari",
                link("/pengisian/", risiko=1, **args),
            )
        )
    alerts.append(
        (
            "truck",
            "Menunggu pengiriman",
            str(pending) + " dokumen",
            "Draf dalam periode",
            link("/dokumen/", alur="pengiriman", status="Draf", **args),
        )
    )
    prompt = {
        "Penjualan": ("Buat faktur", "/buat/?jenis=Penjualan"),
        "Gudang": ("Catat penerimaan", "/buat/?jenis=Penerimaan"),
        "Keuangan": ("Catat mutasi", "/dana/"),
    }.get(role)
    return render(
        request,
        "home.html",
        {
            "title": "Ringkasan operasional",
            "start": start,
            "end": end,
            "kpis": kpis,
            "chart": chart,
            "recent": docs[:6],
            "alerts": alerts,
            "prompt": prompt,
            "priorities": sorted(
                priorities, key=lambda r: (r["risk"] != "Berisiko", r["class"])
            )[:5],
            "risk_count": sum(r["risk"] == "Berisiko" for r in priorities),
        },
    )


@gate(*OPER)
def documents(request):
    start, end = dates(request)
    q = visible(request.user).filter(date__range=(start, end))
    flow = request.GET.get("alur", "")
    groups = {
        "pesanan": ("Pesanan", ["Penjualan"]),
        "pembelian": ("Pembelian", ["Penerimaan", "Retur pemasok"]),
        "pengiriman": ("Pengiriman", ["Penjualan"]),
        "retur": ("Retur", ["Retur", "Retur pemasok"]),
    }
    title = "Dokumen transaksi"
    if flow in groups:
        title, kinds = groups[flow]
        q = q.filter(kind__in=kinds)
    if request.GET.get("jenis"):
        q = q.filter(kind=request.GET["jenis"])
    if request.GET.get("status"):
        q = q.filter(status=request.GET["status"])
    if request.GET.get("mitra"):
        q = q.filter(party_id=request.GET["mitra"])
    if request.GET.get("q"):
        term = request.GET["q"].strip()
        num = term.upper().removeprefix("DPM-")
        q = (
            q.filter(pk=int(num))
            if num.isdigit()
            else q.filter(party__name__icontains=term)
        )
    headers = ["Nomor", "Tanggal", "Jenis", "Mitra", "Status"]
    rows = []
    if flow == "pesanan":
        headers = [
            "Faktur / draf",
            "Pelanggan",
            "Tanggal",
            "Pembayaran",
            "Jatuh tempo",
            "Status",
        ]
    elif flow == "pengiriman":
        headers = ["Dokumen", "Tujuan", "Tanggal", "Muatan", "Status serah terima"]
        q = q.prefetch_related("lines__product")
    for d in q.order_by("-date", "-id"):
        path = doc_url(d)
        cells = [str(d), d.date, d.kind, d.party or "Internal", d.status]
        if flow == "pesanan":
            cells = [str(d), d.party, d.date, d.terms, d.due or "—", d.status]
        elif flow == "pengiriman":
            units = {}
            for line in d.lines.all():
                unit = line.product.unit
                units[unit] = units.get(unit, 0) + line.qty
            load = ", ".join(f"{qty} {unit}" for unit, qty in units.items())
            state = {"Draf": "Menunggu penyerahan", b.POSTED: "Diserahkan"}.get(
                d.status, d.status
            )
            cells = [str(d), d.party, d.date, load, state]
            if d.status == b.POSTED:
                path += "surat-jalan/"
        rows.append(row(cells, path))
    return table(
        request,
        title,
        headers,
        rows,
        start=start,
        end=end,
        actions=[
            item
            for item in actions(request.user.role)
            if not flow
            or (flow == "pesanan" and item[0] == "Buat faktur")
            or (flow == "pembelian" and item[0] == "Penerimaan")
            or (flow == "retur" and item[0].startswith("Retur"))
        ],
        search=True,
        statuses=["Draf", "Dibukukan", "Dibatalkan", "Dikoreksi"],
    )


def actions(role):
    return {
        "Gudang": [
            (k, link("/buat/", jenis=k))
            for k in ("Penerimaan", "Retur", "Retur pemasok", "Opname")
        ],
        "Penjualan": [("Buat faktur", "/buat/?jenis=Penjualan")],
        "Keuangan": [("Catat mutasi", "/dana/"), ("Saldo awal", "/pembukaan/")],
    }.get(role, [])


@gate("Gudang", "Penjualan")
def create(request):
    kind = request.GET.get("jenis", "Penjualan")
    request.document_kind = kind
    b.require(request.user, "Penjualan" if kind == "Penjualan" else "Gudang")
    b.check(
        kind in ("Penerimaan", "Penjualan", "Retur", "Opname", "Retur pemasok"),
        "Jenis tidak valid.",
    )
    if request.method == "POST":
        f = request.POST

        def param(name, i):
            vals = f.getlist(name)
            return vals[i] if i < len(vals) else ""

        rows = [
            {
                key: param(key, i)
                for key in (
                    "product",
                    "qty",
                    "conversion",
                    "price",
                    "discount",
                    "direction",
                    "damaged",
                )
            }
            for i, p in enumerate(f.getlist("product"))
            if p
        ]
        d = b.draft(
            request.user,
            kind,
            f.get("day"),
            Party.objects.filter(pk=f.get("party") or None).first(),
            rows,
            token=f.get("token"),
            due=f.get("due"),
            terms=f.get("terms", "Tempo"),
            note=f.get("note", ""),
            ref=Doc.objects.filter(pk=f.get("ref") or None).first(),
        )
        messages.success(request, f"Draf {d} tersimpan.")
        return redirect(doc_url(d))
    return render(
        request,
        "create.html",
        {
            "title": "Buat " + kind.lower(),
            "kind": kind,
            "products": Product.objects.all(),
            "conversions": Conversion.objects.select_related("product"),
            "price_tiers": list(
                Tier.objects.order_by("-minimum").values(
                    "product_id", "minimum", "price"
                )
            )
            if kind == "Penjualan"
            else [],
            "parties": Party.objects.filter(
                kind="Pemasok" if kind == "Penerimaan" else "Pelanggan"
            ),
            "origins": Doc.objects.filter(
                kind="Penerimaan" if kind == "Retur pemasok" else "Penjualan",
                status=b.POSTED,
            ),
            "token": uuid4().hex,
        },
    )


@gate(*OPER)
def detail(request, pk):
    d = get_object_or_404(visible(request.user), pk=pk)
    request.document_kind = d.kind
    can_book = d.status == "Draf" and request.user.role == (
        "Gudang"
        if d.kind == "Penjualan"
        else "Pemilik"
        if d.kind == "Saldo awal"
        else "Keuangan"
    )
    if request.method == "POST":
        f = request.POST
        if f.get("action") == "reverse":
            return redirect(doc_url(b.reverse(request.user, pk, f.get("reason", ""))))
        if f.get("action") == "cancel":
            with transaction.atomic():
                d = Doc.objects.get(pk=pk)
                b.require(
                    request.user,
                    "Penjualan"
                    if d.kind == "Penjualan"
                    else "Pemilik"
                    if d.kind == "Saldo awal"
                    else "Gudang",
                )
                b.editable(d.date)
                b.check(
                    d.status == "Draf" and f.get("reason", "").strip(),
                    "Alasan pembatalan draf diperlukan.",
                )
                d.status = "Dibatalkan"
                d.save(update_fields=["status"])
                b.audit(request.user, "Batalkan draf", d, f["reason"])
        else:
            if not can_book:
                b.require(
                    request.user,
                    "Gudang"
                    if d.kind == "Penjualan"
                    else "Pemilik"
                    if d.kind == "Saldo awal"
                    else "Keuangan",
                )
                raise ValidationError("Dokumen sudah diproses.")
            rows = {
                str(l.pk): {
                    k: f.get(f"{k}_{l.pk}")
                    for k in ("qty", "price", "freight", "unload")
                }
                for l in d.lines.all()
            }
            b.book(
                request.user,
                pk,
                f.get("day"),
                rows,
                freight=f.get("freight") or 0,
                unload=f.get("unload") or 0,
                proof=f.get("proof", ""),
                fund=f.get("fund", ""),
                freight_proof=f.get("freight_proof", ""),
                unload_proof=f.get("unload_proof", ""),
            )
        messages.success(request, f"Status dokumen {d} diperbarui.")
        return redirect(doc_url(d))
    return render(
        request,
        "detail.html",
        {
            "title": "Surat jalan"
            if request.GET.get("cetak") and d.kind == "Penjualan"
            else str(d),
            "doc": d,
            "lines": d.lines.select_related("product"),
            "can_book": can_book,
            "pricing": request.user.role in SALES,
            "entries": Entry.objects.filter(doc=d) if request.user.role in FIN else [],
            "funds": b.FUNDS,
            "cancel": d.status == "Draf"
            and request.user.role
            == ("Penjualan" if d.kind == "Penjualan" else "Gudang"),
        },
    )


@gate("Keuangan")
def money(request):
    form = CashForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        for key in ("ref", "advance"):
            data[key] = Doc.objects.filter(pk=data[key] or None).first()
        d = b.cash(request.user, **data, token=request.POST.get("token"))
        messages.success(request, f"Mutasi {d} telah dibukukan.")
        return redirect(doc_url(d))
    return render(
        request,
        "form.html",
        {"title": "Catat mutasi dana", "form": form, "token": uuid4().hex},
    )


@gate(*WARE)
def inventory(request):
    start, end = dates(request)
    if request.GET.get("produk"):
        p = get_object_or_404(Product, pk=request.GET["produk"])
        prev = b.stock(p, start - timedelta(days=1))[0]
        rows = [row(["Saldo awal", start, "", prev, p.unit])]
        for m in Movement.objects.filter(
            product=p, doc__date__range=(start, end)
        ).select_related("doc"):
            prev += m.qty
            url = (
                ""
                if request.user.role == "Gudang" and m.doc.kind == "Saldo awal"
                else doc_url(m.doc)
            )
            rows.append(row([str(m.doc), m.doc.date, m.qty, prev, p.unit], url))
        return table(
            request,
            "Kartu stok · " + p.code,
            ["Dokumen", "Tanggal", "Gerakan", "Saldo", "Satuan"],
            rows,
            start=start,
            end=end,
        )
    rows = []
    for p in Product.objects.filter(since__lte=end):
        qty, value = b.stock(p, end)
        cells = [p.code, str(p), qty, p.unit]
        if request.user.role in FIN:
            cells.append(idr(value))
        rows.append(row(cells, link("/stok/", produk=p.pk, awal=start, akhir=end)))
    return table(
        request,
        "Stok & Gudang",
        ["Kode", "Varian produk", "Stok tersedia", "Satuan"]
        + (["Nilai persediaan"] if request.user.role in FIN else []),
        rows,
        start=start,
        end=end,
        tabs=[
            ("Persediaan", "/stok/"),
            ("Analisis ABC dan risiko", "/analisis/"),
            ("Kelengkapan hari", "/hari/"),
        ],
    )


@gate(*WARE)
def mining(request):
    start, end = dates(request)
    result = analysis(start, end, request.user.role)
    if request.path.startswith("/api/"):
        data = [
            {
                **r,
                "product": r["product"].code,
                "unit": r["product"].unit,
                **({"ids": sorted(r["ids"])} if "ids" in r else {}),
            }
            for r in result["rows"]
        ]
        return JsonResponse({**result, "rows": data, "start": start, "end": end})
    return render(
        request,
        "mining.html",
        dict(title="Analisis persediaan", start=start, end=end, **result),
    )


@gate(*SALES)
def reports(request):
    start, end = dates(request)
    kind = request.GET.get("jenis", "laba" if request.user.role in FIN else "piutang")
    if kind not in ("piutang", "penjualan", "pelanggan", "rincian-jual"):
        b.require(request.user, *FIN)
    args = {"awal": start, "akhir": end}
    rows = []

    def add(values, url=""):
        rows.append(row(values, url))

    q = Entry.objects.filter(doc__date__range=(start, end)).select_related(
        "doc__party", "product"
    )
    if kind == "laba":
        title = "Laporan laba rugi"
        prior_end = start.replace(day=1) - timedelta(days=1)
        prior_start = prior_end.replace(day=1)
        totals = actuals(start, end)
        prior = actuals(prior_start, prior_end)
        headers = [
            "Pos laporan",
            "Periode pilihan (Rp)",
            f"Bulan {prior_start:%m/%Y} (Rp)",
        ]
        for label, amt in totals.items():
            add(
                [label, amt, prior[label]],
                link("/laporan/", jenis="rincian", pos=label, **args),
            )
            rows[-1]["prior_url"] = link(
                "/laporan/",
                jenis="rincian",
                pos=label,
                awal=prior_start,
                akhir=prior_end,
            )
    elif kind == "rincian":
        pos = request.GET.get("pos", "Penjualan bersih")
        rule = METRICS.get(pos)
        b.check(rule, "Pos tidak dikenal.")
        title = "Rincian · " + pos
        headers = ["Dokumen", "Tanggal", "Akun", "Produk", "Nilai (Rp)"]
        for e in q.filter(account__in=rule):
            add(
                [
                    str(e.doc),
                    e.doc.date,
                    e.account,
                    e.product.code if e.product else "—",
                    e.amount * rule[e.account],
                ],
                doc_url(e.doc),
            )
    elif kind in ("piutang", "utang", "uang muka"):
        account = {"piutang": "Piutang", "utang": "Utang", "uang muka": "Uang muka"}[
            kind
        ]
        title = account + " per dokumen"
        if account == "Piutang" and request.GET.get("tunggak") == "1":
            title = "Piutang lewat jatuh tempo"
        headers = ["Dokumen", "Mitra", "Tanggal", "Jatuh tempo", "Saldo (Rp)", "Status"]
        for d, v in outstanding(account, end):
            if request.GET.get("tunggak") == "1" and not (
                v > 0 and d.due and d.due < end
            ):
                continue
            initial = abs(
                b.balance(Entry.objects.filter(doc=d, item=d, account=account))
            )
            state = "Lunas" if v == 0 else ("Sebagian" if v < initial else "Terbuka")
            if d.due and d.due < end and v:
                state += " · Lewat tempo"
            add([str(d), d.party.name, d.date, d.due or "—", v, state], doc_url(d))
    elif kind == "dana":
        title = "Mutasi kas dan bank"
        headers = [
            "Akun",
            "Tanggal",
            "Dokumen",
            "Masuk (Rp)",
            "Keluar (Rp)",
            "Saldo (Rp)",
        ]
        for fund in (
            ["Kas", "Bank"] if request.GET.get("akun") == "kas-bank" else b.FUNDS
        ):
            running = b.balance(Entry.objects.filter(account=fund, doc__date__lt=start))
            add([fund, start, "Saldo awal", 0, 0, running])
            for e in q.filter(account=fund).order_by("doc__date", "id"):
                running += e.amount
                add(
                    [
                        fund,
                        e.doc.date,
                        str(e.doc),
                        max(0, e.amount),
                        max(0, -e.amount),
                        running,
                    ],
                    doc_url(e.doc),
                )
    elif kind in ("penjualan", "pelanggan"):
        by_product = kind == "penjualan"
        title = "Penjualan per " + ("produk" if by_product else "pelanggan")
        headers = ["Produk" if by_product else "Pelanggan", "Penjualan bersih (Rp)"]
        totals = {}
        for e in q.filter(account__in=METRICS["Penjualan bersih"]):
            k = (
                (e.product_id, e.product.code)
                if by_product
                else (e.doc.party_id, e.doc.party.name)
            )
            totals[k] = totals.get(k, 0) - e.amount
        for (pk, name), val in sorted(totals.items(), key=lambda item: item[0][1]):
            add(
                [name, val],
                link("/laporan/", jenis="rincian-jual", grup=kind, id=pk, **args),
            )
    elif kind == "rincian-jual":
        title = "Rincian penjualan"
        headers = ["Dokumen", "Tanggal", "Nilai bersih (Rp)"]
        filters = {
            "product_id"
            if request.GET.get("grup") == "penjualan"
            else "doc__party_id": request.GET.get("id")
        }
        for e in q.filter(account__in=METRICS["Penjualan bersih"], **filters):
            add([str(e.doc), e.doc.date, -e.amount], doc_url(e.doc))
    else:
        raise Http404
    if request.path.startswith("/api/"):
        return JsonResponse({"judul": title, "kolom": headers, "baris": rows})
    for report_row in rows:
        report_row["report"] = True
    if request.GET.get("ekspor") == "xlsx":
        return export(request, title, headers, rows, start, end)
    tabs = [
        ("Piutang", "piutang"),
        ("Per produk", "penjualan"),
        ("Per pelanggan", "pelanggan"),
    ]
    if request.user.role in FIN:
        tabs = [
            ("Laba rugi", "laba"),
            *tabs,
            ("Utang", "utang"),
            ("Kas & bank", "dana"),
            ("Uang muka", "uang muka"),
        ]
    params = request.GET.copy()
    params["ekspor"] = "xlsx"
    return table(
        request,
        title,
        headers,
        rows,
        start=start,
        end=end,
        tabs=[(name, link("/laporan/", jenis=k, **args)) for name, k in tabs],
        actions=(
            [("Catat mutasi", "/dana/")]
            if kind in ("dana", "piutang", "utang") and request.user.role == "Keuangan"
            else []
        )
        + [("Ekspor Excel", "?" + params.urlencode())],
    )


def export(request, title, headers, rows, start, end):
    wb = Workbook()
    ws = wb.active
    ws.title = "Laporan"
    ws.append(
        [title, "Data demo sintetis" if settings.DEMO else "CV Dhana Putra Mandiri"]
    )
    ws.append(["Mulai", start, "Sampai", end])
    ws.append(headers)
    for cell in ws[3]:
        cell.font = Font(bold=True, color="00775B")
    for r in rows:
        ws.append(r["cells"])
        for c in ws[ws.max_row]:
            if isinstance(c.value, str):
                c.data_type = "s"
            elif isinstance(c.value, int):
                c.number_format = "#,##0;[Red](#,##0);0"
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = min(
            56, max(15, max(len(str(c.value or "")) for c in col) + 2)
        )
    ws.freeze_panes = "B4"
    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="laporan-{end}.xlsx"'
    wb.save(response)
    b.audit(request.user, "Ekspor Excel", title, f"{start} - {end}")
    return response


@gate("Admin", "Pemilik")
def master(request):
    key = request.GET.get("jenis", "produk")
    if key not in MASTERS:
        raise Http404
    title, cls = MASTERS[key]
    writable = request.user.role == "Admin"
    if not writable:
        b.check(key != "pegawai", "Pengelolaan pegawai khusus admin.")
        if (
            request.method != "GET"
            or request.GET.get("edit")
            or request.GET.get("baru")
        ):
            b.require(request.user, "Admin")
    model = cls._meta.model
    tabs = [
        (v[0], link("/master/", jenis=k))
        for k, v in MASTERS.items()
        if writable or k != "pegawai"
    ]
    if request.GET.get("edit") or request.GET.get("baru"):
        with transaction.atomic():
            obj = (
                get_object_or_404(model, pk=request.GET["edit"])
                if request.GET.get("edit")
                else None
            )
            original_user = obj.username if isinstance(obj, Employee) else None
            form = cls(request.POST or None, instance=obj)
            if request.method == "POST" and form.is_valid():
                record = form.save(commit=False)
                if isinstance(record, Employee):
                    b.check(
                        not obj or record.username == original_user,
                        "Alamat identitas lama tidak dapat dialihkan. Buat undangan baru.",
                    )
                    b.check(
                        record.pk != request.user.pk
                        or (record.role == "Admin" and record.is_active),
                        "Pertahankan akses admin sendiri.",
                    )
                    if not obj:
                        record.set_unusable_password()
                if obj and isinstance(obj, Product) and obj.line_set.exists():
                    b.check(
                        not form.changed_data,
                        "Definisi SKU yang telah dipakai terkunci. Buat varian baru.",
                    )
                if obj and isinstance(obj, Party) and obj.doc_set.exists():
                    b.check(
                        "kind" not in form.changed_data,
                        "Jenis mitra memiliki dokumen aktif.",
                    )
                if isinstance(record, Lead):
                    b.editable(record.day)
                    if obj:
                        b.check(
                            not form.changed_data,
                            "Tambahkan waktu tunggu dengan tanggal efektif baru.",
                        )
                record.save()
                b.audit(
                    request.user,
                    "Simpan master " + key,
                    record.pk,
                    ", ".join(form.changed_data),
                )
                return redirect(link("/master/", jenis=key))
        return render(
            request,
            "form.html",
            {"title": ("Ubah " if obj else "Tambah ") + title.lower(), "form": form},
        )
    fields = cls._meta.fields
    labels = [cls.base_fields[f].label for f in fields]
    rows = [
        row(
            [getattr(o, f) for f in fields],
            link("/master/", jenis=key, edit=o.pk) if writable else "",
        )
        for o in model.objects.all()
    ]
    return table(
        request,
        title,
        labels,
        rows,
        tabs=tabs,
        actions=[("Tambah data", link("/master/", jenis=key, baru=1))]
        if writable
        else [],
    )


def recon(end):
    entries = Entry.objects.filter(doc__date__lte=end)
    return {
        a: b.balance(entries.filter(account=a)) * (-1 if a == "Utang" else 1)
        for a in [*b.FUNDS, "Piutang", "Utang", "Persediaan"]
    }


@gate(*FIN)
def periods(request):
    month = (
        request.POST.get("month")
        or request.GET.get("bulan")
        or timezone.localdate().strftime("%Y-%m")
    )
    first = date.fromisoformat(month + "-01")
    end = first.replace(day=monthrange(first.year, first.month)[1])
    balances = recon(end)
    if request.method == "POST":
        with transaction.atomic():
            p, _ = Period.objects.get_or_create(month=month)
            action = request.POST.get("action")
            reason = request.POST.get("note", "").strip()
            b.check(reason, "Isi catatan rekonsiliasi atau alasan.")
            if action == "ajukan":
                b.require(request.user, "Keuangan")
                b.check(
                    end <= timezone.localdate() and p.status == "Terbuka",
                    "Bulan belum selesai atau sudah diajukan.",
                )
                balances = recon(end)
                for k, expected in balances.items():
                    b.check(
                        int(request.POST.get(k, "")) == expected,
                        "Selisih rekonsiliasi pada "
                        + k
                        + ". Periksa dan koreksi sebelum tutup buku.",
                    )
                b.check(
                    not Doc.objects.filter(
                        date__range=(first, end), status="Draf"
                    ).exists(),
                    "Masih ada dokumen draf pada periode ini.",
                )
                p.status = "Diajukan"
                reason += " | " + ", ".join(
                    k + "=" + str(v) for k, v in balances.items()
                )
            elif action == "tutup":
                b.require(request.user, "Pemilik")
                b.check(p.status == "Diajukan", "Periode harus diajukan oleh keuangan.")
                p.status = "Ditutup"
            elif action == "buka":
                b.require(request.user, "Pemilik")
                b.check(p.status != "Terbuka", "Periode sudah terbuka.")
                p.status = "Terbuka"
            else:
                raise Http404
            p.note = reason
            p.save()
            b.audit(request.user, "Periode " + p.status, month, reason)
        return redirect(link("/periode/", bulan=month))
    return render(
        request,
        "period.html",
        {
            "title": "Rekonsiliasi dan tutup buku",
            "month": month,
            "balances": balances,
            "period": Period.objects.filter(month=month).first(),
            "events": Audit.objects.filter(document=month).order_by("-id"),
        },
    )


@gate("Gudang", *FIN)
def days(request):
    if request.method == "POST":
        b.require(request.user, "Gudang")
        with transaction.atomic():
            d = b.as_day(request.POST.get("day"))
            b.check(
                d < timezone.localdate(), "Konfirmasi setelah hari kalender selesai."
            )
            b.editable(d)
            ok = request.POST.get("complete") == "1"
            Day.objects.update_or_create(day=d, defaults={"complete": ok})
            b.audit(
                request.user,
                "Pencatatan lengkap" if ok else "Pencatatan belum lengkap",
                d,
            )
        return redirect("/hari/")
    return render(
        request,
        "days.html",
        {"title": "Kelengkapan hari", "days": Day.objects.order_by("-day")[:90]},
    )


@gate(*FIN)
def trail(request):
    start, end = dates(request)
    return table(
        request,
        "Jejak aktivitas",
        ["Waktu WIB", "Pegawai", "Aktivitas", "Dokumen", "Alasan"],
        [
            row(
                [
                    timezone.localtime(a.time).strftime("%d/%m %H:%M"),
                    a.actor.first_name,
                    a.action,
                    a.document,
                    a.reason,
                ]
            )
            for a in Audit.objects.filter(time__date__range=(start, end))
            .select_related("actor")
            .order_by("-id")
        ],
        start=start,
        end=end,
    )


@gate("Keuangan")
def opening(request):
    if request.method == "POST":
        f = request.POST
        doc = b.opening(
            request.user,
            f["day"],
            f["account"],
            f["amount"],
            party=Party.objects.filter(pk=f.get("party") or None).first(),
            product=Product.objects.filter(pk=f.get("product") or None).first(),
            qty=f.get("qty"),
            due=f.get("due"),
            proof=f["proof"],
            token=f["token"],
        )
        return redirect(doc_url(doc))
    return render(
        request,
        "opening.html",
        {
            "title": "Ajukan saldo awal",
            "accounts": [*b.FUNDS, "Piutang", "Utang", "Persediaan"],
            "parties": Party.objects.all(),
            "products": Product.objects.all(),
            "token": uuid4().hex,
        },
    )


@gate(*OPER)
def dispatch(request, pk):
    d = get_object_or_404(
        visible(request.user), pk=pk, kind="Penjualan", status=b.POSTED
    )
    return render(
        request,
        "dispatch.html",
        {"title": "Surat jalan", "doc": d, "lines": d.lines.select_related("product")},
    )
