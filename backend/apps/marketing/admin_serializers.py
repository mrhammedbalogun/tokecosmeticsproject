"""Admin serialisers for the Marketing screen.

Two rules shape every one of them:

  1. **No secret is ever serialised.** Not to write, not to read back, not "masked". The
     access tokens live in the environment (`credentials.py`), and the screen reports
     whether each is present. A masked secret in a JSON response is still a secret in a
     browser's network tab, in a screenshot, and in whatever logs the response.
  2. **Nothing here creates or deletes a channel row.** The five channels are the five
     platforms the code has adapters for; a sixth row would be a row nothing reads. The
     viewset seeds them and this serialiser only tunes them.
"""
from rest_framework import serializers

from apps.marketing.credentials import missing_settings_for, supports_server_side
from apps.marketing.models import ConversionEvent, MarketingChannel, MarketingSettings


class MarketingSettingsAdminSerializer(serializers.ModelSerializer):
    """The master switch, the consent policy, and what `value` means.

    Every field is allowlisted for audit. `tracking_enabled` decides whether the shop is
    measuring at all and `consent_required_countries` decides whose consent is asked
    for before it happens — both are the kind of change that has to have a name and a
    timestamp attached to it afterwards.
    """

    audit_allowlist = (
        "tracking_enabled", "purchase_value_basis",
        "consent_required_countries", "consent_version",
    )

    class Meta:
        model = MarketingSettings
        fields = ["tracking_enabled", "purchase_value_basis",
                  "consent_required_countries", "consent_version"]

    def validate_consent_required_countries(self, value):
        """A list of ISO-3166 alpha-2 codes, upper-cased. Validated because this list
        decides who is asked for consent before a cookie is set: a typo does not fail
        loudly, it silently drops a country into the opt-out regime it may not legally
        belong in."""
        if not isinstance(value, list):
            raise serializers.ValidationError("Expected a list of two-letter country codes.")
        codes = []
        for entry in value:
            code = str(entry).strip().upper()
            if len(code) != 2 or not code.isalpha():
                raise serializers.ValidationError(f"{entry!r} is not a two-letter country code.")
            codes.append(code)
        return sorted(set(codes))


class MarketingChannelAdminSerializer(serializers.ModelSerializer):
    """One platform's row, plus the three things the screen must know that are not
    columns: whether its credential is present, whether it has a server-side sender at
    all, and its display name."""

    label = serializers.CharField(source="get_code_display", read_only=True)
    # True when every environment variable this channel's sender needs is set. The names
    # of the MISSING ones are published (they are variable names, not values) so the
    # screen can tell Hammed exactly what to add to `.env.prod` rather than "not
    # configured".
    credential_configured = serializers.SerializerMethodField()
    missing_settings = serializers.SerializerMethodField()
    has_server_side = serializers.SerializerMethodField()

    audit_allowlist = (
        "is_enabled", "pixel_id", "secondary_id",
        "server_account_id", "server_destination_id",
        "browser_enabled", "server_enabled", "test_event_code",
    )

    class Meta:
        model = MarketingChannel
        fields = ["code", "label", "is_enabled", "pixel_id", "secondary_id",
                  "server_account_id", "server_destination_id",
                  "browser_enabled", "server_enabled", "test_event_code",
                  "credential_configured", "missing_settings", "has_server_side"]
        # `code` identifies the platform and is never edited: changing it would point a
        # configured row at a different adapter.
        read_only_fields = ["code"]

    def get_credential_configured(self, obj) -> bool:
        return not missing_settings_for(obj.code)

    def get_missing_settings(self, obj) -> list[str]:
        return missing_settings_for(obj.code)

    def get_has_server_side(self, obj) -> bool:
        return supports_server_side(obj.code)


class ConversionEventAdminSerializer(serializers.ModelSerializer):
    """The outbox, read-only.

    `payload` is included because it is the answer to "what did we actually send", which
    is the only question this table exists to answer. It carries hashed identifiers and,
    for Meta, a raw IP and user agent — which is why `tasks.purge_attribution_pii`
    blanks it after 90 days and why this endpoint audits its reads.
    """

    order_number = serializers.CharField(source="order.number", read_only=True, default="")

    class Meta:
        model = ConversionEvent
        fields = ["id", "channel", "event_name", "event_id", "order_number", "status",
                  "attempts", "last_error", "response_excerpt", "payload",
                  "created_at", "sent_at"]
        read_only_fields = fields
