from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenObtainSerializer

from apps.accounts.models import Address, StaffInvite
from apps.core.address_rules import required_fields_for
from apps.core.phones import normalize_e164

User = get_user_model()


def _clean_contact_number(value):
    """Serializer-facing wrapper: E.164 or bust, with the customer-facing message."""
    try:
        return normalize_e164(value)
    except ValueError as exc:
        raise serializers.ValidationError(str(exc))


class RegisterSerializer(serializers.ModelSerializer):
    # Explicit field (no auto UniqueValidator) so our own duplicate message wins.
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, validators=[validate_password])

    class Meta:
        model = User
        fields = [
            "email", "password", "first_name", "last_name",
            "phone", "whatsapp", "marketing_consent",
        ]

    def validate_email(self, value):
        value = value.lower()
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Account already exists")
        return value

    def validate_phone(self, value):
        return _clean_contact_number(value)

    def validate_whatsapp(self, value):
        return _clean_contact_number(value)

    def create(self, validated_data):
        password = validated_data.pop("password")
        return User.objects.create_user(password=password, **validated_data)


class MeSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "email", "first_name", "last_name",
            "phone", "whatsapp", "marketing_consent", "toke_id",
        ]
        read_only_fields = ["email", "toke_id"]

    def _clean_number(self, field, value):
        # Grandfather clause: rows migrated from WordPress hold national-format
        # numbers ("08099998888"). Re-submitting the stored value unchanged must not
        # block an unrelated profile edit — only a NEW value has to be E.164.
        if self.instance and value == getattr(self.instance, field):
            return value
        return _clean_contact_number(value)

    def validate_phone(self, value):
        return self._clean_number("phone", value)

    def validate_whatsapp(self, value):
        return self._clean_number("whatsapp", value)


class PasswordChangeSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, validators=[validate_password])

    def validate_old_password(self, value):
        # self.context["request"].user is guaranteed by IsAuthenticated on the view.
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value


class AccountDeletionSerializer(serializers.Serializer):
    password = serializers.CharField(write_only=True)

    def validate_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("Password is incorrect.")
        return value


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class PasswordResetSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    password = serializers.CharField(write_only=True, validators=[validate_password])


class AddressSerializer(serializers.ModelSerializer):
    """Structured, per-country address. The per-country required-field rules come from
    the single source apps.core.address_rules.required_fields_for so the serializer and
    any admin form can never disagree about what NG vs GB requires."""

    class Meta:
        model = Address
        fields = [
            "id", "label", "first_name", "last_name", "phone",
            "line1", "line2", "country_code",
            "state_region", "area_region", "city_text", "state_text", "postcode",
            "latitude", "longitude",
            "is_default_shipping", "is_default_billing",
        ]
        read_only_fields = ["id", "is_default_shipping", "is_default_billing"]
        extra_kwargs = {
            # The pin (Plan-32b slice 3). Always optional — free-text addresses without
            # one fall back to the LGA centroid everywhere (model comment).
            "latitude": {"min_value": Decimal("-90"), "max_value": Decimal("90")},
            "longitude": {"min_value": Decimal("-180"), "max_value": Decimal("180")},
        }

    def validate_country_code(self, value):
        return (value or "").upper()

    def validate_phone(self, value):
        # Same rule and same grandfather clause as MeSerializer: a NEW value must be
        # E.164 (the delivery number GIG actually dials — see gig/capture.py), but a
        # legacy national-format value re-submitted unchanged must not block an
        # unrelated edit on an old address.
        if self.instance and value == self.instance.phone:
            return value
        return _clean_contact_number(value)

    def validate(self, attrs):
        # On PATCH, fall back to the instance's current values for anything not sent.
        def get(name):
            if name in attrs:
                return attrs[name]
            return getattr(self.instance, name, None)

        country = (get("country_code") or "").upper()
        errors = {}

        # 1. Per-country required fields (single source of truth).
        for field in required_fields_for(country):
            if not get(field):
                errors[field] = "This field is required for this country."

        state_region = get("state_region")
        area_region = get("area_region")

        # 2. A chosen state_region must belong to the declared country.
        if state_region is not None and state_region.country_code.upper() != country:
            errors["state_region"] = "That region is not in the selected country."

        # 3. If an area_region (LGA) is given, its parent must be the chosen state_region.
        if area_region is not None:
            if state_region is None:
                errors["area_region"] = "Select a state/region before an area."
            elif area_region.parent_id != getattr(state_region, "id", None):
                errors["area_region"] = "That area does not belong to the selected state/region."

        # 4. A NEW address whose chosen state has areas must pick one. The delivery
        #    matcher and GIG quoting work on the area FK, so "state only" quietly
        #    excludes the address from every area-scoped option. Enforced on create
        #    only: old rows predate the rule, and a phone-number PATCH on one should
        #    not demand an LGA it never had.
        if (
            self.instance is None
            and state_region is not None
            and area_region is None
            and state_region.children.filter(is_active=True).exists()
        ):
            errors["area_region"] = "Select an area within the state/region."

        # 5. The pin is both coordinates or neither — a lone latitude is meaningless
        #    and receiver_point() (gig/quotes.py) treats half a pin as no pin. Checked
        #    against the merged (PATCH-aware) values so a partial update cannot strand
        #    one half.
        if (get("latitude") is None) != (get("longitude") is None):
            half = "longitude" if get("longitude") is None else "latitude"
            errors[half] = "Set both latitude and longitude, or neither."

        if errors:
            raise serializers.ValidationError(errors)
        return attrs


class EmailVerifySerializer(serializers.Serializer):
    token = serializers.CharField()


class AdminPasswordSerializer(TokenObtainSerializer):
    """Step ONE of the staff ceremony (`/auth/admin-token/`): password only.

    IT MINTS NOTHING, and that is the change Task 3b made. It subclasses
    `TokenObtainSerializer` — SimpleJWT's base, which authenticates and stops — rather
    than `TokenObtainPairSerializer`, which authenticates AND issues a refresh/access
    pair. Two consequences, both wanted:

    * There is no code path anywhere in this project that turns a password into an
      admin-audience token. Amendment 6's invariant becomes a property of the call
      graph rather than a rule people follow; `apps/accounts/authentication.py`'s
      `mint_admin_token_pair` is the single mint and TOTP-confirm is its single caller.
    * No `OutstandingToken` row is created for a token nobody will ever hold. Before
      3b the alternative shape considered here was "mint the pair and discard it",
      which would have left the database quietly accumulating rows describing live
      refresh tokens that do not exist.

    The staff check hangs off `validate` after `super().validate()` has confirmed the
    password, so a non-staff caller is refused at the same point a wrong password is.

    THE ERROR IS DELIBERATELY IDENTICAL to the wrong-password path — same message, same
    `no_active_account` code, same 401. Saying "not a staff account" would turn this
    endpoint into an oracle: an attacker with a list of leaked customer addresses could
    sort it into "real accounts" and, worse, "real staff accounts", which is precisely
    the list worth phishing. The difference is recorded in the `apps.security` log
    instead, where only we can read it.

    `turnstile_token` is read straight off `request.data` by `require_turnstile` (as on
    every other gated endpoint) and is declared here only so the generated schema tells
    the admin app to send it.
    """

    turnstile_token = serializers.CharField(required=False, allow_blank=True, write_only=True)
    # The trusted-device cookie's value, forwarded by the admin BFF when the browser
    # holds one. Read straight off `request.data` by the view (like `turnstile_token`);
    # declared here only so the generated schema tells the admin app to send it. It
    # buys the caller nothing at this step but a UI hint — redemption happens at
    # confirm, behind the preauth token.
    device_token = serializers.CharField(required=False, allow_blank=True, write_only=True)

    def validate(self, attrs):
        data = super().validate(attrs)
        if not self.user.is_staff:
            raise AuthenticationFailed(
                self.error_messages["no_active_account"],
                "no_active_account",
            )
        return data

    @classmethod
    def get_token(cls, user):
        """Unreachable, and loudly so.

        `TokenObtainSerializer.validate` never calls this — only the *pair* subclass
        does — so overriding it costs nothing and closes the one way this class could
        quietly regain the ability to mint: someone subclassing it later, or a future
        SimpleJWT release moving the call into the base. The guard test walks the AST
        for calls to `mint_admin_token_pair`; this covers the other direction.
        """
        raise NotImplementedError(
            "the staff password step mints nothing — an admin token comes only from "
            "apps.accounts.authentication.mint_admin_token_pair, called by TOTP confirm"
        )


class AdminPreauthResponseSerializer(serializers.Serializer):
    """Response shape of `/auth/admin-token/`. Response-only; documents the schema.

    `second_factor` ("totp", "email", or null for "none chosen yet") exists so the
    admin app knows which screen to draw next — the method chooser, a code-from-your-
    app prompt, or an email-code prompt. It leaks nothing: only a caller who has
    already produced this account's password and a solved Turnstile token ever sees
    it, and they could learn the same fact by calling enrol and reading the status
    code. `totp_enrolled` is the same fact in its pre-email-OTP shape, kept so an
    admin app deployed before this field existed keeps working through the rollout.

    `device_trusted` is a hint that the forwarded `device_token` matched a live trust
    row — "skip straight to confirm". NOT a branch in the security logic: the confirm
    endpoint re-runs the same predicate before anything is minted.
    """

    preauth_token = serializers.CharField(read_only=True)
    expires_in = serializers.IntegerField(read_only=True)
    totp_enrolled = serializers.BooleanField(read_only=True)
    second_factor = serializers.CharField(read_only=True, allow_null=True)
    device_trusted = serializers.BooleanField(read_only=True)


class TOTPCodeSerializer(serializers.Serializer):
    """A six-digit code, or a twenty-character recovery code. One field, no validation
    beyond presence: every judgement about the value belongs in
    `apps/accounts/totp.py`, where the failure is counted against both caps. A
    serializer-level format check would 400 before those counters ran, which is a free
    guessing attempt."""

    code = serializers.CharField(write_only=True, max_length=64)


class TOTPEnrolResponseSerializer(serializers.Serializer):
    """Response shape of TOTP enrol. Returned ONCE, never stored, never logged: the
    provisioning URI carries the secret in its query string, so a copy in a log line is
    a copy of the second factor."""

    secret = serializers.CharField(read_only=True)
    provisioning_uri = serializers.CharField(read_only=True)
    issuer = serializers.CharField(read_only=True)


class SecondFactorConfirmSerializer(serializers.Serializer):
    """Request shape of second-factor confirm, which now speaks three methods.

    `method` defaults to "totp" so every admin app deployed before the other two
    existed keeps sending exactly the body it always sent, and keeps meaning the same
    thing by it.

    `code` stays as permissive as `TOTPCodeSerializer` and for the same reason: every
    judgement about the value belongs where the failure is counted against the caps.
    It is optional at THIS layer only because the trusted-device method has no code —
    the view refuses a codeless totp/email confirm itself, inside the counting.

    `trust_device` asks for a trust token in the response; it is honoured only when a
    real code (never a trusted device) satisfied the factor. `device_token` is the
    cookie value being redeemed when `method` is "trusted_device".
    """

    method = serializers.ChoiceField(
        choices=["totp", "email", "trusted_device"], default="totp", write_only=True
    )
    code = serializers.CharField(
        required=False, allow_blank=True, write_only=True, max_length=64
    )
    trust_device = serializers.BooleanField(default=False, write_only=True)
    device_token = serializers.CharField(required=False, allow_blank=True, write_only=True)


class TOTPConfirmResponseSerializer(serializers.Serializer):
    """Response shape of second-factor confirm — the only response in the project that
    carries an admin-audience token. `recovery_codes` is present only on the response
    that CONFIRMS a new enrolment (first TOTP code, or first email code), not on an
    ordinary login: reissuing a set every login would make whatever the staff member
    printed wrong within a day.

    `device_token`/`device_expires_in` are present only when `trust_device` was asked
    for and granted. The raw token's whole life outside the database digest is this
    response and the httpOnly cookie the admin BFF sets from it."""

    access = serializers.CharField(read_only=True)
    refresh = serializers.CharField(read_only=True)
    recovery_codes = serializers.ListField(child=serializers.CharField(), read_only=True)
    device_token = serializers.CharField(read_only=True)
    device_expires_in = serializers.IntegerField(read_only=True)


class TrustedDeviceRevokeResponseSerializer(serializers.Serializer):
    """Response shape of trusted-device revocation. `revoked` is how many browsers
    stopped being trusted — 0 is a success too (the state the caller wanted is true)."""

    detail = serializers.CharField(read_only=True)
    revoked = serializers.IntegerField(read_only=True)


class EmailOTPRequestResponseSerializer(serializers.Serializer):
    """Response shape of the email-code send. `retry_after` is the cooldown remainder:
    0 means "a fresh code was just sent", anything else means "one is already on its
    way, sent that many seconds ago" — a 200 either way, so a refreshed page or an
    eager double-click reads as reassurance rather than an error."""

    detail = serializers.CharField(read_only=True)
    retry_after = serializers.IntegerField(read_only=True)
    expires_in = serializers.IntegerField(read_only=True)


class TOTPRecoveryResponseSerializer(serializers.Serializer):
    """Response shape of recovery-code verification. Note what is ABSENT: any token.
    Consuming a code voids the secret and the remaining codes and returns the holder to
    enrolment, which keeps "only TOTP-confirm mints an admin token" true with zero
    exceptions."""

    detail = serializers.CharField(read_only=True)
    enrolment_required = serializers.BooleanField(read_only=True)


class StaffInviteSerializer(serializers.ModelSerializer):
    """READ shape. Note what is absent: `token_hash`.

    Not merely uninteresting — a digest is the lookup key, so returning it to any
    caller who can list invites would let them mount an offline check against a
    candidate token without touching the throttled endpoint. It is excluded by an
    explicit field list rather than by `exclude`, so a field added later is opt-in.
    """

    role = serializers.CharField(source="role.name", read_only=True)
    invited_by = serializers.EmailField(source="invited_by.email", read_only=True, default=None)
    state = serializers.CharField(read_only=True)

    class Meta:
        model = StaffInvite
        fields = [
            "id", "email", "role", "state", "expires_at",
            "invited_by", "accepted_at", "revoked_at", "created_at",
        ]
        read_only_fields = fields


class StaffInviteCreateSerializer(serializers.Serializer):
    """WRITE shape for `POST /admin/staff/invites/`.

    THE TWO REFUSALS ARE THE INTERESTING PART, and both are about keeping "an invite"
    a single unambiguous thing:

    1. **An address that is already staff is refused.** An invite whose meaning is
       sometimes-create-an-administrator and sometimes-modify-an-existing-one has no
       single answer to "how did this person get this role?", which is the question the
       whole invite trail exists to answer. Changing an existing staff member's role is
       a group edit.
    2. **A second outstanding invite for the same address is refused.** Two live tokens
       for one address means the older one survives the "resend" meant to replace it —
       and since accepting ALWAYS sets a password, a stale token is a silent
       staff-password reset sitting in an old inbox. Resend is revoke + invite; this is
       what makes that the only way to do it.

    `role` is a group NAME validated against `rbac.ROLES` rather than a primary key.
    Ruling 3 says views never name groups, and this endpoint is the one place that rule
    cannot hold — it is *about* groups — so the constraint is enforced here instead: the
    only accepted names are the four seeded roles, which means an invite can never point
    at some other group that happens to exist and grants nothing.
    """

    # The most consequential body on the whole admin surface: it names who is about to
    # become an administrator and with which role. Both keys are recorded; the raw
    # invite TOKEN is minted server-side and never appears in a request body, so there
    # is nothing credential-shaped here to keep out.
    audit_allowlist = ("email", "role")

    email = serializers.EmailField()
    role = serializers.CharField()

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value, is_staff=True).exists():
            raise serializers.ValidationError(
                "That address is already a staff account. Manage their groups directly."
            )
        return value

    def validate_role(self, value):
        from apps.accounts.rbac import ROLES

        if value not in ROLES:
            raise serializers.ValidationError(f"Unknown role. Choose one of: {', '.join(ROLES)}.")
        group = Group.objects.filter(name=value).first()
        if group is None:
            # The seed migration creates these; a missing one means the group was
            # deleted or renamed, which `accounts.W001` also reports. Fail loudly here
            # rather than inviting someone into a role that cannot exist.
            raise serializers.ValidationError(
                f"The {value} role group is missing. Re-run the accounts.0003 seed."
            )
        return group

    def validate(self, attrs):
        outstanding = StaffInvite.objects.filter(
            email__iexact=attrs["email"],
            accepted_at__isnull=True,
            revoked_at__isnull=True,
            expires_at__gt=timezone.now(),
        )
        if outstanding.exists():
            raise serializers.ValidationError(
                "That address already has an outstanding invite. Revoke it first, "
                "then send a new one."
            )
        return attrs


class StaffInviteAcceptSerializer(serializers.Serializer):
    """WRITE shape for the PUBLIC accept endpoint.

    The password is validated HERE, before the view claims the invite, so a rejected
    password cannot burn a single-use capability on a typo — see
    `StaffInviteAcceptView` for the ordering and why it is what it is.

    `turnstile_token` is read straight off `request.data` by `require_turnstile` (same
    as every other gated endpoint) and is declared here only so the generated schema
    tells the admin app to send it.
    """

    token = serializers.CharField(write_only=True)
    password = serializers.CharField(write_only=True, validators=[validate_password])
    turnstile_token = serializers.CharField(required=False, allow_blank=True, write_only=True)


class StaffRosterSerializer(serializers.ModelSerializer):
    """READ shape for `/admin/staff/` — one administrator per row.

    AN EXPLICIT FIELD LIST, on a `ModelSerializer` over the USER model, which is the
    riskiest base class in this file: `fields = "__all__"` here would serialise
    `password`. The list is therefore opt-in, and `test_no_password_material_is_ever_
    serialised` asserts the outcome rather than trusting the list.

    `roles` comes from group membership and is a LIST rather than a single value even
    though the invite flow only ever assigns one. Django permits several, `createsuperuser`
    assigns none, and a serializer that rendered `groups[0]` would silently hide the
    second role on the day somebody adds one by hand.

    `totp_confirmed` is derived from the related row's `confirmed_at`, never stored
    twice — see the model docstring for why `confirmed_at` is the only thing that counts
    as enrolled. `second_factor` is the Plan-33 generalisation of the same fact
    ("totp", "email", or null): without it the roster would report an email-method
    administrator as having no second factor, which is exactly the "enrolment gap"
    reading the Owner uses this list for, wrong in the alarming direction.
    """

    roles = serializers.SerializerMethodField()
    totp_confirmed = serializers.SerializerMethodField()
    second_factor = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "email", "name", "roles", "is_active", "is_superuser",
            "totp_confirmed", "second_factor", "last_login", "date_joined",
        ]
        read_only_fields = fields

    def get_roles(self, obj) -> list[str]:
        # `obj.groups.all()` and not a fresh query: the view prefetches, so this is the
        # difference between one query and one per administrator.
        return sorted(group.name for group in obj.groups.all())

    def get_totp_confirmed(self, obj) -> bool:
        totp = getattr(obj, "totp", None)
        return bool(totp and totp.confirmed_at)

    def get_second_factor(self, obj) -> str | None:
        if self.get_totp_confirmed(obj):
            return "totp"
        email_factor = getattr(obj, "email_second_factor", None)
        return "email" if email_factor and email_factor.confirmed_at else None

    def get_name(self, obj) -> str:
        return f"{obj.first_name} {obj.last_name}".strip()


class AdminMeSerializer(serializers.Serializer):
    """Shape of `/auth/admin-me/`. Response-only — the admin shell reads it to decide
    which nav items and actions to render, so `scopes` is the field that matters.

    Client-side scope checks are a UI convenience and nothing more: every one of them
    is re-checked server-side by `HasAdminScope`. Hiding a button is not a control.
    """

    email = serializers.EmailField(read_only=True)
    name = serializers.CharField(read_only=True)
    is_superuser = serializers.BooleanField(read_only=True)
    groups = serializers.ListField(child=serializers.CharField(), read_only=True)
    scopes = serializers.ListField(child=serializers.CharField(), read_only=True)
