import datetime


def week_start_of(d):
    """Return the Sunday on or before `d`.

    `d` is a `datetime.date` (or `datetime.datetime`). Sunday itself maps to
    itself.
    """
    # date.weekday(): Monday=0 ... Sunday=6
    days_since_sunday = (d.weekday() + 1) % 7
    return d - datetime.timedelta(days=days_since_sunday)
