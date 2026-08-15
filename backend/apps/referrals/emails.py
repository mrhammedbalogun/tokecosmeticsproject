"""The two referral emails that exist, and the reasoning for the ones that do not.

`payout_method_changed` is a SECURITY email, not a courtesy one. It is the control that
turns an account-takeover payout redirect from silent into noisy (see
`models.PayoutMethod` for why that, rather than encryption, is where the effort went),
so it is sent on every change and it is not gated on marketing consent — transactional
security notices are not marketing.

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


def enqueue_payout_method_changed(method_pk: int) -> None:
    method = (
        PayoutMethod.objects.select_related("user", "currency").filter(pk=method_pk).first()
    )
    if method is None:
        return
    send_email_task.delay(
        "referral_payout_method_changed",
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
