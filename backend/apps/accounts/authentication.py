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
from rest_framework_simplejwt.tokens import AccessToken

# Private claim name (see the module docstring for why it is not `aud`).
ADMIN_AUDIENCE_CLAIM = "toke_aud"
ADMIN_AUDIENCE = "toke-admin"

# The BOOTSTRAP audience. Same claim, different value, so the equality check in
# `AdminJWTAuthentication` rejects it without needing to know it exists.
#
# WHY IT EXISTS AND WHY IT OPENS NOTHING TODAY. Amendment 6's invariant is that
# `toke-admin` means the FULL admin ceremony completed — password, Turnstile and TOTP —
# and is minted nowhere else. Accepting a staff invite completes only the first two, so
# it cannot mint one; bootstrap is not an exception to the invariant, because an
# exception is where the hole grows. What it mints instead is this: a short-lived token
# that says "this person has proved the invite and set a password, and now owes a TOTP
# enrolment".
#
# Task 3b will give it exactly two destinations — TOTP enrol and TOTP confirm. Until
# then it reaches NOTHING AT ALL, which is correct and fail-closed rather than an
# oversight; a temporary escape hatch here would be a second bootstrap path, and the
# enumerated allowlist in `tests/test_admin_surface_guard.py` exists so adding one is a
# deliberate, reviewed edit.
#
# NOTE FOR TASK 3b: `/auth/admin-token/` presented with a valid password + Turnstile by
# a staff account with NO TOTP enrolled must return this SAME preauth token, routing to
# those SAME two endpoints. One bootstrap path, not two.
ADMIN_PREAUTH_AUDIENCE = "toke-admin-preauth"

# Long enough to scan a QR code and type a six-digit code, short enough that a preauth
# token left in a browser history or a proxy log is worthless by the time anyone finds
# it. Not env-tunable: there is no operational reason to lengthen it, and the only
# effect of doing so would be to widen that window.
PREAUTH_TOKEN_LIFETIME = timedelta(minutes=10)


def mint_preauth_token(user) -> str:
    """A bootstrap credential for `user`. Never an admin-audience token.

    An ACCESS token rather than a refresh pair on purpose: there is nothing to renew.
    It has one job, one short life, and if it expires the person re-uses their invite
    link — or, once Task 3b lands, logs in again. Handing out a refresh token here
    would create a long-lived credential for an account that has not finished proving
    who it is.
    """
    token = AccessToken.for_user(user)
    token[ADMIN_AUDIENCE_CLAIM] = ADMIN_PREAUTH_AUDIENCE
    token.set_exp(lifetime=PREAUTH_TOKEN_LIFETIME)
    return str(token)


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

    NOTHING USES THIS YET, and that is the design rather than an omission. It exists now
    so that the accept-invite flow has something to return that is provably not an admin
    session, and so Task 3b has a mechanism to attach its two TOTP endpoints to instead
    of inventing one under deadline pressure.

    The pairing that makes it safe is mutual exclusion by construction: `toke_aud` holds
    one value, both authentication classes compare it for equality, so a preauth token
    is refused everywhere an admin token is accepted and vice versa. There is no
    ordering, precedence or subset relationship to get wrong.

    `tests/test_admin_surface_guard.py` keeps an explicitly enumerated list of the views
    allowed to accept this class. It is empty today. Adding a view to it is the moment
    to ask what a half-authenticated caller can now reach.
    """

    audience = ADMIN_PREAUTH_AUDIENCE


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
