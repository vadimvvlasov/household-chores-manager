import datetime

import time_machine
from django.contrib.auth.models import User
from django.db.models import ProtectedError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from people.models import Person

from .dateutils import week_start_of
from .models import (
    Chore,
    ChoreInstance,
    ProposalStatus,
    ProposedAssignmentChange,
    ProposedBudgetChange,
    SwapLog,
    TimeLog,
    WeeklyAssignmentTemplate,
)
from .notifications import get_unfinished_today, get_upcoming_blocks
from .services import (
    apply_assignment_change,
    apply_budget_change,
    ensure_instances_generated,
    is_over_budget,
    minutes_logged_this_week,
    minutes_logged_today,
    swap_assignment,
)


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


class SwapAssignmentServiceTests(TestCase):
    def setUp(self):
        self.chore = Chore.objects.create(name="Dishes")
        self.person = Person.objects.create(name="Alex", role=Person.Role.ADULT)
        self.other_person = Person.objects.create(name="Sam", role=Person.Role.KID)
        self.third_person = Person.objects.create(name="Riley", role=Person.Role.KID)
        self.swapper = Person.objects.create(name="Jamie", role=Person.Role.ADULT)
        self.template = WeeklyAssignmentTemplate.objects.create(
            chore=self.chore,
            assigned_to=self.person,
            day_of_week=WeeklyAssignmentTemplate.DayOfWeek.SUNDAY,
            start_time=datetime.time(9, 0),
            duration_minutes=10,
        )

    def _make_instance(self, date, **extra):
        defaults = {
            "template": self.template,
            "chore": self.chore,
            "date": date,
            "scheduled_start": timezone.make_aware(
                datetime.datetime.combine(date, datetime.time(9, 0))
            ),
            "budgeted_minutes": 10,
            "assigned_person": self.person,
        }
        defaults.update(extra)
        return ChoreInstance.objects.create(**defaults)

    def test_swap_on_future_undone_instance_succeeds(self):
        instance = self._make_instance(timezone.localdate() + datetime.timedelta(days=1))

        swap_assignment(instance, self.other_person, swapped_by=self.swapper)

        instance.refresh_from_db()
        self.assertEqual(instance.assigned_person, self.other_person)

    def test_swap_on_todays_undone_instance_succeeds(self):
        instance = self._make_instance(timezone.localdate())

        swap_assignment(instance, self.other_person, swapped_by=self.swapper)

        instance.refresh_from_db()
        self.assertEqual(instance.assigned_person, self.other_person)

    def test_swap_on_past_instance_raises_and_makes_no_change(self):
        instance = self._make_instance(timezone.localdate() - datetime.timedelta(days=1))

        with self.assertRaises(ValueError):
            swap_assignment(instance, self.other_person, swapped_by=self.swapper)

        instance.refresh_from_db()
        self.assertEqual(instance.assigned_person, self.person)

    def test_swap_on_past_instance_creates_no_swap_log(self):
        instance = self._make_instance(timezone.localdate() - datetime.timedelta(days=1))

        with self.assertRaises(ValueError):
            swap_assignment(instance, self.other_person, swapped_by=self.swapper)

        self.assertEqual(SwapLog.objects.filter(chore_instance=instance).count(), 0)

    def test_swap_on_done_instance_raises_and_makes_no_change(self):
        instance = self._make_instance(
            timezone.localdate(),
            is_done=True,
            done_at=timezone.now(),
            done_by=self.person,
        )

        with self.assertRaises(ValueError):
            swap_assignment(instance, self.other_person, swapped_by=self.swapper)

        instance.refresh_from_db()
        self.assertEqual(instance.assigned_person, self.person)

    def test_swap_on_done_instance_creates_no_swap_log(self):
        instance = self._make_instance(
            timezone.localdate(),
            is_done=True,
            done_at=timezone.now(),
            done_by=self.person,
        )

        with self.assertRaises(ValueError):
            swap_assignment(instance, self.other_person, swapped_by=self.swapper)

        self.assertEqual(SwapLog.objects.filter(chore_instance=instance).count(), 0)

    def test_swap_does_not_alter_time_logs_or_done_by(self):
        instance = self._make_instance(
            timezone.localdate() + datetime.timedelta(days=1)
        )
        log = TimeLog.objects.create(
            chore_instance=instance,
            logged_by=self.person,
            minutes=15,
            logged_at=timezone.now(),
        )

        swap_assignment(instance, self.other_person, swapped_by=self.swapper)

        log.refresh_from_db()
        self.assertEqual(log.logged_by, self.person)
        instance.refresh_from_db()
        self.assertIsNone(instance.done_by)
        self.assertIsNone(instance.done_at)

    def test_successful_swap_creates_one_swap_log_with_expected_fields(self):
        instance = self._make_instance(timezone.localdate() + datetime.timedelta(days=1))
        before = timezone.now()

        swap_assignment(instance, self.other_person, swapped_by=self.swapper)

        after = timezone.now()
        logs = SwapLog.objects.filter(chore_instance=instance)
        self.assertEqual(logs.count(), 1)
        log = logs.get()
        self.assertEqual(log.from_person, self.person)
        self.assertEqual(log.to_person, self.other_person)
        self.assertEqual(log.swapped_by, self.swapper)
        self.assertGreaterEqual(log.swapped_at, before)
        self.assertLessEqual(log.swapped_at, after)

    def test_second_swap_creates_separate_log_row_and_leaves_first_untouched(self):
        instance = self._make_instance(timezone.localdate() + datetime.timedelta(days=1))

        swap_assignment(instance, self.other_person, swapped_by=self.swapper)
        first_log = SwapLog.objects.get(chore_instance=instance)

        instance.refresh_from_db()
        swap_assignment(instance, self.third_person, swapped_by=self.swapper)

        self.assertEqual(SwapLog.objects.filter(chore_instance=instance).count(), 2)
        first_log.refresh_from_db()
        self.assertEqual(first_log.from_person, self.person)
        self.assertEqual(first_log.to_person, self.other_person)

        second_log = (
            SwapLog.objects.filter(chore_instance=instance).exclude(pk=first_log.pk).get()
        )
        self.assertEqual(second_log.from_person, self.other_person)
        self.assertEqual(second_log.to_person, self.third_person)
        self.assertEqual(second_log.swapped_by, self.swapper)


class SwapLogCascadeDeleteTests(TestCase):
    def setUp(self):
        self.chore = Chore.objects.create(name="Dishes")
        self.person = Person.objects.create(name="Alex", role=Person.Role.ADULT)
        self.other_person = Person.objects.create(name="Sam", role=Person.Role.KID)
        self.template = WeeklyAssignmentTemplate.objects.create(
            chore=self.chore,
            assigned_to=self.person,
            day_of_week=WeeklyAssignmentTemplate.DayOfWeek.SUNDAY,
            start_time=datetime.time(9, 0),
            duration_minutes=10,
        )
        self.instance = ChoreInstance.objects.create(
            template=self.template,
            chore=self.chore,
            date=timezone.localdate() + datetime.timedelta(days=1),
            scheduled_start=timezone.now(),
            budgeted_minutes=10,
            assigned_person=self.person,
        )

    def test_deleting_chore_instance_cascades_to_its_swap_logs(self):
        swap_assignment(self.instance, self.other_person, swapped_by=self.person)
        self.assertEqual(SwapLog.objects.filter(chore_instance=self.instance).count(), 1)

        self.instance.delete()

        self.assertEqual(SwapLog.objects.count(), 0)


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


class ChoreInstanceViewTestBase(TestCase):
    """Shared setup for the dashboard and per-instance action views."""

    def setUp(self):
        self.user = User.objects.create_user(username="family", password="password")
        self.client.force_login(self.user)

        self.chore = Chore.objects.create(name="Dishes")
        self.active_person = Person.objects.create(name="Alex", role=Person.Role.ADULT)
        self.other_person = Person.objects.create(name="Sam", role=Person.Role.KID)

        self.template = WeeklyAssignmentTemplate.objects.create(
            chore=self.chore,
            assigned_to=self.active_person,
            day_of_week=WeeklyAssignmentTemplate.DayOfWeek.SUNDAY,
            start_time=datetime.time(9, 0),
            duration_minutes=10,
        )

        self.today = timezone.localdate()

        session = self.client.session
        session["active_person_id"] = self.active_person.id
        session.save()

    def _make_instance(self, date, assigned_person=None, **extra):
        assigned_person = assigned_person or self.active_person
        defaults = {
            "template": self.template,
            "chore": self.chore,
            "date": date,
            "scheduled_start": timezone.make_aware(
                datetime.datetime.combine(date, datetime.time(9, 0))
            ),
            "budgeted_minutes": 10,
            "assigned_person": assigned_person,
        }
        defaults.update(extra)
        return ChoreInstance.objects.create(**defaults)


class DashboardViewTests(ChoreInstanceViewTestBase):
    def test_lists_todays_instances_for_everyone_not_just_active_person(self):
        self._make_instance(self.today, assigned_person=self.active_person)
        other_template = WeeklyAssignmentTemplate.objects.create(
            chore=self.chore,
            assigned_to=self.other_person,
            day_of_week=WeeklyAssignmentTemplate.DayOfWeek.MONDAY,
            start_time=datetime.time(10, 0),
            duration_minutes=15,
        )
        ChoreInstance.objects.create(
            template=other_template,
            chore=self.chore,
            date=self.today,
            scheduled_start=timezone.make_aware(
                datetime.datetime.combine(self.today, datetime.time(10, 0))
            ),
            budgeted_minutes=15,
            assigned_person=self.other_person,
        )

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alex")
        self.assertContains(response, "Sam")

    def test_does_not_list_instances_from_other_days(self):
        vacuum = Chore.objects.create(name="Vacuum")
        vacuum_template = WeeklyAssignmentTemplate.objects.create(
            chore=vacuum,
            assigned_to=self.active_person,
            day_of_week=WeeklyAssignmentTemplate.DayOfWeek.MONDAY,
            start_time=datetime.time(9, 0),
            duration_minutes=10,
        )
        ChoreInstance.objects.create(
            template=vacuum_template,
            chore=vacuum,
            date=self.today - datetime.timedelta(days=1),
            scheduled_start=timezone.make_aware(
                datetime.datetime.combine(
                    self.today - datetime.timedelta(days=1), datetime.time(9, 0)
                )
            ),
            budgeted_minutes=10,
            assigned_person=self.active_person,
        )

        response = self.client.get("/")

        self.assertNotContains(response, "Vacuum")

    def test_shows_done_and_not_done_state(self):
        self._make_instance(self.today, is_done=False)

        done_template = WeeklyAssignmentTemplate.objects.create(
            chore=self.chore,
            assigned_to=self.other_person,
            day_of_week=WeeklyAssignmentTemplate.DayOfWeek.TUESDAY,
            start_time=datetime.time(11, 0),
            duration_minutes=10,
        )
        ChoreInstance.objects.create(
            template=done_template,
            chore=self.chore,
            date=self.today,
            scheduled_start=timezone.make_aware(
                datetime.datetime.combine(self.today, datetime.time(11, 0))
            ),
            budgeted_minutes=10,
            assigned_person=self.other_person,
            is_done=True,
            done_at=timezone.now(),
            done_by=self.other_person,
        )

        response = self.client.get("/")

        self.assertContains(response, "Not done")
        self.assertContains(response, "Done")

    def test_generates_this_weeks_instances_before_listing(self):
        self.assertFalse(ChoreInstance.objects.exists())

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(ChoreInstance.objects.filter(template=self.template).exists())

    def test_shows_working_swap_link_for_todays_instance(self):
        instance = self._make_instance(self.today)

        response = self.client.get("/")

        self.assertContains(response, reverse("swap", args=[instance.id]))


class CheckInstanceViewTests(ChoreInstanceViewTestBase):
    def test_check_marks_done_with_active_person_and_redirects_home(self):
        instance = self._make_instance(self.today)

        response = self.client.post(reverse("check_instance", args=[instance.id]))

        self.assertRedirects(response, "/", fetch_redirect_response=False)
        instance.refresh_from_db()
        self.assertTrue(instance.is_done)
        self.assertIsNotNone(instance.done_at)
        self.assertEqual(instance.done_by, self.active_person)

    def test_get_is_not_allowed(self):
        instance = self._make_instance(self.today)

        response = self.client.get(reverse("check_instance", args=[instance.id]))

        self.assertEqual(response.status_code, 405)

    def test_check_against_past_instance_is_rejected_and_makes_no_change(self):
        instance = self._make_instance(self.today - datetime.timedelta(days=1))

        response = self.client.post(reverse("check_instance", args=[instance.id]))

        self.assertIn(response.status_code, (302, 403))
        instance.refresh_from_db()
        self.assertFalse(instance.is_done)
        self.assertIsNone(instance.done_at)
        self.assertIsNone(instance.done_by)


class UncheckInstanceViewTests(ChoreInstanceViewTestBase):
    def test_uncheck_resets_done_state_and_redirects_home(self):
        instance = self._make_instance(
            self.today,
            is_done=True,
            done_at=timezone.now(),
            done_by=self.active_person,
        )

        response = self.client.post(reverse("uncheck_instance", args=[instance.id]))

        self.assertRedirects(response, "/", fetch_redirect_response=False)
        instance.refresh_from_db()
        self.assertFalse(instance.is_done)
        self.assertIsNone(instance.done_at)
        self.assertIsNone(instance.done_by)

    def test_uncheck_against_past_instance_is_rejected_and_makes_no_change(self):
        instance = self._make_instance(
            self.today - datetime.timedelta(days=1),
            is_done=True,
            done_at=timezone.now(),
            done_by=self.active_person,
        )

        response = self.client.post(reverse("uncheck_instance", args=[instance.id]))

        self.assertIn(response.status_code, (302, 403))
        instance.refresh_from_db()
        self.assertTrue(instance.is_done)
        self.assertIsNotNone(instance.done_at)
        self.assertEqual(instance.done_by, self.active_person)


class LogTimeViewTests(ChoreInstanceViewTestBase):
    def test_get_renders_form(self):
        instance = self._make_instance(self.today)

        response = self.client.get(reverse("log_time", args=[instance.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dishes")

    def test_post_creates_time_log_with_active_person_and_redirects_home(self):
        instance = self._make_instance(self.today)

        response = self.client.post(
            reverse("log_time", args=[instance.id]), {"minutes": "15", "note": "Quick pass"}
        )

        self.assertRedirects(response, "/", fetch_redirect_response=False)
        log = TimeLog.objects.get(chore_instance=instance)
        self.assertEqual(log.minutes, 15)
        self.assertEqual(log.note, "Quick pass")
        self.assertEqual(log.logged_by, self.active_person)
        self.assertIsNotNone(log.logged_at)

    def test_note_is_optional(self):
        instance = self._make_instance(self.today)

        response = self.client.post(reverse("log_time", args=[instance.id]), {"minutes": "10"})

        self.assertRedirects(response, "/", fetch_redirect_response=False)
        log = TimeLog.objects.get(chore_instance=instance)
        self.assertEqual(log.note, "")

    def test_multiple_time_logs_allowed_and_independent_of_is_done(self):
        instance = self._make_instance(self.today, is_done=False)

        self.client.post(reverse("log_time", args=[instance.id]), {"minutes": "10"})
        self.client.post(reverse("log_time", args=[instance.id]), {"minutes": "5"})

        self.assertEqual(TimeLog.objects.filter(chore_instance=instance).count(), 2)
        instance.refresh_from_db()
        self.assertFalse(instance.is_done)  # logging time never checks it off

    def test_checking_off_does_not_create_a_time_log(self):
        instance = self._make_instance(self.today)

        self.client.post(reverse("check_instance", args=[instance.id]))

        self.assertEqual(TimeLog.objects.filter(chore_instance=instance).count(), 0)

    def test_post_against_past_instance_is_rejected_and_creates_no_log(self):
        instance = self._make_instance(self.today - datetime.timedelta(days=1))

        response = self.client.post(reverse("log_time", args=[instance.id]), {"minutes": "10"})

        self.assertIn(response.status_code, (302, 403))
        self.assertEqual(TimeLog.objects.filter(chore_instance=instance).count(), 0)

    def test_invalid_minutes_does_not_create_a_log(self):
        instance = self._make_instance(self.today)

        response = self.client.post(reverse("log_time", args=[instance.id]), {"minutes": "not-a-number"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(TimeLog.objects.filter(chore_instance=instance).count(), 0)


class SwapViewTests(ChoreInstanceViewTestBase):
    def test_get_renders_form_listing_active_people(self):
        instance = self._make_instance(self.today)

        response = self.client.get(reverse("swap", args=[instance.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alex")
        self.assertContains(response, "Sam")

    def test_get_does_not_list_inactive_people(self):
        inactive = Person.objects.create(
            name="Riley", role=Person.Role.ADULT, is_active=False
        )
        instance = self._make_instance(self.today)

        response = self.client.get(reverse("swap", args=[instance.id]))

        self.assertNotContains(response, "Riley")
        self.assertEqual(inactive.is_active, False)

    def test_post_swaps_assignment_and_redirects_home(self):
        instance = self._make_instance(self.today, assigned_person=self.active_person)

        response = self.client.post(
            reverse("swap", args=[instance.id]), {"new_person": self.other_person.id}
        )

        self.assertRedirects(response, "/", fetch_redirect_response=False)
        instance.refresh_from_db()
        self.assertEqual(instance.assigned_person, self.other_person)

    def test_post_future_instance_succeeds(self):
        instance = self._make_instance(
            self.today + datetime.timedelta(days=1), assigned_person=self.active_person
        )

        response = self.client.post(
            reverse("swap", args=[instance.id]), {"new_person": self.other_person.id}
        )

        self.assertRedirects(response, "/", fetch_redirect_response=False)
        instance.refresh_from_db()
        self.assertEqual(instance.assigned_person, self.other_person)

    def test_post_against_past_instance_is_rejected_with_error_and_no_change(self):
        instance = self._make_instance(
            self.today - datetime.timedelta(days=1), assigned_person=self.active_person
        )

        response = self.client.post(
            reverse("swap", args=[instance.id]), {"new_person": self.other_person.id}
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "past")
        instance.refresh_from_db()
        self.assertEqual(instance.assigned_person, self.active_person)

    def test_post_against_done_instance_is_rejected_with_error_and_no_change(self):
        instance = self._make_instance(
            self.today,
            assigned_person=self.active_person,
            is_done=True,
            done_at=timezone.now(),
            done_by=self.active_person,
        )

        response = self.client.post(
            reverse("swap", args=[instance.id]), {"new_person": self.other_person.id}
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "done")
        instance.refresh_from_db()
        self.assertEqual(instance.assigned_person, self.active_person)

    def test_any_active_person_can_swap_not_restricted_to_assigned_person(self):
        # active_person (the logged-in session's active person) is not the
        # instance's assigned_person, and is a KID role, yet the swap still
        # succeeds — swaps aren't restricted to adults or the current
        # assignee.
        instance = self._make_instance(self.today, assigned_person=self.other_person)

        response = self.client.post(
            reverse("swap", args=[instance.id]), {"new_person": self.active_person.id}
        )

        self.assertRedirects(response, "/", fetch_redirect_response=False)
        instance.refresh_from_db()
        self.assertEqual(instance.assigned_person, self.active_person)

    def test_swap_does_not_create_a_time_log(self):
        instance = self._make_instance(self.today)

        self.client.post(
            reverse("swap", args=[instance.id]), {"new_person": self.other_person.id}
        )

        self.assertEqual(TimeLog.objects.filter(chore_instance=instance).count(), 0)

    def test_post_records_active_person_as_swapped_by(self):
        # active_person (the session's active person) is not to_person here,
        # so this also confirms swapped_by isn't just echoing to_person.
        instance = self._make_instance(self.today, assigned_person=self.active_person)

        self.client.post(
            reverse("swap", args=[instance.id]), {"new_person": self.other_person.id}
        )

        log = SwapLog.objects.get(chore_instance=instance)
        self.assertEqual(log.swapped_by, self.active_person)
        self.assertEqual(log.to_person, self.other_person)


class MinutesLoggedTodayTests(TestCase):
    def setUp(self):
        self.person = Person.objects.create(name="Alex", role=Person.Role.ADULT)
        self.chore = Chore.objects.create(name="Dishes")
        self.other_chore = Chore.objects.create(name="Vacuum")
        self.template = WeeklyAssignmentTemplate.objects.create(
            chore=self.chore,
            assigned_to=self.person,
            day_of_week=WeeklyAssignmentTemplate.DayOfWeek.SUNDAY,
            start_time=datetime.time(9, 0),
            duration_minutes=10,
        )
        self.other_template = WeeklyAssignmentTemplate.objects.create(
            chore=self.other_chore,
            assigned_to=self.person,
            day_of_week=WeeklyAssignmentTemplate.DayOfWeek.MONDAY,
            start_time=datetime.time(9, 0),
            duration_minutes=10,
        )

    def _make_instance(self, template, chore, date):
        return ChoreInstance.objects.create(
            template=template,
            chore=chore,
            date=date,
            scheduled_start=timezone.make_aware(datetime.datetime.combine(date, datetime.time(9, 0))),
            budgeted_minutes=10,
            assigned_person=self.person,
        )

    def test_sums_two_logs_on_different_chore_instances_same_day(self):
        day = datetime.date(2026, 9, 1)
        instance1 = self._make_instance(self.template, self.chore, day)
        instance2 = self._make_instance(self.other_template, self.other_chore, day)
        TimeLog.objects.create(
            chore_instance=instance1,
            logged_by=self.person,
            minutes=20,
            logged_at=timezone.make_aware(datetime.datetime.combine(day, datetime.time(8, 0))),
        )
        TimeLog.objects.create(
            chore_instance=instance2,
            logged_by=self.person,
            minutes=15,
            logged_at=timezone.make_aware(datetime.datetime.combine(day, datetime.time(14, 0))),
        )

        self.assertEqual(minutes_logged_today(self.person, day), 35)

    def test_scoped_by_logged_at_date_not_instance_scheduled_date(self):
        # A swap can move assigned_person after the fact, so this must
        # reflect when the time was actually logged, not the instance's
        # scheduled date.
        instance = self._make_instance(self.template, self.chore, datetime.date(2026, 9, 1))
        logged_day = datetime.date(2026, 9, 5)
        TimeLog.objects.create(
            chore_instance=instance,
            logged_by=self.person,
            minutes=30,
            logged_at=timezone.make_aware(datetime.datetime.combine(logged_day, datetime.time(10, 0))),
        )

        self.assertEqual(minutes_logged_today(self.person, logged_day), 30)
        self.assertEqual(minutes_logged_today(self.person, instance.date), 0)

    def test_no_logs_returns_zero(self):
        self.assertEqual(minutes_logged_today(self.person, datetime.date(2026, 9, 1)), 0)


class MinutesLoggedThisWeekTests(TestCase):
    def setUp(self):
        self.person = Person.objects.create(name="Alex", role=Person.Role.ADULT)
        self.chore = Chore.objects.create(name="Dishes")
        self.template = WeeklyAssignmentTemplate.objects.create(
            chore=self.chore,
            assigned_to=self.person,
            day_of_week=WeeklyAssignmentTemplate.DayOfWeek.SUNDAY,
            start_time=datetime.time(9, 0),
            duration_minutes=10,
        )
        self.instance = ChoreInstance.objects.create(
            template=self.template,
            chore=self.chore,
            date=datetime.date(2026, 8, 30),
            scheduled_start=timezone.make_aware(datetime.datetime(2026, 8, 30, 9, 0)),
            budgeted_minutes=10,
            assigned_person=self.person,
        )

    def _log(self, minutes, logged_at):
        return TimeLog.objects.create(
            chore_instance=self.instance,
            logged_by=self.person,
            minutes=minutes,
            logged_at=logged_at,
        )

    def test_sums_within_the_sunday_saturday_week(self):
        self._log(10, timezone.make_aware(datetime.datetime(2026, 8, 30, 1, 0)))
        self._log(5, timezone.make_aware(datetime.datetime(2026, 9, 5, 23, 0)))

        self.assertEqual(minutes_logged_this_week(self.person, datetime.date(2026, 9, 2)), 15)

    def test_derives_week_start_via_week_start_of_rather_than_requiring_a_sunday(self):
        self._log(10, timezone.make_aware(datetime.datetime(2026, 8, 30, 1, 0)))

        # Passing a mid-week date should still land in the Aug 30 - Sep 5 week.
        self.assertEqual(minutes_logged_this_week(self.person, datetime.date(2026, 9, 2)), 10)
        self.assertEqual(
            minutes_logged_this_week(self.person, datetime.date(2026, 9, 2)),
            minutes_logged_this_week(self.person, week_start_of(datetime.date(2026, 9, 2))),
        )

    def test_log_just_before_and_after_sunday_boundary_count_toward_correct_week_only(self):
        # Saturday 23:59:59 belongs to the prior week (Aug 23 - Aug 29).
        self._log(20, timezone.make_aware(datetime.datetime(2026, 8, 29, 23, 59, 59)))
        # Sunday 00:00:00 belongs to the new week (Aug 30 - Sep 5).
        self._log(30, timezone.make_aware(datetime.datetime(2026, 8, 30, 0, 0, 0)))

        self.assertEqual(minutes_logged_this_week(self.person, datetime.date(2026, 8, 29)), 20)
        self.assertEqual(minutes_logged_this_week(self.person, datetime.date(2026, 8, 30)), 30)

    def test_no_logs_returns_zero(self):
        self.assertEqual(minutes_logged_this_week(self.person, datetime.date(2026, 8, 30)), 0)


class IsOverBudgetTests(TestCase):
    def setUp(self):
        self.person = Person.objects.create(
            name="Alex",
            role=Person.Role.ADULT,
            daily_budget_minutes=30,
            weekly_budget_minutes=120,
        )
        self.chore = Chore.objects.create(name="Dishes")
        self.template = WeeklyAssignmentTemplate.objects.create(
            chore=self.chore,
            assigned_to=self.person,
            day_of_week=WeeklyAssignmentTemplate.DayOfWeek.SUNDAY,
            start_time=datetime.time(9, 0),
            duration_minutes=10,
        )
        self.day = datetime.date(2026, 8, 30)  # a Sunday
        self.instance = ChoreInstance.objects.create(
            template=self.template,
            chore=self.chore,
            date=self.day,
            scheduled_start=timezone.make_aware(datetime.datetime.combine(self.day, datetime.time(9, 0))),
            budgeted_minutes=10,
            assigned_person=self.person,
        )

    def _log(self, minutes):
        TimeLog.objects.create(
            chore_instance=self.instance,
            logged_by=self.person,
            minutes=minutes,
            logged_at=timezone.make_aware(datetime.datetime.combine(self.day, datetime.time(10, 0))),
        )

    def test_daily_exactly_at_limit_is_not_over(self):
        self._log(30)

        self.assertFalse(is_over_budget(self.person, "daily", self.day))

    def test_daily_one_minute_over_warns(self):
        self._log(31)

        self.assertTrue(is_over_budget(self.person, "daily", self.day))

    def test_daily_none_budget_never_warns(self):
        self.person.daily_budget_minutes = None
        self.person.save()
        self._log(10_000)

        self.assertFalse(is_over_budget(self.person, "daily", self.day))

    def test_weekly_exactly_at_limit_is_not_over(self):
        self._log(120)

        self.assertFalse(is_over_budget(self.person, "weekly", week_start_of(self.day)))

    def test_weekly_one_minute_over_warns(self):
        self._log(121)

        self.assertTrue(is_over_budget(self.person, "weekly", week_start_of(self.day)))

    def test_weekly_none_budget_never_warns(self):
        self.person.weekly_budget_minutes = None
        self.person.save()
        self._log(10_000)

        self.assertFalse(is_over_budget(self.person, "weekly", week_start_of(self.day)))


class DashboardBudgetWarningTests(ChoreInstanceViewTestBase):
    def test_people_section_lists_active_person_with_no_instance_today(self):
        response = self.client.get("/")

        self.assertContains(response, "Sam")  # other_person has no chore instance today

    def test_over_budget_person_shows_warning_badge(self):
        self.active_person.daily_budget_minutes = 10
        self.active_person.save()
        instance = self._make_instance(self.today)
        TimeLog.objects.create(
            chore_instance=instance, logged_by=self.active_person, minutes=15, logged_at=timezone.now()
        )

        response = self.client.get("/")

        self.assertContains(response, "Over budget")

    def test_person_under_budget_does_not_show_warning(self):
        self.active_person.daily_budget_minutes = 100
        self.active_person.save()
        instance = self._make_instance(self.today)
        TimeLog.objects.create(
            chore_instance=instance, logged_by=self.active_person, minutes=15, logged_at=timezone.now()
        )

        response = self.client.get("/")

        self.assertNotContains(response, "Over budget")

    def test_inactive_person_is_not_listed_in_people_section(self):
        self.other_person.is_active = False
        self.other_person.save()

        response = self.client.get("/")

        self.assertNotContains(response, "Sam")


class BudgetDoesNotBlockActionsTests(ChoreInstanceViewTestBase):
    def test_logging_time_past_budget_then_check_off_still_succeeds(self):
        self.active_person.daily_budget_minutes = 10
        self.active_person.save()
        instance = self._make_instance(self.today)

        log_response = self.client.post(reverse("log_time", args=[instance.id]), {"minutes": "50"})
        self.assertRedirects(log_response, "/", fetch_redirect_response=False)

        check_response = self.client.post(reverse("check_instance", args=[instance.id]))
        self.assertRedirects(check_response, "/", fetch_redirect_response=False)

        instance.refresh_from_db()
        self.assertTrue(instance.is_done)


class ApplyAssignmentChangeServiceTests(TestCase):
    def setUp(self):
        self.chore = Chore.objects.create(name="Dishes")
        self.person = Person.objects.create(name="Alex", role=Person.Role.ADULT)
        self.other_person = Person.objects.create(name="Sam", role=Person.Role.KID)
        self.template = WeeklyAssignmentTemplate.objects.create(
            chore=self.chore,
            assigned_to=self.person,
            day_of_week=WeeklyAssignmentTemplate.DayOfWeek.SUNDAY,
            start_time=datetime.time(9, 0),
            duration_minutes=10,
        )

    def test_none_target_template_creates_new_template(self):
        result = apply_assignment_change(
            target_template=None,
            chore=self.chore,
            assigned_to=self.other_person,
            day_of_week=WeeklyAssignmentTemplate.DayOfWeek.TUESDAY,
            start_time=datetime.time(14, 0),
            duration_minutes=20,
        )

        self.assertEqual(WeeklyAssignmentTemplate.objects.count(), 2)
        self.assertEqual(result.assigned_to, self.other_person)
        self.assertEqual(result.duration_minutes, 20)

    def test_given_target_template_updates_it_in_place(self):
        result = apply_assignment_change(
            target_template=self.template,
            chore=self.chore,
            assigned_to=self.other_person,
            day_of_week=WeeklyAssignmentTemplate.DayOfWeek.WEDNESDAY,
            start_time=datetime.time(15, 0),
            duration_minutes=35,
        )

        self.assertEqual(result.pk, self.template.pk)
        self.assertEqual(WeeklyAssignmentTemplate.objects.count(), 1)
        self.template.refresh_from_db()
        self.assertEqual(self.template.assigned_to, self.other_person)
        self.assertEqual(self.template.day_of_week, WeeklyAssignmentTemplate.DayOfWeek.WEDNESDAY)
        self.assertEqual(self.template.duration_minutes, 35)


class ApplyBudgetChangeServiceTests(TestCase):
    def setUp(self):
        self.person = Person.objects.create(name="Alex", role=Person.Role.ADULT)

    def test_sets_only_daily_when_weekly_is_none(self):
        apply_budget_change(self.person, daily_budget_minutes=50, weekly_budget_minutes=None)

        self.person.refresh_from_db()
        self.assertEqual(self.person.daily_budget_minutes, 50)
        self.assertIsNone(self.person.weekly_budget_minutes)

    def test_sets_only_weekly_when_daily_is_none(self):
        apply_budget_change(self.person, daily_budget_minutes=None, weekly_budget_minutes=200)

        self.person.refresh_from_db()
        self.assertIsNone(self.person.daily_budget_minutes)
        self.assertEqual(self.person.weekly_budget_minutes, 200)

    def test_sets_both_when_both_given(self):
        apply_budget_change(self.person, daily_budget_minutes=10, weekly_budget_minutes=60)

        self.person.refresh_from_db()
        self.assertEqual(self.person.daily_budget_minutes, 10)
        self.assertEqual(self.person.weekly_budget_minutes, 60)

    def test_existing_value_untouched_when_its_field_is_none(self):
        self.person.daily_budget_minutes = 15
        self.person.save()

        apply_budget_change(self.person, daily_budget_minutes=None, weekly_budget_minutes=90)

        self.person.refresh_from_db()
        self.assertEqual(self.person.daily_budget_minutes, 15)
        self.assertEqual(self.person.weekly_budget_minutes, 90)


class ProposedAssignmentChangeModelTests(TestCase):
    def setUp(self):
        self.chore = Chore.objects.create(name="Dishes")
        self.adult = Person.objects.create(name="Alex", role=Person.Role.ADULT)
        self.kid = Person.objects.create(name="Sam", role=Person.Role.KID)
        self.template = WeeklyAssignmentTemplate.objects.create(
            chore=self.chore,
            assigned_to=self.adult,
            day_of_week=WeeklyAssignmentTemplate.DayOfWeek.SUNDAY,
            start_time=datetime.time(9, 0),
            duration_minutes=10,
        )

    def _make_proposal(self, **extra):
        defaults = dict(
            target_template=self.template,
            chore=self.chore,
            assigned_to=self.kid,
            day_of_week=WeeklyAssignmentTemplate.DayOfWeek.MONDAY,
            start_time=datetime.time(16, 0),
            duration_minutes=25,
            proposed_by=self.adult,
        )
        defaults.update(extra)
        return ProposedAssignmentChange.objects.create(**defaults)

    def test_defaults_to_pending_with_no_review_fields(self):
        proposal = self._make_proposal()

        self.assertEqual(proposal.status, ProposalStatus.PENDING)
        self.assertIsNone(proposal.reviewed_by)
        self.assertIsNone(proposal.reviewed_at)

    def test_approve_applies_change_via_service_and_sets_review_fields(self):
        proposal = self._make_proposal()

        proposal.approve(self.adult)

        self.template.refresh_from_db()
        self.assertEqual(self.template.assigned_to, self.kid)
        self.assertEqual(self.template.duration_minutes, 25)
        self.assertEqual(proposal.status, ProposalStatus.APPROVED)
        self.assertEqual(proposal.reviewed_by, self.adult)
        self.assertIsNotNone(proposal.reviewed_at)

    def test_approve_with_null_target_template_creates_a_new_template(self):
        proposal = self._make_proposal(target_template=None)
        before = WeeklyAssignmentTemplate.objects.count()

        proposal.approve(self.adult)

        self.assertEqual(WeeklyAssignmentTemplate.objects.count(), before + 1)

    def test_reject_makes_no_live_data_change(self):
        proposal = self._make_proposal()

        proposal.reject(self.adult, note="no thanks")

        self.template.refresh_from_db()
        self.assertEqual(self.template.assigned_to, self.adult)
        self.assertEqual(self.template.duration_minutes, 10)
        self.assertEqual(proposal.status, ProposalStatus.REJECTED)
        self.assertEqual(proposal.note, "no thanks")
        self.assertEqual(proposal.reviewed_by, self.adult)
        self.assertIsNotNone(proposal.reviewed_at)

    def test_deleting_referenced_target_template_is_protected(self):
        self._make_proposal()

        with self.assertRaises(ProtectedError):
            self.template.delete()

    def test_deleting_referenced_chore_is_protected(self):
        self._make_proposal()

        with self.assertRaises(ProtectedError):
            self.chore.delete()

    def test_deleting_referenced_assigned_to_is_protected(self):
        self._make_proposal()

        with self.assertRaises(ProtectedError):
            self.kid.delete()

    def test_deleting_referenced_proposed_by_is_protected(self):
        self._make_proposal()

        with self.assertRaises(ProtectedError):
            self.adult.delete()

    def test_deleting_referenced_reviewed_by_is_protected(self):
        reviewer = Person.objects.create(name="Jordan", role=Person.Role.ADULT)
        proposal = self._make_proposal()
        proposal.approve(reviewer)

        with self.assertRaises(ProtectedError):
            reviewer.delete()


class ProposedBudgetChangeModelTests(TestCase):
    def setUp(self):
        self.adult = Person.objects.create(name="Alex", role=Person.Role.ADULT)
        self.kid = Person.objects.create(name="Sam", role=Person.Role.KID)

    def _make_proposal(self, **extra):
        defaults = dict(person=self.kid, daily_budget_minutes=30, proposed_by=self.adult)
        defaults.update(extra)
        return ProposedBudgetChange.objects.create(**defaults)

    def test_defaults_to_pending_with_no_review_fields(self):
        proposal = self._make_proposal()

        self.assertEqual(proposal.status, ProposalStatus.PENDING)
        self.assertIsNone(proposal.reviewed_by)
        self.assertIsNone(proposal.reviewed_at)

    def test_approve_applies_only_non_none_fields_via_service(self):
        proposal = self._make_proposal(daily_budget_minutes=45, weekly_budget_minutes=None)

        proposal.approve(self.adult)

        self.kid.refresh_from_db()
        self.assertEqual(self.kid.daily_budget_minutes, 45)
        self.assertIsNone(self.kid.weekly_budget_minutes)
        self.assertEqual(proposal.status, ProposalStatus.APPROVED)
        self.assertEqual(proposal.reviewed_by, self.adult)
        self.assertIsNotNone(proposal.reviewed_at)

    def test_reject_makes_no_live_data_change(self):
        proposal = self._make_proposal(daily_budget_minutes=45)

        proposal.reject(self.adult, note="later")

        self.kid.refresh_from_db()
        self.assertIsNone(self.kid.daily_budget_minutes)
        self.assertEqual(proposal.status, ProposalStatus.REJECTED)
        self.assertEqual(proposal.note, "later")

    def test_deleting_referenced_person_is_protected(self):
        self._make_proposal()

        with self.assertRaises(ProtectedError):
            self.kid.delete()

    def test_deleting_referenced_proposed_by_is_protected(self):
        self._make_proposal()

        with self.assertRaises(ProtectedError):
            self.adult.delete()

    def test_deleting_referenced_reviewed_by_is_protected(self):
        reviewer = Person.objects.create(name="Jordan", role=Person.Role.ADULT)
        proposal = self._make_proposal()
        proposal.approve(reviewer)

        with self.assertRaises(ProtectedError):
            reviewer.delete()


class ProposalViewTestBase(TestCase):
    """Shared setup for the assignment/budget edit views and the approvals
    views: a logged-in user with an adult and a kid `Person` to switch the
    active person between.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="family3", password="password")
        self.client.force_login(self.user)

        self.chore = Chore.objects.create(name="Dishes")
        self.adult = Person.objects.create(name="Alex", role=Person.Role.ADULT)
        self.kid = Person.objects.create(name="Sam", role=Person.Role.KID)
        self.template = WeeklyAssignmentTemplate.objects.create(
            chore=self.chore,
            assigned_to=self.adult,
            day_of_week=WeeklyAssignmentTemplate.DayOfWeek.SUNDAY,
            start_time=datetime.time(9, 0),
            duration_minutes=10,
        )

    def _select(self, person):
        session = self.client.session
        session["active_person_id"] = person.id
        session.save()


class AssignmentEditViewTests(ProposalViewTestBase):
    def test_kid_post_new_assignment_creates_pending_proposal_no_template_created(self):
        self._select(self.kid)

        response = self.client.post(
            reverse("assignment_new"),
            {
                "chore": self.chore.id,
                "assigned_to": self.kid.id,
                "day_of_week": WeeklyAssignmentTemplate.DayOfWeek.MONDAY,
                "start_time": "10:00",
                "duration_minutes": "20",
            },
        )

        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertEqual(WeeklyAssignmentTemplate.objects.count(), 1)  # only setUp's
        proposal = ProposedAssignmentChange.objects.get()
        self.assertEqual(proposal.status, ProposalStatus.PENDING)
        self.assertIsNone(proposal.target_template)
        self.assertEqual(proposal.proposed_by, self.kid)
        self.assertEqual(proposal.assigned_to, self.kid)
        self.assertEqual(proposal.duration_minutes, 20)

    def test_kid_post_edit_creates_pending_proposal_and_leaves_template_untouched(self):
        self._select(self.kid)

        response = self.client.post(
            reverse("assignment_edit", args=[self.template.id]),
            {
                "chore": self.chore.id,
                "assigned_to": self.kid.id,
                "day_of_week": WeeklyAssignmentTemplate.DayOfWeek.TUESDAY,
                "start_time": "11:00",
                "duration_minutes": "30",
            },
        )

        self.assertRedirects(response, "/", fetch_redirect_response=False)
        proposal = ProposedAssignmentChange.objects.get()
        self.assertEqual(proposal.target_template, self.template)
        self.assertEqual(proposal.status, ProposalStatus.PENDING)
        self.template.refresh_from_db()
        self.assertEqual(self.template.assigned_to, self.adult)
        self.assertEqual(self.template.duration_minutes, 10)

    def test_adult_post_edit_applies_immediately_with_no_proposal_created(self):
        self._select(self.adult)

        response = self.client.post(
            reverse("assignment_edit", args=[self.template.id]),
            {
                "chore": self.chore.id,
                "assigned_to": self.kid.id,
                "day_of_week": WeeklyAssignmentTemplate.DayOfWeek.WEDNESDAY,
                "start_time": "12:00",
                "duration_minutes": "40",
            },
        )

        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertFalse(ProposedAssignmentChange.objects.exists())
        self.template.refresh_from_db()
        self.assertEqual(self.template.assigned_to, self.kid)
        self.assertEqual(self.template.duration_minutes, 40)

    def test_adult_post_new_creates_template_immediately_with_no_proposal(self):
        self._select(self.adult)

        response = self.client.post(
            reverse("assignment_new"),
            {
                "chore": self.chore.id,
                "assigned_to": self.adult.id,
                "day_of_week": WeeklyAssignmentTemplate.DayOfWeek.THURSDAY,
                "start_time": "13:00",
                "duration_minutes": "25",
            },
        )

        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertFalse(ProposedAssignmentChange.objects.exists())
        self.assertEqual(WeeklyAssignmentTemplate.objects.count(), 2)


class BudgetEditViewTests(ProposalViewTestBase):
    def test_kid_post_creates_pending_proposal_and_leaves_budget_untouched(self):
        self._select(self.kid)

        response = self.client.post(
            reverse("budget_edit", args=[self.adult.id]), {"daily_budget_minutes": "45"}
        )

        self.assertRedirects(response, "/", fetch_redirect_response=False)
        proposal = ProposedBudgetChange.objects.get()
        self.assertEqual(proposal.status, ProposalStatus.PENDING)
        self.assertEqual(proposal.person, self.adult)
        self.assertEqual(proposal.daily_budget_minutes, 45)
        self.assertIsNone(proposal.weekly_budget_minutes)
        self.assertEqual(proposal.proposed_by, self.kid)
        self.adult.refresh_from_db()
        self.assertIsNone(self.adult.daily_budget_minutes)

    def test_adult_post_applies_immediately_with_no_proposal_created(self):
        self._select(self.adult)

        response = self.client.post(
            reverse("budget_edit", args=[self.kid.id]), {"weekly_budget_minutes": "300"}
        )

        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertFalse(ProposedBudgetChange.objects.exists())
        self.kid.refresh_from_db()
        self.assertEqual(self.kid.weekly_budget_minutes, 300)


class ApprovalsListViewTests(ProposalViewTestBase):
    def test_lists_pending_assignment_and_budget_changes_visible_to_a_kid(self):
        ProposedAssignmentChange.objects.create(
            target_template=None,
            chore=self.chore,
            assigned_to=self.kid,
            day_of_week=WeeklyAssignmentTemplate.DayOfWeek.FRIDAY,
            start_time=datetime.time(14, 0),
            duration_minutes=15,
            proposed_by=self.kid,
        )
        ProposedBudgetChange.objects.create(
            person=self.kid, daily_budget_minutes=20, proposed_by=self.kid
        )
        self._select(self.kid)

        response = self.client.get(reverse("approvals"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dishes")
        self.assertContains(response, "Sam")

    def test_non_pending_changes_are_not_listed(self):
        approved = ProposedBudgetChange.objects.create(
            person=self.kid,
            daily_budget_minutes=20,
            proposed_by=self.kid,
            status=ProposalStatus.APPROVED,
        )
        self._select(self.adult)

        response = self.client.get(reverse("approvals"))

        self.assertNotIn(approved, response.context["budget_changes"])


class ApproveRejectAssignmentChangeViewTests(ProposalViewTestBase):
    def setUp(self):
        super().setUp()
        self.proposal = ProposedAssignmentChange.objects.create(
            target_template=self.template,
            chore=self.chore,
            assigned_to=self.kid,
            day_of_week=WeeklyAssignmentTemplate.DayOfWeek.SATURDAY,
            start_time=datetime.time(15, 0),
            duration_minutes=50,
            proposed_by=self.kid,
        )

    def test_adult_approve_applies_change_via_service_and_updates_status(self):
        self._select(self.adult)

        response = self.client.post(reverse("approve_assignment_change", args=[self.proposal.id]))

        self.assertRedirects(response, reverse("approvals"), fetch_redirect_response=False)
        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.status, ProposalStatus.APPROVED)
        self.assertEqual(self.proposal.reviewed_by, self.adult)
        self.template.refresh_from_db()
        self.assertEqual(self.template.assigned_to, self.kid)
        self.assertEqual(self.template.duration_minutes, 50)

    def test_adult_reject_leaves_live_data_untouched(self):
        self._select(self.adult)

        response = self.client.post(
            reverse("reject_assignment_change", args=[self.proposal.id]), {"note": "not now"}
        )

        self.assertRedirects(response, reverse("approvals"), fetch_redirect_response=False)
        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.status, ProposalStatus.REJECTED)
        self.assertEqual(self.proposal.note, "not now")
        self.template.refresh_from_db()
        self.assertEqual(self.template.assigned_to, self.adult)
        self.assertEqual(self.template.duration_minutes, 10)

    def test_kid_approve_gets_403_and_makes_no_state_change(self):
        self._select(self.kid)

        response = self.client.post(reverse("approve_assignment_change", args=[self.proposal.id]))

        self.assertEqual(response.status_code, 403)
        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.status, ProposalStatus.PENDING)
        self.template.refresh_from_db()
        self.assertEqual(self.template.assigned_to, self.adult)

    def test_kid_reject_gets_403_and_makes_no_state_change(self):
        self._select(self.kid)

        response = self.client.post(reverse("reject_assignment_change", args=[self.proposal.id]))

        self.assertEqual(response.status_code, 403)
        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.status, ProposalStatus.PENDING)


class ApproveRejectBudgetChangeViewTests(ProposalViewTestBase):
    def setUp(self):
        super().setUp()
        self.proposal = ProposedBudgetChange.objects.create(
            person=self.kid, daily_budget_minutes=40, proposed_by=self.kid
        )

    def test_adult_approve_applies_change_via_service_and_updates_status(self):
        self._select(self.adult)

        response = self.client.post(reverse("approve_budget_change", args=[self.proposal.id]))

        self.assertRedirects(response, reverse("approvals"), fetch_redirect_response=False)
        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.status, ProposalStatus.APPROVED)
        self.kid.refresh_from_db()
        self.assertEqual(self.kid.daily_budget_minutes, 40)

    def test_adult_reject_leaves_budget_untouched(self):
        self._select(self.adult)

        response = self.client.post(reverse("reject_budget_change", args=[self.proposal.id]))

        self.assertRedirects(response, reverse("approvals"), fetch_redirect_response=False)
        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.status, ProposalStatus.REJECTED)
        self.kid.refresh_from_db()
        self.assertIsNone(self.kid.daily_budget_minutes)

    def test_kid_approve_gets_403_and_makes_no_state_change(self):
        self._select(self.kid)

        response = self.client.post(reverse("approve_budget_change", args=[self.proposal.id]))

        self.assertEqual(response.status_code, 403)
        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.status, ProposalStatus.PENDING)
        self.kid.refresh_from_db()
        self.assertIsNone(self.kid.daily_budget_minutes)

    def test_kid_reject_gets_403_and_makes_no_state_change(self):
        self._select(self.kid)

        response = self.client.post(reverse("reject_budget_change", args=[self.proposal.id]))

        self.assertEqual(response.status_code, 403)
        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.status, ProposalStatus.PENDING)


class CalendarViewTests(ChoreInstanceViewTestBase):
    """`GET /calendar/?week=YYYY-MM-DD` — see issue #10."""

    def test_route_is_mounted_at_calendar_not_under_chores(self):
        self.assertEqual(reverse("calendar"), "/calendar/")

    def test_dashboard_links_to_calendar(self):
        response = self.client.get("/")

        self.assertContains(response, 'href="/calendar/"')

    def test_missing_week_param_defaults_to_current_week(self):
        response = self.client.get(reverse("calendar"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, str(week_start_of(self.today)))

    def test_unparsable_week_param_defaults_to_current_week(self):
        response = self.client.get(reverse("calendar"), {"week": "not-a-date"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, str(week_start_of(self.today)))

    def test_week_param_names_any_date_in_the_target_week(self):
        # Saturday of the current week names the same week as today does.
        saturday = week_start_of(self.today) + datetime.timedelta(days=6)

        response = self.client.get(reverse("calendar"), {"week": saturday.isoformat()})

        self.assertContains(response, str(week_start_of(self.today)))

    def test_prev_and_next_links_point_to_adjacent_sundays(self):
        week_start = week_start_of(self.today)

        response = self.client.get(reverse("calendar"), {"week": week_start.isoformat()})

        prev_week = (week_start - datetime.timedelta(days=7)).isoformat()
        next_week = (week_start + datetime.timedelta(days=7)).isoformat()
        self.assertContains(response, f"?week={prev_week}")
        self.assertContains(response, f"?week={next_week}")

    def test_requesting_a_week_twice_generates_its_instances_exactly_once(self):
        week_start = week_start_of(self.today)
        self.assertFalse(ChoreInstance.objects.exists())

        self.client.get(reverse("calendar"), {"week": week_start.isoformat()})
        self.client.get(reverse("calendar"), {"week": week_start.isoformat()})

        self.assertEqual(
            ChoreInstance.objects.filter(template=self.template, date=week_start).count(), 1
        )

    def test_renders_chore_details_grouped_by_day(self):
        instance = self._make_instance(self.today)

        response = self.client.get(reverse("calendar"), {"week": self.today.isoformat()})

        self.assertContains(response, "Dishes")
        self.assertContains(response, "Alex")
        self.assertContains(response, instance.scheduled_start.astimezone().strftime("%H:%M"))
        self.assertContains(response, "Not done")

    def test_a_week_entirely_of_past_days_renders_no_action_forms(self):
        past_week_start = week_start_of(self.today) - datetime.timedelta(days=14)
        for offset in range(7):
            self._make_day_instance(past_week_start + datetime.timedelta(days=offset))

        response = self.client.get(reverse("calendar"), {"week": past_week_start.isoformat()})

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "<form")
        self.assertNotContains(response, "Log time")
        self.assertNotContains(response, "Swap")

    def test_current_week_shows_forms_for_today_and_later_but_not_earlier_days(self):
        week_start = week_start_of(self.today)
        offsets = range(7)
        earlier_dates = [
            week_start + datetime.timedelta(days=offset)
            for offset in offsets
            if week_start + datetime.timedelta(days=offset) < self.today
        ]
        later_dates = [
            week_start + datetime.timedelta(days=offset)
            for offset in offsets
            if week_start + datetime.timedelta(days=offset) >= self.today
        ]

        earlier_instances = [self._make_day_instance(date) for date in earlier_dates]
        later_instances = [self._make_day_instance(date) for date in later_dates]

        response = self.client.get(reverse("calendar"), {"week": week_start.isoformat()})
        content = response.content.decode()

        for instance in later_instances:
            self.assertIn(reverse("swap", args=[instance.id]), content)

        for instance in earlier_instances:
            self.assertNotIn(reverse("swap", args=[instance.id]), content)

    def _make_day_instance(self, date):
        # A distinct WeeklyAssignmentTemplate per date, since (template,
        # date) is unique and every date needs its own ChoreInstance.
        day_of_week = 0 if date.weekday() == 6 else date.weekday() + 1
        chore = Chore.objects.create(name=f"Chore-{date.isoformat()}")
        template = WeeklyAssignmentTemplate.objects.create(
            chore=chore,
            assigned_to=self.active_person,
            day_of_week=day_of_week,
            start_time=datetime.time(9, 0),
            duration_minutes=10,
        )
        return ChoreInstance.objects.create(
            template=template,
            chore=chore,
            date=date,
            scheduled_start=timezone.make_aware(
                datetime.datetime.combine(date, datetime.time(9, 0))
            ),
            budgeted_minutes=10,
            assigned_person=self.active_person,
        )


class NotificationsTestBase(TestCase):
    """Shared setup for `get_upcoming_blocks`/`get_unfinished_today` tests.

    Each instance gets its own `Chore`/`WeeklyAssignmentTemplate` so several
    instances can share a `date` without tripping the `(template, date)`
    uniqueness constraint.
    """

    def setUp(self):
        self.person = Person.objects.create(name="Alex", role=Person.Role.ADULT)

    def _make_instance(self, name, date, scheduled_start, is_done=False):
        chore = Chore.objects.create(name=name)
        template = WeeklyAssignmentTemplate.objects.create(
            chore=chore,
            assigned_to=self.person,
            day_of_week=0 if date.weekday() == 6 else date.weekday() + 1,
            start_time=scheduled_start.time(),
            duration_minutes=10,
        )
        return ChoreInstance.objects.create(
            template=template,
            chore=chore,
            date=date,
            scheduled_start=scheduled_start,
            budgeted_minutes=10,
            assigned_person=self.person,
            is_done=is_done,
            done_at=timezone.now() if is_done else None,
            done_by=self.person if is_done else None,
        )


class GetUpcomingBlocksTests(NotificationsTestBase):
    @time_machine.travel(datetime.datetime(2026, 9, 2, 10, 0), tick=False)
    def test_instance_29_minutes_out_is_included(self):
        now = timezone.localtime(timezone.now())
        instance = self._make_instance(
            "Dishes", now.date(), now + datetime.timedelta(minutes=29)
        )

        self.assertIn(instance, get_upcoming_blocks(now))

    @time_machine.travel(datetime.datetime(2026, 9, 2, 10, 0), tick=False)
    def test_instance_31_minutes_out_is_excluded(self):
        now = timezone.localtime(timezone.now())
        instance = self._make_instance(
            "Dishes", now.date(), now + datetime.timedelta(minutes=31)
        )

        self.assertNotIn(instance, get_upcoming_blocks(now))

    @time_machine.travel(datetime.datetime(2026, 9, 2, 10, 0), tick=False)
    def test_instance_exactly_at_lookahead_boundary_is_included(self):
        now = timezone.localtime(timezone.now())
        instance = self._make_instance(
            "Dishes", now.date(), now + datetime.timedelta(minutes=30)
        )

        self.assertIn(instance, get_upcoming_blocks(now, lookahead_minutes=30))

    @time_machine.travel(datetime.datetime(2026, 9, 2, 10, 0), tick=False)
    def test_instance_exactly_at_now_is_included(self):
        now = timezone.localtime(timezone.now())
        instance = self._make_instance("Dishes", now.date(), now)

        self.assertIn(instance, get_upcoming_blocks(now))

    @time_machine.travel(datetime.datetime(2026, 9, 2, 23, 50), tick=False)
    def test_window_spanning_midnight_includes_next_days_instance(self):
        now = timezone.localtime(timezone.now())
        tomorrow = now.date() + datetime.timedelta(days=1)
        instance = self._make_instance(
            "Dishes",
            tomorrow,
            timezone.make_aware(datetime.datetime.combine(tomorrow, datetime.time(0, 10))),
        )

        self.assertIn(instance, get_upcoming_blocks(now, lookahead_minutes=30))

    @time_machine.travel(datetime.datetime(2026, 9, 2, 10, 0), tick=False)
    def test_done_instance_is_excluded(self):
        now = timezone.localtime(timezone.now())
        instance = self._make_instance(
            "Dishes", now.date(), now + datetime.timedelta(minutes=10), is_done=True
        )

        self.assertNotIn(instance, get_upcoming_blocks(now))

    @time_machine.travel(datetime.datetime(2026, 9, 2, 10, 0), tick=False)
    def test_results_are_ordered_by_scheduled_start(self):
        now = timezone.localtime(timezone.now())
        later = self._make_instance(
            "Vacuum", now.date(), now + datetime.timedelta(minutes=20)
        )
        earlier = self._make_instance(
            "Dishes", now.date(), now + datetime.timedelta(minutes=5)
        )

        self.assertEqual(list(get_upcoming_blocks(now)), [earlier, later])


class GetUnfinishedTodayTests(NotificationsTestBase):
    @time_machine.travel(datetime.datetime(2026, 9, 2, 10, 0), tick=False)
    def test_unfinished_instance_from_earlier_today_is_included(self):
        now = timezone.localtime(timezone.now())
        instance = self._make_instance(
            "Dishes", now.date(), now - datetime.timedelta(minutes=30)
        )

        self.assertIn(instance, get_unfinished_today(now))

    @time_machine.travel(datetime.datetime(2026, 9, 2, 10, 0), tick=False)
    def test_done_instance_is_excluded(self):
        now = timezone.localtime(timezone.now())
        instance = self._make_instance(
            "Dishes", now.date(), now - datetime.timedelta(minutes=30), is_done=True
        )

        self.assertNotIn(instance, get_unfinished_today(now))

    @time_machine.travel(datetime.datetime(2026, 9, 2, 10, 0), tick=False)
    def test_instance_starting_in_the_future_today_is_excluded(self):
        now = timezone.localtime(timezone.now())
        instance = self._make_instance(
            "Dishes", now.date(), now + datetime.timedelta(minutes=30)
        )

        self.assertNotIn(instance, get_unfinished_today(now))

    @time_machine.travel(datetime.datetime(2026, 9, 2, 10, 0), tick=False)
    def test_instance_from_yesterday_is_excluded(self):
        now = timezone.localtime(timezone.now())
        yesterday = now.date() - datetime.timedelta(days=1)
        instance = self._make_instance(
            "Dishes",
            yesterday,
            timezone.make_aware(datetime.datetime.combine(yesterday, datetime.time(9, 0))),
        )

        self.assertNotIn(instance, get_unfinished_today(now))


class DashboardNotificationsViewTests(ChoreInstanceViewTestBase):
    """Confirms the dashboard view wires the two functions into the
    "Starting soon"/"Unfinished today" sections, recomputed on every load
    (no meta-refresh/polling/background job involved)."""

    @time_machine.travel(datetime.datetime(2026, 9, 2, 10, 0), tick=False)
    def test_dashboard_shows_upcoming_and_unfinished_sections(self):
        now = timezone.localtime(timezone.now())
        soon_chore = Chore.objects.create(name="Take out trash")
        soon_template = WeeklyAssignmentTemplate.objects.create(
            chore=soon_chore,
            assigned_to=self.active_person,
            day_of_week=0 if now.weekday() == 6 else now.weekday() + 1,
            start_time=(now + datetime.timedelta(minutes=10)).time(),
            duration_minutes=10,
        )
        ChoreInstance.objects.create(
            template=soon_template,
            chore=soon_chore,
            date=now.date(),
            scheduled_start=now + datetime.timedelta(minutes=10),
            budgeted_minutes=10,
            assigned_person=self.active_person,
        )

        overdue_chore = Chore.objects.create(name="Feed the cat")
        overdue_template = WeeklyAssignmentTemplate.objects.create(
            chore=overdue_chore,
            assigned_to=self.active_person,
            day_of_week=0 if now.weekday() == 6 else now.weekday() + 1,
            start_time=(now - datetime.timedelta(hours=1)).time(),
            duration_minutes=10,
        )
        ChoreInstance.objects.create(
            template=overdue_template,
            chore=overdue_chore,
            date=now.date(),
            scheduled_start=now - datetime.timedelta(hours=1),
            budgeted_minutes=10,
            assigned_person=self.active_person,
        )

        response = self.client.get("/")

        self.assertContains(response, "Starting soon")
        self.assertContains(response, "Take out trash")
        self.assertContains(response, "Unfinished today")
        self.assertContains(response, "Feed the cat")
