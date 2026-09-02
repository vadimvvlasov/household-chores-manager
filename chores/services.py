import datetime

from django.db.models import Sum
from django.utils import timezone

from .dateutils import week_start_of
from .models import ChoreInstance, TimeLog, WeeklyAssignmentTemplate


def ensure_instances_generated(week_start):
    """Materialize `ChoreInstance` rows for `week_start` from active templates.

    `week_start` is expected to be a Sunday (see `dateutils.week_start_of`).
    For every `WeeklyAssignmentTemplate` whose chore and assigned person are
    both currently active, get-or-creates the matching `ChoreInstance` for
    that template's day within the week. Idempotent: calling this twice for
    the same week never creates duplicates, and never touches instances that
    already exist (so template edits made after generation don't retroactively
    change already-generated instances).
    """
    templates = WeeklyAssignmentTemplate.objects.filter(
        chore__is_active=True, assigned_to__is_active=True
    ).select_related("chore", "assigned_to")

    created_instances = []
    for template in templates:
        instance_date = week_start + datetime.timedelta(days=template.day_of_week)
        scheduled_start = timezone.make_aware(
            datetime.datetime.combine(instance_date, template.start_time)
        )

        instance, created = ChoreInstance.objects.get_or_create(
            template=template,
            date=instance_date,
            defaults={
                "chore": template.chore,
                "scheduled_start": scheduled_start,
                "budgeted_minutes": template.duration_minutes,
                "assigned_person": template.assigned_to,
            },
        )
        if created:
            created_instances.append(instance)

    return created_instances


def minutes_logged_today(person, on_date):
    """Total `TimeLog.minutes` for `person` logged on `on_date`.

    Scoped by the local date `logged_at` falls on, not by the chore
    instance's scheduled date — a swap can move `assigned_person` after the
    fact, so this reflects who actually did the work.
    """
    total = TimeLog.objects.filter(logged_by=person, logged_at__date=on_date).aggregate(
        total=Sum("minutes")
    )["total"]
    return total or 0


def minutes_logged_this_week(person, week_start):
    """Total `TimeLog.minutes` for `person` in the Sunday-Saturday week containing `week_start`."""
    start_of_week = week_start_of(week_start)
    end_of_week = start_of_week + datetime.timedelta(days=6)

    total = TimeLog.objects.filter(
        logged_by=person,
        logged_at__date__gte=start_of_week,
        logged_at__date__lte=end_of_week,
    ).aggregate(total=Sum("minutes"))["total"]
    return total or 0


def is_over_budget(person, period, on_date):
    """Whether `person` has exceeded their `"daily"` or `"weekly"` budget.

    `False` whenever the relevant budget field is `None` (no cap set).
    Otherwise `True` only when logged minutes strictly exceed the budget —
    exactly at the limit is not over.
    """
    if period == "daily":
        budget = person.daily_budget_minutes
        if budget is None:
            return False
        return minutes_logged_today(person, on_date) > budget
    elif period == "weekly":
        budget = person.weekly_budget_minutes
        if budget is None:
            return False
        return minutes_logged_this_week(person, on_date) > budget
    else:
        raise ValueError(f"Unknown period: {period!r}")
