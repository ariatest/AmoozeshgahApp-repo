# AcaSmart

A Persian, right-to-left desktop application that manages the day-to-day operational records of a one-to-one music academy — student enrollments, weekly class scheduling, attendance, tuition and payments, financial reporting, and automatic renewal-reminder SMS.

**Status:** in production — installed and used daily at a music academy &nbsp;·&nbsp;
🔗 **Live:** desktop app, not a public web service &nbsp;·&nbsp;
📦 **Releases:** 12+ tagged releases, currently `v1.1.25` &nbsp;·&nbsp;
🧪 **Tests:** pytest — 60+ tests over enrollment, scheduling conflicts, three-state attendance, derived term completion, term pricing/config, and the renewal-reminder rules

**My role:** Sole developer — requirements, domain modelling, data model, architecture, implementation, tests, packaging and release.

---

## Screenshots

![Dashboard](media/images/dashboard_preview.png)
![Attendance recording](media/images/attendance_preview.png)

More screens: [`media/screenshots/`](media/screenshots/) · [video walkthrough](media/video/project-demo2.mp4)

---

## Problem

A music academy runs on one-to-one lessons: each student has a standing weekly slot with one teacher, pays a term of tuition up front, and renews when the term runs out. Before AcaSmart this was tracked on paper and in spreadsheets — attendance per session, how many sessions of a paid term were left, who owed tuition, and who needed a "your term is ending, please re-register" call. Renewal reminders depended on someone remembering to count sessions.

## What I built

A PySide6 desktop application for Windows and macOS, in Persian with a Jalali (Shamsi) calendar throughout. It covers students and teachers (with instruments and teaching/bank-card details), classes, term enrollment with interval-aware schedule-conflict detection, per-session three-state attendance, snapshotted tuition with tuition and extra payments, live financial reporting, a contact directory, and IPPanel SMS — both an automatic renewal reminder fired when exactly one session of a term remains, and a manual bulk "register for a new term" send. It ships as a per-architecture installable build activated with a license code.

---

## Architecture

```
SQLite DB
  → data/db.py::get_connection()          # one place sets foreign_keys=ON, WAL, Row factory
  → data/repos/<domain>_repo.py           # modules of plain functions, never classes
  → services/*                            # cross-repo workflows (attendance recording, renewal reminder, SMS)
  → ui/windows/*.py                       # PySide6 windows, presentation only
```

| Layer | Responsibility |
|---|---|
| `core/` | domain rules with no UI import — `schedule.py` (weekly occurrence maths on Shamsi dates), `app_init.py` (startup + migrations), config, version, Persian collation |
| `data/db.py` | single connection factory; `get_connection()` / `tx()` — every repo opens, works, closes |
| `data/migrator.py` | `PRAGMA user_version` migration runner; WAL-safe backup before each migration, restore-and-abort on failure |
| `data/repos/` | one module of functions per domain — `enrollment_repo` (enroll/reschedule + conflict detection), `terms_repo` (reads about an existing term, derived completion), attendance, payments, students, teachers, classes, profiles, notifications, reports, settings |
| `services/` | `attendance_recording.py`, `renewal_reminder.py`, `sms_notifier.py` |
| `ui/windows/` | dashboard and secondary windows; all secondary windows extend `BaseSecondaryWindow` (Back action, ESC handler, parent-raise) |

**One action end to end.** When the user saves attendance for a class on a date, `AttendanceManager.save_attendance()` writes each student's `present` / `absent` / `canceled` row into `attendance` (keyed by `term_id` + date), then calls `terms_repo.refresh_term_completion()` for each affected term — which sets or clears the term's `end_date` from counted attendance versus the snapshotted session limit, so a term can also re-open if a record is later deleted. If that save leaves exactly one session remaining, the renewal-reminder SMS fires through `SmsNotifier`, and the `sms_notifications` ledger is written **only** when the provider returns an explicit success — disabled, failed, and rejected sends stay resendable.

---

## Key design decisions

| Decision | Why | Trade-off accepted |
|---|---|---|
| **Schedule-as-truth: no `sessions` table** ([ADR-0002](docs/adr/0002-enrollment-schedule-is-source-of-truth.md), [MODEL-B-DESIGN](docs/MODEL-B-DESIGN.md)) | A lesson is computed weekly from the enrollment's `start_date` + weekday, not stored. `attendance` is the only record of what actually happened, so the schedule and history can't drift apart | A migration (v6) to drop the legacy table; every "list the lessons" query is now a computation over `student_terms` + `attendance` |
| **Term pricing is snapshotted at enrollment** ([ADR-0003](docs/adr/0003-term-pricing-is-snapshotted.md)) | Changing the academy's price list must not silently rewrite what an already-enrolled student owes | Tuition and session limit are duplicated onto every `student_terms` row instead of being looked up live |
| **Term completion is derived, not a frozen lock** ([ADR-0005](docs/adr/0005-term-completion-is-derived-not-frozen.md)) | Attendance gets corrected after the fact; a completed term must be able to re-open when a record is deleted | Completion is recomputed after every attendance change rather than being a one-way state transition |
| **Three-state attendance; reschedule = cancellation + new attendance** ([ADR-0006](docs/adr/0006-three-state-attendance-reschedule-as-cancellation.md)) | Canceled sessions must not burn a paid session; a moved lesson is just a cancel on the old date plus normal attendance on the new one | Every counting query must remember to filter `AND status != 'canceled'` |
| **Lightweight guardrails, not an audit ledger** ([ADR-0007](docs/adr/0007-lightweight-guardrails-not-audit-ledger.md)) | Single non-technical operator, single machine — deletion is blocked once a term has any payment or attendance; corrections are deliberate edits, not history rewrites | No full change history / undo; trades auditability for a simpler schema and UI |
| **Versioned, backed-up migrations before any big refactor** ([ADR-0008](docs/adr/0008-versioned-backed-up-migrations.md)) | The DB lives on the user's machine with real data; a bad migration on launch would lose it | Startup takes a WAL-safe backup and can abort; migration functions must be written idempotently |
| **SQLite, single-file desktop app** | Zero-config install for a non-technical user; the whole DB is one backup-able file | No concurrent multi-user access — would need a real refactor if the academy opened a second branch |
| **Separate x86 and arm64 builds** | Users are on both Intel Windows and Apple Silicon | The release pipeline runs twice per version |

Full domain vocabulary is in [`CONTEXT.md`](CONTEXT.md); the "why" behind the model is in [`docs/adr/`](docs/adr/) (0001–0009).

---

## Tech stack

- **Language:** Python — 3.11 (arm64 / modern) and 3.8 (x86 / legacy Windows 7/8), driven by markers in `requirements.txt`
- **UI:** PySide6 (Qt), custom light/dark theme built from token dicts + a `%`-interpolated QSS template
- **Database:** SQLite (`foreign_keys=ON`, WAL, `sqlite3.Row`), custom `PRAGMA user_version` migration framework
- **Dates:** `jdatetime` / `jalali-core` — all business dates are Shamsi `YYYY-MM-DD` text
- **SMS:** IPPanel (`ippanel`), pattern-based templates
- **Reporting:** pandas / openpyxl for Excel export
- **Packaging:** PyInstaller (`packaging/main.spec`, `packaging/mac.spec`) + Inno Setup (`packaging/setup.iss`); per-architecture ZIP releases

---

## Getting started (development)

```bash
git clone https://github.com/Aramesh-Aria/AcaSmart-repo.git
cd AcaSmart-repo

source .venv-macos-arm64/bin/activate   # Python 3.11, arm64
# or: source .venv-macos-x86/bin/activate   # Python 3.8, x86
pip install -r requirements.txt

cp .env.example .env        # then fill in the values

python main.py              # or: python -m acasmart
```

There is no linter or build script. Sanity-check edits with `python -m compileall -q acasmart`.

The app reads/writes its SQLite DB at the OS app-data dir (e.g. `~/Library/Application Support/AcaSmart/acasmart.db` on macOS), **not** in the repo. First run copies `resources/acasmart_template.db` there and requires a license-code activation.

**Environment variables** (`.env` at repo root)

| Variable | Purpose |
|---|---|
| `ADMIN_MOBILE`, `ADMIN_PASSWORD` | login credentials |
| `IPPANEL_API_KEY`, `IPPANEL_FROM_NUMBER` | SMS gateway |
| `IPPANEL_PATTERN_CODE_1` | pattern for the automatic "one session left" renewal reminder (params `student_name`, `class_name`) |
| `IPPANEL_PATTERN_CODE_2` | pattern for the manual bulk "register for a new term" SMS (param `student_name`) |

---

## Installing (end users)

1. Open the latest release on the [Releases](https://github.com/Aramesh-Aria/AcaSmart-repo/releases) page.
2. Under **Assets**, download the ZIP for your architecture — `x86` / `x86_64` for Intel/AMD, `arm64` for Apple Silicon or Windows on ARM.
3. Unzip, then run `AcaSmart.exe` (Windows) or `AcaSmart.app` (macOS — right-click → **Open** if Gatekeeper warns).
4. Enter a valid **license code** on first launch.
5. To update, download the newest ZIP for your architecture and replace the previous version.

---

## Testing

```bash
pytest
```

Tests point `data.db.DB_PATH` / `data.migrator.DB_PATH` at a throwaway copy of a real DB and exercise the repo and service logic:

- `test_enrollment.py` — `enroll()` / `reschedule()`, interval-aware student and teacher schedule-conflict detection, one-active-term rule
- `test_attendance_recording.py` — three-state attendance writes and counting
- `test_term_progress.py`, `test_finished_terms.py` — derived term completion, re-opening on deletion
- `test_term_config.py` — session-limit resolution (term snapshot → pricing profile → default setting)
- `test_renewal_reminder.py` — the "exactly one session left" trigger and the ledger's send-only-on-success rule
- `test_config.py` — settings helpers

Interactive GUI flows (click paths, dialog sequences) have no automated coverage and are verified by launching the app. There is no CI configured.

---

## Roadmap

- [ ] Deeper modules for the remaining architecture candidates (payments, reporting, notifications)
- [ ] Add CI on GitHub Actions to run `pytest` on every push
- [ ] Non-interactive smoke test for widget construction under `QT_QPA_PLATFORM=offscreen`
- [ ] Optional cloud backup of the app-data DB

---

## Documentation

- [`CONTEXT.md`](CONTEXT.md) — canonical domain vocabulary (Student, Teacher, Term, Session, Attendance, Renewal Reminder, …)
- [`docs/adr/`](docs/adr/) — architecture decision records 0001–0009
- [`docs/MODEL-B-DESIGN.md`](docs/MODEL-B-DESIGN.md) — the schedule-as-truth refactor
- [`docs/IMPLEMENTATION-PLAN.md`](docs/IMPLEMENTATION-PLAN.md) — the v2–v5 hardening roadmap (shipped)
- [`docs/README_DEV.md`](docs/README_DEV.md) — the data-layer refactor from the old monolithic `db_helper.py`
- [`CLAUDE.md`](CLAUDE.md) — architecture notes and conventions

---

## License

Proprietary — provided for review and portfolio purposes only. See [LICENSE](LICENSE).

## Contact

Ahmad (Aria) Aramesh Moghaddam — aramesh_aria@yahoo.com — [github.com/Aramesh-Aria](https://github.com/Aramesh-Aria)
