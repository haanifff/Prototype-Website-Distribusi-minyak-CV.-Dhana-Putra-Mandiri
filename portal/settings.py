import os
import secrets
import tempfile
import uuid
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
PRODUCTION = os.getenv("APP_ENV", "local") == "production"
DEMO = os.getenv("DEMO_MODE") == "1"
if DEMO and PRODUCTION:
    raise RuntimeError("Mode demo hanya untuk perangkat lokal.")
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    if PRODUCTION:
        raise RuntimeError("SECRET_KEY wajib di produksi.")
    key = BASE_DIR / ".local-secret"
    if not key.exists():
        key.write_text(secrets.token_urlsafe(48))
    SECRET_KEY = key.read_text()
DEBUG = False
ALLOWED_HOSTS = (
    ["localhost", "127.0.0.1"]
    if DEMO
    else os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
)
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "ops",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "portal.urls"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / ("demo.sqlite3" if DEMO else "distribusi.sqlite3"),
        "OPTIONS": {"transaction_mode": "IMMEDIATE", "timeout": 20},
    }
}
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "ops.views.context",
            ]
        },
    }
]
DATABASES["default"]["TEST"] = {
    "NAME": Path(tempfile.gettempdir()) / ("dpm-test-" + uuid.uuid4().hex + ".sqlite3")
}
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / ".static"
LANGUAGE_CODE = "id"
TIME_ZONE = "Asia/Jakarta"
USE_TZ = True
USE_THOUSAND_SEPARATOR = False
AUTH_USER_MODEL = "ops.Employee"
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = PRODUCTION
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 28800
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_SSL_REDIRECT = PRODUCTION
SECURE_HSTS_SECONDS = 31536000 if PRODUCTION else 0
LOGIN_URL = "/masuk/"
