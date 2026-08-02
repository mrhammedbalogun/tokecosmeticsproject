# Plan-18b — the staff customer list and detail

Deferred from Plan-18a ("18b and 18c are deferred — their backends do not exist"), then
scheduled by Plan-20's design note. Built 2026-08-02, between Plan-23 and Plan-25.

## Why it went here in the queue

Plan-20 settled the ordering and gave two reasons, both of which held up:

- **Not before Plan-22/23.** Built between the customer and order migrations it would show
  every migrated customer with zero orders, so its "orders count / lifetime value" columns
  would have validated nothing.
- **Not after Plan-25.** *"18b is the densest PII surface in the system and its detail page
  is the most IDOR-shaped thing not yet built; shipping it after the Plan-25 IDOR/PII pass
  and Plan-26 UAT would put it into production untested against the class of bug those
  stages exist to catch."*

So Plan-25 was asked for and this was built first, because otherwise Plan-25's hardening
pass would have had nothing to test on the surface that most needs it.

## What was built

`customers.view` had existed since Plan-16 with exactly one endpoint using it — global
search. This is the list and detail the scope was granted for.

- `CustomerAdminViewSet` — read-only, `customers.view`, **read-audited**, keyed on
  `toke_id`.
- `analytics.queries.customer_totals` / `unclaimed_guest_orders` — the other half of the
  shared aggregate layer 20a opened.
- `admin/` — `/customers` list and `/customers/[tokeId]` detail. The nav entry already
  existed and had pointed at nothing since Plan-16.

## Design rulings

### 1. Read-only, as a decision and not as an unfinished stage

Nothing a staff member needs to *change* about a customer belongs here. Editing an email
silently re-points order history and password resets; deactivating an account is what the
deletion flow owns, on a 30-day timer with an anonymisation sweep behind it. A write
surface here would be a second way to do both without either's rules. Support answers
questions from this page; the customer changes their own details.

### 2. Lifetime value is per currency, and comes from the shared layer

`customer_totals` sits on the same `REVENUE_STATUSES` as the dashboard and the
top-customers report. A customer whose lifetime value disagreed with the report would make
both numbers untrustworthy without either being obviously wrong. Per currency from day one
because Plan-23 imports four currencies of history and this project bans FX mixing.

It is **not on the list page**: a per-row aggregate would fire one query per row, and "who
spends most" is already answered by a report in one grouped query.

### 3. Guest orders are shown, and deliberately not summed

Orders carrying the customer's email but owned by nobody appear as a **count with an
explanation**, never inside lifetime value. Summing them would attribute money to somebody
who has not proved the address is theirs — the exact claim `apps/accounts/claims.py`
refuses to make. Showing them answers support's most common question about a migrated
customer: *"why can't they see their old orders?"*

### 4. Fields are listed, never excluded

`fields = "__all__"` minus a deny-list is one forgotten field away from publishing a
credential, and the forgotten field is always the one added later. Tests assert the
outcome — no key matching `password`, `totp`, `secret`, `recovery`, `session` or `token`
in either payload — rather than the technique.

## What the guards caught, and what they were right about

**The customers tripwire fired, and it named its own fix.** `admin_search.py` had one
section — customers — declaring its scope and queryset by hand, because no list endpoint
existed; the guard test said that exception should die the day one was routed. It did.
`SEARCH_SOURCES` now points at `CustomerAdminViewSet` and derives both, so the search and
the list cannot drift; the exception test was replaced by the mutation-style parity test
the tripwire asked for.

That derivation also moved the staff exclusion. It had been on the viewset, which would
have left global search as the way around it — a support agent typing a colleague's name
and getting their contact details from a section scoped for customers.

**The OpenAPI schema test caught a bug 24 passing tests missed.** `CustomerAddressSerializer`
named a column `Address` does not have (`city`; the model stores `city_text`). DRF builds
ModelSerializer fields lazily, so it sat unnoticed through a green run — every address
assertion in the suite was the *empty* case. Generating a schema forces field construction,
which is what surfaced it. Fixed, and the suite now exercises a real address row plus a
direct field-construction check.

## Not done here

No customer **write** surface, by ruling 1. No order list embedded in the detail page — it
links to `/orders?search=<email>`, which is the order desk with its own filters, pagination
and audit trail rather than a second half-featured copy of it.
