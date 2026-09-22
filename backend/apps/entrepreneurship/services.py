"""The decisions the programme endpoints make, kept out of the views so they can be
tested without HTTP and so the subtle one is written down once.

── WHY APPLYING NEVER SAYS "YOU HAVE ALREADY APPLIED" ──────────────────────────

Because that sentence tells whoever typed the address that its owner is looking for a
way to make money. This codebase has already refused that trade in the place it is most
tempting — `accounts.views.PasswordResetView` answers 200 to every address precisely so
it cannot be used to prove an account exists — and a student programme is a worse place
to leak it, not a better one: the fact is specific, fresh, and the obvious people to
care are a parent paying the fees and a current employer.

So every successful submission returns the same body, and the de-duplication happens
silently on our side. See `models.ProgramApplication` for the two halves of that rule.

── WHY THE INTAKE IS RE-READ UNDER A LOCK ──────────────────────────────────────

The window between "the page rendered the form" and "the form was submitted" is measured
in minutes, and closing the intake is one click in the admin. The storefront's copy of
`is_open` is a CACHED read (a tagged fetch with a five-minute floor), so it is stale by
construction — which is fine, because this is the authority. Re-reading the settings row
`FOR UPDATE` inside the same transaction that writes the application is what stops a
submission landing after the intake closed. The setting is public information, so
answering "applications have closed" leaks nothing.
"""
from __future__ import annotations

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.entrepreneurship.models import (
    STATUS_NEW,
    ProgramApplication,
    ProgramSettings,
)


class ApplicationRefused(Exception):
    """The application cannot be accepted, and the applicant needs to know why.

    `field` names the form field to paint, or None for a message at the top.
    """

    def __init__(self, message: str, *, field: str | None = None, status: int = 400):
        super().__init__(message)
        self.message = message
        self.field = field
        self.status = status


@transaction.atomic
def record_application(
    *,
    country,
    full_name: str,
    email: str,
    phone: str,
    institution: str,
    academic_level: str,
    course_of_study: str,
    social_handle: str = "",
    motivation: str = "",
) -> ProgramApplication:
    """Write (or replace) exactly one application row.

    ORDER IS DELIBERATE. The intake is locked and re-checked FIRST, so a submission to a
    closed programme never becomes a row somebody has to explain to the student later.
    """
    settings_row = (
        ProgramSettings.objects.select_for_update().filter(pk=1).first()
    )
    # `None` means the singleton has never been written — a fresh database. Treated as
    # OPEN, which is what `ProgramSettings.load()` would have created anyway; refusing
    # here would make "nobody has opened the settings screen yet" look like "the
    # programme is closed" to every visitor.
    if settings_row is not None and not settings_row.is_open:
        raise ApplicationRefused(settings_row.public_closed_message, status=409)

    email = (email or "").strip().lower()

    fields = {
        "country": country,
        "full_name": full_name,
        "phone": phone,
        "institution": institution,
        "academic_level": academic_level,
        "course_of_study": course_of_study,
        "social_handle": social_handle,
        "motivation": motivation,
    }

    existing = (
        ProgramApplication.objects.select_for_update()
        .filter(email=email, status=STATUS_NEW)
        .first()
    )
    if existing is not None:
        for name, value in fields.items():
            setattr(existing, name, value)
        existing.submission_count += 1
        existing.save()
        return existing

    try:
        # Savepoint, because the partial unique index can still refuse this: two submits
        # in the same second both find no existing row. An IntegrityError left uncaught
        # poisons the surrounding transaction and every later query in the request,
        # including the one that renders the response — the same reasoning as
        # `apps.careers.services.record_application` and
        # `apps.stores.admin_views.StoreLocationAdminViewSet.create`.
        with transaction.atomic():
            return ProgramApplication.objects.create(
                email=email,
                is_resubmission=ProgramApplication.objects.filter(email=email).exists(),
                **fields,
            )
    except IntegrityError:
        # Somebody else won the race with an identical submission. Their row is the one
        # that exists; ours would be a duplicate. Returning theirs makes the endpoint
        # idempotent and keeps the response indistinguishable from a first application,
        # which is the whole point (see the module docstring).
        winner = ProgramApplication.objects.filter(
            email=email, status=STATUS_NEW
        ).first()
        if winner is None:
            raise
        return winner


def mark_reviewed(application: ProgramApplication, user) -> None:
    """Stamp who last moved this application and when.

    Only on a STATUS change, not on a note edit: "reviewed by" answers "who decided", and
    a typo fix in the notes is not a decision.
    """
    application.reviewed_by = user if getattr(user, "is_authenticated", False) else None
    application.reviewed_at = timezone.now()
