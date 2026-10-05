from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import Role, User
from .permissions import setup_incomplete_reason


class UserSerializer(serializers.ModelSerializer):
    business_name = serializers.CharField(source="business.name", read_only=True, default=None)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "full_name",
            "role",
            "business",
            "business_name",
            "is_active",
            "totp_enabled",
            "must_change_password",
            "date_joined",
            "last_login",
        ]
        read_only_fields = fields


class MeSerializer(UserSerializer):
    setup_required = serializers.SerializerMethodField()
    is_platform_staff = serializers.BooleanField(read_only=True)
    is_super_admin = serializers.BooleanField(read_only=True)
    business_status = serializers.CharField(source="business.status", read_only=True, default=None)

    class Meta(UserSerializer.Meta):
        fields = UserSerializer.Meta.fields + [
            "setup_required",
            "is_platform_staff",
            "is_super_admin",
            "business_status",
        ]
        read_only_fields = fields

    def get_setup_required(self, obj):
        return setup_incomplete_reason(obj)


class UserCreateSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    full_name = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    role = serializers.ChoiceField(choices=Role.choices, default=Role.BUSINESS_ADMIN)
    business = serializers.IntegerField(required=False, allow_null=True)

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this e-mail already exists.")
        return value


class UserUpdateSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)
    role = serializers.ChoiceField(choices=Role.choices, required=False)


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(max_length=256, trim_whitespace=False)


class OtpSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=20)


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(max_length=256, trim_whitespace=False)
    new_password = serializers.CharField(max_length=256, trim_whitespace=False)

    def validate(self, attrs):
        user = self.context["request"].user
        if not user.check_password(attrs["current_password"]):
            raise serializers.ValidationError({"current_password": "Current password is incorrect."})
        if attrs["current_password"] == attrs["new_password"]:
            raise serializers.ValidationError({"new_password": "Choose a password you have not used here."})
        validate_password(attrs["new_password"], user)
        return attrs


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField(max_length=64)
    token = serializers.CharField(max_length=128)
    new_password = serializers.CharField(max_length=256, trim_whitespace=False)


class PasswordConfirmSerializer(serializers.Serializer):
    password = serializers.CharField(max_length=256, trim_whitespace=False)
    code = serializers.CharField(max_length=20, required=False, allow_blank=True)
