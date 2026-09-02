Documents

- `_docs/process.md` - how work is organized

Commands

- `uv sync` - install dependencies
- `uv run python manage.py runserver` - run dev server
- `uv run python manage.py test` - the whole suite
- `uv run python manage.py test chores_manager` - one app/module
- `uv run python manage.py seed_family` - create the 4 placeholder `Person` rows

Rules

- Dependencies are added via `uv add` into `pyproject.toml`. Do not add one without
  asking.
