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
