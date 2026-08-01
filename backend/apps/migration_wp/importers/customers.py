"""WooCommerce users -> accounts.User + LegacyIdentity (Plan-22).

Idempotent on `(store, wp_user_id)` via LegacyIdentity, so the staging run and Plan-27's
cutover delta run reach the same database state.

── THE THREE RULES THAT PREVENT DATA LOSS ───────────────────────────────────────────────

Everything below is one of these three, and every one of them exists because the failure
it prevents is silent — nothing raises, nothing logs an error, a real person simply loses
something and finds out later.

1. **A password is only ever written to an account that still carries an untouched
   WordPress hash.** Not "on create only" — that phrasing is too weak in one direction and
   too strong in the other. The actual property we need is *never overwrite a password a
   human has since chosen*, and the hasher hands us that test for free: if the stored hash
   still starts with `wordpress$`, nobody has logged in or reset since the import, because
   a successful login rehashes to PBKDF2 (`must_update()` is always True). If it does not,
   this importer keeps its hands off. That covers the cutover-delta case the plan called
   out AND the case it did not: a customer who reset their password between the staging
   run and cutover.

2. **A pre-existing account is never modified.** By cutover the Django database holds
   staff — including the owner's own account — and possibly organic signups whose emails
   collide with a WooCommerce customer. Those are identified by `legacy_source == ""`.
   They get a LegacyIdentity attached, so Plan-23 can still find their order history, and
   nothing else: no password, no name, no `is_staff`. Silently replacing a staff account's
   hash with a customer's WordPress hash is the worst outcome available in this file.

3. **Creation goes through `UserManager._create_user`.** It lowercases the email and
   retries `toke_id` collisions. Constructing `User(...)` directly here would work in
   testing and produce duplicate Toke IDs in production, at a rate nobody would notice
   until two customers rang up about each other's orders.

── CROSS-STORE COLLISIONS ───────────────────────────────────────────────────────────────

17 people exist on more than one store (ng∩old 13, ng∩intl 1, old∩intl 3 — measured). Each
store is a separate artifact and a separate run, so precedence cannot be decided by import
order; it is decided by `accounts.best_store` against the `legacy_source` already stored.
A lower-precedence store attaches its identity and leaves the account alone. Import the
three artifacts in any order and the result is identical.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from apps.accounts.hashers import PREFIX as WP_HASH_PREFIX
from apps.accounts.hashers import wrap_wordpress_hash
from apps.accounts.models import STORE_PRECEDENCE, LegacyIdentity
from apps.migration_wp.importers.common import logger

User = get_user_model()


def _rank(store: str) -> int:
    """Lower is more authoritative. An unknown store sorts last and therefore never wins."""
    try:
        return STORE_PRECEDENCE.index(store)
    except ValueError:
        return len(STORE_PRECEDENCE)


def _names(row: dict, meta: dict) -> tuple[str, str]:
    """first/last name, preferring the account's own over the billing copy.

    `display_name` is the last resort and is split on the first space only: "Mary Jane
    Watson" becomes ("Mary", "Jane Watson"), which is wrong for some people and less wrong
    than any other single rule. It is only reached when the customer never filled in a
    name anywhere, in which case both fields are usually the email local-part anyway.
    """
    first = (meta.get("first_name") or meta.get("billing_first_name") or "").strip()
    last = (meta.get("last_name") or meta.get("billing_last_name") or "").strip()
    if first or last:
        return first[:150], last[:150]

    display = (row.get("display_name") or "").strip()
    if " " in display:
        head, tail = display.split(" ", 1)
        return head[:150], tail[:150]
    return display[:150], ""


def _clean_email(raw: str) -> str:
    email = (raw or "").strip().lower()
    if not email:
        return ""
    try:
        validate_email(email)
    except ValidationError:
        return ""
    return email


def _has_untouched_wp_hash(user) -> bool:
    """True only if this account's password is still exactly what WordPress had.

    See rule 1. This is the single test that makes a re-run safe.
    """
    return (user.password or "").startswith(WP_HASH_PREFIX)


def import_customers(data: dict, *, since=None) -> dict:
    """Import one store's customer artifact. Returns a counts-only summary.

    The summary is counts and sample WordPress IDs — never emails or names. It is written
    into the run log and, per the plan, the repo only ever receives counts; PII goes where
    Plan-21's artifacts go.
    """
    store = data["store"]
    rows = data["customers"]
    meta_all = data.get("meta", {})

    created = updated = already = 0
    skipped_no_email: list[int] = []
    skipped_pre_existing: list[int] = []
    skipped_lower_precedence: list[int] = []
    skipped_human_password: list[int] = []
    skipped_not_since = 0

    for row in rows:
        wp_id = int(row["ID"])

        if since and (row.get("user_registered") or "") < since:
            skipped_not_since += 1
            continue

        email = _clean_email(row.get("user_email"))
        if not email:
            # No email means no way to log in and no way to contact them. Importing the
            # row would create an account nobody can ever reach.
            skipped_no_email.append(wp_id)
            continue

        meta = meta_all.get(str(wp_id)) or meta_all.get(wp_id) or {}
        first, last = _names(row, meta)
        phone = (meta.get("billing_phone") or "").strip()[:32]
        wp_hash = wrap_wordpress_hash(row.get("user_pass"))

        identity = LegacyIdentity.objects.filter(store=store, wp_user_id=wp_id).first()
        if identity:
            # Seen on a previous run of THIS store. The account is whatever it is now;
            # rules 1 and 2 decide whether it may be refreshed, exactly as below.
            user = identity.user
        else:
            user = User.objects.filter(email=email).first()

        if user is None:
            # RULE 3: through the manager, which lowercases and retries toke_id.
            user = User.objects._create_user(email=email, password=None, first_name=first,
                                             last_name=last, phone=phone)
            user.password = wp_hash
            user.legacy_source = store
            # email_verified_at stays NULL DELIBERATELY. A WordPress account proves they
            # once had the password, not that they control the inbox today — and
            # apps/accounts/claims.py gates claiming legacy GUEST orders on that flag.
            # Marking them verified here would let whoever holds this password sweep up
            # every guest order that shares the address. They verify the normal way.
            user.save(update_fields=["password", "legacy_source"])
            created += 1
        elif not user.legacy_source:
            # RULE 2: staff, or an organic signup. Attach and touch nothing.
            skipped_pre_existing.append(wp_id)
        elif not _has_untouched_wp_hash(user):
            # RULE 1: they have logged in or reset since the last run. Their password is
            # theirs now.
            skipped_human_password.append(wp_id)
        elif user.legacy_source == store:
            # A re-run of this same store. Rule 1 keeps our hands off: the account is
            # already this store's record of them, and re-writing the password would only
            # ever move it backwards.
            already += 1
        elif _rank(store) < _rank(user.legacy_source):
            # This store outranks the one that created the account: the customer's more
            # authoritative record wins.
            user.first_name, user.last_name = first, last
            user.phone = phone or user.phone
            user.password = wp_hash
            user.legacy_source = store
            user.save(update_fields=["first_name", "last_name", "phone", "password",
                                     "legacy_source"])
            updated += 1
        else:
            skipped_lower_precedence.append(wp_id)

        if identity is None:
            LegacyIdentity.objects.create(user=user, store=store, wp_user_id=wp_id)

    summary = {
        "store": store,
        "rows": len(rows),
        "created": created,
        "already_imported": already,
        "updated_by_precedence": updated,
        "attached_to_pre_existing": len(skipped_pre_existing),
        "left_alone_human_password": len(skipped_human_password),
        "left_alone_lower_precedence": len(skipped_lower_precedence),
        "skipped_no_usable_email": len(skipped_no_email),
        "skipped_before_since": skipped_not_since,
        # Sample WordPress IDs only — never emails. See the docstring on PII.
        "sample_no_email_wp_ids": skipped_no_email[:20],
        "sample_pre_existing_wp_ids": skipped_pre_existing[:20],
    }
    logger.info("import_customers %s: %s", store, summary)
    return summary
