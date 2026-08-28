"""Base settings shared across environments. Env-specific values live in dev.py / prod.py."""
from decimal import Decimal
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
    # Required by `OpClass` in an expression index: `PostgresConfig.ready()` is what
    # registers it as an index-expression WRAPPER, and without that registration Django
    # emits `USING gin ((UPPER("email") gin_trgm_ops))` — the operator class inside the
    # expression's parentheses, which Postgres rejects as a syntax error. Added in Plan-16
    # Task 6 for the admin search box's trigram indexes (accounts/0006, orders/0006,
    # catalog/0009). It also registers the `trigram_similar`/`unaccent` lookups and the
    # array/range field lookups; nothing here uses those today, and none of it changes the
    # behaviour of code that does not ask for it.
    "django.contrib.postgres",
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
    "apps.analytics",
    "apps.cms",
    "apps.catalog",
    "apps.pricing",
    "apps.inventory",
    "apps.search",
    "apps.carts",
    "apps.checkout",
    "apps.orders",
    "apps.payments",
    "apps.delivery",
    # The public store locator (Plan-42). Its own app rather than a table inside
    # `delivery`: an active `delivery.SenderLocation` is a live GIG shipping origin,
    # and a directory of distributors must never be able to become one.
    "apps.stores",
    "apps.shipping",
    "apps.wishlist",
    "apps.reviews",
    "apps.newsletter",
    "apps.referrals",
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

# --- Password hashing (Plan-22) ---
# Django's default list, VERBATIM AND IN ORDER, plus the verify-only WordPress hasher
# appended for migrated customers. Position 0 is what every new password is written with;
# every later entry only reads existing hashes and triggers a rehash on next login.
#
# THE ORDER IS THE SECURITY PROPERTY. `WordPressPasswordHasher.encode()` raises, so
# promoting it would break `set_password()` everywhere including `createsuperuser` — and
# a WordPress hash must never be *written* by this project regardless.
# `apps.accounts.checks.check_wordpress_hasher_is_not_first` fails the system check if a
# future edit reorders this, because `migrate` runs checks and would catch it at deploy
# rather than at the first password change.
#
# This list was previously undefined, so the effective default was Django's. It is spelled
# out here only so that appending does not silently change anything else. Argon2 is a
# separate decision needing `argon2-cffi`, and deliberately is NOT smuggled in here.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
    "apps.accounts.hashers.WordPressPasswordHasher",
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
# The zone STAFF-FACING timestamps are rendered in. Storage stays UTC (`USE_TZ`); this is
# a presentation choice only, and it exists because the people reading the admin's alert
# emails are in Lagos. A UTC time in an email that asks the reader to reason about a
# 24-hour deadline sends them to the wrong hour — see `apps/orders/emails.py::_staff_local`.
# Customer emails are unaffected: they print dates, not times.
STAFF_DISPLAY_TIMEZONE = env("STAFF_DISPLAY_TIMEZONE", default="Africa/Lagos")
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

# This service's own public origin. LOAD-BEARING IN PRODUCTION — set it there.
#
# Two consumers, and the second is why the default must never be relied on:
#
# 1. Absolutising media paths for email (`apps/catalog/images.py::absolutise`). Only
#    matters in dev/test, where no S3 bucket is configured and `image.url` returns a
#    relative `/media/...` path that would render as a broken image inside a mail client.
#    Production's `AWS_S3_CUSTOM_DOMAIN` makes those URLs absolute already.
# 2. **Building the confirmation link an external notification recipient clicks**
#    (`apps/notifications/confirm.py::confirm_url_for`). If this is unset in production,
#    every confirmation email points at `http://localhost:8000` and the failure is
#    invisible until a recipient clicks a dead link — and since an unconfirmed address
#    receives nothing, the symptom is silence, which is the exact failure mode the
#    notifications app exists to eliminate.
#
# `config/settings/prod.py` asserts it is set rather than trusting a deploy checklist.
API_PUBLIC_URL = env("API_PUBLIC_URL", default="http://localhost:8000")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    # Logs 429s (the only signal several endpoints emit under attack), then
    # delegates to DRF's default — responses are unchanged.
    "EXCEPTION_HANDLER": "config.exception_handler.logging_exception_handler",
    # Our own subclass, NOT the stock class. It is stock behaviour minus one refusal:
    # a PREAUTH token (password proved, TOTP still owed) must not authenticate anything
    # outside the three TOTP endpoints, and stock JWTAuthentication does not look at the
    # `toke_aud` claim at all — so it accepted one on the whole customer surface. See
    # apps/accounts/authentication.CustomerJWTAuthentication.
    #
    # NOTE `SessionAuthentication` is deliberately absent and must stay absent:
    # django.contrib.admin is mounted at /django-admin/ (denied at the Apache vhost in
    # production), and a session cookie cannot carry the admin audience claim, so a view
    # accepting one would bypass the admin gate entirely.
    # test_admin_surface_guard.test_no_view_anywhere_uses_session_authentication pins it.
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.accounts.authentication.CustomerJWTAuthentication",
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
        # Staff. A separate, higher bucket (see UserRateThrottle.allow_request): one
        # admin page render costs ~13 authenticated GETs (product + variants + stock +
        # prices + images + countries + admin-me + paged tags/categories), so 120/min
        # throttled a single person doing ordinary catalogue work — measured live
        # 2026-08-10 while one staff member priced one product. The key is
        # request.user.pk from a validated JWT: unforgeable and unshared, so the only
        # session a runaway tab can starve is its own.
        #
        # 300 AND NOT MORE, because this number is also the exfiltration budget of a
        # stolen staff session: the customer and order LIST endpoints sit under this
        # rate, at PAGE_SIZE 24 rows a request — the same threat `admin_search` below
        # is capped at 60/min for. The worst legitimate minute observed is ~100
        # requests (an editor load ~13 GETs + a 16-variant Apply + price typing);
        # 300 covers that 3× over while holding the exfil budget to 2.5× what the
        # old rate allowed. Raise it only with that trade-off named.
        "user_staff": "300/min",
        "search": "30/min",
        "suggest": "60/min",
        "cart": "120/min",
        "newsletter": "5/min",
        # Public referral-code lookup. Shared bucket via the BFF (see
        # `_IPKeyedThrottle`), so generous on purpose: this must never stop a real
        # customer typing a code, and a guessed code costs nobody anything.
        "referral_lookup": "60/min",
        # Writes to a referrer's payout bank account. Every change sends the
        # account-takeover security email, so this is an outbound-mail cap as much as
        # an abuse cap; keyed per-user (unforgeable), applied to PUT only — see
        # PayoutMethodWriteThrottle.
        "payout_method_write": "6/hour",
        # Resending a notification-recipient confirmation. Owner-only and audited, but
        # the endpoint mails BRANDED, AUTHENTICATED-LOOKING mail to an arbitrary address
        # on demand — the same "open relay wearing a staff login" shape the test-send
        # action's docstring names. A cap means a mistake, or a stolen Owner session,
        # cannot turn it into a way to bombard somebody's inbox. Generous enough that the
        # real use (it went to spam, send another) never hits it.
        "recipient_confirm_resend": "10/hour",
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
        # Staff login (/auth/admin-token/). Deliberately brutal compared with the
        # customer rates above: legitimate staff volume is near zero, a staff lockout
        # is recoverable with root access, and the account being guessed at can change
        # the payout bank account. Separate scopes = separate buckets, so an attack on
        # one gate cannot deny logins on the other.
        "admin_login_ip": "5/min",
        "admin_login_email": "10/hour",
        # Delivery-partner portal login (Plan-39). Same failure-counting design as the
        # admin pair (see PartnerLoginIPThrottle); rates match the admin gate because
        # the population is the same order of magnitude (one business) and there is no
        # TOTP behind this door, so the buckets carry more of the weight, not less.
        "partner_login_ip": "5/min",
        "partner_login_email": "10/hour",
        # Staff invite acceptance. Counts INVALID tokens only — see
        # `StaffInviteAcceptThrottle`, which deliberately inverts the usual order so a
        # valid token never touches the bucket. 10/hour is a junk-volume cap, not a
        # guess cap: at 256 bits of token entropy, guessing is not the threat model.
        "invite_accept_ip": "10/hour",
        # Global admin search. Keyed on the authenticated staff USER, request-counted —
        # see `AdminSearchThrottle` for why that is safe here and is a lockout button
        # everywhere else on this surface. Generous because it is a box a human types into.
        "admin_search": "60/min",
        # The _ip rates below are DELIBERATELY loose. All storefront traffic egresses
        # from Vercel, so these are shared by every customer at once -- at 10/hour they
        # were a store-wide cap of ten signups and ten password resets per hour, which
        # Plan-22's "imported customers, reset your password" wave would have hit within
        # minutes. They are volume caps against the direct-to-API path, where the address
        # is real, and the per-email rates below carry the anti-abuse weight for the
        # shared path. See the caveat on _IPKeyedThrottle.
        "register_ip": "60/hour",
        "register_email": "3/hour",
        # Guest order placement (Plan-38). Email-keyed: every guest order mails the
        # SUBMITTED address (order-received + bank details for a transfer), so this is
        # an inbox-protection cap like register_email — 6/hour not 3 because a real
        # customer retrying a flaky gateway re-POSTs the same address and every attempt
        # counts (throttles run before the idempotency replay can answer). IP-keyed:
        # volume cap for the direct-to-API path only, same shared-egress caveat as
        # register_ip. Turnstile on the endpoint is the actual bot gate.
        "guest_checkout_email": "6/hour",
        "guest_checkout_ip": "60/hour",
        "password_reset_email": "5/hour",
        "password_reset_ip": "60/hour",
    },
}

# --- Logging ---
# Everything under the "apps" namespace logs at INFO and propagates to the root
# console handler (docker captures stdout in prod). Security-shaped events all
# use the "apps.security" logger, so one grep tells the whole auth story.
# Propagation (rather than a per-logger handler) is deliberate: pytest's caplog
# attaches at the root and would miss records from propagate=False loggers.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {"format": "%(asctime)s %(levelname)s [%(name)s] %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "standard"},
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        "apps": {"level": "INFO"},
        "django": {"level": "WARNING"},
    },
}

# --- Sentry ---
# Errors only (traces_sample_rate=0 keeps the free tier for what matters).
# ERROR-level log records become events; INFO/WARNING become breadcrumbs on
# those events — both via the SDK's default logging integration.
# send_default_pii=False: customer emails appear in our own log lines by choice,
# but are not shipped to Sentry as indexed user identities.
SENTRY_DSN = env("SENTRY_DSN", default="")
if SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=env("SENTRY_ENVIRONMENT", default="development"),
        send_default_pii=False,
        traces_sample_rate=0.0,
    )

# --- Cloudflare Turnstile ---
# The auth gate (login/register/password-reset) is active iff this is non-empty.
# Deliberate rollout order: the backend deploys with it UNSET until the storefront
# ships the widget, then setting the secret in the prod env turns the gate on.
# See apps/accounts/turnstile.py.
TURNSTILE_SECRET = env("TURNSTILE_SECRET", default="")

# The staff gate (/auth/admin-token/) reads this FIRST and falls back to
# TURNSTILE_SECRET when it is empty. Two reasons it exists, both operational:
#
# 1. Turnstile widgets are DOMAIN-SCOPED. The existing widget's allowlist is
#    next.tokecosmetics.com; the admin app is a new hostname, so unless that hostname
#    is added to the existing widget it needs its own widget — and its own secret.
#    Without this setting, "give admin its own widget" would mean editing code.
# 2. Break-glass granularity. During a Cloudflare/siteverify outage the rehearsed
#    recovery is to drop the secret from the prod env and restart. With one shared
#    secret that opens the customer gate too; with this one, staff can get back in
#    while the customer gate stays closed (or the reverse).
#
# Unset by default, so nothing changes until an admin widget actually exists.
TURNSTILE_ADMIN_SECRET = env("TURNSTILE_ADMIN_SECRET", default="")

# --- Admin BFF shared secret ---
# The anti-abuse gate on the two admin endpoints with exactly one legitimate caller
# (`/auth/admin-token/` and `/admin/staff/invites/accept/`). NOT an authentication
# control — see the long note in apps/accounts/bff.py before touching it.
#
# It exists because those two endpoints each make an outbound siteverify call before
# anything else, and that cost could not be metered by request volume: the admin app
# calls the API server-side, so staff and attackers share one Vercel egress address and
# any volume cap keyed on it is a free staff lockout.
#
# Unset = OFF, the same contract TURNSTILE_SECRET has, so the backend can deploy before
# the admin app sends the header and so an operator can break-glass by removing it.
ADMIN_BFF_SECRET = env("ADMIN_BFF_SECRET", default="")

# --- Checkout ---
RESERVATION_TTL_MINUTES = env.int("RESERVATION_TTL_MINUTES", default=30)

# How long after DELIVERY an order waits before auto-completing. "completed" means
# "delivered and the return window has closed" — staff can complete sooner from the
# admin; whichever happens first wins. Plan-11's verified-purchase review rule and
# Plan-28's accounting both read this status, so it has to actually get set.
RETURN_WINDOW_DAYS = env.int("RETURN_WINDOW_DAYS", default=14)

# --- Referral programme (Plan-29, referral half) ---
#
# THESE NUMBERS ARE PUBLISHED TERMS, not tuning knobs. Every one of them is on
# https://tokecosmetics.com/affiliates-2/ where customers can read it, so changing one
# changes what the shop has promised.
#
# Most of them still live here, env-overridable, precisely BECAUSE they are not meant to
# be edited casually from an admin screen — a change is a deploy and a terms update,
# together.
#
# THE TWO PERCENTAGES ARE THE EXCEPTION (Hammed, 2026-08-27). The commission rate and the
# referred customer's discount are now edited from the admin's Business Decisions page and
# stored on `core.BusinessDecisions`. The settings below survive as that row's SEED — it
# is created from them on first touch, so a fresh database and every existing deploy start
# at the published 10%/5% with no migration step — and are never read again afterwards.
# **Changing them in the environment moves nothing on a database that already has the
# row.** Change those two from the admin page, or edit the row.
#
# Note what does NOT follow from any change: commissions already earned keep the rate they
# were earned under (`Commission.rate_percent`), and orders already placed keep the
# discount they were given (`Order.referral_discount_percent`). Both are snapshots.
REFERRAL_COMMISSION_PERCENT = env("REFERRAL_COMMISSION_PERCENT", default="10.00")

# What the REFERRED CUSTOMER gets off their own order for arriving through a referral —
# the buyer's half of the programme, added 2026-08-27. Seeds
# `BusinessDecisions.customer_discount_percent`; see that model before changing it here.
#
# It is a REAL price reduction, not a tender: it lands in `Order.referral_discount_total`,
# comes out of the tax base in `compute_totals`, and therefore also out of the referrer's
# commission base — the referrer earns their percentage of what the customer actually
# paid for the goods. That last consequence is Hammed's explicit ruling of 2026-08-27 and
# is pinned by a test; it is also the rule coupons and loyalty points already follow.
REFERRAL_CUSTOMER_DISCOUNT_PERCENT = env("REFERRAL_CUSTOMER_DISCOUNT_PERCENT", default="5.00")

# The click-attribution window. A visit carrying ?ref=CODE credits that referrer for
# any order the visitor places in the next 30 days. Read by the STOREFRONT too (its
# cookie max-age must match, or the two disagree about who earned what) — see
# storefront/src/lib/referral.ts, which restates it and says so.
REFERRAL_COOKIE_DAYS = env.int("REFERRAL_COOKIE_DAYS", default=30)

# The holding period, counted from the order SHIPPING (not from payment — see
# Commission's docstring). Deliberately longer than RETURN_WINDOW_DAYS: the shop's own
# return window is 14 days, and the affiliate terms promise a more conservative 60
# before commission is payable. Being more cautious than the terms is safe; being less
# is a breach, so this must never be lowered below the published number.
REFERRAL_HOLD_DAYS = env.int("REFERRAL_HOLD_DAYS", default=60)

# Minimum balance before a payout can be requested, PER CURRENCY. ₦20,000 is the
# published figure; the other three are this platform's own numbers, since the
# WordPress programme only ever ran in Nigeria. Balances roll over until met, exactly
# as the terms say. A currency absent from this map cannot be paid out at all, which is
# the safe direction to be wrong in.
REFERRAL_PAYOUT_THRESHOLDS = {
    "NGN": Decimal("20000.00"),
    "GBP": Decimal("20.00"),
    "USD": Decimal("25.00"),
    "CAD": Decimal("30.00"),
}

# The "₦200k Club": referred sales over ₦200,000 in any rolling 90-day window unlock
# manually-fulfilled perks (retainer talks, PR packages, early access). Computed on the
# fly from Commission.base_amount — there is no stored tier, because a stored tier is a
# thing that goes stale the day someone's 90-day window rolls past a big order.
# NGN-only on purpose: the tier is naira-denominated in the published terms, and
# inventing a GBP equivalent would be inventing a promise.
REFERRAL_ELITE_THRESHOLDS = {"NGN": Decimal("200000.00")}
REFERRAL_ELITE_WINDOW_DAYS = env.int("REFERRAL_ELITE_WINDOW_DAYS", default=90)

# Bumped when the affiliate terms change; stamped onto ReferralProfile at the first
# payout request so a dispute can be answered with "you agreed to v1 of these terms on
# this date". A date string rather than an integer so it reads as what it is.
REFERRAL_TERMS_VERSION = env("REFERRAL_TERMS_VERSION", default="2026-08-14")

# Withholding tax deducted from a payout, as a percentage of the gross.
#
# ZERO BY HAMMED'S RULING, 2026-08-15: referral commission is paid in full, to residents
# and non-residents alike — a referrer with ₦50,000 available receives ₦50,000. The
# mechanism exists anyway, and that is the whole point of this setting: the tax position
# is the kind of thing an accountant changes, and changing it should be an env var and a
# month's payouts, not a schema migration and a rewrite.
#
# The rate is SNAPSHOT onto each `PayoutRequest` when it is created, exactly as
# `Commission.rate_percent` snapshots the commission rate. So raising this never
# retroactively re-cuts a request that is already open, and a payout can always answer
# "what rate was I paid under" from its own row.
#
# If it ever goes above zero, four things need attention, in this order: the storefront
# must show the NET the customer will receive (it reads `net_amount`, which already
# exists); the payout email must state the deduction; the remittance fields on
# `PayoutRequest` need filling; and someone must actually remit. See
# `docs/runbooks/referral-programme.md` for the accountant's answers this setting encodes.
REFERRAL_WHT_PERCENT = env("REFERRAL_WHT_PERCENT", default="0.00")

# --- Staff invites ---
# How long an invite link stays usable. 72 hours is long enough to survive a weekend
# and short enough that a link forwarded, screenshotted or left in a mailbox stops
# being a staff-creation capability quickly. Env-tunable because the right number
# depends on how the person is actually onboarded, and the only alternative to tuning
# it is people asking for a re-invite. Lowering it costs nothing: "resend" is
# revoke + invite, which is a two-click operation for the Owner.
STAFF_INVITE_TTL_HOURS = env.int("STAFF_INVITE_TTL_HOURS", default=72)

# --- Staff TOTP (Plan-16 Task 3b) ---
#
# A DEDICATED KEY, NOT DERIVED FROM SECRET_KEY. A TOTP secret is symmetric and must be
# recoverable in order to verify a code, so unlike a password it cannot be hashed —
# encryption at rest is the only option, and the whole value of it is that a stolen
# database backup does not contain the key. (The backups leave this box nightly for an
# S3 bucket whose write credential can also delete, versioning off; see memory
# project_tokecosmetics_s3_backup_risk.) Key separation is the point: SECRET_KEY signs
# every JWT and every password-reset token, so rotating it logs the whole shop out,
# while rotating this one is a background re-encrypt (`manage.py rotate_totp_key`).
# Deriving one from the other would tie those two operations together forever.
#
# WHAT IS CONFIGURED TODAY. The default below is a literal, obviously-insecure
# development key — the same convention as SECRET_KEY above — so the test suite and a
# fresh checkout work with no setup. `config/settings/prod.py` re-reads this WITHOUT a
# default, so a production process that has not been given a real key fails to start
# rather than encrypting staff second factors under a value that is in the repository.
#
# Generate one with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
TOTP_ENCRYPTION_KEY = env(
    "TOTP_ENCRYPTION_KEY", default="dG9rZS1kZXYtaW5zZWN1cmUtdG90cC1rZXktMzJieXQ="
)
# Decrypt-only keys, newest first — the same shape as Django's SECRET_KEY_FALLBACKS.
# Rotation is: put the old key here, set the new one above, restart, run
# `manage.py rotate_totp_key`, then empty this list and restart again. Documented in
# docs/runbooks/admin-gate.md §6.
TOTP_ENCRYPTION_KEY_FALLBACKS = env.list("TOTP_ENCRYPTION_KEY_FALLBACKS", default=[])

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
# Reply-To for every outgoing mail, and the contact address printed in the footer.
#
# DEFAULT_FROM_EMAIL sits on the Resend SENDING subdomain (mg.tokecosmetics.com), which
# has no inbox — so without this the "just reply to this email" that five customer
# templates promise reaches nobody, silently. `send_email` sets Reply-To on every message.
#
# DEFAULTED IN CODE rather than left to the environment: it is a published brand fact, not
# a secret and not per-environment, and a blank value here is a broken promise in a
# customer's inbox rather than a loud failure. The env var still overrides — point a
# staging deploy somewhere else with it.
#
# A Reply-To on a different domain from the From address is normal and does not touch
# SPF/DKIM/DMARC, which authenticate the envelope sender and the From header only.
EMAIL_REPLY_TO = env("EMAIL_REPLY_TO", default="sales@tokecosmetics.com")

# Origin the email templates load the logo and social icons from. Those files live in
# `storefront/public/email/` and are served by the storefront's CDN, so the storefront
# must be deployed BEFORE mail that references them goes out. Override only if the
# assets move (a bucket, a separate CDN) — see apps/notifications/branding.py.
EMAIL_ASSET_BASE_URL = env("EMAIL_ASSET_BASE_URL", default="")

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

# --- GIG Logistics (Plan-32a; sandbox base by default, production at go-live) ---
GIG_BASE_URL = env("GIG_BASE_URL", default="https://dev-thirdpartynode.theagilitysystems.com")
GIG_EMAIL = env("GIG_EMAIL", default="")
GIG_PASSWORD = env("GIG_PASSWORD", default="")
# Wallet is prepaid and debited at waybill creation; below this NGN balance the
# monitor task (slice 6) emails admins before fulfilment starts failing.
GIG_WALLET_ALERT_THRESHOLD = env.int("GIG_WALLET_ALERT_THRESHOLD", default=50_000)
# Where GIG's rider collects parcels — distance from here drives every quote. The
# defaults are the SANDBOX test company's address (Gbagada); the go-live runbook
# replaces them with the real warehouse coordinates.
GIG_SENDER_LATITUDE = env.float("GIG_SENDER_LATITUDE", default=6.5560)
GIG_SENDER_LONGITUDE = env.float("GIG_SENDER_LONGITUDE", default=3.3888)
# Printed on the waybill and read to the rider — go-live sets the real office values.
GIG_SENDER_NAME = env("GIG_SENDER_NAME", default="Toke Cosmetics")
GIG_SENDER_PHONE = env("GIG_SENDER_PHONE", default="")
GIG_SENDER_ADDRESS = env("GIG_SENDER_ADDRESS", default="Gbagada, Lagos")
GIG_SENDER_LOCALITY = env("GIG_SENDER_LOCALITY", default="Gbagada")
# 0=Car 1=Bike 2=Van 3=Truck (confirmed by GIG's developer 2026-08-11, matching
# the measured enum). Bike is the small-parcel default.
GIG_VEHICLE_TYPE = env.int("GIG_VEHICLE_TYPE", default=1)
# Tracking webhook (gig/webhook.py). The secret comes from the one-time
# `register_gig_webhook` command; empty = not registered, receiver answers 503.
# The registration API lives on a DIFFERENT host from the third-party node;
# production swaps the dev- prefix for prod- (their docs' stated convention).
GIG_WEBHOOK_SECRET = env("GIG_WEBHOOK_SECRET", default="")
GIG_WEBHOOK_API_BASE = env(
    "GIG_WEBHOOK_API_BASE", default="https://dev-agilitythirdpartyapi.theagilitysystems.com"
)

# --- AAJ Express (Plan-43; sandbox base by default, production at go-live) ---
# Bearer API key auth — no login call, no token lifetime. The key decides which AAJ
# partner account a booking lands on (measured: two test keys, two `source` accounts).
AAJ_BASE_URL = env("AAJ_BASE_URL", default="https://dev.aajexpress.org/api/v2")
AAJ_API_KEY = env("AAJ_API_KEY", default="")
# `payments.accountNumber` on every booking — AAJ's number for our account. Charged at
# process-booking time (create-booking is free) via CREDIT_FACILITY (post-paid) or
# WALLET (prepaid); which one AAJ enabled for us is a commercial fact, hence a setting.
AAJ_ACCOUNT_NUMBER = env("AAJ_ACCOUNT_NUMBER", default="")
AAJ_PAYMENT_METHOD = env("AAJ_PAYMENT_METHOD", default="CREDIT_FACILITY")
# Booking category is REQUIRED for DOMESTIC and its id is environment-specific. Empty =
# resolve "Non Electronics" by name from get-categories (cached); set to pin one.
AAJ_CATEGORY_ID = env("AAJ_CATEGORY_ID", default="")
# Sender contact fields AAJ requires that SenderLocation does not hold. The email is
# where AAJ's booking notifications land; the postal code is required for the sender
# (measured: irrelevant to pricing, printed on the label). The sender's STATE — which
# PRICES the zone — is never a setting: aaj/origins.py resolves it per row from its
# state region, its state label, or its pin, and skips a row it cannot place.
AAJ_SENDER_EMAIL = env("AAJ_SENDER_EMAIL", default="")
AAJ_SENDER_POSTAL_CODE = env("AAJ_SENDER_POSTAL_CODE", default="100001")
# THE KILL-SWITCH ON THE MONEY CALL. process-booking cannot be rehearsed on AAJ's
# sandbox (its test credit is not chargeable), so the first real order is the first
# real test. Off = capture stops after the free create-booking step with a clear
# refusal; the runbook flips it on after one controlled live booking.
AAJ_PROCESS_ENABLED = env.bool("AAJ_PROCESS_ENABLED", default=False)

# --- Google Places: homepage reviews header refresh (runbooks/google-apis-setup.md) ---
# The SERVER key (IP-locked to the VPS, Places API (New) only) — never the browser key
# and never NEXT_PUBLIC anything. Empty = the refresh task skips, admin numbers stand.
GOOGLE_PLACES_API_KEY = env("GOOGLE_PLACES_API_KEY", default="")
# The shop's Google Business listing (not a secret; verified live 2026-08-11:
# "Toke Cosmetics", Igbogbo Ikorodu, rating 4.6 / 49 ratings at time of writing).
GOOGLE_PLACE_ID = env("GOOGLE_PLACE_ID", default="ChIJj1450kjsOxARhI16Z0jVX-c")

# Storefront origin, used ONLY to build the gateway return URL (Flutterwave redirect).
# Never derived from a request — a client-supplied return URL is an open-redirect vector.
STOREFRONT_BASE_URL = env("STOREFRONT_BASE_URL", default="http://localhost:3000")

# Shared secret for the storefront's POST /api/revalidate (instant cache flush on CMS
# writes — apps/cms/revalidate.py). EMPTY DISABLES the notifier and the storefront falls
# back to its 60-second revalidate window, so a missing secret degrades, never breaks.
# Must match REVALIDATE_SECRET in the storefront's environment.
REVALIDATE_SECRET = env("REVALIDATE_SECRET", default="")

# --- Celery ---
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=REDIS_URL)
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_BEAT_SCHEDULE = {
    # Hourly, but the task only SENDS when the low-stock list changes — see
    # `low_stock_digest`. An hourly check that stays quiet tells you a bestseller ran out
    # within the hour; a daily digest cannot, and demoting it would have traded away
    # responsiveness to fix a problem that was repetition rather than frequency.
    "low-stock-digest-hourly": {
        "task": "apps.inventory.tasks.low_stock_digest",
        "schedule": 3600.0,  # every hour; sends only on change
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
    "tombstone-search-terms": {
        "task": "apps.core.tasks.tombstone_search_terms",
        "schedule": 86400.0,  # daily — the retention window is 90 days
    },
    "sync-gig-coverage": {
        "task": "apps.delivery.tasks.sync_gig_coverage_task",
        "schedule": 86400.0,  # daily — GIG's network changes on human timescales
    },
    "sync-gig-centres": {
        "task": "apps.delivery.tasks.sync_gig_centres_task",
        "schedule": 86400.0,  # daily — centres change on human timescales, like LGAs
    },
    "poll-gig-tracking": {
        "task": "apps.delivery.tasks.poll_gig_tracking",
        "schedule": 7200.0,  # every 2h — pull until GIG's webhook exists, fallback after
    },
    "monitor-gig-wallet": {
        "task": "apps.delivery.tasks.monitor_gig_wallet",
        "schedule": 21600.0,  # every 6h — the wallet drains at fulfilment speed, not checkout speed
    },
    "poll-aaj-tracking": {
        "task": "apps.delivery.tasks.poll_aaj_tracking",
        "schedule": 7200.0,  # every 2h — AAJ has no webhook; pull is the only feed
    },
    "check-aaj-states": {
        "task": "apps.delivery.tasks.check_aaj_states",
        "schedule": 86400.0,  # daily — the state-code table prices every AAJ order
    },
    "mature-referral-commissions": {
        "task": "apps.referrals.tasks.mature_commissions",
        "schedule": 86400.0,  # daily — the holding period is measured in days
    },
    "refresh-google-reviews-meta": {
        "task": "apps.cms.tasks.refresh_google_reviews_meta",
        "schedule": 86400.0,  # daily — review counts move on human timescales
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
