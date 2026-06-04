from django.urls import path
from . import views

urlpatterns = [
    path('lookup/', views.portal_lookup, name='portal-lookup'),
    path('setup/', views.portal_setup, name='portal-setup'),
    path('login/', views.portal_login, name='portal-login'),
    path('children/', views.portal_children, name='portal-children'),
]
