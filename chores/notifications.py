import datetime

from .models import ChoreInstance


def get_upcoming_blocks(now, lookahead_minutes=30):
    """`ChoreInstance` rows starting within the next `lookahead_minutes`.

    Filters only on `scheduled_start` — never adds a `date == now.date()`
    filter — so the window correctly spans two calendar dates when `now` is
    late enough in the day. Inclusive on both ends:
    `now <= scheduled_start <= now + timedelta(minutes=lookahead_minutes)`.
    Excludes already-done instances.
    """
    window_end = now + datetime.timedelta(minutes=lookahead_minutes)
    return (
        ChoreInstance.objects.filter(
            is_done=False,
            scheduled_start__gte=now,
            scheduled_start__lte=window_end,
        )
        .select_related("chore", "assigned_person")
        .order_by("scheduled_start")
    )


def get_unfinished_today(now):
    """Today's `ChoreInstance` rows whose start time has passed and are
    still not done."""
    return (
        ChoreInstance.objects.filter(
            date=now.date(),
            is_done=False,
            scheduled_start__lt=now,
        )
        .select_related("chore", "assigned_person")
        .order_by("scheduled_start")
    )
