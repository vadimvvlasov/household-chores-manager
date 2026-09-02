# Household Chores Manager — v1 Backlog

Per `_docs/process.md`, tasks are tracked as GitHub issues — each task below is mirrored there, and issue open/closed state is canonical for progress. This file stays as the reference spec/description for each task (source of truth for *content*, not status). Full acceptance criteria, out-of-scope links, and file/dependency constraints live on the issue itself, groomed per `_docs/team/pm.md`; this file keeps the one-paragraph summary in sync.

Each task independent, one-session sized. Based on `_docs/plan.md` spec + `_docs/outdated/architecture.md` (Django + uv, single shared login w/ session-based active-person picker, in-app notifications recomputed on page load, plain Django template forms with full-page POST/redirect/GET — no HTMX, no JS build, no Celery/cron/push). Two apps: `people` (login/session/`Person`) and `chores` (everything else).

## 1. Project scaffolding with a passing test — closed
Goal: Empty Django project runs and tests pass.
Description: Init Django project via `uv` (`uv init`, `uv add django`, `django-admin startproject`), matching README commands (`uv sync`, `manage.py migrate/runserver/test`). Add one trivial test (e.g. homepage returns 200) so `uv run python manage.py test` is green from commit one.

## 2. Family member (Person) model + admin
Goal: Represent the 4 household members in DB.
Description: `people` app. `Person` model — `name`, `role` (`TextChoices` `ADULT`/`KID`), `is_active` (default `True` — deactivate, don't delete, since later apps FK to `Person`). Register in Django admin (list shows name/role/is_active) so household members can be created/edited without a custom UI yet. No login/session logic in this task. Budget fields → #7. Seeding the real 4 members → #12.

## 3. Shared login + active-profile picker
Goal: One shared family account, but every action still attributable to a specific person.
Description: Single Django `auth.User` (shared login/password). After login, a picker screen (only `is_active=True` people, re-checked every request) lets whoever's using the browser choose which `Person` they are for this session; store `active_person_id` in the session. `ActivePersonMiddleware` redirects to the picker if no active person is set (allowlist: picker/login/logout/static/admin), and clears it on logout. No PIN — trust-based, accepted v1 trade-off. Redirects to the existing homepage stub from #1; real dashboard content is built in #6.

## 4. Chore model + weekly recurring assignment template
Goal: Define the fixed weekly plan (who does what, when).
Description: `chores` app. `Chore` model (name, description, default duration, is_active) and `WeeklyAssignmentTemplate` (chore FK, assigned person FK, day-of-week with Sunday=0=start-of-week, start time, duration). Both FKs `on_delete=PROTECT` — deleting a `Chore`/`Person` still referenced by a template must raise, not silently cascade away assignment history. Admin registration only — no instance generation or non-admin UI editing yet (that's #9).

## 5. Daily instance generation from the weekly template
Goal: Turn the recurring template into concrete, per-date checklist rows.
Description: `ChoreInstance` (template + chore FKs `PROTECT`, date, scheduled_start, budgeted_minutes, assigned_person — all snapshotted from the template at generation time; is_done/done_at/done_by). `unique_together(template, date)`. Service function `ensure_instances_generated(week_start)`, given a week's Sunday date, creates instances from whichever templates were active for that week, skipping any template whose chore or assigned person is inactive. Idempotent (safe to call repeatedly) and must never rewrite instances already generated for a past week, even if the template changes later.

## 6. Check-off + time log on a chore instance
Goal: Mark a chore done and record actual minutes spent.
Description: Builds the actual dashboard view at `/` (nothing built one yet — earlier issues only had the #1 stub redirect target) listing today's instances for **everyone** in the household, not just the active person. Plain form views to toggle `is_done` on a `ChoreInstance` and to add a `TimeLog` entry (`chore_instance` FK `CASCADE` — logs are dependent data, unlike the `PROTECT` FKs elsewhere; logged_by, minutes, logged_at, note), each posting and redirecting back to the dashboard. Reject both actions server-side for instances dated before today.

## 7. Daily & weekly time budgets with non-blocking warnings
Goal: Show when someone's approaching or over their time cap, without stopping them.
Description: `daily_budget_minutes`/`weekly_budget_minutes` fields on `Person` (nullable = no cap set). Service sums `TimeLog.minutes` by `logged_by` and `logged_at`'s date — **not** `ChoreInstance.assigned_person`/date, since a swap can move an instance's assignment after time was already logged against it, and the budget should track who actually spent the time. Warning triggers strictly above the cap (at-limit is not a warning). Badge shown on the dashboard when exceeded. Exceeding a budget must never block check-off or time-logging.

## 8. Instant chore swap between two people
Goal: Let any two family members trade who's doing a specific day's chore, immediately.
Description: Swap endpoint that reassigns a `ChoreInstance.assigned_person` directly to another person, on the spot — any active person can trigger it, not just the two people involved or adults only. No approval step, no separate audit record — `assigned_person` plus `done_by` are enough for who's-responsible/who-actually-did-it visibility. Reject swaps on instances that are already done or dated in the past, with no DB write on rejection.

## 9. Propose/edit changes with kid-approval gating
Goal: Kids can suggest assignment/budget changes; adults can apply changes immediately.
Description: Two small pending-change models — `ProposedAssignmentChange` and `ProposedBudgetChange` — each with plain typed fields for the proposed values (no generic/JSON payload). When the active person is an adult, edits apply immediately via a shared apply-service function; when a kid, the edit becomes a pending row an adult must approve or reject from a queue view, which calls that same apply function. Enforce the adult-only approve/reject action server-side, not just by hiding the button.

## 10. Weekly calendar view (also serves as history)
Goal: One place to see the week's chore time blocks — for this week or any past week.
Description: Server-rendered week grid (simple per-day ordered list, not an hour-by-hour pixel calendar) showing each person's scheduled chore blocks for the selected week, with prev/next week navigation. Viewing a week triggers lazy instance generation for it if not already generated. For a past week, the same server-side "no edits before today" guard from tasks #6/#8 means the grid is naturally read-only — no separate history view/URL needed.

## 11. In-app notifications (starting soon + unfinished today)
Goal: Surface time-sensitive info without any background jobs.
Description: Two live-computed queries — chore blocks starting within the next ~30 minutes, and today's chores still unfinished after their start time. Render as a dashboard section, recomputed fresh from current server time on every full-page load (no polling, no background job). Needs `TIME_ZONE` actually set to the family's zone (currently UTC default) and boundary tests via a time-travel library (`time-machine`/`freezegun`) — that's a new dependency, ask before `uv add`ing per AGENTS.md.

## 12. Seed default family members
Goal: The 4 real household members exist without hand-typing them into `/admin/` on every fresh DB.
Description: Management command (`people/management/commands/seed_family.py`) backed by a plain `seed_default_family()` function so tests can call it directly in `setUp()`; `get_or_create`s the 4 people so re-running it doesn't duplicate rows. Depends on #2.
