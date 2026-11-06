import os
import secrets
from urllib.parse import urlparse

from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.django_client import OAuth
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST
from joserfc.errors import JoseError
from requests.exceptions import RequestException

from .books import audit
from .models import ROLES, Employee

ISSUER = os.getenv("OIDC_ISSUER", "https://accounts.google.com").rstrip("/")
REDIRECT = os.getenv("OIDC_REDIRECT_URI", "http://localhost:8000/auth/callback/")
oauth = OAuth()
oauth.register(
    "pegawai",
    server_metadata_url=ISSUER + "/.well-known/openid-configuration",
    client_id=os.getenv("OIDC_CLIENT_ID"),
    client_secret=os.getenv("OIDC_CLIENT_SECRET"),
    client_kwargs={"scope": "openid email profile", "code_challenge_method": "S256"},
)


def signin(request):
    if request.user.is_authenticated:
        return redirect("/")
    return render(
        request,
        "login.html",
        {"roles": ROLES, "configured": bool(os.getenv("OIDC_CLIENT_ID"))},
    )


@require_POST
def start(request):
    if not os.getenv("OIDC_CLIENT_ID") or not os.getenv("OIDC_CLIENT_SECRET"):
        messages.error(request, "Konfigurasi penyedia identitas belum lengkap.")
        return redirect("signin")
    if urlparse(ISSUER).scheme != "https" or (
        settings.PRODUCTION and urlparse(REDIRECT).scheme != "https"
    ):
        raise PermissionDenied
    return oauth.pegawai.authorize_redirect(
        request, REDIRECT, nonce=secrets.token_urlsafe(32)
    )


@transaction.atomic
def approved(claims):
    if (
        claims.get("iss") != ISSUER
        or claims.get("email_verified") is not True
        or not claims.get("sub")
    ):
        raise PermissionDenied
    identity = ISSUER + "|" + claims["sub"]
    user = Employee.objects.filter(
        username=str(claims.get("email", "")).strip().lower(), is_active=True
    ).first()
    if not user or (user.identity and user.identity != identity):
        raise PermissionDenied
    if not user.identity:
        if Employee.objects.filter(identity=identity).exists():
            raise PermissionDenied
        user.identity = identity
        user.save(update_fields=["identity"])
    return user


def callback(request):
    try:
        tokens = oauth.pegawai.authorize_access_token(request, leeway=30)
        if not tokens.get("id_token"):
            raise PermissionDenied
        user = approved(tokens.get("userinfo") or {})
    except (OAuthError, JoseError, PermissionDenied, RequestException, ValueError):
        return render(
            request,
            "error.html",
            {
                "message": "Login ditolak. Periksa undangan aktif atau mulai kembali login pegawai."
            },
            status=403,
        )
    login(request, user)
    audit(user, "Login OIDC", "Sesi")
    return redirect("/")


@require_POST
def demo(request):
    if not settings.DEMO or request.META.get("REMOTE_ADDR") not in ("127.0.0.1", "::1"):
        raise PermissionDenied
    role = request.POST.get("role", "")
    if role not in ROLES:
        raise PermissionDenied
    user = Employee.objects.filter(
        username=role.lower() + "@demo.invalid", is_active=True, role=role
    ).first()
    if not user:
        raise PermissionDenied
    login(request, user)
    audit(user, "Login demo", "Sesi")
    return redirect("/")


@require_POST
def signout(request):
    if request.user.is_authenticated:
        audit(request.user, "Logout", "Sesi")
    logout(request)
    return redirect("signin")
