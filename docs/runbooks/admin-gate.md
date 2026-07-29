# Runbook — the staff login gate (`/auth/admin-token/`)

Operational companion to `backend/apps/accounts/throttling.py`, `views.py` and
`turnstile.py`. Everything here is a thing an operator does, not a thing the code
does.

## 1. OUTSTANDING — two edge rate-limit rules

**Status: neither is configured. This is the part of Plan-16's admin rate limiting
that cannot live in the repository, and it is the part that supplies the volume cap
Django deliberately no longer has.**

### Why it cannot be done in Django

The admin app's login is a Server Function that calls the API **server-side** (the
same shape as `storefront/src/lib/auth-session.ts`). Every legitimate staff login
therefore reaches Django from a Vercel egress address, and so does any attacker who
uses the admin login page rather than hitting the API directly. Django sees one
address for both populations, so any *volume* cap keyed on it denies the staff by
construction — raising the number only raises the price of the lockout, it does not
remove it.

Both Django throttles on this endpoint therefore count **failed credential attempts**
rather than requests. The consequence, stated so nobody is surprised by it:
`/auth/admin-token/` has **no request-volume cap in Django at all**. Junk that never
reaches a password check is unmetered, including junk carrying a bogus Turnstile
token — each of which costs one outbound siteverify call with a 5s timeout. That is
what these two rules are for.

### Rule A — Vercel Firewall (covers the via-BFF path)

The account is **Pro**, so Firewall rate-limit rules are available.

- Project: the **admin** Vercel project (and, separately, the storefront project —
  see `project_tokecosmetics_real_client_ip_gap`; that one is not Plan-16 work).
- Match: request path is the admin login Server Function route (`/login`, POST).
- Key: client IP.
- Limit: start at **20 requests / 10 minutes**, action `deny`. Staff volume is a
  handful of logins a day, so this is generous; it is a volume cap, not a guess cap.

### Rule B — Cloudflare (covers the direct-to-API path)

`api.tokecosmetics.com` is Cloudflare-proxied — the same fact that makes
`CF-Connecting-IP` trustworthy in `throttling.client_ip`. Rule A does nothing for a
caller who skips the admin app and posts straight to the API, which is what any
scripted attacker will do.

- Zone: `tokecosmetics.com`, hostname `api.tokecosmetics.com`.
- Match: `http.request.uri.path eq "/api/v1/auth/admin-token/"`.
- Key: client IP (Cloudflare's default characteristic).
- Limit: **20 requests / 10 minutes**, action `block`.

Leave the Django throttles in place under both. They cap *guesses* per account and
per origin; these cap *volume*. They are not substitutes for each other.

### What is already handled in code, so you do not double-solve it

`admin_login_ip` and `admin_login_email` both count **failed credential attempts**,
not requests. Empty POSTs, malformed bodies and Turnstile-blocked bots consume
nothing, and a successful staff login clears both buckets. An anonymous party can no
longer deny staff access at zero cost. What remains — an attacker spending real
credential attempts (and, with Turnstile on, a solved token each) to keep the shared
bucket full — is bounded to 60 seconds, self-healing, cleared by any successful staff
login, and raises an ERROR-level Sentry event per attempt. The edge rules are what
stop it reaching Django at all.

## 2. Break-glass — Cloudflare / Turnstile siteverify outage

`require_turnstile` fails **closed**, so a siteverify outage blocks staff login.
During such an outage customer login, register and checkout sign-in are already down;
the revenue path is dark regardless.

Drop the **admin** gate only (leaves the customer gate as it is):

```
ssh tokecosmetics 'sed -i "/^TURNSTILE_ADMIN_SECRET=/d" /opt/tokecosmetics/.env.prod && cd /opt/tokecosmetics/repo && docker compose -p tokecosmetics --env-file /opt/tokecosmetics/.env.prod -f infra/docker-compose.prod.yml up -d'
```

Note this only works while `TURNSTILE_ADMIN_SECRET` is set to its **own** value. If
the admin gate is still falling back to `TURNSTILE_SECRET` (see
`turnstile.admin_turnstile_secret`), deleting `TURNSTILE_ADMIN_SECRET` changes
nothing and you must drop `TURNSTILE_SECRET` instead — which opens the customer gate
too:

```
ssh tokecosmetics 'sed -i "/^TURNSTILE_SECRET=/d" /opt/tokecosmetics/.env.prod && cd /opt/tokecosmetics/repo && docker compose -p tokecosmetics --env-file /opt/tokecosmetics/.env.prod -f infra/docker-compose.prod.yml up -d'
```

**Put the secret back the moment siteverify recovers.** With the gate off, every
failed credential attempt is free again, which is precisely the condition the
failure-counting throttles were sized against.

## 3. Break-glass — clearing a throttle bucket

Only needed if staff are genuinely locked out (they should not be — see §1). The
cache is Redis in production; keys are `throttle_admin_login_ip_*` and
`throttle_admin_login_email_*`.

```
ssh tokecosmetics 'docker exec -i $(docker ps -qf name=redis) redis-cli --scan --pattern "*throttle_admin_login*" | xargs -r docker exec -i $(docker ps -qf name=redis) redis-cli DEL'
```

Cheaper alternative that needs no SSH: **a successful staff login from the same
address clears both buckets.** If any staff member can still get in, that is the fix.

## 4. Alerting — what should reach Sentry

Everything below logs to `apps.security` at ERROR, which the Sentry logging
integration turns into events:

- `admin login failed for <email> (<ExceptionClass>)` — one per refused attempt on
  the staff gate, including Turnstile blocks and customers trying the admin door.
- `throttled: /api/v1/auth/admin-token/ (retry in Ns)` — someone reached the cap.
  Opt-in per view (`AdminLoginView.log_throttling_at_error`); ordinary customer 429s
  stay at WARNING deliberately, so they do not bury this.
- `staff account <email> is in group(s) that grant nothing: <names>` — a role Group
  was renamed or deleted in the Django admin and somebody has silently lost every
  scope. `accounts.W001` reports the same condition at deploy time.

## 5. Staff invites

An outstanding invite is a **live staff-creation capability**: whoever holds the token
in that email can mint an `is_staff` account in the named role. Treat a mis-sent invite
the way you would treat a leaked password.

- **Mis-sent one?** Revoke it: `POST /api/v1/admin/staff/invites/<id>/revoke/` (Owner
  scope, and the Plan-16 Task 7 staff page will put a button on it). Revocation is
  checked inside the same atomic claim as expiry and single-use, so it cannot lose a
  race with an acceptance already in flight.
- **"Resend" is revoke + a new invite.** There is deliberately no token refresh: a
  refreshed token in place would leave the old one working for whoever already has it.
  The create endpoint refuses a second outstanding invite for the same address for the
  same reason.
- **TTL is 72 hours**, `STAFF_INVITE_TTL_HOURS` in the prod env. Lowering it costs
  nothing operationally.
- **Accepting does not produce an admin session.** It returns a short-lived *preauth*
  token which, until Task 3b lands, opens nothing at all. The account exists, is
  `is_staff`, is in its group, and reaches nothing. That is intended.
- **Accepting always sets a new password**, including when the address already had a
  customer account (which is promoted rather than duplicated). No customer-era password
  ever becomes a staff password.
- **Clearing the accept throttle bucket** (only invalid tokens count toward it, so
  legitimate users never hit it):

```
ssh tokecosmetics 'docker exec -i $(docker ps -qf name=redis) redis-cli --scan --pattern "*throttle_invite_accept_ip*" | xargs -r docker exec -i $(docker ps -qf name=redis) redis-cli DEL'
```

Security lines to expect in `apps.security`: `staff invite created ...` (INFO),
`staff invite revoked ...` (INFO), `staff invite accepted ...` (WARNING), and
`staff invite accept failed: <reason> token from <ip>` (ERROR — a Sentry event; the
`expired` reason logs at INFO instead, because that is a real new hire who waited too
long).

## 6. OUTSTANDING — lost-device TOTP recovery is a `manage.py` command, not an endpoint

**Status: nothing to run yet. TOTP itself is Plan-16 Task 3b and has not been built.**
This entry exists now so that whoever builds it does not solve the problem the cheap
way.

A staff member who loses their phone must NOT be able to reset their own TOTP over the
web. Any such endpoint becomes the cheapest door into the admin — it is, by
construction, a way to turn "I control this inbox" or "I answer these questions" back
into full administrator access, which is exactly the fence TOTP was added to build
(Amendment 1: the catastrophic scenario is admin compromise → attacker edits the payout
bank account → every bank-transfer order pays them).

Recovery is therefore an operator action requiring root SSH:

```
ssh tokecosmetics 'cd /opt/tokecosmetics/repo && docker compose -p tokecosmetics --env-file /opt/tokecosmetics/.env.prod -f infra/docker-compose.prod.yml exec api python manage.py reset_staff_totp <email>'
```

Task 3b must ship that command. The staff population is ~1 and the store owner holds
the SSH key, so the operational cost is a few minutes and the security saving is an
entire attack surface.

## 7. Staff role groups

Roles are Django Groups named exactly `Owner`, `Manager`, `Support`, `Content`
(`accounts/migrations/0003_seed_admin_roles.py`). **Do not rename them in the Django
admin.** `apps/accounts/rbac.py` grants scopes by name and fails closed on a name it
does not recognise, so a rename revokes everything from everyone in that group. The
owner will not notice, because superusers short-circuit to every scope.

If it happens: rename the group back. `manage.py check` reports it as
`accounts.W001`, and it is logged at ERROR the first time an affected staff member
makes a request.
