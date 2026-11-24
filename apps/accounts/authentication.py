from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User
from .sessions import is_current

REPLACED = {
    'detail': 'You were signed out because your account was opened on another device.',
    'code': 'session_replaced',
}


class SessionJWTAuthentication(JWTAuthentication):
    """The usual token check, plus: a student's token must belong to their one live session,
    and a school that has not paid is held at the billing gate.

    The user row is already loaded to check the token, so the session check adds no query.
    The billing check reads one cached row per school (apps.billing.services).
    """

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is not None:
            from apps.billing.services import enforce     # local: keeps app loading clean
            enforce(result[0], request)
        return result

    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        if not is_current(user, validated_token.get('sid')):
            raise AuthenticationFailed(REPLACED)
        return user


class SessionTokenRefreshSerializer(TokenRefreshSerializer):
    """A replaced device cannot keep itself alive by refreshing its token."""

    def validate(self, attrs):
        try:
            token = RefreshToken(attrs['refresh'])
        except TokenError as e:
            raise InvalidToken(e.args[0])
        user = User.objects.filter(pk=token.get('user_id')).first()
        if user is not None and not is_current(user, token.get('sid')):
            raise AuthenticationFailed(REPLACED)
        return super().validate(attrs)
