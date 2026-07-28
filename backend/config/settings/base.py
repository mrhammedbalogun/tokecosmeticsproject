"""Base settings shared across environments. Env-specific values live in dev.py / prod.py."""
from pathlib import Path

import environ
from corsheaders.defaults import default_headers as cors_default_headers

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
    "apps.search",
    "apps.carts",
    "apps.checkout",
    "apps.orders",
    "apps.payments",
    "apps.delivery",
    "apps.shipping",
    "apps.wishlist",
    "apps.reviews",
    "apps.newsletter",
    "apps.migration_wp",
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
AWS_QUERYSTRING_AUTH = False  # stable unsigned URLs for product images under catalog/

# Serve catalog media through a CDN hostname instead of the S3 endpoint.
#
# WHY THIS EXISTS. The bucket is private and must stay private: the nightly Postgres
# backups live in it under `backups/` alongside `catalog/` (infra/deploy/backup.sh), so
# making objects publicly readable would require switching Block Public Access off on the
# bucket holding the database dumps — and versioning is currently disabled. CloudFront with
# Origin Access Control reaches a private bucket without any of that, and its policy is
# scoped to `catalog/*` so `backups/` stays unreachable even through the CDN.
#
# Set to the distribution hostname in prod (e.g. dxxxx.cloudfront.net). django-storages
# then emits https://<domain>/<key>, which also fixes Open Graph and Product JSON-LD
# images — those embed the raw URL and never touch Next's image optimizer, so a
# storefront-only allowlist change would have left social previews broken.
#
# Empty by default, so dev and tests keep the plain S3/filesystem behaviour.
AWS_S3_CUSTOM_DOMAIN = env("AWS_S3_CUSTOM_DOMAIN", default="")

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
    # Our own subclasses, NOT rest_framework.throttling.*: DRF's get_ident keys on the
    # whole X-Forwarded-For chain when NUM_PROXIES is unset, so a rotating junk prefix
    # mints a fresh bucket per request. See apps/accounts/throttling.py.
    #
    # This covers views that do NOT set throttle_classes. Any view that pins its own
    # classes opts OUT of these defaults entirely -- DRF replaces, it does not merge --
    # so such views must use apps.accounts.throttling.ScopedRateThrottle rather than the
    # stock one, or they keep the bypass.
    "DEFAULT_THROTTLE_CLASSES": [
        "apps.accounts.throttling.AnonRateThrottle",
        "apps.accounts.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/min",
        "user": "120/min",
        "search": "30/min",
        "suggest": "60/min",
        "cart": "120/min",
        "newsletter": "5/min",
        # Auth. Email-keyed unless the name says _ip.
        #
        # login_ip is the VOLUME cap and must stay listed first on LoginView: without it
        # the email-keyed windows leave password spraying (one guess each against many
        # addresses) completely unmetered, since no per-email counter is ever touched.
        "login_ip": "30/min",
        # Two windows per email. NOTE they are not independent: DRF's check_throttles
        # does not short-circuit, so a request rejected by login_burst still records
        # against login_sustained. 20 rapid attempts therefore spend the whole hour.
        "login_burst": "5/min",
        "login_sustained": "20/hour",
        # The _ip rates below are DELIBERATELY loose. All storefront traffic egresses
        # from Vercel, so these are shared by every customer at once -- at 10/hour they
        # were a store-wide cap of ten signups and ten password resets per hour, which
        # Plan-22's "imported customers, reset your password" wave would have hit within
        # minutes. They are volume caps against the direct-to-API path, where the address
        # is real, and the per-email rates below carry the anti-abuse weight for the
        # shared path. See the caveat on _IPKeyedThrottle.
        "register_ip": "60/hour",
        "register_email": "3/hour",
        "password_reset_email": "5/hour",
        "password_reset_ip": "60/hour",
    },
}

# --- Cloudflare Turnstile ---
# The auth gate (login/register/password-reset) is active iff this is non-empty.
# Deliberate rollout order: the backend deploys with it UNSET until the storefront
# ships the widget, then setting the secret in the prod env turns the gate on.
# See apps/accounts/turnstile.py.
TURNSTILE_SECRET = env("TURNSTILE_SECRET", default="")

# --- Checkout ---
RESERVATION_TTL_MINUTES = env.int("RESERVATION_TTL_MINUTES", default=30)

# How long after DELIVERY an order waits before auto-completing. "completed" means
# "delivered and the return window has closed" — staff can complete sooner from the
# admin; whichever happens first wins. Plan-11's verified-purchase review rule and
# Plan-28's accounting both read this status, so it has to actually get set.
RETURN_WINDOW_DAYS = env.int("RETURN_WINDOW_DAYS", default=14)

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
# Default to the two origins we already know about rather than hardcoded localhost.
# Those literals were identical to the FRONTEND_URL/ADMIN_URL defaults, so this
# changes nothing in dev — but in production FRONTEND_URL was correctly set to
# https://next.tokecosmetics.com while CORS silently stayed on localhost, so every
# browser-side call from the deployed storefront would have been blocked. Deriving
# it means the two cannot disagree again. CORS_ALLOWED_ORIGINS still overrides.
CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS",
    default=[FRONTEND_URL, ADMIN_URL],
)

# The storefront sends X-Country on EVERY request and X-Cart-Id on cart requests
# (storefront/src/lib/api.ts). Neither is in django-cors-headers' default allow
# list, so without this every browser-side call fails its preflight — and the
# browser reports that as an opaque network error, which reads like "the API is
# down" rather than "one header is missing". Same-origin dev never hits a
# preflight at all, so this only ever breaks in deployment.
CORS_ALLOW_HEADERS = (*cors_default_headers, "x-country", "x-cart-id")

# --- Email ---
# Dev/test default = console; prod switches to Resend via anymail (set EMAIL_BACKEND in .env).
# Resend is the sole provider. From address must be on the verified sending domain
# (mg.tokecosmetics.com); Resend rejects mail from an unverified domain.
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Toke Cosmetics <hello@mg.tokecosmetics.com>")
ANYMAIL = {
    "RESEND_API_KEY": env("RESEND_API_KEY", default=""),
}

# --- Brand ---
# Shown on gateway-HOSTED checkout pages (Flutterwave/PayPal render these server-side, so
# the logo must be a PUBLIC url they can fetch — a local file won't do). Stripe and
# Paystack don't take branding via the API: Stripe is embedded in our own UI (client_secret)
# so the storefront brands it, and Paystack branding is configured in their dashboard.
BRAND_NAME = env("BRAND_NAME", default="Toké Cosmetics")
BRAND_LOGO_URL = env("BRAND_LOGO_URL", default="")

# --- Payment gateways (test-mode keys in dev; never commit real keys) ---
# Read here, consumed lazily by each gateway adapter so a missing key never breaks
# imports/migrations — an unconfigured gateway raises GatewayNotConfigured at call time.
PAYSTACK_SECRET_KEY = env("PAYSTACK_SECRET_KEY", default="")
PAYSTACK_PUBLIC_KEY = env("PAYSTACK_PUBLIC_KEY", default="")
FLUTTERWAVE_SECRET_KEY = env("FLUTTERWAVE_SECRET_KEY", default="")
FLUTTERWAVE_SECRET_HASH = env("FLUTTERWAVE_SECRET_HASH", default="")  # webhook verif-hash
STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY", default="")
STRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET", default="")
PAYPAL_CLIENT_ID = env("PAYPAL_CLIENT_ID", default="")
PAYPAL_CLIENT_SECRET = env("PAYPAL_CLIENT_SECRET", default="")
PAYPAL_WEBHOOK_ID = env("PAYPAL_WEBHOOK_ID", default="")
PAYPAL_API_BASE = env("PAYPAL_API_BASE", default="https://api-m.sandbox.paypal.com")

# Storefront origin, used ONLY to build the gateway return URL (Flutterwave redirect).
# Never derived from a request — a client-supplied return URL is an open-redirect vector.
STOREFRONT_BASE_URL = env("STOREFRONT_BASE_URL", default="http://localhost:3000")

# --- Celery ---
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=REDIS_URL)
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_BEAT_SCHEDULE = {
    "low-stock-digest-hourly": {
        "task": "apps.inventory.tasks.low_stock_digest",
        "schedule": 3600.0,  # every hour
    },
    "abandon-stale-carts": {
        "task": "apps.carts.tasks.abandon_stale_carts",
        "schedule": 1800.0,  # every 30 min
    },
    "expire-pending-orders": {
        "task": "apps.checkout.tasks.expire_pending_orders",
        "schedule": 300.0,  # every 5 min
    },
    "complete-delivered-orders": {
        "task": "apps.orders.tasks.complete_delivered_orders",
        "schedule": 86400.0,  # daily — the return window is measured in days
    },
    "anonymize-deleted-accounts": {
        "task": "apps.accounts.tasks.anonymize_deleted_accounts",
        "schedule": 86400.0,  # daily — the grace window is measured in days
    },
}

# --- WordPress migration source (Plan-21) ---
# Deliberately unset in normal operation: credentials are passed per-invocation to
# `extract_wp_catalog` only, against a MariaDB user granted SELECT on five wp_* tables
# and nothing else. `import_catalog` never reads these.
WP_DB_HOST = env("WP_DB_HOST", default="")
WP_DB_PORT = env.int("WP_DB_PORT", default=3306)
WP_DB_NAME = env("WP_DB_NAME", default="")
WP_DB_USER = env("WP_DB_USER", default="")
WP_DB_PASSWORD = env("WP_DB_PASSWORD", default="")
WP_TABLE_PREFIX = env("WP_TABLE_PREFIX", default="wp_")
