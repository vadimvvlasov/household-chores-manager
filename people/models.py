from django.db import models


class Person(models.Model):
    class Role(models.TextChoices):
        ADULT = "ADULT", "Adult"
        KID = "KID", "Kid"

    name = models.CharField(max_length=100)
    role = models.CharField(max_length=10, choices=Role.choices)
    is_active = models.BooleanField(default=True)
    # None means no cap set for that period.
    daily_budget_minutes = models.PositiveIntegerField(null=True, blank=True)
    weekly_budget_minutes = models.PositiveIntegerField(null=True, blank=True)

    def __str__(self):
        return self.name
