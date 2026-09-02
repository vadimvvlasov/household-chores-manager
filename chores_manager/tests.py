from django.contrib.auth.models import User
from django.test import TestCase

from people.models import Person


class HomePageTests(TestCase):
    def test_home_page_requires_login(self):
        response = self.client.get("/")
        self.assertRedirects(response, "/login/?next=/", fetch_redirect_response=False)

    def test_home_page_returns_200_with_active_person(self):
        user = User.objects.create_user(username="family", password="password")
        person = Person.objects.create(name="Alex", role=Person.Role.ADULT)
        self.client.force_login(user)
        session = self.client.session
        session["active_person_id"] = person.id
        session.save()

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
