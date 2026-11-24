from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .authentication import SessionTokenRefreshSerializer
from rest_framework_simplejwt.views import TokenViewBase
from .serializers import EmailTokenObtainPairSerializer
from .views import (
    AuthRateThrottle, OnboardView, AdminCreateUserView, AdminGenerateLoginView,
    ChangePasswordView, MeView, StudentLoginView, UserListView, LogoutView,
)

class EmailTokenObtainPairView(TokenViewBase):
    serializer_class = EmailTokenObtainPairSerializer
    throttle_classes = (AuthRateThrottle,)

class SessionTokenRefreshView(TokenRefreshView):
    serializer_class = SessionTokenRefreshSerializer


urlpatterns = [
    path('login/', EmailTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('refresh/', SessionTokenRefreshView.as_view(), name='token_refresh'),
    path('onboard/', OnboardView.as_view(), name='onboard'),
    path('admin/create-user/', AdminCreateUserView.as_view(), name='admin-create-user'),
    path('admin/generate-login/', AdminGenerateLoginView.as_view(), name='admin-generate-login'),
    path('change-password/', ChangePasswordView.as_view(), name='change-password'),
    path('me/', MeView.as_view(), name='me'),
    path('student-login/', StudentLoginView.as_view(), name='student-login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('users/', UserListView.as_view(), name='user-list'),
]
