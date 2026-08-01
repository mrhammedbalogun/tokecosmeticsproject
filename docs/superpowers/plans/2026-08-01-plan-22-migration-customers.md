# Plan-22 — customer migration

Master spec: `master-tokerebuild.md` §Plan-22-migration-customers. Branch off `main`
(`4a7a369`).

> **DRAFT — blocked on a decision only Hammed can make, and a Fable review is running.**

---

## Grounding (measured 2026-08-01 — do not re-derive)

| | |
|---|---|
| Legacy stores | **THREE**, all on one MariaDB host |
| `tokecosm_wp481` | NG current — **639** registered customers with ≥1 order |
| `tokecosm_wp788` | NG old — **285** |
| `tokecosm_usawp100` | Intl — **13** |
| Total before dedup | **937** (the audit expects the deduped figure to be lower) |
| Guest-order emails | **~2,042** — these get NO account, by Decision 7 |
| `User` legacy fields | `legacy_source`, `legacy_wp_id`, `legacy_wp_id_intl` already exist |

## THE BLOCKER: the migration credential deliberately cannot read customers

`wp_readonly@localhost` holds exactly this, verified on the live host today:

```
GRANT SELECT ON tokecosm_wp481.wp_posts             TO wp_readonly@localhost
GRANT SELECT ON tokecosm_wp481.wp_postmeta          TO wp_readonly@localhost
GRANT SELECT ON tokecosm_wp481.wp_terms             TO wp_readonly@localhost
GRANT SELECT ON tokecosm_wp481.wp_term_taxonomy     TO wp_readonly@localhost
GRANT SELECT ON tokecosm_wp481.wp_term_relationships TO wp_readonly@localhost
```

Five tables, **one** database. `wp_reader.py`'s own docstring says why, in as many words:

> "The MariaDB user this runs as is granted SELECT on those five and nothing else, so a
> compromise here cannot reach `wp_users` or any order table."

That is a control somebody built on purpose in Plan-21, and Plan-22 cannot proceed without
widening it: this stage needs `wp_users` (which holds **the password hash of every
customer**) and `wp_usermeta`, plus the order tables to apply the "≥1 order" filter — in
**three** schemas, not one.

**This is a security decision, not an implementation detail, so it is Hammed's.** It is
also the first time in this project that a service credential would be able to read
password material. The plan will state the exact minimum grant and the alternative
(a filtered dump prepared by hand, so the service account never holds hash access at all)
once the review returns.

Until it is decided, **nothing in this plan may write a row**, and no import can even be
dry-run against real data.

## What is NOT blocked

`apps/accounts/hashers.py` — the WordPress-compatible password hasher. It needs no
WooCommerce access at all: phpass, bcrypt and `$wp$` hashes can all be generated locally
and verified against, which is exactly how the spec says to test it. It is also the piece
that decides whether 937 people can keep their passwords, so it deserves the most scrutiny
in the stage.

## Open questions the review is being asked

- The spec pastes a full hasher implementation. It should be scrutinised, not copied.
- **Three stores, two ID columns.** The spec says "collision across the two stores" and
  provides `legacy_wp_id_intl` only; NG-old has nowhere to be recorded.
- What Plan-23 will need that this stage should prepare for.
