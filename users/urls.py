from django.urls import path
from . import views

urlpatterns = [
    path("signup/", views.signup),
    path("register/", views.register),   # optional API
    path("login/", views.login_view),
    path("logout/", views.logout_view),
    path("me/", views.me),

    # superaccount account approval
    path("<int:user_id>/approve/", views.approve_user, name="api-approve-user"),
    path("<int:user_id>/reject/", views.reject_user, name="api-reject-user"),
]
