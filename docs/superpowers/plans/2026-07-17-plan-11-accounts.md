# Plan-11 — Customer accounts (profile, addresses, wishlist, reviews, newsletter) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Everything a logged-in customer can do, API-side — manage addresses, edit their profile, change their password, request account deletion, keep a wishlist, and leave verified-purchase reviews — plus public newsletter capture and legacy guest-order claiming on email verification.

**Architecture:** Extend `apps/accounts` (profile/password/deletion/addresses/email-verification) and add three small apps: `apps/wishlist`, `apps/reviews`, `apps/newsletter`. Addresses reuse the structured `Address` model already shipped in Plan-03 and the single per-country rule source `apps.core.address_rules.required_fields_for`. Reviews denormalise `rating_avg`/`rating_count` onto `Product` on approval (the approval endpoint itself is Plan-18; the model, the Django-admin approval action, and the recompute service land now). Account deletion is a two-phase GDPR/NDPR pattern: `is_active=False` immediately, PII anonymised after 30 days by a Celery-beat task that mirrors the existing expiry/complete sweeps.

**Tech Stack:** Python 3.12 / Django 5.2 / DRF / djangorestframework-simplejwt / Postgres / Celery / pytest + factory_boy / ruff. Backend only — the storefront (Plan-12+) consumes these endpoints later.

**Spec:** `master-tokerebuild.md` lines 870–888 (Plan-11-accounts). Read them before Task 1.

**Branch:** `plan-11-accounts` off `main`.

---

## Decisions needing sign-off

These are genuinely ambiguous or carry a security/scope trade-off. **Get Hammed's answer before Task 12 / Task 6 / the reviews cluster** — the rest of the plan does not depend on them.

**D1 — Email verification for guest-order claiming (blocks Task 12). RECOMMENDED: build a minimal signed-token verification.**
The spec says migrated guest orders attach to an account *"on email verification"*, but **no email-verification flow exists today** — registration does not verify the address, and only password-reset proves control of an inbox.
- Attaching legacy orders on *bare registration* (email string match only) is **rejected**: anyone who registers with `victim@example.com` would inherit the victim's full order history, delivery addresses, and phone number — a PII-disclosure hole. The spec's "on verification" wording exists precisely to prevent this.
- **Recommendation (built in Task 12):** a minimal verification endpoint using `django.core.signing` (mirrors the existing `apps/orders/tokens.py` pattern — no new table). Registration emails a verify link; `POST /api/v1/auth/verify-email/` marks `email_verified_at` and *then* claims legacy orders. Password-reset-confirm also proves inbox control, so it sets `email_verified_at` and claims too. This is boring, uses machinery already in the repo, and closes the hole.
- Alternative if Hammed wants less now: claim **only** on password-reset-confirm (defer the verify-email endpoint). Task 12 notes exactly which steps to drop.

**D2 — "Synced to search index" for denormalised ratings (affects Task 9/10). RECOMMENDED: cache-invalidation now, Meilisearch push deferred to Plan-07b.**
Search today is `apps/search/backends.PostgresSearchBackend`, which reads live `Product` rows — there is **no separate index to sync**. Meilisearch is Plan-07b (not built). So on approval we recompute the fields, save the `Product` (which fires `apps/catalog/signals.py` → `bump_catalog_cache()`, invalidating every cached product card so the new rating shows), and stop there. When Plan-07b builds the Meilisearch document mapping it must include `rating_avg`/`rating_count`. **Recommendation:** do not invent a placeholder Meilisearch client now (YAGNI); record the requirement as a Plan-07b note. Confirm this is acceptable.

**D3 — Account-deletion anonymisation scrub (affects Task 6). RECOMMENDED scrub set below.**
After 30 days a deactivated account's PII is scrubbed but the **rows survive** (orders must stay reconcilable). Recommended scrub on the `User`: `email` → `deleted-<toke_id>@deleted.invalid`, `first_name`/`last_name`/`phone` → `""`, `marketing_consent=False`, `is_active=False`, `set_unusable_password()`. `toke_id` is kept (it is not PII — it is an opaque id). Orders keep `order.user` set to the now-anonymised user (so history stays linked but carries no PII); the order's own `email`/`shipping_address` JSON snapshot is **also** scrubbed in the same task. Addresses are deleted. Confirm the scrub set and whether order snapshots must be scrubbed too (recommended: yes).

**D4 — Newsletter model home. RECOMMENDED: a new `apps/newsletter`.**
`apps/notifications` is a **stateless send pipeline** — it has no `models.py` at all (just `send.py`, `tasks.py`, templates). `NewsletterSubscriber` is persistent list-membership state with its own lifecycle (consent, unsubscribe). Putting a model there would give the send-pipeline app a database identity it deliberately does not have. **Recommendation:** `apps/newsletter` owns subscriber state; `apps/notifications` stays the thing that *sends*. Campaign sending is Plan-30.

**D5 — Profile endpoint path (minor). RECOMMENDED: keep `auth/me/`, add the rest under `/api/v1/me/`.**
Profile GET/PATCH already exists at `/api/v1/auth/me/` (`MeView` + `MeSerializer`, with `toke_id`/`email` read-only) and already covers names, phone, and `marketing_consent`. The spec writes addresses/wishlist under `/api/v1/me/…`. **Recommendation:** leave the working profile endpoint where it is (storefront-facing already), mount addresses + wishlist under a new `/api/v1/me/` include, and add password-change + account-deletion under `/api/v1/auth/`. No profile rewrite. (If Hammed wants one canonical `/api/v1/me/` root, that is a bigger URL change — flag, don't silently do it.)

---

## Critical context for the implementer

You know nothing about this codebase. Read this before touching anything.

- **The user model is `apps.accounts.models.User`** (`AUTH_USER_MODEL`), email-as-username, with a permanent public `toke_id` (`TK-XXXXXX`, `editable=False`). Get it via `django.contrib.auth.get_user_model()`, never by importing the class in serializers.
- **`Address` already exists** (`apps/accounts/models.py`) with structured region FKs (`state_region`, `area_region` → `core.Region`) plus free-text fallbacks (`city_text`, `state_text`, `postcode`). Checkout already reads it. **There is no addresses CRUD API yet — that is this plan.** Do not add fields to the model unless a task says so.
- **Per-country address rules live in ONE place:** `apps.core.address_rules.required_fields_for(country_code)` → a `set` of required field names. `NG` requires `state_region`; `GB`/`US`/`CA` require `postcode` + `city_text`; everything else requires `city_text`. The serializer MUST use this function, never re-encode the rules.
- **Region dropdowns already have an endpoint:** `GET /api/v1/meta/regions/?country=NG` (top-level states) and `?parent=<id>` (children). `Region` rows carry `country_code`, `level` (`state`/`city`/`area`), and a self-FK `parent`.
- **Verified purchase = an `Order` for this user with `status in ("delivered", "completed")` containing the product.** Both statuses count: `completed` is `delivered` + return-window elapsed (set by the daily `complete_delivered_orders` beat task, whose docstring explicitly says Plan-11's review rule reads it). `OrderItem.variant` → `catalog.ProductVariant`; a variant's product is `variant.product`.
- **Migrated WordPress guest orders (Plan-22, not yet run) have `user=None` and a stored `email`.** New orders always have a user (Decision 7). So "claimable legacy orders" = `Order.objects.filter(user__isnull=True, email__iexact=<addr>)`. Test with synthetic user-less orders — do not wait for Plan-22.
- **Celery beat schedule is a dict** in `config/settings/base.py:230` (`CELERY_BEAT_SCHEDULE`). Existing periodic sweeps (`expire_pending_orders` every 5 min, `complete_delivered_orders` daily) show the pattern: a `@shared_task` in `apps/<app>/tasks.py`, **one transaction per row**, re-checking under `select_for_update()`, wrapped in per-row `try/except` so one poison row cannot starve the sweep. Follow it exactly.
- **Signed tokens** (unsubscribe, email-verify) mirror `apps/orders/tokens.py`: `django.core.signing.dumps/loads` with a per-scope `salt` and a `max_age` — **no table, HMAC'd with `SECRET_KEY`**. Read the payload out of the token; never trust an id from the URL.
- **Emails** go through `apps.notifications.tasks.send_email_task.delay(template_name, to, context)`; templates live at `apps/notifications/templates/email/<name>.{subject.txt,txt,html}`. In dev/test `CELERY_TASK_ALWAYS_EAGER=True`, so `.delay(...)` runs synchronously and you can assert on `django.core.mail.outbox`.
- **Tests:** pytest-django. Build users inline with the `django_user_model` fixture — `django_user_model.objects.create_user(email=..., password=..., is_staff=True)`. **There is no shared `staff_user`/`admin_client` fixture** — do not reference one. `APIClient().force_authenticate(user)` for auth'd calls. `Country`/`Currency` rows (`NG`,`GB`,`US`,`CA`,`ZZ`,`NGN`,…) and NG regions are seeded by migrations — `Country.objects.get(code="NG")` works in any `@pytest.mark.django_db` test. Factories: `apps/orders/factories.OrderFactory` (minimal — pass `number`/`country`/`currency`), `apps/catalog/factories.{ProductFactory,ProductVariantFactory,PriceFactory}`.

**Money / scope guardrails (standing project rules — do not break):**
- **Do NOT touch payments, shipping, checkout, or delivery pricing code paths.** This plan is customer-account surface only. If a review/claim/deletion path seems to need a checkout change, stop and flag it.
- **Do NOT add any tolerance band or fuzzy matching anywhere near payment amounts.** Nothing in this plan compares money, but the rule stands.
- **Anonymisation and deletion touch real customer data.** Every destructive task re-checks state under a lock and is idempotent (a double beat-run must be safe).

**Commands:**

```bash
cd tokecosmetics-platform/backend
uv run pytest apps/accounts apps/wishlist apps/reviews apps/newsletter -q   # scope to this plan's apps
uv run pytest -q                                                            # full suite (~451 passed, 1 skipped baseline)
uv run ruff check .                                                         # must be clean before every commit
uv run python manage.py makemigrations                                      # never hand-number migrations
```

Windows note: use `uv run` for every Python/Django command (the project convention).

---

## File structure

| File | Responsibility | Task |
|---|---|---|
| `backend/apps/accounts/serializers.py` | + `PasswordChangeSerializer`, `AddressSerializer`, `AccountDeletionSerializer`, `EmailVerifySerializer` | 1, 2, 5, 12 |
| `backend/apps/accounts/views.py` | + password-change, address CRUD, set-default, deletion, verify-email views | 1, 3, 5, 12 |
| `backend/apps/accounts/me_urls.py` | **new** — `/api/v1/me/…` router (addresses, wishlist mount) | 3 |
| `backend/apps/accounts/urls.py` | + `password/change/`, `account/delete/`, `verify-email/` | 1, 5, 12 |
| `backend/apps/accounts/models.py` | + `User.deletion_requested_at`, `User.email_verified_at` | 5 |
| `backend/apps/accounts/verification.py` | **new** — signed email-verify token (mirrors orders/tokens.py) | 12 |
| `backend/apps/accounts/claims.py` | **new** — `claim_legacy_orders(user)` | 12 |
| `backend/apps/accounts/tasks.py` | **new** — `anonymize_deleted_accounts` beat task | 6 |
| `backend/apps/accounts/admin.py` | **new** — register `User`/`Address` (read-only PII audit view) | 5 |
| `backend/apps/wishlist/` | **new app** — `WishlistItem` model + API | 7, 8 |
| `backend/apps/reviews/` | **new app** — `Review` model + admin approve action + API | 10, 11 |
| `backend/apps/reviews/services.py` | `recompute_product_rating` | 10 |
| `backend/apps/newsletter/` | **new app** — `NewsletterSubscriber` + capture/unsubscribe | 13 |
| `backend/apps/catalog/models.py` | + `Product.rating_avg`, `Product.rating_count` | 9 |
| `backend/apps/catalog/api_serializers.py` | expose rating on list + detail serializers | 9 |
| `backend/config/settings/base.py` | `INSTALLED_APPS` (+3 apps), throttle rate `newsletter`, beat entry | 6, 7, 10, 13 |
| `backend/config/urls.py` | mount `me/`, reviews, newsletter includes | 3, 8, 11, 13 |
| `docs/architecture.md` | § Accounts (deletion, claiming, review moderation) | 14 |

**Task order is a dependency chain.** Task 9 (rating fields) lands before Task 10 (which adds the recompute service Task 11 calls). Task 7 (wishlist model) before Task 8 (its API). Task 5 (deletion fields) before Task 6 (the sweep that reads them). Task 12 (verify-email) depends on D1.

**Why three new apps rather than piling onto `accounts`:** wishlist and reviews are independent aggregates with their own lifecycles and admin surfaces; `newsletter` is public/anonymous and must not import auth. Keeping them apart keeps each `models.py` small and each app's tests fast and scoped (the `uv run pytest apps/<app>` habit the team relies on while other work is in flight).

---

### Task 0: Branch

- [ ] **Step 1: Cut the branch**

```bash
cd tokecosmetics-platform
git checkout main
git status --short          # must be empty
git checkout -b plan-11-accounts
```

---

### Task 1: Password change endpoint

**Why:** logged-in password change needs the OLD password (an authenticated session is not consent to change credentials — a shoulder-surfer or a borrowed laptop must not be able to lock the owner out). Password *reset* (forgot-password, no old password) already exists and is separate.

**Files:**
- Modify: `backend/apps/accounts/serializers.py`
- Modify: `backend/apps/accounts/views.py`
- Modify: `backend/apps/accounts/urls.py`
- Test: `backend/apps/accounts/tests/test_password_change.py` (create)

- [ ] **Step 1: Write the failing tests**

`backend/apps/accounts/tests/test_password_change.py`:

```python
import pytest
from rest_framework.test import APIClient

PW = "Str0ng!pass9"
NEW = "N3w!pass9word"


@pytest.mark.django_db
def test_password_change_requires_correct_old_password(django_user_model):
    user = django_user_model.objects.create_user(email="a@b.com", password=PW)
    c = APIClient()
    c.force_authenticate(user)

    r = c.post("/api/v1/auth/password/change/",
               {"old_password": "wrong", "new_password": NEW}, format="json")

    assert r.status_code == 400
    assert "old_password" in r.data
    user.refresh_from_db()
    assert user.check_password(PW)          # unchanged


@pytest.mark.django_db
def test_password_change_succeeds_with_correct_old_password(django_user_model):
    user = django_user_model.objects.create_user(email="a@b.com", password=PW)
    c = APIClient()
    c.force_authenticate(user)

    r = c.post("/api/v1/auth/password/change/",
               {"old_password": PW, "new_password": NEW}, format="json")

    assert r.status_code == 200
    user.refresh_from_db()
    assert user.check_password(NEW)


@pytest.mark.django_db
def test_password_change_rejects_weak_new_password(django_user_model):
    user = django_user_model.objects.create_user(email="a@b.com", password=PW)
    c = APIClient()
    c.force_authenticate(user)

    r = c.post("/api/v1/auth/password/change/",
               {"old_password": PW, "new_password": "123"}, format="json")

    assert r.status_code == 400
    assert "new_password" in r.data


@pytest.mark.django_db
def test_password_change_requires_auth():
    r = APIClient().post("/api/v1/auth/password/change/",
                         {"old_password": PW, "new_password": NEW}, format="json")
    assert r.status_code in (401, 403)
```

- [ ] **Step 2: Run to verify failure**

```bash
cd tokecosmetics-platform/backend
uv run pytest apps/accounts/tests/test_password_change.py -q
```

Expected: FAIL — 404 (URL not wired).

- [ ] **Step 3: Serializer**

Append to `backend/apps/accounts/serializers.py`:

```python
class PasswordChangeSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, validators=[validate_password])

    def validate_old_password(self, value):
        # self.context["request"].user is guaranteed by IsAuthenticated on the view.
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value
```

- [ ] **Step 4: View**

Append to `backend/apps/accounts/views.py` (add `PasswordChangeSerializer` to the existing import block from `.serializers`):

```python
class PasswordChangeView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = PasswordChangeSerializer

    @extend_schema(request=PasswordChangeSerializer, responses={200: None})
    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = request.user
        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password"])
        return Response({"detail": "Password updated."})
```

- [ ] **Step 5: URL**

In `backend/apps/accounts/urls.py`, add `PasswordChangeView` to the imports and this line to `urlpatterns`:

```python
    path("password/change/", PasswordChangeView.as_view(), name="password_change"),
```

- [ ] **Step 6: Run tests**

```bash
uv run pytest apps/accounts/tests/test_password_change.py -q
```

Expected: PASS.

- [ ] **Step 7: Mutation-verify**

In `validate_old_password`, change `if not ...check_password(value)` to `if False`. Confirm `test_password_change_requires_correct_old_password` goes RED. Revert.

- [ ] **Step 8: Commit**

```bash
git add apps/accounts
git commit -m "feat: authenticated password-change endpoint (old password required)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Address serializer with per-country validation

**Why:** the structured `Address` model exists but nothing validates it per country yet. The serializer is the single enforcement point that turns `address_rules.required_fields_for` into 400s, and it must also keep the region FKs internally consistent (an `area_region` whose parent is not the chosen `state_region`, or a `state_region` in the wrong country, is a data-integrity bug that would misroute delivery).

**Files:**
- Modify: `backend/apps/accounts/serializers.py`
- Test: `backend/apps/accounts/tests/test_address_serializer.py` (create)

- [ ] **Step 1: Write the failing tests**

`backend/apps/accounts/tests/test_address_serializer.py`:

```python
import pytest

from apps.accounts.serializers import AddressSerializer
from apps.core.models import Region


@pytest.mark.django_db
def test_ng_address_requires_a_state_region():
    """NG is a region country: required_fields_for('NG') demands state_region."""
    s = AddressSerializer(data={
        "label": "Home", "first_name": "Ada", "phone": "08012345678",
        "line1": "1 Allen Ave", "country_code": "NG",
    })
    assert not s.is_valid()
    assert "state_region" in s.errors


@pytest.mark.django_db
def test_ng_address_with_valid_state_region_is_accepted():
    lagos = Region.objects.create(country_code="NG", name="Lagos", level="state")
    s = AddressSerializer(data={
        "first_name": "Ada", "phone": "08012345678", "line1": "1 Allen Ave",
        "country_code": "NG", "state_region": lagos.id,
    })
    assert s.is_valid(), s.errors


@pytest.mark.django_db
def test_ng_area_region_must_be_a_child_of_the_chosen_state():
    lagos = Region.objects.create(country_code="NG", name="Lagos", level="state")
    abuja = Region.objects.create(country_code="NG", name="Abuja", level="state")
    garki = Region.objects.create(country_code="NG", name="Garki", level="area", parent=abuja)
    s = AddressSerializer(data={
        "first_name": "Ada", "phone": "08012345678", "line1": "1 Allen Ave",
        "country_code": "NG", "state_region": lagos.id, "area_region": garki.id,
    })
    assert not s.is_valid()
    assert "area_region" in s.errors


@pytest.mark.django_db
def test_state_region_must_be_in_the_declared_country():
    lagos = Region.objects.create(country_code="NG", name="Lagos", level="state")
    s = AddressSerializer(data={
        "first_name": "Ada", "phone": "08012345678", "line1": "1 Allen Ave",
        "country_code": "GB", "state_region": lagos.id,
    })
    assert not s.is_valid()
    assert "state_region" in s.errors


@pytest.mark.django_db
def test_gb_address_requires_a_postcode():
    s = AddressSerializer(data={
        "first_name": "Ada", "phone": "07123456789", "line1": "1 Baker St",
        "country_code": "GB", "city_text": "London",
    })
    assert not s.is_valid()
    assert "postcode" in s.errors


@pytest.mark.django_db
def test_gb_address_with_city_and_postcode_is_accepted():
    s = AddressSerializer(data={
        "first_name": "Ada", "phone": "07123456789", "line1": "1 Baker St",
        "country_code": "GB", "city_text": "London", "postcode": "NW1 6XE",
    })
    assert s.is_valid(), s.errors


@pytest.mark.django_db
def test_unknown_country_needs_city_but_no_postcode():
    s = AddressSerializer(data={
        "first_name": "Ada", "phone": "0600000000", "line1": "1 Rue",
        "country_code": "FR", "city_text": "Paris",
    })
    assert s.is_valid(), s.errors
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest apps/accounts/tests/test_address_serializer.py -q
```

Expected: FAIL — `ImportError: cannot import name 'AddressSerializer'`.

- [ ] **Step 3: Implement the serializer**

Append to `backend/apps/accounts/serializers.py` (add `from apps.accounts.models import Address` and `from apps.core.address_rules import required_fields_for` and `from apps.core.models import Region` at the top):

```python
class AddressSerializer(serializers.ModelSerializer):
    """Structured, per-country address. The per-country required-field rules come from
    the single source apps.core.address_rules.required_fields_for so the serializer and
    any admin form can never disagree about what NG vs GB requires."""

    class Meta:
        model = Address
        fields = [
            "id", "label", "first_name", "last_name", "phone",
            "line1", "line2", "country_code",
            "state_region", "area_region", "city_text", "state_text", "postcode",
            "is_default_shipping", "is_default_billing",
        ]
        read_only_fields = ["id", "is_default_shipping", "is_default_billing"]

    def validate_country_code(self, value):
        return (value or "").upper()

    def validate(self, attrs):
        # On PATCH, fall back to the instance's current values for anything not sent.
        def get(name):
            if name in attrs:
                return attrs[name]
            return getattr(self.instance, name, None)

        country = (get("country_code") or "").upper()
        errors = {}

        # 1. Per-country required fields (single source of truth).
        for field in required_fields_for(country):
            if not get(field):
                errors[field] = "This field is required for this country."

        state_region = get("state_region")
        area_region = get("area_region")

        # 2. A chosen state_region must belong to the declared country.
        if state_region is not None and state_region.country_code.upper() != country:
            errors["state_region"] = "That region is not in the selected country."

        # 3. If an area_region (LGA) is given, its parent must be the chosen state_region.
        if area_region is not None:
            if state_region is None:
                errors["area_region"] = "Select a state/region before an area."
            elif area_region.parent_id != getattr(state_region, "id", None):
                errors["area_region"] = "That area does not belong to the selected state/region."

        if errors:
            raise serializers.ValidationError(errors)
        return attrs
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest apps/accounts/tests/test_address_serializer.py -q
```

Expected: PASS.

- [ ] **Step 5: Mutation-verify**

Comment out the `for field in required_fields_for(country)` loop body (make it `pass`). Confirm `test_ng_address_requires_a_state_region` and `test_gb_address_requires_a_postcode` go RED. Revert.

- [ ] **Step 6: Commit**

```bash
git add apps/accounts
git commit -m "feat: per-country Address serializer backed by core.address_rules

NG requires a state_region; GB/US/CA require a postcode; region FKs are kept
consistent (state in the declared country, area a child of the chosen state).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Address CRUD + set-default endpoints

**Why:** unlimited labelled addresses per user, scoped so a user can only ever see or touch their own. Exactly one default-shipping and one default-billing per user, enforced server-side (two "defaults" is an ambiguity the checkout would have to guess at).

**Files:**
- Modify: `backend/apps/accounts/views.py`
- Create: `backend/apps/accounts/me_urls.py`
- Modify: `backend/config/urls.py`
- Test: `backend/apps/accounts/tests/test_address_api.py` (create)

- [ ] **Step 1: Write the failing tests**

`backend/apps/accounts/tests/test_address_api.py`:

```python
import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Address
from apps.core.models import Region


def _client(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


@pytest.mark.django_db
def test_create_and_list_own_addresses(django_user_model):
    user = django_user_model.objects.create_user(email="a@b.com", password="pw")
    Region.objects.create(country_code="NG", name="Lagos", level="state")
    lagos = Region.objects.get(name="Lagos")
    c = _client(user)

    r = c.post("/api/v1/me/addresses/", {
        "label": "Home", "first_name": "Ada", "phone": "08012345678",
        "line1": "1 Allen Ave", "country_code": "NG", "state_region": lagos.id,
    }, format="json")
    assert r.status_code == 201

    lst = c.get("/api/v1/me/addresses/")
    assert lst.status_code == 200
    assert len(lst.data) == 1
    assert lst.data[0]["label"] == "Home"


@pytest.mark.django_db
def test_a_user_cannot_see_or_edit_another_users_address(django_user_model):
    owner = django_user_model.objects.create_user(email="owner@b.com", password="pw")
    other = django_user_model.objects.create_user(email="other@b.com", password="pw")
    addr = Address.objects.create(user=owner, line1="1 Allen", country_code="GB",
                                  city_text="London", postcode="NW1 6XE",
                                  first_name="A", phone="07")

    c = _client(other)
    assert c.get(f"/api/v1/me/addresses/{addr.id}/").status_code == 404
    assert c.delete(f"/api/v1/me/addresses/{addr.id}/").status_code == 404
    assert Address.objects.filter(id=addr.id).exists()


@pytest.mark.django_db
def test_set_default_shipping_is_exclusive(django_user_model):
    user = django_user_model.objects.create_user(email="a@b.com", password="pw")
    a = Address.objects.create(user=user, line1="1", country_code="GB", city_text="L",
                               postcode="N1", first_name="A", phone="07",
                               is_default_shipping=True)
    b = Address.objects.create(user=user, line1="2", country_code="GB", city_text="L",
                               postcode="N2", first_name="A", phone="07")
    c = _client(user)

    r = c.post(f"/api/v1/me/addresses/{b.id}/set-default-shipping/")
    assert r.status_code == 200

    a.refresh_from_db(); b.refresh_from_db()
    assert b.is_default_shipping is True
    assert a.is_default_shipping is False      # the previous default was cleared


@pytest.mark.django_db
def test_addresses_require_auth():
    assert APIClient().get("/api/v1/me/addresses/").status_code in (401, 403)
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest apps/accounts/tests/test_address_api.py -q
```

Expected: FAIL — 404 (URLs not wired).

- [ ] **Step 3: Views**

Append to `backend/apps/accounts/views.py` (add `AddressSerializer` to the `.serializers` import; add `from apps.accounts.models import Address` and `from django.db import transaction`):

```python
class AddressListCreateView(generics.ListCreateAPIView):
    serializer_class = AddressSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None  # a customer's address book is short

    def get_queryset(self):
        return self.request.user.addresses.all().order_by("-is_default_shipping", "id")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class AddressDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = AddressSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # Scoped to the owner: another user's id resolves to 404, never their data.
        return self.request.user.addresses.all()


class _SetDefaultView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    field = None  # "is_default_shipping" | "is_default_billing"

    def post(self, request, pk):
        from django.shortcuts import get_object_or_404

        address = get_object_or_404(request.user.addresses, pk=pk)
        with transaction.atomic():
            # Exactly one default of this kind per user — clear the rest first.
            request.user.addresses.exclude(pk=address.pk).filter(
                **{self.field: True}
            ).update(**{self.field: False})
            setattr(address, self.field, True)
            address.save(update_fields=[self.field, "updated_at"])
        return Response(AddressSerializer(address).data)


class SetDefaultShippingView(_SetDefaultView):
    field = "is_default_shipping"


class SetDefaultBillingView(_SetDefaultView):
    field = "is_default_billing"
```

- [ ] **Step 4: `me_urls.py`**

`backend/apps/accounts/me_urls.py`:

```python
"""Authenticated customer self-service under /api/v1/me/ (addresses now; wishlist in
Plan-11 Task 8). Profile GET/PATCH stays at /api/v1/auth/me/ (already shipped)."""
from django.urls import path

from apps.accounts.views import (
    AddressDetailView,
    AddressListCreateView,
    SetDefaultBillingView,
    SetDefaultShippingView,
)

urlpatterns = [
    path("addresses/", AddressListCreateView.as_view(), name="address-list"),
    path("addresses/<int:pk>/", AddressDetailView.as_view(), name="address-detail"),
    path("addresses/<int:pk>/set-default-shipping/",
         SetDefaultShippingView.as_view(), name="address-default-shipping"),
    path("addresses/<int:pk>/set-default-billing/",
         SetDefaultBillingView.as_view(), name="address-default-billing"),
]
```

- [ ] **Step 5: Mount it**

In `backend/config/urls.py`, add under the API v1 block (after the auth include):

```python
    path("api/v1/me/", include("apps.accounts.me_urls")),
```

- [ ] **Step 6: Run tests**

```bash
uv run pytest apps/accounts -q
```

Expected: PASS.

- [ ] **Step 7: Mutation-verify**

In `_SetDefaultView.post`, remove the `.exclude(...).update(...)` clear line. Confirm `test_set_default_shipping_is_exclusive` goes RED (address `a` stays default). Revert. Then, in `AddressDetailView.get_queryset`, change to `Address.objects.all()`; confirm `test_a_user_cannot_see_or_edit_another_users_address` goes RED. Revert.

- [ ] **Step 8: Commit**

```bash
git add apps/accounts config
git commit -m "feat: address CRUD under /api/v1/me/ with exclusive set-default endpoints

Owner-scoped querysets (another user's id 404s), unlimited labelled addresses, and
exactly one default-shipping / default-billing per user enforced in a transaction.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Confirm the profile endpoint covers the spec (no rewrite)

**Why:** Spec item 1 asks for profile GET/PATCH (names, phone, `marketing_consent`) with a read-only `toke_id`. `MeView` + `MeSerializer` at `/api/v1/auth/me/` already do exactly this. This task adds the *missing coverage test* so the spec requirement is provably met and a future refactor can't silently drop `toke_id` read-only-ness. No production code changes (see D5).

**Files:**
- Test: `backend/apps/accounts/tests/test_profile.py` (create)

- [ ] **Step 1: Write the tests**

`backend/apps/accounts/tests/test_profile.py`:

```python
import pytest
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_profile_get_returns_readonly_toke_id(django_user_model):
    user = django_user_model.objects.create_user(email="a@b.com", password="pw",
                                                  first_name="Ada")
    c = APIClient(); c.force_authenticate(user)

    r = c.get("/api/v1/auth/me/")
    assert r.status_code == 200
    assert r.data["toke_id"].startswith("TK-")
    assert r.data["marketing_consent"] is False


@pytest.mark.django_db
def test_profile_patch_updates_names_phone_consent_but_not_toke_id(django_user_model):
    user = django_user_model.objects.create_user(email="a@b.com", password="pw")
    original_toke = user.toke_id
    c = APIClient(); c.force_authenticate(user)

    r = c.patch("/api/v1/auth/me/", {
        "first_name": "Ada", "last_name": "Obi", "phone": "08099998888",
        "marketing_consent": True, "toke_id": "TK-HACKED", "email": "evil@b.com",
    }, format="json")

    assert r.status_code == 200
    user.refresh_from_db()
    assert user.first_name == "Ada"
    assert user.last_name == "Obi"
    assert user.phone == "08099998888"
    assert user.marketing_consent is True
    assert user.toke_id == original_toke        # read-only, ignored
    assert user.email == "a@b.com"              # read-only, ignored
```

- [ ] **Step 2: Run**

```bash
uv run pytest apps/accounts/tests/test_profile.py -q
```

Expected: PASS immediately (the endpoint already behaves this way). If either test fails, the endpoint regressed — fix `MeSerializer.read_only_fields` rather than the test.

- [ ] **Step 3: Commit**

```bash
git add apps/accounts
git commit -m "test: pin profile GET/PATCH contract (toke_id + email read-only)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Account-deletion request (soft) + deletion fields + admin

**Why:** GDPR/NDPR right-to-erasure, done safely. Deleting rows outright would orphan orders and break accounting; instead we deactivate immediately (the account can no longer log in) and stamp `deletion_requested_at` so the 30-day anonymisation task (Task 6) has a clock. The refresh token is blacklisted so existing sessions die at once.

**Files:**
- Modify: `backend/apps/accounts/models.py`
- Create: `backend/apps/accounts/migrations/0002_deletion_fields.py` (via makemigrations)
- Modify: `backend/apps/accounts/serializers.py`, `views.py`, `urls.py`
- Create: `backend/apps/accounts/admin.py`
- Test: `backend/apps/accounts/tests/test_account_deletion.py` (create)

- [ ] **Step 1: Write the failing tests**

`backend/apps/accounts/tests/test_account_deletion.py`:

```python
import pytest
from rest_framework.test import APIClient

PW = "Str0ng!pass9"


@pytest.mark.django_db
def test_deletion_request_deactivates_and_stamps(django_user_model):
    user = django_user_model.objects.create_user(email="a@b.com", password=PW)
    c = APIClient(); c.force_authenticate(user)

    r = c.post("/api/v1/auth/account/delete/", {"password": PW}, format="json")

    assert r.status_code == 200
    user.refresh_from_db()
    assert user.is_active is False
    assert user.deletion_requested_at is not None


@pytest.mark.django_db
def test_deletion_request_requires_the_current_password(django_user_model):
    user = django_user_model.objects.create_user(email="a@b.com", password=PW)
    c = APIClient(); c.force_authenticate(user)

    r = c.post("/api/v1/auth/account/delete/", {"password": "wrong"}, format="json")

    assert r.status_code == 400
    user.refresh_from_db()
    assert user.is_active is True
    assert user.deletion_requested_at is None


@pytest.mark.django_db
def test_deactivated_user_cannot_obtain_a_token(django_user_model):
    user = django_user_model.objects.create_user(email="a@b.com", password=PW)
    APIClient().force_authenticate(user)  # request the delete first
    c = APIClient(); c.force_authenticate(user)
    c.post("/api/v1/auth/account/delete/", {"password": PW}, format="json")

    r = APIClient().post("/api/v1/auth/token/", {"email": "a@b.com", "password": PW},
                         format="json")
    assert r.status_code == 401     # SimpleJWT refuses inactive users
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest apps/accounts/tests/test_account_deletion.py -q
```

Expected: FAIL — 404 / missing `deletion_requested_at`.

- [ ] **Step 3: Model fields**

In `backend/apps/accounts/models.py`, add to `User` (after `marketing_consent`):

```python
    # Set when the customer requests deletion. is_active flips to False immediately;
    # PII is anonymised 30 days later by apps.accounts.tasks.anonymize_deleted_accounts
    # (a grace window in case the request was a mistake or fraud recovery is needed).
    deletion_requested_at = models.DateTimeField(null=True, blank=True)
    # Set once the customer proves control of their inbox (verify-email or a completed
    # password reset). Gates legacy guest-order claiming — see apps.accounts.claims.
    email_verified_at = models.DateTimeField(null=True, blank=True)
```

(Both fields are added now; `email_verified_at` is used in Task 12. Adding them together means one migration, not two.)

- [ ] **Step 4: Migration**

```bash
uv run python manage.py makemigrations accounts
```

Expected: `0002_user_deletion_requested_at_user_email_verified_at.py`. Both nullable — no prompt.

- [ ] **Step 5: Serializer + view**

Append to `serializers.py`:

```python
class AccountDeletionSerializer(serializers.Serializer):
    password = serializers.CharField(write_only=True)

    def validate_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("Password is incorrect.")
        return value
```

Append to `views.py` (import `AccountDeletionSerializer`; `from django.utils import timezone`):

```python
class AccountDeletionView(APIView):
    """Soft-delete: deactivate now, anonymise after 30 days (apps.accounts.tasks)."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = AccountDeletionSerializer

    @extend_schema(request=AccountDeletionSerializer, responses={200: None})
    def post(self, request):
        serializer = AccountDeletionSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = request.user
        user.is_active = False
        user.deletion_requested_at = timezone.now()
        user.save(update_fields=["is_active", "deletion_requested_at"])
        # Kill every outstanding refresh token so existing sessions end immediately.
        try:
            from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
            from rest_framework_simplejwt.tokens import RefreshToken

            for t in OutstandingToken.objects.filter(user=user):
                try:
                    RefreshToken(t.token).blacklist()
                except Exception:  # noqa: BLE001 — already-expired tokens are fine
                    pass
        except Exception:  # noqa: BLE001 — blacklist app optional; deactivation already done
            pass
        return Response({"detail": "Your account has been closed."})
```

- [ ] **Step 6: URL**

In `urls.py`, import `AccountDeletionView` and add:

```python
    path("account/delete/", AccountDeletionView.as_view(), name="account_delete"),
```

- [ ] **Step 7: Admin (read-only PII audit surface)**

`backend/apps/accounts/admin.py`:

```python
from django.contrib import admin

from apps.accounts.models import Address, User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email", "toke_id", "is_active", "deletion_requested_at",
                    "email_verified_at", "date_joined")
    list_filter = ("is_active", "is_staff", "marketing_consent")
    search_fields = ("email", "toke_id")
    # Never hand-edit identity/audit columns from the admin.
    readonly_fields = ("toke_id", "date_joined", "last_login", "password",
                       "legacy_source", "legacy_wp_id", "legacy_wp_id_intl")


@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ("user", "label", "country_code", "is_default_shipping")
    list_filter = ("country_code", "is_default_shipping")
    search_fields = ("user__email", "line1", "postcode")
```

- [ ] **Step 8: Run tests**

```bash
uv run pytest apps/accounts -q
```

Expected: PASS.

- [ ] **Step 9: Mutation-verify**

In `AccountDeletionView.post`, remove the `user.is_active = False` line. Confirm `test_deactivated_user_cannot_obtain_a_token` goes RED. Revert.

- [ ] **Step 10: Commit**

```bash
git add apps/accounts
git commit -m "feat: soft account-deletion request (deactivate now, anonymise in 30d)

Password-confirmed. Deactivates immediately, stamps deletion_requested_at, and
blacklists outstanding refresh tokens. Adds email_verified_at (used by claiming).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: 30-day anonymisation Celery-beat task

**Why:** the erasure only completes when PII is actually scrubbed. This is the second phase of Task 5. It mirrors `expire_pending_orders` / `complete_delivered_orders`: a daily `@shared_task`, one transaction per user, re-checking under the lock, idempotent (a user already anonymised is skipped). See **D3** for the exact scrub set — confirm before implementing.

**Files:**
- Create: `backend/apps/accounts/tasks.py`
- Modify: `backend/config/settings/base.py` (`CELERY_BEAT_SCHEDULE`)
- Test: `backend/apps/accounts/tests/test_anonymize.py` (create)

- [ ] **Step 1: Write the failing tests**

`backend/apps/accounts/tests/test_anonymize.py`:

```python
import pytest
from django.utils import timezone

from apps.accounts.models import Address
from apps.accounts.tasks import anonymize_deleted_accounts
from apps.core.models import Country
from apps.orders.factories import OrderFactory


@pytest.mark.django_db
def test_account_past_30_days_is_anonymised(django_user_model):
    user = django_user_model.objects.create_user(
        email="ada@b.com", password="pw", first_name="Ada", last_name="Obi",
        phone="08012345678",
    )
    user.is_active = False
    user.deletion_requested_at = timezone.now() - timezone.timedelta(days=31)
    user.save()
    Address.objects.create(user=user, line1="1 Allen", country_code="GB",
                           city_text="London", postcode="N1", first_name="Ada", phone="07")
    toke = user.toke_id

    n = anonymize_deleted_accounts()

    assert n == 1
    user.refresh_from_db()
    assert user.email == f"deleted-{toke}@deleted.invalid"
    assert user.first_name == ""
    assert user.last_name == ""
    assert user.phone == ""
    assert user.toke_id == toke                      # opaque id kept
    assert Address.objects.filter(user=user).count() == 0
    assert not user.has_usable_password()


@pytest.mark.django_db
def test_account_within_grace_window_is_untouched(django_user_model):
    user = django_user_model.objects.create_user(email="ada@b.com", password="pw",
                                                  first_name="Ada")
    user.is_active = False
    user.deletion_requested_at = timezone.now() - timezone.timedelta(days=5)
    user.save()

    assert anonymize_deleted_accounts() == 0
    user.refresh_from_db()
    assert user.email == "ada@b.com"


@pytest.mark.django_db
def test_active_account_is_never_anonymised(django_user_model):
    user = django_user_model.objects.create_user(email="ada@b.com", password="pw")
    # No deletion_requested_at, still active.
    assert anonymize_deleted_accounts() == 0
    user.refresh_from_db()
    assert user.email == "ada@b.com"


@pytest.mark.django_db
def test_order_snapshot_pii_is_scrubbed(django_user_model):
    ng = Country.objects.get(code="NG")
    user = django_user_model.objects.create_user(email="ada@b.com", password="pw")
    user.is_active = False
    user.deletion_requested_at = timezone.now() - timezone.timedelta(days=31)
    user.save()
    order = OrderFactory(number="TC-900001", country=ng, currency=ng.currency,
                         user=user, email="ada@b.com", phone="08012345678",
                         shipping_address={"first_name": "Ada", "phone": "080"})

    anonymize_deleted_accounts()

    order.refresh_from_db()
    assert order.email == f"deleted-{user.toke_id}@deleted.invalid"
    assert order.phone == ""
    assert order.shipping_address == {}
    assert order.user_id == user.id     # link kept, PII gone


@pytest.mark.django_db
def test_anonymize_is_idempotent(django_user_model):
    user = django_user_model.objects.create_user(email="ada@b.com", password="pw")
    user.is_active = False
    user.deletion_requested_at = timezone.now() - timezone.timedelta(days=31)
    user.save()

    assert anonymize_deleted_accounts() == 1
    assert anonymize_deleted_accounts() == 0     # already scrubbed, not re-counted
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest apps/accounts/tests/test_anonymize.py -q
```

Expected: FAIL — `ModuleNotFoundError: apps.accounts.tasks`.

- [ ] **Step 3: Implement the task**

`backend/apps/accounts/tasks.py`:

```python
"""anonymize_deleted_accounts — the second phase of soft account deletion.

Mirrors expire_pending_orders / complete_delivered_orders: a daily beat task, ONE
transaction per user, re-checking under the lock, per-user try/except so one poison
row can't starve the sweep. Idempotent: the anonymised sentinel email means an
already-scrubbed user is not matched again.
"""
import logging

from celery import shared_task
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

GRACE_DAYS = 30
_SENTINEL_DOMAIN = "@deleted.invalid"


def _anonymize_one(pk: int) -> bool:
    from apps.orders.models import Order

    with transaction.atomic():
        User = get_user_model()
        user = User.objects.select_for_update().get(pk=pk)
        # Re-check under the lock: a re-activation or a prior run may have changed things.
        if user.is_active or user.deletion_requested_at is None:
            return False
        if user.email.endswith(_SENTINEL_DOMAIN):
            return False  # already scrubbed — idempotent
        sentinel = f"deleted-{user.toke_id}{_SENTINEL_DOMAIN}"
        user.email = sentinel
        user.first_name = ""
        user.last_name = ""
        user.phone = ""
        user.marketing_consent = False
        user.set_unusable_password()
        user.save(update_fields=[
            "email", "first_name", "last_name", "phone", "marketing_consent",
            "password",
        ])
        user.addresses.all().delete()
        # Scrub the order snapshots too — the link stays, the PII does not (D3).
        Order.objects.filter(user=user).update(
            email=sentinel, phone="", shipping_address={}, billing_address={},
        )
        return True


@shared_task
def anonymize_deleted_accounts() -> int:
    User = get_user_model()
    cutoff = timezone.now() - timezone.timedelta(days=GRACE_DAYS)
    due = list(
        User.objects.filter(
            is_active=False, deletion_requested_at__lt=cutoff
        )
        .exclude(email__endswith=_SENTINEL_DOMAIN)
        .values_list("pk", flat=True)
    )
    done = 0
    for pk in due:
        try:
            if _anonymize_one(pk):
                done += 1
        except Exception:  # noqa: BLE001 — one bad row must not stop the sweep
            logger.exception("anonymize failed for user %s", pk)
    return done
```

- [ ] **Step 4: Register in the beat schedule**

In `backend/config/settings/base.py`, add to `CELERY_BEAT_SCHEDULE`:

```python
    "anonymize-deleted-accounts": {
        "task": "apps.accounts.tasks.anonymize_deleted_accounts",
        "schedule": 86400.0,  # daily — the grace window is measured in days
    },
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest apps/accounts -q
```

Expected: PASS.

- [ ] **Step 6: Mutation-verify**

Change `timedelta(days=GRACE_DAYS)` to `timedelta(days=0)`. Confirm `test_account_within_grace_window_is_untouched` goes RED. Revert. Then change the idempotency guard `if user.email.endswith(_SENTINEL_DOMAIN): return False` to `pass`-through and confirm `test_anonymize_is_idempotent` goes RED (second run returns 1). Revert.

- [ ] **Step 7: Commit**

```bash
git add apps/accounts config
git commit -m "feat: daily task anonymises soft-deleted accounts after 30 days

Mirrors the expiry/complete sweeps: per-user locked transaction, idempotent via the
deleted.invalid sentinel email. Scrubs user PII, deletes addresses, blanks order
snapshots; keeps toke_id and the order link for reconciliation.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Wishlist app + `WishlistItem` model

**Why:** a per-user set of saved variants. A new app keeps its model and tests self-contained; the item points at a `ProductVariant` (the spec says "variant ids") so a wishlist can distinguish a 50ml from a 100ml.

**Files:**
- Create: `backend/apps/wishlist/{__init__.py,apps.py,models.py,admin.py,migrations/__init__.py,tests/__init__.py,tests/test_models.py}`
- Modify: `backend/config/settings/base.py` (`INSTALLED_APPS`)

- [ ] **Step 1: Write the failing test**

`backend/apps/wishlist/tests/test_models.py`:

```python
import pytest

from apps.catalog.factories import ProductVariantFactory
from apps.wishlist.models import WishlistItem


@pytest.mark.django_db
def test_wishlist_item_is_unique_per_user_and_variant(django_user_model):
    user = django_user_model.objects.create_user(email="a@b.com", password="pw")
    variant = ProductVariantFactory()

    WishlistItem.objects.create(user=user, variant=variant)
    with pytest.raises(Exception):  # IntegrityError under the unique_together
        WishlistItem.objects.create(user=user, variant=variant)


@pytest.mark.django_db
def test_two_users_can_wishlist_the_same_variant(django_user_model):
    u1 = django_user_model.objects.create_user(email="a@b.com", password="pw")
    u2 = django_user_model.objects.create_user(email="b@b.com", password="pw")
    variant = ProductVariantFactory()

    WishlistItem.objects.create(user=u1, variant=variant)
    WishlistItem.objects.create(user=u2, variant=variant)  # no clash

    assert WishlistItem.objects.count() == 2
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest apps/wishlist -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'apps.wishlist'`.

- [ ] **Step 3: Scaffold**

```bash
cd tokecosmetics-platform/backend
uv run python manage.py startapp wishlist apps/wishlist
```

Set `name = "apps.wishlist"` in `apps/wishlist/apps.py` (mirror `apps/delivery/apps.py`). Delete the generated `views.py`/`tests.py`; create `apps/wishlist/tests/__init__.py`. Add `"apps.wishlist"` to `INSTALLED_APPS` in `config/settings/base.py`.

- [ ] **Step 4: Model**

`backend/apps/wishlist/models.py`:

```python
from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class WishlistItem(TimeStampedModel):
    """One saved variant for one user. Variant-level (not product-level) so a customer
    can save a specific size; the API resolves the product card per country on read."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wishlist_items"
    )
    variant = models.ForeignKey(
        "catalog.ProductVariant", on_delete=models.CASCADE, related_name="wishlisted_by"
    )

    class Meta:
        unique_together = [("user", "variant")]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.user_id} ♥ {self.variant_id}"
```

- [ ] **Step 5: Migration**

```bash
uv run python manage.py makemigrations wishlist
```

- [ ] **Step 6: Admin**

`backend/apps/wishlist/admin.py`:

```python
from django.contrib import admin

from apps.wishlist.models import WishlistItem


@admin.register(WishlistItem)
class WishlistItemAdmin(admin.ModelAdmin):
    list_display = ("user", "variant", "created_at")
    search_fields = ("user__email", "variant__sku")
```

- [ ] **Step 7: Run tests**

```bash
uv run pytest apps/wishlist -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add apps/wishlist config
git commit -m "feat: wishlist app with the per-user WishlistItem model

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 8: Wishlist API (GET / POST / DELETE)

**Why:** the customer-facing endpoint. `POST` a variant SKU to add, `DELETE` to remove, `GET` to list — each entry rendered as a country-resolved product card so the storefront can show price/availability like everywhere else.

**Files:**
- Create: `backend/apps/wishlist/serializers.py`, `views.py`, `urls.py`
- Modify: `backend/config/urls.py`
- Test: `backend/apps/wishlist/tests/test_api.py` (create)

- [ ] **Step 1: Write the failing tests**

`backend/apps/wishlist/tests/test_api.py`:

```python
import pytest
from rest_framework.test import APIClient

from apps.catalog.factories import PriceFactory, ProductVariantFactory
from apps.wishlist.models import WishlistItem


def _client(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


@pytest.mark.django_db
def test_add_and_list_wishlist_with_country_card(django_user_model):
    price = PriceFactory()                       # NGN price on a fresh variant
    variant = price.variant
    user = django_user_model.objects.create_user(email="a@b.com", password="pw")
    c = _client(user)

    r = c.post("/api/v1/me/wishlist/", {"sku": variant.sku}, format="json",
               HTTP_X_COUNTRY="NG")
    assert r.status_code == 201

    lst = c.get("/api/v1/me/wishlist/", HTTP_X_COUNTRY="NG")
    assert lst.status_code == 200
    assert len(lst.data) == 1
    item = lst.data[0]
    assert item["sku"] == variant.sku
    assert item["product"]["from_price"] is not None    # resolved per country
    assert item["product"]["currency"] == "NGN"


@pytest.mark.django_db
def test_adding_the_same_variant_twice_is_idempotent(django_user_model):
    variant = ProductVariantFactory()
    user = django_user_model.objects.create_user(email="a@b.com", password="pw")
    c = _client(user)

    a = c.post("/api/v1/me/wishlist/", {"sku": variant.sku}, format="json")
    b = c.post("/api/v1/me/wishlist/", {"sku": variant.sku}, format="json")
    assert a.status_code == 201
    assert b.status_code in (200, 201)                  # no crash, no duplicate
    assert WishlistItem.objects.filter(user=user).count() == 1


@pytest.mark.django_db
def test_delete_removes_only_the_callers_item(django_user_model):
    variant = ProductVariantFactory()
    owner = django_user_model.objects.create_user(email="o@b.com", password="pw")
    other = django_user_model.objects.create_user(email="x@b.com", password="pw")
    WishlistItem.objects.create(user=owner, variant=variant)

    # another user deleting it must not touch the owner's item
    assert _client(other).delete(f"/api/v1/me/wishlist/{variant.sku}/").status_code == 404
    assert WishlistItem.objects.filter(user=owner).count() == 1

    assert _client(owner).delete(f"/api/v1/me/wishlist/{variant.sku}/").status_code == 204
    assert WishlistItem.objects.filter(user=owner).count() == 0


@pytest.mark.django_db
def test_wishlist_requires_auth():
    assert APIClient().get("/api/v1/me/wishlist/").status_code in (401, 403)
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest apps/wishlist/tests/test_api.py -q
```

Expected: FAIL — 404.

- [ ] **Step 3: Serializer**

`backend/apps/wishlist/serializers.py`:

```python
from rest_framework import serializers

from apps.catalog.api_serializers import ProductListSerializer
from apps.catalog.models import Product
from apps.catalog.services import annotate_min_price
from apps.wishlist.models import WishlistItem


class WishlistItemSerializer(serializers.ModelSerializer):
    sku = serializers.CharField(source="variant.sku", read_only=True)
    product = serializers.SerializerMethodField()

    class Meta:
        model = WishlistItem
        fields = ["sku", "product", "created_at"]

    def get_product(self, obj):
        # Resolve the product card in the request's country, exactly like listings do.
        country = self.context["request"].country
        qs = annotate_min_price(
            Product.objects.filter(pk=obj.variant.product_id), country
        ).select_related("brand").prefetch_related("images")
        product = qs.first()
        if product is None:
            return None
        return ProductListSerializer(product, context=self.context).data
```

- [ ] **Step 4: Views**

`backend/apps/wishlist/views.py`:

```python
from django.shortcuts import get_object_or_404
from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import ProductVariant
from apps.wishlist.models import WishlistItem
from apps.wishlist.serializers import WishlistItemSerializer


class _AddSerializer(serializers.Serializer):
    sku = serializers.CharField()


class WishlistView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        items = (
            request.user.wishlist_items.select_related("variant__product__brand")
            .prefetch_related("variant__product__images")
        )
        return Response(WishlistItemSerializer(items, many=True,
                                               context={"request": request}).data)

    def post(self, request):
        s = _AddSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        variant = get_object_or_404(ProductVariant, sku=s.validated_data["sku"])
        item, created = WishlistItem.objects.get_or_create(
            user=request.user, variant=variant
        )
        code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(
            WishlistItemSerializer(item, context={"request": request}).data, status=code
        )


class WishlistItemDeleteView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, sku):
        item = get_object_or_404(request.user.wishlist_items, variant__sku=sku)
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 5: URLs**

`backend/apps/wishlist/urls.py`:

```python
from django.urls import path

from apps.wishlist.views import WishlistItemDeleteView, WishlistView

urlpatterns = [
    path("wishlist/", WishlistView.as_view(), name="wishlist"),
    path("wishlist/<str:sku>/", WishlistItemDeleteView.as_view(), name="wishlist-item"),
]
```

Mount it under the same `me/` prefix in `config/urls.py`:

```python
    path("api/v1/me/", include("apps.wishlist.urls")),
```

(Place it after the `apps.accounts.me_urls` include; the two do not collide — one owns `addresses/`, the other `wishlist/`.)

- [ ] **Step 6: Run tests**

```bash
uv run pytest apps/wishlist -q
```

Expected: PASS.

- [ ] **Step 7: Mutation-verify**

In `WishlistItemDeleteView.delete`, change `request.user.wishlist_items` to `WishlistItem.objects`. Confirm `test_delete_removes_only_the_callers_item` goes RED (the other user gets a 204 and deletes the owner's item). Revert.

- [ ] **Step 8: Commit**

```bash
git add apps/wishlist config
git commit -m "feat: wishlist GET/POST/DELETE with country-resolved product cards

Owner-scoped, idempotent add (get_or_create), delete by variant SKU. Cards resolve
price/currency in the X-Country context like every other catalog surface.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 9: `Product.rating_avg` / `rating_count` + recompute service

**Why:** reviews are only useful if the star rating rides on the product card and detail. These fields are **denormalised** — recomputed from approved reviews (the service lands in Task 10), never hand-written — so a read never aggregates. This task is catalog-only (schema + serializer) and has no dependency on the reviews app; saving a product fires the existing catalog-cache signal so cards re-render (see **D2** for why that satisfies "synced to search index" today).

**Files:**
- Modify: `backend/apps/catalog/models.py`
- Create: `backend/apps/catalog/migrations/000X_product_rating.py` (via makemigrations)
- Modify: `backend/apps/catalog/api_serializers.py`
- Test: `backend/apps/catalog/tests/test_rating_fields.py` (create)

> The recompute service (`apps/reviews/services.py`) is **not** created here — it lives with the reviews app in Task 10, because it queries `Review`. This task is catalog schema + serializer only.

- [ ] **Step 1: Write the failing tests**

`backend/apps/catalog/tests/test_rating_fields.py`:

```python
from decimal import Decimal

import pytest

from apps.catalog.factories import ProductFactory


@pytest.mark.django_db
def test_new_product_has_zero_rating():
    p = ProductFactory()
    assert p.rating_avg == Decimal("0.00")
    assert p.rating_count == 0


@pytest.mark.django_db
def test_rating_fields_are_exposed_on_the_list_card(django_user_model, client):
    """A country-resolved product card must carry the denormalised rating so the
    storefront can show stars without a second query."""
    from apps.catalog.factories import PriceFactory

    price = PriceFactory()
    product = price.variant.product
    product.rating_avg = Decimal("4.50")
    product.rating_count = 12
    product.save(update_fields=["rating_avg", "rating_count"])

    r = client.get("/api/v1/products/", HTTP_X_COUNTRY="NG")
    assert r.status_code == 200
    card = next(c for c in r.data["results"] if c["slug"] == product.slug)
    assert card["rating_avg"] == "4.50"
    assert card["rating_count"] == 12
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest apps/catalog/tests/test_rating_fields.py -q
```

Expected: FAIL — `AttributeError: 'Product' object has no attribute 'rating_avg'`.

- [ ] **Step 3: Add the fields**

In `backend/apps/catalog/models.py`, inside `Product` (after `is_featured`):

```python
    # Denormalised from APPROVED reviews only (apps.reviews.services.recompute_product_rating).
    # Never hand-write these — a read must never aggregate reviews. rating_avg is 0.00
    # with rating_count 0 until the first review is approved.
    rating_avg = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    rating_count = models.PositiveIntegerField(default=0)
```

- [ ] **Step 4: Migration**

```bash
uv run python manage.py makemigrations catalog
```

Both fields have defaults — existing rows backfill to `0` / `0.00`, no prompt.

- [ ] **Step 5: Expose on serializers**

In `backend/apps/catalog/api_serializers.py`, add `"rating_avg"` and `"rating_count"` to `ProductListSerializer.Meta.fields` **and** `ProductDetailSerializer.Meta.fields`. `rating_avg` is a `DecimalField`, so DRF renders it as a string (`"4.50"`) by default — matching the test. No `SerializerMethodField` needed.

- [ ] **Step 6: Run tests**

```bash
uv run pytest apps/catalog/tests/test_rating_fields.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/catalog
git commit -m "feat: denormalised rating_avg/rating_count on Product, exposed on cards

Recomputed from approved reviews only (service lands with the reviews app). Saving a
product fires the catalog-cache signal so cards re-render with the new rating.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 10: Reviews app — `Review` model, recompute service, admin approve action

**Why:** the moderation core. Reviews are born `pending`; approval is a deliberate human act. The API approval endpoint is **Plan-18** — what lands now is the model, the recompute service, and a **Django-admin action** so staff can approve today. Approval (and only approval) recomputes the product's denormalised rating.

**Files:**
- Create: `backend/apps/reviews/{__init__.py,apps.py,models.py,services.py,admin.py,migrations/__init__.py,tests/__init__.py,tests/test_models.py,tests/test_admin_approve.py}`
- Modify: `backend/config/settings/base.py` (`INSTALLED_APPS`)

- [ ] **Step 1: Write the failing tests**

`backend/apps/reviews/tests/test_models.py`:

```python
from decimal import Decimal

import pytest

from apps.catalog.factories import ProductFactory
from apps.reviews.models import Review
from apps.reviews.services import recompute_product_rating


@pytest.mark.django_db
def test_review_is_born_pending(django_user_model):
    user = django_user_model.objects.create_user(email="a@b.com", password="pw")
    product = ProductFactory()
    review = Review.objects.create(product=product, user=user, rating=5, body="Great")
    assert review.status == "pending"


@pytest.mark.django_db
def test_one_review_per_user_per_product(django_user_model):
    user = django_user_model.objects.create_user(email="a@b.com", password="pw")
    product = ProductFactory()
    Review.objects.create(product=product, user=user, rating=5, body="A")
    with pytest.raises(Exception):     # IntegrityError under unique_together
        Review.objects.create(product=product, user=user, rating=3, body="B")


@pytest.mark.django_db
def test_recompute_counts_only_approved(django_user_model):
    product = ProductFactory()
    u1 = django_user_model.objects.create_user(email="a@b.com", password="pw")
    u2 = django_user_model.objects.create_user(email="b@b.com", password="pw")
    u3 = django_user_model.objects.create_user(email="c@b.com", password="pw")
    Review.objects.create(product=product, user=u1, rating=5, body="x", status="approved")
    Review.objects.create(product=product, user=u2, rating=3, body="y", status="approved")
    Review.objects.create(product=product, user=u3, rating=1, body="z", status="pending")

    recompute_product_rating(product)

    product.refresh_from_db()
    assert product.rating_count == 2                 # pending excluded
    assert product.rating_avg == Decimal("4.00")     # (5+3)/2


@pytest.mark.django_db
def test_recompute_with_no_approved_reviews_resets_to_zero(django_user_model):
    product = ProductFactory()
    product.rating_avg = Decimal("4.00")
    product.rating_count = 3
    product.save()

    recompute_product_rating(product)

    product.refresh_from_db()
    assert product.rating_avg == Decimal("0.00")
    assert product.rating_count == 0
```

`backend/apps/reviews/tests/test_admin_approve.py`:

```python
from decimal import Decimal

import pytest
from django.contrib.admin.sites import AdminSite

from apps.catalog.factories import ProductFactory
from apps.reviews.admin import ReviewAdmin
from apps.reviews.models import Review


@pytest.mark.django_db
def test_admin_approve_action_sets_status_and_recomputes(django_user_model):
    user = django_user_model.objects.create_user(email="a@b.com", password="pw")
    product = ProductFactory()
    review = Review.objects.create(product=product, user=user, rating=4, body="Good")

    admin = ReviewAdmin(Review, AdminSite())
    admin.approve_reviews(request=None, queryset=Review.objects.filter(pk=review.pk))

    review.refresh_from_db()
    product.refresh_from_db()
    assert review.status == "approved"
    assert product.rating_count == 1
    assert product.rating_avg == Decimal("4.00")
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest apps/reviews -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'apps.reviews'`.

- [ ] **Step 3: Scaffold**

```bash
cd tokecosmetics-platform/backend
uv run python manage.py startapp reviews apps/reviews
```

Set `name = "apps.reviews"` in `apps/reviews/apps.py`. Delete generated `views.py`/`tests.py`; create `apps/reviews/tests/__init__.py`. Add `"apps.reviews"` to `INSTALLED_APPS`.

- [ ] **Step 4: Model**

`backend/apps/reviews/models.py`:

```python
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.models import TimeStampedModel


class Review(TimeStampedModel):
    """A verified-purchase product review. Born `pending`; only an approval (admin now,
    API in Plan-18) makes it public and feeds the product's denormalised rating."""

    STATUSES = [("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")]

    product = models.ForeignKey(
        "catalog.Product", on_delete=models.CASCADE, related_name="reviews"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews"
    )
    # The order that made this a verified purchase (audit trail; SET_NULL so deleting a
    # migrated order never deletes the review).
    order = models.ForeignKey(
        "orders.Order", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="reviews",
    )
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    title = models.CharField(max_length=140, blank=True)
    body = models.TextField()
    status = models.CharField(max_length=10, default="pending", choices=STATUSES)

    class Meta:
        # One review per customer per product — re-review edits the existing row (Plan-18).
        unique_together = [("product", "user")]
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["product", "status"])]

    def __str__(self) -> str:
        return f"{self.rating}★ {self.product_id} by {self.user_id} ({self.status})"
```

- [ ] **Step 5: Migration**

```bash
uv run python manage.py makemigrations reviews
```

- [ ] **Step 6: Recompute service**

`backend/apps/reviews/services.py`:

```python
"""Denormalised product-rating recompute. The ONLY writer of Product.rating_avg /
rating_count. Aggregates APPROVED reviews only; saving the product fires the catalog
cache-bump signal (apps.catalog.signals) so cached cards re-render with the new stars.

Meilisearch document sync is Plan-07b's job (no index exists yet — see the plan's D2).
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Avg, Count


def recompute_product_rating(product) -> None:
    from apps.reviews.models import Review

    agg = Review.objects.filter(product=product, status="approved").aggregate(
        avg=Avg("rating"), count=Count("id")
    )
    count = agg["count"] or 0
    avg = agg["avg"]
    product.rating_count = count
    product.rating_avg = (
        Decimal(str(avg)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if avg is not None
        else Decimal("0.00")
    )
    product.save(update_fields=["rating_avg", "rating_count", "updated_at"])
```

- [ ] **Step 7: Admin with the approve action**

`backend/apps/reviews/admin.py`:

```python
from django.contrib import admin

from apps.reviews.models import Review
from apps.reviews.services import recompute_product_rating


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("product", "user", "rating", "status", "created_at")
    list_filter = ("status", "rating")
    search_fields = ("product__name", "user__email", "body")
    readonly_fields = ("product", "user", "order", "rating", "title", "body", "created_at")
    actions = ["approve_reviews", "reject_reviews"]

    @admin.action(description="Approve selected reviews")
    def approve_reviews(self, request, queryset):
        products = set()
        for review in queryset:
            review.status = "approved"
            review.save(update_fields=["status", "updated_at"])
            products.add(review.product)
        for product in products:
            recompute_product_rating(product)

    @admin.action(description="Reject selected reviews")
    def reject_reviews(self, request, queryset):
        products = set()
        for review in queryset:
            review.status = "rejected"
            review.save(update_fields=["status", "updated_at"])
            products.add(review.product)
        for product in products:
            # Rejecting a previously-approved review must drop it back out of the average.
            recompute_product_rating(product)
```

- [ ] **Step 8: Run tests**

```bash
uv run pytest apps/reviews -q
```

Expected: PASS.

- [ ] **Step 9: Mutation-verify**

In `recompute_product_rating`, change the filter to `status__in=["approved", "pending"]`. Confirm `test_recompute_counts_only_approved` goes RED. Revert. Then in `approve_reviews`, remove the `recompute_product_rating` loop; confirm `test_admin_approve_action_sets_status_and_recomputes` goes RED. Revert.

- [ ] **Step 10: Commit**

```bash
git add apps/reviews config
git commit -m "feat: reviews app — pending->approved model, recompute service, admin action

Reviews are born pending. Approval (admin action now; API in Plan-18) recomputes the
product's denormalised rating from approved reviews only. One review per user/product.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 11: Reviews API — verified-purchase POST + approved-only GET

**Why:** the customer endpoint. Only a verified purchaser may POST (`delivered`/`completed` order containing the product); the review lands `pending`. `GET` lists **approved** reviews only — a pending or rejected review is invisible to the public.

**Files:**
- Create: `backend/apps/reviews/serializers.py`, `views.py`, `urls.py`
- Modify: `backend/config/urls.py`
- Test: `backend/apps/reviews/tests/test_api.py` (create)

- [ ] **Step 1: Write the failing tests**

`backend/apps/reviews/tests/test_api.py`:

```python
import pytest
from rest_framework.test import APIClient

from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country
from apps.orders.factories import OrderFactory
from apps.orders.models import OrderItem
from apps.reviews.models import Review


def _delivered_order_for(user, variant, status="delivered"):
    ng = Country.objects.get(code="NG")
    order = OrderFactory(number=f"TC-{variant.id:06d}", country=ng, currency=ng.currency,
                         user=user, email=user.email, status=status)
    OrderItem.objects.create(order=order, variant=variant, product_name=variant.product.name,
                             unit_price=1, line_total=1, quantity=1)
    return order


@pytest.mark.django_db
def test_verified_purchaser_can_post_a_pending_review(django_user_model):
    variant = ProductVariantFactory()
    product = variant.product
    user = django_user_model.objects.create_user(email="a@b.com", password="pw")
    _delivered_order_for(user, variant)
    c = APIClient(); c.force_authenticate(user)

    r = c.post(f"/api/v1/products/{product.slug}/reviews/",
               {"rating": 5, "title": "Love it", "body": "Great product"}, format="json")

    assert r.status_code == 201
    review = Review.objects.get(product=product, user=user)
    assert review.status == "pending"


@pytest.mark.django_db
def test_non_purchaser_is_refused(django_user_model):
    variant = ProductVariantFactory()
    product = variant.product
    user = django_user_model.objects.create_user(email="a@b.com", password="pw")
    c = APIClient(); c.force_authenticate(user)

    r = c.post(f"/api/v1/products/{product.slug}/reviews/",
               {"rating": 5, "body": "never bought it"}, format="json")

    assert r.status_code == 403
    assert not Review.objects.filter(product=product, user=user).exists()


@pytest.mark.django_db
def test_a_pending_order_does_not_count_as_verified(django_user_model):
    variant = ProductVariantFactory()
    product = variant.product
    user = django_user_model.objects.create_user(email="a@b.com", password="pw")
    _delivered_order_for(user, variant, status="pending_payment")   # not delivered/completed
    c = APIClient(); c.force_authenticate(user)

    r = c.post(f"/api/v1/products/{product.slug}/reviews/",
               {"rating": 5, "body": "paid but not delivered"}, format="json")

    assert r.status_code == 403


@pytest.mark.django_db
def test_completed_order_also_counts_as_verified(django_user_model):
    variant = ProductVariantFactory()
    product = variant.product
    user = django_user_model.objects.create_user(email="a@b.com", password="pw")
    _delivered_order_for(user, variant, status="completed")
    c = APIClient(); c.force_authenticate(user)

    r = c.post(f"/api/v1/products/{product.slug}/reviews/",
               {"rating": 4, "body": "arrived and completed"}, format="json")

    assert r.status_code == 201


@pytest.mark.django_db
def test_get_lists_only_approved_reviews(django_user_model):
    variant = ProductVariantFactory()
    product = variant.product
    u1 = django_user_model.objects.create_user(email="a@b.com", password="pw")
    u2 = django_user_model.objects.create_user(email="b@b.com", password="pw")
    Review.objects.create(product=product, user=u1, rating=5, body="approved one",
                          status="approved")
    Review.objects.create(product=product, user=u2, rating=1, body="pending one",
                          status="pending")

    r = APIClient().get(f"/api/v1/products/{product.slug}/reviews/")
    assert r.status_code == 200
    bodies = [rv["body"] for rv in r.data]
    assert bodies == ["approved one"]


@pytest.mark.django_db
def test_cannot_review_the_same_product_twice(django_user_model):
    variant = ProductVariantFactory()
    product = variant.product
    user = django_user_model.objects.create_user(email="a@b.com", password="pw")
    _delivered_order_for(user, variant)
    c = APIClient(); c.force_authenticate(user)

    c.post(f"/api/v1/products/{product.slug}/reviews/", {"rating": 5, "body": "one"},
           format="json")
    r = c.post(f"/api/v1/products/{product.slug}/reviews/", {"rating": 1, "body": "two"},
               format="json")
    assert r.status_code == 400
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest apps/reviews/tests/test_api.py -q
```

Expected: FAIL — 404.

- [ ] **Step 3: Serializer**

`backend/apps/reviews/serializers.py`:

```python
from rest_framework import serializers

from apps.reviews.models import Review


class ReviewReadSerializer(serializers.ModelSerializer):
    author = serializers.SerializerMethodField()

    class Meta:
        model = Review
        fields = ["rating", "title", "body", "author", "created_at"]

    def get_author(self, obj):
        # Public display name only — never the email.
        name = obj.user.first_name or "Verified buyer"
        return name


class ReviewWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = ["rating", "title", "body"]

    def validate_rating(self, value):
        if not 1 <= value <= 5:
            raise serializers.ValidationError("Rating must be between 1 and 5.")
        return value
```

- [ ] **Step 4: Views (with the verified-purchase gate)**

`backend/apps/reviews/views.py`:

```python
from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Product
from apps.orders.models import Order
from apps.reviews.models import Review
from apps.reviews.serializers import ReviewReadSerializer, ReviewWriteSerializer

# Statuses that make a purchase "verified" — the customer has the goods in hand.
# completed = delivered + return window elapsed (set by complete_delivered_orders).
_VERIFIED_STATUSES = ("delivered", "completed")


def _verified_order(user, product):
    """The most recent delivered/completed order of this user that contains the product,
    or None. Used both as the permission gate and to stamp Review.order for audit."""
    return (
        Order.objects.filter(
            user=user, status__in=_VERIFIED_STATUSES, items__variant__product=product
        )
        .order_by("-placed_at")
        .first()
    )


class ProductReviewsView(APIView):
    def get_permissions(self):
        # Public GET, authenticated POST.
        if self.request.method == "POST":
            return [permissions.IsAuthenticated()]
        return [permissions.AllowAny()]

    def get(self, request, slug):
        product = get_object_or_404(Product, slug=slug)
        reviews = product.reviews.filter(status="approved").select_related("user")
        return Response(ReviewReadSerializer(reviews, many=True).data)

    def post(self, request, slug):
        product = get_object_or_404(Product, slug=slug)
        order = _verified_order(request.user, product)
        if order is None:
            return Response(
                {"detail": "Only verified purchasers can review this product."},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = ReviewWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            review = Review.objects.create(
                product=product, user=request.user, order=order,
                **serializer.validated_data,
            )
        except IntegrityError:
            # unique_together(product, user): they already reviewed it.
            return Response(
                {"detail": "You have already reviewed this product."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(ReviewReadSerializer(review).data, status=status.HTTP_201_CREATED)
```

- [ ] **Step 5: URLs**

`backend/apps/reviews/urls.py`:

```python
from django.urls import path

from apps.reviews.views import ProductReviewsView

urlpatterns = [
    path("products/<slug:slug>/reviews/", ProductReviewsView.as_view(), name="product-reviews"),
]
```

Mount in `config/urls.py` under `api/v1/` (near the catalog include):

```python
    path("api/v1/", include("apps.reviews.urls")),
```

- [ ] **Step 6: Run tests**

```bash
uv run pytest apps/reviews -q
```

Expected: PASS.

- [ ] **Step 7: Mutation-verify**

Change `_VERIFIED_STATUSES` to `("delivered", "completed", "pending_payment")`. Confirm `test_a_pending_order_does_not_count_as_verified` goes RED. Revert. Then change the GET filter from `status="approved"` to no filter; confirm `test_get_lists_only_approved_reviews` goes RED. Revert.

- [ ] **Step 8: Commit**

```bash
git add apps/reviews config
git commit -m "feat: product reviews API — verified-purchase POST, approved-only GET

Only a delivered/completed order containing the product lets a user post; the review
lands pending. Public GET shows approved reviews and never leaks the reviewer's email.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 12: Legacy guest-order claiming on email verification

**Why:** migrated WordPress guest orders (Plan-22) have `user=None` + a stored `email`. When a real customer proves control of that inbox, their old history should attach to their account. Claiming is gated on **verification**, not bare registration, so a stranger cannot type someone's email and inherit their orders (see **D1**).

> **Depends on D1.** If Hammed chooses "password-reset only", drop Steps 3–6 (the verify-email endpoint) and keep only the `claims.py` service + its call from `PasswordResetConfirmView` (Step 7). The claiming tests in Step 1 stay.

**Files:**
- Create: `backend/apps/accounts/claims.py`, `backend/apps/accounts/verification.py`
- Modify: `backend/apps/accounts/views.py`, `urls.py`, `serializers.py`
- Modify: `backend/apps/accounts/views.py` `RegisterView` (send verify email) and `PasswordResetConfirmView` (claim on reset)
- Create: `backend/apps/notifications/templates/email/verify_email.{subject.txt,txt,html}`
- Test: `backend/apps/accounts/tests/test_claiming.py` (create)

- [ ] **Step 1: Write the failing tests**

`backend/apps/accounts/tests/test_claiming.py`:

```python
import pytest
from rest_framework.test import APIClient

from apps.accounts.claims import claim_legacy_orders
from apps.accounts.verification import make_verify_token
from apps.core.models import Country
from apps.orders.factories import OrderFactory

PW = "Str0ng!pass9"


def _guest_order(number, email):
    ng = Country.objects.get(code="NG")
    return OrderFactory(number=number, country=ng, currency=ng.currency,
                        user=None, email=email, source="legacy_ng")


@pytest.mark.django_db
def test_claim_attaches_userless_orders_matching_email(django_user_model):
    user = django_user_model.objects.create_user(email="ada@b.com", password=PW)
    o1 = _guest_order("NG-1001", "ada@b.com")
    o2 = _guest_order("NG-1002", "ADA@b.com")           # case-insensitive match
    other = _guest_order("NG-1003", "someone@else.com")  # must NOT be claimed

    n = claim_legacy_orders(user)

    assert n == 2
    o1.refresh_from_db(); o2.refresh_from_db(); other.refresh_from_db()
    assert o1.user_id == user.id
    assert o2.user_id == user.id
    assert other.user_id is None


@pytest.mark.django_db
def test_claim_ignores_orders_that_already_have_a_user(django_user_model):
    """The user__isnull guard: an order already attached to an account is never
    re-pointed. Re-running claim for the owner returns 0 — the owned order is not
    matched, so nothing is silently re-written."""
    owner = django_user_model.objects.create_user(email="ada@b.com", password=PW)
    ng = Country.objects.get(code="NG")
    order = OrderFactory(number="NG-2001", country=ng, currency=ng.currency,
                         user=owner, email="ada@b.com")

    assert claim_legacy_orders(owner) == 0     # already owned → not re-claimed
    order.refresh_from_db()
    assert order.user_id == owner.id


@pytest.mark.django_db
def test_verify_email_endpoint_marks_verified_and_claims(django_user_model):
    user = django_user_model.objects.create_user(email="ada@b.com", password=PW)
    _guest_order("NG-3001", "ada@b.com")
    token = make_verify_token(user.email)

    r = APIClient().post("/api/v1/auth/verify-email/", {"token": token}, format="json")

    assert r.status_code == 200
    user.refresh_from_db()
    assert user.email_verified_at is not None
    from apps.orders.models import Order
    assert Order.objects.get(number="NG-3001").user_id == user.id


@pytest.mark.django_db
def test_verify_email_rejects_a_bad_token():
    r = APIClient().post("/api/v1/auth/verify-email/", {"token": "garbage"}, format="json")
    assert r.status_code == 400
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest apps/accounts/tests/test_claiming.py -q
```

Expected: FAIL — import errors / 404.

- [ ] **Step 3: Claiming service**

`backend/apps/accounts/claims.py`:

```python
"""Attach migrated guest orders (user=None) to a verified account on exact email match.

Guarded two ways: only USER-LESS orders are ever touched (an order that already has a
user is never re-pointed), and the match is on the account's own verified email. New
orders always carry a user (Decision 7), so this only ever picks up legacy guest rows.
"""
from __future__ import annotations


def claim_legacy_orders(user) -> int:
    from apps.orders.models import Order

    return (
        Order.objects.filter(user__isnull=True, email__iexact=user.email)
        .update(user=user)
    )
```

- [ ] **Step 4: Verification token**

`backend/apps/accounts/verification.py`:

```python
"""Signed email-verification token — mirrors apps.orders.tokens (django.core.signing,
HMAC'd with SECRET_KEY, no table). The email is read OUT of the token, never trusted
from the request body, so a token minted for one address cannot verify another."""
from __future__ import annotations

from datetime import timedelta

from django.core import signing

VERIFY_SALT = "accounts.verify_email"
VERIFY_MAX_AGE = timedelta(days=7)


class VerifyTokenError(Exception):
    """The token is expired, tampered with, wrong-scoped, or not one of ours."""


def make_verify_token(email: str) -> str:
    return signing.dumps({"e": email.lower(), "s": "verify"}, salt=VERIFY_SALT)


def read_verify_token(token: str, max_age=VERIFY_MAX_AGE) -> str:
    try:
        payload = signing.loads(token, salt=VERIFY_SALT, max_age=max_age)
    except signing.BadSignature as exc:  # covers SignatureExpired
        raise VerifyTokenError(str(exc)) from exc
    if not isinstance(payload, dict) or payload.get("s") != "verify" or not payload.get("e"):
        raise VerifyTokenError("token is not a verification token")
    return payload["e"]
```

- [ ] **Step 5: Verify-email view + serializer**

Append to `serializers.py`:

```python
class EmailVerifySerializer(serializers.Serializer):
    token = serializers.CharField()
```

Append to `views.py` (imports: `EmailVerifySerializer`, `from apps.accounts.verification import read_verify_token, VerifyTokenError`, `from apps.accounts.claims import claim_legacy_orders`, `from django.utils import timezone`):

```python
class VerifyEmailView(APIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = EmailVerifySerializer

    @extend_schema(request=EmailVerifySerializer, responses={200: None})
    def post(self, request):
        serializer = EmailVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            email = read_verify_token(serializer.validated_data["token"])
        except VerifyTokenError:
            return Response({"detail": "Invalid or expired verification link."}, status=400)
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            return Response({"detail": "Invalid verification link."}, status=400)
        if user.email_verified_at is None:
            user.email_verified_at = timezone.now()
            user.save(update_fields=["email_verified_at"])
        claimed = claim_legacy_orders(user)
        return Response({"detail": "Email verified.", "orders_claimed": claimed})
```

- [ ] **Step 6: Send the verify email on registration**

The existing `RegisterView` is a bare `generics.CreateAPIView`. Give it a `perform_create` that enqueues the verification email (import `make_verify_token`, `send_email_task`, `settings` at the top of `views.py` if not present — `send_email_task` is already imported):

```python
class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]

    def perform_create(self, serializer):
        from django.conf import settings

        from apps.accounts.verification import make_verify_token

        user = serializer.save()
        token = make_verify_token(user.email)
        verify_url = f"{settings.FRONTEND_URL}/verify-email?token={token}"
        send_email_task.delay(
            "verify_email", user.email,
            {"verify_url": verify_url, "first_name": user.first_name},
        )
```

- [ ] **Step 7: Also claim on password-reset-confirm**

In `PasswordResetConfirmView.post`, after `user.set_password(...)` / `user.save(...)`, add (a completed reset proves inbox control):

```python
        from django.utils import timezone

        from apps.accounts.claims import claim_legacy_orders

        if user.email_verified_at is None:
            user.email_verified_at = timezone.now()
            user.save(update_fields=["email_verified_at"])
        claim_legacy_orders(user)
```

- [ ] **Step 8: URL + email templates**

In `urls.py`, import `VerifyEmailView` and add:

```python
    path("verify-email/", VerifyEmailView.as_view(), name="verify_email"),
```

Create the three templates mirroring an existing set (copy the shape of `password_reset.*` under `apps/notifications/templates/email/`):
- `verify_email.subject.txt`: `Confirm your Toké Cosmetics email`
- `verify_email.txt`: a plain-text body using `{{ first_name }}` and `{{ verify_url }}`.
- `verify_email.html`: the brand-styled HTML equivalent.

- [ ] **Step 9: Run tests**

```bash
uv run pytest apps/accounts -q
```

Expected: PASS.

- [ ] **Step 10: Mutation-verify**

In `claim_legacy_orders`, remove `user__isnull=True` from the filter. Confirm `test_claim_ignores_orders_that_already_have_a_user` goes RED (the owned order is now matched, so the count is 1, not 0). Revert. Then change `email__iexact` to `email__exact`; confirm `test_claim_attaches_userless_orders_matching_email` goes RED (the `ADA@b.com` order is missed). Revert.

- [ ] **Step 11: Commit**

```bash
git add apps/accounts apps/notifications
git commit -m "feat: claim legacy guest orders on email verification

Verify-email endpoint (signed token, mirrors orders/tokens) marks the account verified
and attaches user-less migrated orders matching the verified email. Registration sends
the verify link; a completed password reset also verifies and claims. Never re-points an
order that already has a user.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 13: Newsletter app — throttled capture + signed unsubscribe

**Why:** the storefront footer (Plan-12) needs a place to POST an email so the list grows from day one; campaign *sending* is Plan-30. Capture is public and abuse-prone, so it is throttled 5/min/IP, and unsubscribe uses a signed token link (no login, no enumerable id).

**Files:**
- Create: `backend/apps/newsletter/{__init__.py,apps.py,models.py,serializers.py,views.py,urls.py,admin.py,tokens.py,migrations/__init__.py,tests/__init__.py,tests/test_api.py}`
- Modify: `backend/config/settings/base.py` (`INSTALLED_APPS`, throttle rate), `backend/config/urls.py`

- [ ] **Step 1: Write the failing tests**

`backend/apps/newsletter/tests/test_api.py`:

```python
import pytest
from rest_framework.test import APIClient

from apps.newsletter.models import NewsletterSubscriber
from apps.newsletter.tokens import make_unsubscribe_token


@pytest.mark.django_db
def test_public_subscribe_creates_a_subscriber():
    r = APIClient().post("/api/v1/newsletter/",
                         {"email": "a@b.com", "source": "footer"}, format="json")
    assert r.status_code in (200, 201)
    sub = NewsletterSubscriber.objects.get(email="a@b.com")
    assert sub.consented_at is not None
    assert sub.unsubscribed_at is None


@pytest.mark.django_db
def test_subscribing_twice_is_idempotent():
    c = APIClient()
    c.post("/api/v1/newsletter/", {"email": "a@b.com"}, format="json")
    c.post("/api/v1/newsletter/", {"email": "A@b.com"}, format="json")  # case-insensitive
    assert NewsletterSubscriber.objects.filter(email="a@b.com").count() == 1


@pytest.mark.django_db
def test_unsubscribe_via_signed_token():
    sub = NewsletterSubscriber.objects.create(email="a@b.com", source="footer")
    token = make_unsubscribe_token("a@b.com")

    r = APIClient().get(f"/api/v1/newsletter/unsubscribe/?token={token}")
    assert r.status_code == 200
    sub.refresh_from_db()
    assert sub.unsubscribed_at is not None


@pytest.mark.django_db
def test_unsubscribe_rejects_a_bad_token():
    r = APIClient().get("/api/v1/newsletter/unsubscribe/?token=garbage")
    assert r.status_code == 400


@pytest.mark.django_db
def test_subscribe_is_throttled_at_5_per_minute(settings):
    settings.REST_FRAMEWORK = {
        **settings.REST_FRAMEWORK,
        "DEFAULT_THROTTLE_RATES": {**settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],
                                   "newsletter": "5/min"},
    }
    c = APIClient()
    codes = [c.post("/api/v1/newsletter/", {"email": f"u{i}@b.com"}, format="json").status_code
             for i in range(6)]
    assert codes.count(429) >= 1        # the 6th in a minute is throttled
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest apps/newsletter -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'apps.newsletter'`.

- [ ] **Step 3: Scaffold + INSTALLED_APPS + throttle rate**

```bash
cd tokecosmetics-platform/backend
uv run python manage.py startapp newsletter apps/newsletter
```

Set `name = "apps.newsletter"` in `apps.py`; delete generated `views.py`/`tests.py`; create `tests/__init__.py`. Add `"apps.newsletter"` to `INSTALLED_APPS`. In `REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]` (config/settings/base.py) add:

```python
        "newsletter": "5/min",
```

- [ ] **Step 4: Model**

`backend/apps/newsletter/models.py`:

```python
from django.db import models
from django.utils import timezone

from apps.core.models import TimeStampedModel


class NewsletterSubscriber(TimeStampedModel):
    """A marketing-list membership. Capture only (Plan-11); campaign sending is Plan-30.
    Re-subscribing after an unsubscribe clears unsubscribed_at rather than duplicating."""

    email = models.EmailField(unique=True)
    source = models.CharField(max_length=40, blank=True)  # "footer", "checkout", ...
    consented_at = models.DateTimeField(default=timezone.now)
    unsubscribed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        state = "unsubscribed" if self.unsubscribed_at else "active"
        return f"{self.email} ({state})"
```

- [ ] **Step 5: Migration**

```bash
uv run python manage.py makemigrations newsletter
```

- [ ] **Step 6: Unsubscribe token**

`backend/apps/newsletter/tokens.py`:

```python
"""Signed unsubscribe token — mirrors apps.orders.tokens. No stored token, HMAC'd with
SECRET_KEY; the email is read out of the token so a link can only unsubscribe itself."""
from __future__ import annotations

from django.core import signing

UNSUB_SALT = "newsletter.unsubscribe"


class UnsubscribeTokenError(Exception):
    pass


def make_unsubscribe_token(email: str) -> str:
    return signing.dumps({"e": email.lower(), "s": "unsub"}, salt=UNSUB_SALT)


def read_unsubscribe_token(token: str) -> str:
    try:
        payload = signing.loads(token, salt=UNSUB_SALT)  # no expiry — links live in inboxes
    except signing.BadSignature as exc:
        raise UnsubscribeTokenError(str(exc)) from exc
    if not isinstance(payload, dict) or payload.get("s") != "unsub" or not payload.get("e"):
        raise UnsubscribeTokenError("token is not an unsubscribe token")
    return payload["e"]
```

- [ ] **Step 7: Serializer + views**

`backend/apps/newsletter/serializers.py`:

```python
from rest_framework import serializers


class SubscribeSerializer(serializers.Serializer):
    email = serializers.EmailField()
    source = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")

    def validate_email(self, value):
        return value.lower()
```

`backend/apps/newsletter/views.py`:

```python
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.newsletter.models import NewsletterSubscriber
from apps.newsletter.serializers import SubscribeSerializer
from apps.newsletter.tokens import UnsubscribeTokenError, read_unsubscribe_token


class SubscribeView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "newsletter"          # 5/min/IP (DEFAULT_THROTTLE_RATES)
    serializer_class = SubscribeSerializer

    def post(self, request):
        serializer = SubscribeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        sub, created = NewsletterSubscriber.objects.get_or_create(
            email=data["email"], defaults={"source": data["source"]}
        )
        if not created and sub.unsubscribed_at is not None:
            # A returning subscriber — clear the opt-out, re-stamp consent.
            sub.unsubscribed_at = None
            sub.consented_at = timezone.now()
            sub.save(update_fields=["unsubscribed_at", "consented_at", "updated_at"])
        code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response({"detail": "Subscribed."}, status=code)


class UnsubscribeView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        token = request.query_params.get("token", "")
        try:
            email = read_unsubscribe_token(token)
        except UnsubscribeTokenError:
            return Response({"detail": "Invalid unsubscribe link."}, status=400)
        sub = NewsletterSubscriber.objects.filter(email=email).first()
        if sub and sub.unsubscribed_at is None:
            sub.unsubscribed_at = timezone.now()
            sub.save(update_fields=["unsubscribed_at", "updated_at"])
        # Idempotent: an already-unsubscribed or unknown email still returns 200 here so
        # the link never leaks whether an address is on the list.
        return Response({"detail": "You have been unsubscribed."})
```

- [ ] **Step 8: URLs + admin**

`backend/apps/newsletter/urls.py`:

```python
from django.urls import path

from apps.newsletter.views import SubscribeView, UnsubscribeView

urlpatterns = [
    path("newsletter/", SubscribeView.as_view(), name="newsletter-subscribe"),
    path("newsletter/unsubscribe/", UnsubscribeView.as_view(), name="newsletter-unsubscribe"),
]
```

Mount in `config/urls.py`:

```python
    path("api/v1/", include("apps.newsletter.urls")),
```

`backend/apps/newsletter/admin.py`:

```python
from django.contrib import admin

from apps.newsletter.models import NewsletterSubscriber


@admin.register(NewsletterSubscriber)
class NewsletterSubscriberAdmin(admin.ModelAdmin):
    list_display = ("email", "source", "consented_at", "unsubscribed_at")
    list_filter = ("source",)
    search_fields = ("email",)
```

- [ ] **Step 9: Run tests**

```bash
uv run pytest apps/newsletter -q
```

Expected: PASS. (If the throttle test is flaky under a shared cache, confirm the autouse `_clear_cache` fixture in the root `conftest.py` runs — it clears LocMemCache, which is where DRF stores throttle history in dev.)

- [ ] **Step 10: Mutation-verify**

Remove `throttle_classes`/`throttle_scope` from `SubscribeView`. Confirm `test_subscribe_is_throttled_at_5_per_minute` goes RED. Revert. Then in `read_unsubscribe_token`, remove the scope check (`payload.get("s") != "unsub"`); confirm nothing regresses but note the salt still protects it — leave the check in.

- [ ] **Step 11: Commit**

```bash
git add apps/newsletter config
git commit -m "feat: newsletter capture (5/min/IP) + signed-token unsubscribe

Public subscribe is idempotent and re-subscribes clear a prior opt-out; unsubscribe is
a signed link (no login, no enumerable id). Campaign sending is Plan-30.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 14: Documentation

**Files:**
- Modify: `docs/architecture.md` (repo root)

- [ ] **Step 1: Write § "Customer accounts (Plan-11)"**

Cover:
1. **Addresses:** per-country rules come from `core.address_rules.required_fields_for` (one source); region FKs kept consistent; exactly one default-shipping/billing per user.
2. **Account deletion is two-phase:** `is_active=False` immediately (login dies, refresh tokens blacklisted), PII scrubbed after 30 days by `anonymize_deleted_accounts` (daily beat). State the exact scrub set (D3) and that **order rows survive with the user link intact but PII blanked** — Plan-28 accounting must not assume a deleted user's orders vanish.
3. **Reviews moderation:** born `pending`; the **denormalised `Product.rating_avg`/`rating_count` are written ONLY by `reviews.services.recompute_product_rating`, from approved reviews only.** Never treat these as writable. The approval API is Plan-18; the admin action lands now.
4. **Search sync (D2):** ratings show on cards via the catalog cache-bump on `Product.save`; **Plan-07b's Meilisearch document mapping must include `rating_avg`/`rating_count`** — record this as a Plan-07b requirement.
5. **Legacy claiming:** only `user=None` orders are ever attached, only on a **verified** email, never re-pointing an owned order. Plan-22's migration must leave guest orders with `user=None` + the real `email` for this to work.
6. **Email verification** exists as a lightweight signed-token flow (no verified-vs-unverified gate on checkout — verification only gates order-claiming for now). If a future plan needs "must verify before ordering", it builds on `User.email_verified_at`.

- [ ] **Step 2: Commit**

```bash
git add docs
git commit -m "docs: accounts — addresses, two-phase deletion, review moderation, claiming

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 15: Full suite + driven verification checkpoint

**Tests are not this checkpoint.** Drive the real HTTP endpoints against real Postgres, seeded via the ORM, and read the responses yourself — the project convention (Plan-09b/14a's lesson: rendering the artefact found bugs a green suite did not).

- [ ] **Step 1: Full suite + ruff**

```bash
cd tokecosmetics-platform/backend
uv run pytest -q
uv run ruff check .
```

Expected: green — the ~451 pre-existing + 1 skipped baseline, plus every test this plan added. Ruff clean. **If you see hundreds of DB errors, restart the docker dev stack before believing them.**

- [ ] **Step 2: Drive the endpoints (nothing mocked)**

```bash
docker compose -f docker-compose.dev.yml up -d
uv run python manage.py runserver
```

Seed via `uv run python manage.py shell` (ORM), then exercise with `curl`/httpie against the running server. Concrete steps a reviewer can run:

1. **Register** `POST /api/v1/auth/register/` → 201; confirm a `verify_email` message is in the console email backend output.
2. **Token** `POST /api/v1/auth/token/` → grab the access token for the calls below (`Authorization: Bearer …`).
3. **Profile** `GET /api/v1/auth/me/` → shows `toke_id`; `PATCH` names/phone/`marketing_consent` sticks; `toke_id`/`email` in the body are ignored.
4. **Password change** `POST /api/v1/auth/password/change/` with the wrong old password → 400; with the right one → 200, and the old token still works but a fresh login needs the new password.
5. **Addresses** `POST /api/v1/me/addresses/` for **NG without a `state_region`** → 400 naming `state_region`; with a real Lagos region id → 201. `POST` for **GB without a postcode** → 400. `set-default-shipping/` on a second address clears the first.
6. **Wishlist** `POST /api/v1/me/wishlist/ {"sku": …}` (header `X-Country: NG`) → 201; `GET` shows the product card with an NGN `from_price`; same SKU again → no duplicate; `DELETE /api/v1/me/wishlist/<sku>/` → 204.
7. **Reviews** — seed a `delivered` order containing a product for the user. `POST /api/v1/products/<slug>/reviews/` → 201 `pending`. `GET` (anon) → empty (nothing approved). Approve it in the Django admin (`/django-admin/reviews/review/`, "Approve selected reviews"), then `GET` → the review appears **and** `GET /api/v1/products/<slug>/` shows `rating_avg: "X.XX"`, `rating_count: 1`. A second user with **no** delivered order → 403.
8. **Legacy claiming** — ORM-create an `Order(user=None, email="ada@b.com", source="legacy_ng")`. `POST /api/v1/auth/verify-email/` with a token from `make_verify_token("ada@b.com")` → 200 `orders_claimed: 1`; the order now has `user` set. A token for a different email does not claim it.
9. **Account deletion** `POST /api/v1/auth/account/delete/` with the password → 200; the user is `is_active=False` and cannot obtain a token. Then in the shell, backdate `deletion_requested_at` 31 days and run `anonymize_deleted_accounts()` → email becomes `deleted-TK-…@deleted.invalid`, addresses gone, order snapshot blanked.
10. **Newsletter** `POST /api/v1/newsletter/ {"email": …}` six times fast → at least one `429`. `GET /api/v1/newsletter/unsubscribe/?token=<make_unsubscribe_token(email)>` → 200 and `unsubscribed_at` set.
11. **Swagger** open `/api/docs/` → every new endpoint appears with a schema (drf-spectacular).

- [ ] **Step 3: Show Hammed the compact API demo**

Show: the NG-vs-GB address validation 400s, a wishlist card with a resolved price, a pending→approved review flipping the product's star rating, and a legacy order attaching on verify-email. **Do not mark this plan done without his sign-off** (spec: "CHECKPOINT: compact API demo").

- [ ] **Step 4: Merge**

```bash
git checkout main
git merge --no-ff plan-11-accounts
```

---

## Follow-ups — deliberately NOT built here

- **Review approval/rejection API** (`Plan-18`) — only the model + Django-admin action land now.
- **Meilisearch rating fields** (`Plan-07b`) — the document mapping must include `rating_avg`/`rating_count`; today the catalog cache-bump carries the change (D2).
- **Verified-before-ordering gate** — `email_verified_at` exists but does not gate checkout; a future plan can build on it.
- **Review edit / re-review** — `unique_together(product, user)` means one row; editing it is Plan-18.
- **Newsletter double opt-in / welcome email** — capture only now; Plan-30 owns sending.
- **Storefront wiring** (account area, wishlist heart, review form) — Plan-12+.

---

## Self-review — spec coverage

| Spec item (master lines 878–888) | Task |
|---|---|
| Addresses CRUD `/api/v1/me/addresses/` + set-default, per-country rules (NG state+LGA, GB/US/CA postcode) | 2, 3 |
| Profile GET/PATCH (names, phone, marketing_consent) + read-only `toke_id` | 4 (already shipped; pinned by test) |
| Password change (old-password required) | 1 |
| Account deletion (soft `is_active=False`, anonymise after 30d) | 5, 6 |
| Wishlist GET/POST/DELETE (variant ids), country-resolved cards | 7, 8 |
| Reviews POST verified-purchase only, pending→approved, GET approved only | 10, 11 |
| `rating_avg`/`rating_count` denormalised on approval + synced to search | 9, 10 (D2 records the Meili follow-up) |
| Django-admin approval action now; API approval is Plan-18 | 10 |
| Legacy guest-order claiming on email match, on verification | 12 (D1) |
| Newsletter `POST /api/v1/newsletter/` throttled 5/min/IP + unsubscribe link | 13 |
| Verification (pytest + Swagger smoke); CHECKPOINT compact API demo | 15 |
