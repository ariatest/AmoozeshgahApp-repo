import logging
from acasmart.data.db import get_connection

logger = logging.getLogger(__name__)


def insert_attendance_with_date(student_id, class_id, term_id, date, status, cancel_reason=None):
	"""
	ثبت وضعیت جلسه برای تاریخ مشخص. status یکی از 'present' / 'absent' / 'canceled'.
	جلسهٔ لغوشده در سقف ترم شمرده نمی‌شود. اگر با این ثبت سقف پر شود،
	refresh_completion همان روز را end_date می‌گذارد.
	مقدار True/False برمی‌گرداند که آیا end_date ست شد یا نه.
	"""
	from acasmart.data.repos.terms_repo import refresh_completion
	if status not in {"present", "absent", "canceled"}:
		raise ValueError("invalid attendance status")
	if not term_id:
		term_id = get_term_id_by_student_class_and_date(student_id, class_id, date)
	if not term_id:
		return False  # ترمی پیدا نشد؛ چیزی ثبت نشد

	is_present = 1 if status == "present" else 0
	if status != "canceled":
		cancel_reason = None  # دلیل فقط برای جلسهٔ لغوشده معنا دارد

	with get_connection() as conn:
		conn.execute(
			"""
			INSERT OR REPLACE INTO attendance
				(student_id, class_id, term_id, date, is_present, status, cancel_reason)
			VALUES (?, ?, ?, ?, ?, ?, ?)
			""",
			(student_id, class_id, term_id, date, is_present, status, cancel_reason)
		)
		conn.commit()

	# بعد از ثبت، بررسی و در صورت لزوم بستن ترم (end_date = همان date)
	ended = refresh_completion(term_id)
	return ended


def delete_attendance(student_id, class_id, term_id, date_str):
	"""حذف یک رکورد حضور بر اساس هنرجو/کلاس/ترم/تاریخ (رشته شمسی)."""
	with get_connection() as conn:
		c = conn.cursor()
		c.execute("""
			DELETE FROM attendance
			WHERE student_id = ? AND class_id = ? AND term_id = ? AND date = ?
		""", (student_id, class_id, term_id, date_str))
		conn.commit()
		return c.rowcount  # برای اطلاع از تعداد رکوردهای حذف‌شده


def fetch_attendance_by_date(student_id, class_id, date_str, term_id=None):
	"""
	وضعیت حضور هنرجو در یک کلاس، تاریخ و ترم خاص را برمی‌گرداند.
	اگر term_id داده نشود، از آخرین ترم فعال استفاده می‌کند.
	"""
	from acasmart.data.repos.terms_repo import get_term_id_by_student_and_class
	if term_id is None:
		term_id = get_term_id_by_student_and_class(student_id, class_id)
	if not term_id:
		return None

	with get_connection() as conn:
		c = conn.cursor()
		c.execute("""
			SELECT is_present FROM attendance
			WHERE student_id = ? AND class_id = ? AND term_id = ? AND date = ?
		""", (student_id, class_id, term_id, date_str))
		row = c.fetchone()
		if row is None:
			return None
		return bool(row[0])


def fetch_attendance_status_by_date(student_id, class_id, date_str, term_id=None):
	"""
	وضعیت ثبت‌شدهٔ جلسه را برمی‌گرداند: None (ثبت‌نشده) / 'present' / 'absent' / 'canceled'.
	اگر term_id داده نشود، از آخرین ترم فعال استفاده می‌کند.
	"""
	from acasmart.data.repos.terms_repo import get_term_id_by_student_and_class
	if term_id is None:
		term_id = get_term_id_by_student_and_class(student_id, class_id)
	if not term_id:
		return None

	with get_connection() as conn:
		c = conn.cursor()
		c.execute("""
			SELECT status FROM attendance
			WHERE student_id = ? AND class_id = ? AND term_id = ? AND date = ?
		""", (student_id, class_id, term_id, date_str))
		row = c.fetchone()
		return row[0] if row else None


def get_term_id_by_student_class_and_date(student_id, class_id, selected_date):
	with get_connection() as conn:
		c = conn.cursor()
		c.execute("""
			SELECT id, start_date, end_date
			FROM student_terms
			WHERE student_id = ? AND class_id = ?
		""", (student_id, class_id))
		terms = c.fetchall()

		for term_id, start, end in terms:
			if selected_date >= start and (end is None or selected_date <= end):
				return term_id  # فقط ترمی که بازه‌اش معتبر است
	return None
