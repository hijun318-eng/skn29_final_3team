"""SensePlace 인증 URL 패턴."""

from django.urls import path

from senseplace.auth import views

app_name = "senseplace_auth"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("me/", views.me_view, name="me"),
]
