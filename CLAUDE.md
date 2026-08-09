# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Domain language

`CONTEXT.md` defines the canonical terms for this codebase (Student, Teacher, Term, Session, Attendance, Renewal Reminder, etc.). Read it before working on any feature. Using the wrong term (e.g. "Course" instead of "Term") will confuse the model and the code.

## Running the app

There is no `pyproject.toml`, `Makefile`, or setup script. Run directly:

```bash
source .venv-macos-arm64/bin/activate   # Python 3.11, arm64
# or
source .venv-macos-x86/bin/activate     # Python 3.8, x86

python main.py
# or
python -m acasmart
```

The app requires a `.env` file at the repo root with:
- `ADMIN_MOBILE`, `ADMIN_PASSWORD` — login credentials
- `IPPANEL_API_KEY`, `IPPANEL_FROM_NUMBER` — SMS gateway
- `IPPANEL_PATTERN_CODE_1` — pattern for the automatic "one session left" renewal reminder (attendance flow; params `student_name`, `class_name`)
- `IPPANEL_PATTERN_CODE_2` — pattern for the manual bulk "register for a new term" SMS (send-SMS window; param `student_name`)

There are no tests and no linter configured. Sanity-check edits with `python -m compileall -q acasmart`.

### Building / packaging

PyInstaller + Inno Setup (no build script — invoke the spec directly):

```bash
pyinstaller packaging/main.spec    # Windows (.exe); then packaging/setup.iss → installer via Inno Setup
pyinstaller packaging/mac.spec     # macOS (.app)
```

Releases ship as per-architecture ZIPs (x86 / arm64). The app reads/writes its SQLite DB at the OS app-data dir (`acasmart/paths.py::get_app_data_dir()`), e.g. `~/Library/Application Support/AcaSmart/acasmart.db` on macOS — **not** in the repo. First run copies `resources/acasmart_template.db` there and requires a license-code activation.

## Architecture

### Data flow

```
SQLite DB  →  data/db.py::get_connection()  →  data/repos/<domain>_repo.py  →  ui/windows/*.py
```

- **Repos** are modules of plain functions, never classes. Each function opens a connection via `get_connection()`, does its work, and closes it. Use `with get_connection() as conn:` for auto-close; use `tx()` from `data/db.py` when you need explicit commit/rollback.
- `get_connection()` always sets `PRAGMA foreign_keys=ON`, `journal_mode=WAL`, `row_factory=sqlite3.Row`.

### Model-B: schedule-as-truth, computed lessons (ADR-0002)

There is **no `sessions` table** (dropped in migration v6). A lesson is not a stored row — it is computed from the enrollment's weekly schedule:

- **Enrollment = a `student_terms` row** (the "Term"): `student_id`, `class_id`, `start_date`, `start_time`, `lesson_duration`, `sessions_limit`, snapshotted tuition, `end_date`. Created via `enrollment_repo.enroll()` (returns an `EnrollmentResult` carrying the `term_id`, or a precise reason on failure). `start_date` is snapped to the class weekday with `core/schedule.first_on_or_after()`.
- **Occurrences are computed** weekly from `start_date` (same weekday, every 7 days) by `core/schedule.py` (`is_weekly_occurrence`, `occurrence_dates`). All dates are Shamsi strings; arithmetic goes through `jdatetime`.
- The attendance list comes from `enrollment_repo.fetch_scheduled_students_for_class_on_date()` — computed from `student_terms` + `attendance`, never from session rows.
- `attendance` (keyed by `term_id` + `date`) is the **only** record of what actually happened.
- `enrollment_repo.py` (renamed from the misnamed `sessions_repo`) owns the enrollment lifecycle — `enroll()` / `reschedule()` plus interval-aware schedule-conflict detection — over `student_terms`; there is no session CRUD. `terms_repo` owns reads about an existing Term (progress, config, completion). See `docs/MODEL-B-DESIGN.md`.

### Migration framework (`data/migrator.py`)

`run_migrations()` is called at startup (wired in `core/app_init.py`) instead of calling `create_tables()` directly.

- Uses `PRAGMA user_version` as the version counter. `BASELINE_VERSION = 1`.
- Before applying any pending migration it takes a WAL-safe backup via `sqlite3.Connection.backup()` to `<app_data>/backups/`.
- On failure: restores backup, aborts startup with a clear message.
- Each `fn(conn)` in `MIGRATIONS` receives an autocommit connection and must manage its own transaction. Use the `transactional(conn)` helper for single-transaction migrations.
- Keep migration functions idempotent (guard with `PRAGMA table_info` / `sqlite_master`).

Current `MIGRATIONS` list: v2 payments integrity, v3 attendance status, v4 lesson_duration, v5 dedup active terms + partial unique index, **v6 drop the legacy `sessions` table**. `schema.py::create_tables()` no longer creates `sessions`, so it cannot reappear after v6.

### UI / window lifecycle

- `LoginWindow` → `DashboardWindow` → secondary windows.
- All secondary windows extend `BaseSecondaryWindow` (`ui/widgets/base_secondary_window.py`): receives `return_target`, adds a Back toolbar action and ESC handler that raises the parent and closes self.
- Store window references on the opener (`self.<name>_window = ...`) to prevent garbage collection.
- Interactive GUI behaviour (clicks, dialog flows) can only be verified by launching the full app. For a non-interactive smoke test, `pip install PySide6` and instantiate widgets under `QT_QPA_PLATFORM=offscreen` — this catches import/construction errors but not click flows. Repo/migration logic is best tested by pointing `data.db.DB_PATH` + `data.migrator.DB_PATH` at a `shutil.copyfile` copy of the live DB.

### Theme system

- Two token dicts in `style/theme.py`: `LIGHT` and `DARK`.
- `build_qss(tokens)` in `style/qss.py` fills `BASE_QSS` (a `%`-interpolated template) with the chosen tokens.
- `ThemeManager` in `ui/widgets/theme_manager.py` is class-level state. Call `ThemeManager.repolish(widget)` after changing a `setProperty("variant", ...)` so QSS re-evaluates.
- Buttons get their variant via `setProperty("variant", "primary"|"secondary"|"ghost")`.

### SMS / Renewal Reminder

- Provider: IPPanel. `SmsNotifier` in `services/sms_notifier.py`.
- Returns `{"status": SmsStatus.SENT | FAILED | DISABLED}` or raises on non-200.
- Write to `sms_notifications` ledger **only on `SmsStatus.SENT`**. Never mark sent on `DISABLED` or `FAILED` — those must stay resendable.
- `clear_renew_sms_sent(student_id, term_id)` in `notifications_repo.py` resets the flag before a forced resend.
- Renewal SMS fires in `AttendanceManager.save_attendance()` when exactly one session remains (count == limit−1). Manual SMS in `SmsNotificationWindow` does not touch the ledger.

## Key conventions

- **Three-state attendance**: `status` is `'present'`, `'absent'`, or `'canceled'`. Canceled sessions are never counted toward the term session limit. All counting queries must filter `AND status != 'canceled'`.
- **Term completion is derived**: `terms_repo.refresh_term_completion(term_id)` sets or clears `end_date` based on counted attendance vs `sessions_limit`. It is two-way — it can re-open a completed term if an attendance record is deleted. Call it after every attendance change.
- **One active term rule**: enforced by `idx_one_active_term` partial unique index on `student_terms(student_id, class_id) WHERE end_date IS NULL` (added in migration v5). `insert_student_term_if_not_exists` catches `IntegrityError` from this index and returns `None`.
- **Interval-aware conflict detection**: `_has_student_schedule_conflict` and `_has_teacher_schedule_conflict` in `enrollment_repo.py` compare `[start, start+duration)` intervals over active `student_terms` on the same weekday, not exact time strings. Used internally by `enroll()` / `reschedule()`.
- **Persian calendar**: all business dates are Shamsi (Jalali) stored as `YYYY-MM-DD` text. Use `ShamsiDatePicker` / `ShamsiDatePopup` widgets; never use Gregorian dates in the UI.

## Design history

- **Domain model**: `CONTEXT.md` (canonical terms) + ADRs `docs/adr/0001`–`0009`.
- **Hardening roadmap**: `docs/IMPLEMENTATION-PLAN.md` — items 1–7 (SMS fix, deletion guard, derived completion, three-state attendance, payment integrity, interval conflict, one-active-term), shipped as migrations v2–v5. **Done.**
- **Model-B refactor**: `docs/MODEL-B-DESIGN.md` — schedule-as-truth, `sessions` table dropped (v6). **Done.**

These docs are the historical record of *why* the code is shaped this way; read the relevant one before changing the term/attendance/scheduling model.
