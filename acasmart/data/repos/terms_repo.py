import logging
import sqlite3
from acasmart.data.db import get_connection

logger = logging.getLogger(__name__)


def insert_student_term_if_not_exists(
	student_id, class_id, start_date, start_time,
	sessions_limit=None, tuition_fee=None, currency_unit=None, profile_id=None,
	lesson_duration=None
):
	from acasmart.data.repos.settings_repo import get_setting  # local to avoid cycles
	from acasmart.data.repos.sessions_repo import (
		has_teacher_schedule_conflict, has_student_schedule_conflict,
	)  # avoid cycles
	eff_duration = int(lesson_duration) if lesson_duration else 30
	with get_connection() as conn:
		c = conn.cursor()

		# اگر ترم فعالِ دقیقا با همین start_date/start_time هست، همان را برگردان (idempotent)
		c.execute("""
			SELECT id
			FROM student_terms
			WHERE student_id=? AND class_id=? AND start_date=? AND start_time=? AND end_date IS NULL
		""", (student_id, class_id, start_date, start_time))
		row = c.fetchone()
		if row:
			term_id = row[0]
			# اگر ترم موجود است ولی کاربر مقدار سفارشی داده، روی همان ترم ست کن
			if any(v is not None for v in (sessions_limit, tuition_fee, currency_unit, profile_id)):
				if currency_unit is None:
					currency_unit = get_setting("currency_unit", "toman")
				c.execute("""
					UPDATE student_terms
					   SET sessions_limit = COALESCE(?, sessions_limit),
					       tuition_fee    = COALESCE(?, tuition_fee),
					       currency_unit  = COALESCE(?, currency_unit),
					       profile_id     = COALESCE(?, profile_id),
					       updated_at     = datetime('now','localtime')
					 WHERE id=?
				""", (sessions_limit, tuition_fee, currency_unit, profile_id, term_id))
				conn.commit()
			return term_id

		# Model-B: تداخلِ برنامهٔ هفتگی، محاسبه‌شده از ترم‌ها (نه جلسات) — استاد و سپس هنرجو
		if has_teacher_schedule_conflict(class_id, start_time, new_duration=eff_duration):
			return None
		if has_student_schedule_conflict(student_id, class_id, start_time, new_duration=eff_duration):
			return None

		# عدم شروع قبل از پایان ترم قبلی
		c.execute("""
			SELECT end_date FROM student_terms
			WHERE student_id=? AND class_id=? AND end_date IS NOT NULL
			ORDER BY end_date DESC LIMIT 1
		""", (student_id, class_id))
		last = c.fetchone()
		if last and start_date < last[0]:
			return None

		# مقادیر پیش‌فرض برای فیلدهای سفارشی
		if sessions_limit is None:
			sessions_limit = int(get_setting("term_session_count", 12))
		if tuition_fee is None:
			tuition_fee = int(get_setting("term_fee", get_setting("term_tuition", 6000000)))
		if currency_unit is None:
			currency_unit = get_setting("currency_unit", "toman")

		# درج ترم جدید با مقادیر سفارشی
		try:
			c.execute("""
				INSERT INTO student_terms
					(student_id, class_id, start_date, start_time, end_date,
					 sessions_limit, tuition_fee, currency_unit, profile_id, lesson_duration)
				VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)
			""", (student_id, class_id, start_date, start_time,
			      sessions_limit, tuition_fee, currency_unit, profile_id, eff_duration))
			conn.commit()
			return c.lastrowid
		except sqlite3.IntegrityError:
			# نقضِ ایندکسِ «یک ترمِ فعال»: این هنرجو از قبل ترمِ فعال در این کلاس دارد
			return None


def delete_student_term_by_id(term_id):
	with get_connection() as conn:
		conn.execute("DELETE FROM student_terms WHERE id = ?", (term_id,))
		conn.commit()


def update_term_schedule(term_id, new_start_time, new_duration=None):
	"""Model-B: change an existing enrollment's weekly time (and optionally lesson duration).

	Only the time-of-day changes — the weekday and start_date are untouched (the class
	day is unchanged), so the computed weekly occurrences simply shift to the new time.
	Re-runs interval-aware teacher/student conflict detection, excluding this term itself.

	Returns:
		True                on success,
		'notfound'          if the term does not exist,
		'teacher_conflict'  if the new slot overlaps the teacher's weekly schedule,
		'student_conflict'  if it overlaps the student's own weekly schedule.
	"""
	from acasmart.data.repos.sessions_repo import (
		has_teacher_schedule_conflict, has_student_schedule_conflict,
	)  # local import to avoid cycles
	with get_connection() as conn:
		c = conn.cursor()
		row = c.execute(
			"SELECT student_id, class_id, COALESCE(lesson_duration, 30) FROM student_terms WHERE id=?",
			(term_id,),
		).fetchone()
		if not row:
			return 'notfound'
		student_id, class_id, cur_dur = row
		eff_dur = int(new_duration) if new_duration else int(cur_dur or 30)

		if has_teacher_schedule_conflict(class_id, new_start_time, new_duration=eff_dur, exclude_term_id=term_id):
			return 'teacher_conflict'
		if has_student_schedule_conflict(student_id, class_id, new_start_time, new_duration=eff_dur, exclude_term_id=term_id):
			return 'student_conflict'

		c.execute(
			"""UPDATE student_terms
			      SET start_time = ?, lesson_duration = ?, updated_at = datetime('now','localtime')
			    WHERE id = ?""",
			(new_start_time, eff_dur, term_id),
		)
		conn.commit()
		return True


def get_student_term(student_id, class_id):
	with get_connection() as conn:
		c = conn.cursor()
		c.execute("""
			SELECT start_date, end_date
			FROM student_terms
			WHERE student_id=? AND class_id=?
		""", (student_id, class_id))
		return c.fetchone()


def get_last_term_end_date(student_id, class_id):
	with get_connection() as conn:
		c = conn.cursor()
		c.execute("""
			SELECT end_date
			FROM student_terms
			WHERE student_id = ? AND class_id = ?
			AND end_date IS NOT NULL
			ORDER BY end_date DESC
			LIMIT 1
		""", (student_id, class_id))
		row = c.fetchone()
		return row[0] if row else None


def get_active_term_count_per_student():
	"""{student_id: تعدادِ ترم‌های فعال} — برای نمایش کنارِ نام در پنجرهٔ انتخاب هنرجو (Model-B)."""
	with get_connection() as conn:
		c = conn.cursor()
		c.execute("""
			SELECT student_id, COUNT(*)
			FROM student_terms
			WHERE end_date IS NULL
			GROUP BY student_id
		""")
		return {row[0]: row[1] for row in c.fetchall()}


def get_active_term_count_per_class():
	"""{class_id: تعدادِ ترم‌های فعال} — برای نمایش کنارِ کلاس در پنجرهٔ انتخاب کلاس (Model-B)."""
	with get_connection() as conn:
		c = conn.cursor()
		c.execute("""
			SELECT class_id, COUNT(*)
			FROM student_terms
			WHERE end_date IS NULL
			GROUP BY class_id
		""")
		return {row[0]: row[1] for row in c.fetchall()}


def get_term_id_by_student_and_class(student_id, class_id):
	with get_connection() as conn:
		c = conn.cursor()
		c.execute("""
			SELECT id FROM student_terms
			WHERE student_id = ? AND class_id = ? AND end_date IS NULL
			ORDER BY id DESC LIMIT 1
		""", (student_id, class_id))
		row = c.fetchone()
		return row[0] if row else None


def get_all_terms_for_student_class(student_id, class_id):
	with get_connection() as conn:
		c = conn.cursor()
		c.execute("""
			SELECT id, start_date, end_date, created_at
			FROM student_terms
			WHERE student_id = ? AND class_id = ?
			ORDER BY start_date DESC
		""", (student_id, class_id))
		return c.fetchall()


def refresh_term_completion(term_id):
	"""وضعیتِ تکمیلِ ترم را از روی شمارشِ حضور (حاضر+غایب) بازمحاسبه می‌کند (ADR-0005).

	تکمیل یک «وضعیتِ مشتق‌شده» است، نه قفلِ یک‌طرفه:
	- اگر جلسات مصرف‌شده (به‌جزِ لغوشده) به سقفِ ترم برسد → end_date = آخرین تاریخِ مصرف‌شده.
	- در غیرِ این صورت → end_date = NULL (ترم دوباره فعال می‌شود و ویرایشِ گذشته ممکن می‌گردد).

	برای حفظِ قاعدهٔ «یک ترمِ فعال» (آیتم ۶)، اگر بازکردنِ این ترم باعثِ وجودِ دو ترمِ فعال برای
	همان هنرجو/کلاس شود، end_date را NULL نمی‌کند و مارکر را نگه می‌دارد.
	خروجی: True اگر ترم اکنون تکمیل‌شده است.
	"""
	from acasmart.data.repos.settings_repo import get_setting  # local to avoid cycles
	with get_connection() as conn:
		c = conn.cursor()
		c.execute("""
			SELECT student_id, class_id, sessions_limit, end_date
			FROM student_terms WHERE id = ?
		""", (term_id,))
		row = c.fetchone()
		if not row:
			return False
		sid, cid, term_limit, current_end = row[0], row[1], row[2], row[3]
		try:
			term_limit = int(term_limit)
		except (TypeError, ValueError):
			term_limit = int(get_setting("term_session_count", 12))

		c.execute("""
			SELECT COUNT(*), MAX(date) FROM attendance
			WHERE term_id = ? AND status != 'canceled'
		""", (term_id,))
		crow = c.fetchone()
		total = crow[0] or 0
		last_date = crow[1]

		if total >= term_limit:
			new_end = last_date or current_end
			if current_end != new_end:
				c.execute("""
					UPDATE student_terms SET end_date = ?, updated_at = datetime('now','localtime')
					WHERE id = ?
				""", (new_end, term_id))
				conn.commit()
			return True

		# زیرِ سقف → ترم باید فعال باشد، مگر اینکه ترمِ فعالِ دیگری برای همان هنرجو/کلاس وجود داشته باشد
		if current_end is not None:
			c.execute("""
				SELECT COUNT(*) FROM student_terms
				WHERE student_id = ? AND class_id = ? AND end_date IS NULL AND id != ?
			""", (sid, cid, term_id))
			if c.fetchone()[0] == 0:
				c.execute("""
					UPDATE student_terms SET end_date = NULL, updated_at = datetime('now','localtime')
					WHERE id = ?
				""", (term_id,))
				conn.commit()
		return False


def recalc_term_end_by_id(term_id: int):
	"""سازگاریِ به‌عقب: اکنون از refresh_term_completion (تکمیلِ دوطرفه) استفاده می‌کند."""
	refresh_term_completion(term_id)


def get_term_dates(term_id):
	with get_connection() as conn:
		c = conn.cursor()
		c.execute("""
			SELECT start_date, end_date FROM student_terms
			WHERE id = ?
		""", (term_id,))
		return c.fetchone()


def get_term_tuition_by_id(term_id: int):
	with get_connection() as conn:
		c = conn.cursor()
		c.execute("SELECT tuition_fee FROM student_terms WHERE id= ?", (term_id,))
		row = c.fetchone()
		return int(row[0]) if row and row[0] is not None else None


def get_term_sessions_limit_by_id(term_id: int):
	"""
	سقف جلسات ترم را برمی‌گرداند.
	اول از student_terms.sessions_limit، اگر تهی بود از pricing_profiles.sessions_limit
	و در نهایت از تنظیمات پیش‌فرض term_session_count.
	"""
	with get_connection() as conn:
		c = conn.cursor()
		c.execute("""
			SELECT
			  COALESCE(st.sessions_limit, pp.sessions_limit) AS lim
			FROM student_terms st
			LEFT JOIN pricing_profiles pp ON pp.id = st.profile_id
			WHERE st.id = ?
		""", (term_id,))
		row = c.fetchone()
		if row and row[0] is not None:
			return int(row[0])
	# fallback بیرون از DB (در خود PaymentManager هم دوباره fallback می‌کنیم)
	return None


def check_and_set_term_end_by_id(term_id, student_id, class_id, session_date):
	"""سازگاریِ به‌عقب: اکنون از refresh_term_completion (تکمیلِ دوطرفه) استفاده می‌کند.
	خروجی: True اگر ترم پس از این ثبت تکمیل شده باشد."""
	return refresh_term_completion(term_id)


def get_all_expired_terms():
	with get_connection() as conn:
		c = conn.cursor()
		c.execute("""
			SELECT s.name, s.national_code, c.name, c.day
			FROM student_terms t
			JOIN students s ON s.id = t.student_id
			JOIN classes c ON c.id = t.class_id
			WHERE t.end_date IS NOT NULL
		""")
		return c.fetchall()


def count_attendance_for_term(term_id):
    """تعداد جلسات مصرف‌شدهٔ ترم (حاضر + غایب). جلسهٔ لغوشده شمرده نمی‌شود."""
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT COUNT(*) FROM attendance
            WHERE term_id = ? AND status != 'canceled'
        """, (term_id,))
        return c.fetchone()[0]