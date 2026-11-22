from django.contrib.auth import views as auth
from django.urls import include, path

from core.membership import ClubLoginForm

urlpatterns = [
    path("login/", auth.LoginView.as_view(authentication_form=ClubLoginForm), name="login"),
    path("logout/", auth.LogoutView.as_view(), name="logout"),
    path("", include("core.urls")),
]
