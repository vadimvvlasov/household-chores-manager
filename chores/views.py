import datetime

from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from people.decorators import adult_required
from people.models import Person

from .dateutils import week_start_of
from .models import (
    Chore,
    ChoreInstance,
    ProposalStatus,
    ProposedAssignmentChange,
    ProposedBudgetChange,
    TimeLog,
    WeeklyAssignmentTemplate,
)
from .notifications import get_unfinished_today, get_upcoming_blocks
from .services import (
    apply_assignment_change,
    apply_budget_change,
    ensure_instances_generated,
    is_over_budget,
    swap_assignment,
)


def calendar_view(request):
    """`GET /calendar/?week=YYYY-MM-DD` — a whole week's chore blocks per day.

    `week` names any date in the target week; a missing or unparsable value
    (anything `datetime.strptime(value, "%Y-%m-%d")` can't parse) defaults to
    the current week's Sunday. Materializes that week's instances (lazy,
    idempotent — see `ensure_instances_generated`) before rendering.

    Groups the week's `ChoreInstance` rows by day, oldest first. Action
    controls (check-off/uncheck/log-time/swap) render per day, only for days
    whose date is today or later — the same `date < today` guard already
    enforced server-side by the individual action views, just not rendered
    here when it would be rejected anyway. A week entirely in the past (its
    Sunday before the current week's Sunday) is read-only for every day; the
    current week additionally reads-only for its already-past days while
    still rendering controls for today and any later days.
    """
    raw_week = request.GET.get("week")
    try:
        requested_date = datetime.datetime.strptime(raw_week, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        requested_date = timezone.localdate()

    week_start = week_start_of(requested_date)
    ensure_instances_generated(week_start)

    today = timezone.localdate()
    week_end = week_start + datetime.timedelta(days=6)
    instances = (
        ChoreInstance.objects.filter(date__gte=week_start, date__lte=week_end)
        .select_related("chore", "assigned_person")
        .order_by("date", "scheduled_start")
    )

    instances_by_date = {}
    for instance in instances:
        instances_by_date.setdefault(instance.date, []).append(instance)

    days = [
        {
            "date": week_start + datetime.timedelta(days=offset),
            "instances": instances_by_date.get(week_start + datetime.timedelta(days=offset), []),
            "is_editable": (week_start + datetime.timedelta(days=offset)) >= today,
        }
        for offset in range(7)
    ]

    prev_week = week_start - datetime.timedelta(days=7)
    next_week = week_start + datetime.timedelta(days=7)

    return render(
        request,
        "chores/calendar.html",
        {
            "week_start": week_start,
            "days": days,
            "prev_week": prev_week,
            "next_week": next_week,
        },
    )


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

    Also recomputes, on every load, which instances are starting soon and
    which of today's are unfinished and overdue (see `chores.notifications`)
    — no background jobs or polling involved.
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

    now = timezone.localtime(timezone.now())
    upcoming_blocks = get_upcoming_blocks(now)
    unfinished_today = get_unfinished_today(now)

    return render(
        request,
        "chores/dashboard.html",
        {
            "instances": instances,
            "today": today,
            "people": people,
            "upcoming_blocks": upcoming_blocks,
            "unfinished_today": unfinished_today,
        },
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


def swap(request, instance_id):
    """`GET/POST /chores/<instance_id>/swap/` — trade who's responsible.

    GET renders a form listing active `Person` rows to swap the instance
    to. POST calls `swap_assignment`; any `ValueError` it raises (past-dated
    or already-done instance) is caught and shown as an error on the
    re-rendered form, with no DB write. Any active person can perform a
    swap on any instance — not restricted to adults or to the currently
    assigned person.
    """
    instance = get_object_or_404(ChoreInstance, pk=instance_id)
    error = None

    if request.method == "POST":
        new_person = get_object_or_404(Person, pk=request.POST.get("new_person"), is_active=True)
        try:
            swap_assignment(instance, new_person, swapped_by=request.active_person)
        except ValueError as exc:
            error = str(exc)
        else:
            return redirect("home")

    people = Person.objects.filter(is_active=True).order_by("name")

    return render(
        request,
        "chores/swap.html",
        {"instance": instance, "people": people, "error": error},
    )


def assignment_edit(request, template_id=None):
    """`GET/POST /assignments/new/` and `/assignments/<id>/edit/`.

    `template_id=None` proposes/creates a brand new `WeeklyAssignmentTemplate`
    slot; otherwise edits the named one. An adult's POST calls
    `apply_assignment_change` immediately — no proposal row is created. A
    kid's POST instead creates a `PENDING` `ProposedAssignmentChange` holding
    the same typed values, and leaves the live template (if any) untouched.
    """
    template = None
    if template_id is not None:
        template = get_object_or_404(WeeklyAssignmentTemplate, pk=template_id)

    error = None

    if request.method == "POST":
        chore = Chore.objects.filter(pk=request.POST.get("chore")).first()
        assigned_to = Person.objects.filter(
            pk=request.POST.get("assigned_to"), is_active=True
        ).first()
        raw_day = request.POST.get("day_of_week", "")
        raw_start_time = request.POST.get("start_time", "")
        raw_duration = request.POST.get("duration_minutes", "")

        day_of_week = None
        start_time = None
        duration_minutes = None

        if chore is None or assigned_to is None:
            error = "Choose a chore and a person."

        if error is None:
            try:
                day_of_week = int(raw_day)
                if day_of_week not in WeeklyAssignmentTemplate.DayOfWeek.values:
                    raise ValueError
            except (TypeError, ValueError):
                error = "Choose a valid day of the week."

        if error is None:
            try:
                start_time = datetime.datetime.strptime(raw_start_time, "%H:%M").time()
            except (TypeError, ValueError):
                error = "Enter a valid start time."

        if error is None:
            try:
                duration_minutes = int(raw_duration)
                if duration_minutes <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                error = "Enter a whole number of minutes greater than zero."

        if error is None:
            if request.active_person.role == Person.Role.ADULT:
                apply_assignment_change(
                    target_template=template,
                    chore=chore,
                    assigned_to=assigned_to,
                    day_of_week=day_of_week,
                    start_time=start_time,
                    duration_minutes=duration_minutes,
                )
            else:
                ProposedAssignmentChange.objects.create(
                    target_template=template,
                    chore=chore,
                    assigned_to=assigned_to,
                    day_of_week=day_of_week,
                    start_time=start_time,
                    duration_minutes=duration_minutes,
                    proposed_by=request.active_person,
                )
            return redirect("home")

    chores = Chore.objects.filter(is_active=True).order_by("name")
    people = Person.objects.filter(is_active=True).order_by("name")

    return render(
        request,
        "chores/assignment_edit.html",
        {
            "template": template,
            "chores": chores,
            "people": people,
            "day_choices": WeeklyAssignmentTemplate.DayOfWeek.choices,
            "error": error,
        },
    )


def budget_edit(request, person_id):
    """`GET/POST /people/<person_id>/budget/`.

    An adult's POST calls `apply_budget_change` immediately — no proposal
    row is created. A kid's POST instead creates a `PENDING`
    `ProposedBudgetChange`, and leaves the live budget untouched. A blank
    field means "not changing that one" (see `apply_budget_change`).
    """
    person = get_object_or_404(Person, pk=person_id)
    error = None

    if request.method == "POST":
        raw_daily = request.POST.get("daily_budget_minutes", "").strip()
        raw_weekly = request.POST.get("weekly_budget_minutes", "").strip()

        daily_budget_minutes = None
        weekly_budget_minutes = None

        try:
            if raw_daily:
                daily_budget_minutes = int(raw_daily)
                if daily_budget_minutes < 0:
                    raise ValueError
            if raw_weekly:
                weekly_budget_minutes = int(raw_weekly)
                if weekly_budget_minutes < 0:
                    raise ValueError
        except (TypeError, ValueError):
            error = "Enter whole, non-negative numbers of minutes."

        if error is None:
            if request.active_person.role == Person.Role.ADULT:
                apply_budget_change(
                    person,
                    daily_budget_minutes=daily_budget_minutes,
                    weekly_budget_minutes=weekly_budget_minutes,
                )
            else:
                ProposedBudgetChange.objects.create(
                    person=person,
                    daily_budget_minutes=daily_budget_minutes,
                    weekly_budget_minutes=weekly_budget_minutes,
                    proposed_by=request.active_person,
                )
            return redirect("home")

    return render(
        request,
        "chores/budget_edit.html",
        {"person": person, "error": error},
    )


def approvals_list(request):
    """`GET /approvals/` — every `PENDING` proposal from both models.

    Visible to any active person; approve/reject buttons render for
    everyone, but are only actionable by adults (enforced server-side by
    `@adult_required` on the POST endpoints below).
    """
    assignment_changes = (
        ProposedAssignmentChange.objects.filter(status=ProposalStatus.PENDING)
        .select_related("chore", "assigned_to", "target_template", "proposed_by")
        .order_by("proposed_at")
    )
    budget_changes = (
        ProposedBudgetChange.objects.filter(status=ProposalStatus.PENDING)
        .select_related("person", "proposed_by")
        .order_by("proposed_at")
    )

    return render(
        request,
        "chores/approvals.html",
        {"assignment_changes": assignment_changes, "budget_changes": budget_changes},
    )


@require_POST
@adult_required
def approve_assignment_change(request, pk):
    """`POST /approvals/assignment/<id>/approve/` — adult-only."""
    change = get_object_or_404(ProposedAssignmentChange, pk=pk, status=ProposalStatus.PENDING)
    change.approve(request.active_person)
    return redirect("approvals")


@require_POST
@adult_required
def reject_assignment_change(request, pk):
    """`POST /approvals/assignment/<id>/reject/` — adult-only."""
    change = get_object_or_404(ProposedAssignmentChange, pk=pk, status=ProposalStatus.PENDING)
    change.reject(request.active_person, note=request.POST.get("note", ""))
    return redirect("approvals")


@require_POST
@adult_required
def approve_budget_change(request, pk):
    """`POST /approvals/budget/<id>/approve/` — adult-only."""
    change = get_object_or_404(ProposedBudgetChange, pk=pk, status=ProposalStatus.PENDING)
    change.approve(request.active_person)
    return redirect("approvals")


@require_POST
@adult_required
def reject_budget_change(request, pk):
    """`POST /approvals/budget/<id>/reject/` — adult-only."""
    change = get_object_or_404(ProposedBudgetChange, pk=pk, status=ProposalStatus.PENDING)
    change.reject(request.active_person, note=request.POST.get("note", ""))
    return redirect("approvals")
