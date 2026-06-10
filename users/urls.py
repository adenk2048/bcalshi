from django.urls import path
from . import views

urlpatterns = [
    path("signup/", views.signup),
    path("register/", views.register),   # optional API
    path("login/", views.login_view),
    path("logout/", views.logout_view),
    path("me/", views.me),
]