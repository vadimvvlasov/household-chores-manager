# Household Chores Manager — v1 Implementation Plan

## Context confirmed from repo

Repo currently has only `README.md` and `_docs/plan.md` — no `pyproject.toml`, no Django project scaffolded yet, single commit (`cdcfd01 chore: Initialize project with documentation and configuration`). README already documents the target commands (`uv sync`, `uv run python manage.py migrate/runserver/test`), so the plan below is designed to make those commands true from milestone 0 onward.

---

## 1. Project / app layout

**Project package:** `chores_manager` (settings/urls/wsgi/asgi), `manage.py` at repo root — flat layout, no `src/` nesting, since this is a small single-deployable app.

**Apps** (4, each with a clear single responsibility, avoiding one giant app but also avoiding over-fragmentation):

| App | Responsibility |
|---|---|
| `people` | The single shared `auth.User` login flow, the 4 `Person` profiles, session-based "active person" middleware/context processor, profile picker, optional adult PIN guard. |
| `chores` | `Chore`, `WeeklyAssignmentTemplate`, `ChoreInstance`, `TimeLog`, `Swap`, instance-generation service, dashboard view, calendar view, notification computation, history view. This is the largest app because check-off/swap/time-log/calendar/notifications/history all revolve around `ChoreInstance` and benefit from living together. |
| `budgets` | `TimeBudget` (daily/weekly caps per person), aggregation + warning-computation services. Kept separate from `chores` because it's a genuinely distinct domain concept (a cap on a person, not a property of a chore) and because both `chores` view code and the approval flow need to read it without a circular "budgets depends on chores depends on budgets" import problem. |
| `approvals` | The generic pending-change queue (`Proposal`) used by *both* `chores` (assignment edits) and `budgets` (budget edits). Implemented once, using `django.contrib.contenttypes` so it doesn't need to know about assignment/budget internals. Kept as its own app specifically so it can sit "above" `chores` and `budgets` without either of them depending on the other. |

Rejected alternative: a single monolithic `chores` app holding everything. Rejected because the approval mechanism genuinely needs to be generic across two unrelated target models, and jamming that plus calendar/notifications/budgets into one app file set would get hard to navigate for a 9-milestone build.

No DRF/API app — this is server-rendered Django templates + HTMX only, per the fixed stack decision.

**Dependencies (via `uv add`):**
- `django`
- `django-htmx` (gives `request.htmx` boolean + `HX-*` response helpers, used to decide partial vs. full-page render)
- Dev-only (`uv add --dev`): `time-machine` (or `freezegun`) for deterministic "now" in notification/budget tests.

No CSS framework, no JS bundler, no calendar JS library, no Celery/cron, no DRF — all consistent with the fixed constraints.

---

## 2. Data model

### `people` app

**`Person`**
- `name` (CharField)
- `role` (CharField choices: `ADULT`, `KID`)
- `pin_hash` (CharField, blank/null) — see auth section
- `is_active` (bool, default True) — soft-deactivate instead of delete, since every other model FKs to `Person` and history must survive.
- `created_at`

### `chores` app

**`Chore`** — the reusable "what": `name`, `description` (blank), `default_duration_minutes` (nullable, just a convenience default for new template slots), `is_active`, `created_at`.

**`WeeklyAssignmentTemplate`** — the recurring "who/when" slot. This is versioned with effective-dating so that reconstructing "what was the plan on date X" is always possible even for weeks where nobody visited the app (instances are lazily generated, so the template itself is sometimes the only historical record for a stale week):
- `chore` FK
- `assigned_to` FK Person
- `day_of_week` (IntegerChoices, **Sunday = 0 … Saturday = 6**, matching the "week starts Sunday" requirement)
- `start_time` (TimeField) — needed for calendar time blocks and "starting soon" notifications
- `duration_minutes` (PositiveSmallInteger) — budgeted length of this specific chore occurrence
- `effective_from` (Date, always a Sunday)
- `effective_to` (Date, null = currently active)
- `created_by` FK Person, `created_at`

**`ChoreInstance`** — the materialized, checkable, swappable, loggable per-date row. Generated from the template that was active for that week; **never mutated by later template edits**, which is the core mechanism that keeps history accurate:
- `template` FK (protect on delete)
- `chore` FK (denormalized reference for convenience/query simplicity)
- `date` (Date)
- `scheduled_start` (DateTimeField, computed at generation time from `date` + `template.start_time`, timezone-aware) — stored as a full datetime specifically so notification range-queries don't have to deal with time-only comparisons across midnight
- `budgeted_minutes` (int, copied from template at generation time)
- `assigned_person` FK Person — the *currently* responsible person; this is what swaps mutate
- `original_person` FK Person — snapshot of who the template assigned, kept even after a swap, for audit ("Kid1 was supposed to do this, Kid2 actually did")
- `is_done` (bool, default False), `done_at` (nullable), `done_by` FK Person (nullable)
- `created_at`
- `unique_together = (template, date)` — makes generation idempotent via `get_or_create`.

**`TimeLog`** — actual time spent, multiple entries allowed per instance (sum them for "actual minutes"):
- `chore_instance` FK (related_name `time_logs`)
- `logged_by` FK Person
- `minutes` (PositiveInteger)
- `logged_at` (DateTime, default now)
- `note` (CharField, blank)

**`Swap`** — audit record of an instant reassignment (the mutation itself happens on `ChoreInstance.assigned_person`; this table is the "why does history look different from the template" trail):
- `chore_instance` FK
- `from_person`, `to_person` FK Person
- `swapped_by` FK Person
- `swapped_at` (DateTime, default now)
- `note` (blank)

Business rule (enforced in the view, not just the template): swaps are only allowed on instances dated today-or-future and not yet `is_done`, so past/completed history can't be silently rewritten by a swap either.

### `budgets` app

**`TimeBudget`** — same effective-dating pattern as the assignment template, for the same reason (accurate historical "what was the cap" even for weeks nobody generated instances for):
- `person` FK
- `period` (choices `DAILY` / `WEEKLY`)
- `minutes` (PositiveInteger)
- `effective_from` (Date, Sunday-aligned for `WEEKLY`, any date for `DAILY`)
- `effective_to` (Date, null = active)
- `created_by` FK Person, `created_at`

Aggregation lives in `budgets/services.py`: `minutes_logged_today(person, on_date)` and `minutes_logged_this_week(person, week_start)` — both just sum `TimeLog.minutes` joined through `ChoreInstance` filtered by `assigned_person`/`date`. `is_over_budget(person, period, on_date)` compares that sum to the active `TimeBudget` row and returns a plain bool used only for a warning badge — it **never blocks** any check-off or logging action, per spec.

### `approvals` app

**`Proposal`** — the one generic pending-change mechanism for both assignment edits and budget edits, using `django.contrib.contenttypes` instead of two near-duplicate models:
- `proposed_by` FK Person
- `proposed_at` (DateTime)
- `status` (choices `PENDING` / `APPROVED` / `REJECTED`, default `PENDING`)
- `reviewed_by` FK Person (null), `reviewed_at` (null)
- `content_type` FK `ContentType`, `object_id` (nullable int) → `GenericForeignKey('content_type', 'object_id')` pointing at the existing `WeeklyAssignmentTemplate` or `TimeBudget` row being replaced (null for a brand-new slot/budget)
- `action` (choices `CREATE` / `UPDATE` / `DEACTIVATE`)
- `payload` (JSONField) — the proposed new field values, e.g. `{"assigned_to_id": 3, "day_of_week": 2, "start_time": "17:30", "duration_minutes": 20}`
- `effective_from` (Date) — defaults to *next* week's Sunday, computed at proposal-creation time via the shared `week_start_of()` helper (see below)
- `note` (blank text, optional justification)

`Proposal.apply(applied_by)` dispatches on `content_type`/`action`/`payload` and calls into `chores/services.py::apply_assignment_change(...)` or `budgets/services.py::apply_budget_change(...)`. Those two service functions are the **single source of truth for mutating a template/budget** (deactivate the old effective-dated row, insert the new one) — they're called both from `Proposal.apply()` and directly from an adult's "edit" view, so "adult changes apply immediately" and "kid changes apply after approval" are just two callers of the same function, never duplicated logic. `Proposal.reject(reviewed_by, note)` just flips status, no data mutation.

**Explicit simplification (recommend stating this to the user up front):** assignment/budget template edits — whether direct (adult) or approved (kid's proposal) — take effect starting the *next* week's instance generation, never retroactively touching a week whose `ChoreInstance` rows already exist. If you need to change *today's* assignment right now, that's what a `Swap` is for. This keeps instance generation simple/idempotent and avoids ambiguous "did this week's remaining days already lock in the old plan or not" states.

### Shared date utility

`chores/dateutils.py::week_start_of(d)` → the Sunday of the week containing `d`, using `d - timedelta(days=d.isoweekday() % 7)`. Used everywhere: template/budget `effective_from` computation, instance generation, calendar prev/next navigation, history grouping. Having exactly one implementation of this matters given "week starts Sunday" touches almost every model.

---

## 3. Auth & session profile-picker

- Single Django `auth.User` created once via `uv run python manage.py createsuperuser` (documented in README) — this is the shared family login, unrelated to the 4 `Person` rows.
- `people/middleware.py::ActivePersonMiddleware` — after Django's `AuthenticationMiddleware`, reads `request.session.get('active_person_id')`, sets `request.active_person` to the matching `Person` or `None`. Redirects unauthenticated-active-person requests to the picker, except for the picker/login/logout/static URLs themselves (an allowlist).
- `people/context_processors.py::active_person` — exposes `active_person` and a boolean `is_adult` in every template, so templates can conditionally show adult-only controls (approval buttons, etc.) without every view passing it explicitly.
- `people/decorators.py::require_active_person` — for views that assume `request.active_person` is set (defense in depth beyond the middleware for anything exempted from it).
- `people/decorators.py::adult_required` — for approval/reject POST handlers; returns 403 if `request.active_person.role != ADULT`. **This check must be server-side, not just a hidden button in the template**, since the picker is trust-based and a kid could otherwise switch to an adult profile in the UI or simply POST directly to the endpoint.
- **Adult-switch guard (recommendation):** since there's no real security boundary needed but the approval workflow's entire point is defeated if a kid can freely become "Mom" and self-approve, add an *optional* 4-digit PIN per adult `Person` (`pin_hash`, hashed with Django's `make_password`/`check_password`). Switching to a profile with no PIN set is free (default for kids, and optionally for adults who don't care). Switching to a profile *with* a PIN set requires entering it in a small form on the picker. This is intentionally light — not a real auth system, just enough friction that a 12-16 year old can't casually rubber-stamp their own proposal.
- Logout should also clear `active_person_id` from the session (log out = fully reset, not just the Django auth session).

---

## 4. Views / URLs per feature

`H` = HTMX partial response (used for in-place swap), `F` = full page render.

| Feature | Method + URL | View | Response |
|---|---|---|---|
| Login | `GET/POST /login/` | `django.contrib.auth.views.LoginView` (custom template) | F |
| Logout | `POST /logout/` | `LogoutView` subclass clearing `active_person_id` | F (redirect) |
| Profile picker | `GET /profile/` | `ProfilePickerView` | F |
| Select profile (+ PIN if set) | `POST /profile/select/` | `SelectProfileView` | F (redirect to dashboard) |
| Dashboard (today's checklist, all 4 people, notification banner) | `GET /` | `dashboard_view` | F (includes the notifications partial on first render) |
| Notifications banner (polling refresh) | `GET /notifications/partial/` | `notifications_partial_view` | H, `hx-trigger="every 45s"` |
| Check off a chore | `POST /chores/<instance_id>/check/` | `check_off_view` | H (updated instance card) |
| Uncheck (mistake correction) | `POST /chores/<instance_id>/uncheck/` | same view, toggled | H |
| Log time form | `GET /chores/<instance_id>/log-time/` | `log_time_form_view` | H (inline form) |
| Submit time log | `POST /chores/<instance_id>/log-time/` | `log_time_submit_view` | H (updated card w/ new total + budget badge) |
| Swap form | `GET /chores/<instance_id>/swap/` | `swap_form_view` | H |
| Submit swap | `POST /chores/<instance_id>/swap/` | `swap_submit_view` | H |
| Weekly calendar | `GET /calendar/?week=YYYY-MM-DD` | `calendar_view` (calls `ensure_instances_generated`) | F |
| History index | `GET /history/` | `history_index_view` | F |
| History week detail (read-only) | `GET /history/<week_start>/` | `history_week_view` — reuses calendar template with `read_only=True` | F |
| Assignment template list | `GET /assignments/` | `assignment_list_view` | F |
| Assignment edit form | `GET /assignments/<id>/edit/` | `assignment_edit_form_view` | H or F (works both embedded and as direct URL) |
| Submit assignment edit | `POST /assignments/<id>/edit/` | `assignment_edit_submit_view` — branches: adult → `apply_assignment_change()` immediately; kid → creates `Proposal` | H |
| New assignment slot | `GET/POST /assignments/new/` | `assignment_create_view` — same branch | F/H |
| Budget list | `GET /budgets/` | `budget_list_view` | F |
| Budget edit | `GET/POST /budgets/<id>/edit/` | `budget_edit_view` — same immediate-vs-proposal branch | H/F |
| Approval queue | `GET /approvals/` | `approval_queue_view` — everyone can view (full visibility); action buttons only rendered for adults | F |
| Approve | `POST /approvals/<id>/approve/` | `approve_view`, `@adult_required` | H |
| Reject | `POST /approvals/<id>/reject/` | `reject_view`, `@adult_required` | H |

---

## 5. In-app notification computation

No new persistent model — everything is derivable from `ChoreInstance.scheduled_start`/`is_done` plus the current time, and the spec doesn't ask for per-notification dismissal state (if it later does, a small `DismissedNotification(person, chore_instance, dismissed_at)` table would be the minimal addition — not needed for v1).

`chores/notifications.py`:

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

Both are plain functions called from `dashboard_view` and from `notifications_partial_view` — same code path for the initial page load and the HTMX poll, so there's exactly one implementation to test. `now` is always `django.utils.timezone.localtime(timezone.now())` with `USE_TZ = True` and `TIME_ZONE` set to the family's actual zone in settings (needs to be filled in — not specified in the product spec).

The dashboard template renders two sections from these: "Starting soon" (from `get_upcoming_blocks`) and "Not done yet today" (from `get_unfinished_today`), each showing chore name, assigned person, and scheduled time. The `/notifications/partial/` endpoint polls every ~45s via `hx-trigger="every 45s"` so the banner is "live" without any background job, satisfying the no-Celery/no-cron constraint directly.

---

## 6. Admin / seed data

- Register every model in each app's `admin.py`. This gives parents a power-user escape hatch (e.g. fixing a bad time log) without needing a dedicated UI for every edge case in v1.
- The shared login `User` is created via Django's built-in `uv run python manage.py createsuperuser` — no custom code needed, and it's already documented as a `manage.py` command pattern.
- Domain seed data (the 4 `Person` rows, starter `Chore`s, and starter `WeeklyAssignmentTemplate` slots) needs a **custom, idempotent management command** since there's no signup flow and admin alone doesn't give a repeatable "set up a fresh household" path:
  - `people/management/commands/seed_family.py` — `get_or_create`s the 2 adults + 2 kids (names/roles either hardcoded as a documented starting point or read from a small local JSON the family edits before running it).
  - `chores/management/commands/seed_chores.py` — creates a handful of starter `Chore` + `WeeklyAssignmentTemplate` rows (e.g. dishes, trash, laundry) so the app isn't empty on first run.
  - Both commands live behind a shared `seed_default_family()` / `seed_default_chores()` function (in `people/seed.py`, `chores/seed.py`) so tests can call the exact same seeding logic in `setUp()` instead of maintaining a second copy of "what a valid household looks like."

---

## 7. Testing strategy

All via `django.test.TestCase` + Django's test client, runnable with the existing `uv run python manage.py test`.

- **`people`**: profile picker sets session correctly; PIN required/rejected/accepted for adult profiles with a PIN set; logout clears `active_person_id`; middleware redirects to picker when no active person.
- **`chores` — model/service logic**:
  - `ensure_instances_generated(week_start)` is idempotent (calling twice doesn't duplicate rows) and only generates from templates whose effective range covers that week.
  - **History-integrity test (the most important one)**: generate week 1 from template v1, then apply a template edit (creating v2 effective week 2); assert week 1's `ChoreInstance` rows are byte-for-byte unchanged (`assigned_person`, `budgeted_minutes`, `scheduled_start`), and week 2 generation uses v2.
  - Check-off sets `is_done`/`done_by`/`done_at`; un-check reverses it.
  - Multiple `TimeLog` entries sum correctly for a given instance/day/week.
  - Swap: updates `assigned_person` immediately, creates a `Swap` row, is blocked (service-level, not just UI) for past or already-done instances.
- **`budgets`**: `is_over_budget` boundary cases (exactly at limit = no warning, one minute over = warning); asserts that being over budget never prevents check-off or time-log submission (call the view, assert 200/redirect + DB write still happened).
- **`approvals`**: kid-proposed assignment/budget change creates a `PENDING` `Proposal` and does **not** mutate the live template/budget; adult direct edit mutates immediately without ever creating a `Proposal`; approving applies via the shared service function and only affects the *next* week's generation, not already-generated instances; rejecting leaves live data untouched; **an explicit test that POSTing directly to `/approvals/<id>/approve/` as a kid-active-session returns 403**, since that's the one place a URL-guessing attack against the trust-based picker would matter.
- **`chores.notifications`**: use `time-machine`/`freezegun` to fix "now" and assert `get_upcoming_blocks`/`get_unfinished_today` boundaries (just inside window, just outside, exactly at start, midnight-crossing) — this is the logic most prone to off-by-one/timezone bugs and least likely to be caught by manual testing.
- **View-level integration tests**: use `self.client.session["active_person_id"] = person.id; session.save()` to simulate each role (adult/kid) hitting the propose/approve/swap/check-off endpoints end-to-end.

---

## 8. Suggested build order / milestones

| # | Milestone | Acceptance |
|---|---|---|
| 0 | Scaffold: `uv init`, `uv add django django-htmx`, `django-admin startproject chores_manager .`, base settings (`TIME_ZONE`, `django_htmx` middleware), root urls, placeholder view. | `uv sync`, `manage.py migrate`, `manage.py runserver`, `manage.py test` all work per README. |
| 1 | `people` app: `Person` model, admin, `ActivePersonMiddleware` + context processor, login + profile picker (+ optional PIN), `seed_family` command. | Can log in with the shared account, pick a profile, have it persist across requests; logout resets it. |
| 2 | `chores` core: `Chore`, `WeeklyAssignmentTemplate`, `ChoreInstance`, `ensure_instances_generated()`, `seed_chores` command, admin registration. | Visiting a week auto-generates its instances exactly once (idempotency test passes). |
| 3 | Check-off + time log: HTMX endpoints, dashboard renders today's checklist per person with running actual-minutes total. | HTMX partial swap works without a full reload; check-off/log-time tests pass. |
| 4 | `budgets` app: `TimeBudget`, aggregation services, non-blocking warning badges on dashboard. | Over-budget never blocks an action; boundary tests pass. |
| 5 | Swaps: `Swap` model, form/endpoint, guarded against past/completed instances. | Swap reassigns instantly and is visible to both old and new assignee; audit row created. |
| 6 | `approvals` app: `Proposal` (ContentType-based), shared `apply_assignment_change`/`apply_budget_change` services, propose/edit views branching on role, approval queue with server-side adult guard. | Kid change sits pending until approved; adult change applies immediately; 403 test for non-adult approve attempt passes. |
| 7 | Calendar view: server-rendered week grid (simple per-day ordered list of time blocks, not an hour-by-hour pixel grid — satisfies "shows only chore time blocks" with far less template/CSS complexity), prev/next navigation. | Grid shows only that week's blocks; navigating triggers lazy generation for newly-viewed weeks. |
| 8 | In-app notifications: `chores/notifications.py`, dashboard banner, HTMX polling partial. | Starting-soon and unfinished-today sections update correctly on poll; timezone/midnight edge tests pass. |
| 9 | History view: index of past weeks + read-only week detail reusing the calendar template with actions hidden and blocked server-side. | Past weeks display unchanged even after later template edits; direct POST attempts to check-off/swap a past instance are rejected server-side, not just hidden in the UI. |

---

### Critical Files for Implementation
- `chores/models.py` — `WeeklyAssignmentTemplate`/`ChoreInstance`/`TimeLog`/`Swap` and the effective-dating pattern that underpins history integrity
- `chores/services.py` — instance generation (`ensure_instances_generated`) and `apply_assignment_change`, shared by direct-adult-edit and proposal-approval paths
- `approvals/models.py` — the generic `Proposal` (ContentType-based) approval mechanism shared by chores and budgets
- `people/middleware.py` — session-based active-person resolution that every other view depends on
- `chores/notifications.py` — live "starting soon" / "unfinished today" computation logic
