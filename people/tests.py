from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

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
