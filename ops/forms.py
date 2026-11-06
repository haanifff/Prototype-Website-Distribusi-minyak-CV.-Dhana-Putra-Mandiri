from django import forms
from django.utils import timezone

from .books import EXPENSES, FUNDS, INCOMES
from .models import Conversion, Employee, Lead, Party, Product, Tier, choices


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ["code", "brand", "size", "pack", "unit", "since"]
        widgets = {"since": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}


class PartyForm(forms.ModelForm):
    class Meta:
        model = Party
        fields = ["name", "kind"]


class TierForm(forms.ModelForm):
    class Meta:
        model = Tier
        fields = ["product", "minimum", "price"]
        labels = {"product": "Produk"}

    def clean(self):
        data = super().clean()
        if not data.get("minimum") or not data.get("price"):
            raise forms.ValidationError("Jumlah dan harga harus positif.")
        return data


class ConversionForm(forms.ModelForm):
    class Meta:
        model = Conversion
        fields = ["product", "label", "factor"]
        labels = {"product": "Produk"}

    def clean_factor(self):
        v = self.cleaned_data["factor"]
        if v < 1:
            raise forms.ValidationError("Faktor harus positif.")
        return v


class LeadForm(forms.ModelForm):
    class Meta:
        model = Lead
        fields = ["product", "day", "days"]
        labels = {"product": "Produk"}
        widgets = {"day": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}


class EmployeeForm(forms.ModelForm):
    username = forms.EmailField(label="Email undangan")

    class Meta:
        model = Employee
        fields = ["username", "first_name", "role", "is_active"]
        labels = {
            "first_name": "Nama tampilan",
            "role": "Peran",
            "is_active": "Akun aktif",
        }

    def clean_username(self):
        return self.cleaned_data["username"].strip().lower()


MASTERS = {
    "produk": ("Produk", ProductForm),
    "mitra": ("Pelanggan & pemasok", PartyForm),
    "harga": ("Harga bertingkat", TierForm),
    "konversi": ("Konversi satuan", ConversionForm),
    "tunggu": ("Waktu tunggu", LeadForm),
    "pegawai": ("Pengguna dan peran", EmployeeForm),
}


class CashForm(forms.Form):
    kind = forms.ChoiceField(
        label="Jenis mutasi",
        choices=choices(
            [
                "Cicilan",
                "Bayar pemasok",
                "Beban",
                "Modal",
                "Transfer",
                "Uang muka",
                "Alokasi uang muka",
                "Pendapatan lain",
            ]
        ),
    )
    day = forms.DateField(
        label="Tanggal pembayaran",
        initial=timezone.localdate,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    amount = forms.IntegerField(label="Jumlah (Rp)", min_value=1)
    fund = forms.ChoiceField(label="Akun dana", choices=choices(FUNDS))
    target = forms.ChoiceField(
        label="Tujuan transfer", choices=[("", "—")] + choices(FUNDS), required=False
    )
    category = forms.ChoiceField(
        label="Kelompok beban / pendapatan",
        choices=[("", "—")] + choices(EXPENSES + INCOMES),
        required=False,
    )
    ref = forms.ChoiceField(label="Faktur / penerimaan asal", required=False)
    advance = forms.ChoiceField(label="Bukti uang muka / kredit retur", required=False)
    party = forms.ModelChoiceField(
        label="Pelanggan uang muka",
        queryset=Party.objects.filter(kind="Pelanggan"),
        required=False,
    )
    proof = forms.CharField(
        label="Nomor bukti eksternal", max_length=80, required=False
    )
    note = forms.CharField(label="Keterangan", required=False, max_length=400)

    def __init__(self, *args, **kwargs):
        from .models import Doc

        super().__init__(*args, **kwargs)
        docs = (
            Doc.objects.filter(status="Dibukukan")
            .select_related("party")
            .order_by("-id")
        )
        for field, kinds in [
            ("ref", ["Penjualan", "Penerimaan", "Saldo awal"]),
            ("advance", ["Uang muka", "Retur"]),
        ]:
            self.fields[field].choices = [("", "—")] + [
                (d.pk, f"{d} · {d.kind} · {d.party}")
                for d in docs.filter(kind__in=kinds)
            ]
