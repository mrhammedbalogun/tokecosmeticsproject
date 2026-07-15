# Plan-01 Scaffold — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the `tokecosmetics-platform` monorepo — Django backend + storefront + admin Next.js apps — all runnable locally with one command, backend `pytest` green (real healthz test), pushed to GitHub with CI running backend tests on every push.

**Architecture:** Single Git repo. `backend/` = Django 5.2 project managed by uv (Python 3.12), settings split base/dev/prod, `/healthz/` reports db+redis. `storefront/` + `admin/` = Next.js (App Router, TS, Tailwind) via create-next-app. `docker-compose.dev.yml` at root runs Postgres 16 + Redis 7 + Meilisearch for local dev. CI = GitHub Actions running ruff + pytest (with a Postgres service) and `next build` for each app.

**Tech Stack:** Python 3.12, Django 5.2, DRF, pytest-django, uv; Next.js (latest), TypeScript, TailwindCSS; Docker Compose; GitHub Actions.

**Repo:** https://github.com/mrhammedbalogun/tokecosmeticsproject.git · local `C:\Users\Hammed\Desktop\TokeCosmeticsDev\tokecosmetics-platform` · default branch `main`.

**Environment notes (Windows):** `python` is not on PATH — always use `uv run python …` / `uv run pytest …`. uv provisions Python 3.12. Node 26, npm 11, Docker 29, Compose v5 confirmed present.

---

## File Structure

```
tokecosmetics-platform/
├── .gitignore                       # Python, Node, .env*, *.bak-*
├── README.md
├── docker-compose.dev.yml           # postgres:16, redis:7, meilisearch (local dev)
├── docs/
│   ├── audit.md                     # moved from ../docs/audit.md (Plan-00 deliverable)
│   ├── architecture.md              # condensed §3+§4 of master guide
│   └── superpowers/plans/…          # this plan
├── backend/
│   ├── pyproject.toml               # uv-managed; django, drf, pytest-django, redis, psycopg[binary], django-environ
│   ├── manage.py
│   ├── pytest.ini
│   ├── .env.example
│   ├── config/
│   │   ├── __init__.py
│   │   ├── urls.py                  # /healthz/ + (later) /api/
│   │   ├── wsgi.py / asgi.py
│   │   └── settings/{__init__,base,dev,prod}.py
│   └── apps/
│       └── core/
│           ├── __init__.py
│           ├── apps.py
│           ├── views.py             # healthz view
│           └── tests/test_healthz.py
├── storefront/                      # create-next-app (TS, Tailwind, App Router, src/)
├── admin/                           # create-next-app (same)
└── .github/workflows/
    ├── ci-backend.yml               # ruff + pytest w/ postgres service
    └── ci-frontend.yml              # next build (storefront, admin)
```

---

### Task 1: Repo skeleton + Git + GitHub remote

**Files:**
- Create: `.gitignore`, `README.md`
- Move: `../docs/audit.md` → `docs/audit.md`

- [ ] **Step 1: Init repo, set default branch, add remote**

```bash
cd "C:/Users/Hammed/Desktop/TokeCosmeticsDev/tokecosmetics-platform"
git init -b main
git remote add origin https://github.com/mrhammedbalogun/tokecosmeticsproject.git
```

- [ ] **Step 2: Write `.gitignore`** (Python, Node, env, backups)

```gitignore
# Python
__pycache__/
*.py[cod]
.venv/
*.egg-info/
.pytest_cache/
.ruff_cache/
# Node / Next
node_modules/
.next/
out/
.vercel/
next-env.d.ts
# Env & secrets
.env
.env.*
!.env.example
# Backups / OS
*.bak-*
.DS_Store
Thumbs.db
# Data
/data/
```

- [ ] **Step 3: Move audit.md into the repo, add a README**

```bash
mv "C:/Users/Hammed/Desktop/TokeCosmeticsDev/docs/audit.md" docs/audit.md
```
README.md: project name, one-paragraph description, "see docs/architecture.md".

- [ ] **Step 4: First commit**

```bash
git add .gitignore README.md docs/
git commit -m "chore: init monorepo skeleton with Plan-00 audit"
```

---

### Task 2: Django backend boots via uv

**Files:**
- Create: `backend/pyproject.toml`, `backend/manage.py`, `backend/config/**`, `backend/apps/core/**`

- [ ] **Step 1: Init uv project + pin Python + add deps**

```bash
cd backend
uv init --python 3.12 --no-workspace
uv add "django==5.2.*" djangorestframework "psycopg[binary]" redis django-environ
uv add --dev pytest pytest-django ruff
```

- [ ] **Step 2: Create Django project scaffolding** (`config/` + `manage.py`)

```bash
uv run django-admin startproject config .
```
Then split settings: create `config/settings/{__init__,base,dev,prod}.py`, delete `config/settings.py`, point `manage.py`/`wsgi.py`/`asgi.py` at `config.settings.dev` default. `base.py` reads env via django-environ; `dev.py` defaults DB to the compose Postgres (host `localhost:5433`), Redis `localhost:6380`, `DEBUG=True`; `prod.py` strict.

- [ ] **Step 3: Create `apps/core` app + register**

```bash
uv run python manage.py startapp core apps/core
```
Add `apps.core` to `INSTALLED_APPS`; set app `name = "apps.core"` in `apps/core/apps.py`.

- [ ] **Step 4: Verify server boots**

Run: `uv run python manage.py check`
Expected: "System check identified no issues".

---

### Task 3: `/healthz/` endpoint (TDD)

**Files:**
- Test: `backend/apps/core/tests/test_healthz.py`
- Create: `backend/apps/core/views.py`, wire `backend/config/urls.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/apps/core/tests/test_healthz.py
import pytest
from django.urls import reverse

@pytest.mark.django_db
def test_healthz_reports_ok(client):
    resp = client.get("/healthz/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"] is True
    assert "redis" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest apps/core/tests/test_healthz.py -v`
Expected: FAIL (404 — no `/healthz/` route).

- [ ] **Step 3: Implement the view + route**

```python
# backend/apps/core/views.py
from django.db import connection
from django.http import JsonResponse
from django.conf import settings
import redis

def healthz(request):
    db_ok = False
    try:
        connection.cursor().execute("SELECT 1")
        db_ok = True
    except Exception:
        db_ok = False
    redis_ok = False
    try:
        redis.from_url(settings.REDIS_URL).ping()
        redis_ok = True
    except Exception:
        redis_ok = False
    status = "ok" if db_ok else "degraded"
    return JsonResponse({"status": status, "db": db_ok, "redis": redis_ok})
```

```python
# backend/config/urls.py
from django.contrib import admin
from django.urls import path
from apps.core.views import healthz

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("healthz/", healthz),
]
```

- [ ] **Step 4: Add pytest config**

```ini
# backend/pytest.ini
[pytest]
DJANGO_SETTINGS_MODULE = config.settings.dev
python_files = tests.py test_*.py *_tests.py
```

- [ ] **Step 5: Run test to verify it passes** (needs the dev DB up — Task 5 compose, or SQLite fallback in dev.py for this test)

Run: `uv run pytest apps/core/tests/test_healthz.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/
git commit -m "feat(backend): django skeleton with /healthz/ endpoint (TDD)"
```

---

### Task 4: Local dev services — docker-compose.dev.yml

**Files:**
- Create: `docker-compose.dev.yml`

- [ ] **Step 1: Write compose file** (Postgres 16, Redis 7, Meilisearch; dev ports 5433/6380/7700)

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment: { POSTGRES_USER: toke, POSTGRES_PASSWORD: toke, POSTGRES_DB: toke }
    ports: ["5433:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]
  redis:
    image: redis:7-alpine
    ports: ["6380:6379"]
  meilisearch:
    image: getmeili/meilisearch:v1.10
    environment: { MEILI_MASTER_KEY: devmasterkey, MEILI_ENV: development }
    ports: ["7700:7700"]
    volumes: ["meili:/meili_data"]
volumes: { pgdata: {}, meili: {} }
```

- [ ] **Step 2: Bring services up + verify healthz against real DB/Redis**

```bash
docker compose -f docker-compose.dev.yml up -d
uv --project backend run python backend/manage.py migrate
uv --project backend run pytest backend/apps/core/tests/test_healthz.py -v   # PASS, db+redis True
```

- [ ] **Step 3: Commit**

```bash
git add docker-compose.dev.yml
git commit -m "chore: local dev services (postgres/redis/meilisearch)"
```

---

### Task 5: Storefront Next.js app

**Files:** `storefront/**`

- [ ] **Step 1: Scaffold**

```bash
npx create-next-app@latest storefront --ts --tailwind --app --src-dir --eslint --use-npm --no-import-alias
```

- [ ] **Step 2: Home page renders the brand placeholder**

Edit `storefront/src/app/page.tsx` to render `Toke Cosmetics — coming soon`.

- [ ] **Step 3: Verify build + dev**

Run: `cd storefront && npm run build`
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add storefront/
git commit -m "feat(storefront): next.js app scaffold with coming-soon home"
```

---

### Task 6: Admin Next.js app

**Files:** `admin/**`

- [ ] **Step 1: Scaffold** (same flags as storefront)

```bash
npx create-next-app@latest admin --ts --tailwind --app --src-dir --eslint --use-npm --no-import-alias
```

- [ ] **Step 2: Login placeholder page**

Edit `admin/src/app/page.tsx` to render a simple "Toke Admin — sign in" placeholder.

- [ ] **Step 3: Verify build**

Run: `cd admin && npm run build`
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add admin/
git commit -m "feat(admin): next.js app scaffold with login placeholder"
```

---

### Task 7: CI — GitHub Actions

**Files:** `.github/workflows/ci-backend.yml`, `.github/workflows/ci-frontend.yml`

- [ ] **Step 1: Backend CI** (uv sync, ruff, pytest with Postgres + Redis services)

```yaml
# .github/workflows/ci-backend.yml
name: ci-backend
on: { push: {}, pull_request: {} }
jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres: { image: postgres:16, env: { POSTGRES_USER: toke, POSTGRES_PASSWORD: toke, POSTGRES_DB: toke }, ports: ["5432:5432"], options: >-
        --health-cmd "pg_isready -U toke" --health-interval 10s --health-timeout 5s --health-retries 5 }
      redis: { image: redis:7, ports: ["6379:6379"] }
    env:
      DATABASE_URL: postgres://toke:toke@localhost:5432/toke
      REDIS_URL: redis://localhost:6379/0
      SECRET_KEY: ci-not-secret
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --project backend
      - run: uv run --project backend ruff check .
      - run: uv run --project backend pytest -v
        working-directory: backend
```

- [ ] **Step 2: Frontend CI** (`next build` for each app)

```yaml
# .github/workflows/ci-frontend.yml
name: ci-frontend
on: { push: {}, pull_request: {} }
jobs:
  build:
    runs-on: ubuntu-latest
    strategy: { matrix: { app: [storefront, admin] } }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 22 }
      - run: npm ci
        working-directory: ${{ matrix.app }}
      - run: npm run build
        working-directory: ${{ matrix.app }}
```

- [ ] **Step 3: Commit**

```bash
git add .github/
git commit -m "ci: backend (ruff+pytest) and frontend (next build) workflows"
```

---

### Task 8: docs/architecture.md + push

**Files:** `docs/architecture.md`

- [ ] **Step 1: Write architecture.md** — condensed §3 (target architecture, domain plan, monorepo layout) + §4 (decisions already made) from master-tokerebuild.md, plus the Plan-00 findings that change things (3 order sources; no SKUs/stock → manual counts; coupons start fresh; loyalty not preserved).

- [ ] **Step 2: Commit + push**

```bash
git add docs/architecture.md
git commit -m "docs: architecture overview"
git push -u origin main
```

- [ ] **Step 3: Verify CI green** on GitHub Actions.

---

## Verification (whole stage)

Fresh clone → `docker compose -f docker-compose.dev.yml up -d` → `uv run --project backend pytest` green (healthz db+redis True) → `npm run dev` in each app loads in a browser → CI green on GitHub.

## CHECKPOINT

Show Hammed the repo URL and the green CI badge.
