from collections import defaultdict
from datetime import timedelta

from django.db.models import Max
from django.utils import timezone

from .books import EXPENSES, FINANCE, INCOMES
from .models import Audit, Day, Doc, Entry, Lead, Movement, Product

METRICS = {
    "Penjualan bruto": {"Penjualan": -1},
    "Diskon": {"Diskon": 1},
    "Retur penjualan": {"Retur": 1},
    "Penjualan bersih": {"Penjualan": -1, "Diskon": -1, "Retur": -1},
    "HPP": {"HPP": 1},
}
METRICS["Laba kotor"] = {**METRICS["Penjualan bersih"], "HPP": -1}
for name in EXPENSES:
    METRICS[name] = {name: 1}
for name in INCOMES:
    METRICS[name] = {name: -1}
METRICS["Laba bersih"] = {
    **METRICS["Laba kotor"],
    **{a: -1 for a in EXPENSES + INCOMES},
}


def actuals(start, end):
    totals = defaultdict(int)
    for account, amount in Entry.objects.filter(
        doc__date__range=(start, end)
    ).values_list("account", "amount"):
        totals[account] += amount
    return {
        name: sum(totals[a] * sign for a, sign in rule.items())
        for name, rule in METRICS.items()
    }


def analysis(start, end, role):
    cutoff = min(end, timezone.localdate() - timedelta(days=1))
    begin = cutoff - timedelta(days=27)
    # Paling baru, gunakan tujuh hari yang telah selesai sebagai set uji terpisah.
    eval_cutoff = min(cutoff, timezone.localdate() - timedelta(days=8))
    eval_begin = eval_cutoff - timedelta(days=27)
    horizon = eval_cutoff + timedelta(days=7)
    complete = set(
        Day.objects.filter(
            complete=True, day__range=(eval_begin, max(horizon, cutoff))
        ).values_list("day", flat=True)
    )
    history = [begin + timedelta(days=i) for i in range(28)]
    training = [eval_begin + timedelta(days=i) for i in range(28)]
    future = [eval_cutoff + timedelta(days=i) for i in range(1, 8)]
    prods = list(Product.objects.filter(since__lte=end))
    records = {
        p.id: {
            "product": p,
            "stock": 0,
            "usage": 0,
            "ids": set(),
            "daily": defaultdict(int),
            "changes": defaultdict(list),
        }
        for p in prods
    }
    for m in (
        Movement.objects.filter(
            product_id__in=records, doc__date__lte=max(end, horizon)
        )
        .select_related("doc__ref")
        .order_by("doc__date", "pk")
    ):
        r = records[m.product_id]
        d = m.doc.date
        if d <= end:
            r["stock"] += m.qty
        if d <= horizon:
            r["changes"][d].append(m.qty)
        source = m.doc.ref.kind if m.doc.kind == "Pembatalan" else m.doc.kind
        if source == "Penjualan":
            r["daily"][d] -= m.qty
        if start <= d <= end and source in ("Penjualan", "Retur"):
            r["usage"] -= m.value
            r["ids"].add(m.doc_id)
    ranked = sorted(records.values(), key=lambda r: (-r["usage"], r["product"].code))
    total = sum(max(0, r["usage"]) for r in ranked)
    cumulative = 0
    grade = "A"
    for r in ranked:
        usage = r["usage"]
        r["class"] = "Tinjau" if usage <= 0 else grade
        if usage > 0:
            cumulative += usage
            if grade == "A" and cumulative * 100 >= total * 80:
                grade = "B"
            elif grade == "B" and cumulative * 100 >= total * 95:
                grade = "C"
        r["share"] = 100 * max(0, usage) / total if total else 0
        r["cumulative"] = 100 * cumulative / total if total else 0
        p = r["product"]
        lead = Lead.objects.filter(product=p, day__lte=end).order_by("-day").first()
        r["lead"] = lead.days if lead else None
        r["missing"] = sum(d not in complete or d < p.since for d in history)
        opening = sum(sum(changes) for d, changes in r["changes"].items() if d < begin)
        outages = 0
        for d in history:
            levels = [opening]
            for n in r["changes"][d]:
                levels.append(levels[-1] + n)
            opening = levels[-1]
            outages += d >= p.since and min(levels) <= 0
        r.update(
            outages=outages, rate=None, coverage=None, mae=None, risk="Data belum cukup"
        )
        if not r["missing"]:
            rate = sum(r["daily"][d] for d in history) / 28
            r["rate"] = rate
            if rate:
                r["coverage"] = r["stock"] / rate
                r["risk"] = (
                    "Isi waktu tunggu"
                    if lead is None
                    else ("Berisiko" if r["coverage"] < lead.days else "Cukup")
                )
            else:
                r["risk"] = "Belum ada laju permintaan"
        if p.since <= eval_begin and all(d in complete for d in training + future):
            prior_rate = sum(r["daily"][d] for d in training) / 28
            r["mae"] = sum(abs(r["daily"][d] - prior_rate) for d in future) / 7
        for key in ("daily", "changes"):
            r.pop(key)
        if role not in FINANCE:
            for key in ("usage", "share", "cumulative", "ids"):
                r.pop(key)
    if role not in FINANCE:
        ranked.sort(key=lambda r: (r["class"], r["product"].code))
    changes = Audit.objects.exclude(
        action__in=["Login demo", "Login OIDC", "Logout", "Ekspor Excel"]
    )
    return {
        "rows": ranked,
        "begin": begin,
        "cutoff": cutoff,
        "eval_begin": eval_begin,
        "eval_cutoff": eval_cutoff,
        "horizon": horizon,
        "updated": changes.aggregate(last=Max("time"))["last"],
    }


def outstanding(account, end):
    totals = defaultdict(int)
    for key, amt in Entry.objects.filter(
        account=account, item__isnull=False, doc__date__lte=end
    ).values_list("item_id", "amount"):
        totals[key] += amt if account == "Piutang" else -amt
    return [
        (doc, totals[doc.pk])
        for doc in Doc.objects.filter(pk__in=totals)
        .select_related("party")
        .order_by("due", "id")
    ]


def date_series(start, end):
    totals = defaultdict(lambda: [0, 0])
    for d, a, v in Entry.objects.filter(
        account__in=("Penjualan", "HPP", "Diskon", "Retur"),
        doc__date__range=(start, end),
    ).values_list("doc__date", "account", "amount"):
        idx = 1 if a == "HPP" else 0
        totals[d][idx] += v if idx else -v
    return [
        {
            "date": (start + timedelta(days=i)).isoformat(),
            "sales": totals[start + timedelta(days=i)][0],
            "cost": totals[start + timedelta(days=i)][1],
        }
        for i in range((end - start).days + 1)
    ]
