"""Pembukuan hanya melalui layanan atomik ini, termasuk ketika dipanggil oleh perintah lokal."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from uuid import uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import (
    Audit,
    Conversion,
    CostProof,
    Day,
    Doc,
    Entry,
    Line,
    Movement,
    Opening,
    Period,
    Product,
    Tier,
)

FUNDS = ["Bank", "Kas", "Perantara"]
EXPENSES = [
    "Distribusi dan pemasaran",
    "Tenaga kerja",
    "Administrasi dan umum",
    "Beban usaha lainnya",
    "Beban nonoperasional",
    "Pajak",
]
INCOMES = ["Pendapatan operasional lain", "Pendapatan nonoperasional"]
FINANCE = ("Keuangan", "Pemilik")
POSTED = "Dibukukan"


def require(user, *roles):
    if not user.is_active or user.role not in roles:
        raise PermissionDenied


def check(ok, message):
    if not ok:
        raise ValidationError(message)


def integer(value, minimum=0):
    try:
        n = int(str(value))
    except (ValueError, TypeError):
        raise ValidationError("Masukkan bilangan bulat.")
    check(minimum <= n <= 10**14, "Nilai di luar batas.")
    return n


def as_day(value):
    try:
        d = date.fromisoformat(str(value))
    except ValueError:
        raise ValidationError("Tanggal tidak valid.")
    check(d <= timezone.localdate(), "Tanggal pembukuan melewati hari ini.")
    return d


def editable(d):
    check(
        not Period.objects.filter(
            month__gte=str(d)[:7], status__in=["Ditutup", "Diajukan"]
        ).exists(),
        "Periode atau saldo bulan berikutnya dikunci. Pemilik perlu membuka kembali dengan alasan.",
    )


def audit(user, action, document, reason=""):
    Audit.objects.create(
        actor=user, action=action, document=str(document), reason=reason[:400]
    )


def balance(qs, column="amount"):
    return qs.aggregate(total=Sum(column))["total"] or 0


def stock(product, until=None):
    q = Movement.objects.filter(product=product)
    if until:
        q = q.filter(doc__date__lte=until)
    a = q.aggregate(q=Sum("qty"), v=Sum("value"))
    return a["q"] or 0, a["v"] or 0


def part(value, qty, total):
    return int(
        (Decimal(value) * qty / total).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    )


def post(doc, account, amount, item=None, product=None):
    if amount:
        check(abs(amount) <= 10**15, "Nilai pembukuan melebihi batas per baris.")
        Entry.objects.create(
            doc=doc, account=account, amount=amount, item=item, product=product
        )


def movement(doc, p, qty, val):
    check(abs(val) <= 10**15, "Nilai gerakan melampaui batas per baris.")
    check(
        not Movement.objects.filter(product=p, doc__date__gt=doc.date).exists(),
        "Sudah ada gerakan produk setelah tanggal ini. Gunakan koreksi bertanggal berjalan.",
    )
    check(stock(p)[0] + qty >= 0, f"Stok {p.code} tidak mencukupi.")
    Movement.objects.create(doc=doc, product=p, qty=qty, value=val)
    post(doc, "Persediaan", val, product=p)


def finish(doc, user):
    if doc.kind != "Saldo awal":
        check(
            not Doc.objects.filter(kind="Saldo awal", status="Draf").exists(),
            "Pemilik perlu memutuskan saldo awal sebelum transaksi pertama.",
        )
    check(balance(Entry.objects.filter(doc=doc)) == 0, "Jurnal tidak seimbang.")
    doc.status = POSTED
    doc.save()
    if doc.kind == "Penjualan" or (
        doc.kind == "Pembatalan" and doc.ref.kind == "Penjualan"
    ):
        Day.objects.filter(day=doc.date, complete=True).update(complete=False)
    audit(user, "Pembukuan " + doc.kind, doc, doc.note)


def unique_token(token):
    token = str(token or uuid4())
    check(
        len(token) <= 64 and not Doc.objects.filter(token=token).exists(),
        "Permintaan ini sudah tersimpan.",
    )
    return token


def reserve_proof(doc, code, purpose):
    code = code.strip().upper()
    check(0 < len(code) <= 80, "Nomor bukti harus berisi 1–80 karakter.")
    check(
        not Doc.objects.filter(proof=code).exclude(pk=doc.pk).exists(),
        "Nomor bukti telah digunakan pada dokumen lain.",
    )
    proof, new = CostProof.objects.get_or_create(
        code=code, defaults={"doc": doc, "purpose": purpose}
    )
    check(proof.doc_id == doc.pk, "Bukti biaya ini telah dibukukan.")
    if not new and purpose not in proof.purpose.split(", "):
        proof.purpose += ", " + purpose
        proof.save(update_fields=["purpose"])


@transaction.atomic
def draft(
    user,
    kind,
    day,
    party,
    rows,
    *,
    token=None,
    due=None,
    terms="Tempo",
    note="",
    ref=None,
):
    allowed = {
        "Penerimaan": "Gudang",
        "Penjualan": "Penjualan",
        "Retur": "Gudang",
        "Opname": "Gudang",
        "Retur pemasok": "Gudang",
    }
    check(kind in allowed, "Jenis dokumen tidak dikenal.")
    require(user, allowed[kind])
    day = as_day(day)
    editable(day)
    check(bool(rows), "Tambahkan sedikitnya satu baris.")
    if kind in ("Retur", "Retur pemasok"):
        if ref:
            ref = Doc.objects.get(pk=ref.pk)
        origin = "Penjualan" if kind == "Retur" else "Penerimaan"
        check(
            ref and ref.kind == origin and ref.status == POSTED and ref.date <= day,
            "Dokumen asal tidak sah.",
        )
        party = ref.party
    if kind != "Opname":
        required = "Pemasok" if kind in ("Penerimaan", "Retur pemasok") else "Pelanggan"
        check(party and party.kind == required, "Pilih mitra yang sesuai.")
    if kind == "Penjualan":
        check(terms in ["Tunai", "Tempo"], "Pilih syarat pembayaran.")
        if terms == "Tempo":
            try:
                due = date.fromisoformat(str(due))
            except ValueError:
                raise ValidationError("Isi tanggal jatuh tempo.")
            check(due >= day, "Jatuh tempo mendahului faktur.")
        else:
            due = day
    if kind in ("Opname", "Retur", "Retur pemasok"):
        check(bool(note.strip()), "Alasan diperlukan.")
    doc = Doc.objects.create(
        kind=kind,
        date=day,
        party=party,
        ref=ref,
        due=due,
        terms=terms,
        note=note,
        actor=user,
        token=unique_token(token),
    )
    seen = set()
    for row in rows:
        p = Product.objects.get(pk=row["product"])
        check(p.since <= day, "Tanggal mendahului awal pencatatan produk.")
        check(p.pk not in seen, "Gabungkan baris produk yang sama.")
        seen.add(p.pk)
        qty = integer(row["qty"], 1)
        if row.get("conversion"):
            qty *= Conversion.objects.get(pk=row["conversion"], product=p).factor
        check(qty <= 10**9, "Jumlah satuan dasar melampaui batas per baris.")
        price = discount = 0
        if kind == "Penjualan":
            tier = (
                Tier.objects.filter(product=p, minimum__lte=qty)
                .order_by("-minimum")
                .first()
            )
            price = integer(row.get("price") or (tier.price if tier else 0), 1)
            discount = integer(row.get("discount") or 0)
            check(discount <= price * qty, "Diskon melebihi nilai baris.")
        Line.objects.create(
            doc=doc,
            product=p,
            qty=qty,
            price=price,
            discount=discount,
            damaged=kind == "Retur" and bool(row.get("damaged")),
            direction=-1
            if kind == "Opname" and row.get("direction") == "kurang"
            else 1,
        )
    audit(user, "Buat " + kind, doc, note)
    return doc


@transaction.atomic
def book(
    user,
    doc_id,
    day,
    lines,
    *,
    freight=0,
    unload=0,
    proof="",
    fund="",
    freight_proof="",
    unload_proof="",
):
    doc = Doc.objects.get(pk=doc_id)
    require(
        user,
        "Gudang"
        if doc.kind == "Penjualan"
        else "Pemilik"
        if doc.kind == "Saldo awal"
        else "Keuangan",
    )
    check(doc.status == "Draf", "Dokumen sudah diproses.")
    day = as_day(day)
    editable(doc.date)
    editable(day)
    check(day >= doc.date, "Tanggal pembukuan mendahului draf.")
    if not doc.draft_date:
        doc.draft_date = doc.date
    if doc.kind == "Saldo awal":
        check(day == doc.date, "Gunakan tanggal efektif saldo awal.")
        check(
            not Doc.objects.filter(status=POSTED).exclude(kind="Saldo awal").exists(),
            "Pembukuan operasional sudah dimulai.",
        )
        opening = doc.opening
        if opening.account == "Persediaan":
            line = doc.lines.get()
            movement(doc, line.product, line.qty, opening.amount)
            line.cost = opening.amount
            line.save()
            net = opening.amount
        else:
            net = -opening.amount if opening.account == "Utang" else opening.amount
            post(
                doc,
                opening.account,
                net,
                doc if opening.account in ("Piutang", "Utang") else None,
            )
        post(doc, "Ekuitas awal", -net)
        finish(doc, user)
        return doc
    doc.date = day
    if doc.kind == "Penerimaan":
        doc.freight, doc.unload = integer(freight), integer(unload)
        doc.proof = proof.strip().upper() or None
        check(
            doc.proof and not Doc.objects.filter(proof=doc.proof).exists(),
            "Nomor bukti penerimaan harus unik.",
        )
        reserve_proof(doc, doc.proof, "Penerimaan")
        if doc.freight:
            reserve_proof(doc, freight_proof or doc.proof, "Transport")
        if doc.unload:
            reserve_proof(doc, unload_proof or doc.proof, "Bongkar")
        check(fund in ["", *FUNDS], "Akun dana tidak valid.")
    for l in doc.lines.select_related("product"):
        p = l.product
        q, v = stock(p)
        info = lines.get(str(l.pk), {})
        if doc.kind == "Penerimaan":
            l.price = integer(info.get("price"), 1)
            l.freight = integer(info.get("freight") or 0)
            l.unload = integer(info.get("unload") or 0)
            l.cost = l.price * l.qty + l.freight + l.unload
            movement(doc, p, l.qty, l.cost)
            post(doc, fund or "Utang", -l.cost, item=None if fund else doc)
        elif doc.kind == "Penjualan":
            if doc.terms == "Tunai":
                doc.due = day
            check(
                integer(info.get("qty"), 1) == l.qty,
                "Jumlah serah berbeda. Penjualan harus menyesuaikan draf.",
            )
            check(q >= l.qty, "Stok tidak mencukupi.")
            l.cost = part(v, l.qty, q)
            movement(doc, p, -l.qty, -l.cost)
            post(doc, "HPP", l.cost, product=p)
            post(doc, "Penjualan", -l.qty * l.price, product=p)
            post(doc, "Diskon", l.discount, product=p)
            post(doc, "Piutang", l.qty * l.price - l.discount, doc, p)
        elif doc.kind in ("Retur", "Retur pemasok"):
            orig = doc.ref.lines.filter(product=p).first()
            check(orig, "Produk tidak terdapat pada dokumen asal.")
            prior = Line.objects.filter(
                doc__ref=doc.ref, doc__kind=doc.kind, doc__status=POSTED, product=p
            )
            used = balance(prior, "qty")
            check(l.qty + used <= orig.qty, "Jumlah retur melampaui dokumen asal.")
            cost = part(orig.cost, used + l.qty, orig.qty) - part(
                orig.cost, used, orig.qty
            )
            if doc.kind == "Retur":
                total = orig.qty * orig.price - orig.discount
                refund = part(total, used + l.qty, orig.qty) - part(
                    total, used, orig.qty
                )
                ar = max(
                    0,
                    balance(
                        Entry.objects.filter(
                            item=doc.ref, account="Piutang", doc__date__lte=day
                        )
                    ),
                )
                check(
                    not Entry.objects.filter(item=doc.ref, doc__date__gt=day).exists(),
                    "Ada alokasi lebih baru pada faktur.",
                )
                post(doc, "Retur", refund, product=p)
                post(doc, "Piutang", -min(refund, ar), doc.ref)
                post(doc, "Uang muka", -max(0, refund - ar), doc)
                if not l.damaged:
                    movement(doc, p, l.qty, cost)
                    post(doc, "HPP", -cost, product=p)
                l.cost = cost
            else:
                check(q >= l.qty and q > 0, "Stok retur pemasok kurang.")
                removed = part(v, l.qty, q)
                debt = -balance(Entry.objects.filter(item=doc.ref, account="Utang"))
                check(debt >= cost, "Nilai retur melebihi utang terbuka.")
                movement(doc, p, -l.qty, -removed)
                post(doc, "Utang", cost, doc.ref)
                post(doc, "Beban usaha lainnya", removed - cost)
                l.cost = removed
        elif doc.kind == "Opname":
            check(q > 0, "Koreksi memerlukan nilai rata-rata tersedia.")
            change = l.direction * l.qty
            l.cost = part(v, l.qty, q)
            movement(doc, p, change, l.cost * l.direction)
            post(doc, "Beban usaha lainnya", -l.cost * l.direction)
        else:
            raise ValidationError("Jenis pembukuan tidak valid.")
        l.save()
    if doc.kind == "Penerimaan":
        check(
            balance(doc.lines.all(), "freight") == doc.freight
            and balance(doc.lines.all(), "unload") == doc.unload,
            "Jumlah alokasi transport dan bongkar harus sama dengan bukti.",
        )
    finish(doc, user)
    return doc


@transaction.atomic
def cash(
    user,
    kind,
    day,
    amount,
    fund,
    *,
    ref=None,
    advance=None,
    party=None,
    category="",
    target="",
    proof="",
    note="",
    token=None,
):
    require(user, "Keuangan")
    day = as_day(day)
    editable(day)
    amount = integer(amount, 1)
    check(fund in FUNDS, "Akun dana tidak valid.")
    if ref:
        ref = Doc.objects.get(pk=ref.pk)
        check(
            ref.date <= day and ref.status == POSTED,
            "Dokumen acuan belum dibukukan pada tanggal ini.",
        )
        check(
            not Entry.objects.filter(item=ref, doc__date__gt=day).exists(),
            "Terdapat alokasi lebih baru pada dokumen ini.",
        )
        party = ref.party
    proof = proof.strip().upper() or None
    check(
        not proof or not Doc.objects.filter(proof=proof).exists(),
        "Nomor bukti sudah dibukukan.",
    )
    doc = Doc.objects.create(
        kind=kind,
        date=day,
        party=party,
        ref=ref,
        actor=user,
        note=note,
        token=unique_token(token),
        proof=proof,
    )
    if proof:
        reserve_proof(doc, proof, kind)
    debit, credit = fund, None
    debit_item = credit_item = None
    if kind in ("Cicilan", "Alokasi uang muka"):
        check(
            ref
            and ref.kind in ("Penjualan", "Saldo awal")
            and amount <= balance(Entry.objects.filter(item=ref, account="Piutang")),
            "Nilai melampaui piutang terbuka.",
        )
        credit, credit_item = "Piutang", ref
        if kind == "Alokasi uang muka":
            check(
                advance
                and advance.party_id == ref.party_id
                and advance.date <= day
                and not Entry.objects.filter(item=advance, doc__date__gt=day).exists()
                and amount
                <= -balance(Entry.objects.filter(item=advance, account="Uang muka")),
                "Saldo uang muka tidak cukup atau pelanggan berbeda.",
            )
            debit, debit_item = "Uang muka", advance
    elif kind == "Bayar pemasok":
        check(
            ref
            and ref.kind in ("Penerimaan", "Saldo awal")
            and amount <= -balance(Entry.objects.filter(item=ref, account="Utang")),
            "Nilai melampaui utang terbuka.",
        )
        debit, debit_item, credit = "Utang", ref, fund
    elif kind == "Beban":
        check(
            category in EXPENSES and proof,
            "Pilih kelompok beban dan isi nomor bukti unik.",
        )
        debit, credit = category, fund
    elif kind == "Pendapatan lain":
        check(category in INCOMES, "Pilih kelompok pendapatan.")
        credit = category
    elif kind == "Modal":
        credit = "Modal"
    elif kind == "Transfer":
        check(target in FUNDS and target != fund, "Pilih dua akun dana berbeda.")
        debit, credit = target, fund
    elif kind == "Uang muka":
        check(party and party.kind == "Pelanggan", "Pilih pelanggan.")
        credit, credit_item = "Uang muka", doc
    else:
        raise ValidationError("Jenis mutasi tidak valid.")
    post(doc, debit, amount, debit_item)
    post(doc, credit, -amount, credit_item)
    finish(doc, user)
    return doc


@transaction.atomic
def opening(
    user,
    day,
    account,
    amount,
    *,
    party=None,
    product=None,
    qty=0,
    due=None,
    proof="",
    token=None,
):
    require(user, "Keuangan")
    day = as_day(day)
    editable(day)
    check(
        not Doc.objects.filter(status=POSTED).exclude(kind="Saldo awal").exists(),
        "Sudah ada transaksi operasional.",
    )
    check(
        account in [*FUNDS, "Piutang", "Utang", "Persediaan"], "Pilih akun saldo awal."
    )
    check(bool(proof.strip()), "Nomor bukti saldo awal diperlukan.")
    if account in ("Piutang", "Utang"):
        check(
            party
            and party.kind == ("Pelanggan" if account == "Piutang" else "Pemasok"),
            "Mitra harus sesuai jenis tagihan.",
        )
    doc = Doc.objects.create(
        kind="Saldo awal",
        date=day,
        actor=user,
        party=party,
        due=due or None,
        proof=proof.strip().upper(),
        token=unique_token(token),
    )
    Opening.objects.create(doc=doc, account=account, amount=integer(amount, 1))
    if account == "Persediaan":
        check(
            product and product.since <= day,
            "Periksa produk dan tanggal mulai pencatatan.",
        )
        Line.objects.create(doc=doc, product=product, qty=integer(qty, 1))
    audit(user, "Ajukan saldo awal", doc)
    return doc


@transaction.atomic
def reverse(user, pk, reason):
    require(user, "Keuangan")
    original = Doc.objects.get(pk=pk)
    editable(original.date)
    check(
        original.status == POSTED
        and original.kind not in ("Pembatalan", "Saldo awal")
        and bool(reason.strip()),
        "Pilih dokumen aktif dan isi alasan pembatalan.",
    )
    check(
        not Doc.objects.filter(ref=original).exclude(status="Dibatalkan").exists(),
        "Selesaikan ketergantungan dokumen melalui koreksi terkait.",
    )
    entries = list(Entry.objects.filter(doc=original))
    for e in entries:
        if e.item_id:
            check(
                not Entry.objects.filter(item_id=e.item_id, id__gt=e.pk)
                .exclude(doc=original)
                .exists(),
                "Sudah ada alokasi berikutnya.",
            )
    doc = Doc.objects.create(
        kind="Pembatalan",
        date=original.date,
        ref=original,
        party=original.party,
        note=reason,
        actor=user,
        token=unique_token(None),
    )
    for m in Movement.objects.filter(doc=original):
        check(
            not Movement.objects.filter(product=m.product, id__gt=m.pk).exists(),
            "Mutasi stok berikutnya sudah ada. Gunakan retur atau opname.",
        )
        movement(doc, m.product, -m.qty, -m.value)
    for e in entries:
        if e.account != "Persediaan":
            post(doc, e.account, -e.amount, e.item, e.product)
    original.status = "Dikoreksi"
    original.save(update_fields=["status"])
    finish(doc, user)
    return doc
