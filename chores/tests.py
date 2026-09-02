import datetime

from django.contrib.auth.models import User
from django.db.models import ProtectedError
from django.test import TestCase
from django.urls import reverse

from people.models import Person

from .models import Chore, WeeklyAssignmentTemplate


class ChoreModelTests(TestCase):
    def test_chore_fields_persist_with_expected_defaults(self):
        chore = Chore.objects.create(name="Dishes")

        chore.refresh_from_db()

        self.assertEqual(chore.name, "Dishes")
        self.assertEqual(chore.description, "")
        self.assertIsNone(chore.default_duration_minutes)
        self.assertTrue(chore.is_active)
        self.assertEqual(str(chore), "Dishes")

    def test_chore_can_set_description_and_duration(self):
        chore = Chore.objects.create(
            name="Vacuum",
            description="Living room and hallway",
            default_duration_minutes=20,
        )

        chore.refresh_from_db()

        self.assertEqual(chore.description, "Living room and hallway")
        self.assertEqual(chore.default_duration_minutes, 20)


class WeeklyAssignmentTemplateModelTests(TestCase):
    def setUp(self):
        self.chore = Chore.objects.create(name="Dishes")
        self.person = Person.objects.create(name="Alex", role=Person.Role.ADULT)

    def test_creating_template_links_chore_and_person(self):
        template = WeeklyAssignmentTemplate.objects.create(
            chore=self.chore,
            assigned_to=self.person,
            day_of_week=WeeklyAssignmentTemplate.DayOfWeek.SUNDAY,
            start_time=datetime.time(18, 0),
            duration_minutes=15,
        )

        template.refresh_from_db()

        self.assertEqual(template.chore, self.chore)
        self.assertEqual(template.assigned_to, self.person)

    def test_day_of_week_zero_is_sunday(self):
        template = WeeklyAssignmentTemplate.objects.create(
            chore=self.chore,
            assigned_to=self.person,
            day_of_week=0,
            start_time=datetime.time(9, 0),
            duration_minutes=10,
        )

        self.assertEqual(template.day_of_week, WeeklyAssignmentTemplate.DayOfWeek.SUNDAY)
        self.assertEqual(template.get_day_of_week_display(), "Sunday")

    def test_day_of_week_six_is_saturday(self):
        template = WeeklyAssignmentTemplate.objects.create(
            chore=self.chore,
            assigned_to=self.person,
            day_of_week=6,
            start_time=datetime.time(9, 0),
            duration_minutes=10,
        )

        self.assertEqual(template.day_of_week, WeeklyAssignmentTemplate.DayOfWeek.SATURDAY)
        self.assertEqual(template.get_day_of_week_display(), "Saturday")

    def test_deleting_referenced_chore_is_protected(self):
        WeeklyAssignmentTemplate.objects.create(
            chore=self.chore,
            assigned_to=self.person,
            day_of_week=WeeklyAssignmentTemplate.DayOfWeek.MONDAY,
            start_time=datetime.time(8, 0),
            duration_minutes=10,
        )

        with self.assertRaises(ProtectedError):
            self.chore.delete()

    def test_deleting_referenced_person_is_protected(self):
        WeeklyAssignmentTemplate.objects.create(
            chore=self.chore,
            assigned_to=self.person,
            day_of_week=WeeklyAssignmentTemplate.DayOfWeek.MONDAY,
            start_time=datetime.time(8, 0),
            duration_minutes=10,
        )

        with self.assertRaises(ProtectedError):
            self.person.delete()


class ChoresAdminTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username="admin", email="admin@example.com", password="password"
        )
        self.client.force_login(self.superuser)
        self.chore = Chore.objects.create(name="Dishes")
        self.person = Person.objects.create(name="Alex", role=Person.Role.ADULT)

    def test_superuser_can_create_chore(self):
        response = self.client.post(
            reverse("admin:chores_chore_add"),
            {"name": "Laundry", "description": "", "is_active": "on"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Chore.objects.filter(name="Laundry").exists())

    def test_superuser_can_create_weekly_assignment_template(self):
        response = self.client.post(
            reverse("admin:chores_weeklyassignmenttemplate_add"),
            {
                "chore": self.chore.pk,
                "assigned_to": self.person.pk,
                "day_of_week": WeeklyAssignmentTemplate.DayOfWeek.SUNDAY,
                "start_time": "18:00:00",
                "duration_minutes": 15,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            WeeklyAssignmentTemplate.objects.filter(
                chore=self.chore, assigned_to=self.person
            ).exists()
        )

    def test_changelist_shows_day_of_week_as_label_not_raw_integer(self):
        WeeklyAssignmentTemplate.objects.create(
            chore=self.chore,
            assigned_to=self.person,
            day_of_week=WeeklyAssignmentTemplate.DayOfWeek.SUNDAY,
            start_time=datetime.time(18, 0),
            duration_minutes=15,
        )

        response = self.client.get(reverse("admin:chores_weeklyassignmenttemplate_changelist"))

        self.assertContains(response, "Sunday")
        self.assertNotContains(response, "<td>0</td>")

    def test_add_form_renders_day_of_week_as_labelled_select(self):
        response = self.client.get(reverse("admin:chores_weeklyassignmenttemplate_add"))

        self.assertContains(response, '<option value="0">Sunday</option>', html=True)
        self.assertContains(response, '<option value="6">Saturday</option>', html=True)
