Documents

- `_docs/process.md` - how work is organized

Commands

- `uv sync` - install dependencies
- `uv run python manage.py runserver` - run dev server
- `uv run python manage.py test` - the whole suite
- `uv run python manage.py test chores_manager` - one app/module

Rules

- Dependencies are added via `uv add` into `pyproject.toml`. Do not add one without
  asking.
- Shortcut phrases (e.g. "Test issue #N") are defined in `_docs/process.md`. Check
  there.
