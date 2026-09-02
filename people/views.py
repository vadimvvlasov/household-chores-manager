from django.contrib.auth.views import LoginView, LogoutView
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .models import Person


class FamilyLoginView(LoginView):
    """Login for the single shared family account.

    Always lands on LOGIN_REDIRECT_URL ("/profile/") on success, ignoring
    any "?next=" carried over from the mandated anonymous-request redirect
    (e.g. "/login/?next=/profile/select/"). Following such a "next" would
    either violate the "success redirects to /profile/" criterion, or,
    for POST-only targets like /profile/select/, send the post-login GET
    straight into a 405.
    """

    template_name = "people/login.html"

    def get_success_url(self):
        return self.get_default_redirect_url()


def profile_picker(request):
    people = Person.objects.filter(is_active=True).order_by("name")
    return render(request, "people/picker.html", {"people": people})


@require_POST
def select_person(request):
    person = Person.objects.filter(
        pk=request.POST.get("person_id"), is_active=True
    ).first()

    if person is not None:
        request.session["active_person_id"] = person.id
        return redirect("home")

    return redirect("profile_picker")


class ActivePersonLogoutView(LogoutView):
    """Logs out the shared account and clears the selected active person."""

    next_page = "/login/"

    def post(self, request, *args, **kwargs):
        request.session.pop("active_person_id", None)
        return super().post(request, *args, **kwargs)
