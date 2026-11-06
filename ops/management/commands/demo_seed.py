from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from ops import books as b
from ops.models import ROLES, Conversion, Day, Employee, Lead, Party, Product, Tier


class Command(BaseCommand):
    help = "Isi database demo lokal kosong dengan data sintetis."

    @transaction.atomic
    def handle(self, *args, **opts):
        if not settings.DEMO:
            raise CommandError("Aktifkan DEMO_MODE=1 untuk database demo terpisah.")
        if Employee.objects.exists():
            self.stdout.write("Database demo sudah diinisialisasi.")
            return
        users = {
            role: Employee.objects.create_user(
                username=role.lower() + "@demo.invalid",
                first_name=role + " Demo",
                role=role,
                password=None,
            )
            for role in ROLES
        }
        supply = Party.objects.create(name="Pemasok Simulasi", kind="Pemasok")
        customers = [
            Party.objects.create(name=n, kind="Pelanggan")
            for n in ("Toko Simulasi Utara", "Koperasi Contoh", "Gerai Latihan Selatan")
        ]
        today = timezone.localdate()
        first = today - timedelta(days=42)
        products = []
        for i, (brand, size, pack, unit) in enumerate(
            [
                ("Nira", "1 liter", "Pouch", "karton"),
                ("Nira", "800 ml", "Pouch", "karton"),
                ("Sora", "2 liter", "Botol", "karton"),
                ("Luma", "5 liter", "Jeriken", "jeriken"),
            ],
            1,
        ):
            p = Product.objects.create(
                code=f"MG-{i:03d}",
                brand=brand,
                size=size,
                pack=pack,
                unit=unit,
                since=first,
            )
            products.append(p)
            Lead.objects.create(product=p, day=first, days=7 + i)
            Tier.objects.create(product=p, minimum=1, price=175000 + i * 12500)
            Tier.objects.create(product=p, minimum=30, price=173000 + i * 12500)
            Conversion.objects.create(product=p, label="Palet demo", factor=20)
        receipt = b.draft(
            users["Gudang"],
            "Penerimaan",
            first,
            supply,
            [
                {"product": p.pk, "qty": n}
                for p, n in zip(products, [438, 303, 250, 98])
            ],
        )
        b.book(
            users["Keuangan"],
            receipt.pk,
            first,
            {
                str(l.pk): {"price": 150000 + l.product_id * 7000}
                for l in receipt.lines.all()
            },
            proof="SIM-PB-001",
        )
        for i in range(42):
            day = first + timedelta(days=i + 1)
            if i % 7 != 6:
                rows = [
                    {"product": p.pk, "qty": n}
                    for p, n in zip(
                        products, [9 + i % 5, 4 + i % 6, 2 + i % 4, 1 + i % 3]
                    )
                    if p != products[3] or i % 2 == 0
                ]
                d = b.draft(
                    users["Penjualan"],
                    "Penjualan",
                    day,
                    customers[i % 3],
                    rows,
                    due=day + timedelta(days=14),
                )
                b.book(
                    users["Gudang"],
                    d.pk,
                    day,
                    {str(l.pk): {"qty": l.qty} for l in d.lines.all()},
                )
                if i % 3 != 0:
                    amount = b.balance(d.open_entries.filter(account="Piutang"))
                    b.cash(
                        users["Keuangan"],
                        "Cicilan",
                        day,
                        amount if i % 2 else amount // 2,
                        "Bank",
                        ref=d,
                    )
                if i % 5 == 0:
                    b.cash(
                        users["Keuangan"],
                        "Beban",
                        day,
                        125000,
                        "Bank",
                        category=b.EXPENSES[0],
                        proof=f"SIM-BA-{i}",
                        note="Antar pesanan demo",
                    )
            if day < today:
                Day.objects.create(day=day, complete=True)
        self.stdout.write("Data sintetis siap.")
