"""The careers board (Plan-45): the roles we are hiring for, and who applied to them.

── WHY A POSTING CARRIES MANY LOCATIONS ────────────────────────────────────────

The WordPress page this replaces listed "Sales Representative" ELEVEN TIMES — once
for Alimosho, Iba, Agbara, Lagos Island, Delta, Abuja, Port Harcourt, Onitsha,
Bayelsa, Benin and Enugu — each with the identical "Full-Time / Good Pay" pair
beneath it. Modelled as eleven rows that is eleven copies of one job description to
keep in step, and a careers page that reads as a templated wall to anyone scanning
it. Modelled as one posting with eleven `JobLocation` children it is one description,
one edit, one card, and the applicant tells us which city they mean — which is the
fact we actually needed and the old form never captured.

`JobLocation.label` is FREE TEXT and deliberately not a `core.Region` FK. The real
data mixes levels without apology: "Alimosho, Lagos" is an LGA, "Delta State" is a
state, "Benin" and "Port Harcourt" are cities that are not regions in our tree at
all. An FK would have refused more than half the openings we were asked to publish.

── THE THREE VISIBILITY STATES ─────────────────────────────────────────────────

Same shape as `apps.stores.models.StoreLocation`, and for the same reasons:

* **draft**    — being written. Never public.
* **open**     — on the careers page, accepting applications.
* **closed**   — still on the page (with an "applications closed" badge) but the form
                 is gone. A role that vanishes the moment it is filled makes a
                 candidate who bookmarked it think the site is broken.
* archived (`archived_at` set) — what DELETE does. Off the page entirely, out of the
                 admin list unless asked for, restorable, never purged. There is no
                 hard delete of a posting: `JobApplication.job` is PROTECTed, so
                 purging one would mean purging the people who applied to it.

`closes_at` is an independent, optional deadline. A posting past it is treated as
closed by `is_accepting` without anybody clicking anything, because the failure mode
of the alternative — a stale advert collecting applications for a filled job — is
paid for by the applicant, not by us.

── WHY `resume_key` IS A CharField AND NOT A FileField ─────────────────────────

Because a FileField has `.url`, and in this project `.url` is a trap. `AWS_QUERYSTRING_AUTH
= False` (config/settings/base.py:179) is set so PRODUCT images get stable unsigned
CDN URLs; applied to a CV it renders a URL that is both broken (the CloudFront OAC
policy exposes only `catalog/*`, so it 403s) and misleading (it LOOKS like a public
link to a stranger's CV). The field is a bare key, `apps.careers.resume_storage` is
the only thing that may resolve it, and there is no attribute on this model that a
future template can accidentally render.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from apps.cms.sanitize import clean_html
from apps.core.models import TimeStampedModel

# CharField-with-choices rather than lookup tables, matching `stores.STORE_TYPE_CHOICES`:
# adding "Internship" tomorrow is one line here plus a choices-only migration, and the
# LABELS are what the storefront badge renders, so the display text cannot drift from
# the stored value.
EMPLOYMENT_FULL_TIME = "full_time"
EMPLOYMENT_TYPE_CHOICES = [
    (EMPLOYMENT_FULL_TIME, "Full-Time"),
    ("part_time", "Part-Time"),
    ("contract", "Contract"),
    ("internship", "Internship"),
    ("temporary", "Temporary"),
    ("volunteer", "Volunteer"),
]

WORKPLACE_ON_SITE = "on_site"
WORKPLACE_TYPE_CHOICES = [
    (WORKPLACE_ON_SITE, "On-site"),
    ("hybrid", "Hybrid"),
    ("remote", "Remote"),
]

STATUS_DRAFT = "draft"
STATUS_OPEN = "open"
STATUS_CLOSED = "closed"
JOB_STATUS_CHOICES = [
    (STATUS_DRAFT, "Draft"),
    (STATUS_OPEN, "Open"),
    (STATUS_CLOSED, "Closed"),
]


class JobPosting(TimeStampedModel):
    title = models.CharField(max_length=140)
    # A PUBLISHED URL (`/careers/<slug>`), not a label. Unique across archived rows too:
    # restoring an archived posting must not collide with the one somebody re-typed
    # while it was gone, and a slug that silently changes breaks every link shared to it.
    slug = models.SlugField(max_length=160, unique=True)
    # Optional, and a grouping hint only — "Sales", "Operations". Free text because a
    # five-row lookup table nobody edits is a join on every query for nothing.
    department = models.CharField(max_length=80, blank=True)
    employment_type = models.CharField(
        max_length=20, choices=EMPLOYMENT_TYPE_CHOICES, default=EMPLOYMENT_FULL_TIME
    )
    workplace_type = models.CharField(
        max_length=20, choices=WORKPLACE_TYPE_CHOICES, default=WORKPLACE_ON_SITE
    )
    # PROTECT for the same reason every other place-FK in this codebase is: deleting a
    # market must not silently take the jobs advertised in it with it.
    country = models.ForeignKey(
        "core.Country", on_delete=models.PROTECT, related_name="job_postings"
    )
    # "Good Pay" on the old page. Free text and OPTIONAL: a salary band is a commercial
    # decision per role, and an empty string renders as nothing rather than as "₦0".
    compensation_text = models.CharField(max_length=120, blank=True)
    # The one line the card shows under the title. Separate from `description` because a
    # card must not render a truncated paragraph of HTML — that is how a bold tag ends up
    # unclosed halfway down a listing.
    summary = models.CharField(max_length=300, blank=True)

    # Staff-authored rich HTML, sanitised on write (see `save`). The storefront renders
    # both through `dangerouslySetInnerHTML` under `.rich-text`, exactly like the CMS
    # pages, so they go through the same nh3 allow-list and for the same reason.
    description = models.TextField(blank=True)
    requirements = models.TextField(blank=True)

    status = models.CharField(max_length=10, choices=JOB_STATUS_CHOICES, default=STATUS_DRAFT)
    published_at = models.DateTimeField(null=True, blank=True)
    # Optional deadline. See the module docstring: an advert past its date stops taking
    # applications on its own.
    closes_at = models.DateTimeField(null=True, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "job posting"
        # Hand-ordered first, then newest.
        #
        # `nulls_last` IS LOAD-BEARING and was found by a test: a bare `-published_at`
        # sorts NULLs FIRST on PostgreSQL, and a posting only gets a `published_at` when
        # it first goes open — so every draft, and every role closed before it was ever
        # opened, floated to the top of the board above the live ones.
        #
        # `id` breaks the remaining tie because PageNumberPagination over a non-unique
        # sort key repeats and skips rows across page boundaries, which on a careers
        # board reads as "the job I saw yesterday is gone".
        ordering = [
            "sort_order",
            models.F("published_at").desc(nulls_last=True),
            "-id",
        ]
        indexes = [
            models.Index(fields=["status", "archived_at"], name="job_status_archived_idx"),
            models.Index(fields=["slug"], name="job_slug_idx"),
        ]

    def __str__(self) -> str:
        if self.archived_at:
            return f"{self.title} (archived)"
        return f"{self.title} ({self.status})"

    def save(self, *args, **kwargs):
        """Sanitise on write, and mint a slug the first time.

        SANITISE HERE rather than in the serializer so the shell, a data migration, the
        seed command and the Django admin all produce rows the storefront can render
        without re-cleaning. Same ruling as `apps.cms.models.Page`.
        """
        self.description = clean_html(self.description)
        self.requirements = clean_html(self.requirements)
        if not self.slug:
            self.slug = self._unique_slug()
        # `published_at` is stamped the first time a posting goes public and then left
        # alone: it is the `datePosted` in the JobPosting structured data, and a date that
        # jumps forward every time somebody fixes a typo tells Google the advert is newer
        # than it is.
        if self.status == STATUS_OPEN and self.published_at is None:
            self.published_at = timezone.now()
        return super().save(*args, **kwargs)

    def _unique_slug(self) -> str:
        """`slugify(title)`, with `-2`, `-3`… only if that is genuinely taken.

        Collisions are rare BY DESIGN now that one posting carries many locations — the
        eleven Sales Representative rows that would have collided eleven times are one
        row. The suffix is here for the honest case (two different "Sales Manager" roles
        a year apart), not as the normal path.
        """
        base = slugify(self.title)[:150] or "role"
        candidate = base
        n = 2
        while JobPosting.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
            suffix = f"-{n}"
            candidate = f"{base[:150 - len(suffix)]}{suffix}"
            n += 1
        return candidate

    # -- read helpers, used by the serializers and the public filter ------------

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None

    @property
    def is_expired(self) -> bool:
        return self.closes_at is not None and self.closes_at <= timezone.now()

    @property
    def is_accepting(self) -> bool:
        """THE single answer to "can somebody apply right now?".

        One property so the listing, the role page, the apply endpoint and the admin
        badge cannot disagree — a form that renders when the endpoint will refuse it is
        the worst version of this feature.
        """
        return (
            self.archived_at is None
            and self.status == STATUS_OPEN
            and not self.is_expired
        )

    @property
    def is_public(self) -> bool:
        """On the careers page at all. A CLOSED role stays listed (with its badge);
        a draft or archived one does not exist as far as the storefront is concerned."""
        return self.archived_at is None and self.status in (STATUS_OPEN, STATUS_CLOSED)


class JobLocation(TimeStampedModel):
    """One place a posting is hiring for. See the module docstring for why `label` is
    free text and not a region FK."""

    job = models.ForeignKey(JobPosting, on_delete=models.CASCADE, related_name="locations")
    label = models.CharField(max_length=120)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]
        constraints = [
            # Typing "Lagos" twice on one posting is a slip, never an intention, and the
            # resulting dropdown has two identical options a candidate must choose between.
            models.UniqueConstraint(fields=["job", "label"], name="joblocation_unique_label"),
        ]

    def __str__(self) -> str:
        return self.label


APPLICATION_NEW = "new"
APPLICATION_STATUS_CHOICES = [
    (APPLICATION_NEW, "New"),
    ("in_review", "In review"),
    ("shortlisted", "Shortlisted"),
    ("rejected", "Not proceeding"),
    ("hired", "Hired"),
]


class JobApplication(TimeStampedModel):
    """One person's application. THE MOST SENSITIVE TABLE IN THIS APP.

    Every row holds a named stranger's email, phone number, a CV that typically carries
    their home address and employment history, and often a cover letter that explains why
    they want to leave their current employer. That is why the admin endpoints over it sit
    behind their own scope, why their READS are audited
    (`apps/core/tests/test_audit_guard.py`), and why deleting one is Owner-only and takes
    the S3 object with it.

    ── SNAPSHOTS BESIDE THE FOREIGN KEYS ───────────────────────────────────────

    `job_title` and `location_label` are copies, not denormalisation for speed. A posting
    gets retitled ("Sales Representative" -> "Field Sales Executive") and a location gets
    removed when that city is filled; without the snapshot, an application six months old
    would silently re-describe itself as being for a job the candidate never applied to.
    The FKs stay for joining and filtering; the snapshots are what the screen renders.

    ── WHY THERE IS NO `(job, email)` HARD UNIQUE ──────────────────────────────

    There IS one, but only over rows still at status `new` (see `Meta.constraints`), and
    it exists to settle a race rather than to refuse a person. The public endpoint never
    answers "you have already applied": whether a named individual is job-hunting is
    exactly the kind of third-party fact `accounts.views.PasswordResetView` refuses to
    confirm, and an employer's careers form is a worse place to leak it than a login page.
    A resubmission while the row is untouched OVERWRITES it (which is also how a candidate
    fixes the CV they attached by mistake, without emailing anybody); a resubmission after
    staff have moved the status makes a second row, so nobody can destroy a review in
    progress by knowing an address.
    """

    # PROTECT: a posting is soft-archived, never hard-deleted, so in practice this never
    # fires. It is the seatbelt for a future `.delete()` written in a shell at 2am — the
    # one that would otherwise take twenty candidates with it.
    job = models.ForeignKey(JobPosting, on_delete=models.PROTECT, related_name="applications")
    job_title = models.CharField(max_length=140)
    location = models.ForeignKey(
        JobLocation, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="applications",
    )
    location_label = models.CharField(max_length=120, blank=True)

    full_name = models.CharField(max_length=120)
    # Lowercased in `save()`. Without that, `Ade@x.com` and `ade@x.com` are two rows, the
    # partial unique index below cannot see the collision, and the same person appears
    # twice in the list under two spellings of one address.
    email = models.EmailField(max_length=254)
    # Strict E.164, judged by `apps.core.phones` — the same rule as every other stored
    # number in the platform, so the admin can render a `tel:`/WhatsApp link that dials.
    phone = models.CharField(max_length=20)
    # PLAIN TEXT, never HTML. A cover letter is typed into a <textarea> by an anonymous
    # member of the public; there is no editor to produce markup and therefore no reason
    # to accept any. The admin renders it with `white-space: pre-wrap`.
    cover_letter = models.TextField(blank=True)

    # The S3 key under `recruitment/resumes/`. See the module docstring for why this is
    # not a FileField.
    resume_key = models.CharField(max_length=255)
    resume_original_name = models.CharField(max_length=255, blank=True)
    resume_size = models.PositiveIntegerField(default=0)
    resume_content_type = models.CharField(max_length=100, blank=True)

    status = models.CharField(
        max_length=16, choices=APPLICATION_STATUS_CHOICES, default=APPLICATION_NEW
    )
    staff_notes = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="reviewed_applications",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    # How many times this row has been submitted. 2+ means the candidate replaced their
    # own application, which is worth seeing on the row: it is the difference between "sent
    # us the wrong file once" and "keeps resending the same thing".
    submission_count = models.PositiveIntegerField(default=1)
    # True when this row was created BECAUSE an earlier application from the same address
    # was already under review. Surfaced in the admin so the reviewer knows to look for
    # the sibling rather than wondering why the person appears twice.
    is_resubmission = models.BooleanField(default=False)

    class Meta:
        verbose_name = "job application"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["job", "status"], name="jobapp_job_status_idx"),
            models.Index(fields=["email"], name="jobapp_email_idx"),
            models.Index(fields=["-created_at"], name="jobapp_created_idx"),
        ]
        constraints = [
            # ONE UNTOUCHED APPLICATION PER PERSON PER ROLE.
            #
            # Scoped to `status='new'` on purpose: the overwrite path in
            # `services.record_application` reuses that row, and the index is what makes
            # the two-submits-in-one-second race an IntegrityError to catch rather than a
            # duplicate to discover later. Once staff have moved the status the row is a
            # record of a review, and a second application must not be able to touch it —
            # so the index stops applying and a new row is allowed.
            models.UniqueConstraint(
                fields=["job", "email"],
                condition=models.Q(status=APPLICATION_NEW),
                name="jobapp_unique_new_per_email",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.full_name} — {self.job_title}"

    def save(self, *args, **kwargs):
        self.email = (self.email or "").strip().lower()
        return super().save(*args, **kwargs)
