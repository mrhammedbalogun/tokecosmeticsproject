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
    the storefront path currently sees a real per-customer IP. The candidates are a
    Vercel Firewall rate-limit rule (plan-tier dependent) or the signed-BFF-header work;
    until one lands, the per-email keys carry the whole weight on the shared path. See
    memory project_tokecosmetics_real_client_ip_gap.

    The ADMIN login throttles below are the one place this caveat does not bite: staff
    log in from a browser to the admin origin, and there is no legitimate shared-egress
    population to protect, so those rates can be set to what abuse deserves.
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
# 10/hour per address vs 30/min and 20/hour). Three reasons this costs nothing:
#
# * Legitimate staff login volume is near zero -- a handful of people, a few times a
#   day -- so a rate that would be absurd for the storefront is generous here.
# * A staff lockout is recoverable: root SSH access to the box can clear the cache or
#   the rate. A customer lockout is not recoverable and is a support call.
# * Separate scopes also mean separate BUCKETS: an attack on the admin gate cannot
#   throttle the storefront's login, and vice versa. Sharing login_ip would have made
#   the admin endpoint a lever for denying customers their own logins.
#
# Turnstile sits in front of this too (Plan-16 Amendment 1), but Turnstile stops dumb
# bots, not a targeted attacker buying solver tokens -- these rates are what makes the
# targeted case slow, and mandatory TOTP (Amendment 2 / Task 3b) is what makes it
# pointless.


class AdminLoginIPThrottle(_IPKeyedThrottle):
    """Volume cap on staff login. MUST be listed first in AdminLoginView.throttle_classes
    -- same reasoning as LoginIPThrottle: it is the only cap that meters password
    spraying (one guess each against many addresses), and listing it first means it
    records before the email throttle touches request.data."""

    scope = "admin_login_ip"


class AdminLoginEmailThrottle(_EmailKeyedThrottle):
    """Per-account cap on staff login, counting FAILURES rather than requests.

    This is the one throttle in the project that does not count requests, and the
    reason is residual risk 1 in this module's docstring, made acute by the admin's
    tiny user population. `SimpleRateThrottle` counts every request before
    authentication runs, so with request-counting at 10/hour, ten anonymous junk
    POSTs carrying the owner's (publicly known) address locked him out of his own
    store for an hour — zero cost to the attacker, recoverable only by SSHing into
    the box to clear Redis. That is a denial-of-service primitive handed out for
    free, and at a staff population of one it takes the whole admin down.

    Counting failures instead means:

    * a request that never reached a password check cannot consume the bucket, so
      Turnstile-blocked junk is free to the victim as well as costly to the attacker;
    * once the Turnstile gate is on, every countable failure costs a solved token;
    * a proven login clears the count, so a staff member who fumbles their password
      is not one typo away from an afternoon of lockout;
    * an attacker already at the cap does not extend their own lockout by keeping
      going — blocked requests never reach the recorder — which is fine, because the
      IP throttle is the volume cap and it still counts every request.

    The caller decides what counts, because only the caller knows how the attempt
    failed: `AdminLoginView` records exactly where it emits its `apps.security` ERROR
    line, so the alert and the counter can never disagree about what happened.
    Deliberately NOT applied to the customer login throttles — that change has to be
    weighed against Plan-22's imported-customer wave separately.
    """

    scope = "admin_login_email"

    def throttle_success(self) -> bool:
        """Checked, not counted. Overriding this is the whole mechanism: DRF's
        `allow_request` still reads the bucket and still denies at the limit; it just
        no longer writes on the way through. Writes happen in `record_failure`."""
        return True

    def record_failure(self, request) -> None:
        """Count one failed credential attempt against the submitted address."""
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
        """Clear the count for the submitted address — call on a proven login."""
        key = self.get_cache_key(request, view=None)
        if key is not None:
            self.cache.delete(key)


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
