import datetime

from django.contrib.auth.models import User
from django.db.models import ProtectedError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from people.models import Person

from .dateutils import week_start_of
from .models import Chore, ChoreInstance, TimeLog, WeeklyAssignmentTemplate
from .services import (
    ensure_instances_generated,
    is_over_budget,
    minutes_logged_this_week,
    minutes_logged_today,
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
