# Toke Admin

The staff administration app — the third deployable, alongside `backend/` and
`storefront/`. Next 16 (App Router), port **3001** in development, which is what
`backend`'s `ADMIN_URL` defaults to (staff-invite links are built from it).

```bash
npm --prefix admin run dev        # http://localhost:3001
npm --prefix admin test           # vitest
npm --prefix admin run build
```

## Environment

| variable | who reads it | notes |
|---|---|---|
| `API_URL` | server only | Django base, e.g. `http://localhost:8000`. Never exposed to the browser. |
| `NEXT_PUBLIC_API_URL` | browser | Same URL, published so the topbar can show a red **STAGING** badge whenever it is not `https://api.tokecosmetics.com`. Also the fallback for `API_URL`. |
| `NEXT_PUBLIC_TURNSTILE_ADMIN_SITE_KEY` | browser | The **admin** Turnstile widget's site key. Unset = widget off, matching an unset `TURNSTILE_ADMIN_SECRET`/`TURNSTILE_SECRET` on the backend. |

There is deliberately nothing else. No secret belongs in this bundle beyond a
`NEXT_PUBLIC_*` site key.

### Turnstile in development — use Cloudflare's permanent test keys

The real admin widget is a **separate** Turnstile widget from the storefront's, because
widgets are domain-scoped and this is a new hostname — and because a separate widget pairs
with `TURNSTILE_ADMIN_SECRET`, which is what lets an operator drop the *staff* gate during
a siteverify outage without also dropping the customer gate
(`docs/runbooks/admin-gate.md` §2). Creating it needs a human in the Cloudflare dashboard,
and that is a **launch** dependency, not a build one.

Cloudflare publishes permanent, documented test keys. Use them locally; the full
three-step ceremony is verifiable end to end with them, and production cutover is swapping
two values.

| behaviour | site key (`NEXT_PUBLIC_TURNSTILE_ADMIN_SITE_KEY`) | secret (`TURNSTILE_ADMIN_SECRET`, backend) |
|---|---|---|
| always passes | `1x00000000000000000000AA` | `1x0000000000000000000000000000000AA` |
| always fails (use to exercise the rejection path) | `2x00000000000000000000AB` | `2x0000000000000000000000000000000AA` |

They are **not** defaulted in the source. A widget that silently always passes is exactly
the kind of thing that ships to production once and is never noticed.

## Rules this app is built to

- **ZERO third-party scripts or analytics on this origin, ever.** No tag manager, no
  session replay, no font CDN. It is what makes `/accept-invite?token=…` (a staff-creation
  capability in a URL) and the TOTP setup screen (a secret on screen) safe. The only
  exception is Cloudflare's own Turnstile widget, loaded on the two unauthenticated forms.
  Enforced by the CSP in `next.config.ts`.
- **No service worker**, and `Cache-Control: no-store` on every page and BFF response
  (`src/proxy.ts`).
- **Never link to this hostname from the storefront**, and never add a sitemap.
  `X-Robots-Tag: noindex` is set site-wide.

## The BFF surface, in full

Short on purpose. Every entry below is a place cookies are written or a credential is
forwarded; the list is meant to stay countable on one hand.

| surface | what it does |
|---|---|
| `app/login/actions.ts` | password + Turnstile → stores the **preauth** cookie |
| `app/totp/actions.ts` | enrol / confirm / recovery — confirm is the only thing that stores a session |
| `app/accept-invite/actions.ts` | invite token + password → stores the **preauth** cookie |
| `app/(shell)/actions.ts` | sign out: blacklists the refresh token, clears every cookie |
| `app/(shell)/search-actions.ts` | global search: forwards the access token, renews once if needed, and **never redirects** |
| `app/api/[...path]/route.ts` | the generic authenticated proxy |
| `app/api/auth/refresh-redirect/route.ts` | renewal bounce for Server Components (they cannot write cookies) |
| `app/api/auth/purge/route.ts` | clears the three cookies and returns to `/login` — the destination a page's "anomaly" decision redirects to, for the same reason: a page cannot delete a cookie |

## Session model

Three httpOnly, `SameSite=Strict` cookies, and the third one is the design:

- `admin_preauth` (10 min) — the bootstrap credential. Opens exactly three backend
  endpoints and nothing else.
- `admin_access` (10 min) / `admin_refresh` (**12 h**, not the storefront's 14 days) — a
  real session, obtainable only from `/auth/admin-totp/confirm/`.

The two sets are **mutually exclusive at write time**, so holding both is an anomaly the
gate purges rather than an ambiguity it has to guess about. The full matrix, with the
reasoning, is at the top of `src/lib/auth-guard.ts`.

## Global search (topbar)

One box, up to ten results per section, **no links on any result**. Plans 17/18 build the
order, customer and product pages; until they exist a linked result is a 404 with extra
steps, so the useful fields are inline instead — order number + status + total, customer
name + toke_id, product name + SKUs. That answers the two questions the owner asks all day
("what is the status of TC-100123", "which customer is this email") with no navigation at
all. When the detail pages land, add `href`s in `lib/search.ts` and `GlobalSearch.tsx`;
nothing else has to change.

**This app never filters sections.** The response contains only the sections the caller's
scopes allow — derived on the backend from each section's own list endpoint — and a role
holding none of them gets `{}` and the ordinary "no matches" message. Re-deciding that in
the browser would put a second, weaker copy of the scope rule in a bundle anybody can read.
The box is rendered for every staff member for the same reason.

The 250 ms debounce is UX. The controls are server-side: a three-character minimum, ten
results per section with no pagination, and 60/min per staff user.

## What is NOT here yet

- **No QR code on the TOTP setup screen.** Rendering one needs a QR encoder, and this app
  may take new dependencies only where the storefront already uses the equivalent — it has
  none. The screen shows the setup key for manual entry plus the raw `otpauth://` URI,
  which every authenticator app accepts. Pointing an `<img>` at a QR web service is **not**
  an option: it would put the TOTP secret in a third party's request log.
- Every nav item except Dashboard links to a page Plans 17-19 will build.
