from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from rest_framework_simplejwt.views import TokenViewBase
from .serializers import EmailTokenObtainPairSerializer
from .views import OnboardView, AdminCreateUserView, MeView, StudentLoginView, UserListView

class EmailTokenObtainPairView(TokenViewBase):
    serializer_class = EmailTokenObtainPairSerializer

urlpatterns = [
    path('login/', EmailTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('onboard/', OnboardView.as_view(), name='onboard'),
    path('admin/create-user/', AdminCreateUserView.as_view(), name='admin-create-user'),
    path('me/', MeView.as_view(), name='me'),
    path('student-login/', StudentLoginView.as_view(), name='student-login'),
    path('users/', UserListView.as_view(), name='user-list'),
]
