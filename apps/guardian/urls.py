from django.urls import path
from . import views

urlpatterns = [
    path('lookup/', views.portal_lookup, name='portal-lookup'),
    path('setup/initiate/', views.portal_setup_initiate, name='portal-setup-initiate'),
    path('setup/verify/', views.portal_setup_verify, name='portal-setup-verify'),
    path('setup/', views.portal_setup, name='portal-setup'),
    path('children/', views.portal_children, name='portal-children'),
]
