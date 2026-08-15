"""anonymize_deleted_accounts — the second phase of soft account deletion.

Mirrors expire_pending_orders / complete_delivered_orders: a daily beat task, ONE
transaction per user, re-checking under the lock, per-user try/except so one poison
row can't starve the sweep. Idempotent: the anonymised sentinel email means an
already-scrubbed user is not matched again.

Plan-16 Task 4 added a fourth thing to scrub: the VALUES inside `AuditLog.changes` for
rows about this customer. The keys, object id, actor, IP, session and timestamp stay —
see `apps/core/audit.redact_audit_values` for why keeping the shape of a deleted
customer's rows is what lets the deletion promise and the audit promise both be true.
"""
import logging

from celery import shared_task
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import ANONYMISED_EMAIL_DOMAIN

logger = logging.getLogger(__name__)

GRACE_DAYS = 30
# Aliased rather than restated: `UserManager.admin_visible()` excludes rows carrying this
# suffix, which is how global search (and the Plan-18 customer list) learn not to show an
# anonymised account. Two copies of the string would mean a deleted customer stayed
# findable in one of the two places.
_SENTINEL_DOMAIN = ANONYMISED_EMAIL_DOMAIN


def _scrub_payout_details(user) -> None:
    """Remove a deleted customer's bank details, keeping the financial record.

    Two different things live in the referrals app and they get different treatment,
    because "delete my account" and "keep honest books" pull in opposite directions:

    * `PayoutMethod` is a standing instruction — where to send the NEXT payout. There
      will not be one, so the row is DELETED outright, like the address book above it.
    * `PayoutRequest.method_snapshot` is the record of where money the shop actually
      sent went. That has to survive (it is the answer to "prove you paid me"), but it
      holds the full account number, so it is REDUCED to the bank name and the last four
      digits — the same masked form the API has always shown the customer.

    So the shop can still say "₦31,000 went to GTBank ••••6789 on 30 September, reference
    GTB/2026/0042" without holding a deleted customer's account number.

    Imported inside the function: `apps.accounts` is imported by nearly everything, and a
    module-level import of the referrals app here would be a circular one.
    """
    from apps.referrals.models import PayoutMethod, PayoutRequest

    PayoutMethod.objects.filter(user=user).delete()
    for payout in PayoutRequest.objects.filter(referrer=user):
        snapshot = payout.method_snapshot or {}
        number = str(snapshot.get("account_number", ""))
        payout.method_snapshot = {
            "bank_name": snapshot.get("bank_name", ""),
            "currency": snapshot.get("currency", ""),
            "account_number": f"••••{number[-4:]}" if len(number) > 4 else "",
            "redacted": True,
        }
        payout.save(update_fields=["method_snapshot", "updated_at"])


def _anonymize_one(pk: int) -> bool:
    from apps.core.audit import redact_audit_values
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
        # Captured BEFORE the address is overwritten: it is the needle used to find
        # audit rows that recorded a staff SEARCH for this customer, which have no
        # object id to match on because a list has no object.
        old_email = user.email
        order_numbers = list(
            Order.objects.filter(user=user).values_list("number", flat=True)
        )
        user.email = sentinel
        user.first_name = ""
        user.last_name = ""
        user.phone = ""
        user.whatsapp = ""
        user.marketing_consent = False
        user.set_unusable_password()
        user.save(update_fields=[
            "email", "first_name", "last_name", "phone", "whatsapp",
            "marketing_consent", "password",
        ])
        user.addresses.all().delete()
        # Scrub the order snapshots too — the link stays, the PII does not (D3).
        Order.objects.filter(user=user).update(
            email=sentinel, phone="", shipping_address={}, billing_address={},
        )
        _scrub_payout_details(user)
        # THE ROW SURVIVES, THE VALUES DO NOT (Plan-16 Task 4). Audit rows about this
        # customer keep their keys, object id, actor, IP, session and timestamp, and
        # lose only the values — so "staff member X edited customer 123's address at
        # 14:02" stays provable without the address still being on file. The two
        # promises this project makes are then both true at once: deletion means the
        # data is gone, and the audit trail is still an audit trail.
        #
        # Inside the same transaction as the rest of the scrub, so a failure here leaves
        # the account un-anonymised and the sweep retries it, rather than reporting a
        # deletion that only half happened.
        # Both needles, and the toke_id is the one Task 6 added. Global search is the one
        # place a staff member types a customer's PUBLIC id rather than their address, so
        # without it `TK-7X4KQZ` would sit in the log after the person it names had been
        # deleted. See `redact_audit_values` for the two limits this does NOT close —
        # notably that a partial typed prefix of the address is not matched and lives out
        # its ≤90 days under `tombstone_expired_search_terms` instead.
        redact_audit_values(
            model_labels_and_ids=[
                ("accounts.user", [user.pk]),
                ("orders.order", order_numbers),
            ],
            text_needles=(old_email, user.toke_id),
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
