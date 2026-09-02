import datetime

from django.contrib.auth.models import User
from django.db.models import ProtectedError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from people.models import Person

from .dateutils import week_start_of
from .models import Chore, ChoreInstance, WeeklyAssignmentTemplate
from .services import ensure_instances_generated


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


class WeekStartOfTests(TestCase):
    def test_sunday_maps_to_itself(self):
        sunday = datetime.date(2026, 8, 30)
        self.assertEqual(sunday.weekday(), 6)

        self.assertEqual(week_start_of(sunday), sunday)

    def test_monday_maps_to_preceding_sunday(self):
        monday = datetime.date(2026, 8, 31)

        self.assertEqual(week_start_of(monday), datetime.date(2026, 8, 30))

    def test_saturday_maps_to_preceding_sunday(self):
        saturday = datetime.date(2026, 9, 5)

        self.assertEqual(week_start_of(saturday), datetime.date(2026, 8, 30))


class EnsureInstancesGeneratedTests(TestCase):
    def setUp(self):
        self.chore = Chore.objects.create(name="Dishes")
        self.person = Person.objects.create(name="Alex", role=Person.Role.ADULT)
        self.template = WeeklyAssignmentTemplate.objects.create(
            chore=self.chore,
            assigned_to=self.person,
            day_of_week=WeeklyAssignmentTemplate.DayOfWeek.TUESDAY,
            start_time=datetime.time(18, 30),
            duration_minutes=15,
        )
        # A Sunday, per week_start_of's contract.
        self.week_start = datetime.date(2026, 8, 30)

    def test_creates_instance_on_the_templates_day_of_week(self):
        ensure_instances_generated(self.week_start)

        instance = ChoreInstance.objects.get(template=self.template)
        self.assertEqual(instance.date, datetime.date(2026, 9, 1))  # Tuesday
        self.assertEqual(instance.chore, self.chore)
        self.assertEqual(instance.assigned_person, self.person)
        self.assertEqual(instance.budgeted_minutes, 15)
        self.assertFalse(instance.is_done)
        self.assertIsNone(instance.done_at)
        self.assertIsNone(instance.done_by)

    def test_scheduled_start_is_timezone_aware_and_combines_date_and_start_time(self):
        ensure_instances_generated(self.week_start)

        instance = ChoreInstance.objects.get(template=self.template)
        self.assertTrue(timezone.is_aware(instance.scheduled_start))
        expected = timezone.make_aware(
            datetime.datetime.combine(datetime.date(2026, 9, 1), datetime.time(18, 30))
        )
        self.assertEqual(instance.scheduled_start, expected)

    def test_calling_twice_for_same_week_creates_no_duplicates(self):
        ensure_instances_generated(self.week_start)
        ensure_instances_generated(self.week_start)

        self.assertEqual(
            ChoreInstance.objects.filter(template=self.template).count(), 1
        )

    def test_editing_template_after_generation_does_not_change_existing_instance(self):
        ensure_instances_generated(self.week_start)
        instance = ChoreInstance.objects.get(template=self.template)

        other_person = Person.objects.create(name="Sam", role=Person.Role.ADULT)
        self.template.assigned_to = other_person
        self.template.duration_minutes = 45
        self.template.save()

        instance.refresh_from_db()
        self.assertEqual(instance.assigned_person, self.person)
        self.assertEqual(instance.budgeted_minutes, 15)

    def test_generating_a_later_week_after_edit_picks_up_new_values(self):
        ensure_instances_generated(self.week_start)

        other_person = Person.objects.create(name="Sam", role=Person.Role.ADULT)
        self.template.assigned_to = other_person
        self.template.duration_minutes = 45
        self.template.save()

        next_week_start = self.week_start + datetime.timedelta(days=7)
        ensure_instances_generated(next_week_start)

        new_instance = ChoreInstance.objects.get(
            template=self.template, date=datetime.date(2026, 9, 8)
        )
        self.assertEqual(new_instance.assigned_person, other_person)
        self.assertEqual(new_instance.budgeted_minutes, 45)

        # The earlier week's instance is still untouched.
        old_instance = ChoreInstance.objects.get(
            template=self.template, date=datetime.date(2026, 9, 1)
        )
        self.assertEqual(old_instance.assigned_person, self.person)
        self.assertEqual(old_instance.budgeted_minutes, 15)

    def test_inactive_chore_produces_no_instance(self):
        self.chore.is_active = False
        self.chore.save()

        ensure_instances_generated(self.week_start)

        self.assertFalse(ChoreInstance.objects.filter(template=self.template).exists())

    def test_inactive_assigned_person_produces_no_instance(self):
        self.person.is_active = False
        self.person.save()

        ensure_instances_generated(self.week_start)

        self.assertFalse(ChoreInstance.objects.filter(template=self.template).exists())

    def test_returns_created_instances(self):
        result = ensure_instances_generated(self.week_start)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].template, self.template)

    def test_second_call_returns_no_newly_created_instances(self):
        ensure_instances_generated(self.week_start)

        result = ensure_instances_generated(self.week_start)

        self.assertEqual(result, [])


class ChoreInstanceModelTests(TestCase):
    def setUp(self):
        self.chore = Chore.objects.create(name="Dishes")
        self.person = Person.objects.create(name="Alex", role=Person.Role.ADULT)
        self.template = WeeklyAssignmentTemplate.objects.create(
            chore=self.chore,
            assigned_to=self.person,
            day_of_week=WeeklyAssignmentTemplate.DayOfWeek.SUNDAY,
            start_time=datetime.time(9, 0),
            duration_minutes=10,
        )

    def _make_instance(self, date=datetime.date(2026, 8, 30)):
        return ChoreInstance.objects.create(
            template=self.template,
            chore=self.chore,
            date=date,
            scheduled_start=timezone.make_aware(
                datetime.datetime.combine(date, datetime.time(9, 0))
            ),
            budgeted_minutes=10,
            assigned_person=self.person,
        )

    def test_unique_together_on_template_and_date(self):
        self._make_instance()

        with self.assertRaises(Exception):
            self._make_instance()

    def test_same_template_different_date_is_allowed(self):
        self._make_instance(date=datetime.date(2026, 8, 30))
        self._make_instance(date=datetime.date(2026, 9, 6))

        self.assertEqual(ChoreInstance.objects.filter(template=self.template).count(), 2)

    def test_deleting_referenced_chore_is_protected(self):
        self._make_instance()

        with self.assertRaises(ProtectedError):
            self.chore.delete()

    def test_deleting_referenced_template_is_protected(self):
        self._make_instance()

        with self.assertRaises(ProtectedError):
            self.template.delete()

    def test_deleting_referenced_assigned_person_is_protected(self):
        self._make_instance()

        with self.assertRaises(ProtectedError):
            self.person.delete()


class ChoreInstanceAdminTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username="admin2", email="admin2@example.com", password="password"
        )
        self.client.force_login(self.superuser)
        self.chore = Chore.objects.create(name="Dishes")
        self.person = Person.objects.create(name="Alex", role=Person.Role.ADULT)
        self.template = WeeklyAssignmentTemplate.objects.create(
            chore=self.chore,
            assigned_to=self.person,
            day_of_week=WeeklyAssignmentTemplate.DayOfWeek.SUNDAY,
            start_time=datetime.time(9, 0),
            duration_minutes=10,
        )
        ensure_instances_generated(datetime.date(2026, 8, 30))

    def test_changelist_shows_generated_instance(self):
        response = self.client.get(reverse("admin:chores_choreinstance_changelist"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dishes")
