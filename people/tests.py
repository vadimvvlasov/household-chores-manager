from django.contrib.auth.models import User
from django.http import HttpResponse
from django.test import TestCase
from django.urls import reverse

from .decorators import adult_required
from .models import Person


class PersonAdminTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username="admin", email="admin@example.com", password="password"
        )
        self.client.force_login(self.superuser)

    def test_superuser_can_create_person(self):
        response = self.client.post(
            reverse("admin:people_person_add"),
            {"name": "Jamie", "role": Person.Role.KID, "is_active": "on"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Person.objects.filter(name="Jamie", role=Person.Role.KID).exists())

    def test_superuser_can_edit_and_deactivate_person(self):
        person = Person.objects.create(name="Jamie", role=Person.Role.KID)

        response = self.client.post(
            reverse("admin:people_person_change", args=[person.pk]),
            {"name": "Jamie", "role": Person.Role.KID},
        )

        self.assertEqual(response.status_code, 302)
        person.refresh_from_db()
        self.assertFalse(person.is_active)
        self.assertTrue(Person.objects.filter(pk=person.pk).exists())

    def test_admin_changelist_shows_columns(self):
        Person.objects.create(name="Jamie", role=Person.Role.KID)

        response = self.client.get(reverse("admin:people_person_changelist"))

        self.assertContains(response, "Jamie")
        self.assertContains(response, "Kid")

    def test_budget_fields_are_editable_in_admin(self):
        person = Person.objects.create(name="Jamie", role=Person.Role.KID)

        response = self.client.post(
            reverse("admin:people_person_change", args=[person.pk]),
            {
                "name": "Jamie",
                "role": Person.Role.KID,
                "is_active": "on",
                "daily_budget_minutes": "45",
                "weekly_budget_minutes": "200",
            },
        )

        self.assertEqual(response.status_code, 302)
        person.refresh_from_db()
        self.assertEqual(person.daily_budget_minutes, 45)
        self.assertEqual(person.weekly_budget_minutes, 200)

    def test_budget_fields_can_be_cleared_back_to_none_in_admin(self):
        person = Person.objects.create(
            name="Jamie",
            role=Person.Role.KID,
            daily_budget_minutes=45,
            weekly_budget_minutes=200,
        )

        response = self.client.post(
            reverse("admin:people_person_change", args=[person.pk]),
            {"name": "Jamie", "role": Person.Role.KID, "is_active": "on"},
        )

        self.assertEqual(response.status_code, 302)
        person.refresh_from_db()
        self.assertIsNone(person.daily_budget_minutes)
        self.assertIsNone(person.weekly_budget_minutes)


class PersonModelTests(TestCase):
    def test_person_fields_persist(self):
        person = Person.objects.create(name="Alex", role=Person.Role.ADULT)

        person.refresh_from_db()

        self.assertEqual(person.name, "Alex")
        self.assertEqual(person.role, Person.Role.ADULT)
        self.assertTrue(person.is_active)
        self.assertEqual(str(person), "Alex")

    def test_deactivating_does_not_delete(self):
        person = Person.objects.create(name="Sam", role=Person.Role.KID)

        person.is_active = False
        person.save()

        self.assertTrue(Person.objects.filter(pk=person.pk, is_active=False).exists())

    def test_budget_fields_default_to_none(self):
        person = Person.objects.create(name="Alex", role=Person.Role.ADULT)

        person.refresh_from_db()

        self.assertIsNone(person.daily_budget_minutes)
        self.assertIsNone(person.weekly_budget_minutes)

    def test_budget_fields_can_be_set(self):
        person = Person.objects.create(
            name="Alex",
            role=Person.Role.ADULT,
            daily_budget_minutes=30,
            weekly_budget_minutes=150,
        )

        person.refresh_from_db()

        self.assertEqual(person.daily_budget_minutes, 30)
        self.assertEqual(person.weekly_budget_minutes, 150)


class LoginAndActivePersonTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="family", password="password")
        self.adult = Person.objects.create(name="Alex", role=Person.Role.ADULT)
        self.kid = Person.objects.create(name="Sam", role=Person.Role.KID)

    def login(self):
        self.client.force_login(self.user)

    def select(self, person):
        session = self.client.session
        session["active_person_id"] = person.id
        session.save()

    def test_unauthenticated_request_to_home_redirects_to_login(self):
        response = self.client.get("/")

        self.assertRedirects(response, "/login/?next=/", fetch_redirect_response=False)

    def test_unauthenticated_requests_to_protected_paths_redirect_to_login(self):
        for path in ["/profile/", "/profile/select/", "/logout/"]:
            with self.subTest(path=path):
                response = self.client.post(path) if path != "/profile/" else self.client.get(path)
                self.assertRedirects(
                    response, f"/login/?next={path}", fetch_redirect_response=False
                )

    def test_login_success_redirects_to_profile(self):
        response = self.client.post(
            reverse("login"), {"username": "family", "password": "password"}
        )

        self.assertRedirects(response, "/profile/", fetch_redirect_response=False)

    def test_login_success_redirects_to_profile_even_with_next_param(self):
        # Reproduces the real browser flow: an anonymous request is bounced
        # to "/login/?next=<path>" (per the redirect-to-login criterion),
        # and the login form submission carries that "next" along. Success
        # must still land on "/profile/", per the other criterion.
        response = self.client.post(
            f"{reverse('login')}?next=/",
            {"username": "family", "password": "password"},
        )

        self.assertRedirects(response, "/profile/", fetch_redirect_response=False)

    def test_login_success_after_bounce_from_select_person_does_not_405(self):
        # A user bounced from POST /profile/select/ while unauthenticated
        # gets redirected to "/login/?next=/profile/select/". Following
        # that "next" after login would send a GET to the POST-only
        # /profile/select/ endpoint, producing a 405. Login must ignore it.
        bounce = self.client.post(reverse("select_person"), {"person_id": self.adult.id})
        self.assertRedirects(
            bounce, "/login/?next=/profile/select/", fetch_redirect_response=False
        )

        response = self.client.post(
            "/login/?next=/profile/select/",
            {"username": "family", "password": "password"},
        )

        self.assertRedirects(response, "/profile/", fetch_redirect_response=False)

    def test_authenticated_with_no_active_person_redirects_to_profile(self):
        self.login()

        response = self.client.get("/")

        self.assertRedirects(response, "/profile/", fetch_redirect_response=False)

    def test_profile_picker_lists_only_active_people(self):
        self.kid.is_active = False
        self.kid.save()
        self.login()

        response = self.client.get(reverse("profile_picker"))

        self.assertContains(response, "Alex")
        self.assertNotContains(response, "Sam")

    def test_selecting_person_persists_active_person_id_across_requests(self):
        self.login()

        response = self.client.post(reverse("select_person"), {"person_id": self.adult.id})

        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertEqual(self.client.session["active_person_id"], self.adult.id)

        # A later request in the same session no longer bounces to the picker.
        second_response = self.client.get("/")
        self.assertEqual(second_response.status_code, 200)

    def test_selecting_inactive_person_does_not_set_session(self):
        self.kid.is_active = False
        self.kid.save()
        self.login()

        response = self.client.post(reverse("select_person"), {"person_id": self.kid.id})

        self.assertRedirects(response, "/profile/", fetch_redirect_response=False)
        self.assertNotIn("active_person_id", self.client.session)

    def test_logout_clears_active_person_id(self):
        self.login()
        self.select(self.adult)

        self.client.post(reverse("logout"))

        self.assertNotIn("active_person_id", self.client.session)

    def test_deactivated_selected_person_is_treated_as_unset(self):
        self.login()
        self.select(self.adult)

        self.adult.is_active = False
        self.adult.save()

        response = self.client.get("/")

        self.assertRedirects(response, "/profile/", fetch_redirect_response=False)


class AdultRequiredDecoratorTests(TestCase):
    def setUp(self):
        self.adult = Person.objects.create(name="Alex", role=Person.Role.ADULT)
        self.kid = Person.objects.create(name="Sam", role=Person.Role.KID)
        self.view = adult_required(lambda request: HttpResponse("ok"))

    def _request_with_active_person(self, active_person):
        return type("FakeRequest", (), {"active_person": active_person})()

    def test_adult_active_person_passes_through_to_the_view(self):
        response = self.view(self._request_with_active_person(self.adult))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")

    def test_kid_active_person_gets_403(self):
        response = self.view(self._request_with_active_person(self.kid))

        self.assertEqual(response.status_code, 403)

    def test_no_active_person_gets_403(self):
        response = self.view(self._request_with_active_person(None))

        self.assertEqual(response.status_code, 403)
