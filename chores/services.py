import datetime

from django.utils import timezone

from .models import ChoreInstance, WeeklyAssignmentTemplate


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
