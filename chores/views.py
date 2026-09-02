from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from people.models import Person

from .dateutils import week_start_of
from .models import ChoreInstance, TimeLog
from .services import ensure_instances_generated, is_over_budget


def dashboard(request):
    """`GET /` — today's chores for the whole household.

    Materializes this week's instances (idempotent), then lists every
    `ChoreInstance` scheduled for today, for every person, not just the
    active one — per project scope, everyone can see everyone else's
    status.

    Also lists every active `Person` once (in addition to the per-instance
    list above) with an over-budget warning flag, since a person may appear
    zero or several times in the instance list depending on how many chores
    they have today.
    """
    today = timezone.localdate()
    week_start = week_start_of(today)
    ensure_instances_generated(week_start)

    instances = (
        ChoreInstance.objects.filter(date=today)
        .select_related("chore", "assigned_person")
        .order_by("scheduled_start")
    )

    people = []
    for person in Person.objects.filter(is_active=True).order_by("name"):
        over_budget = is_over_budget(person, "daily", today) or is_over_budget(
            person, "weekly", week_start
        )
        people.append({"person": person, "over_budget": over_budget})

    return render(
        request,
        "chores/dashboard.html",
        {"instances": instances, "today": today, "people": people},
    )


@require_POST
def check_instance(request, instance_id):
    """`POST /chores/<instance_id>/check/` — mark an instance done.

    A no-op redirect for instances whose date is in the past: check/uncheck
    only applies to today's (or future) chores.
    """
    instance = get_object_or_404(ChoreInstance, pk=instance_id)

    if instance.date >= timezone.localdate():
        instance.is_done = True
        instance.done_at = timezone.now()
        instance.done_by = request.active_person
        instance.save()

    return redirect("home")


@require_POST
def uncheck_instance(request, instance_id):
    """`POST /chores/<instance_id>/uncheck/` — reverse a check-off."""
    instance = get_object_or_404(ChoreInstance, pk=instance_id)

    if instance.date >= timezone.localdate():
        instance.is_done = False
        instance.done_at = None
        instance.done_by = None
        instance.save()

    return redirect("home")


def log_time(request, instance_id):
    """`GET/POST /chores/<instance_id>/log-time/` — record time spent.

    GET renders the form; POST creates a `TimeLog` and redirects back to
    the dashboard. Logging time is independent of `is_done`: it neither
    requires nor causes a check-off, and any number of logs may be created
    per instance. POSTs against a past-dated instance are rejected with no
    DB change.
    """
    instance = get_object_or_404(ChoreInstance, pk=instance_id)
    error = None

    if request.method == "POST":
        if instance.date < timezone.localdate():
            return redirect("home")

        raw_minutes = request.POST.get("minutes", "")
        note = request.POST.get("note", "")
        try:
            minutes = int(raw_minutes)
            if minutes <= 0:
                raise ValueError
        except (TypeError, ValueError):
            error = "Enter a whole number of minutes greater than zero."

        if error is None:
            TimeLog.objects.create(
                chore_instance=instance,
                logged_by=request.active_person,
                minutes=minutes,
                logged_at=timezone.now(),
                note=note,
            )
            return redirect("home")

    return render(
        request,
        "chores/log_time.html",
        {"instance": instance, "error": error},
    )
