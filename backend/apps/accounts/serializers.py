from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from apps.accounts.models import Address
from apps.core.address_rules import required_fields_for

User = get_user_model()


class RegisterSerializer(serializers.ModelSerializer):
    # Explicit field (no auto UniqueValidator) so our own duplicate message wins.
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, validators=[validate_password])

    class Meta:
        model = User
        fields = ["email", "password", "first_name", "last_name", "phone", "marketing_consent"]

    def validate_email(self, value):
        value = value.lower()
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Account already exists")
        return value

    def create(self, validated_data):
        password = validated_data.pop("password")
        return User.objects.create_user(password=password, **validated_data)


class MeSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["email", "first_name", "last_name", "phone", "marketing_consent", "toke_id"]
        read_only_fields = ["email", "toke_id"]


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
            "is_default_shipping", "is_default_billing",
        ]
        read_only_fields = ["id", "is_default_shipping", "is_default_billing"]

    def validate_country_code(self, value):
        return (value or "").upper()

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

        if errors:
            raise serializers.ValidationError(errors)
        return attrs
