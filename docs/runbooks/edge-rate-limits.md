# The two edge rate-limit rules — complete guide

**Status as of 2026-07-30: neither is configured.** `vercel firewall overview` on the
admin project reports *Not configured*, and there is no Cloudflare rate-limiting rule on
`api.tokecosmetics.com`.

These are the last two items from Plan-16's admin hardening. They are specified in
[`admin-gate.md` §1](./admin-gate.md); this file is the step-by-step.

---

## 0. Why these exist at all — read this first

It explains every odd choice below.

The admin login is a **Server Function**: the browser posts to the admin app, and the
admin app calls Django *server-side*. So every legitimate staff login reaches Django from
a **Vercel egress address** — and so does an attacker who drives the login page. Django
sees one address for both populations.

That makes a request-volume cap inside Django actively harmful: it denies the staff by
construction. Raising the number raises the price of the lockout, it does not remove it.
An earlier adversarial review found exactly this — **five empty POSTs per minute locked
every staff member out**, with no Turnstile solved and no password guessed.

So both Django throttles on `/auth/admin-token/` count **failed credential attempts**,
never requests:

| throttle | rate | counts |
|---|---|---|
| `admin_login_ip` | 5/min | failed credential attempts |
| `admin_login_email` | 10/hour | failed credential attempts |

Empty POSTs, malformed bodies and Turnstile-blocked bots consume **nothing**, and a
successful staff login clears both buckets.

**The deliberate consequence: `/auth/admin-token/` has no request-volume cap in Django at
all.** Junk that never reaches a password check is unmetered — including junk carrying a
bogus Turnstile token, each of which costs one outbound siteverify call with a 5-second
timeout.

**That gap is what these two rules close.** They cap *volume*; Django caps *guesses*. They
are not substitutes for each other, and the Django throttles stay exactly as they are.

### Why two rules and not one

| hostname | proxied by | verified |
|---|---|---|
| `admin.tokecosmetics.com` | **Vercel only** — not Cloudflare | `Server: Vercel`, no `CF-RAY` |
| `api.tokecosmetics.com` | **Cloudflare** → VPS | `Server: cloudflare`, `CF-RAY` present |

A Cloudflare rule **cannot see admin login traffic** — that hostname is a bare CNAME to
Vercel. And a Vercel rule cannot see a caller who skips the admin app and posts straight
to the API, which is what any scripted attacker does. Each rule covers a path the other
is blind to. This is the same class of mistake recorded in
`project_tokecosmetics_real_client_ip_gap`: a control written down for a hostname that
does not route through the thing enforcing it.

---

## Rule A — Vercel Firewall, on the admin login

**Covers:** somebody hammering `admin.tokecosmetics.com/login`.

Project `tokecosmeticsproject-ytgp`, team `billztechnologiesofficial-5180s-projects`.

### What it matches

The login form renders as `<form action="" method="POST">` — an empty action posts to the
**current URL**. So the Server Function arrives as `POST /login`, verified against the
live page.

### Step A1 — add it in LOG mode

Log mode records hits and blocks nothing. Do not skip this: you are the only staff member,
and a rule that misfires locks *you* out of your own store's admin.

```bash
cd tokecosmetics-platform/admin

npx vercel firewall rules add "Admin login volume cap" \
  --condition '{"type":"path","op":"eq","value":"/login"}' \
  --condition '{"type":"method","op":"eq","value":"POST"}' \
  --action rate_limit \
  --rate-limit-window 600 \
  --rate-limit-requests 20 \
  --rate-limit-keys ip \
  --rate-limit-action log \
  --yes
```

20 requests per 10 minutes per IP. Staff volume is a handful of logins a day, so this is
deliberately generous — it is a volume cap, not a guess cap. Guesses are Django's job.

**Note `--rate-limit-action log`, not `deny`.** The rule counts and records; nothing is
blocked yet.

### Step A2 — review, then publish

Rule changes are **staged**. Nothing is live until you publish.

```bash
npx vercel firewall diff          # read what is about to change
npx vercel firewall publish --yes
```

### Step A3 — watch it for a day

Get the rule id, then open the filtered traffic view:

```bash
npx vercel firewall rules list --json    # find the "id" field, starts with rule_
```

```
https://vercel.com/billztechnologiesofficial-5180s-projects/tokecosmeticsproject-ytgp/firewall/traffic?filter=<ruleId>
```

You are checking one thing: **does your own normal use ever approach 20 in 10 minutes?**
Log in a few times, get a TOTP code wrong on purpose, reload the page. If your own use
sits well under the limit, the rule is safe to enforce.

### Step A4 — enforce

```bash
npx vercel firewall rules edit "Admin login volume cap" \
  --action rate_limit \
  --rate-limit-window 600 \
  --rate-limit-requests 20 \
  --rate-limit-keys ip \
  --rate-limit-action deny \
  --yes

npx vercel firewall diff
npx vercel firewall publish --yes
```

> **`edit --condition` replaces ALL conditions on a rule.** The command above changes only
> the action, so the conditions are left alone deliberately. If you ever pass one
> `--condition`, you must pass every condition the rule should keep.

### ⚠ Do not add `--duration` to this rule

`--duration` makes a block **persistent**: the client stays blocked for the whole duration
**even if you delete the rule**. On the one door you use to administer your own store,
that turns a small misconfiguration into a lockout you cannot undo by fixing the rule.
Leave duration unset so every action is evaluated per-request and deleting the rule is an
instant fix.

### Optional — the same cap on `/accept-invite`

Beyond `admin-gate.md`'s spec, and worth considering once you have real staff.
`/accept-invite` is the other unauthenticated POST on the admin origin, and the capability
behind it is *creating an administrator*. Django already throttles invalid invite tokens,
so this is again a volume cap rather than a guess cap:

```bash
npx vercel firewall rules add "Accept-invite volume cap" \
  --condition '{"type":"path","op":"eq","value":"/accept-invite"}' \
  --condition '{"type":"method","op":"eq","value":"POST"}' \
  --action rate_limit --rate-limit-window 600 --rate-limit-requests 20 \
  --rate-limit-keys ip --rate-limit-action log --yes
```

Same log → review → deny progression.

---

## Rule B — Cloudflare, on the API's staff-login endpoint

**Covers:** a caller who ignores the admin app and posts straight to
`api.tokecosmetics.com`. This is the one that matters against scripted abuse, because a
script has no reason to go through the UI.

### Step B1 — create the rule

1. [dash.cloudflare.com](https://dash.cloudflare.com) → zone **tokecosmetics.com**
2. **Security → WAF → Rate limiting rules → Create rule**
3. Name: `admin-token volume cap`
4. **If incoming requests match** → *Edit expression* and paste:

   ```
   (http.host eq "api.tokecosmetics.com" and http.request.uri.path eq "/api/v1/auth/admin-token/")
   ```

5. **Rate limiting characteristics:** IP
6. **Period:** 10 minutes · **Requests:** 20
7. **Then take action:** Block · **Duration:** 10 minutes
8. Deploy

### If 10 minutes is not offered

The available periods depend on your Cloudflare plan — the shorter ones (10s/60s) are
always there, longer ones are not. Scale proportionally rather than raising the rate:

| period available | use requests |
|---|---|
| 10 minutes | 20 |
| 1 minute | 5 |
| 10 seconds | 2 |

### Why the path is matched with `eq` and not `pre`

`eq` matches **exactly** `/api/v1/auth/admin-token/` and nothing else.

A prefix match on `/api/v1/auth/` would sweep in `token/refresh/` — the endpoint every
signed-in customer's browser calls to renew a session. Rate-limiting that by IP would log
out shoppers behind a shared connection, in a way that looks like a random site bug. This
is a recorded constraint on the *storefront* Cloudflare rule too
(`project_tokecosmetics_login_throttle_gap`): **any rule in this zone must exclude
`token/refresh/`.**

---

## Verifying, safely

Test from a network you can afford to have blocked — mobile data, not the machine you
administer the store from.

**Rule B** is easy to test directly:

```bash
for i in $(seq 1 25); do
  curl -s -o /dev/null -w "%{http_code} " --max-time 10 \
    -X POST https://api.tokecosmetics.com/api/v1/auth/admin-token/ \
    -H 'Content-Type: application/json' -d '{"email":"probe@example.com","password":"x"}'
done; echo
```

Expect a run of `403` (Turnstile refusing, which is Django working) turning into `429` or
Cloudflare's block page once you pass 20. **Those 403s cost nothing in Django** — the
whole point is that they never reach a password check — so this probe is safe to run.

**Rule A** is harder to probe honestly, because a real Server Action POST needs a valid
action id. The log-mode soak in Step A3 is the better evidence: it tells you what real
traffic actually does, which is the number that matters.

---

## If you lock yourself out

Both are reversible in under a minute, and neither touches Django.

**Vercel:**
```bash
cd tokecosmetics-platform/admin
npx vercel firewall rules disable "Admin login volume cap"
npx vercel firewall publish --yes
```

**Cloudflare:** WAF → Rate limiting rules → toggle the rule off. Immediate.

Because Rule A carries no `--duration`, disabling it restores access at once. If you ever
add a duration and get caught by it, you must wait it out — that is the reason the
guidance above says not to.

Neither rule can lock you out of the **API itself**; both are scoped to a single path.
The VPS remains reachable over SSH regardless — Cloudflare is not in that path.

---

## What NOT to do

- **Do not add a request-volume throttle in Django to "fix" this properly.** It reintroduces
  the free staff lockout described in §0. The volume cap belongs at the edge precisely
  because the edge can see the real client IP and Django cannot.
- **Do not loosen the Django throttles because the edge now caps volume.** They cap
  different things — guesses per account, versus requests per address.
- **Do not use a path prefix in the Cloudflare expression.** See `token/refresh/` above.
- **Do not set a persistent `--duration` on the admin login rule.**

---

## Known limitation, stated rather than hidden

**Vercel rate-limit counters are per region.** Traffic spread across N regions can
collectively exceed the configured limit by roughly N×. For a volume cap on a login door
this is acceptable — the purpose is to stop cheap floods, and Django's failure-counting
throttles remain the per-account control underneath. It is worth knowing before anyone
reads "20 per 10 minutes" as a hard global ceiling.

---

## Related, but not this task

- **Storefront `/api/auth/*` rate limiting** — a separate Vercel Firewall rule on the
  `tokecosmeticsproject` project. `next.tokecosmetics.com` is also not Cloudflare-proxied,
  so it has the same shape as Rule A. See `project_tokecosmetics_real_client_ip_gap`.
- **Customer login Cloudflare rule** — the pre-Plan-22 gate item; same zone as Rule B, and
  subject to the same `token/refresh/` exclusion.

## Checklist

- [ ] Rule A added in **log** mode, published
- [ ] Rule A soaked ~24h; your own use confirmed well under 20/10min
- [ ] Rule A switched to **deny**, published
- [ ] Rule B created in Cloudflare, deployed
- [ ] Rule B verified with the curl loop from an expendable network
- [ ] Both rules confirmed present: `npx vercel firewall rules list` and the Cloudflare WAF list
- [ ] `admin-gate.md` §1 updated from "neither is configured"
