from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.http import HttpResponseForbidden


def club_members():
    return list(get_user_model().objects.filter(is_active=True).order_by("pk")[:2])


class ClubLoginForm(AuthenticationForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if user not in club_members():
            raise self.get_invalid_login_error()


class PrivateClubMiddleware:
    """Give club access to the first two manually provisioned active accounts."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            request.members = club_members()
            if request.user not in request.members and request.path_info != "/logout/":
                return HttpResponseForbidden("This account is outside the two-person club.")
        response = self.get_response(request)
        response.headers["Cache-Control"] = "private, no-store"
        return response
