from django.shortcuts import render
from django.urls import path
from django.views.static import serve

from ops import auth, workspace
from ops import views as v

from . import settings as config

urlpatterns = [
    path("pelanggan/", workspace.customers),
    path("pengisian/", workspace.restock),
    path("pengaturan/", workspace.settings_page),
    path("fee/", workspace.fees),
    path("dokumen/<int:pk>/surat-jalan/", v.dispatch),
    path("pembukaan/", v.opening),
    path("", v.home),
    path("masuk/", auth.signin, name="signin"),
    path("auth/start/", auth.start),
    path("auth/callback/", auth.callback),
    path("auth/demo/", auth.demo),
    path("keluar/", auth.signout),
    path("dokumen/", v.documents),
    path("buat/", v.create),
    path("dokumen/<int:pk>/", v.detail),
    path("dana/", v.money),
    path("stok/", v.inventory),
    path("analisis/", v.mining),
    path("laporan/", v.reports),
    path("api/keuangan/", v.reports),
    path("api/analisis/", v.mining),
    path("master/", v.master),
    path("periode/", v.periods),
    path("hari/", v.days),
    path("aktivitas/", v.trail),
    path("static/<path:path>", serve, {"document_root": config.BASE_DIR / "static"}),
]


def forbidden(request, exception=None):
    return render(
        request,
        "error.html",
        {
            "message": "Akun ini tidak memiliki izin untuk membuka atau mengubah data tersebut."
        },
        status=403,
    )


handler403 = forbidden
