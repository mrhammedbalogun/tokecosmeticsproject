# One image serves web, worker and beat — they differ only by CMD (see
# infra/docker-compose.prod.yml). Built for the Namecheap VPS, which also runs the
# live WordPress stores, so the image stays small and the runtime is non-root.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# libpango-1.0-0 / libpangoft2-1.0-0 are WeasyPrint's NATIVE dependencies. WeasyPrint is a
# binding over Pango/cairo, so `pip install weasyprint` succeeds without them and then
# raises at IMPORT time — meaning every invoice download 500s in production while the build
# looks perfectly healthy. This is also why invoices cannot be rendered on the Windows dev
# box (no Pango there); the container is the only place to verify it.
# libpq5: psycopg runtime.  curl: the compose healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies first, from the LOCKFILE, so an application-code edit doesn't reinstall the
# world and prod gets exactly the versions CI tested. Exported to a plain requirements file
# rather than `uv sync` because this project declares no [build-system] — there is nothing
# to "install the project itself" from, and pip-installing the exported set sidesteps the
# whole packaging question.
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-hashes -o /tmp/requirements.txt \
    && uv pip install --system -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

COPY . .

# Non-root. staticfiles/ and media/ are bind-mounted from the host in production and must be
# writable by this uid, so they are created and chowned here rather than left to Docker
# (which would create them root-owned on first mount).
RUN adduser --disabled-password --gecos "" --uid 10001 app \
    && mkdir -p /app/staticfiles /app/media \
    && chown -R app:app /app
USER app

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--timeout", "60", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
