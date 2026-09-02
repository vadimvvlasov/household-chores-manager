# Household Chores Manager

A web app that gives a family of 4 a shared, clear system for household chores — fixed weekly assignments, daily checklists, time budgets, and swap tracking.

Built as Homework 1 for [AI Dev Tools Zoomcamp](https://github.com/DataTalksClub/ai-dev-tools-zoomcamp) (DataTalksClub).

## Scope

See [`_docs/plan.md`](_docs/plan.md) for the full spec (users, features, out-of-scope for v1).

## Stack

- Python + Django
- [uv](https://docs.astral.sh/uv/) for dependency management and running commands

## Setup

```bash
uv sync
uv run python manage.py migrate
uv run python manage.py runserver
```

## Tests

```bash
uv run python manage.py test
```
