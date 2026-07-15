# Tokecosmetics Platform

One global e-commerce platform for Toke Cosmetics (Nigeria + international), replacing two
WordPress/WooCommerce stores. **API-first:** Django + DRF backend on the VPS, two Next.js apps
(storefront + admin) on Vercel, one database with data-driven country/currency support.

## Repository layout

| Path | What |
|---|---|
| `backend/` | Django 5.2 + DRF project (managed with **uv**, Python 3.12) |
| `storefront/` | Next.js customer storefront (App Router, TypeScript, Tailwind) |
| `admin/` | Next.js admin portal |
| `docker-compose.dev.yml` | Local dev services: Postgres 16, Redis 7, Meilisearch |
| `docs/` | `audit.md` (store audit), `architecture.md`, implementation plans |
| `.github/workflows/` | CI: backend tests + frontend builds |

## Local development

```bash
# 1. Start local services
docker compose -f docker-compose.dev.yml up -d

# 2. Backend (uv provisions Python 3.12; `python` need not be on PATH)
uv run --project backend python manage.py migrate
uv run --project backend python manage.py runserver   # http://localhost:8000/healthz/

# 3. Frontends
cd storefront && npm run dev     # http://localhost:3000
cd admin && npm run dev
```

See [docs/architecture.md](docs/architecture.md) for the full design and decisions, and
[docs/audit.md](docs/audit.md) for the audited state of the legacy WordPress stores.

## Conventions

- Conventional commits (`feat:`, `fix:`, `chore:`, `docs:`, `test:`). Never commit `.env*`.
- `main` is always deployable. Every stage is verified by running the thing, not just typechecking.
