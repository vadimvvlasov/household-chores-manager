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


def swap_assignment(instance, new_person):
    """Reassign `instance.assigned_person` to `new_person`, effective immediately.

    Any two active family members can swap who's responsible for a specific
    day's chore, with no approval step. Raises `ValueError` (making no DB
    write) when the instance is in the past or already done — a swap only
    changes who's responsible going forward, so it can't apply to a chore
    whose day has already passed or that's already been completed. Existing
    `TimeLog` rows and any already-set `done_by`/`done_at` are left alone.
    """
    if instance.date < timezone.localdate():
        raise ValueError("Can't swap a chore from a past date.")
    if instance.is_done:
        raise ValueError("Can't swap a chore that's already done.")

    instance.assigned_person = new_person
    instance.save()


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


def apply_assignment_change(
    target_template, chore, assigned_to, day_of_week, start_time, duration_minutes
):
    """Create or update a `WeeklyAssignmentTemplate` from typed args.

    `target_template=None` means "new slot": a fresh `WeeklyAssignmentTemplate`
    is created. Otherwise the given template's fields are overwritten and
    saved in place. Returns the created/updated template.
    """
    if target_template is None:
        return WeeklyAssignmentTemplate.objects.create(
            chore=chore,
            assigned_to=assigned_to,
            day_of_week=day_of_week,
            start_time=start_time,
            duration_minutes=duration_minutes,
        )

    target_template.chore = chore
    target_template.assigned_to = assigned_to
    target_template.day_of_week = day_of_week
    target_template.start_time = start_time
    target_template.duration_minutes = duration_minutes
    target_template.save()
    return target_template


def apply_budget_change(person, daily_budget_minutes=None, weekly_budget_minutes=None):
    """Set only the non-`None` budget field(s) on `person`.

    A `None` argument means "not changing this one" — it leaves the
    existing value on `person` untouched, it does not clear it. Returns
    `person`.
    """
    changed = False
    if daily_budget_minutes is not None:
        person.daily_budget_minutes = daily_budget_minutes
        changed = True
    if weekly_budget_minutes is not None:
        person.weekly_budget_minutes = weekly_budget_minutes
        changed = True

    if changed:
        person.save()
    return person


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
