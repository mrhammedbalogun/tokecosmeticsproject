"""Who gets emailed about what. One table, two kinds of row.

WHY THIS TABLE EXISTS. Until now every staff-facing alert in this codebase was addressed
to `settings.DEFAULT_FROM_EMAIL` (`apps/inventory/tasks.py`, `apps/delivery/tasks.py`) —
the Resend SENDING domain, which has no inbox. Those alerts have been mailing nobody. A
recipient list an operator can see and edit is the fix, and "new order" is the event that
finally made it worth building.

── TWO KINDS OF ROW, AND WHY BOTH ARE NEEDED ───────────────────────────────────────

A row names EITHER a staff account (`user`) OR a bare address (`email`), never both and
never neither. A `CheckConstraint` enforces it, because a row with neither is a
subscription that silently mails nobody — the exact failure this table was built to end —
and a row with both raises "which wins?" for every future reader of `address`.

**Staff rows hold a ForeignKey, not a copy of the address.** This is about the day
somebody LEAVES. Deactivate a staff account and their subscription stops resolving on the
next send, with no second place to remember; store the address as a string instead and an
ex-employee keeps receiving customers' names and order contents until someone remembers
this screen exists. `address` re-checks `is_active` and `is_staff` at SEND time rather
than trusting the row — deactivation in this codebase is a flag flip, not a delete
(`apps/accounts/invites.py`), so `on_delete=CASCADE` alone would not save us. The FK also
means a staff member who changes their email keeps their subscriptions.

**Standalone rows exist because the owner asked for them** — a packer, a bookkeeper, a
warehouse address with no business holding an admin login. They are the sharper edge of
this table: a bare address on `order.paid` receives order contents with no account, no
invite and no second factor behind it. That is why these endpoints are Owner-only
(`settings.manage`) and audited, why the staff email deliberately carries no customer
phone number or street address (`apps/orders/emails.py::_staff_context`), and why the
admin screen labels these rows as external instead of letting them blend into the staff
list.

── EMAIL IS STORED LOWERCASED ──────────────────────────────────────────────────────

`save()` normalises it. Without that, `Sales@x.com` and `sales@x.com` are two rows, two
identical emails to one inbox, and a uniqueness constraint that cannot see the collision.
The local part of an address is technically case-sensitive per RFC 5321; no mail provider
anyone uses actually treats it so, and a duplicate alert every time an order lands is a
worse bug than the theoretical one.

── WHY `event` HAS NO `choices` ────────────────────────────────────────────────────

Deliberately a bare CharField. `choices` sourced from a code registry makes
`makemigrations` emit a no-op `AlterField` every time an event is added — friction that
teaches you not to add events, defeating the point of a registry. The validation lives in
the serializer, against `events.EVENTS_BY_CODE`, which is where a bad code should be
refused anyway.

The same choice means a code REMOVED from the registry leaves its rows behind rather than
cascading them away. That is the safe direction: an event renamed in a refactor should
strand a visible, recoverable row, not silently unsubscribe the Owner.
`resolve_recipients()` ignores unregistered codes, and the admin serializer surfaces them
so the screen can offer a delete rather than hiding them.

── WHY NOT AN `is_active` FLAG ON THE ROW ──────────────────────────────────────────

Considered and rejected. The list is short, visible in full on one screen, and trivially
rebuilt; a paused row is a way to believe somebody is subscribed when they are not.
Deleting is the honest "stop emailing this person", and the audit log keeps the history.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel
from apps.notifications.events import EVENTS_BY_CODE


class NotificationRecipient(TimeStampedModel):
    event = models.CharField(max_length=50, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="notification_subscriptions",
        help_text="A staff account. Deleting the account removes the subscription.",
    )
    email = models.EmailField(
        blank=True,
        help_text="An address with no admin account. Blank on staff rows.",
    )

    class Meta:
        constraints = [
            # Exactly one of the two. `condition=` and not the deprecated `check=`
            # (Django 5.2 warns on the old spelling; apps/inventory/models.py still uses
            # it and is where the deprecation warnings in the test run come from).
            models.CheckConstraint(
                condition=(
                    models.Q(user__isnull=False, email="")
                    | (models.Q(user__isnull=True) & ~models.Q(email=""))
                ),
                name="notification_recipient_user_xor_email",
            ),
            # One subscription per person per event. BOTH are CONDITIONAL, and that is
            # not decoration:
            #
            # * `(event, email)` must exclude `email=""` or it collides on every staff
            #   row — the empty string is a value, unlike NULL, so the SECOND staff
            #   member added to an event would raise IntegrityError. That bug survives
            #   any happy-path test with one recipient and appears the day the shop adds
            #   a colleague.
            # * `(event, user)` must exclude NULL users. Postgres treats each NULL as
            #   distinct so it would not error, but stating the condition keeps the two
            #   constraints reading as the pair they are.
            models.UniqueConstraint(
                fields=["event", "user"],
                condition=models.Q(user__isnull=False),
                name="uniq_notification_recipient_user_per_event",
            ),
            models.UniqueConstraint(
                fields=["event", "email"],
                condition=~models.Q(email=""),
                name="uniq_notification_recipient_email_per_event",
            ),
        ]
        ordering = ["event", "email", "user_id"]

    def save(self, *args, **kwargs):
        # Normalised on the model, not only in the serializer: a management command, a
        # data migration and a shell session all write rows too, and the uniqueness
        # constraint above is only as good as the normalisation behind it.
        self.email = (self.email or "").strip().lower()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.event} -> {self.address or '(unresolvable)'}"

    @property
    def address(self) -> str:
        """The address this row would be mailed at, or "" if it resolves to nobody — a
        staff account that has been deactivated or demoted out of staff.

        Read by the admin serializer so the screen can SAY "this person no longer
        receives mail" rather than showing a row that looks live and is not."""
        if self.user_id is None:
            return self.email
        if not (self.user.is_active and self.user.is_staff):
            return ""
        return self.user.email


def resolve_recipients(event: str) -> list[str]:
    """Every address subscribed to `event`, deduplicated, ready to send to.

    DEDUPLICATED, CASE-INSENSITIVELY, ON PURPOSE. A manager who is both a staff row and a
    standalone row — easily done, since the standalone form does not know who holds an
    account — would otherwise get two identical mails per order, and the natural
    conclusion from that is that the system is broken.

    Returns `[]` for an unregistered code rather than raising. A caller firing a typo'd
    event should send nothing, not 500 in the middle of an order transition; the typo is
    caught by `test_events.py` at test time, which is where it belongs.

    NO SILENT FALLBACK when the list is empty. An earlier draft fell back to the Owner's
    address so an event could never reach nobody. Rejected: it makes "remove everyone"
    impossible to express, and a fallback that fires invisibly is how the
    DEFAULT_FROM_EMAIL bug this table exists to fix came about in the first place. The
    honest version of that safety net is visible, and it lives in two places — the
    migration seeds every event with the Owner, and the admin screen shows a warning on
    any event whose list is empty.
    """
    if event not in EVENTS_BY_CODE:
        return []
    seen: dict[str, None] = {}
    for row in NotificationRecipient.objects.filter(event=event).select_related("user"):
        address = row.address
        if address:
            seen.setdefault(address.lower(), None)
    return list(seen)
