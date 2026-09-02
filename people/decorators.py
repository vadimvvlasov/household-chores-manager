from functools import wraps

from django.http import HttpResponseForbidden

from .models import Person


def adult_required(view_func):
    """Restrict a view to the active person being an adult.

    Returns a 403 `HttpResponseForbidden` (no state change, view body never
    runs) whenever `request.active_person` isn't set or isn't an adult.
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        active_person = getattr(request, "active_person", None)
        if active_person is None or active_person.role != Person.Role.ADULT:
            return HttpResponseForbidden()
        return view_func(request, *args, **kwargs)

    return wrapper
