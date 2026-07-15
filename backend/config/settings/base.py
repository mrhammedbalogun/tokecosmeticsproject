"""Base settings shared across environments. Env-specific values live in dev.py / prod.py."""
from pathlib import Path

import environ

# backend/  (this file is config/settings/base.py -> parents[2] = backend/)
BASE_DIR = Path(__file__).resolve().parents[2]

env = environ.Env()
# Read backend/.env if present (local dev convenience; never committed).
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY", default="dev-insecure-key-change-me")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third-party
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "drf_spectacular",
    "django_filters",
    "anymail",
    "storages",
    # local
    "apps.core",
    "apps.accounts",
    "apps.notifications",
    "apps.catalog",
    "apps.pricing",
    "apps.inventory",
]

AUTH_USER_MODEL = "accounts.User"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.CountryMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Redis (used by /healthz/ now; broker/cache wired in Plan-03).
REDIS_URL = env("REDIS_URL", default="redis://localhost:6380/0")

# Cache — dev/tests default to locmem (hermetic). Prod sets these to Redis via env:
#   CACHE_BACKEND=django.core.cache.backends.redis.RedisCache
#   CACHE_LOCATION=${REDIS_URL}
CACHES = {
    "default": {
        "BACKEND": env("CACHE_BACKEND", default="django.core.cache.backends.locmem.LocMemCache"),
        "LOCATION": env("CACHE_LOCATION", default="toke-cache"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# --- Storage (Django 5.x STORAGES) ---
# Media -> S3 when a bucket is configured (prod), else local filesystem (dev).
# Static -> whitenoise compressed manifest (only Django admin uses static files).
AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME", default="")
AWS_S3_REGION_NAME = env("AWS_S3_REGION_NAME", default="")
AWS_QUERYSTRING_AUTH = False  # public product images under media/catalog/

if AWS_STORAGE_BUCKET_NAME:
    AWS_ACCESS_KEY_ID = env("AWS_ACCESS_KEY_ID", default="")
    AWS_SECRET_ACCESS_KEY = env("AWS_SECRET_ACCESS_KEY", default="")
    _default_storage = {"BACKEND": "storages.backends.s3.S3Storage"}
else:
    _default_storage = {"BACKEND": "django.core.files.storage.FileSystemStorage"}

STORAGES = {
    "default": _default_storage,
    # Plain static storage by default (dev/test); prod switches to whitenoise manifest.
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 24,
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {"anon": "60/min", "user": "120/min"},
}

# --- JWT (SimpleJWT) ---
from datetime import timedelta  # noqa: E402

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

# --- drf-spectacular ---
SPECTACULAR_SETTINGS = {
    "TITLE": "Tokecosmetics API",
    "DESCRIPTION": "Storefront + admin REST API.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# --- Frontend origins / URLs ---
FRONTEND_URL = env("FRONTEND_URL", default="http://localhost:3000")
ADMIN_URL = env("ADMIN_URL", default="http://localhost:3001")
CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS",
    default=["http://localhost:3000", "http://localhost:3001"],
)

# --- Email ---
# Dev/test default = console; prod switches to Resend via anymail (set EMAIL_BACKEND in .env).
# Resend is the sole provider. From address must be on the verified sending domain
# (mg.tokecosmetics.com); Resend rejects mail from an unverified domain.
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Toke Cosmetics <hello@mg.tokecosmetics.com>")
ANYMAIL = {
    "RESEND_API_KEY": env("RESEND_API_KEY", default=""),
}

# --- Celery ---
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=REDIS_URL)
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
