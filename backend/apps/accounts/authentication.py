"""Staff-only JWT authentication.

WHY THIS MODULE EXISTS. Until it did, `/auth/token/` (customer login) and
`/auth/admin-token/` (staff login) minted tokens that were byte-for-byte
interchangeable: same signing key, same claims, same `user_id`. Every protection
on the admin gate — the Turnstile challenge, the 5/min IP cap, the 10/hour
per-account cap — could therefore be skipped by brute-forcing a staff password at
the *customer* door and carrying the resulting token over. Measured before this
existed: a staff token obtained from `/auth/token/` returned 200 on
`/auth/admin-me/`.

The fix is an audience claim minted only by the admin login, plus an
authentication class that refuses tokens without it.

WHY THE CHECK LIVES IN AUTHENTICATION RATHER THAN IN A PERMISSION CLASS. The two
fail in opposite directions when someone forgets to wire one up:

* Authentication forgotten -> the request is *unauthenticated*, `request.user` is
  anonymous, and even a view with no permission class at all answers 401. Closed.
* Permission forgotten -> the request is authenticated as a real staff-shaped user
  and the view runs. Open.

Since the whole class of bug this guards against is "a future admin endpoint was
added and something was left off", the check belongs on the side whose omission is
harmless. `apps/accounts/tests/test_admin_surface_guard.py` enforces that admin
views list this class and ONLY this class.

WHY *ONLY*, PRECISELY. Task 1 justified the equality assertion with "DRF takes the
first authenticator that returns a user", which is true but incomplete, and the
incomplete half matters. Measured by mutation during Task 2:

* `[JWTAuthentication, AdminJWTAuthentication]` — the stock class runs first, accepts
  a customer token, returns a user, and DRF stops. **The bypass, in full.**
* `[AdminJWTAuthentication, JWTAuthentication]` — this class runs first and RAISES.
  `Request._authenticate` catches `APIException`, marks the request unauthenticated
  and RE-RAISES rather than trying the next authenticator, so the stock class never
  runs and the customer token is still refused. Not a bypass.

The equality assertion is right either way and stays as it is: the safe ordering is
safe by accident of which class raises first, the list is a place a reviewer's eye
slides over, and "correct only in one of its two orderings" is not a property worth
depending on. But do not repeat the shorter claim — someone will check it, find the
second case, and conclude the guard is cargo cult.

WHY THE PERMISSION LAYER STILL CHECKS `is_staff`. A claim is a snapshot taken at
login and it outlives revocation — a staff account demoted at 10:00 still holds a
token asserting `toke-admin` until it expires. `HasAdminScope` / `IsAdminUser` read
`is_staff` and group membership from the database on every request, which is what
makes a revocation take effect immediately. Neither fence replaces the other: this
one answers "was this token issued for the admin app?", that one answers "is this
person still staff, right now?".

WHY THE CLAIM IS NAMED `toke_aud` AND NOT `aud`. `aud` is a reserved JWT claim that
SimpleJWT owns: `TokenBackend.encode` overwrites it unconditionally whenever
`SIMPLE_JWT["AUDIENCE"]` is set, and `decode` then verifies it. Verified against
this version — encoding a payload carrying `aud="toke-admin"` through a backend
built with `audience="some-other-audience"` produced `aud="some-other-audience"`,
silently. Two failure modes follow, both silent and both bad: setting AUDIENCE to
anything locks every staff member out, and setting it to our own value would stamp
the claim onto CUSTOMER tokens too and reopen the bypass completely. A private,
non-reserved claim name is not subject to either.
"""
from datetime import timedelta

from django.utils.translation import gettext_lazy as _
from drf_spectacular.contrib.rest_framework_simplejwt import SimpleJWTScheme
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

# Private claim name (see the module docstring for why it is not `aud`).
ADMIN_AUDIENCE_CLAIM = "toke_aud"
ADMIN_AUDIENCE = "toke-admin"

# The BOOTSTRAP audience. Same claim, different value, so the equality check in
# `AdminJWTAuthentication` rejects it without needing to know it exists.
#
# WHY IT EXISTS. Amendment 6's invariant is that `toke-admin` means the FULL admin
# ceremony completed — password, Turnstile and TOTP — and is minted nowhere else. The
# two ways a person arrives at this system (accepting a staff invite; logging in at
# `/auth/admin-token/`) complete only the first two steps, so neither can mint one.
# Bootstrap is not an exception to the invariant, because an exception is where the hole
# grows. What both mint instead is this: a short-lived token that says "this person has
# proved a password and a human check, and now owes a TOTP code".
#
# IT HAS EXACTLY FOUR DESTINATIONS — TOTP enrol, second-factor confirm, recovery-code
# verification, and the email-code send — and `tests/test_admin_surface_guard.py`
# asserts that set EXACTLY against the live URLconf, in both directions. A fifth
# destination is a deliberate, reviewed edit; it cannot be a side effect of adding a
# view.
#
# ONE BOOTSTRAP PATH, NOT TWO: `/auth/admin-token/` returns this token whether or not
# the caller has a confirmed enrolment. The alternative — a full session for the
# enrolled and a preauth for the rest — would mean two code paths that mint credentials,
# and the second one is where the hole grows.
ADMIN_PREAUTH_AUDIENCE = "toke-admin-preauth"

# THE DELIVERY-PARTNER AUDIENCE (Plan-39). Same claim, third value. A partner login —
# an external courier maintaining their own rate card — mints tokens carrying this,
# and `PartnerJWTAuthentication` is the only class that accepts it, so the credential
# opens exactly the `/api/v1/partner/` surface: the equality checks on the other two
# classes refuse it without needing to know it exists, same as preauth.
#
# No TOTP ceremony here, deliberately (Hammed's ruling, plan-39): the surface behind
# it is one rate table belonging to the holder. The compensating controls are the
# login throttles (partner_login_ip / partner_login_email), the DB-read
# `IsDeliveryPartner` permission (revocation is immediate, like `is_staff`), and the
# staff kill-switch on the DeliveryPartner row.
PARTNER_AUDIENCE = "toke-partner"

# Long enough to scan a QR code and type a six-digit code, short enough that a preauth
# token left in a browser history or a proxy log is worthless by the time anyone finds
# it. Not env-tunable: there is no operational reason to lengthen it, and the only
# effect of doing so would be to widen that window.
PREAUTH_TOKEN_LIFETIME = timedelta(minutes=10)


def mint_preauth_token(user) -> str:
    """A bootstrap credential for `user`. Never an admin-audience token.

    An ACCESS token rather than a refresh pair on purpose: there is nothing to renew.
    It has one job, one short life, and if it expires the person logs in again (or
    re-uses their invite link). Handing out a refresh token here would create a
    long-lived credential for an account that has not finished proving who it is.
    """
    token = AccessToken.for_user(user)
    token[ADMIN_AUDIENCE_CLAIM] = ADMIN_PREAUTH_AUDIENCE
    token.set_exp(lifetime=PREAUTH_TOKEN_LIFETIME)
    return str(token)


def mint_admin_token_pair(user) -> dict[str, str]:
    """THE ONLY PLACE AN ADMIN-AUDIENCE TOKEN IS CREATED. Amendment 6, in one function.

    It is called from exactly one place — `AdminTOTPConfirmView`, after a TOTP code has
    verified — and `tests/test_admin_surface_guard.py` asserts that by walking the AST of
    every module under `apps/` and `config/`. A second call site is a test failure, not a
    code review question, which is the difference between an invariant and an intention.

    The claim goes on the REFRESH token rather than the access token because SimpleJWT's
    `RefreshToken.access_token` copies every claim except its `no_copy_claims` denylist
    (`token_type`, `exp`, `jti`, `iat`). One write therefore covers the initial pair and
    every renewal through the SHARED `/auth/token/refresh/` endpoint, with no
    admin-specific refresh code to keep in sync — and a customer's refresh token can
    never grow the claim, because nothing else ever writes it.

    NO `is_staff` CHECK HERE, deliberately: this function is unreachable without a
    preauth token, which `AdminPasswordSerializer` only issues to a staff account, and
    the permission layer re-reads `is_staff` from the database on every admin request
    anyway (that second read is what makes revocation immediate). A third copy of the
    check here would look like the guarantee while being the least load-bearing of the
    three.
    """
    refresh = RefreshToken.for_user(user)
    refresh[ADMIN_AUDIENCE_CLAIM] = ADMIN_AUDIENCE
    return {"refresh": str(refresh), "access": str(refresh.access_token)}


class _AudienceScopedJWTAuthentication(JWTAuthentication):
    """Shared body: accept only ACCESS tokens whose `toke_aud` equals `audience`.

    One implementation for both audiences so the two can never drift — in particular so
    a future edit cannot relax the `token_type` pin on one of them and leave the other
    looking identical while behaving differently.
    """

    audience: str = ""

    def get_validated_token(self, raw_token):
        token = super().get_validated_token(raw_token)
        wrong_type = token.get(api_settings.TOKEN_TYPE_CLAIM) != AccessToken.token_type
        if wrong_type or token.get(ADMIN_AUDIENCE_CLAIM) != self.audience:
            # Deliberately generic, and deliberately the same shape as any other
            # bad token: the response must not teach a caller holding a valid
            # customer token that a *different kind* of token would have worked.
            raise AuthenticationFailed(
                _("Given token not valid for this endpoint"),
                code="token_not_valid",
            )
        return token


class AdminJWTAuthentication(_AudienceScopedJWTAuthentication):
    """Accepts only ACCESS tokens minted by `/auth/admin-token/`.

    The claim is set on the REFRESH token at login. SimpleJWT's
    `RefreshToken.access_token` copies every claim except its `no_copy_claims`
    denylist (`token_type`, `exp`, `jti`, `iat`), so access tokens inherit it for
    free — which is why the shared `/auth/token/refresh/` endpoint needs no
    admin-specific code, and why a customer's refresh token can never grow the
    claim: nothing but the admin serializer ever writes it.

    THAT DESIGN IS ALSO WHY `token_type` IS CHECKED HERE. The claim lives on the
    refresh token, so a raw refresh token presented as a bearer credential carries a
    perfectly valid `toke_aud`. `JWTAuthentication.get_validated_token` loops over
    `AUTH_TOKEN_CLASSES` and accepts whatever validates, without looking at
    `token_type` — so the only thing standing between a refresh token and an admin
    session was the SETTING. Measured by monkeypatching `AUTH_TOKEN_CLASSES` to
    `(AccessToken, RefreshToken)`: `/auth/admin-me/` returned 200 for a raw refresh
    token.

    That is not the current configuration, and `test_admin_auth.py` now pins it. But a
    setting is the wrong place for this guarantee to live alone: adding `RefreshToken`
    to that tuple is a plausible thing to do while wiring up a token-verify or
    introspection endpoint, and it would silently upgrade a 30-day, browser-held
    credential into an admin session key. Two independent fences, same argument as
    the claim-plus-`is_staff` pair below.
    """

    audience = ADMIN_AUDIENCE


class AdminPreauthJWTAuthentication(_AudienceScopedJWTAuthentication):
    """Accepts ONLY the bootstrap token minted by `mint_preauth_token`.

    The pairing that makes it safe is mutual exclusion by construction: `toke_aud` holds
    one value, both authentication classes compare it for equality, so a preauth token
    is refused everywhere an admin token is accepted and vice versa. There is no
    ordering, precedence or subset relationship to get wrong.

    `tests/test_admin_surface_guard.py` keeps an explicitly enumerated list of the views
    allowed to accept this class, and asserts it against the URLconf in both directions.
    It holds exactly four: TOTP enrol, second-factor confirm, recovery-code
    verification, and the email-code send. Adding a fifth is the moment to ask what a
    half-authenticated caller can now reach.

    THE INVALIDATION CHECK LIVES HERE RATHER THAN IN THE VIEWS, and that placement is
    the whole reason it is reliable. Five wrong codes kill a preauth token (see
    `totp.record_preauth_failure`); a JWT cannot be un-issued, so the kill is a cache
    entry keyed on the token's `jti` with a TTL equal to its remaining life. Checking it
    in the authentication class means all three endpoints inherit it, and so does the
    fourth one somebody adds — a per-view check is exactly the kind of thing that gets
    remembered twice and forgotten once.
    """

    audience = ADMIN_PREAUTH_AUDIENCE

    def get_validated_token(self, raw_token):
        from apps.accounts.totp import preauth_is_denied

        token = super().get_validated_token(raw_token)
        if preauth_is_denied(token.get(api_settings.JTI_CLAIM)):
            # The same generic message as any other bad token: a caller who has just
            # burnt their guesses learns that the token no longer works, not that it was
            # a *guessing* limit they hit rather than an expiry.
            raise AuthenticationFailed(
                _("Given token not valid for this endpoint"),
                code="token_not_valid",
            )
        return token


def mint_partner_token_pair(user) -> dict[str, str]:
    """THE ONLY PLACE A PARTNER-AUDIENCE TOKEN IS CREATED (Plan-39). Called from
    exactly one place — `apps.delivery.partner_views.PartnerLoginView`, after the
    password has verified and the DeliveryPartner row has been checked active.

    Same claim-on-the-REFRESH-token construction as `mint_admin_token_pair`, for the
    same reason: SimpleJWT copies every non-denylisted claim onto renewed access
    tokens, so the shared `/auth/token/refresh/` endpoint needs no partner-specific
    code and a customer's refresh token can never grow the claim.
    """
    refresh = RefreshToken.for_user(user)
    refresh[ADMIN_AUDIENCE_CLAIM] = PARTNER_AUDIENCE
    return {"refresh": str(refresh), "access": str(refresh.access_token)}


class PartnerJWTAuthentication(_AudienceScopedJWTAuthentication):
    """Accepts only ACCESS tokens minted by `/partner/auth/login/` (Plan-39).

    Mutual exclusion by construction, same as the other two subclasses: `toke_aud`
    holds one value and every class compares for equality, so a partner token is
    refused on the admin and ceremony surfaces and their tokens are refused here.
    The permission layer (`IsDeliveryPartner`) still re-reads the DeliveryPartner
    row's `is_active` from the database on every request — the claim answers "was
    this token issued for the partner portal?", the DB read answers "is this
    partner still welcome, right now?".
    """

    audience = PARTNER_AUDIENCE


class CustomerJWTAuthentication(JWTAuthentication):
    """The project default. Stock behaviour, minus one thing: it refuses PREAUTH tokens.

    FOUND BY TEST, during Task 3b, and worth writing down because it is not obvious. A
    preauth token is an ordinary SimpleJWT *access* token with one extra claim, and
    stock `JWTAuthentication` does not look at claims it was not taught about — so
    `DEFAULT_AUTHENTICATION_CLASSES` accepted it happily and a token that was supposed to
    open a handful of ceremony endpoints opened the entire customer surface: `/auth/me/`,
    `/me/addresses/`, the cart, everything. `test_a_preauth_token_reaches_exactly_those_
    endpoints_and_nothing_else` is what surfaced it; the guard walker could not,
    because it reasons about which views declare which classes and every one of those
    views declares nothing at all.

    SEVERITY, HONESTLY: this was not a privilege escalation. A preauth token is issued
    only after a correct password, and anyone with the password could have obtained a
    full customer token from `/auth/token/` instead. What it WAS is a credential doing
    something its own definition said it could not do, and "half-authenticated" is a
    concept that only survives if it is enforced somewhere. Enforced here, once, rather
    than in each of the ~40 customer views.

    THE ADMIN AUDIENCE IS DELIBERATELY *NOT* REFUSED HERE, and the asymmetry is a
    decision rather than an oversight. An admin token represents a COMPLETED ceremony —
    strictly more proof than a customer login — so letting it act on its holder's own
    customer resources gains an attacker nothing. Refusing it would, however, break the
    ordinary things an administrator does with their own account, `/auth/logout/` first
    among them, and a sign-out that 401s is how sessions get left open.

    THE PARTNER AUDIENCE *IS* REFUSED (Plan-39), on the preauth side of that line: a
    delivery partner is an external business, not a person with a customer account,
    and their credential's definition is "opens the partner rate table". The admin
    exemption's argument does not transfer — a partner never needs `/auth/logout/`
    (the portal BFF just clears its cookies) or any other customer endpoint, so the
    refusal costs nothing and keeps the credential meaning what it says.
    """

    _REFUSED_AUDIENCES = frozenset({ADMIN_PREAUTH_AUDIENCE, PARTNER_AUDIENCE})

    def get_validated_token(self, raw_token):
        token = super().get_validated_token(raw_token)
        if token.get(ADMIN_AUDIENCE_CLAIM) in self._REFUSED_AUDIENCES:
            raise AuthenticationFailed(
                _("Given token not valid for this endpoint"),
                code="token_not_valid",
            )
        return token


class CustomerJWTScheme(SimpleJWTScheme):
    """Keeps drf-spectacular describing the default class as bearer-JWT auth. Without
    it every customer endpoint is documented as having no security requirement."""

    target_class = "apps.accounts.authentication.CustomerJWTAuthentication"
    name = "jwtAuth"


class PartnerJWTScheme(SimpleJWTScheme):
    """Same job as AdminJWTScheme, for the partner audience (Plan-39): without it every
    `/partner/` endpoint is documented as having no security requirement at all."""

    target_class = "apps.accounts.authentication.PartnerJWTAuthentication"
    name = "partnerJwtAuth"


class AdminJWTScheme(SimpleJWTScheme):
    """Teaches drf-spectacular that this is still bearer-JWT authentication.

    Without it every view using `AdminJWTAuthentication` emits "could not resolve
    authenticator" and is documented as having NO security requirement at all — which
    would be actively misleading in the generated schema, and worse once Task 2
    retrofits eighteen more endpoints onto this class. A distinct scheme name keeps
    admin endpoints visibly separate from customer ones in the docs.
    """

    target_class = "apps.accounts.authentication.AdminJWTAuthentication"
    name = "adminJwtAuth"
