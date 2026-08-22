"""The store locator (Plan-42): every shop a customer can walk into and buy Toke
Cosmetics from — our own counters and the distributors who stock us.

── WHY THIS IS NOT `delivery.SenderLocation` ────────────────────────────────────

`SenderLocation` looks like the same table and is not. Every ACTIVE row of it is a
candidate GIG shipping origin — `delivery/gig/origins.select_origin()` picks the
nearest active one by haversine — so filing a distributor in Kano there would
silently start routing real parcels through a shop that has never packed one. The
two tables answer different questions: SenderLocation answers "where do we ship
FROM", this one answers "where can I buy this today".

They do overlap in the real world: an Ogudu counter is both. That overlap is
handled by a WARNING at create time (`services.possible_duplicates` looks at
SenderLocation rows too) rather than by a foreign key, deliberately. A nullable FK
that nothing enforces and nothing syncs is documentation stored in a schema — it
rots the first time a shop moves and one of the two rows is edited, and then it
actively misleads. The warning is behaviour; it fires at the moment somebody would
otherwise create the divergence.

── THE THREE VISIBILITY STATES, AND WHY THERE ARE THREE ─────────────────────────

`is_active` and `archived_at` are not two spellings of one idea:

* **active** (`is_active=True`, `archived_at=None`) — listed on /find-stores.
* **inactive** (`is_active=False`, `archived_at=None`) — temporarily not listed:
  refurbishing, stock gone, phone number unverified. Still fully editable in the
  admin, still in every filter, and one click from being live again. This is the
  state the brief asks for by name.
* **archived** (`archived_at` set) — removed from the directory. What `DELETE`
  does. Hidden from the admin list unless asked for, restorable, never purged.

There is no hard delete. Nothing in the system references a store row, so a purge
would be *safe*, but the rows are hand-typed field intelligence — a distributor's
address and phone somebody collected once — and "safe to delete" is not "worth
deleting". The cost is that archived rows keep a third party's contact details
indefinitely; that is a conscious choice, recorded here rather than discovered.

── WHAT IS FREE TEXT AND WHAT IS AN FK ──────────────────────────────────────────

Country/state/area are FKs (`core.Country`, `core.Region`) so a store cannot claim
Nigeria → Lagos → an LGA of Kano's; the serializer proves the chain and the public
filter walks the same FKs the address matcher does. `city_text` is free text on
purpose and mirrors `core/address_rules.py`: GB/US/CA have level-1 regions only
(England, California, Ontario — no children were ever seeded), so outside Nigeria
the finest structured place is a whole country-sized state and the city has to be
typed. Requiring an LGA everywhere would have made this feature NG-only.
"""

from django.db import models

from apps.core.models import TimeStampedModel
from apps.stores.normalize import address_key, name_key

# `store_type` is a CharField with choices rather than an FK to a lookup table:
# adding "Salon Partner" tomorrow is one line here plus a choices-only migration,
# and a table with three rows nobody edits is a join on every query for nothing.
# The LABELS are served to the storefront (`store_type_label`) so the badge text
# lives here too and cannot drift from the value.
STORE_TYPE_TOKE = "toke_store"
STORE_TYPE_DISTRIBUTOR = "distributor"
STORE_TYPE_CHOICES = [
    (STORE_TYPE_TOKE, "Toke Store"),
    (STORE_TYPE_DISTRIBUTOR, "Authorized Distributor"),
]


class StoreLocation(TimeStampedModel):
    name = models.CharField(max_length=120)
    store_type = models.CharField(
        max_length=32, choices=STORE_TYPE_CHOICES, default=STORE_TYPE_DISTRIBUTOR
    )

    # --- where it is -------------------------------------------------------
    # PROTECT, not CASCADE: deleting a market or a region must not silently take
    # the directory of shops in it with it.
    country = models.ForeignKey(
        "core.Country", on_delete=models.PROTECT, related_name="store_locations"
    )
    state_region = models.ForeignKey(
        "core.Region", on_delete=models.PROTECT, related_name="stores_as_state",
        limit_choices_to={"level": "state"},
    )
    # Required when the chosen state HAS areas (Nigeria), impossible when it does
    # not (GB/US/CA). Enforced by the serializer, which can see the state; a
    # database-level rule would have to re-derive "does this state have children"
    # in a constraint expression, and would refuse the seed data the day an area
    # is added to a state that already has storeless-state rows.
    area_region = models.ForeignKey(
        "core.Region", on_delete=models.PROTECT, related_name="stores_as_area",
        null=True, blank=True, limit_choices_to={"level": "area"},
    )
    # Free text, and the finest place a non-NG store has. Blank for NG, where the
    # LGA dropdown plays this role — same split as `core/address_rules.py`.
    city_text = models.CharField(max_length=100, blank=True)
    address = models.CharField(max_length=300)
    # Optional pin. When present the "Get directions" link points at the
    # COORDINATES rather than at the address text, because a free-text Nigerian
    # address geocodes badly and a maps link to the wrong street is worse than no
    # link at all. Nothing routes on these — they are not GIG origins.
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    # --- how to reach it ---------------------------------------------------
    # Strict E.164, judged by `core.phones` — the same rule as every other stored
    # number in the platform, so the card can render a `tel:` link that dials.
    phone = models.CharField(max_length=20)
    phone_alt = models.CharField(max_length=20, blank=True)
    # A SEPARATE field rather than a "phone is on WhatsApp" flag: for this customer
    # base WhatsApp is the primary channel, and the shop's WhatsApp number is very
    # often not the landline printed on the door.
    whatsapp_phone = models.CharField(max_length=20, blank=True)
    # Deliberately one free-text line ("Mon–Sat, 9am – 7pm · Closed Sundays") and
    # not a structured opening-hours table. Structured hours mean public holidays,
    # split shifts, timezones and an "open now" badge that is wrong on Boxing Day.
    # The second question a store finder gets asked deserves an answer; it does not
    # yet deserve a schema.
    opening_hours = models.CharField(max_length=160, blank=True)
    notes = models.CharField(max_length=300, blank=True)  # staff-only, never public

    # --- visibility (see the module docstring) -----------------------------
    is_active = models.BooleanField(default=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    # --- derived, for duplicate detection ----------------------------------
    # Written by `save()` below. Stored rather than computed per query because both
    # the unique index and the "is this a duplicate?" lookup are SQL, and neither
    # can call Python. `editable=False` keeps them out of every ModelForm and out
    # of DRF's automatic field discovery.
    name_key = models.CharField(max_length=120, editable=False, db_index=True, default="")
    address_key = models.CharField(max_length=300, editable=False, db_index=True, default="")

    class Meta:
        verbose_name = "store location"
        ordering = ["name"]
        indexes = [
            # The public query: active, unarchived, in one LGA (or one state, for
            # the countries with no LGAs).
            models.Index(fields=["area_region", "is_active"], name="store_area_active_idx"),
            models.Index(fields=["state_region", "is_active"], name="store_state_active_idx"),
            models.Index(fields=["country", "is_active"], name="store_country_active_idx"),
            # The admin list's default ordering within a filter.
            models.Index(fields=["archived_at"], name="store_archived_idx"),
        ]
        constraints = [
            # SAME NAME **AND** SAME ADDRESS IN THE SAME PLACE IS THE SAME SHOP.
            #
            # Name alone would be too tight: two branches of "Beauty Hub" in
            # Alimosho is an ordinary thing for a distributor network, and refusing
            # the second one teaches the operator to invent fake names. Address
            # alone would be too tight too — a mall has many counters at one
            # address. Together they are the definition of an accidental re-entry,
            # which is what this constraint is for; everything fuzzier is the SOFT
            # warning in `services.possible_duplicates`, which a human overrides.
            #
            # TWO constraints rather than one, because `area_region` is NULL for
            # every GB/US/CA row and SQL unique indexes treat NULLs as distinct —
            # a single constraint naming `area_region` would therefore enforce
            # nothing at all outside Nigeria. Splitting on the null-ness is the
            # portable spelling (`nulls_distinct=False` is PostgreSQL 15+ only,
            # and the test suite must keep running on SQLite).
            models.UniqueConstraint(
                fields=["country", "state_region", "area_region", "name_key", "address_key"],
                condition=models.Q(archived_at__isnull=True, area_region__isnull=False),
                name="store_unique_name_address_in_area",
            ),
            models.UniqueConstraint(
                fields=["country", "state_region", "name_key", "address_key"],
                condition=models.Q(archived_at__isnull=True, area_region__isnull=True),
                name="store_unique_name_address_in_state",
            ),
        ]

    def __str__(self) -> str:
        if self.archived_at:
            state = "archived"
        else:
            state = "active" if self.is_active else "hidden"
        return f"{self.name} ({state})"

    def save(self, *args, **kwargs):
        """Keep the derived keys in step with the fields they are derived from.

        Here rather than in the serializer so that the shell, a data migration and
        the Django admin all produce rows the unique index can judge. `bulk_create`
        still bypasses it — Django's does not call `save()` — so a future bulk
        import must set both keys itself.
        """
        self.name_key = name_key(self.name)
        self.address_key = address_key(self.address)
        return super().save(*args, **kwargs)

    # -- convenience used by the serializers --------------------------------

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None

    @property
    def status(self) -> str:
        """The single word the admin list renders. One property so the list, the
        filter and the row badge can never disagree about what a row's state is."""
        if self.archived_at is not None:
            return "archived"
        return "active" if self.is_active else "inactive"
