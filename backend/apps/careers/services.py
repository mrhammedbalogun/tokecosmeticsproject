"""The decisions the careers endpoints make, kept out of the views so they can be
tested without HTTP and so the two that are genuinely subtle are written down once.

── WHY APPLYING NEVER SAYS "YOU HAVE ALREADY APPLIED" ──────────────────────────

Because that sentence tells whoever typed the address that its owner is job-hunting.
This codebase has already refused that trade once, in the place it is most tempting:
`accounts.views.PasswordResetView` answers 200 to every address precisely so it
cannot be used to prove an account exists. An employer's application form is a WORSE
place to leak it — the fact is fresher, more specific ("applied to Toke, for Sales
Rep, on Tuesday"), and the obvious people to care are a current employer and an
abusive partner.

So every successful submission returns the same body, and the de-duplication happens
silently on our side:

* **an untouched application from the same person for the same role is REPLACED.**
  New CV, new cover letter, `submission_count` incremented, old S3 object removed.
  This is also the candidate's own fix for attaching the wrong file — the single most
  common support email a careers form generates, answered without a support email.
* **an application staff have already moved (in review, shortlisted…) is LEFT ALONE**
  and a second row is created, flagged `is_resubmission`. Nobody who merely knows an
  address can overwrite a review in progress, and the reviewer sees both.

── WHY THE ROLE IS RE-READ UNDER A LOCK ───────────────────────────────────────

The window between "the page rendered the form" and "the form was submitted" is
measured in minutes, and closing a role is a single click. Re-reading the posting
`FOR UPDATE` inside the same transaction that writes the row is what stops an
application landing against a role that closed while the applicant was typing. The
posting's own state is public, so answering "this role has just closed" leaks nothing.
"""
from __future__ import annotations

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.careers import resume_storage
from apps.careers.models import (
    APPLICATION_NEW,
    JobApplication,
    JobLocation,
    JobPosting,
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


def public_postings():
    """Everything the careers page may show: open AND closed, never draft or archived.

    A CLOSED role stays listed with its badge. Removing it the moment it is filled makes
    the candidate who bookmarked it, or who is halfway through their CV, believe the site
    broke — and a visible "applications closed" is the answer to the email they would
    otherwise send.
    """
    return (
        JobPosting.objects.filter(archived_at__isnull=True, status__in=("open", "closed"))
        .select_related("country")
        .prefetch_related("locations")
    )


def resolve_location(job: JobPosting, location_id) -> JobLocation | None:
    """The chosen city, proved to belong to THIS posting.

    Proving the parentage matters: without it a crafted id attaches an application for
    the Lagos operations role to a location row belonging to a different posting, and the
    admin list then shows a place that role never advertised.
    """
    options = list(job.locations.all())
    if not options:
        # The posting names no locations, so the form showed no picker. A value sent
        # anyway is ignored rather than refused — it costs the applicant nothing and
        # there is nothing to attach it to.
        return None
    if location_id in (None, "", 0):
        raise ApplicationRefused("Choose which location you are applying for.", field="location")
    try:
        wanted = int(location_id)
    except (TypeError, ValueError):
        raise ApplicationRefused("Choose which location you are applying for.", field="location") from None
    for option in options:
        if option.pk == wanted:
            return option
    # Reachable honestly: the location was removed between the page rendering and the
    # submit. Named as a field error so the form can re-render the picker.
    raise ApplicationRefused(
        "That location is no longer listed for this role. Choose another.", field="location"
    )


@transaction.atomic
def record_application(
    *,
    job: JobPosting,
    full_name: str,
    email: str,
    phone: str,
    cover_letter: str,
    location_id,
    incoming_key: str,
    resume_filename: str,
) -> JobApplication:
    """Verify the upload, then write (or replace) exactly one application row.

    ORDER IS DELIBERATE. The role is locked and re-checked BEFORE the file is copied out
    of quarantine, so an application to a role that just closed does not leave a CV
    sitting in the resume prefix with no row pointing at it. The copy is the last thing
    that can fail on the happy path, and if the transaction rolls back after it, the
    orphan is a file in a private prefix that nothing references — recoverable, and the
    honest direction to fail in.
    """
    locked = (
        JobPosting.objects.select_for_update()
        .filter(pk=job.pk)
        .first()
    )
    if locked is None or not locked.is_accepting:
        raise ApplicationRefused(
            "This role is no longer accepting applications.", status=409
        )
    location = resolve_location(locked, location_id)

    resume_key, size, content_type = resume_storage.finalize(incoming_key, resume_filename)

    email = (email or "").strip().lower()
    existing = (
        JobApplication.objects.select_for_update()
        .filter(job=locked, email=email, status=APPLICATION_NEW)
        .first()
    )

    fields = {
        "job_title": locked.title,
        "location": location,
        "location_label": location.label if location else "",
        "full_name": full_name,
        "phone": phone,
        "cover_letter": cover_letter,
        "resume_key": resume_key,
        "resume_original_name": resume_filename[:255],
        "resume_size": size,
        "resume_content_type": content_type,
    }

    if existing is not None:
        old_key = existing.resume_key
        for name, value in fields.items():
            setattr(existing, name, value)
        existing.submission_count += 1
        existing.save()
        # After the row points at the NEW file, never before: a failure here must not
        # leave an application referencing a CV that has been deleted.
        if old_key and old_key != resume_key:
            resume_storage.delete_quietly(old_key)
        return existing

    try:
        # Savepoint, because the partial unique index can still refuse this: two submits
        # in the same second both find no existing row. `AdminAuditMixin` is not in play
        # on the public surface, but DRF's ATOMIC_REQUESTS-style wrapping is — an
        # IntegrityError left uncaught poisons the transaction and every later query,
        # including the one that renders the response. Same reasoning as
        # `apps.stores.admin_views.StoreLocationAdminViewSet.create`.
        with transaction.atomic():
            return JobApplication.objects.create(
                job=locked,
                email=email,
                is_resubmission=JobApplication.objects.filter(job=locked, email=email).exists(),
                **fields,
            )
    except IntegrityError:
        # Somebody else won the race with an identical submission. Their row is the one
        # that exists; ours would be a duplicate. Returning theirs makes the endpoint
        # idempotent and keeps the response indistinguishable from a first application —
        # which is the whole point (see the module docstring).
        winner = JobApplication.objects.filter(
            job=locked, email=email, status=APPLICATION_NEW
        ).first()
        if winner is None:
            raise
        resume_storage.delete_quietly(resume_key)
        return winner


def mark_reviewed(application: JobApplication, user) -> None:
    """Stamp who last moved this application and when.

    Only on a STATUS change, not on a note edit: "reviewed by" answers "who decided",
    and a typo fix in the notes is not a decision.
    """
    application.reviewed_by = user if getattr(user, "is_authenticated", False) else None
    application.reviewed_at = timezone.now()
