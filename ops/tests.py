import base64
import hashlib
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connections
from django.test import Client, TestCase, TransactionTestCase
from django.utils import timezone
from joserfc import jwt
from joserfc.jwk import RSAKey
from openpyxl import load_workbook

from . import auth
from . import books as b
from .insights import actuals, analysis, outstanding
from .models import (
    ROLES,
    Day,
    Doc,
    Employee,
    Entry,
    Lead,
    Movement,
    Party,
    Period,
    Product,
)


class Scenario:
    def setUp(self):
        self.day = timezone.localdate() - timedelta(days=50)
        self.users = {
            role: Employee.objects.create_user(
                username=role.lower() + "@unit.invalid", role=role
            )
            for role in ROLES
        }
        self.g = self.users["Gudang"]
        self.f = self.users["Keuangan"]
        self.s = self.users["Penjualan"]
        self.c = Party.objects.create(kind="Pelanggan", name="Contoh")
        self.v = Party.objects.create(kind="Pemasok", name="Pemasok contoh")
        self.p = self.product("S1")

    def product(self, code):
        return Product.objects.create(
            code=code,
            brand=code,
            size="1 liter",
            pack="Botol",
            unit="karton",
            since=self.day,
        )

    def receive(self, qty, price, day=None, p=None, freight=0, unload=0):
        d = b.draft(
            self.g,
            "Penerimaan",
            day or self.day,
            self.v,
            [{"product": (p or self.p).pk, "qty": qty}],
        )
        return b.book(
            self.f,
            d.pk,
            d.date,
            {str(d.lines.get().pk): dict(price=price, freight=freight, unload=unload)},
            freight=freight,
            unload=unload,
            proof=str(d),
        )

    def sell(self, qty, price, day=None, p=None, confirm=True):
        d = b.draft(
            self.s,
            "Penjualan",
            day or self.day,
            self.c,
            [{"product": (p or self.p).pk, "qty": qty, "price": price}],
            due=(day or self.day) + timedelta(days=7),
        )
        if confirm:
            return b.book(self.g, d.pk, d.date, {str(d.lines.get().pk): {"qty": qty}})
        return d


class DeliveryTests(Scenario, TestCase):
    def test_acceptance_finance_and_excel(self):
        r = self.receive(100, 170000, freight=800000, unload=200000)
        sale = self.sell(40, 195000)
        pay = self.day + timedelta(days=2)
        b.cash(self.f, "Cicilan", pay, 5000000, "Bank", ref=sale)
        b.cash(
            self.f, "Beban", pay, 250000, "Bank", category=b.EXPENSES[0], proof="ONG-1"
        )
        self.assertEqual(b.stock(self.p), (60, 10800000))
        self.assertEqual(outstanding("Piutang", self.day)[0][1], 7800000)
        self.assertEqual(outstanding("Piutang", pay)[0][1], 2800000)
        self.assertEqual(outstanding("Utang", pay), [(r, 18000000)])
        self.assertEqual(b.balance(Entry.objects.filter(account="Bank")), 4750000)
        totals = actuals(self.day, pay)
        self.assertEqual(
            (totals["Penjualan bruto"], totals["HPP"], totals["Laba bersih"]),
            (7800000, 7200000, 350000),
        )
        self.client.force_login(self.f)
        resp = self.client.get(
            "/laporan/", {"awal": self.day, "akhir": pay, "ekspor": "xlsx"}
        )
        wb = load_workbook(BytesIO(resp.content), read_only=True)
        self.assertEqual(list(wb.active.values)[-1][1], 350000)
        b.cash(
            self.f, "Beban", pay, 500000, "Bank", category=b.EXPENSES[0], proof="ONG-2"
        )
        self.assertEqual(actuals(self.day, pay)["Laba bersih"], -150000)

    def test_avg_allocation_atomicity_and_duplicate_proof(self):
        self.receive(10, 180000)
        self.receive(10, 200000)
        self.sell(5, 215000)
        self.assertEqual(b.stock(self.p), (15, 2850000))
        self.assertEqual(actuals(self.day, self.day)["HPP"], 950000)
        d = b.draft(
            self.g, "Penerimaan", self.day, self.v, [{"product": self.p.pk, "qty": 1}]
        )
        with self.assertRaises(ValidationError):
            b.book(
                self.f,
                d.pk,
                self.day,
                {str(d.lines.get().pk): {"price": 10}},
                freight=1,
                proof="PROOF",
            )
        self.assertFalse(Movement.objects.filter(doc=d).exists())
        with self.assertRaises(ValidationError):
            b.cash(
                self.f,
                "Beban",
                self.day,
                10,
                "Bank",
                proof="dpm-00001",
                category=b.EXPENSES[0],
            )

    def test_abc(self):
        for p, n in [(self.p, 82), (self.product("S2"), 14), (self.product("S3"), 4)]:
            self.receive(n, 100, p=p)
            self.sell(n, 120, p=p)
        self.product("NOL")
        rows = analysis(self.day, self.day, "Pemilik")["rows"]
        self.assertEqual(
            [(r["share"], r["class"]) for r in rows],
            [(82, "A"), (14, "B"), (4, "C"), (0, "Tinjau")],
        )

    def test_forecast_and_temporal_holdout(self):
        self.receive(320, 100)
        first = self.day + timedelta(days=1)
        for i in range(28):
            d = first + timedelta(days=i)
            self.sell(10, 120, d)
            Day.objects.create(day=d)
        end = d
        Lead.objects.create(product=self.p, day=first, days=7)
        risk = lambda: analysis(first, end, "Pemilik")["rows"][0]
        before = risk()
        self.assertEqual(
            (before["stock"], before["rate"], before["coverage"], before["risk"]),
            (40, 10, 4, "Berisiko"),
        )
        self.assertIsNone(before["mae"])
        for i in range(1, 8):
            d = end + timedelta(days=i)
            self.sell(5, 120, d)
            Day.objects.create(day=d)
        Lead.objects.create(product=self.p, day=d, days=1)
        after = risk()
        self.assertEqual(
            (after["stock"], after["rate"], after["mae"], after["lead"]), (40, 10, 5, 7)
        )
        Day.objects.filter(day=first).delete()
        self.assertEqual(risk()["risk"], "Data belum cukup")

    def test_zero_rate_missing_lead_and_stockout(self):
        end = self.day + timedelta(days=27)
        Day.objects.bulk_create(
            [Day(day=self.day + timedelta(days=i)) for i in range(28)]
        )
        r = analysis(self.day, end, "Gudang")["rows"][0]
        self.assertEqual((r["risk"], r["outages"]), ("Belum ada laju permintaan", 28))
        self.receive(10, 2, end)
        self.sell(5, 3, end)
        self.assertFalse(Day.objects.get(day=end).complete)
        Day.objects.filter(day=end).update(complete=True)
        r = analysis(self.day, end, "Gudang")["rows"][0]
        self.assertEqual(r["risk"], "Isi waktu tunggu")
        self.assertIsNotNone(r["coverage"])

    def test_duplicate_and_closed_period(self):
        self.receive(10, 200)
        d = self.sell(4, 300)
        with self.assertRaises(ValidationError):
            b.book(self.g, d.pk, self.day, {str(d.lines.get().pk): {"qty": 4}})
        Period.objects.create(month=str(self.day)[:7], status="Ditutup")
        with self.assertRaises(ValidationError):
            b.cash(self.f, "Modal", self.day, 1, "Kas")
        self.assertEqual(b.stock(self.p), (6, 1200))

    def test_return_and_advance(self):
        self.receive(100, 200)
        sale = self.sell(10, 300)
        b.cash(self.f, "Cicilan", self.day, 3000, "Kas", ref=sale)
        for damaged in (False, True):
            r = b.draft(
                self.g,
                "Retur",
                self.day,
                self.c,
                [{"product": self.p.pk, "qty": 2, "damaged": damaged}],
                ref=sale,
                note="Kembali",
            )
            b.book(self.f, r.pk, self.day, {})
        self.assertEqual(b.stock(self.p), (92, 18400))
        self.assertEqual(actuals(self.day, self.day)["HPP"], 1600)
        self.assertEqual(sum(v for _, v in outstanding("Uang muka", self.day)), 1200)
        invoice = self.sell(3, 300)
        credit = outstanding("Uang muka", self.day)[0][0]
        b.cash(
            self.f,
            "Alokasi uang muka",
            self.day,
            600,
            "Bank",
            ref=invoice,
            advance=credit,
        )
        self.assertEqual(outstanding("Piutang", self.day)[-1][1], 300)
        self.assertEqual(b.balance(Entry.objects.filter(account="Bank")), 0)

    def test_roles_exports_csrf_and_session(self):
        self.receive(10, 200)
        sale = self.sell(3, 350)
        self.client.force_login(self.g)
        for url in (
            "/api/keuangan/",
            "/laporan/?ekspor=xlsx",
            "/dana/",
            "/master/",
            "/periode/",
        ):
            self.assertEqual(self.client.get(url).status_code, 403)
        raw = self.client.get("/api/analisis/").json()["rows"][0]
        self.assertFalse(set(raw) & {"usage", "ids", "cumulative", "share", "cost"})
        self.assertNotContains(self.client.get(f"/dokumen/{sale.pk}/"), "Harga pokok")
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.g)
        self.assertEqual(
            client.post("/hari/", {"day": self.day, "complete": "1"}).status_code, 403
        )
        self.client.post("/keluar/")
        self.assertEqual(self.client.get("/api/analisis/").status_code, 302)

    def test_opening_and_reversal(self):
        d = b.opening(
            self.f, self.day, "Persediaan", 1000, product=self.p, qty=10, proof="AW-1"
        )
        with self.assertRaises(PermissionDenied):
            b.book(self.f, d.pk, self.day, {})
        b.book(self.users["Pemilik"], d.pk, self.day, {})
        sale = self.sell(5, 200)
        b.reverse(self.f, sale.pk, "Kesalahan penyerahan")
        self.assertEqual(b.stock(self.p), (10, 1000))
        self.assertEqual(actuals(self.day, self.day)["Penjualan bersih"], 0)
        self.assertEqual(analysis(self.day, self.day, "Pemilik")["rows"][0]["usage"], 0)

    def test_close_and_reopen_with_reason(self):
        self.client.force_login(self.f)
        month = str(self.day)[:7]
        form = {
            "month": month,
            "action": "ajukan",
            "note": "Sudah cocok",
            **{s: 0 for s in [*b.FUNDS, "Utang", "Piutang", "Persediaan"]},
        }
        self.assertEqual(self.client.post("/periode/", form).status_code, 302)
        self.client.force_login(self.users["Pemilik"])
        self.assertEqual(
            self.client.post("/periode/", dict(form, action="tutup")).status_code, 302
        )
        self.assertEqual(
            self.client.post(
                "/periode/", dict(form, action="buka", note="")
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                "/periode/", dict(form, action="buka", note="Periksa bukti")
            ).status_code,
            302,
        )
        self.assertEqual(Period.objects.get().status, "Terbuka")

    def test_three_roles_through_http(self):
        self.client.force_login(self.g)
        res = self.client.post(
            "/buat/?jenis=Penerimaan",
            {
                "day": self.day,
                "party": self.v.pk,
                "product": [self.p.pk],
                "qty": [100],
                "token": "receipt",
            },
        )
        self.assertEqual(res.status_code, 302)
        receipt = Doc.objects.get(token="receipt")
        self.client.force_login(self.f)
        line = receipt.lines.get()
        res = self.client.post(
            res.url,
            {
                "day": self.day,
                "proof": "UAT-WEB",
                "unload_proof": "BONGKAR-001",
                "freight": 800000,
                "unload": 200000,
                f"price_{line.pk}": 170000,
                f"freight_{line.pk}": 800000,
                f"unload_{line.pk}": 200000,
            },
        )
        self.assertEqual(res.status_code, 302)
        with self.assertRaises(ValidationError):
            b.cash(
                self.f,
                "Beban",
                self.day,
                200000,
                "Kas",
                category=b.EXPENSES[0],
                proof="BONGKAR-001",
            )
        self.client.force_login(self.s)
        res = self.client.post(
            "/buat/?jenis=Penjualan",
            {
                "day": self.day,
                "party": self.c.pk,
                "due": self.day,
                "terms": "Tempo",
                "product": [self.p.pk],
                "qty": [40],
                "price": [195000],
                "token": "sale",
            },
        )
        self.assertEqual(res.status_code, 302)
        sale = Doc.objects.get(token="sale")
        self.client.force_login(self.g)
        payload = {"day": self.day, f"qty_{sale.lines.get().pk}": 40}
        self.assertEqual(self.client.post(res.url, payload).status_code, 302)
        slip = self.client.get(f"/dokumen/{sale.pk}/surat-jalan/")
        self.assertContains(slip, "Jumlah diserahkan")
        self.assertNotContains(slip, "195000")
        self.assertEqual(self.client.post(res.url, payload).status_code, 400)
        self.client.force_login(self.f)
        res = self.client.post(
            "/dana/",
            {
                "kind": "Cicilan",
                "day": self.day,
                "amount": 5000000,
                "fund": "Bank",
                "ref": sale.pk,
                "token": "pay",
            },
        )
        self.assertEqual(res.status_code, 302)
        res = self.client.post(
            "/dana/",
            {
                "kind": "Beban",
                "day": self.day,
                "amount": 250000,
                "fund": "Bank",
                "category": b.EXPENSES[0],
                "proof": "ANTAR",
                "token": "exp",
            },
        )
        self.assertEqual(res.status_code, 302)
        self.assertEqual(actuals(self.day, self.day)["Laba bersih"], 350000)

    def test_master_tier_unit_and_supplier_settlement(self):
        self.client.force_login(self.users["Admin"])
        from .models import Conversion, Tier

        res = self.client.post(
            "/master/?jenis=konversi&baru=1",
            {"product": self.p.pk, "label": "palet", "factor": 10},
        )
        self.assertEqual(res.status_code, 302)
        tier = Tier.objects.create(product=self.p, minimum=10, price=250)
        received = self.receive(15, 100)
        d = b.draft(
            self.s,
            "Penjualan",
            self.day,
            self.c,
            [
                {
                    "product": self.p.pk,
                    "qty": 1,
                    "conversion": Conversion.objects.get().pk,
                }
            ],
            due=self.day,
        )
        tier.price = 1000
        tier.save()
        self.assertEqual((d.lines.get().qty, d.lines.get().price), (10, 250))
        b.cash(self.f, "Modal", self.day, 2000, "Kas")
        b.cash(self.f, "Transfer", self.day, 1500, "Kas", target="Bank")
        b.cash(self.f, "Bayar pemasok", self.day, 1500, "Bank", ref=received)
        self.assertEqual(outstanding("Utang", self.day)[0][1], 0)
        self.assertEqual(b.balance(Entry.objects.filter(account__in=b.FUNDS)), 500)
        self.assertEqual(actuals(self.day, self.day)["Laba bersih"], 0)


class RaceTests(Scenario, TransactionTestCase):
    def test_competing_confirmations(self):
        self.receive(5, 100)
        docs = [self.sell(4, 150, confirm=False) for i in range(2)]
        payloads = [(d.pk, {str(d.lines.get().pk): {"qty": 4}}) for d in docs]
        barrier = threading.Barrier(2)

        def worker(pair):
            try:
                barrier.wait(timeout=5)
                b.book(self.g, pair[0], self.day, pair[1])
                return "ok"
            except ValidationError:
                return "ditolak"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(2) as pool:
            self.assertCountEqual(pool.map(worker, payloads), ["ok", "ditolak"])
        self.assertEqual(b.stock(self.p), (1, 100))


class LoginTests(TestCase):
    def test_signed_oidc_code_and_pkce(self):
        remote = auth.oauth.pegawai
        key = RSAKey.generate_key(2048, parameters={"kid": "uji"})
        wrong = RSAKey.generate_key(2048, parameters={"kid": "uji"})
        issuer = auth.ISSUER
        metadata = {
            "issuer": issuer,
            "authorization_endpoint": "https://id.invalid/auth",
            "token_endpoint": "https://id.invalid/token",
            "jwks": {"keys": [key.as_dict(private=False)]},
            "id_token_signing_alg_values_supported": ["RS256"],
        }
        Employee.objects.create_user(username="aktif@unit.invalid", role="Gudang")
        Employee.objects.create_user(
            username="nonaktif@unit.invalid", role="Gudang", is_active=False
        )
        with (
            patch.dict(
                os.environ, {"OIDC_CLIENT_ID": "dpm", "OIDC_CLIENT_SECRET": "dummy"}
            ),
            patch.object(remote, "client_id", "dpm"),
            patch.object(remote, "load_server_metadata", return_value=metadata),
        ):
            for failure in (
                "state",
                "nonce",
                "iss",
                "aud",
                "expired",
                "signature",
                "not-invited",
                "inactive",
                "valid",
            ):
                res = self.client.post("/auth/start/")
                params = parse_qs(urlparse(res.url).query)
                self.assertEqual(params["code_challenge_method"], ["S256"])
                self.assertEqual(params["response_type"], ["code"])
                now = int(time.time())
                claims = {
                    "sub": "employee",
                    "email": "aktif@unit.invalid",
                    "email_verified": True,
                    "iss": issuer,
                    "aud": "dpm",
                    "iat": now,
                    "exp": now + 300,
                    "nonce": params["nonce"][0],
                }
                if failure in ("nonce", "iss", "aud"):
                    claims[failure] = "wrong"
                if failure == "expired":
                    claims.update(iat=now - 2000, exp=now - 1000)
                if failure == "not-invited":
                    claims["email"] = "asing@unit.invalid"
                if failure == "inactive":
                    claims["email"] = "nonaktif@unit.invalid"
                token = jwt.encode(
                    {"alg": "RS256", "kid": "uji"},
                    claims,
                    wrong if failure == "signature" else key,
                )
                with patch.object(
                    remote,
                    "fetch_access_token",
                    return_value={"id_token": token, "access_token": "dummy"},
                ) as fetch:
                    response = self.client.get(
                        "/auth/callback/",
                        {
                            "state": "wrong"
                            if failure == "state"
                            else params["state"][0],
                            "code": "code",
                        },
                    )
                    self.assertEqual(
                        response.status_code,
                        302 if failure == "valid" else 403,
                        failure,
                    )
                    if failure != "state":
                        verifier = fetch.call_args.kwargs["code_verifier"]
                        challenge = (
                            base64.urlsafe_b64encode(
                                hashlib.sha256(verifier.encode()).digest()
                            )
                            .decode()
                            .rstrip("=")
                        )
                        self.assertEqual(params["code_challenge"], [challenge])
            self.assertIn("_auth_user_id", self.client.session)
