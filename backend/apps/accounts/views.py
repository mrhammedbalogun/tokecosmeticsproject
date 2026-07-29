import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.db import transaction
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from apps.core.log_safety import scrub
from apps.notifications.tasks import send_email_task

from .authentication import AdminJWTAuthentication

from .rbac import HasAdminScope, scopes_for_user

from .turnstile import admin_turnstile_secret, require_turnstile

from .throttling import (
    AdminLoginEmailThrottle,
    AdminLoginIPThrottle,
    client_ip,
    LoginBurstThrottle,
    LoginIPThrottle,
    LoginSustainedThrottle,
    PasswordResetEmailThrottle,
    PasswordResetIPThrottle,
    RegisterEmailThrottle,
    RegisterIPThrottle,
)

from .serializers import (
    AccountDeletionSerializer,
    AddressSerializer,
    AdminMeSerializer,
    AdminTokenObtainPairSerializer,
    EmailVerifySerializer,
    LogoutSerializer,
    MeSerializer,
    PasswordChangeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetSerializer,
    RegisterSerializer,
    StaffInviteAcceptSerializer,
    StaffInviteCreateSerializer,
    StaffInviteSerializer,
)

User = get_user_model()

security_logger = logging.getLogger("apps.security")


class LoginView(TokenObtainPairView):
    """`/auth/token/` with throttles attached.

    Stock `TokenObtainPairView` carried only the global anon rate, which was bypassable
    by rotating X-Forwarded-For. Listing throttle_classes here REPLACES the global
    defaults -- DRF does not merge them -- so every cap this endpoint has must appear in
    this list. `LoginIPThrottle` is first and is not optional: without it, password
    spraying across many addresses touches no per-email counter and is unmetered.
    """

    throttle_classes = [LoginIPThrottle, LoginBurstThrottle, LoginSustainedThrottle]

    def post(self, request, *args, **kwargs):
        # After throttling (dispatch runs that first), before credentials: a bot
        # failing Turnstile must not get its guess checked against the password.
        require_turnstile(request)
        response = super().post(request, *args, **kwargs)
        # The failure line comes from the user_login_failed signal (signals.py);
        # JWT flows never fire user_logged_in, so the success line lives here.
        if response.status_code == 200:
            security_logger.info("login succeeded for %s", _submitted_email(request))
        return response


def _submitted_email(request) -> str:
    """The address a login attempt claimed, for the security log. Never trusted for
    anything else, and safe on a malformed body (request.data may not be a dict).

    SCRUBBED, because this value is read from `request.data` BEFORE any validation and
    goes straight into a plain-text log line. `.strip()` alone was not enough: it takes
    the newlines off the ENDS and leaves the ones in the middle, so an email of
    `attacker@evil.test\\nadmin login succeeded for owner@toke.test` forged a complete,
    well-formed success line for the shop owner into `apps.security` — the one stream
    anybody would later read to find out what happened. `scrub` also caps the length,
    which matters here specifically because admin failures log at ERROR and ERROR
    records become Sentry events: uncapped, a 50 KB field is a quota attack.

    The scrub happens HERE rather than in the logging call so that every caller of this
    helper gets it, including ones that do not exist yet.
    """
    data = getattr(request, "data", None)
    if hasattr(data, "get"):
        value = data.get("email")
        if isinstance(value, str) and value.strip():
            return scrub(value.strip())
    return "<no email>"


class AdminLoginView(TokenObtainPairView):
    """`/auth/admin-token/` — the staff gate.

    Same machinery as LoginView, three deliberate differences:

    **1. Staff-only, silently.** `AdminTokenObtainPairSerializer` rejects a non-staff
    user with the same body as a wrong password, so the endpoint never confirms that
    an address belongs to a real customer, let alone a real administrator.

    **2. Turnstile'd** (Plan-16 Amendment 1, which overrides the plan's original
    "Turnstile-exempt — staff URLs are not public forms"). That rationale was
    rejected because the endpoint is publicly reachable and one grep of the deployed
    admin bundle away from discovery; obscurity is not a control, and exempting it
    would have left the HIGHER-value login with less protection than customer login
    got on the same day. It verifies against `admin_turnstile_secret()`, which is the
    admin widget's secret if one is configured and the customer one otherwise.

    Be clear about sizing, so nobody mistakes this for the fence: Turnstile stops
    dumb bots. A targeted attacker buys solver tokens for about $1/1k, and the admin
    is the target worth paying for — compromise here means editing the payout bank
    account and every bank-transfer order pays the attacker. The controls actually
    sized to that threat are the strict throttles below and mandatory TOTP
    (Amendment 2, Task 3b).

    **3. Its own throttle scopes**, far tighter than the customer rates — see
    throttling.py. `AdminLoginIPThrottle` is FIRST and is not optional: listing
    throttle_classes REPLACES the global defaults, and without an IP key password
    spraying across many addresses touches no per-email counter at all.

    LOGGING, and why it is written out rather than left to the signal: a failed admin
    login logs to `apps.security` at ERROR, because Sentry's logging integration turns
    ERROR records into events while INFO/WARNING become mere breadcrumbs, and a
    failed staff login is worth an alert. The `user_login_failed` signal (signals.py)
    ALSO fires on the wrong-password path and logs its generic "login failed" line at
    WARNING — that is a breadcrumb, not a duplicate event, and its different wording
    keeps the two greppable apart. The signal cannot replace this line in either
    direction: it does NOT fire when a customer submits CORRECT credentials here (the
    authentication succeeded; it was the staff check that refused), which is the single
    most interesting event this endpoint can produce.

    THE ERROR LINE AND THE FAILURE COUNTERS ARE THE SAME EVENT, so they are emitted
    from the same place rather than from two independent detectors that could drift.
    BOTH admin throttles count failures rather than requests (see throttling.py), which
    is what stops anonymous junk from locking staff out — of one account for an hour via
    the email key, or of the whole admin indefinitely via the shared-egress IP key. Only
    `AuthenticationFailed` counts: a malformed or incomplete request is not a credential
    guess, and letting it count hands the lockout primitive straight back.

    THROTTLE REJECTIONS ON THIS VIEW ARE ALERTS, not breadcrumbs — `Throttled` is
    raised in `initial()`, before this method runs, so nothing here can log it. See
    `log_throttling_at_error` below and `config/exception_handler.py`.
    """

    serializer_class = AdminTokenObtainPairSerializer
    throttle_classes = [AdminLoginIPThrottle, AdminLoginEmailThrottle]

    # Read by config.exception_handler. Someone reaching the cap on the STAFF gate is
    # the single loudest signal this endpoint can produce, and it was the one that
    # never alerted: `Throttled` is raised in `initial()` before `post()`, so the ERROR
    # line below never fired and the handler's generic WARNING became a Sentry
    # breadcrumb attached to no event. Opt-in per view rather than promoting every 429
    # in the project, because ordinary customer rate limiting is routine and would bury
    # this signal under storefront noise.
    log_throttling_at_error = True

    def post(self, request, *args, **kwargs):
        # Seeded before the try so a body so malformed that reading it raises still
        # produces the ERROR line rather than an unlogged 400.
        email = "<no email>"
        try:
            email = _submitted_email(request)
            # After throttling (dispatch runs that first), before credentials.
            require_turnstile(request, secret=admin_turnstile_secret())
            response = super().post(request, *args, **kwargs)
        except exceptions.APIException as exc:
            # Every refused attempt on the staff gate is one line, one Sentry event:
            # a bot blocked by Turnstile, a wrong password, and a customer trying the
            # admin door all belong in the same alert. The exception class is included
            # because the response body deliberately does not distinguish them.
            security_logger.error(
                "admin login failed for %s (%s)", email, exc.__class__.__name__
            )
            if isinstance(exc, exceptions.AuthenticationFailed):
                # A real credential was submitted and rejected — the only thing that
                # counts, against either key. Turnstile rejections and malformed bodies
                # deliberately do not, or the lockout vector comes straight back at
                # zero cost.
                AdminLoginEmailThrottle().record_failure(request)
                AdminLoginIPThrottle().record_failure(request)
            raise
        security_logger.info("admin login succeeded for %s", email)
        # Proving who you are clears both failure counts. On the email key that stops a
        # bad morning following a staff member around for the rest of the hour; on the
        # IP key it is what makes the bucket the whole staff SHARES survivable, and it
        # is safe for exactly that reason — only a real staff member can produce a
        # success, so the reset can only ever land on the shared egress address, never
        # on an attacker's own address where no login will ever succeed.
        AdminLoginEmailThrottle().reset(request)
        AdminLoginIPThrottle().reset(request)
        return response


class AdminMeView(APIView):
    """`/auth/admin-me/` — who am I and what may I do.

    The admin shell calls this once per session to decide which nav items exist. It
    returns SCOPES, not groups-as-permissions: the client must never have to know
    that "Support" implies `orders.view`, or the role table would live in two
    codebases and drift.

    TWO FENCES, deliberately. `AdminJWTAuthentication` rejects any token that was not
    minted by `/auth/admin-token/` — including a perfectly valid one belonging to the
    same staff member, obtained at the customer login. `IsAdminUser` then re-reads
    `is_staff` from the database, which is what makes a revoked staff account lose
    access immediately instead of whenever its token expires. The claim answers "was
    this token issued for the admin app?"; the DB read answers "is this person still
    staff?". Listing stock `JWTAuthentication` alongside the admin class undoes the
    first of those if it is listed FIRST — see the mechanism, and the ordering subtlety
    behind it, in apps/accounts/authentication.py. test_admin_surface_guard.py asserts
    list EQUALITY so that neither ordering can arise.

    `IsAdminUser` rather than a scope: every staff member must be able to ask who
    they are, including one whose role grants nothing yet. It is not an authorisation
    decision — the endpoint returns only the caller's own identity, and each actual
    admin endpoint re-checks its own scope.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [permissions.IsAdminUser]
    serializer_class = AdminMeSerializer

    @extend_schema(responses={200: AdminMeSerializer})
    def get(self, request):
        user = request.user
        return Response(
            {
                "email": user.email,
                "name": user.get_full_name() or user.email,
                "is_superuser": user.is_superuser,
                "groups": sorted(user.groups.values_list("name", flat=True)),
                # Sorted so the payload is stable — it is compared in tests and cached
                # client-side, and set iteration order is not something to rely on.
                "scopes": sorted(scopes_for_user(user)),
            }
        )


class StaffInviteListCreateView(generics.ListCreateAPIView):
    """`/admin/staff/invites/` — the Owner's staff-creation surface.

    NO THROTTLE, and that is a decision rather than an omission — which is why it is
    written down here instead of leaving its absence to look like one. Reaching this
    endpoint requires the full admin ceremony (an admin-audience token, minted only by
    `/auth/admin-token/` behind Turnstile and the failure-counting staff throttles) plus
    the `staff.manage` scope, which exactly one role holds. The population that can
    reach it is one person. A rate limit on top of that meters nobody: it cannot slow an
    attacker, because an attacker who can reach this endpoint has already won outright,
    and its only realistic effect is to 429 the owner. Decoration on a door that is
    already locked.

    THE LIST IS HERE BECAUSE REVOCATION NEEDS AN ID. A kill switch nobody can address is
    not a kill switch, and the alternative — the Owner reading invite ids out of the
    database — makes the operational answer to a mis-sent invite "SSH in".

    LOGGING AT INFO. Creating an invite is an authenticated, authorised, deliberate act
    by the one person entitled to perform it, so it is provenance rather than anomaly:
    valuable to read later, wrong to alert on. (Sentry treats INFO and WARNING alike —
    both are breadcrumbs — so the level here is about what a human greps for, not about
    what pages someone.) The line carries actor, target and role because `invited_by` on
    the row is the deletable half of that record and this stream is the durable half.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("staff.manage")]
    serializer_class = StaffInviteSerializer
    pagination_class = None  # outstanding invites are a handful, not a feed

    def get_queryset(self):
        from apps.accounts.models import StaffInvite

        return StaffInvite.objects.select_related("role", "invited_by")

    @extend_schema(request=StaffInviteCreateSerializer, responses={201: StaffInviteSerializer})
    def post(self, request, *args, **kwargs):
        from apps.accounts.invites import issue_invite

        serializer = StaffInviteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        role = serializer.validated_data["role"]

        invite, raw_token = issue_invite(email=email, role=role, invited_by=request.user)

        # The raw token leaves this process exactly once, in the mail. It is not
        # returned, not stored and not logged: see the StaffInvite docstring for why the
        # recipient's mailbox (and Resend's stored copy) is the accepted exposure and a
        # log line is not.
        send_email_task.delay(
            "staff_invite",
            invite.email,
            {
                "invite_url": f"{settings.ADMIN_URL}/accept-invite?token={raw_token}",
                "role": role.name,
                "invited_by": request.user.get_full_name() or request.user.email,
                "expires_hours": settings.STAFF_INVITE_TTL_HOURS,
            },
        )
        security_logger.info(
            "staff invite created for %s as %s by %s",
            scrub(invite.email),
            scrub(role.name),
            scrub(request.user.email),
        )
        return Response(StaffInviteSerializer(invite).data, status=status.HTTP_201_CREATED)


class StaffInviteRevokeView(APIView):
    """`/admin/staff/invites/<pk>/revoke/` — the kill switch.

    BUILT NOW, not "later". An outstanding invite is a live staff-creation capability;
    mis-send one — wrong address, typo, wrong role — and without this the only remedy is
    to wait out the whole TTL while a stranger's inbox holds the ability to become an
    administrator. "Resend" is revoke + a new invite, deliberately: refreshing a token
    in place would leave the old one working for whoever already has it, which is the
    exact situation revocation exists to end.

    Idempotent on an already-revoked invite (the state the caller wants is already
    true, and an operator hammering the button should not get an error), but NOT
    permitted on an accepted one: the account exists, deleting the invite row would not
    un-make it, and returning success would tell the Owner they had undone something
    they had not. The honest action there is to demote the staff member.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("staff.manage")]
    serializer_class = StaffInviteSerializer

    @extend_schema(request=None, responses={200: StaffInviteSerializer})
    def post(self, request, pk):
        from django.shortcuts import get_object_or_404

        from apps.accounts.models import StaffInvite

        invite = get_object_or_404(StaffInvite, pk=pk)
        if invite.accepted_at is not None:
            raise exceptions.ValidationError(
                "That invite has already been accepted. Remove the staff account's role "
                "instead."
            )
        if invite.revoked_at is None:
            invite.revoked_at = timezone.now()
            invite.save(update_fields=["revoked_at", "updated_at"])
            security_logger.info(
                "staff invite revoked for %s by %s",
                scrub(invite.email),
                scrub(request.user.email),
            )
        return Response(StaffInviteSerializer(invite).data)


# One message for three different failures. See `StaffInviteAcceptView`.
_INVITE_REFUSED = "That invite link is not valid. Ask for a new one."
_INVITE_EXPIRED = "That invite link has expired. Ask for a new one."


class StaffInviteAcceptView(APIView):
    """`/admin/staff/invites/accept/` — **deliberately PUBLIC**, and the security-critical
    half of this feature.

    It is public because it has to be: the person accepting has no account yet, or has a
    customer account whose credentials are irrelevant here. The proof it accepts is the
    token, which proves control of the invited inbox — the same proof
    `/auth/password/reset/` runs on. `test_admin_surface_guard.py` carries an explicit
    allowlist so this route reads as public ON PURPOSE, distinct from the
    `APIRootView` that Task 2 found sitting on the admin prefix because someone forgot.

    ── THE ORDER OF OPERATIONS IS THE DESIGN ──────────────────────────────────────────

    1. **Turnstile**, against the admin widget's secret (`TURNSTILE_ADMIN_SECRET`,
       falling back to the customer secret) — this page is served by the admin app's
       hostname and Turnstile widgets are domain-scoped.
    2. **Validate the body**, including password strength. Before the claim, so that a
       weak password cannot burn a single-use capability on a typo and strand the new
       hire.
    3. **Hash the submitted token and look it up by digest** (one indexed equality
       match).
    4. **If it is valid: proceed, touching NO throttle bucket.**
    5. **Only if it is invalid: check-and-increment the failure bucket**, then return
       the uniform error.

    Step 4 is the inversion, and it is the opposite of what a reviewer expects — the
    full argument, including the state of the shared-egress assumption today, is in
    `throttling.StaffInviteAcceptThrottle`. In one paragraph: any bucket checked BEFORE
    a request proves itself is a denial button, this endpoint's traffic will arrive from
    one shared Vercel egress address once the admin app exists, and the legitimate user
    gets exactly one shot. Ordinary request-counting would let a stranger 429 the new
    hire out of their own invite for free. Counting only invalid tokens is safe precisely
    because the token is unguessable: an attacker cannot manufacture the bypass
    condition without already holding the capability the bucket protects. New-hire
    lockout becomes structurally impossible rather than merely unlikely.

    ── WHAT IT RETURNS ────────────────────────────────────────────────────────────────

    A PREAUTH token, never an admin session. See `authentication.ADMIN_PREAUTH_AUDIENCE`:
    the admin audience claim means password + Turnstile + TOTP, and bootstrap is not an
    exception to that. Today the preauth token reaches nothing at all, because Task 3b's
    TOTP endpoints do not exist yet. That is correct and fail-closed.

    ── ERRORS ─────────────────────────────────────────────────────────────────────────

    Unknown, revoked and already-used share ONE message. Distinguishing them would
    confirm that a token was once real, which is exactly the feedback someone who
    scraped a mailbox, a proxy log or a browser history needs. EXPIRED is distinguished,
    deliberately: only a holder of a genuine token can ever see it, so it leaks nothing,
    and "your link expired, ask for another" is the difference between a new hire who
    re-invites themselves and one who reports the admin as broken.

    ── LOGGING LEVELS, chosen rather than defaulted ───────────────────────────────────

    * accepted -> WARNING. A new administrator now exists, which is the most
      consequential thing this endpoint can do and worth standing out in the stream. Not
      ERROR: it is the expected happy path of a flow the Owner deliberately started, and
      paging on expected outcomes is how alerts get ignored.
    * unknown / revoked token -> ERROR, i.e. a Sentry event. There is no benign way to
      reach it — the only legitimate callers hold a token out of their own inbox — and
      the volume is bounded by the failure bucket above.
    * expired -> INFO. A real new hire who waited too long. Alerting on it would train
      whoever reads Sentry to dismiss the alert that matters.
    * a 429 here stays a WARNING breadcrumb (no `log_throttling_at_error`): every
      countable failure has already raised its own ERROR event, so promoting the cap
      would raise a second event describing the same attack.
    """

    authentication_classes = []  # public: no credential is accepted, so none can be forged
    permission_classes = [permissions.AllowAny]
    throttle_classes = []  # NOT an oversight — see the ordering above
    serializer_class = StaffInviteAcceptSerializer

    @extend_schema(request=StaffInviteAcceptSerializer, responses={200: None})
    def post(self, request):
        from apps.accounts.authentication import PREAUTH_TOKEN_LIFETIME, mint_preauth_token
        from apps.accounts.invites import InviteRejected, accept_invite, find_invite

        require_turnstile(request, secret=admin_turnstile_secret())

        serializer = StaffInviteAcceptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        raw_token = serializer.validated_data["token"]

        # This lookup is deliberately separate from the one inside `accept_invite`, and
        # the duplication is the point rather than an oversight: the throttle decision
        # has to be made BEFORE anything is claimed, and folding the two together would
        # mean either metering valid tokens or claiming before metering. One extra
        # indexed equality match is a cheap price for keeping that order legible.
        if find_invite(raw_token) is None:
            self._refuse(request, "unknown")

        try:
            invite, user, created = accept_invite(
                raw_token, password=serializer.validated_data["password"]
            )
        except InviteRejected as exc:
            self._refuse(request, exc.reason, invite=exc.invite)

        security_logger.warning(
            "staff invite accepted for %s as %s (%s)",
            scrub(user.email),
            scrub(invite.role.name),
            "new account" if created else "existing customer promoted",
        )
        return Response(
            {
                "detail": "Your account is ready. Set up two-factor authentication to finish.",
                "preauth_token": mint_preauth_token(user),
                "expires_in": int(PREAUTH_TOKEN_LIFETIME.total_seconds()),
            }
        )

    def _refuse(self, request, reason: str, invite=None):
        """Count the failure (if it is one), log it, and raise the uniform error.

        Always raises. Factored out so the counting and the logging cannot drift apart —
        the same reasoning that put `AdminLoginView`'s ERROR line and its
        `record_failure` calls in one place.
        """
        from apps.accounts.throttling import StaffInviteAcceptThrottle

        if reason == "expired":
            # Genuine token, genuine person, benign outcome: no bucket, no alert.
            security_logger.info(
                "staff invite accept failed: expired link for %s",
                scrub(invite.email if invite else "<unknown>"),
            )
            raise exceptions.ValidationError(_INVITE_EXPIRED)

        throttle = StaffInviteAcceptThrottle()
        if not throttle.allow_request(request, self):
            raise exceptions.Throttled(throttle.wait())
        throttle.record_failure(request)

        # `client_ip` reads CF-Connecting-IP, which is only unforgeable because the
        # origin accepts nothing but Cloudflare. On the direct-to-API path it is
        # attacker-chosen text heading for a plain-text log line, so it is scrubbed —
        # the same newline-forgery lesson as the login email field.
        security_logger.error(
            "staff invite accept failed: %s token from %s",
            scrub(reason),
            scrub(client_ip(request)),
        )
        raise exceptions.ValidationError(_INVITE_REFUSED)


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]
    # IP first: it is the cap that protects the sending domain. The email throttle only
    # stops one address being spammed repeatedly; it cannot stop volume.
    throttle_classes = [RegisterIPThrottle, RegisterEmailThrottle]

    def create(self, request, *args, **kwargs):
        require_turnstile(request)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        # A token pair ships WITH the 201. The BFF used to log in via /auth/token/
        # right after registering, but Turnstile tokens are single-use, so one form
        # submit cannot clear two gated endpoints. Issuing tokens here keeps signup
        # a single gated request.
        refresh = RefreshToken.for_user(serializer.instance)
        data = {
            **serializer.data,
            "access": str(refresh.access_token),
            "refresh": str(refresh),
        }
        headers = self.get_success_headers(serializer.data)
        return Response(data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        from django.conf import settings

        from apps.accounts.verification import make_verify_token

        user = serializer.save()
        token = make_verify_token(user.email)
        verify_url = f"{settings.FRONTEND_URL}/verify-email?token={token}"
        send_email_task.delay(
            "verify_email", user.email,
            {"verify_url": verify_url, "first_name": user.first_name},
        )


class VerifyEmailView(APIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = EmailVerifySerializer

    @extend_schema(request=EmailVerifySerializer, responses={200: None})
    def post(self, request):
        from apps.accounts.claims import claim_legacy_orders
        from apps.accounts.verification import VerifyTokenError, read_verify_token

        serializer = EmailVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            email = read_verify_token(serializer.validated_data["token"])
        except VerifyTokenError:
            return Response({"detail": "Invalid or expired verification link."}, status=400)
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            return Response({"detail": "Invalid verification link."}, status=400)
        if user.email_verified_at is None:
            user.email_verified_at = timezone.now()
            user.save(update_fields=["email_verified_at"])
        claimed = claim_legacy_orders(user)
        return Response({"detail": "Email verified.", "orders_claimed": claimed})


class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = MeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


class PasswordChangeView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = PasswordChangeSerializer

    @extend_schema(request=PasswordChangeSerializer, responses={200: None})
    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = request.user
        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password"])
        return Response({"detail": "Password updated."})


class AccountDeletionView(APIView):
    """Soft-delete: deactivate now, anonymise after 30 days (apps.accounts.tasks)."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = AccountDeletionSerializer

    @extend_schema(request=AccountDeletionSerializer, responses={200: None})
    def post(self, request):
        serializer = AccountDeletionSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = request.user
        user.is_active = False
        user.deletion_requested_at = timezone.now()
        user.save(update_fields=["is_active", "deletion_requested_at"])
        # Kill every outstanding refresh token so existing sessions end immediately.
        try:
            from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
            from rest_framework_simplejwt.tokens import RefreshToken

            for t in OutstandingToken.objects.filter(user=user):
                try:
                    RefreshToken(t.token).blacklist()
                except Exception:  # noqa: BLE001 — already-expired tokens are fine
                    pass
        except Exception:  # noqa: BLE001 — blacklist app optional; deactivation already done
            pass
        return Response({"detail": "Your account has been closed."})


class LogoutView(APIView):
    """Blacklist the supplied refresh token."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = LogoutSerializer

    @extend_schema(request=LogoutSerializer, responses={205: None})
    def post(self, request):
        try:
            RefreshToken(request.data["refresh"]).blacklist()
        except (KeyError, TokenError):
            return Response({"detail": "Invalid or missing refresh token."}, status=400)
        return Response(status=status.HTTP_205_RESET_CONTENT)


class PasswordResetView(APIView):
    permission_classes = [permissions.AllowAny]
    # This endpoint SENDS AN EMAIL to an address the caller picks. Unthrottled that is an
    # email-bomb primitive aimed at someone else's inbox, and it is the victim's mail
    # provider that decides we are the spammer. The deliberate always-200 (below) means
    # throttling is also the only signal an abuser ever gets back.
    serializer_class = PasswordResetSerializer
    throttle_classes = [PasswordResetIPThrottle, PasswordResetEmailThrottle]

    @extend_schema(request=PasswordResetSerializer, responses={200: None})
    def post(self, request):
        require_turnstile(request)
        serializer = PasswordResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].lower()
        user = User.objects.filter(email=email, is_active=True).first()
        # Always 200 (don't leak which emails exist).
        if user:
            from django.conf import settings

            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            reset_url = f"{settings.FRONTEND_URL}/reset-password?uid={uid}&token={token}"
            send_email_task.delay(
                "password_reset", user.email, {"reset_url": reset_url, "first_name": user.first_name}
            )
        return Response({"detail": "If that account exists, a reset link has been sent."})


class PasswordResetConfirmView(APIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = PasswordResetConfirmSerializer

    @extend_schema(request=PasswordResetConfirmSerializer, responses={200: None})
    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            uid = force_str(urlsafe_base64_decode(data["uid"]))
            user = User.objects.get(pk=uid)
        except (User.DoesNotExist, ValueError, TypeError):
            return Response({"detail": "Invalid reset link."}, status=400)
        if not default_token_generator.check_token(user, data["token"]):
            return Response({"detail": "Invalid or expired reset link."}, status=400)
        user.set_password(data["password"])
        user.save(update_fields=["password"])
        # A completed reset proves control of the inbox: verify + claim legacy orders.
        from apps.accounts.claims import claim_legacy_orders

        if user.email_verified_at is None:
            user.email_verified_at = timezone.now()
            user.save(update_fields=["email_verified_at"])
        claim_legacy_orders(user)
        return Response({"detail": "Password updated."})


class AddressListCreateView(generics.ListCreateAPIView):
    serializer_class = AddressSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None  # a customer's address book is short

    def get_queryset(self):
        return self.request.user.addresses.all().order_by("-is_default_shipping", "id")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class AddressDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = AddressSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # Scoped to the owner: another user's id resolves to 404, never their data.
        return self.request.user.addresses.all()


class _SetDefaultView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    field = None  # "is_default_shipping" | "is_default_billing"

    def post(self, request, pk):
        from django.shortcuts import get_object_or_404

        address = get_object_or_404(request.user.addresses, pk=pk)
        with transaction.atomic():
            # Exactly one default of this kind per user — clear the rest first.
            request.user.addresses.exclude(pk=address.pk).filter(
                **{self.field: True}
            ).update(**{self.field: False})
            setattr(address, self.field, True)
            address.save(update_fields=[self.field, "updated_at"])
        return Response(AddressSerializer(address).data)


class SetDefaultShippingView(_SetDefaultView):
    field = "is_default_shipping"


class SetDefaultBillingView(_SetDefaultView):
    field = "is_default_billing"
