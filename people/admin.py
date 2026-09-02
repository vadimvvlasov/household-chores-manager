from django.contrib import admin

from .models import Person


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ("name", "role", "is_active")
    fields = (
        "name",
        "role",
        "is_active",
        "daily_budget_minutes",
        "weekly_budget_minutes",
    )
