import logging
from acasmart.data.db import get_connection

logger = logging.getLogger(__name__)


# ستون‌های مشترکِ «ترم‌های پایان‌یافته» — یک شکل برای اعلانِ خودکار و برای دکمهٔ نمایش.
_FINISHED_TERMS_SELECT = """
	SELECT
		t.student_id, t.class_id, s.name, s.national_code, c.name, c.day,
		t.id AS term_id, t.end_date AS session_date, t.start_time AS session_time
	FROM student_terms t
	JOIN students s ON s.id = t.student_id
	JOIN classes c  ON c.id = t.class_id
	WHERE t.end_date IS NOT NULL
"""


_NOT_DISMISSED = " AND NOT EXISTS (SELECT 1 FROM dismissed_finished_terms d WHERE d.term_id = t.id)"


def get_unnotified_expired_terms():
	"""ترم‌های پایان‌یافته‌ای که نه اعلان شده‌اند و نه پاک‌شده — برای اعلانِ خودکارِ یک‌بارهٔ هنگام باز کردنِ پنجره."""
	with get_connection() as conn:
		c = conn.cursor()
		c.execute(_FINISHED_TERMS_SELECT +
			" AND NOT EXISTS (SELECT 1 FROM notified_terms n WHERE n.term_id = t.id)" +
			_NOT_DISMISSED)
		return c.fetchall()


def get_visible_finished_terms():
	"""ترم‌های پایان‌یافته‌ای که کاربر از فهرست پاک‌شان نکرده — برای دکمهٔ «نمایش ترم‌های پایان‌یافته »."""
	with get_connection() as conn:
		c = conn.cursor()
		c.execute(_FINISHED_TERMS_SELECT + _NOT_DISMISSED + " ORDER BY t.end_date DESC")
		return c.fetchall()


def dismiss_finished_terms(term_ids):
	"""ترم‌های پایان‌یافته را از فهرستِ نمایش پنهان می‌کند (فقط در نما؛ ردیفِ ترم و سابقه‌اش باقی می‌مانند)."""
	if not term_ids:
		return
	with get_connection() as conn:
		conn.executemany(
			"INSERT OR IGNORE INTO dismissed_finished_terms (term_id) VALUES (?)",
			[(tid,) for tid in term_ids],
		)
		conn.commit()


def mark_terms_as_notified(term_info_list):
	"""
	term_info_list = list of (term_id, student_id, class_id, session_date, session_time)
	"""
	with get_connection() as conn:
		c = conn.cursor()
		c.executemany("""
			INSERT OR IGNORE INTO notified_terms (term_id, student_id, class_id, session_date, session_time)
			VALUES (?, ?, ?, ?, ?)
		""", term_info_list)
		conn.commit()


def has_renew_sms_been_sent(student_id, term_id):
	with get_connection() as conn:
		c = conn.cursor()
		c.execute("""
			SELECT COUNT(*) FROM sms_notifications
			WHERE student_id = ? AND term_id = ?
		""", (student_id, term_id))
		return c.fetchone()[0] > 0


def mark_renew_sms_sent(student_id, term_id):
	with get_connection() as conn:
		conn.execute("""
			INSERT OR IGNORE INTO sms_notifications (student_id, term_id)
			VALUES (?, ?)
		""", (student_id, term_id))
		conn.commit()


def clear_renew_sms_sent(student_id, term_id):
	"""
	پاک‌کردن فلگ «پیامک تمدید ارسال شد» تا امکان ارسال مجدد فراهم شود.
	برای ترم‌هایی که به‌اشتباه (به‌علت باگ قدیمی) ارسال‌شده علامت خورده‌اند.
	"""
	with get_connection() as conn:
		conn.execute("""
			DELETE FROM sms_notifications
			WHERE student_id = ? AND term_id = ?
		""", (student_id, term_id))
		conn.commit()
