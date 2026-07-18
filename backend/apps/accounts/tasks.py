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
