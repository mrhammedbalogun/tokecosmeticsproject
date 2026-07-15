# Plan-03 Django Core — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (inline). Steps use `- [ ]`.

> **Update 2026-07-15 (supersedes the email design below):** Email is now **Resend as the sole provider** — the Mailgun-primary/Amazon-SES-fallback wrapper described in Task 6 was replaced. `send.py` sends via the single default backend with no fallback; the Celery task handles retries. Live Resend send verified (message id `618bccf2-2264-4ddf-835e-eb6618902fb8`). The SES-fallback steps in Task 6 are kept as a historical record only.

**Goal:** Backend foundation every later stage builds on — custom User (+ Toke ID), structured Address + Region tree, SimpleJWT auth endpoints, email send wrapper (Resend, sole provider) via Celery, S3 storage config, Celery wiring, security baseline, core models (SiteSetting, Redirect), and OpenAPI docs.

**Architecture:** Extend the `apps/core` + new `apps/accounts` + `apps/notifications` apps. Custom user with email login and a public `TK-XXXXXX` id. JWT with rotation + blacklist. Email + Celery are code-complete now; real Resend/S3 *delivery* smoke is deferred until Hammed supplies keys (console/locmem backends + mocks used for tests). [2026-07-15: Resend key supplied, live send verified.]

**Tech Stack:** Django 5.2, DRF, djangorestframework-simplejwt, drf-spectacular, celery[redis], django-cors-headers, django-anymail[resend], django-storages[s3], django-filter, factory_boy (dev).

**Environment:** `uv run --project backend …`; Python 3.12; local services via `docker-compose.dev.yml`.

**Credentials NOT yet provided (defer real smoke, keep code + mocked tests):** ~~MAILGUN_API_KEY~~ RESEND_API_KEY, AWS S3 keys. [2026-07-15: both supplied; live Resend send verified.]

**Deviation from master §Plan-03 item 3:** the WordPress password hasher (full code + tests) stays in **Plan-22** to avoid wiring a class that has no test coverage yet; `PASSWORD_HASHERS` keeps Django defaults now, with a documented TODO. All other Plan-03 items are implemented here.

---

## File Structure

```
backend/apps/core/
  models.py            # TimeStampedModel, SiteSetting, Redirect, Region
  address_rules.py     # per-country required-field map
apps/accounts/
  models.py            # User, UserManager, Address, generate_toke_id
  managers.py
  serializers.py       # Register, Me, PasswordReset(+Confirm), Address
  views.py             # auth endpoints + me + addresses (addresses full in Plan-11; here: me)
  urls.py
  tests/               # test_user, test_tokeid, test_auth_flow, test_address_rules
apps/notifications/
  send.py              # send_email(template, to, context) via Resend (sole provider, no fallback)
  tasks.py             # send_email_task (Celery)
  templates/email/…    # base + password_reset
config/
  celery.py            # Celery app
  settings/base.py     # + apps, DRF auth/throttle, spectacular, security, storages, email, celery
  urls.py              # /api/v1/auth/…, /api/schema/, /api/docs/
```

---

### Task 1: Dependencies + app registration

- [ ] **Step 1: Add deps**
```bash
cd backend
uv add djangorestframework-simplejwt drf-spectacular "celery[redis]" django-cors-headers \
  "django-anymail[resend]" "django-storages[s3]" django-filter
uv add --dev factory-boy
```
- [ ] **Step 2: Register apps** in `base.py` INSTALLED_APPS: `rest_framework_simplejwt.token_blacklist`, `corsheaders`, `drf_spectacular`, `django_filters`, `anymail`, `storages`, `apps.accounts`, `apps.notifications`. Add `corsheaders.middleware.CorsMiddleware` high in MIDDLEWARE.
- [ ] **Step 3:** `uv run python manage.py check` → no issues. Commit `chore(backend): add core dependencies`.

---

### Task 2: Custom User + Toke ID (TDD) — DO FIRST

**Files:** `apps/accounts/models.py`, `apps/accounts/managers.py`, test `apps/accounts/tests/test_tokeid.py`, `test_user.py`

- [ ] **Step 1: Failing test — toke id format**
```python
# apps/accounts/tests/test_tokeid.py
import re
from apps.accounts.models import generate_toke_id, TOKE_ID_ALPHABET

def test_toke_id_shape():
    tid = generate_toke_id()
    assert tid.startswith("TK-")
    assert len(tid) == 9
    assert re.fullmatch(f"TK-[{TOKE_ID_ALPHABET}]{{6}}", tid)

def test_toke_id_alphabet_excludes_ambiguous():
    for ch in "01OIL":
        assert ch not in TOKE_ID_ALPHABET
```
- [ ] **Step 2:** run → FAIL (import error).
- [ ] **Step 3: Implement** `generate_toke_id` + `TOKE_ID_ALPHABET`, `UserManager` (create_user/create_superuser, assigns toke_id in a retry loop on IntegrityError), and `User(AbstractBaseUser, PermissionsMixin)` exactly per master §Plan-03 item 1 (email USERNAME_FIELD, toke_id unique editable=False, marketing_consent, legacy_source, legacy_wp_id, legacy_wp_id_intl nullable).
- [ ] **Step 4: Failing test — user create + toke id assigned + email login field**
```python
# apps/accounts/tests/test_user.py
import pytest
from django.contrib.auth import get_user_model

@pytest.mark.django_db
def test_create_user_assigns_toke_id():
    U = get_user_model()
    u = U.objects.create_user(email="a@b.com", password="x")
    assert u.toke_id.startswith("TK-")
    assert U.USERNAME_FIELD == "email"

@pytest.mark.django_db
def test_email_is_unique():
    U = get_user_model()
    U.objects.create_user(email="a@b.com", password="x")
    with pytest.raises(Exception):
        U.objects.create_user(email="a@b.com", password="y")
```
- [ ] **Step 5:** set `AUTH_USER_MODEL = "accounts.User"` in base.py; `uv run python manage.py makemigrations accounts`.
- [ ] **Step 6:** run tests → PASS. Commit `feat(accounts): custom User with Toke ID (TDD)`.

---

### Task 3: Core base models — TimeStampedModel, SiteSetting, Redirect

**Files:** `apps/core/models.py`, test `apps/core/tests/test_core_models.py`

- [ ] **Step 1: Failing test**
```python
# apps/core/tests/test_core_models.py
import pytest
from apps.core.models import SiteSetting, Redirect

@pytest.mark.django_db
def test_sitesetting_typed_get():
    SiteSetting.objects.create(key="free_ship_min", value="15000", value_type="int")
    assert SiteSetting.get_typed("free_ship_min") == 15000

@pytest.mark.django_db
def test_redirect_defaults_301():
    r = Redirect.objects.create(old_path="/x/", new_path="/y")
    assert r.status_code == 301 and r.hits == 0
```
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3: Implement** `TimeStampedModel(abstract, created_at/updated_at)`, `SiteSetting(key unique, value text, value_type[str/int/bool/json], get_typed classmethod)`, `Redirect(old_path unique, new_path, status_code default 301, hits default 0)`.
- [ ] **Step 4:** makemigrations core; run → PASS. Commit `feat(core): TimeStampedModel, SiteSetting, Redirect`.

---

### Task 4: Region tree + structured Address + per-country rules (TDD)

**Files:** `apps/core/models.py` (+Region), `apps/accounts/models.py` (+Address), `apps/core/address_rules.py`, test `apps/accounts/tests/test_address_rules.py`

- [ ] **Step 1: Failing test — address rules**
```python
# apps/accounts/tests/test_address_rules.py
from apps.core.address_rules import required_fields_for

def test_ng_requires_state_region():
    req = required_fields_for("NG")
    assert "state_region" in req
def test_gb_requires_postcode():
    assert "postcode" in required_fields_for("GB")
```
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3: Implement** `Region(country_code, name, level[state/city/area], parent self FK, is_active, unique_together (country_code,parent,name))`; `Address` per master §Plan-03 item 1 (FK user, structured fields, `state_region`/`area_region` FK core.Region PROTECT, `*_text` fallbacks, defaults flags); `address_rules.py::required_fields_for(country_code)` returning the per-country required set (NG: state_region [+area_region when state has children]; GB/US/CA: postcode + city_text/state_text).
- [ ] **Step 4:** makemigrations; run → PASS. Commit `feat: Region tree + structured Address + per-country rules`.

---

### Task 5: SimpleJWT auth endpoints (TDD)

**Files:** `config/settings/base.py` (SIMPLE_JWT, DRF auth), `apps/accounts/serializers.py`, `apps/accounts/views.py`, `apps/accounts/urls.py`, `config/urls.py`, test `apps/accounts/tests/test_auth_flow.py`

- [ ] **Step 1: Failing test — register→login→me→refresh→logout**
```python
# apps/accounts/tests/test_auth_flow.py
import pytest
from rest_framework.test import APIClient

@pytest.mark.django_db
def test_register_login_me_flow():
    c = APIClient()
    r = c.post("/api/v1/auth/register/", {"email":"a@b.com","password":"Str0ng!pass9","first_name":"A"}, format="json")
    assert r.status_code == 201
    r = c.post("/api/v1/auth/token/", {"email":"a@b.com","password":"Str0ng!pass9"}, format="json")
    assert r.status_code == 200 and "access" in r.data
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")
    me = c.get("/api/v1/auth/me/")
    assert me.status_code == 200 and me.data["email"] == "a@b.com" and me.data["toke_id"].startswith("TK-")

@pytest.mark.django_db
def test_duplicate_email_clean_400():
    c = APIClient()
    payload = {"email":"a@b.com","password":"Str0ng!pass9"}
    c.post("/api/v1/auth/register/", payload, format="json")
    r = c.post("/api/v1/auth/register/", payload, format="json")
    assert r.status_code == 400 and "email" in r.data
```
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3: Implement** SIMPLE_JWT (access 15min, refresh 30d, ROTATE + BLACKLIST), DRF DEFAULT_AUTHENTICATION_CLASSES=JWT, `RegisterSerializer` (validate_password, clean duplicate-email 400 `{"email":["Account already exists"]}`), `MeSerializer` (read-only toke_id), views: register (CreateAPIView), token/refresh (simplejwt views), logout (blacklist refresh), password/reset + confirm (email token), me (RetrieveUpdate). Wire `apps/accounts/urls.py` under `/api/v1/auth/` and include in `config/urls.py`.
- [ ] **Step 4:** run → PASS. Commit `feat(accounts): SimpleJWT auth endpoints (TDD)`.

---

### Task 6: Email send wrapper + Celery task (TDD, mocked)

> ⚠️ **SUPERSEDED 2026-07-15 — read this before the steps below.** The Mailgun→SES fallback described in Steps 1–4 was replaced by **Resend as the sole provider, no fallback**. Current behavior: `send.py` renders the templates and sends via the single default backend (`anymail.backends.resend.EmailBackend` in prod, console in dev/tests); a send failure bubbles up so `send_email_task` retries with backoff. The `_send_via` helper and the "falls back to SES" test were removed. The steps below are retained only as a record of the original plan.

**Files:** `apps/notifications/send.py`, `apps/notifications/tasks.py`, `apps/notifications/templates/email/{base.html,password_reset.{html,txt}}`, test `apps/notifications/tests/test_send.py`

- [ ] **Step 1: Failing test — send uses backend; falls back to SES on Mailgun error**
```python
# apps/notifications/tests/test_send.py
from unittest import mock
from django.core import mail
from apps.notifications.send import send_email

def test_send_email_renders_and_sends(db, settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    send_email("password_reset", "a@b.com", {"reset_url":"https://x/y","first_name":"A"})
    assert len(mail.outbox) == 1
    assert "a@b.com" in mail.outbox[0].to

def test_send_email_falls_back_to_ses(db):
    from anymail.exceptions import AnymailAPIError
    with mock.patch("apps.notifications.send._send_via", side_effect=[AnymailAPIError("boom"), None]) as m:
        send_email("password_reset", "a@b.com", {"reset_url":"https://x/y","first_name":"A"})
        assert m.call_count == 2   # mailgun then ses
```
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3: Implement** `send_email(template_name, to, context)` rendering `email/<template>.html` + `.txt`, sending via default connection, and on `AnymailAPIError` retrying once via a SES connection (`get_connection("anymail.backends.amazon_ses.EmailBackend")`); factor the actual send into `_send_via(connection, ...)` so the test can patch it. `tasks.py::send_email_task` = Celery task wrapping it with retry/backoff. Base + password_reset templates (simple HTML + text).
- [ ] **Step 4:** run → PASS. Commit `feat(notifications): email send wrapper with SES fallback (TDD)`.

---

### Task 7: Celery app + demo task

**Files:** `config/celery.py`, `config/__init__.py`, `apps/core/tasks.py`, base.py (CELERY_*)

- [ ] **Step 1:** Implement `config/celery.py` (Celery("config"), broker/result = REDIS/CELERY_BROKER_URL env, autodiscover), import in `config/__init__.py`. `apps/core/tasks.py::ping` returns "pong". Beat schedule (dev only) runs ping every 5 min. `CELERY_TASK_ALWAYS_EAGER=True` in dev/test.
- [ ] **Step 2: Test**
```python
# apps/core/tests/test_tasks.py
from apps.core.tasks import ping
def test_ping():
    assert ping.apply().get() == "pong"
```
- [ ] **Step 3:** run → PASS. Commit `feat(backend): celery app + ping task`.

---

### Task 8: Storage (S3) + static (whitenoise) config

- [ ] **Step 1:** In `base.py` set `STORAGES` — default = S3 (django-storages) when `AWS_STORAGE_BUCKET_NAME` env set, else FileSystemStorage (dev); `AWS_QUERYSTRING_AUTH=False`, public `media/catalog/`. Add `whitenoise` to deps + middleware; `STATICFILES_STORAGE` = whitenoise. `.env.example` += AWS_* keys.
- [ ] **Step 2:** `uv run python manage.py check` clean; `collectstatic --noinput --dry-run` OK. Commit `chore(backend): s3 media + whitenoise static config`.
- [ ] Real S3 upload smoke deferred (needs AWS keys).

---

### Task 9: Security baseline + CORS + throttles

- [ ] **Step 1:** In `prod.py`: `SECURE_HSTS_SECONDS=31536000`, HSTS subdomains+preload, `SESSION_COOKIE_SECURE`/`CSRF_COOKIE_SECURE=True`, `X_FRAME_OPTIONS="DENY"`, `SECURE_REFERRER_POLICY`, `SECURE_SSL_REDIRECT` via proxy header. `base.py`: `CORS_ALLOWED_ORIGINS` = env list (three frontend origins), DRF `DEFAULT_THROTTLE_CLASSES/RATES` (anon 60/min, user 120/min), `ATOMIC_REQUESTS=True` on the DB.
- [ ] **Step 2:** `manage.py check --deploy` shows only expected dev warnings; a throttle test hits the limit. Commit `feat(backend): security baseline, CORS allowlist, DRF throttles`.

---

### Task 10: drf-spectacular schema + docs

- [ ] **Step 1:** DRF `DEFAULT_SCHEMA_CLASS = drf_spectacular`; `SPECTACULAR_SETTINGS` (title, version v1). Routes: `/api/schema/`, `/api/docs/` (SpectacularSwaggerView; staff-only permission in prod).
- [ ] **Step 2: Test** `GET /api/schema/` → 200 and lists `/api/v1/auth/register/`.
- [ ] **Step 3:** run → PASS. Commit `feat(backend): OpenAPI schema + Swagger docs`.

---

### Task 11: Full-suite verify + push

- [ ] `uv run pytest -v` all green; `manage.py check` clean; run flow once against the live docker services. Push; CI green. Update `.env.example` + `docs/architecture.md` status.

## Verification (stage)

pytest covers register→login→refresh→me→logout, toke-id, address rules, email send + error-propagation (mocked/locmem), ping task, schema endpoint. `manage.py migrate` clean on Postgres. **Deferred (need creds):** real Resend inbox email + real S3 upload — do at Plan-03 checkpoint once keys arrive. [2026-07-15: Resend inbox email done — live send accepted, id `618bccf2-2264-4ddf-835e-eb6618902fb8`. S3 upload smoke done — write/read/delete round-trip against the live bucket passed.]

## CHECKPOINT

Show Hammed Swagger UI at `/api/docs/` (served locally), the passing test suite, and the list of what's blocked on credentials (Resend key ✅ supplied, AWS S3 keys ✅ supplied) to unblock the real email/upload smokes. [2026-07-15: Resend email smoke done; S3 upload smoke done — both green.]
