from django.urls import path
from . import views

urlpatterns = [
    path('lookup/', views.portal_lookup, name='portal-lookup'),
    path('children/', views.portal_children, name='portal-children'),
]
