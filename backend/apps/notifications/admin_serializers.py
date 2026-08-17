"""Read and write shapes for the Email Notifications screen.

THE WRITE SHAPE IS A DISCRIMINATED PAIR, not two endpoints. A recipient row is either a
staff account or a bare address, and `validate()` below is where "exactly one of them"
becomes a 400 instead of an IntegrityError from the database constraint. The constraint
stays — it is the thing that holds when a shell session or a future management command
writes a row — but a user-facing screen should not learn about it as a 500.

WHY `user` IS VALIDATED AGAINST `is_staff`, NOT JUST EXISTENCE. The picker on the screen
offers staff accounts, but a Server Function is a public POST endpoint and the pk in the
body is whatever the caller sent. Without this check the Owner (or anyone who reached
this endpoint) could subscribe an arbitrary CUSTOMER account to `order.paid` and quietly
forward every order in the shop to them — a customer id is not a secret. The check makes
the staff branch mean what its name says.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.notifications.events import EVENTS, EVENTS_BY_CODE
from apps.notifications.models import NotificationRecipient

User = get_user_model()


class NotificationRecipientSerializer(serializers.ModelSerializer):
    """One row of the list. Read-mostly: the screen adds and deletes rows, it never
    edits one — changing who a subscription points at is delete-then-add, which leaves
    two honest audit rows instead of one that hides what it used to be."""

    #: What this row resolves to TODAY, or "" for a staff account that has been
    #: deactivated or demoted. The screen renders the empty case as a warning rather than
    #: hiding the row, because a silent disappearance is how somebody concludes they are
    #: still subscribed when they are not.
    address = serializers.CharField(read_only=True)
    staff_name = serializers.SerializerMethodField()
    is_external = serializers.SerializerMethodField()
    #: External rows only start receiving once the address has clicked its link. The
    #: screen renders the pending state prominently — an unconfirmed row that LOOKS live
    #: is the same silent-failure shape confirmation exists to remove.
    is_confirmed = serializers.BooleanField(read_only=True)
    confirmed_at = serializers.DateTimeField(read_only=True)

    # Every key here is one a human deliberately submitted, and none is write-only —
    # `test_audit_guard.py` checks exactly that. `event` and the target are the whole
    # content of the decision being audited.
    audit_allowlist = ("event", "user", "email")

    class Meta:
        model = NotificationRecipient
        fields = ["id", "event", "user", "email", "address", "staff_name", "is_external",
                  "is_confirmed", "confirmed_at"]
        extra_kwargs = {
            # Both are optional at the FIELD level; `validate()` below enforces
            # exactly-one-of across the pair, which is a thing no single field can say.
            "user": {"required": False, "allow_null": True},
            "email": {"required": False, "allow_blank": True},
        }
        # THE AUTO-GENERATED UNIQUE VALIDATORS ARE DELIBERATELY DISCARDED, and this is
        # not a shortcut — leaving them in produced two wrong answers on a live server:
        #
        # 1. DRF builds a `UniqueTogetherValidator` from each `UniqueConstraint` in
        #    `Meta.constraints`, and that validator FORCES its fields to be required. So
        #    a request naming only `user` was refused with "email: This field is
        #    required." — telling the operator to fill in the field they correctly left
        #    blank.
        # 2. A duplicate came back as "The fields event, email must make a unique set.",
        #    which is a sentence about a database and not about the shop.
        #
        # `validate()` re-checks both collisions and answers in English; the
        # `UniqueConstraint`s stay on the model as the guarantee, because a `.exists()`
        # check races a concurrent insert and a constraint does not.
        validators: list = []

    def get_staff_name(self, obj) -> str:
        if obj.user_id is None:
            return ""
        return obj.user.get_full_name() or obj.user.email

    def get_is_external(self, obj) -> bool:
        """Flagged for the UI so an address with no account behind it can be labelled as
        such. These rows receive order contents with no login and no second factor, and a
        list that renders them identically to colleagues is a list nobody audits."""
        return obj.user_id is None

    def validate_event(self, value: str) -> str:
        # The model field carries no `choices` on purpose (see its docstring) — this is
        # the only place a bad code is refused, so it is not optional.
        if value not in EVENTS_BY_CODE:
            raise serializers.ValidationError(f"{value} is not a notification event.")
        return value

    def validate_email(self, value: str) -> str:
        return (value or "").strip().lower()

    def validate_user(self, value):
        if value is not None and not (value.is_active and value.is_staff):
            raise serializers.ValidationError(
                "That account is not an active staff member. Use an email address instead."
            )
        return value

    def validate(self, attrs):
        user, email = attrs.get("user"), attrs.get("email", "")
        if bool(user) == bool(email):
            raise serializers.ValidationError(
                "Give either a staff member or an email address, not both and not neither."
            )
        # Duplicates are refused with a sentence rather than the database's constraint
        # name. `.exists()` races against a concurrent insert, which is exactly why the
        # UniqueConstraint stays: this is the friendly path, not the guarantee.
        clash = NotificationRecipient.objects.filter(event=attrs["event"])
        clash = clash.filter(user=user) if user else clash.filter(email=email)
        if clash.exists():
            raise serializers.ValidationError("That recipient is already on this list.")
        return attrs


class NotificationEventSerializer(serializers.Serializer):
    """The registry, as the screen needs it. Not a model — see `events.py`."""

    code = serializers.CharField()
    label = serializers.CharField()
    description = serializers.CharField()


def event_catalog() -> list[dict]:
    return [
        {"code": e.code, "label": e.label, "description": e.description} for e in EVENTS
    ]


class StaffPickerSerializer(serializers.ModelSerializer):
    """The dropdown of accounts that can be subscribed.

    Its own endpoint rather than reusing `/admin/staff/`, which is `staff.manage`. The two
    scopes are both Owner-only today, so this changes nothing about who can see what — it
    keeps them independent, so granting a future Marketing role the notifications screen
    does not silently hand it the staff roster with second-factor enrolment state on it.
    """

    name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "name"]

    def get_name(self, obj) -> str:
        return obj.get_full_name() or obj.email


class TestSendSerializer(serializers.Serializer):
    """Body for "send me a test". Nothing but the row id — see the view for why the
    address is never taken from the request."""

    audit_allowlist = ("recipient_id",)

    recipient_id = serializers.IntegerField()
