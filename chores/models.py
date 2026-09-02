from django.db import models
from django.utils import timezone

from people.models import Person


class Chore(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    default_duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class WeeklyAssignmentTemplate(models.Model):
    class DayOfWeek(models.IntegerChoices):
        SUNDAY = 0, "Sunday"
        MONDAY = 1, "Monday"
        TUESDAY = 2, "Tuesday"
        WEDNESDAY = 3, "Wednesday"
        THURSDAY = 4, "Thursday"
        FRIDAY = 5, "Friday"
        SATURDAY = 6, "Saturday"

    chore = models.ForeignKey(Chore, on_delete=models.PROTECT)
    assigned_to = models.ForeignKey(Person, on_delete=models.PROTECT)
    day_of_week = models.IntegerField(choices=DayOfWeek.choices)
    start_time = models.TimeField()
    duration_minutes = models.PositiveSmallIntegerField()

    def __str__(self):
        return f"{self.chore} - {self.assigned_to} ({self.get_day_of_week_display()})"


class ChoreInstance(models.Model):
    template = models.ForeignKey(WeeklyAssignmentTemplate, on_delete=models.PROTECT)
    # Denormalized copies of the template's values, snapshotted at
    # generation time so editing the template later never rewrites an
    # already-generated instance.
    chore = models.ForeignKey(Chore, on_delete=models.PROTECT)
    date = models.DateField()
    scheduled_start = models.DateTimeField()
    budgeted_minutes = models.PositiveIntegerField()
    assigned_person = models.ForeignKey(
        Person, on_delete=models.PROTECT, related_name="assigned_chore_instances"
    )
    is_done = models.BooleanField(default=False)
    done_at = models.DateTimeField(null=True, blank=True)
    done_by = models.ForeignKey(
        Person,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="completed_chore_instances",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["template", "date"], name="unique_template_date")
        ]

    def __str__(self):
        return f"{self.chore} - {self.assigned_person} on {self.date}"


class ProposalStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"


class ProposedAssignmentChange(models.Model):
    """A kid's (or adult's, pre-approval) suggested create/edit of a
    `WeeklyAssignmentTemplate`.

    Holds the same plain typed fields as `WeeklyAssignmentTemplate` — not a
    diff/JSON blob — so `chores.services.apply_assignment_change` can apply
    them directly. `target_template=None` means "propose a brand new slot";
    otherwise it names the existing template being edited.
    """

    target_template = models.ForeignKey(
        WeeklyAssignmentTemplate,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="proposed_changes",
    )
    chore = models.ForeignKey(Chore, on_delete=models.PROTECT)
    assigned_to = models.ForeignKey(
        Person, on_delete=models.PROTECT, related_name="proposed_assignment_changes"
    )
    day_of_week = models.IntegerField(choices=WeeklyAssignmentTemplate.DayOfWeek.choices)
    start_time = models.TimeField()
    duration_minutes = models.PositiveSmallIntegerField()
    proposed_by = models.ForeignKey(
        Person, on_delete=models.PROTECT, related_name="assignment_changes_proposed"
    )
    proposed_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(
        max_length=10, choices=ProposalStatus.choices, default=ProposalStatus.PENDING
    )
    reviewed_by = models.ForeignKey(
        Person,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="assignment_changes_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"Proposed {self.chore} - {self.assigned_to} ({self.status})"

    def approve(self, reviewed_by):
        """Apply the proposed values to live data, then mark approved."""
        from .services import apply_assignment_change

        apply_assignment_change(
            target_template=self.target_template,
            chore=self.chore,
            assigned_to=self.assigned_to,
            day_of_week=self.day_of_week,
            start_time=self.start_time,
            duration_minutes=self.duration_minutes,
        )
        self.status = ProposalStatus.APPROVED
        self.reviewed_by = reviewed_by
        self.reviewed_at = timezone.now()
        self.save()

    def reject(self, reviewed_by, note=""):
        """Mark rejected without touching live data."""
        self.status = ProposalStatus.REJECTED
        self.reviewed_by = reviewed_by
        self.reviewed_at = timezone.now()
        self.note = note
        self.save()


class ProposedBudgetChange(models.Model):
    """A kid's (or adult's, pre-approval) suggested change to a `Person`'s
    budget caps. Only the field(s) actually being changed carry a value —
    the other stays `None`.
    """

    person = models.ForeignKey(
        Person, on_delete=models.PROTECT, related_name="proposed_budget_changes"
    )
    daily_budget_minutes = models.PositiveIntegerField(null=True, blank=True)
    weekly_budget_minutes = models.PositiveIntegerField(null=True, blank=True)
    proposed_by = models.ForeignKey(
        Person, on_delete=models.PROTECT, related_name="budget_changes_proposed"
    )
    proposed_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(
        max_length=10, choices=ProposalStatus.choices, default=ProposalStatus.PENDING
    )
    reviewed_by = models.ForeignKey(
        Person,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="budget_changes_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"Proposed budget change for {self.person} ({self.status})"

    def approve(self, reviewed_by):
        """Apply the proposed budget field(s) to live data, then mark approved."""
        from .services import apply_budget_change

        apply_budget_change(
            person=self.person,
            daily_budget_minutes=self.daily_budget_minutes,
            weekly_budget_minutes=self.weekly_budget_minutes,
        )
        self.status = ProposalStatus.APPROVED
        self.reviewed_by = reviewed_by
        self.reviewed_at = timezone.now()
        self.save()

    def reject(self, reviewed_by, note=""):
        """Mark rejected without touching live data."""
        self.status = ProposalStatus.REJECTED
        self.reviewed_by = reviewed_by
        self.reviewed_at = timezone.now()
        self.note = note
        self.save()


class TimeLog(models.Model):
    # CASCADE (unlike the PROTECT FKs above): a time log is dependent data
    # that only makes sense attached to its instance, so deleting the
    # instance should remove its logs rather than being blocked by them.
    chore_instance = models.ForeignKey(
        ChoreInstance, on_delete=models.CASCADE, related_name="time_logs"
    )
    logged_by = models.ForeignKey(Person, on_delete=models.PROTECT)
    minutes = models.PositiveIntegerField()
    logged_at = models.DateTimeField(default=timezone.now)
    note = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"{self.minutes}min on {self.chore_instance} by {self.logged_by}"
