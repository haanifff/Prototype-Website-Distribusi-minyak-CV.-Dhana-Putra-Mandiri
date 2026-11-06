from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

ROLES = ["Admin", "Gudang", "Penjualan", "Keuangan", "Pemilik"]


def choices(items):
    return [(item, item) for item in items]


class Employee(AbstractUser):
    role = models.CharField(max_length=16, choices=choices(ROLES))
    identity = models.CharField(max_length=512, blank=True, null=True, unique=True)


class Party(models.Model):
    name = models.CharField("Nama", max_length=100)
    kind = models.CharField(
        "Jenis", max_length=16, choices=choices(["Pelanggan", "Pemasok"])
    )

    class Meta:
        unique_together = ("name", "kind")

    def __str__(self):
        return self.name


class Product(models.Model):
    since = models.DateField("Mulai dicatat", default=timezone.localdate)
    code = models.SlugField("Kode produk", unique=True)
    brand = models.CharField("Merek", max_length=60)
    size = models.CharField("Netto", max_length=30)
    pack = models.CharField("Kemasan", max_length=40)
    unit = models.CharField("Satuan dasar", max_length=20)

    class Meta:
        unique_together = ("brand", "size", "pack", "unit")
        ordering = ["code"]

    def __str__(self):
        return f"{self.brand} {self.size} · {self.pack} ({self.unit})"


class Conversion(models.Model):
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    label = models.CharField("Satuan transaksi", max_length=25)
    factor = models.PositiveIntegerField("Jumlah satuan dasar")

    class Meta:
        unique_together = ("product", "label")


class Tier(models.Model):
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    minimum = models.PositiveIntegerField("Mulai jumlah", default=1)
    price = models.PositiveBigIntegerField("Harga per satuan dasar")

    class Meta:
        unique_together = ("product", "minimum")


class Lead(models.Model):
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    day = models.DateField("Berlaku mulai")
    days = models.PositiveIntegerField("Waktu tunggu (hari)")

    class Meta:
        unique_together = ("product", "day")


class Doc(models.Model):
    kind = models.CharField(max_length=32)
    draft_date = models.DateField(null=True)
    date = models.DateField()
    party = models.ForeignKey(Party, null=True, on_delete=models.PROTECT)
    ref = models.ForeignKey("self", null=True, on_delete=models.PROTECT)
    due = models.DateField(null=True)
    terms = models.CharField(max_length=12, blank=True)
    status = models.CharField(max_length=16, default="Draf")
    note = models.CharField(max_length=400, blank=True)
    actor = models.ForeignKey(Employee, on_delete=models.PROTECT)
    freight = models.PositiveBigIntegerField(default=0)
    unload = models.PositiveBigIntegerField(default=0)
    proof = models.CharField(max_length=80, null=True, unique=True)
    token = models.CharField(max_length=64, unique=True)

    def __str__(self):
        return f"DPM-{self.pk:05d}"


class Line(models.Model):
    doc = models.ForeignKey(Doc, related_name="lines", on_delete=models.PROTECT)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    qty = models.PositiveIntegerField()
    price = models.PositiveBigIntegerField(default=0)
    discount = models.PositiveBigIntegerField(default=0)
    cost = models.PositiveBigIntegerField(default=0)
    freight = models.PositiveBigIntegerField(default=0)
    unload = models.PositiveBigIntegerField(default=0)
    damaged = models.BooleanField(default=False)
    direction = models.SmallIntegerField(default=1)

    class Meta:
        unique_together = ("doc", "product")


class Movement(models.Model):
    doc = models.ForeignKey(Doc, on_delete=models.PROTECT)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    qty = models.IntegerField()
    value = models.BigIntegerField()

    class Meta:
        ordering = ["doc__date", "id"]


class Entry(models.Model):
    doc = models.ForeignKey(Doc, on_delete=models.PROTECT)
    account = models.CharField(max_length=40)
    amount = models.BigIntegerField()  # Debit positif, kredit negatif.
    item = models.ForeignKey(
        Doc, related_name="open_entries", null=True, on_delete=models.PROTECT
    )
    product = models.ForeignKey(Product, null=True, on_delete=models.PROTECT)


class Opening(models.Model):
    doc = models.OneToOneField(Doc, on_delete=models.PROTECT)
    account = models.CharField(max_length=32)
    amount = models.PositiveBigIntegerField()


class CostProof(models.Model):
    code = models.CharField(max_length=80, unique=True)
    doc = models.ForeignKey(Doc, on_delete=models.PROTECT)
    purpose = models.CharField(max_length=60)


class Day(models.Model):
    day = models.DateField(unique=True)
    complete = models.BooleanField(default=True)


class Period(models.Model):
    month = models.CharField(max_length=7, unique=True)
    status = models.CharField(max_length=20, default="Terbuka")
    note = models.TextField(blank=True)


class Audit(models.Model):
    time = models.DateTimeField(default=timezone.now)
    actor = models.ForeignKey(Employee, on_delete=models.PROTECT)
    action = models.CharField(max_length=80)
    document = models.CharField(max_length=100)
    reason = models.CharField(max_length=400, blank=True)
