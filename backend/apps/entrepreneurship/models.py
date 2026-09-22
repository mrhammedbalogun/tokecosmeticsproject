"""The Student Entrepreneurship Program: who has asked to join it, and whether it is open.

── WHAT THE PROGRAMME ACTUALLY IS, BECAUSE IT DECIDES THE SHAPE OF THIS FILE ───

A student is approved, given Toke Cosmetics stock **for free and up front**, sells it,
and pays the company back out of what they take. That is *consignment on trust*, and it
is why this table collects a phone number the WordPress form never asked for: the shop
is about to hand physical goods to somebody it has met once, through a web form.

It is ALSO why this file stops where it does. Everything after "approved" — what stock
went out, what is owed, what has been repaid — is a LEDGER, and a ledger is not a status
on an application row. Modelling it here would produce a `status` field that quietly
means "we are owed ₦40,000", with no amount, no currency and no history beside it. If
that half is ever built it belongs in its own app next to `apps.orders`, and this row
keeps doing the one job it is good at: recording who asked, and what we decided.

── WHY THIS IS NOT A ROW IN `apps.careers` ────────────────────────────────────

The shapes rhyme — a public form, a stranger's details, a staff decision — and that is
the whole trap. A job application is a person asking to be paid by us; this is a person
asking to be TRUSTED WITH STOCK. They have different scopes, different reviewers,
different retention, and a `careers.applications.manage` holder screening candidates has
no business reading either. Two tables, two scopes; the code they genuinely share (the
recipient actions) is shared as `apps.notifications.recipient_admin`, which is the level
the duplication actually lives at.

── NO CONTENT MODEL ───────────────────────────────────────────────────────────

The page's copy, its FAQs and its steps are a bespoke code route under
`storefront/src/app/(static-shop)/entrepreneurial-program/`, following the ruling already
recorded in `storefront/src/lib/site-pages.ts`: the More-menu pages get layouts that
sanitised HTML in `cms.Page.body` cannot express. So there is nothing here for a
`entrepreneurship.manage` content scope to manage, and none exists. `ProgramSettings`
below is the ONE thing on that page which must change without a deploy.
"""

from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel

STATUS_NEW = "new"
STATUS_IN_REVIEW = "in_review"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_WITHDRAWN = "withdrawn"

# CharField-with-choices rather than a lookup table, matching `careers.JobApplication`
# and `stores.STORE_TYPE_CHOICES`: the LABELS are what the admin badge renders, so the
# display text cannot drift from the stored value.
#
# FIVE STATES, AND DELIBERATELY NOT SIX. An earlier draft had `onboarded` between
# `approved` and the end — see the module docstring for why it was cut. "Approved" is a
# DECISION, which this table is the record of; "has their stock / owes us ₦40,000" is a
# BALANCE, which it is not. A status that silently means the second is a debt recorded in
# a field with no amount on it.
APPLICATION_STATUS_CHOICES = [
    (STATUS_NEW, "New"),
    (STATUS_IN_REVIEW, "In review"),
    (STATUS_APPROVED, "Approved"),
    (STATUS_REJECTED, "Not proceeding"),
    # The student pulled out, or stopped answering, AFTER we had moved on them. Distinct
    # from "Not proceeding", which is our decision — and the difference is the one a
    # reviewer wants six months later when the same person applies again.
    (STATUS_WITHDRAWN, "Withdrew"),
]


class ProgramApplication(TimeStampedModel):
    """One student asking to join. Personal data, behind its own scope, reads audited.

    ── THE DE-DUPLICATION RULE, AND WHY IT IS SCOPED TO `new` ──────────────────

    Copied deliberately from `careers.JobApplication`, including the reason: the public
    endpoint NEVER answers "you have already applied", because that sentence proves to
    whoever typed an address that its owner is looking for money. `PasswordResetView`
    already refuses that trade on this codebase, and a student's family or current
    employer is exactly who would care.

    So the endpoint always answers the same way, and the de-duplication happens on our
    side:

    * a submission while the row is still `new` OVERWRITES it — which is also how a
      student fixes the course they typed wrong, without emailing anybody;
    * a submission after staff have moved the status makes a SECOND row flagged
      `is_resubmission`, so nobody who merely knows an address can erase a decision in
      progress, and the reviewer sees both.

    THE UNIQUE INDEX IS ON EMAIL ALONE, with no second axis, and that is the difference
    from careers — where it is `(job, email)` because one person may legitimately want
    two different jobs at once. There is only one programme, so two live applications
    from one address is always the same person submitting twice. Re-applying in a LATER
    academic year still works: by then the earlier row has been decided, the partial
    index no longer covers it, and the new submission is a fresh row that carries the
    history beside it.
    """

    # PROTECT, like every other place-FK in this codebase: deleting a market must not
    # silently take the students who applied from it.
    country = models.ForeignKey(
        "core.Country", on_delete=models.PROTECT, related_name="program_applications"
    )

    full_name = models.CharField(max_length=120)
    # Lowercased in `save()`. Without that, `Ada@x.com` and `ada@x.com` are two rows, the
    # partial unique index below cannot see the collision, and one person appears twice
    # under two spellings of one address.
    email = models.EmailField(max_length=254)
    # Strict E.164, judged by `apps.core.phones` — the same rule as every other stored
    # number in the platform, so the admin can render a `tel:`/WhatsApp link that dials.
    #
    # NOT ON THE OLD WORDPRESS FORM, and the single most defensible addition to it: this
    # programme hands over stock, and "we cannot reach them" is the failure that costs
    # real money rather than a reply.
    phone = models.CharField(max_length=20)

    institution = models.CharField(max_length=160)
    # FREE TEXT, not choices. "300 Level" is Nigerian, "Year 2" is British, "Sophomore"
    # is American, and the programme takes all four markets — a choices field would have
    # to enumerate every system or refuse a real student, and refusing a real student on
    # a marketing funnel is the expensive error. The storefront offers a `<datalist>` of
    # the common Nigerian answers, which is a suggestion rather than a gate.
    academic_level = models.CharField(max_length=60)
    course_of_study = models.CharField(max_length=120)

    # Optional, and the one field a reviewer will actually weigh: this is a selling
    # programme, and where somebody already has an audience is the closest thing to
    # evidence a form can carry. Stored as typed — a handle, a URL, or "@" and a name.
    social_handle = models.CharField(max_length=120, blank=True)
    # PLAIN TEXT, never HTML. Typed into a <textarea> by an anonymous member of the
    # public; there is no editor to produce markup and therefore no reason to accept any.
    # The admin renders it with `white-space: pre-wrap`.
    motivation = models.TextField(blank=True)

    status = models.CharField(
        max_length=16, choices=APPLICATION_STATUS_CHOICES, default=STATUS_NEW
    )
    staff_notes = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="reviewed_program_applications",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    # How many times this row has been submitted. 2+ means the student replaced their own
    # application, which is worth seeing on the row: it separates "fixed a typo once"
    # from "keeps resending the same thing".
    submission_count = models.PositiveIntegerField(default=1)
    # True when this row exists BECAUSE an earlier application from the same address was
    # already decided. Surfaced in the admin so the reviewer knows to look for the
    # sibling rather than wondering why somebody appears twice.
    is_resubmission = models.BooleanField(default=False)

    class Meta:
        verbose_name = "programme application"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["status"], name="progapp_status_idx"),
            models.Index(fields=["email"], name="progapp_email_idx"),
            models.Index(fields=["-created_at"], name="progapp_created_idx"),
        ]
        constraints = [
            # ONE UNDECIDED APPLICATION PER ADDRESS.
            #
            # Scoped to `status='new'` on purpose: the overwrite path in
            # `services.record_application` reuses that row, and this index is what turns
            # the two-submits-in-one-second race into an IntegrityError to catch rather
            # than a duplicate to discover later. Once staff have moved the status the
            # row is the record of a decision, the index stops applying, and a new row is
            # allowed — which is how somebody re-applies a year later.
            models.UniqueConstraint(
                fields=["email"],
                condition=models.Q(status=STATUS_NEW),
                name="progapp_unique_new_per_email",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.full_name} — {self.institution}"

    def save(self, *args, **kwargs):
        self.email = (self.email or "").strip().lower()
        return super().save(*args, **kwargs)


class ProgramSettings(TimeStampedModel):
    """Whether the programme is taking applications. A singleton, row id 1.

    ── WHY A TABLE AND NOT A DEPLOY ───────────────────────────────────────────

    Intakes fill up. Without this, "stop taking applications" is a code change, a CI run
    and a Vercel build — so in practice it does not happen, and the form keeps collecting
    students nobody can take for as long as it takes somebody to feel guilty enough to
    ask a developer. One boolean removes that.

    It is deliberately TWO FIELDS and not a content model. The page's copy is a code
    route (see the module docstring); the only thing that must move at short notice is
    whether the form is there, and what it says in its place.

    ── THE SINGLETON PATTERN ──────────────────────────────────────────────────

    `load()` rather than `get_or_create` at every call site, and `pk` forced to 1 on
    save, so a second row cannot be created by a shell, a fixture or a racing request.
    The same shape `apps.checkout`'s tax settings use, and for the same reason: a
    settings table with two rows has an answer that depends on ordering.
    """

    is_open = models.BooleanField(
        default=True,
        help_text="Uncheck to stop accepting applications. The page stays up.",
    )
    # Shown in the form's place when `is_open` is off. Plain text, deliberately: it is
    # rendered to the public and there is no editor behind it.
    closed_message = models.CharField(
        max_length=300,
        blank=True,
        help_text="What to tell visitors while applications are closed.",
    )

    class Meta:
        verbose_name = "programme settings"
        verbose_name_plural = "programme settings"

    def __str__(self) -> str:
        return "Open to applications" if self.is_open else "Applications closed"

    def save(self, *args, **kwargs):
        self.pk = 1
        return super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "ProgramSettings":
        """The one row, created on first read.

        Never raises: a fresh database, a test, and a restored backup all answer the same
        way, and the default is OPEN — the state the programme is in for all but a few
        weeks of its life.
        """
        row, _ = cls.objects.get_or_create(pk=1)
        return row

    @property
    def public_closed_message(self) -> str:
        """What the storefront shows when the form is away.

        A default lives HERE rather than in the page, so an operator who switches the
        intake off without typing anything still gets a sentence that reads as a decision
        instead of a blank space where a form used to be.
        """
        return (self.closed_message or "").strip() or (
            "We have closed applications for this intake while we work through the "
            "ones we have. Check back soon — the next intake opens here first."
        )
