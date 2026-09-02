from django.shortcuts import redirect
from django.utils.deprecation import MiddlewareMixin

from .models import Person

# Paths reachable without an active person selected.
EXEMPT_PATHS = {"/login/", "/profile/", "/profile/select/", "/logout/"}
EXEMPT_PREFIXES = ("/static/", "/admin/")


def _is_exempt(path):
    if path in EXEMPT_PATHS:
        return True
    return path.startswith(EXEMPT_PREFIXES)


class ActivePersonMiddleware(MiddlewareMixin):
    """Attach the session's active Person to the request, re-checking
    is_active on every request, and require an active person to be
    selected before allowing access to non-exempt paths.

    Implemented as a process_view hook (like Django's own
    LoginRequiredMiddleware) so it runs, in MIDDLEWARE order, after
    LoginRequiredMiddleware's own check for that request.
    """

    def process_view(self, request, view_func, view_args, view_kwargs):
        request.active_person = None

        person_id = request.session.get("active_person_id")
        if person_id is not None:
            request.active_person = Person.objects.filter(
                pk=person_id, is_active=True
            ).first()

        if request.active_person is None and not _is_exempt(request.path):
            return redirect("profile_picker")

        return None
