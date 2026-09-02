# Household Chores Manager — v1 Backlog

Each task independent, one-session sized. Based on `_docs/plan.md` spec + locked stack decisions (Django + uv, single shared login w/ session-based active-person picker, in-app live-computed notifications only, Django templates + HTMX, server-rendered calendar grid — no JS build, no Celery/cron/push).

## 1. Project scaffolding with a passing test
Goal: Empty Django project runs and tests pass.
Description: Init Django project via `uv` (`uv init`, `uv add django`, `django-admin startproject`), matching README commands (`uv sync`, `manage.py migrate/runserver/test`). Add one trivial test (e.g. homepage returns 200) so `uv run python manage.py test` is green from commit one.

## 2. Family member (Person) model + admin
Goal: Represent the 4 household members in DB.
Description: `Person` model — name, role (adult/kid), active flag. Register in Django admin so household members can be created/edited without a custom UI yet. No login/session logic in this task.

## 3. Shared login + active-profile picker
Goal: One shared family account, but every action still attributable to a specific person.
Description: Single Django `auth.User` (shared login/password). After login, a picker screen lets whoever's using the browser choose which `Person` they are for this session; store `active_person_id` in the session. Include a middleware/decorator that redirects to the picker if no active person is set, and clears it on logout.

## 4. Chore model + weekly recurring assignment template
Goal: Define the fixed weekly plan (who does what, when).
Description: `Chore` model (name, description, default duration) and `WeeklyAssignmentTemplate` (chore, assigned person, day-of-week with Sunday=start-of-week, start time, duration). Admin registration only — no instance generation or UI editing yet.

## 5. Daily instance generation from the weekly template
Goal: Turn the recurring template into concrete, per-date checklist rows.
Description: Service function that, given a week's Sunday date, creates `ChoreInstance` rows from whichever template was active for that week. Must be idempotent (safe to call repeatedly) and must never rewrite instances already generated for a past week, even if the template changes later.

## 6. Check-off + time log on a chore instance
Goal: Mark a chore done and record actual minutes spent.
Description: HTMX endpoints to toggle `is_done` on a `ChoreInstance` and to add a time-log entry (person, minutes, timestamp). Dashboard partial re-renders the instance card in place after either action, no full page reload.

## 7. Daily & weekly time budgets with non-blocking warnings
Goal: Show when someone's approaching or over their time cap, without stopping them.
Description: `TimeBudget` model (per person, daily or weekly minutes cap). Add a service that sums logged time for a person/day/week and compares to their active budget, and a warning badge shown on the dashboard when exceeded. Exceeding a budget must never block check-off or time-logging.

## 8. Instant chore swap between two people
Goal: Let any two family members trade who's doing a specific day's chore, immediately.
Description: Swap endpoint that reassigns a `ChoreInstance.assigned_person` on the spot and records a `Swap` audit row (from/to/who requested it). No approval step. Reject swaps on instances that are already done or dated in the past.

## 9. Propose/edit changes with kid-approval gating
Goal: Kids can suggest assignment/budget changes; adults can apply changes immediately.
Description: A generic pending-change (`Proposal`) mechanism covering both assignment-template and budget edits. When the active person is an adult, edits apply immediately; when a kid, the edit becomes a pending proposal an adult must approve or reject from a queue view. Enforce the adult-only approve/reject action server-side, not just by hiding the button.

## 10. Weekly calendar view
Goal: One place to see the week's chore time blocks only.
Description: Server-rendered week grid (simple per-day ordered list, not an hour-by-hour pixel calendar) showing each person's scheduled chore blocks for the selected week, with prev/next week navigation. Viewing a week triggers lazy instance generation for it if not already generated.

## 11. In-app notifications (starting soon + unfinished today)
Goal: Surface time-sensitive info without any background jobs.
Description: Two live-computed queries — chore blocks starting within the next ~30 minutes, and today's chores still unfinished after their start time. Render as a dashboard banner, refreshed via HTMX polling (e.g. every 45s), computed fresh from current server time on every request.

## 12. Weekly history view
Goal: Let the family look back at past weeks' plans, completions, and time spent.
Description: Read-only index of past weeks plus a per-week detail view (can reuse the calendar template with actions hidden). Must show each past week exactly as it was at the time, unaffected by later edits to the weekly template — and must reject any check-off/swap/log-time POST against a past instance server-side.
