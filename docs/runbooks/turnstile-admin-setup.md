# Turnstile on the admin app — complete setup guide

**Status: widget not yet created. This is the outstanding human step blocking Plan-16 Task 8.**

Everything in the codebase is already built and tested for this. Setup is: create one
widget in Cloudflare, put its two values in two places, redeploy. No code changes.

The deeper *reasoning* for a separate admin widget lives in
[`admin-gate.md` §8.3](./admin-gate.md) and in the header comment of
`admin/src/components/TurnstileWidget.tsx`. This file is the procedure.

---

## 0. The shape of it

One **new** Turnstile widget, separate from the storefront's, producing two values:

| value | visibility | destination | env var |
|---|---|---|---|
| Site key | public (ships in the browser bundle) | Vercel — admin project | `NEXT_PUBLIC_TURNSTILE_ADMIN_SITE_KEY` |
| Secret key | **secret** | VPS `/opt/tokecosmetics/.env.prod` | `TURNSTILE_ADMIN_SECRET` |

Why a separate widget rather than adding the admin hostname to the storefront's:

1. **Domain scoping.** Turnstile widgets only render on their allowlisted hostnames. The
   storefront's widget is scoped to `next.tokecosmetics.com` and would error client-side
   on the admin host before a token was ever minted.
2. **Break-glass granularity.** `TURNSTILE_ADMIN_SECRET` is read *first* by the staff gate,
   falling back to `TURNSTILE_SECRET`. During a Cloudflare siteverify outage the rehearsed
   recovery ([`admin-gate.md` §2](./admin-gate.md)) is to drop the secret and restart —
   with two secrets that reopens the *staff* door without also reopening the customer door.

### Hostnames

Decided 2026-07-29:

| hostname | role | status |
|---|---|---|
| `admin.tokecosmetics.com` | production admin app | CNAME created |
| `admin-preview.tokecosmetics.com` | Vercel branch domain, for the Task 8 checkpoint | to create |

Turnstile hostname rules that shaped this choice
([docs](https://developers.cloudflare.com/turnstile/additional-configuration/hostname-management/)):

- Adding a hostname **automatically covers its subdomains**.
- **Wildcards (`*`) are not supported.** This is why preview deploys need a stable custom
  domain — `*.vercel.app` cannot be allowlisted, and adding bare `vercel.app` would
  authorize the widget across the entire Vercel platform.
- Free plan: **10 hostnames per widget** (Enterprise: 200).

`backend.tokecosmetics.com` was the Plan-02 placeholder and is **not** being used — it
reads like the API (the real API is `api.tokecosmetics.com`), and staff-invite emails
carry this hostname in a password-setting link, where "backend.…" reads like phishing.

---

## 1. Create the widget (Cloudflare dashboard)

1. [dash.cloudflare.com](https://dash.cloudflare.com) → the account holding
   `tokecosmetics.com` → **Turnstile**
2. **Add widget**
3. Widget name: `toke-admin`
4. Hostnames: `admin.tokecosmetics.com`, `admin-preview.tokecosmetics.com`
5. Widget mode: **Managed** (Cloudflare's recommendation — chooses interactive vs
   invisible per visitor risk)
6. **Create** → copy the **site key** and **secret key**

Both are re-readable and rotatable from the dashboard afterwards; nothing is shown once.

---

## 2. Rollout order — this one matters

**Site key first, secret second.** The backend fails **closed**: with
`TURNSTILE_ADMIN_SECRET` set but no widget rendering, every staff login gets a 403 and
there is no token to send. This is the same storefront-first order used for the customer
gate on 2026-07-28.

```
① Vercel: site key + redeploy   →   widget renders, backend not yet gated
② VPS: secret + restart         →   gate live
③ Verify
```

Note the intermediate state in ① is **not** ungated: with `TURNSTILE_ADMIN_SECRET` unset,
the staff gate falls back to `TURNSTILE_SECRET` (the customer widget's secret), which is
set in production. An admin token minted by the *admin* widget will be **rejected** by the
*customer* secret. So between ① and ② staff login returns 403 — keep the window short and
do not do this during business hours once staff are live. (Today nobody is live, so it
does not matter.)

---

## 3. Site key → Vercel

The admin app is the third deployable and needs its own Vercel project. Existing projects
for reference: `tokecosmeticsproject` (storefront, personal account, prod =
`next.tokecosmetics.com`) and `tokecosmeticsproject-xvec` (a stale Create-Next-App
scaffold holding `backend.tokecosmetics.com` — a cleanup candidate, not the admin).

Once the admin project exists and `admin.tokecosmetics.com` is assigned to it:

```bash
cd tokecosmetics-platform/admin
printf '%s' '0x4AAA…SITEKEY' | npx vercel env add NEXT_PUBLIC_TURNSTILE_ADMIN_SITE_KEY production
printf '%s' '0x4AAA…SITEKEY' | npx vercel env add NEXT_PUBLIC_TURNSTILE_ADMIN_SITE_KEY preview
```

> **Use Git Bash `printf`, never PowerShell.** Piping a value through `Write-Output`
> prepends a BOM (U+FEFF). On 2026-07-28 that exact mistake put an invisible character in
> the storefront's site key and crashed `/login` behind a client error boundary. The
> symptom looks nothing like the cause.

The admin project also needs, per `admin/README.md`:

| variable | value |
|---|---|
| `API_URL` | `https://api.tokecosmetics.com` |
| `NEXT_PUBLIC_API_URL` | `https://api.tokecosmetics.com` (drives the red STAGING badge when it is anything else) |

Then **redeploy**. `NEXT_PUBLIC_*` values are inlined at build time — setting the variable
without a rebuild changes nothing.

---

## 4. Secret → VPS

Back up first, append, recreate the two containers that read it:

```bash
ssh tokecosmetics 'cp /opt/tokecosmetics/.env.prod /root/env-prod-$(date +%F-%H%M).bak'

ssh tokecosmetics 'echo "TURNSTILE_ADMIN_SECRET=0x4AAA…SECRET" >> /opt/tokecosmetics/.env.prod'

ssh tokecosmetics 'cd /opt/tokecosmetics/repo/infra && docker compose -p tokecosmetics --env-file /opt/tokecosmetics/.env.prod -f docker-compose.prod.yml up -d web worker'
```

> **PowerShell quoting gotcha:** wrap remote commands containing `$(...)` or `$VAR` in
> **single** quotes — PowerShell does not escape `$` with a backslash.

### Also update `ADMIN_URL` in the same pass

Production still carries the Plan-02 placeholder:

```
ADMIN_URL=https://backend.tokecosmetics.com    # ← change to https://admin.tokecosmetics.com
```

This is not cosmetic. `ADMIN_URL` is:

- the base of every **staff-invite link** (`apps/accounts/views.py:731` builds
  `${ADMIN_URL}/accept-invite?token=…`) — wrong value means invites point at a scaffold;
- half of **`CORS_ALLOWED_ORIGINS`**, which is derived as `[FRONTEND_URL, ADMIN_URL]` in
  `base.py:384` and is **not** explicitly set on prod — so with the wrong value every
  browser-side call from the admin app fails its preflight, which the browser reports as
  an opaque network error that reads like "the API is down".

```bash
ssh tokecosmetics 'sed -i "s|^ADMIN_URL=.*|ADMIN_URL=https://admin.tokecosmetics.com|" /opt/tokecosmetics/.env.prod'
```

(Then the same `docker compose … up -d web worker` as above. `ALLOWED_HOSTS` needs no
change — it covers the API's own hostname, `api.tokecosmetics.com`, not the callers'.)

---

## 5. Verify

**a. Widget renders.** Load `https://admin.tokecosmetics.com/login`. The Turnstile box
appears below the password field. If it does not, the site key is unset, has a BOM, or the
hostname is not in the widget's allowlist.

**b. Tokenless request is rejected.** From anywhere:

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  https://api.tokecosmetics.com/api/v1/auth/admin-token/ \
  -H 'Content-Type: application/json' \
  -d '{"email":"nobody@example.com","password":"wrong"}'
```

Expect **403** (`turnstile_missing`). A 401 here means the gate is not active.

**c. The pair actually matches.** In the browser, solve the widget and submit a **wrong**
password. Expect **401**, not 403. This is the load-bearing check: 401 means the token
passed siteverify and execution reached the password comparison, which is the only proof
that this site key and this secret belong to the same widget. A 403 at this point means
they do not.

**d. Failures reach Sentry.** Admin login failures log at ERROR through the
`apps.security` logger, so step (c) should produce a Sentry event.

---

## 6. Development — use Cloudflare's test keys, never the real pair

Published, permanent, and documented by Cloudflare. They are deliberately **not**
defaulted anywhere in the source: a widget that silently always passes is exactly the kind
of thing that ships to production once and is never noticed.

| behaviour | site key | secret |
|---|---|---|
| always passes | `1x00000000000000000000AA` | `1x0000000000000000000000000000000AA` |
| always fails (exercises the rejection path) | `2x00000000000000000000AB` | `2x0000000000000000000000000000000AA` |

The full three-step login ceremony (password → TOTP → session) is verifiable end to end
against these.

---

## 7. Operating it afterwards

**Rotating the secret.** Rotate in the Cloudflare dashboard, update `.env.prod`, restart
`web` and `worker`. Note the failure mode: a *typo'd* or *missing*
`TURNSTILE_ADMIN_SECRET` does not disable the gate — it falls back to `TURNSTILE_SECRET`
and every admin token is rejected against the wrong widget. The symptom is "admin login
mysteriously always fails", not an error at startup. There is a regression test pinning
this fallback (`test_admin_auth.py:288`).

**Break-glass during a Cloudflare outage.** `admin-gate.md` §2. Dropping
`TURNSTILE_ADMIN_SECRET` only opens the staff gate *while it holds its own distinct
value* — if it were ever set equal to `TURNSTILE_SECRET`, deleting it changes nothing.

**Adding hostnames later.** Edit the widget's hostname list in the dashboard; it takes
effect immediately, no redeploy. Remember subdomains are included automatically and
wildcards are not supported.

**Never add a third-party script to this origin** to work around anything Turnstile
related. `/accept-invite?token=…` carries a staff-creation capability in the URL and the
TOTP setup screen renders a secret on the page. The CSP in `admin/next.config.ts` allows
`challenges.cloudflare.com` and nothing else, deliberately.

---

## Checklist

- [ ] `admin.tokecosmetics.com` CNAME → Vercel *(done 2026-07-29)*
- [ ] `admin-preview.tokecosmetics.com` CNAME + Vercel branch domain
- [ ] Turnstile widget `toke-admin` created, both hostnames allowlisted, mode Managed
- [ ] Admin Vercel project created, domain assigned
- [ ] `API_URL` + `NEXT_PUBLIC_API_URL` set on the admin project
- [ ] `NEXT_PUBLIC_TURNSTILE_ADMIN_SITE_KEY` set (production + preview), via bash `printf`
- [ ] Admin app redeployed
- [ ] `.env.prod` backed up
- [ ] `ADMIN_URL` corrected to `https://admin.tokecosmetics.com`
- [ ] `TURNSTILE_ADMIN_SECRET` appended
- [ ] `web` + `worker` recreated
- [ ] Verified: widget renders · tokenless 403 · solved+wrong-password 401 · Sentry event
- [ ] Vercel Deployment Protection **on for previews, off for production**
      ([`admin-gate.md` §8.4](./admin-gate.md))
