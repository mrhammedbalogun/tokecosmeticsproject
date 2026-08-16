"""The four referral emails that exist, and the reasoning for the ones that do not.

`payout_method_changed` is a SECURITY email, not a courtesy one. It is the control that
turns an account-takeover payout redirect from silent into noisy (see
`models.PayoutMethod` for why that, rather than encryption, is where the effort went),
so it is sent on every change and it is not gated on marketing consent — transactional
security notices are not marketing.

`payout_method_added` is the same control aimed at the FIRST save. The original design
sent nothing on an add ("there is nothing to warn about yet") — but the add is exactly
the takeover window: a victim with accrued earnings and no account on file got no email
when a hijacker added one, and the first mail they ever received was `payout_paid`,
after the money had left. Caught in the 2026-08-15 review.

`payout_rejected` exists because the alternative is silence. A refusal that only appears
on a page the customer has no reason to revisit reads, from their side, as the shop
quietly keeping the money — and the one thing they most need to know is the thing the
page states least loudly: the balance came BACK and they can ask again. Added 2026-08-15
on Hammed's word.

`payout_paid` closes the loop on money leaving. Anything that quotes an account number
quotes only the masked form: this mail lands in an inbox, which is the least controlled
place the shop writes to.

DELIBERATELY ABSENT for v1: a "you earned a commission" mail on every referred sale. It
sounds delightful and it is a spam cannon — a referrer having a good week gets one per
order, from a domain whose deliverability is already fragile (see the admin-email
deliverability work). A weekly digest is the right shape and belongs with the admin
phase, once there is somewhere to configure it.
"""
from __future__ import annotations

from django.conf import settings

from apps.notifications.tasks import send_email_task
from apps.payments.money import format_money
from apps.referrals.models import PayoutMethod, PayoutRequest


def enqueue_payout_method_added(method_pk: int) -> None:
    _enqueue_method_notice("referral_payout_method_added", method_pk)


def enqueue_payout_method_changed(method_pk: int) -> None:
    _enqueue_method_notice("referral_payout_method_changed", method_pk)


def _enqueue_method_notice(template: str, method_pk: int) -> None:
    method = (
        PayoutMethod.objects.select_related("user", "currency").filter(pk=method_pk).first()
    )
    if method is None:
        return
    send_email_task.delay(
        template,
        method.user.email,
        {
            "first_name": method.user.first_name,
            "currency": method.currency.code,
            "bank_name": method.bank_name,
            "account_name": method.account_name,
            "account_masked": method.account_number_masked,
            # Built from settings, never hardcoded in the template: the storefront
            # origin differs between dev, staging and production, and a security email
            # that sends a worried customer to the wrong host is worse than useless.
            "security_url": f"{settings.FRONTEND_URL.rstrip('/')}/account/security",
        },
    )


def enqueue_payout_paid(request_pk: int) -> None:
    req = (
        PayoutRequest.objects.select_related("referrer", "currency")
        .filter(pk=request_pk)
        .first()
    )
    if req is None:
        return
    snapshot = req.method_snapshot or {}
    account = str(snapshot.get("account_number", ""))
    send_email_task.delay(
        "referral_payout_paid",
        req.referrer.email,
        {
            "first_name": req.referrer.first_name,
            "amount": format_money(req.amount, req.currency),
            "bank_name": snapshot.get("bank_name", ""),
            # Masked here rather than trusting the snapshot's shape: the snapshot holds
            # the full number on purpose (it is the shop's own audit record of where
            # money went) and an email is not the place for it.
            "account_masked": f"•••• {account[-4:]}" if len(account) > 4 else account,
            "reference": req.reference,
        },
    )


def enqueue_payout_rejected(request_pk: int) -> None:
    """Tell the referrer their request was refused, why, and that the money is still theirs.

    Sends the staff member's own `customer_message` verbatim rather than a template
    sentence: the reviewer is the only person who knows what went wrong, the serializer
    makes the field mandatory for exactly that reason, and paraphrasing it here would
    reintroduce the vagueness the mandatory field exists to remove.

    NOT gated on marketing consent — this is a transactional notice about the customer's
    own money, in the same class as `payout_method_changed`.
    """
    req = (
        PayoutRequest.objects.select_related("referrer", "currency")
        .filter(pk=request_pk)
        .first()
    )
    if req is None:
        return
    send_email_task.delay(
        "referral_payout_rejected",
        req.referrer.email,
        {
            "first_name": req.referrer.first_name,
            "amount": format_money(req.amount, req.currency),
            "currency": req.currency.code,
            "customer_message": req.customer_message,
            # Same reasoning as the security mail's `security_url`: built from settings so
            # dev, staging and production each send people to their own storefront.
            "referrals_url": f"{settings.FRONTEND_URL.rstrip('/')}/account/referrals",
        },
    )
