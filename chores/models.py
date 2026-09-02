from django.db import models

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
