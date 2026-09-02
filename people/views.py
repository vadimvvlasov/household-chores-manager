from django.contrib.auth.views import LogoutView
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .models import Person


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
