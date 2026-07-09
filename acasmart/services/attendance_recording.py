"""Attendance recording use-case: record one attendance outcome and run its effects.

Recording a Present / Absence / Canceled outcome for a Term on a date is not just an
insert: it recomputes Term completion and, if the Term now has exactly one session
remaining, fires the Renewal Reminder. This module is the one Qt-free place that
sequences those effects, so the whole flow is testable without a window.

    UI handler → record_attendance(...) → attendance_repo (persist + completion)
                                        → renewal_reminder (maybe_send)

The SMS transport is injected via ``sender`` (passed through to the reminder) so tests
can drive the full path with a fake.
"""
from dataclasses import dataclass

from acasmart.services.renewal_reminder import RenewalOutcome


@dataclass(frozen=True)
class AttendanceOutcome:
	"""Result of record_attendance(): whether the Term is now complete, and what the
	Renewal Reminder did (NOT_DUE unless the record left exactly one session remaining)."""
	completed: bool
	reminder: RenewalOutcome


def record_attendance(term_id, student_id, class_id, date, status, cancel_reason=None, sender=None):
	"""Record an attendance outcome for a Term on a date and run the downstream effects.

	- persists via insert_attendance_with_date (which recomputes Term completion), then
	- fires the Renewal Reminder (maybe_send) — a no-op unless exactly one session remains.

	`status` is 'present' / 'absent' / 'canceled'; `cancel_reason` applies to 'canceled'.
	Returns an AttendanceOutcome.
	"""
	from acasmart.data.repos.attendance_repo import insert_attendance_with_date
	from acasmart.services import renewal_reminder

	completed = bool(insert_attendance_with_date(student_id, class_id, term_id, date, status, cancel_reason))
	reminder = renewal_reminder.maybe_send(term_id, student_id, class_id, sender=sender)
	return AttendanceOutcome(completed=completed, reminder=reminder)
