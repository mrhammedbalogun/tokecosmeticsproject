"""Seed the roles the old WordPress careers page advertised.

SOURCE OF TRUTH: `tokecosm_wp481.wp_posts` row 4322 on the VPS — the live content of
https://old.tokecosmetics.com/careers/ as at 2026-09-21. It listed FIFTEEN entries, of
which eleven were "Sales Representative" repeated once per city. Those eleven are one
posting here with eleven locations; see `apps/careers/models.py` for why.

The old page carried NO descriptions at all — every entry was a title over
"Full-Time / Lagos / Good Pay". The copy below is therefore written, not migrated, and is
meant to be edited in the admin. It is seeded anyway because an open role whose page says
nothing is worse than no page: a candidate who cannot tell what the job involves either
does not apply or applies for something else.

IDEMPOTENT, by slug. Re-running it adds what is missing and leaves everything else alone,
INCLUDING any edit made in the admin — this command must never be the thing that
overwrites the description somebody rewrote. `--reset` is the explicit opt-out for that,
and it says so at the prompt.
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.careers.models import JobLocation, JobPosting
from apps.core.models import Country

SALES_LOCATIONS = [
    # In the order the old page listed them.
    "Alimosho, Lagos",
    "Iba LG, Lagos",
    "Agbara LG, Lagos",
    "Lagos Island, Lagos",
    "Delta State",
    "Abuja",
    "Port Harcourt",
    "Onitsha",
    "Bayelsa",
    "Benin",
    "Enugu",
]

POSITIONS = [
    {
        "slug": "operations-manager",
        "title": "Operations Manager",
        "department": "Operations",
        "summary": "Run the day to day — production, stock, fulfilment and the people who move it.",
        "locations": ["Lagos"],
        "description": """
<p>You own how Toke Cosmetics runs from the moment a batch is made to the moment a
customer opens the box. That means production schedules, stock levels, the packing
bench, our delivery partners, and the small daily decisions that decide whether an
order arrives on time.</p>
<h3>What you will be doing</h3>
<ul>
<li>Plan production and keep stock at the levels the sales pace actually needs.</li>
<li>Own fulfilment end to end: picking, packing, dispatch and delivery partners.</li>
<li>Keep our inventory records honest, and act on what they show.</li>
<li>Lead and schedule the operations and warehouse team.</li>
<li>Find the bottlenecks, fix them, and tell us what they cost.</li>
</ul>
""",
        "requirements": """
<ul>
<li>Three or more years running operations, production or fulfilment — beauty, FMCG or
retail preferred.</li>
<li>Comfortable with numbers: you can read a stock report and say what it means.</li>
<li>Experience managing a team, including hiring and rostering.</li>
<li>Organised under pressure, and calm when a delivery partner lets us down.</li>
<li>Based in Lagos, or ready to relocate.</li>
</ul>
""",
    },
    {
        "slug": "sales-representative",
        "title": "Sales Representative",
        "department": "Sales",
        "summary": "Grow Toke Cosmetics in your city — stockists, salons, retail counters and repeat customers.",
        "locations": SALES_LOCATIONS,
        "description": """
<p>You are Toke Cosmetics where you live. You open new stockists, look after the ones we
already have, and make sure the shelves that carry us are never empty. This is a role for
somebody who likes being out among customers rather than behind a desk.</p>
<h3>What you will be doing</h3>
<ul>
<li>Find and open new retail stockists, salons and distributors in your area.</li>
<li>Visit existing accounts, take reorders and keep our display looking right.</li>
<li>Hit an agreed monthly sales target, and report honestly against it.</li>
<li>Tell us what customers in your area are actually asking for.</li>
<li>Collect payments and keep your account records clean.</li>
</ul>
<p>Applications are open in several locations — choose the one nearest you when you
apply.</p>
""",
        "requirements": """
<ul>
<li>One or more years in field sales, retail or distribution. We will train the right
person with less.</li>
<li>You know your area and the people who trade in it.</li>
<li>Confident talking to shop owners, and comfortable hearing no.</li>
<li>Able to keep simple records and report on time.</li>
<li>Living in, or able to work daily in, the location you apply for.</li>
</ul>
""",
    },
    {
        "slug": "human-resources-and-strategy-manager",
        "title": "Human Resources & Strategy Manager",
        "department": "People",
        "summary": "Build the team, and the plan the team is working to.",
        "locations": ["Lagos"],
        "description": """
<p>Two halves of one job. You look after the people — hiring, onboarding, records,
payroll input, the culture — and you help decide where the business is going, then turn
that into something the team can actually work to.</p>
<h3>What you will be doing</h3>
<ul>
<li>Run recruitment end to end, including the applications that come through this page.</li>
<li>Own onboarding, employee records, leave and performance reviews.</li>
<li>Keep us on the right side of Nigerian employment requirements.</li>
<li>Work with the founder on planning, targets and how we measure them.</li>
<li>Turn plans into quarterly objectives the team understands.</li>
</ul>
""",
        "requirements": """
<ul>
<li>Three or more years in HR, with real exposure to business planning.</li>
<li>You have hired people, not only processed the paperwork for it.</li>
<li>Working knowledge of Nigerian labour practice.</li>
<li>Discreet. This role sees everything.</li>
<li>Based in Lagos.</li>
</ul>
""",
    },
    {
        "slug": "customer-service-representative",
        "title": "Customer Service Rep (Portfolio Manager)",
        "department": "Customer Care",
        "summary": "Look after a portfolio of customers — answer well, follow through, keep them coming back.",
        "locations": ["Lagos"],
        "description": """
<p>Most of our customers meet us through a WhatsApp message or an order enquiry, and you
are that meeting. You look after a portfolio of them: answering questions about skin
concerns and products, tracking orders, sorting out what went wrong, and following up so
a first order becomes a second.</p>
<h3>What you will be doing</h3>
<ul>
<li>Answer customers on WhatsApp, email, phone and social, quickly and in our voice.</li>
<li>Know the range well enough to recommend honestly, including saying "not that one".</li>
<li>Track orders and chase deliveries on the customer's behalf.</li>
<li>Own complaints through to a resolution the customer accepts.</li>
<li>Follow up your portfolio, and keep notes worth reading.</li>
</ul>
""",
        "requirements": """
<ul>
<li>One or more years in customer service, ideally beauty or retail.</li>
<li>Clear written English, and a warm phone manner.</li>
<li>Genuinely interested in skincare — you will be asked real questions.</li>
<li>Patient with people who are upset, and organised enough to follow through.</li>
<li>Based in Lagos.</li>
</ul>
""",
    },
    {
        "slug": "digital-marketing-officer",
        "title": "Digital Marketing Officer",
        "department": "Marketing",
        "summary": "Run the channels that bring customers in, and prove which ones worked.",
        "locations": ["Lagos"],
        "description": """
<p>You run what customers see of us online: Instagram, TikTok, the emails we send, the
ads we pay for and the content that carries them. And you are the person who can say
which of those actually sold anything.</p>
<h3>What you will be doing</h3>
<ul>
<li>Plan and publish across Instagram, TikTok and Facebook, consistently.</li>
<li>Brief and direct content — photos, short video, before-and-afters.</li>
<li>Run paid campaigns to a budget, and report on what they returned.</li>
<li>Write and send our customer emails.</li>
<li>Work with creators and affiliates on the referral programme.</li>
</ul>
""",
        "requirements": """
<ul>
<li>Two or more years running social and paid channels for a real brand.</li>
<li>You can show work you made, not only work you scheduled.</li>
<li>Comfortable with Meta and TikTok ads managers, and with reading the numbers.</li>
<li>An eye for beauty content — ours is a visual category.</li>
<li>Based in Lagos.</li>
</ul>
""",
    },
]


class Command(BaseCommand):
    help = "Create the job postings the old WordPress careers page advertised."

    def add_arguments(self, parser):
        parser.add_argument(
            "--country", default="NG",
            help="ISO code of the market these roles are in (default: NG).",
        )
        parser.add_argument(
            "--draft", action="store_true",
            help="Create them as drafts instead of open. Default is OPEN — a seeded "
                 "board that nobody remembers to publish is how the CMS pages ended up "
                 "with 47 drafts and seven 404s in the footer.",
        )
        parser.add_argument(
            "--reset", action="store_true",
            help="OVERWRITE the description, requirements and locations of postings that "
                 "already exist. Destroys admin edits; off by default for that reason.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            country = Country.objects.get(code=options["country"].upper())
        except Country.DoesNotExist:
            self.stderr.write(
                self.style.ERROR(f"No country {options['country']!r}. Run migrations first.")
            )
            return

        status = "draft" if options["draft"] else "open"
        created_count = updated_count = skipped_count = 0

        for order, spec in enumerate(POSITIONS):
            posting, created = JobPosting.objects.get_or_create(
                slug=spec["slug"],
                defaults={
                    "title": spec["title"],
                    "department": spec["department"],
                    "summary": spec["summary"],
                    "description": spec["description"].strip(),
                    "requirements": spec["requirements"].strip(),
                    "country": country,
                    # Every entry on the old page said Full-Time and Good Pay.
                    "employment_type": "full_time",
                    "workplace_type": "on_site",
                    "compensation_text": "Good Pay",
                    "status": status,
                    "sort_order": order,
                    "published_at": timezone.now() if status == "open" else None,
                },
            )
            if created:
                created_count += 1
            elif options["reset"]:
                posting.title = spec["title"]
                posting.department = spec["department"]
                posting.summary = spec["summary"]
                posting.description = spec["description"].strip()
                posting.requirements = spec["requirements"].strip()
                posting.compensation_text = "Good Pay"
                posting.sort_order = order
                posting.save()
                updated_count += 1
            else:
                skipped_count += 1
                self.stdout.write(f"  = {spec['title']} (exists, left alone)")
                continue

            # Locations are ADDED, never removed, even on --reset: a city taken off the
            # list is a hiring decision somebody made, and re-adding it because a seed
            # script ran would put a filled job back on the careers page.
            for position, label in enumerate(spec["locations"]):
                JobLocation.objects.get_or_create(
                    job=posting, label=label, defaults={"sort_order": position}
                )
            verb = "created" if created else "updated"
            self.stdout.write(
                f"  + {spec['title']} ({verb}, {len(spec['locations'])} location"
                f"{'s' if len(spec['locations']) != 1 else ''})"
            )

        self.stdout.write(self.style.SUCCESS(
            f"Careers seed done: {created_count} created, {updated_count} updated, "
            f"{skipped_count} left alone. "
            f"{'They are DRAFTS.' if status == 'draft' else 'They are OPEN and live.'}"
        ))
