"""Development settings.

Default DB is the docker-compose Postgres (localhost:5433). If DATABASE_URL is unset,
fall back to a local SQLite file so tests/hacking work without Docker running.
"""
from .base import *  # noqa: F401,F403
from .base import BASE_DIR, env

DEBUG = True
ALLOWED_HOSTS = ["*"]

# Run Celery tasks synchronously in dev/tests (no worker needed).
CELERY_TASK_ALWAYS_EAGER = True

DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
    )
}
