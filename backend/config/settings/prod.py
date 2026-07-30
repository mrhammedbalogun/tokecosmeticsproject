"""Production settings. Strict; all secrets from the environment (see docs/Appendix A).

Security hardening (HSTS, secure cookies, CORS allowlist, throttles) is expanded in Plan-03.
"""
from .base import *  # noqa: F401,F403
from .base import STORAGES, env

DEBUG = False

# Compressed, hashed static files via whitenoise (only Django admin uses static).
STORAGES = {**STORAGES, "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"}}
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["api.tokecosmetics.com"])

DATABASES = {"default": env.db("DATABASE_URL")}
# Wrap every request in a transaction (money-safety, master §Plan-03 item 7).
DATABASES["default"]["ATOMIC_REQUESTS"] = True

# Behind the reverse proxy / Cloudflare (finalized in Plan-02).
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True

# HSTS
SECURE_HSTS_SECONDS = 31536000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Cookies
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# Misc headers
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

# Staff TOTP secrets are encrypted at rest under this key. Re-read WITHOUT a default so
# a production process that was never given one fails at import rather than silently
# encrypting every staff second factor under the development literal in base.py — which
# is in the repository, and therefore not a secret at all. The failure is loud, happens
# at deploy time, and the fix is one env line; the alternative failure is silent and is
# only discovered when a database backup is stolen.
TOTP_ENCRYPTION_KEY = env("TOTP_ENCRYPTION_KEY")

# Swagger/docs are staff-only in production.
SPECTACULAR_SETTINGS = {**globals().get("SPECTACULAR_SETTINGS", {}), "SERVE_PERMISSIONS": ["rest_framework.permissions.IsAdminUser"]}
