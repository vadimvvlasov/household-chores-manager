# Household Chores Manager — v1 Implementation Plan

Revision note (2nd pass — "make it easier"): dropped HTMX entirely (plain
full-page forms), dropped the `Swap` audit model (a swap is just a direct
reassignment), dropped `TimeBudget` as its own model (two fields on `Person`
instead), dropped the dedicated history feature (the calendar view's own
prev/next navigation *is* the history view — past weeks just render
read-only). First-pass simplifications kept: 2 apps, concrete proposal
models instead of generic `ContentType`, no template/budget versioning, no
PIN guard.

---

## 1. Project / app layout

**Project package:** `chores_manager` (already scaffolded), `manage.py` at repo root.

**Apps** (2):

| App | Responsibility |
|---|---|
| `people` | The single shared `auth.User` login, the 4 `Person` profiles (incl. their time budget fields), session-based "active person" middleware/context processor, profile picker. |
| `chores` | `Chore`, `WeeklyAssignmentTemplate`, `ChoreInstance`, `TimeLog`, `ProposedAssignmentChange`, `ProposedBudgetChange`, instance-generation + apply services, dashboard/calendar/approval-queue views, notification computation. |

**Dependencies (via `uv add`):** just `django` (already added). No `django-htmx`, no CSS framework, no JS bundler, no calendar JS library, no Celery/cron, no DRF, no Postgres (SQLite).

Every interactive action (check-off, log time, swap, propose, approve/reject) is a plain `<form method="post">` → view → `redirect()` back to the page it came from. No partial templates, no polling, no JS beyond whatever the browser gives you for free.

---

## 2. Data model

### `people` app

**`Person`**
- `name` (CharField)
- `role` (CharField choices: `ADULT`, `KID`)
- `daily_budget_minutes` (PositiveInteger, nullable = no cap set)
- `weekly_budget_minutes` (PositiveInteger, nullable = no cap set)
- `is_active` (bool, default True) — soft-deactivate, since other models FK to `Person`
- `created_at`

Budgets live directly on `Person` rather than a separate model: there's only ever *one current* daily cap and *one current* weekly cap per person, so it's two nullable integer columns, not a table. Editing them (adult direct, or kid via proposal) is a plain `Person.save()` — see `ProposedBudgetChange` below.

No PIN field — trust-based profile picker (see §3).

### `chores` app

**`Chore`** — `name`, `description` (blank), `default_duration_minutes` (nullable), `is_active`, `created_at`.

**`WeeklyAssignmentTemplate`** — the recurring "who/when" slot, a plain mutable row:
- `chore` FK
- `assigned_to` FK Person
- `day_of_week` (IntegerChoices, **Sunday = 0 … Saturday = 6**)
- `start_time` (TimeField)
- `duration_minutes` (PositiveSmallInteger)
- `updated_at`, `updated_by` FK Person

Editing this only ever affects instances generated *after* the edit — `ChoreInstance` already snapshots what it needs, so the template doesn't need version history of its own.

**`ChoreInstance`** — the per-date checkable/loggable/swappable row:
- `template` FK (protect on delete)
- `chore` FK (denormalized)
- `date` (Date)
- `scheduled_start` (DateTimeField, timezone-aware; `date` + `template.start_time` at generation time)
- `budgeted_minutes` (int, copied from template at generation time)
- `assigned_person` FK Person — this is what a swap changes; no separate audit row, the current value plus `TimeLog`/`done_by` already show who actually did the work regardless of who was originally slotted
- `is_done` (bool, default False), `done_at` (nullable), `done_by` FK Person (nullable)
- `created_at`
- `unique_together = (template, date)` — idempotent generation via `get_or_create`.

Swap = one line: `instance.assigned_person = new_person; instance.save()`, guarded (in `chores/services.py::swap_assignment`) to only allow it when `instance.date >= today` and `not instance.is_done`. No separate `Swap` model, no swap history table — if that's missed later it's a 3-field model to add back, not a redesign.

**`TimeLog`** — actual time spent, multiple entries per instance:
- `chore_instance` FK (related_name `time_logs`)
- `logged_by` FK Person
- `minutes` (PositiveInteger)
- `logged_at` (DateTime, default now)
- `note` (CharField, blank)

`chores/services.py`: `minutes_logged_today(person, on_date)` / `minutes_logged_this_week(person, week_start)` sum `TimeLog.minutes` via `ChoreInstance.assigned_person`. `is_over_budget(person, period, on_date)` compares to `person.daily_budget_minutes`/`weekly_budget_minutes` (skip the check entirely if the field is `None`) — a plain bool for a warning badge, **never blocking**.

**`ProposedAssignmentChange`**:
- `target_template` FK, nullable (null = new slot)
- `chore`, `assigned_to`, `day_of_week`, `start_time`, `duration_minutes` — proposed values as plain typed fields
- `proposed_by` FK Person, `proposed_at`
- `status` (`PENDING`/`APPROVED`/`REJECTED`, default `PENDING`)
- `reviewed_by` FK Person (null), `reviewed_at` (null), `note` (blank)

**`ProposedBudgetChange`**:
- `person` FK — whose budget
- `daily_budget_minutes`, `weekly_budget_minutes` (nullable — only the changed one needs to be set; `None` means "leave that one alone")
- `proposed_by`, `proposed_at`, `status`, `reviewed_by`, `reviewed_at`, `note` — same shape

`chores/services.py::apply_assignment_change(...)` (creates/updates the target `WeeklyAssignmentTemplate`) and `apply_budget_change(...)` (sets the relevant field(s) on `Person`) are the single source of truth for mutating live data — called both directly from an adult's edit view and from a proposal's `.approve(reviewed_by)`. `.reject(reviewed_by, note)` just flips status.

### Shared date utility

`chores/dateutils.py::week_start_of(d)` → the Sunday of the week containing `d`. Used for instance generation and calendar prev/next navigation.

---

## 3. Auth & session profile-picker

- Single Django `auth.User` via `uv run python manage.py createsuperuser` — the shared family login, unrelated to the 4 `Person` rows.
- `people/middleware.py::ActivePersonMiddleware` — reads `request.session['active_person_id']`, sets `request.active_person`. Redirects to the picker if unset (allowlist: picker/login/logout/static/admin).
- `people/context_processors.py::active_person` — exposes `active_person`/`is_adult` to every template.
- `people/decorators.py::adult_required` — 403 if `request.active_person.role != ADULT`. Used only on the approve/reject views. Server-side because the picker itself is trust-based (anyone can pick any profile) — this check stops a kid from *posting directly* to an approve URL; it doesn't stop them picking an adult's profile in the UI, which is an accepted v1 trade-off for a family app with no real security boundary.
- Logout clears `active_person_id` too.

---

## 4. Views / URLs per feature

All full-page renders (`F`) — plain forms, redirect after POST.

| Feature | Method + URL | View |
|---|---|---|
| Login | `GET/POST /login/` | `LoginView` (custom template) |
| Logout | `POST /logout/` | `LogoutView` subclass clearing `active_person_id` |
| Profile picker | `GET /profile/` | `ProfilePickerView` |
| Select profile | `POST /profile/select/` | `SelectProfileView` → redirect to dashboard |
| Dashboard (today's checklist + notifications) | `GET /` | `dashboard_view` — recomputes notifications fresh on every load |
| Check off / uncheck | `POST /chores/<instance_id>/check/`, `.../uncheck/` | `check_off_view` → redirect back |
| Log time | `GET/POST /chores/<instance_id>/log-time/` | `log_time_view` |
| Swap | `GET/POST /chores/<instance_id>/swap/` | `swap_view` → `swap_assignment()` service, redirect back |
| Weekly calendar (also serves as history) | `GET /calendar/?week=YYYY-MM-DD` | `calendar_view` — calls `ensure_instances_generated`; if `week < this week`, renders with all action forms omitted/rejected (see below) |
| Assignment list / edit / new | `GET /assignments/`, `GET/POST /assignments/<id>/edit/`, `/assignments/new/` | adult → `apply_assignment_change()` immediately; kid → creates `ProposedAssignmentChange` |
| Budget edit | `GET/POST /people/<person_id>/budget/` | same immediate-vs-proposal branch, via `ProposedBudgetChange` |
| Approval queue | `GET /approvals/` | lists pending `ProposedAssignmentChange` + `ProposedBudgetChange`; visible to everyone, action buttons adult-only |
| Approve / reject assignment | `POST /approvals/assignment/<id>/approve/`, `.../reject/` | `@adult_required` |
| Approve / reject budget | `POST /approvals/budget/<id>/approve/`, `.../reject/` | `@adult_required` |

No `/history/` URLs at all — `calendar_view` with `?week=` pointing at a past Sunday **is** the history view. Past-week read-only-ness isn't a template flag threaded through, it's the same server-side guard `check_off_view`/`log_time_view`/`swap_view` already need anyway (`instance.date < today` → reject), so there's exactly one place that rule lives, and the calendar template just doesn't render action buttons for instances that would be rejected.

---

## 5. In-app notification computation

No new model — derived from `ChoreInstance.scheduled_start`/`is_done` and the current time, recomputed on every full-page load of `/` (no polling, since there's no HTMX):

```
get_upcoming_blocks(now, lookahead_minutes=30):
    ChoreInstance.objects.filter(
        is_done=False,
        scheduled_start__gte=now,
        scheduled_start__lte=now + timedelta(minutes=lookahead_minutes),
    ).order_by("scheduled_start")

get_unfinished_today(now):
    ChoreInstance.objects.filter(
        date=now.date(),
        is_done=False,
        scheduled_start__lt=now,
    ).order_by("scheduled_start")
```

`now` = `timezone.localtime(timezone.now())`, `USE_TZ = True`, `TIME_ZONE` set to the family's zone in settings. "Live" here means "correct whenever you load or refresh the page" — no auto-refresh, which is the actual complexity this cut removes (no polling loop, no partial endpoint).

---

## 6. Admin / seed data

- Register every model in each app's `admin.py`.
- Shared login `User` via `createsuperuser`.
- `people/management/commands/seed_family.py` — `get_or_create`s the 2 adults + 2 kids.
- `chores/management/commands/seed_chores.py` — a handful of starter `Chore` + `WeeklyAssignmentTemplate` rows.
- Both backed by `seed_default_family()` / `seed_default_chores()` functions so tests reuse the same seeding logic in `setUp()`.

---

## 7. Testing strategy

Via `django.test.TestCase` + Django's test client, `uv run python manage.py test`.

- **`people`**: profile picker sets session; logout clears it; middleware redirects when unset.
- **`chores`**:
  - `ensure_instances_generated(week_start)` idempotent.
  - Snapshot-integrity: generate a week, edit the template, assert already-generated instances unchanged; a later week's generation picks up the edit.
  - Check-off/uncheck; multiple `TimeLog` entries sum correctly.
  - `swap_assignment` reassigns immediately; rejected for past or already-done instances.
  - `is_over_budget` boundary cases (at limit = no warning, one over = warning; `None` budget = never warns); over-budget never blocks check-off/time-log.
  - Kid-proposed change creates a `PENDING` row, doesn't mutate live data; adult edit mutates immediately, never creates a proposal; approve calls the shared apply function; reject leaves data untouched; POSTing an approve URL as a kid returns 403.
  - `get_upcoming_blocks`/`get_unfinished_today` boundaries via `time-machine` (just inside/outside window, exactly at start, midnight-crossing).
  - Past-week guard: POSTing check-off/log-time/swap against a `ChoreInstance` dated before today is rejected, for both calendar-rendered and direct-URL access.
- **View-level integration tests**: `self.client.session["active_person_id"] = person.id; session.save()` per role, end-to-end through propose/approve/swap/check-off.

---

## 8. Suggested build order / milestones

| # | Milestone | Acceptance |
|---|---|---|
| 0 | Scaffold (done) | `uv sync`, `manage.py migrate/runserver/test` work. |
| 1 | `people`: `Person` (incl. budget fields), admin, `ActivePersonMiddleware` + context processor, login + picker, `seed_family`. | Log in, pick a profile, it persists; logout resets it. |
| 2 | `chores` core: `Chore`, `WeeklyAssignmentTemplate`, `ChoreInstance`, `ensure_instances_generated()`, `seed_chores`, admin. | Visiting a week generates its instances exactly once. |
| 3 | Check-off + time log: plain-form views, dashboard checklist per person. | Check-off/log-time tests pass, full page redirect works. |
| 4 | Budget warning badges using `Person.daily_budget_minutes`/`weekly_budget_minutes`. | Over-budget never blocks an action; boundary tests pass. |
| 5 | Swap: `swap_assignment()` service + form, guarded against past/done instances. | Swap reassigns instantly; guard tests pass. |
| 6 | `ProposedAssignmentChange`/`ProposedBudgetChange` + apply services + propose/edit views branching on role + approval queue. | Kid change pends until approved; adult change applies immediately; 403 test passes. |
| 7 | Calendar view (doubles as history): server-rendered week grid, prev/next nav, past-week read-only via the shared date guard. | Grid shows only that week's blocks; past weeks show unchanged after later template edits; action POSTs against past instances rejected. |
| 8 | Notifications: `chores/notifications.py`, dashboard sections, recomputed per page load. | Starting-soon/unfinished-today sections correct; edge tests pass. |

9 milestones → 8; no dedicated history milestone since it's absorbed into #7.

---

### Critical files
- `chores/models.py` — `WeeklyAssignmentTemplate`/`ChoreInstance`/`TimeLog` and the snapshot-at-generation pattern underpinning history integrity; `ProposedAssignmentChange`/`ProposedBudgetChange` and their `.approve()`/`.reject()`
- `chores/services.py` — `ensure_instances_generated`, `swap_assignment`, `apply_assignment_change`, `apply_budget_change` — shared by direct-adult-edit and proposal-approval paths, and by the past-week guard
- `people/models.py` — `Person`, including the two budget fields
- `people/middleware.py` — session-based active-person resolution every other view depends on
- `chores/notifications.py` — "starting soon" / "unfinished today" computation
