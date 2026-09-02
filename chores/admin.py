from django.contrib import admin

from .models import Chore, WeeklyAssignmentTemplate


@admin.register(Chore)
class ChoreAdmin(admin.ModelAdmin):
    list_display = ("name", "default_duration_minutes", "is_active")


@admin.register(WeeklyAssignmentTemplate)
class WeeklyAssignmentTemplateAdmin(admin.ModelAdmin):
    list_display = ("chore", "assigned_to", "day_of_week", "start_time", "duration_minutes")
