"""Production settings. Strict; all secrets from the environment (see docs/Appendix A).

Security hardening (HSTS, secure cookies, CORS allowlist, throttles) is expanded in Plan-03.
"""
from .base import *  # noqa: F401,F403
from .base import env

DEBUG = False
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["api.tokecosmetics.com"])

DATABASES = {"default": env.db("DATABASE_URL")}

# Behind the reverse proxy / Cloudflare (finalized in Plan-02/03).
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
