"""Renewal Reminder — the one place the reminder policy lives.

A Renewal Reminder fires when exactly one session remains in a Term, after the
Attendance that leaves one remaining is recorded (CONTEXT.md). This module owns the
whole policy: when it fires, whether it has already gone out, sending it, and — only
on a confirmed send — writing the ledger. Disabled/failed sends stay resendable.

The SMS transport is injected (``sender``) so the policy is testable without the network:
any object with ``send_renew_term_notification(name, phone, class_name) -> {"status": SmsStatus}``
satisfies it. In production the lazy default is a real :class:`SmsNotifier`.

This is distinct from the Manual SMS path (``SmsNotificationWindow``), which never touches
the ledger.
"""
from enum import Enum

from acasmart.services.sms_notifier import SmsNotifier, SmsStatus


class RenewalOutcome(Enum):
	SENT = "sent"                  # sent and recorded in the ledger
	ALREADY_SENT = "already_sent"  # ledger already has it — no-op
	NOT_DUE = "not_due"            # term is not at exactly one remaining — no-op
	NO_PHONE = "no_phone"          # student has no phone — nothing sent
	DISABLED = "disabled"          # SMS disabled in settings — stays resendable
	FAILED = "failed"              # send failed/rejected — stays resendable


_default_sender = None


def _get_sender():
	"""Lazily build the production SMS transport (avoids constructing it at import time)."""
	global _default_sender
	if _default_sender is None:
		_default_sender = SmsNotifier()
	return _default_sender


def already_sent(term_id, student_id):
	"""Has this Term's Renewal Reminder been recorded as sent? (For the attendance display.)"""
	from acasmart.data.repos.notifications_repo import has_renew_sms_been_sent
	return has_renew_sms_been_sent(student_id, term_id)


def maybe_send(term_id, student_id, class_id, sender=None):
	"""Fire the Renewal Reminder iff the Term is at exactly one remaining and it hasn't
	already been sent. No-op otherwise (NOT_DUE / ALREADY_SENT). Call after recording Attendance.
	"""
	from acasmart.data.repos.terms_repo import term_progress
	from acasmart.data.repos.notifications_repo import has_renew_sms_been_sent
	progress = term_progress(term_id)
	if progress is None or progress.remaining != 1:
		return RenewalOutcome.NOT_DUE
	if has_renew_sms_been_sent(student_id, term_id):
		return RenewalOutcome.ALREADY_SENT
	return _send_and_record(term_id, student_id, class_id, sender)


def force_resend(term_id, student_id, class_id, sender=None):
	"""Manual resend: clear the ledger flag and send unconditionally (ignores the trigger)."""
	from acasmart.data.repos.notifications_repo import clear_renew_sms_sent
	clear_renew_sms_sent(student_id, term_id)
	return _send_and_record(term_id, student_id, class_id, sender)


def _send_and_record(term_id, student_id, class_id, sender):
	"""Send the reminder and, only on a confirmed SENT, write the ledger.

	The 'record only on SENT' rule lives here and nowhere else, so DISABLED/FAILED/NO_PHONE
	never mark the Term as reminded and remain resendable.
	"""
	from acasmart.data.repos.students_repo import get_student_contact
	from acasmart.data.repos.reports_repo import get_class_and_teacher_name
	from acasmart.data.repos.notifications_repo import mark_renew_sms_sent

	name, phone = get_student_contact(student_id)
	if not phone:
		return RenewalOutcome.NO_PHONE
	class_name, _ = get_class_and_teacher_name(class_id)

	try:
		result = (sender or _get_sender()).send_renew_term_notification(name, phone, class_name)
	except Exception as e:
		print(f"[ERROR] renewal SMS failed for sid={student_id}, term_id={term_id}: {e}")
		return RenewalOutcome.FAILED

	status = result.get("status") if isinstance(result, dict) else None
	if status == SmsStatus.SENT:
		mark_renew_sms_sent(student_id, term_id)
		return RenewalOutcome.SENT
	if status == SmsStatus.DISABLED:
		return RenewalOutcome.DISABLED
	return RenewalOutcome.FAILED
