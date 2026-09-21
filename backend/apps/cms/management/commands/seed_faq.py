"""Seed the FAQ with the four categories from the old WordPress help page.

    python manage.py seed_faq            # report only
    python manage.py seed_faq --apply

── WHY SOME ANSWERS SHIP AS DRAFTS ─────────────────────────────────────────────────────

Every answer here is one of two kinds.

MECHANICS — how delivery works, which payment methods exist, what the landmark field is
for, how the referral discount is calculated. These are facts about this system, they
were read out of it, and they are published.

POLICY — the return window, who pays return postage, how long a refund takes, whether
the products are tested on animals. Nothing in this codebase states any of them, so
there is nothing to read and writing one would be inventing a commitment the shop then
has to honour. Those questions are seeded with their question text and a placeholder,
`is_published=False`, for the Owner to answer on the admin screen and publish.

That is also why `PublicFaqView` hides a category with nothing published in it: the
Returns & Exchanges section is entirely policy, so it does not appear on /faq at all
until somebody answers it. A heading with nothing under it reads as a broken page.

── WHAT CAME FROM THE OLD SITE ────────────────────────────────────────────────────────

The four category names, the five Products & Fit questions, and exactly one real answer
(the skin-types one, reproduced as it was written). The old page repeated those same
five questions under all four headings and gave all twenty the same answer — the widget
was copy-pasted and never filled in — so the other three sections are new questions
written to match what customers actually ask this shop.

Idempotent: matched on (category, question), so re-running edits nothing an author has
since changed except to fill in a question that is missing.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils.text import slugify

DRAFT_PLACEHOLDER = (
    "<p><em>This answer has not been written yet. Edit it on the admin's FAQ screen "
    "and publish it when it is right.</em></p>"
)

# (category name, blurb, [(question, answer_html or None for a policy draft)])
FAQ: list[tuple[str, str, list[tuple[str, str | None]]]] = [
    (
        "Products & Fit",
        "Choosing the right product, and getting the most out of it.",
        [
            # The one real answer the old page carried, kept as it was written.
            ("Are your products suitable for all skin types?",
             "<p>Yes. Our formulas are designed to work for all skin types, including "
             "sensitive, oily, dry, and combination skin. We recommend patch-testing any "
             "new product if you have extremely sensitive skin.</p>"),
            ("How long before I see results?", None),
            ("Are your products tested on animals?", None),
            ("Can I use your products with other skincare brands?", None),
            ("How should I store my products?",
             "<p>Keep them somewhere cool and dry, out of direct sunlight, and close the "
             "lid properly after each use. Nigerian heat is hard on cosmetics &mdash; a "
             "bathroom windowsill is the worst place in most homes, and a bedroom shelf "
             "away from the window is one of the best.</p>"
             "<p>If a product changes colour, texture or smell, stop using it.</p>"),
        ],
    ),
    (
        "Orders, Shipping & Tracking",
        "Placing an order, where we deliver, and following your parcel.",
        [
            ("Do I need an account to place an order?",
             "<p>No. You can check out as a guest with just your name, email address, "
             "phone number and delivery address.</p>"
             "<p>Creating an account is worth it if you order regularly: your addresses "
             "are saved, and you can see every order you have placed in one place.</p>"),
            ("Where do you deliver?",
             "<p>Anywhere in Nigeria, and we also ship to the United Kingdom, the United "
             "States and Canada.</p>"
             "<p>Choose your country using the selector at the top of the page before you "
             "shop, so that prices and delivery options are the right ones for you.</p>"),
            ("How much is delivery, and how long does it take?",
             "<p>It depends on where your parcel is going, so the price and the expected "
             "number of days are both shown at checkout once you have entered your "
             "address &mdash; before you pay, never after.</p>"
             "<p>Lagos deliveries are usually the quickest. Deliveries to other states go "
             "through our courier's network and take longer.</p>"),
            ("Can I collect my order instead of having it delivered?",
             "<p>Yes. At checkout you can choose to collect from a GIG centre near you "
             "instead of paying for door delivery, which is normally cheaper.</p>"
             "<p>We will let you know when your parcel has arrived and is ready to "
             "collect. Bring your order number and some ID.</p>"),
            ("Why do you ask for a landmark?",
             "<p>Because it is what actually gets your parcel to you. Most Nigerian "
             "addresses have no postcode, and riders find a house by the nearest "
             "recognisable thing &mdash; a school, a filling station, a junction, a "
             "well-known shop.</p>"
             "<p>A good landmark is the single biggest thing you can do to avoid a failed "
             "delivery. &ldquo;Opposite the blue mosque, after the second speed bump&rdquo; "
             "is far more useful than a street name alone.</p>"),
            ("How do I track my order?",
             "<p>We email you at each stage &mdash; when your order is confirmed, when it "
             "has been dispatched, and when it is on its way to you.</p>"
             "<p>If you have an account, every order and its current status is in the "
             "Orders section of your account. If you checked out as a guest, use the link "
             "in your confirmation email.</p>"),
            ("Can I change or cancel my order after placing it?", None),
        ],
    ),
    (
        "Payment & Refunds",
        "How to pay, and what happens if money needs to come back.",
        [
            ("What payment methods can I use?",
             "<p>The methods available to you are shown at checkout and depend on where "
             "you are shopping from.</p>"
             "<p>In Nigeria you can pay by card. For orders from the UK and elsewhere we "
             "take payment by bank transfer, and the account details are shown to you "
             "during checkout along with what to use as your reference.</p>"),
            ("Is it safe to pay on your website?",
             "<p>Yes. Card payments are handled entirely by our payment provider on their "
             "own secure systems. <strong>Your card number never reaches Toke Cosmetics "
             "and we never store it</strong> &mdash; all we are told is whether the "
             "payment succeeded.</p>"
             "<p>The whole site runs over an encrypted connection.</p>"),
            ("Do you offer payment on delivery?",
             "<p>No. Payment is taken when you place your order, which is what lets us "
             "reserve your items and hand the parcel to the courier the same day.</p>"),
            # A question is plain text rendered by React, not HTML: an entity here would show
            # literally as "&mdash;" on the page. The answers, which ARE html, keep theirs.
            ("A friend referred me — how does the discount work?",
             "<p>If you arrive through a friend's referral link or enter their code at "
             "checkout, <strong>you get 5% off your order</strong> and your friend earns a "
             "commission on it.</p>"
             "<p>The discount is applied before you pay, so you will see it in your order "
             "summary. You can join the programme yourself from the Affiliates page.</p>"),
            ("When will I get my refund?", None),
        ],
    ),
    (
        "Returns & Exchanges",
        "Sending something back, and what to do if an order arrives wrong.",
        [
            ("Can I return a product?", None),
            ("What should I do if my order arrives damaged or incorrect?", None),
            ("How do I start a return or an exchange?", None),
        ],
    ),
]


class Command(BaseCommand):
    help = "Seed the FAQ categories and questions. Dry-run unless --apply is given."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Actually write.")

    def handle(self, *args, **options):
        from apps.cms.models import FaqCategory, FaqItem

        apply = options["apply"]
        created_cats = created_items = existing = 0

        for sort, (name, blurb, questions) in enumerate(FAQ, start=1):
            if apply:
                category, made = FaqCategory.objects.get_or_create(
                    slug=slugify(name)[:80],
                    defaults={"name": name, "blurb": blurb, "sort": sort},
                )
            else:
                category = FaqCategory.objects.filter(slug=slugify(name)[:80]).first()
                made = category is None
            created_cats += int(made)
            drafts = sum(1 for _, answer in questions if answer is None)
            self.stdout.write(
                f"\n{name}  ({len(questions)} questions, {drafts} awaiting an answer)"
                + ("  [new]" if made else "")
            )

            for index, (question, answer) in enumerate(questions, start=1):
                published = answer is not None
                if not apply:
                    self.stdout.write(
                        f"    {'publish' if published else 'DRAFT  '}  {question}")
                    continue
                _, item_made = FaqItem.objects.get_or_create(
                    category=category, question=question,
                    defaults={
                        "answer_source": answer or DRAFT_PLACEHOLDER,
                        "sort": index,
                        "is_published": published,
                    },
                )
                if item_made:
                    created_items += 1
                    self.stdout.write(
                        f"    {'published' if published else 'DRAFT    '}  {question}")
                else:
                    existing += 1

        if not apply:
            self.stdout.write(self.style.WARNING(
                "\nDRY RUN — nothing written. Re-run with --apply."))
            return
        self.stdout.write(self.style.SUCCESS(
            f"\n{created_cats} categor(ies) and {created_items} question(s) created; "
            f"{existing} already present and left alone."))
        self.stdout.write(
            "Answer the DRAFT questions on the admin's FAQ screen, then publish them. "
            "A category with nothing published in it does not appear on /faq at all.")
