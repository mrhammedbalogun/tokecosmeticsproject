"""Rate limiting for the public auth endpoints.

WHY THIS MODULE EXISTS. DRF's `BaseThrottle.get_ident` (rest_framework/throttling.py)
falls back to the *entire* X-Forwarded-For chain joined into one string when
`NUM_PROXIES` is unset. Rotating a junk XFF prefix therefore mints a fresh bucket on
every request. Measured against `/auth/token/` before this module existed:

    no XFF                        -> first 429 at attempt 61
    fixed spoofed XFF             -> first 429 at attempt 61
    ROTATING spoofed XFF prefix   -> 0 x 429 in 80 attempts, every guess allowed

Forwarding XFF from the storefront BFF is NOT the fix and must not be attempted:
`NUM_PROXIES` is one global number, but direct-to-API puts the real client at
`addrs[-2]` and via-BFF at `addrs[-3]`. At 2 the BFF's header is ignored; at 3 a
direct attacker forges any client IP, which is worse than doing nothing.

TWO KEYS, because neither alone is sufficient:

* **IP key** (`CloudflareIdentMixin`) caps total VOLUME from one source. Volume is
  the axis that gets a sending domain blacklisted. It cannot cap per-account guessing,
  because every legitimate login arrives from a handful of Vercel egress IPs.
* **Email key** (`_EmailKeyedThrottle`) caps guesses per ACCOUNT and cannot be forged
  by any proxy hop, because it is read from the request body. It cannot cap volume,
  because an attacker rotates the address.

KNOWN RESIDUAL RISKS, recorded deliberately rather than papered over:

1. **Email-keyed throttling is a lockout vector.** `SimpleRateThrottle` counts every
   request before authentication runs, so junk POSTs carrying a known victim's address
   can keep that account rate-limited. Accepted while the user table is empty. The
   upgrade is failure-counting (count only failed auth, reset on success) and it must
   land BEFORE Plan-22 imports real customer addresses, at which point known victim
   emails exist and the lockout becomes targetable.
2. **Low-and-slow distributed credential stuffing is not stopped by this module.**
   Breadth-first stuffing gets a fresh email bucket per attempt, and the IP key cannot
   be tightened far because legitimate traffic shares the BFF's egress IPs. The answers
   are Turnstile on login/register and/or a signed BFF header letting Django trust a
   real client IP. Neither is in scope here.
3. `CF-Connecting-IP` is only trustworthy because the origin accepts nothing but
   Cloudflare (`infra/proxy/zz-api.conf`). If that ever stops being true, this becomes
   forgeable and the IP keys become worthless.
"""

import hashlib
import hmac

from django.conf import settings
from rest_framework import throttling


def client_ip(request) -> str:
    """The real client IP, ignoring X-Forwarded-For entirely.

    XFF is attacker-controlled on the direct-to-API path and DRF's own handling of it
    is what created the bypass this module exists to close. `CF-Connecting-IP` is set
    by Cloudflare and cannot be spoofed through it; REMOTE_ADDR is the honest fallback
    for local/dev and for any request that somehow reaches the origin directly.
    """
    cf = request.META.get("HTTP_CF_CONNECTING_IP")
    if cf and cf.strip():
        return cf.strip()
    return request.META.get("REMOTE_ADDR") or "unknown"


class CloudflareIdentMixin:
    """Replaces DRF's XFF-chain identity with a spoof-resistant one."""

    def get_ident(self, request):
        return client_ip(request)


class AnonRateThrottle(CloudflareIdentMixin, throttling.AnonRateThrottle):
    """Global anonymous throttle. Installed as a DEFAULT_THROTTLE_CLASS.

    Subclassing matters more than it looks: without this, every anonymous endpoint in
    the project keeps the XFF bypass even after the auth views are individually fixed.
    """


class UserRateThrottle(CloudflareIdentMixin, throttling.UserRateThrottle):
    """Global authenticated throttle; keyed on pk when authenticated, IP otherwise."""


class _EmailKeyedThrottle(CloudflareIdentMixin, throttling.SimpleRateThrottle):
    """Keys on the submitted email address, hashed.

    Falls back to the IP key when the field is missing or unusable. It must never
    return None: in DRF, a None cache key means "do not throttle at all", which an
    attacker discovers immediately by omitting the field.

    The address is hashed rather than embedded raw so that customer email addresses do
    not end up sitting in cache keys (and therefore in Redis, and in anything that
    dumps it).
    """

    email_field = "email"

    def get_cache_key(self, request, view):
        email = ""
        data = getattr(request, "data", None)
        if isinstance(data, dict):
            raw = data.get(self.email_field)
            if isinstance(raw, str):
                email = raw.strip().lower()
        if email:
            # KEYED hash, not a bare digest. An unkeyed hash of a low-entropy value is
            # not privacy: anyone with Redis read access confirms a guessed address by
            # hashing it. Keying on SECRET_KEY costs the same and actually delivers it.
            # blake2b over md5 also avoids hashlib.md5() raising on FIPS-enabled builds,
            # which would 500 every auth endpoint.
            digest = hmac.new(
                settings.SECRET_KEY.encode("utf-8"), email.encode("utf-8"), hashlib.blake2b
            ).hexdigest()[:32]
            ident = "e:" + digest
        else:
            ident = "i:" + self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class _IPKeyedThrottle(CloudflareIdentMixin, throttling.SimpleRateThrottle):
    """Scoped IP throttle that survives XFF rotation.

    CAVEAT that governs every rate below. Storefront auth traffic reaches Django from
    Vercel's egress addresses (the BFF calls the API server-side), so for those requests
    `CF-Connecting-IP` is Vercel's NAT address, not the customer's — one bucket shared by
    the whole shop. Only the direct-to-API path carries a real per-attacker address.

    One number therefore has to serve two populations at once, and it cannot serve both
    well. Rates here are set so they do NOT deny real customers, which means they are
    looser than a pure anti-abuse number would be. The real fix is to have the BFF forward
    the true client IP under a shared secret.

    CORRECTION (2026-07-28, Plan-16 Amendment 5). This docstring used to end by naming
    "the Cloudflare edge rule on the storefront's own /api/auth/*" as the control that
    sees real client addresses. That control does not exist and could not:
    next.tokecosmetics.com is a bare CNAME to vercel-dns-017.com and is NOT proxied
    through Cloudflare, so no Cloudflare rule on that hostname can ever fire. Nothing on
    the storefront path currently sees a real per-customer IP. The candidate is a Vercel
    Firewall rate-limit rule (available — the account is Pro); until it lands, the
    per-email keys carry the whole weight on the shared path. See memory
    project_tokecosmetics_real_client_ip_gap.

    SECOND CORRECTION (2026-07-28, Plan-16 Task 1/2 review). This docstring also used to
    end by claiming the caveat "does not bite" for the ADMIN throttles below, because
    "staff log in from a browser to the admin origin". THAT WAS FALSE, and it was false
    by this plan's own design: Task 5 specifies an admin login built like the
    storefront's, and the storefront's Server Function calls the API SERVER-SIDE
    (storefront/src/lib/auth-session.ts). Every legitimate staff login therefore arrives
    from the same Vercel egress address as every other — `admin_login_ip` is one bucket
    shared by the entire staff, exactly like `login_ip`.

    That made a request-counting 5/min cap on the admin login a free, total, indefinite
    staff lockout: `check_throttles()` runs in `initial()`, i.e. BEFORE
    `require_turnstile`, so five EMPTY JSON POSTs a minute — no Turnstile solved, no
    password guessed, no victim address needed — 429'd every staff login for as long as
    an anonymous stranger cared to keep sending them. The Turnstile gate going live in
    production does not help, because the junk is counted before it is refused.

    WHAT WAS DONE ABOUT IT, and why not simply a bigger number. A pure-IP VOLUME cap is
    the wrong shape for an endpoint whose entire legitimate population shares one
    address: any denial keyed on that address denies the victim by construction, so
    raising the rate only raises the price of the lockout. Three changes, in order of
    how much they matter:

    1. `AdminLoginIPThrottle` now COUNTS FAILURES (`_FailureCountingMixin`), not
       requests — Amendment 9's mechanism, which was applied to the email key only.
       Traffic that never reached a password check now costs the staff nothing at all,
       which is what makes the zero-cost lockout impossible rather than merely dearer.
    2. A successful staff login RESETS the IP bucket. Safe precisely because the bucket
       is shared: only a real staff member can produce a success, so the reset lands on
       the shared egress address and never on an attacker's own address, where no login
       will ever succeed.
    3. The volume cap that can actually tell staff and attacker apart belongs at the
       VERCEL FIREWALL, which is the only hop on this path that sees real client IPs.
       That is configuration, not code. It is NOT YET CONFIGURED; the rule to create
       is written out in docs/runbooks/admin-gate.md §1 so this stays a known gap
       rather than becoming another comment describing a control that does not exist.

    TWO RESIDUALS, stated plainly rather than argued away.

    (a) An attacker willing to spend real credential attempts (and, with the gate on, a
    solved Turnstile token each) can still fill the shared bucket and cause a rolling
    60-second staff lockout. Bounded, self-healing, cleared by any successful staff
    login, and loud — every one of those attempts is an ERROR-level Sentry event.

    (b) THE COST OF (1), NAMED: `/auth/admin-token/` now has NO request-volume cap in
    Django at all. Listing `throttle_classes` on a view REPLACES the global defaults,
    both classes here count failures, and so junk that never reaches a password check
    is unmetered — including junk carrying a bogus Turnstile token, each of which costs
    one outbound siteverify call to Cloudflare with a 5s timeout. That is accepted
    rather than fixed here, because it cannot be fixed here: ANY request-counting deny
    keyed on an address the whole staff shares is a lockout button, whatever number it
    is set to, and swapping a lockout for a load problem would be trading a security
    property for an availability one. Volume belongs at a hop that sees real client
    IPs, and BOTH such hops need a rule (runbook §1): Vercel's Firewall for the
    via-BFF path, and Cloudflare's for the direct-to-API path — api.tokecosmetics.com
    IS Cloudflare-proxied, which is the same fact that makes CF-Connecting-IP
    trustworthy above.
    """

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class LoginIPThrottle(_IPKeyedThrottle):
    """Volume cap on login. MUST be listed first in LoginView.throttle_classes.

    Why this exists: listing throttle_classes on a view REPLACES the global defaults
    rather than merging, so the email-keyed classes alone left /auth/token/ with no
    volume cap of any kind. Password spraying -- one attempt each against thousands of
    addresses -- never touches a per-email counter, so it was entirely unmetered.
    Verified against production before this class existed: 14 logins with 14 different
    emails returned 14 x 401 and never a 429.

    Listing it first also means it records before the email throttle reads request.data,
    which can raise ParseError on a malformed body.
    """

    scope = "login_ip"


# --- login -------------------------------------------------------------------
# Two windows: a burst rate that stops interactive guessing, and a slow rate that
# stops someone pacing themselves just under it.


class LoginBurstThrottle(_EmailKeyedThrottle):
    scope = "login_burst"


class LoginSustainedThrottle(_EmailKeyedThrottle):
    scope = "login_sustained"


# --- admin login -------------------------------------------------------------
# Separate scopes from the customer login on purpose, and far stricter (5/min per IP,
# 10/hour per address vs 30/min and 20/hour). Two reasons that survive scrutiny:
#
# * Legitimate staff login volume is near zero -- a handful of people, a few times a
#   day -- so a rate that would be absurd for the storefront is generous here.
# * Separate scopes also mean separate BUCKETS: an attack on the admin gate cannot
#   throttle the storefront's login, and vice versa. Sharing login_ip would have made
#   the admin endpoint a lever for denying customers their own logins.
#
# A THIRD REASON USED TO BE GIVEN AND IS WITHDRAWN: "a staff lockout is recoverable
# with root SSH, so brutal rates cost nothing". That treated a lockout as an
# inconvenience with a known fix. It is not — it is the outcome an attacker WANTS
# (nobody can watch the store, or reverse what they did, while it lasts), and pricing
# it at "one SSH session" is how both admin throttles ended up as denial-of-service
# levers an anonymous stranger could pull for free. Both now count FAILURES rather
# than requests; see `_FailureCountingMixin` and `_IPKeyedThrottle`.
#
# Turnstile sits in front of this too (Plan-16 Amendment 1), but Turnstile stops dumb
# bots, not a targeted attacker buying solver tokens -- these rates are what makes the
# targeted case slow, and mandatory TOTP (Amendment 2 / Task 3b) is what makes it
# pointless.


class _FailureCountingMixin:
    """Checked on the way in, written only when the caller says the attempt FAILED.

    The two throttles on the staff gate are the only ones in the project that do not
    count requests, and the reason is residual risk 1 in this module's docstring made
    acute by the admin's tiny user population. `SimpleRateThrottle` counts every
    request before authentication runs, so junk POSTs that never reach a password
    check filled the buckets:

    * at 10/hour per address, ten anonymous junk POSTs carrying the owner's (publicly
      known) address locked him out of his own store for an hour;
    * at 5/min per address-of-origin — one bucket for the whole staff, because the
      admin BFF calls this endpoint server-side — five EMPTY POSTs a minute locked out
      every staff member indefinitely, without even needing to know a victim's name.

    Both were zero-cost denial-of-service primitives, and at a staff population of one
    either takes the whole admin down. Counting failures instead means:

    * a request that never reached a password check cannot consume a bucket, so
      Turnstile-blocked junk and malformed bodies are free to the victim as well as
      costly to the attacker;
    * once the Turnstile gate is on, every countable failure costs a solved token;
    * a proven login clears the count (`reset`), so a staff member who fumbles their
      password is not one typo away from an afternoon of lockout;
    * an attacker already at the cap does not extend the lockout by keeping going —
      blocked requests never reach the recorder.

    THE CALLER DECIDES WHAT COUNTS, because only the caller knows how the attempt
    failed: `AdminLoginView` records exactly where it emits its `apps.security` ERROR
    line, so the alert and the counter can never disagree about what happened.
    Deliberately NOT applied to the customer login throttles — that change has to be
    weighed against Plan-22's imported-customer wave separately.
    """

    def throttle_success(self) -> bool:
        """Checked, not counted. Overriding this is the whole mechanism: DRF's
        `allow_request` still reads the bucket and still denies at the limit; it just
        no longer writes on the way through. Writes happen in `record_failure`."""
        return True

    def record_failure(self, request) -> None:
        """Count one failed credential attempt against this throttle's key."""
        if self.rate is None:
            return
        key = self.get_cache_key(request, view=None)
        if key is None:
            return
        now = self.timer()
        history = [t for t in self.cache.get(key, []) if t > now - self.duration]
        history.insert(0, now)
        self.cache.set(key, history, self.duration)

    def reset(self, request) -> None:
        """Clear the count for this key — call on a proven login."""
        key = self.get_cache_key(request, view=None)
        if key is not None:
            self.cache.delete(key)


class AdminLoginIPThrottle(_FailureCountingMixin, _IPKeyedThrottle):
    """Spray cap on staff login. MUST be listed first in AdminLoginView.throttle_classes
    -- same reasoning as LoginIPThrottle: it is the only cap that meters password
    spraying (one guess each against many addresses), and listing it first means it
    records before the email throttle touches request.data.

    Called a SPRAY cap and no longer a volume cap, deliberately. It counts failed
    credential attempts, so it does not meter volume at all any more — volume from
    traffic that never reaches a password check is now unmetered here on purpose, and
    is the Vercel Firewall's job. See `_IPKeyedThrottle` for the whole argument; the
    short version is that on an endpoint where the entire legitimate population shares
    one egress address, a volume cap IS a lockout button.
    """

    scope = "admin_login_ip"


class AdminLoginEmailThrottle(_FailureCountingMixin, _EmailKeyedThrottle):
    """Per-account cap on staff login (Plan-16 Amendment 9).

    The key an attacker cannot rotate away from: it is read from the request body, not
    from a header a proxy hop can rewrite. See `_FailureCountingMixin` for why it does
    not count requests.
    """

    scope = "admin_login_email"


# --- staff invite acceptance ---------------------------------------------------


class StaffInviteAcceptThrottle(_FailureCountingMixin, _IPKeyedThrottle):
    """The accept-invite bucket. **Checked AFTER the token is known to be invalid.**

    THIS INVERTS THE ORDER EVERY OTHER THROTTLE IN THE PROJECT USES, deliberately, and
    a reviewer should expect to find that suspicious — so here is the argument in full.

    DRF checks throttles in `APIView.initial()`, before the view body runs and therefore
    before the request has proved anything about itself. On most endpoints that is
    correct. On this one it is a denial button, for the same shared-egress reason that
    made the admin login throttles a staff lockout (see `_IPKeyedThrottle`): the admin
    app that will serve the accept page is a Next BFF calling this endpoint SERVER-side,
    so every legitimate acceptance will arrive from one Vercel egress address, shared
    with every attacker who uses the same page. And unlike login, the legitimate user
    gets exactly ONE shot: a new hire has a single invite, valid once. An attacker who
    fills the bucket with junk 429s the only person the endpoint exists to serve, and
    the recovery is the Owner noticing, revoking and re-inviting into the same jammed
    bucket.

    STATE OF THAT ASSUMPTION TODAY, per the standing rule about docstrings describing
    what actually exists: the admin app is Plan-16 Task 5 and IS NOT BUILT. Right now
    the only callers are tests and anything hitting the API directly, where
    `CF-Connecting-IP` is a real per-client address. The design is sized for the
    deployed shape rather than the current one deliberately — this is the same
    shared-egress fact that was asserted, wrongly, NOT to apply to the admin login, and
    cost a free staff lockout. If Task 5 ships a client-side call instead, revisit this
    and `_IPKeyedThrottle` together.

    So `StaffInviteAcceptView` does not list this class in `throttle_classes` at all.
    The order is: Turnstile -> hash the submitted token -> indexed lookup -> if the
    token is VALID, proceed and touch no bucket -> only on an INVALID token, check the
    bucket (denying at the cap) and then count the failure.

    WHY THAT IS SAFE RATHER THAN A BYPASS. The bypass condition is "hold a valid
    token", and the token is 256 bits from `secrets.token_urlsafe(32)`. An attacker
    cannot manufacture it; possessing one already means possessing the capability the
    bucket is protecting, at which point metering is pointless. The property this buys
    is stronger than the usual trade-off between availability and abuse: new-hire
    lockout becomes structurally impossible rather than merely unlikely.

    WHAT THE BUCKET IS ACTUALLY FOR, then. Not guess-rate — guessing is not a threat at
    this entropy. It caps the JUNK VOLUME a single origin can push through a public
    endpoint that does a Turnstile round-trip (5s timeout) and a database lookup per
    request. Rate today: `invite_accept_ip` = 10/hour, counted per FAILED token.

    The volume cap that could tell a new hire and an attacker apart would have to sit at
    a hop that sees real client IPs, i.e. the edge. **No such rule is configured for this
    endpoint, and none is specified** — unlike the admin login, where two edge rules are
    written out in `docs/runbooks/admin-gate.md` §1 and are also still unconfigured. That
    is a smaller gap than it sounds: this endpoint is only reachable in a useful way
    while an invite is outstanding, which is a few days a year.

    Inherits `_FailureCountingMixin` so `allow_request` reads without writing, and the
    view calls `record_failure` explicitly. Reset-on-success is NOT used: a successful
    accept never touches the bucket in the first place, so there is nothing to clear,
    and clearing it would hand an attacker holding one genuinely-consumed invite a way
    to wipe the counter.
    """

    scope = "invite_accept_ip"


# --- admin global search -------------------------------------------------------


class AdminSearchThrottle(CloudflareIdentMixin, throttling.UserRateThrottle):
    """Volume cap on `/api/v1/admin/search/`. Keyed on the USER, and request-counted.

    THAT COMBINATION LOOKS LIKE THE MISTAKE THIS MODULE SPENT TWO AMENDMENTS UNDOING, so
    the difference is worth stating rather than leaving to be rediscovered. Every
    request-counting cap that turned into a denial button on this branch —
    `admin_login_ip`, `admin_login_email`, `invite_accept_ip` — was keyed on something
    SHARED or FORGEABLE. The IP key is one bucket for the entire staff, because the admin
    BFF calls this API server-side from a Vercel egress address, so an anonymous stranger
    could fill it and lock every staff member out for free; the email key is read from an
    unauthenticated request body naming a publicly-known address.

    This key is `request.user.pk`, taken from a token that `AdminJWTAuthentication` has
    already validated. It cannot be forged and it is not shared, so the only person a
    caller can throttle is themselves, for a minute. Nobody else's search is affected by
    anybody else's typing.

    So it counts REQUESTS, deliberately, and must keep doing so. There is no failure to
    count here — a search either matches or does not — and the cap's job is not to slow
    down guessing but to stop a ten-results-per-type endpoint being driven in a loop until
    it has produced the whole customer table. Converting this to a failure-counting
    throttle would leave it with no volume cap at all, which is exactly the property the
    per-type cap exists to prevent.

    60/min is generous: it is a topbar box a human types into, and the admin app debounces.
    """

    scope = "admin_search"


# --- registration ------------------------------------------------------------
# The IP throttle is the one that matters. RegisterView mails the SUBMITTED address,
# so an unmetered endpoint is a spam cannon pointed at strangers from our own domain,
# and the cost is mg.tokecosmetics.com getting blacklisted -- which would silently
# break every order confirmation the store sends. An email key alone does NOT cap this,
# because the attacker rotates the recipient.


class RegisterIPThrottle(_IPKeyedThrottle):
    scope = "register_ip"


class RegisterEmailThrottle(_EmailKeyedThrottle):
    scope = "register_email"


# --- password reset ----------------------------------------------------------
# Keying on the target email is the only key that protects the victim's inbox; the IP
# key caps total outbound volume the same way it does for registration.


class PasswordResetEmailThrottle(_EmailKeyedThrottle):
    scope = "password_reset_email"


class PasswordResetIPThrottle(_IPKeyedThrottle):
    scope = "password_reset_ip"


class ScopedRateThrottle(CloudflareIdentMixin, throttling.ScopedRateThrottle):
    """Drop-in for DRF's ScopedRateThrottle with the XFF bypass closed.

    Swapping DEFAULT_THROTTLE_CLASSES does NOT cover views that set throttle_classes
    themselves -- search, carts and newsletter each pin stock ScopedRateThrottle, so they
    kept the unfixed get_ident. Newsletter is the sharpest: nominally 5/min, unbounded
    with a rotating XFF, and every request writes a NewsletterSubscriber row.
    """
