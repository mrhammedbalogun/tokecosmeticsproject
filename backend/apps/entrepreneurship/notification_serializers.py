"""The programme tab's write shape: the general recipient serializer with its event
nailed down.

WHY FORCE THE EVENT RATHER THAN VALIDATE IT. Validating would mean the event still
arrives from the request and is merely checked — one refactor away from being checked
against the wrong thing. Forcing it means there is no code path at all where a client
chooses which event they are subscribing somebody to, which is the property
`apps/entrepreneurship/notification_views.py` is built on. `event` is therefore
read-only here and supplied by `validate()`.
"""
from rest_framework import serializers

from apps.entrepreneurship.emails import EVENT_APPLICATION_RECEIVED
from apps.notifications.admin_serializers import NotificationRecipientSerializer


class ProgrammeRecipientSerializer(NotificationRecipientSerializer):
    # Read-only, so a body naming another event is IGNORED rather than refused. Refusing
    # would be a fine answer too, but ignoring means a stray key in a future client
    # cannot turn into a 400 on a screen that has nothing to do with it.
    event = serializers.CharField(read_only=True)

    # `event` is no longer client-supplied, so logging it would record a constant. The
    # target is the whole content of the decision here.
    audit_allowlist = ("user", "email")

    def validate(self, attrs):
        # BEFORE `super().validate()`, which reads `attrs["event"]` for its duplicate
        # check. Without this line that lookup raises KeyError — the field is read-only,
        # so DRF never puts it in `attrs`.
        attrs["event"] = EVENT_APPLICATION_RECEIVED
        return super().validate(attrs)
