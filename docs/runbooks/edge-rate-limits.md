# The two edge rate-limit rules — complete guide

**Status as of 2026-07-30:**

| rule | state |
|---|---|
| **A — Vercel Firewall** | **DONE and enforcing.** `Admin login volume cap`, `rule_admin_login_volume_cap_fIQ5Tx`, 20 req / 600 s per IP on `POST /login`, action `deny`, no persistent duration. |
| **B — Cloudflare** | **Not configured, and constrained by the Free plan — see §Rule B.** |

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

> **DONE 2026-07-30.** Live and enforcing; the steps below are kept as the record of how,
> and as the procedure for changing or re-creating it.
>
> **The 24h log soak in Step A3 was deliberately compressed**, and the reasoning is worth
> keeping because it is the argument for when a soak is and is not load-bearing. A soak
> answers one question: *does legitimate traffic approach the limit?* Here that was
> answerable without waiting —
>
> - only `POST /login` counts; page loads are GET and are excluded by the `method`
>   condition, verified on the live rule;
> - one form submit is one POST, so a login costs 1 against a budget of 20;
> - Django's own `admin_login_ip` cuts in at **5 failed attempts per minute**, so a
>   legitimate person is stopped by the application long before 20 requests in 10 minutes;
> - real staff volume is a handful of logins a day.
>
> The margin is roughly twentyfold, and recovery is one command because the rule carries
> no `--duration`. A soak buys evidence; when the arithmetic is unambiguous and reversal
> is instant, waiting a day buys nothing. **Soak anyway** for any rule matching customer
> traffic, anything using a `sub`/`re` operator, or anything keyed on JA4 or user agent —
> there the traffic mix genuinely is not predictable from first principles.

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

> **OPTIONAL as of 2026-07-30, and read this before deciding to do it.**
>
> Rule B was originally the control that closed the volume gap. The **BFF shared-secret
> gate** (`backend-v0.4.1`) closed it instead, and closed it better: junk without the
> header is now refused by a constant-time string compare *before* any outbound siteverify
> call. The exposure is unreachable rather than throttled.
>
> **What is left for Rule B** is keeping garbage off the origin. That still has value —
> a request Django rejects cheaply has already consumed a Cloudflare→Apache connection and
> VPS CPU on the box that also serves the **live legacy WordPress stores**. But it is now
> defence in depth, not the thing standing between you and a problem.
>
> Ten minutes of dashboard work. If you skip it, nothing is broken.

**Covers:** a caller who ignores the admin app and posts straight to
`api.tokecosmetics.com`. A script has no reason to go through the UI, so this is the path
Rule A cannot see.

### First: what the Free plan actually allows

Rate limiting rules are **not** a paid-only feature — the Free plan includes **one** rule.
But the Free tier is narrow enough that the rule has to be redesigned, not merely
retyped. Per Cloudflare's
[plan availability table](https://developers.cloudflare.com/waf/rate-limiting-rules/):

| | Free | Pro | Business |
|---|---|---|---|
| rules per zone | **1** | 2 | 5 |
| counting period | **10 s only** | up to 1 min | up to 10 min |
| mitigation timeout | **10 s** | up to 1 h | up to 1 day |
| counting characteristics | IP only | IP only | IP, headers, path, ASN… |
| expression fields | **Path, Verified Bot** | + Host, URI, Query | + headers, bot data |

Three consequences, and each one changes the rule:

1. **No `Host` field.** The expression from the original spec cannot be written — match on
   **path alone**. In practice that is fine: `/api/v1/auth/admin-token/` is served only by
   `api.tokecosmetics.com`, and any other proxied host in the zone would 404 that path
   anyway, so rate-limiting it there costs nothing.
2. **10-second period, 10-second mitigation.** The specified 20-per-10-minutes cannot be
   expressed. The honest translation is a much weaker guarantee — see below.
3. **One rule for the whole zone.** A budget, and it must be spent on the **admin** path.
   See the warning below before considering anything else.

### ⚠ Spend the single rule on the ADMIN path only

An earlier draft of this guide said to OR the customer login path into the same rule,
since only one rule exists and it seemed wasteful not to cover both doors. **That would
have broken customer logins, and the reasoning is worth understanding because it is the
same trap in a new place.**

Customer logins do **not** arrive from customer IPs. `storefront/src/lib/auth-session.ts`
calls `/auth/token/` **server-side**, exactly like the admin app does — verified: the
storefront's `apiFetch` is documented "Server Components and Route Handlers ONLY". So
every customer login on the site reaches Cloudflare from one of Vercel's handful of egress
addresses.

A 5-requests-per-10-seconds **per-IP** rule covering `/auth/token/` therefore meters *all
customers collectively*. Six people logging in during the same ten seconds — an ordinary
evening — and the sixth is blocked. That is the shared-bucket lockout the Django
failure-counting rewrite removed, reinstalled at the edge and pointed at paying customers
instead of staff.

The admin path is safe from the same effect only because its legitimate volume is
genuinely near zero: a handful of staff logins a day never approaches 5 in 10 seconds.

**So: admin path only. Do not add `/auth/token/`.** If customer-login rate limiting is
ever wanted it needs real client IPs, which means a Vercel Firewall rule on the storefront
project — see `project_tokecosmetics_real_client_ip_gap`.

### Step B1 — create the rule

1. [dash.cloudflare.com](https://dash.cloudflare.com) → zone **tokecosmetics.com**
2. **Security → WAF → Rate limiting rules → Create rule**
3. Name: `admin-token volume cap`
4. **If incoming requests match** → *Edit expression*, and paste exactly:

   ```
   http.request.uri.path eq "/api/v1/auth/admin-token/"
   ```

   One path, matched with `eq`. Never a prefix — see below.
5. **Rate limiting characteristics:** IP
6. **Period:** 10 seconds · **Requests:** 5
7. **Then take action:** Block · **Duration:** 10 seconds
8. **Deploy**

Five requests per 10 seconds per IP. A staff login sends one. It caps a flood at roughly
30/min sustained instead of unbounded.

### Be honest about what this buys

A 10-second window with a 10-second timeout is a **flood brake, not a volume cap**. An
attacker pacing at 5 requests per 10 seconds is never blocked.

That used to be the objection to it. Since the BFF gate shipped it is no longer much of
one, because a flood brake is exactly the right shape for what remains: bursts are what
cost Apache connections, and bursts are what a short window stops. Paced low-volume junk
now dies on a string compare in Django and never reaches Turnstile at all.

The layers behind it, unchanged: the BFF secret, Turnstile, failed-credential counting per
account and per origin, TOTP, and the audience claim. This rule is the outermost of six.

### Verify it

Run this from an expendable network — mobile data, not the machine you administer the
store from. It is safe: with the BFF gate live these requests are refused by a string
compare and cost Django nothing.

```bash
for i in $(seq 1 12); do
  curl -s -o /dev/null -w "%{http_code} " --max-time 10 \
    -X POST https://api.tokecosmetics.com/api/v1/auth/admin-token/ \
    -H 'Content-Type: application/json' -d '{"email":"probe@example.com","password":"x"}'
done; echo
```

Expect a run of `403` (the BFF gate refusing, correctly) turning into `429` or a
Cloudflare block page once you pass 5 within a 10-second window. Wait 10 seconds and it
clears.

Then confirm your own admin login still works — the rule keys on IP, and yours is not the
one being metered.

### If the Free rule is too weak — the options, and why both are now moot

**Option 1 — origin-level rate limiting. NOT the drop-in it looks like. Read this before
attempting it.**

An earlier draft of this file recommended an nginx `limit_req` block as a quick free win.
**That was wrong, and the investigation on 2026-07-30 is worth recording** because every
step of it is a trap someone else would walk into.

*a. nginx is not in the request path.* `ss -lntp` shows **`httpd` (Apache)** on 80 and 443;
nginx is installed but `inactive`. `api.tokecosmetics.com` is an Apache vhost
(`infra/proxy/zz-api.conf`) proxying to `127.0.0.1:8001`. The "nginx reverse-proxy on
2002–2006" in the project notes is Webuzo's own internal arrangement, not this path.

*b. Apache cannot see the real client IP here.* Every request arrives from a Cloudflare
edge address, and `mod_remoteip` is deliberately **not loaded** — the vhost says so in a
comment. So any Apache rate limit keyed on client IP would meter **Cloudflare edge nodes**,
throttling every legitimate visitor funnelled through whichever node tripped first.

*c. Loading `mod_remoteip` to fix (b) would take the API down.* The vhost's **origin lock**
is a `Require ip` allowlist of Cloudflare's ranges. Apache's docs are explicit: the
overridden useragent IP "is then used for the `mod_authz_host` `Require ip` feature". Load
`mod_remoteip` and that allowlist starts testing the *visitor's* address against
Cloudflare's ranges — which never matches. **403 on every API request.** The origin lock
would have to be rewritten in the same change, on the same server that serves the live
WordPress stores.

The modules are present but unloaded (`mod_remoteip.so`, `mod_evasive20.so`,
`mod_security2.so`), so this is possible — it is just not small, and its blast radius
includes the WordPress stores on the shared Apache. `mod_evasive` is also a blunt fit:
its counters are per-worker-process and its directives are server/vhost scoped, not
per-path.

**The clean version, if origin rate limiting is wanted: an nginx container inside the
Docker stack.** It sidesteps every problem above — Apache's vhost keeps its origin lock
untouched and only its `ProxyPass` target moves; the WordPress stores are unaffected; the
config is version-controlled and ships through the existing tag pipeline; and
`CF-Connecting-IP` is trustworthy as a header precisely *because* the origin lock
guarantees only Cloudflare reaches Apache:

```nginx
limit_req_zone $http_cf_connecting_ip zone=adminlogin:10m rate=2r/m;

server {
    listen 8002;
    location = /api/v1/auth/admin-token/ {
        limit_req zone=adminlogin burst=5 nodelay;
        limit_req_status 429;
        proxy_pass http://web:8000;
    }
    location / { proxy_pass http://web:8000; }
}
```

This is a **new component in the production request path** — a mini-plan (compose service,
vhost change, local verification, deploy, rollback rehearsal), not a config tweak. Worth
doing properly if the API ever moves off the shared Webuzo box. Not attempted here.

**Option 2 — Cloudflare Pro ($20/mo).** Buys 2 rules, 1-minute periods, 1-hour mitigation
and the `Host` field, so both login doors get their own properly-scoped rule. Reasonable
if you would rather not touch nginx, but note it is a recurring cost for something Option 1
does better for free.

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

- [x] Rule A added in **log** mode, published *(2026-07-30)*
- [x] Rule A scope verified on the live rule — `path eq /login`, `method eq POST`, no persistent duration
- [x] Rule A switched to **deny**, published; `/login` and `/accept-invite` confirmed still 200
- [x] **BFF shared-secret gate shipped** (`backend-v0.4.1`) — this is what actually closed
      the gap; Rule B became optional
- [ ] Rule B created in Cloudflare — **admin path only**, 5 req / 10 s, block 10 s
- [ ] Rule B verified with the curl loop from an expendable network
- [ ] Own admin login confirmed still working afterwards
- [x] `admin-gate.md` §1 updated — Rule A no longer outstanding

---

## Superseded in part — the BFF shared-secret gate (2026-07-30)

Fable 5 was consulted on Rule B and rejected all three options in favour of something
cheaper that this file had listed and walked past. It was right, and the reasoning
generalises:

**`/auth/admin-token/` and `/admin/staff/invites/accept/` have exactly ONE legitimate
caller** — the admin BFF. Verified: `admin/src/lib/admin-session.ts` is the only call site
in either app. An endpoint with a single known server-side caller should not be a public
endpoint you then try to rate-limit; it should require proof of coming from that caller.

`ADMIN_BFF_SECRET` + the `X-Admin-BFF-Secret` header now does that, checked with
`hmac.compare_digest` **before** `require_turnstile`. The exposure this whole file was
about — unmetered junk each costing an outbound siteverify call — is now *unreachable*
rather than throttled. Shipped in `backend-v0.4.1`; see `apps/accounts/bff.py` and
`admin-gate.md` §1b.

**What that changes here:**

- **Rule A stays.** It caps volume on the admin app's own `/login` route, which the
  backend gate cannot see.
- **Rule B is now optional.** Its job shrinks to keeping garbage off the origin — worth
  having, since junk still consumes Apache connections and CPU shared with the live
  WordPress stores, but no longer load-bearing.
- **The Free-plan rule is the right size for that reduced job.** A 10-second flood brake
  is the correct shape for burst protection; the long-window volume cap this file kept
  reaching for is no longer needed by anything.
- **Option 1 (origin rate limiting) is off the table** for the foreseeable future. It was
  already the riskiest option; it is now solving a problem that no longer exists.

**Two corrections to this file's own threat model, from the same review:**

1. **The 5-second siteverify figure is a TIMEOUT, not a cost.** A bogus token is rejected
   in ~100–300 ms. The realistic per-request amplification was always modest.
2. **"43,000 requests/day unblocked" was a scary number about a non-threat.** 0.5 req/s of
   quarter-second calls is noise. Worker exhaustion is a burst phenomenon, and bursts are
   exactly what a short window brakes.

Also unstated here previously: Cloudflare Free's automatic L7 DDoS mitigation sits in
front of `api.*` regardless of any rule.
