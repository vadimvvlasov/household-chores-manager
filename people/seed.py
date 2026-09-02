from .models import Person

DEFAULT_FAMILY = [
    ("Adult 1", Person.Role.ADULT),
    ("Adult 2", Person.Role.ADULT),
    ("Kid 1", Person.Role.KID),
    ("Kid 2", Person.Role.KID),
]


def seed_default_family():
    """Ensure the 4 default placeholder Person rows exist.

    Keyed on `name` alone via get_or_create (there is no unique constraint
    on Person.name, so this is a convention, not a DB guarantee). If a
    Person with a matching name already exists, it is left untouched --
    this only creates rows that are missing.
    """
    for name, role in DEFAULT_FAMILY:
        Person.objects.get_or_create(name=name, defaults={"role": role})
