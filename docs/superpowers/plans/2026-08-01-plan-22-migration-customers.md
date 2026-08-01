# Plan-22 — customer migration

Master spec: `master-tokerebuild.md` §Plan-22-migration-customers. Branch off `main`
(`4a7a369`).

> **Blocked on one decision only Hammed can make.** Revised after a Fable review that
> corrected my database topology, found a live registration flood, and verified the spec's
> hasher against server-generated hashes. What changed is recorded at the bottom.

---

## Grounding (measured on the live host 2026-08-01)

> **CORRECTED after a Fable review.** My first pass put NG-old in `tokecosm_wp788` — it
> is not a store at all. Grants drafted from that table would have targeted an empty
> database. Verified topology:

| Store | Database | Prefix | Users | Customers with ≥1 order |
|---|---|---|---|---|
| NG current | `tokecosm_wp481` | `wp_` | 4,639 | ~695 |
| NG old | `tokecosm_wp481` | **`wp8n_`** | 300 | 285 |
| Intl | `tokecosm_usawp100` | `wp8n_` | 3,269 | 13 |

**Two databases, three stores** — NG current and NG old share `tokecosm_wp481` under
different prefixes. `tokecosm_wp788` holds 15 tables and no WooCommerce. `tokecosm_usawp100`
also carries a `wpstg0_` WP-Staging copy that must never be migrated from.

Cross-store overlap is small: **977 distinct emails** from ~993 rows — ng∩old 13, ng∩intl 1,
old∩intl 3. The audit's guess that "many old-NG customers likely re-registered" is wrong;
collision handling is a **17-row** problem, not a hundreds-row one.

## THE OTHER FINDING: a registration flood is running on the live stores, right now

Not part of this plan, and more urgent than it.

| | |
|---|---|
| Intl store | 3,269 users — **3,218 registered since 14 July**, all role `subscriber`, **zero with any order** |
| NG current | 4,639 users — 3,423 since 14 July, of which only 58 have an order |

**It is still growing:** intl went from 3,269 to **3,284 users during the two reviews that
produced this plan.** The newest registrations are seconds apart (`21:48:42`, `21:48:43`, `21:48:45` on
2026-08-01) with random-looking Gmail addresses. The audit measured 1,218 NG and 51 intl
users on 14 July. **This is automated signup abuse, still in progress**, on a host that has
already had one malware incident (audit §12).

It does not corrupt this migration — the "≥1 order" filter excludes every one of them, and
that filter is now doing real security work. But open registration being farmed on a live
store is worth acting on independently: it is a spam/abuse surface and it bloats every
table this plan reads.

## What is NOT blocked

`apps/accounts/hashers.py` — the WordPress-compatible password hasher. It needs no
WooCommerce access at all: phpass, bcrypt and `$wp$` hashes can all be generated locally
and verified against, which is exactly how the spec says to test it. It is also the piece
that decides whether 937 people can keep their passwords, so it deserves the most scrutiny
in the stage.

## Design rulings (settled by the review)

### 1. A dedicated, short-lived credential — not a widened `wp_readonly`, not a dump

Widening `wp_readonly` would falsify the load-bearing docstring at `wp_reader.py:1-7` and
give the recurring **catalogue** import permanent access to password hashes. Instead:
**`wp_migration@localhost`**, created for this stage and **dropped after Plan-27's delta
sync**.

A one-shot dump was considered and rejected: Plan-27 step 3 needs
`migrate_customers --since` against live data at cutover, which a dump cannot do — and a
file of ~977 password hashes sitting on a laptop is *more* exposure than a localhost-only
database user, not less.

**The grant to approve — 23 tables, one approval covering Plan-23 too.** A second review
pass corrected its own first answer here, and the correction is measured:

- **`wc_order_operational_data` was missing, and Plan-23 would have failed without it.**
  All three stores run HPOS, and in HPOS `wc_orders` has **no `date_paid_gmt` column** —
  verified. `date_paid_gmt`, `date_completed_gmt`, `shipping_total_amount` and
  `discount_total_amount` all live in the operational-data table. An 18-table grant would
  have hit `ERROR 1142` partway through the order import.
- **Intl has 13 orders HPOS never backfilled** — `tokecosm_usawp100.wp8n_posts` holds 13
  `shop_order` rows (2023) alongside 125 in `wc_orders`. They need `posts` + `postmeta` on
  that one prefix, or Plan-23 silently loses them. Their `_customer_user` values point at
  deleted users, so Plan-22's customer set is unaffected.
- **Deliberately excluded:** `wc_orders_meta` (attribution/analytics noise),
  `wc_customer_lookup`, `wc_order_stats` and the `*_lookup` derived tables. Refunds need
  nothing extra — they are `wc_orders` rows of type `shop_order_refund`. Coupon lines are
  `woocommerce_order_items` rows.

So: `{users, usermeta, wc_orders, wc_order_addresses, wc_order_operational_data,
woocommerce_order_items, woocommerce_order_itemmeta}` × three store prefixes, **plus**
`posts` and `postmeta` on `tokecosm_usawp100.wp8n_`.

**`@localhost` is correct, and now proven rather than assumed.** MariaDB binds
`127.0.0.1` only, so no container can reach it over TCP; the extract runs as a one-off
`docker compose run --rm` with the unix socket bind-mounted read-only
(`docs/runbooks/migration.md:107-118`), and a socket connection authenticates as
`localhost`. The long-lived `web`/`worker`/`beat` containers deliberately do not mount it.

**The credential does NOT go in `.env.prod`** — verified: that file contains no `WP_DB_*`
lines, matching `base.py:486-489`. It follows the proven Plan-21 pattern: a root-only
`0600` file (`/root/wp-migration.env`, mirroring the existing `/root/wp-readonly.env`),
sourced and forwarded valuelessly so it never enters shell history or `docker inspect`.

**Create it at extract time, not on approval.** Every day it exists unused is exposure on
a box that is being actively probed right now.

**Verification must include two NEGATIVE checks** that have to fail with `ERROR 1142`:
`tokecosm_usawp100.wpstg0_users` (the WP-Staging copy shares that database and must be
provably out of scope) and `tokecosm_wp481.wp_options`.

**Two exposures to close regardless:** `wp_usermeta` contains **`session_tokens` — live
session material for the running store** — so the extractor allow-lists meta keys exactly
as `wp_reader.fetch_meta` already does (`wp_reader.py:24-52`); and the extract artifact
holds real hashes, so it is chmod 600, never committed (fixtures use synthetic hashes) and
deleted after import.

### 2. Implement the spec's hasher as pasted — its *settings note* is what is wrong

The review tested the spec's code against material generated by the **VPS's own PHP**
(`password_hash(base64_encode(hash_hmac('sha384', pw, 'wp-sha384', true)))`) and WordPress's
own `class-phpass.php`, plus `$2y$` on two bcrypt versions, unicode passwords, and the
`!locked` hashes that actually exist in these tables. It verifies correctly and integrates
with Django 5.2: `identify_hasher` resolves, `check_password` fires the upgrade setter on
success and not on failure.

Corrections to the spec's surrounding prose:

- It says to prepend "Argon2… (default list)". **This repo defines no `PASSWORD_HASHERS` at
  all**, so the effective default is PBKDF2-first, and Argon2 would need `argon2-cffi`,
  which is not a dependency. **Do not smuggle a default-hasher change into a migration
  plan** — define the list explicitly as Django's default plus `wordpress` appended; Argon2
  is its own decision.
- `bcrypt` and `passlib` are both new dependencies. **`passlib` is unmaintained** (1.7.4,
  2020) and serves exactly **86 users** — 84 NG-old plus 2 intl on `$P$`; NG current is
  100% `$wp$`. Pin it with a comment, or vendor a short phpass verify. Silent adoption is
  the option that is not acceptable.
- Add a system check that `PASSWORD_HASHERS[0]` is never `wordpress` — the hasher's
  `encode()` raises, and it is only reachable if a future settings edit puts it first.

### 3. `LegacyIdentity`, and delete `legacy_wp_id_intl` before it holds data

Three stores against two columns is already the wrong shape, and the columns are **empty
today** — the last cheap moment to fix it.

```
LegacyIdentity(user, store, wp_user_id)   # unique (store, wp_user_id)
```

It is the idempotency key for `--since` re-runs, and it is exactly the
`(store, customer_id) → user` map **Plan-23 needs to link orders**. Collision precedence:
`legacy_ng > legacy_intl > legacy_ng_old` — the two live stores beat the one dead since
November 2025. It decides 17 cases.

### 4. Three rules that prevent data loss at cutover

- **Password and legacy fields are set on CREATE only, never on update.** A customer who
  migrates at staging and then resets their password on the new site must not have it
  reverted by the cutover delta run.
- **Never touch a pre-existing account.** By cutover the Django database holds staff —
  including Hammed's own — and possibly organic signups whose emails collide. The importer
  attaches a `LegacyIdentity` and refuses to write password, names or `is_staff`. Silently
  replacing a staff account's hash with a customer's WP hash is the worst outcome available
  here.
- **Route creation through `UserManager._create_user`** (`managers.py:10-29`), which already
  lowercases email and retries `toke_id` collisions, then assign the WP hash separately.

### 5. What Plan-23 inherits

Link orders by `LegacyIdentity(store, wp_user_id)` **first**, `billing_email` only as the
guest fallback — the spec's email-only linkage is lossy, because ordering on someone else's
behalf makes billing email ≠ login email. Also: NG `billing_state` is a WooCommerce code
("LA") and `Address` wants `core.Region` FKs, so a code→Region map is needed; an incomplete
address skips the address, never the user.

**PII stays out of git.** The spec puts a campaign CSV under `docs/migration/` — 977 names
and emails would enter git history. Counts-only report in the repo; the CSV goes where
Plan-21's artifacts go.

**Loyalty balances** (audit §345) are a flagged checkpoint decision that this stage is the
natural moment to snapshot. Surfaced, not silently dropped.

## What the review changed

- **My topology was wrong.** NG-old is `tokecosm_wp481.wp8n_*`, not `tokecosm_wp788` —
  which is not a store at all. Grants drafted from my table would have targeted an empty
  database. I had inferred it from a table-name count instead of measuring.
- **"Blocked" was too broad.** Plan-21's extract → artifact → import shape means everything
  here is buildable and testable against fixtures *now*; only the first real extract needs
  the grant. Sequencing the whole stage behind Hammed's decision was my error.
- **The audit's counts are three weeks stale**, and the reason is a live registration flood.
- **The spec's hasher is correct**; I had assumed the risk was in the code. It is in the
  settings note around it.
- **The dedup problem is 17 rows**, not the hundreds the audit implied.
