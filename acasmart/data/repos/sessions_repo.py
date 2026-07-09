"""Enrollment & schedule queries (Model-B).

The `sessions` table was dropped (migration v6); lessons are computed from each term's
weekly schedule (ADR-0002). This module now holds enrollment creation, the computed
attendance-page listing, and schedule-based conflict detection — all over student_terms.
The module/filename is kept for import stability.
"""
from acasmart.data.db import get_connection


def fetch_enrollments_for_class(class_id, include_completed=False):
	"""Model-B: students enrolled in a class with their weekly schedule and progress.

	Returns rows: (term_id, student_id, student_name, start_date, start_time,
	lesson_duration, sessions_limit, held_count, end_date). held_count excludes canceled.
	By default only active enrollments (end_date IS NULL).
	"""
	with get_connection() as conn:
		c = conn.cursor()
		query = """
			SELECT st.id, st.student_id, s.name, st.start_date, st.start_time,
			       COALESCE(st.lesson_duration, 30), COALESCE(st.sessions_limit, 0),
			       (SELECT COUNT(*) FROM attendance a WHERE a.term_id = st.id AND a.status != 'canceled'),
			       st.end_date
			FROM student_terms st
			JOIN students s ON s.id = st.student_id
			WHERE st.class_id = ?
		"""
		params = [class_id]
		if not include_completed:
			query += " AND st.end_date IS NULL"
		query += " ORDER BY st.start_time, s.name COLLATE NOCASE"
		c.execute(query, params)
		return c.fetchall()


def enroll_student(class_id, student_id, start_date, start_time,
				   sessions_limit=None, tuition_fee=None,
				   currency_unit=None, profile_id=None, lesson_duration=None):
	"""Model-B enrollment: create (or return) the student's term for this class — no session row.

	The weekly lessons are computed from the term's schedule; there is nothing else to persist.
	Returns the term_id, or None if blocked (schedule conflict, or an active term already exists).
	"""
	from acasmart.data.repos.terms_repo import insert_student_term_if_not_exists
	return insert_student_term_if_not_exists(
		student_id, class_id, start_date, start_time,
		sessions_limit=sessions_limit, tuition_fee=tuition_fee,
		currency_unit=currency_unit, profile_id=profile_id, lesson_duration=lesson_duration,
	)


def fetch_scheduled_students_for_class_on_date(class_id, selected_date, include_completed=False):
	"""Model-B: students whose weekly schedule lands a lesson in this class on selected_date.

	Computed from student_terms (no sessions table). A term's student appears when the date is
	a weekly occurrence (start_date + 7·n) and the term still has room (held < limit), OR when an
	attendance record already exists for that date (so recorded/makeup dates stay editable).
	With include_completed=True, completed terms are included too (for editing past dates).
	Returns rows: (sid, name, teacher, start_time, term_id).
	"""
	from acasmart.core.schedule import is_weekly_occurrence
	from acasmart.data.repos.terms_repo import term_progress
	with get_connection() as conn:
		c = conn.cursor()
		c.execute("""
			SELECT st.id, st.student_id, s.name, t.name, st.start_time, st.start_date, st.end_date
			FROM student_terms st
			JOIN students s ON s.id = st.student_id
			JOIN classes c2 ON st.class_id = c2.id
			JOIN teachers t ON c2.teacher_id = t.id
			WHERE st.class_id = ? AND st.start_date <= ?
		""", (class_id, selected_date))
		rows = c.fetchall()

		result = []
		for term_id, sid, sname, tname, start_time, start_date, end_date in rows:
			if end_date is not None and not include_completed:
				continue
			# آیا برای این تاریخ رکوردی ثبت شده؟ (تا تاریخ‌های ثبت‌شده/جبرانی ویرایش‌پذیر بمانند)
			c.execute("SELECT 1 FROM attendance WHERE term_id = ? AND date = ? LIMIT 1", (term_id, selected_date))
			has_record = c.fetchone() is not None
			# آیا این تاریخ یک تکرارِ هفتگی است و ترم هنوز جا دارد؟ (سقف از قاعدهٔ واحدِ terms_repo)
			p = term_progress(term_id)
			is_occ = is_weekly_occurrence(start_date, selected_date) and p is not None and p.remaining > 0
			if has_record or is_occ:
				result.append((sid, sname, tname, start_time, term_id))

		result.sort(key=lambda r: (str(r[3]), str(r[1])))
		return result


def _time_to_minutes(t):
	"""تبدیل "HH:mm" (با ارقام فارسی یا انگلیسی) به دقیقه از نیمه‌شب؛ None اگر نامعتبر."""
	if t is None:
		return None
	t = str(t).strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
	try:
		hh, mm = t.split(":")
		return int(hh) * 60 + int(mm)
	except (ValueError, AttributeError):
		return None


def _intervals_overlap(start1, dur1, start2, dur2):
	"""آیا دو بازهٔ [start, start+dur) هم‌پوشانی دارند؟"""
	if start1 is None or start2 is None:
		return False
	return start1 < (start2 + dur2) and start2 < (start1 + dur1)


def has_student_schedule_conflict(student_id, class_id, start_time, new_duration=30, exclude_term_id=None):
	"""Model-B: does the student already have an active term whose weekly slot overlaps this one?

	Computed from student_terms (no sessions): same weekday (class.day) AND interval overlap on
	start_time/lesson_duration. exclude_term_id skips a term being edited.
	"""
	new_start = _time_to_minutes(start_time)
	if new_start is None:
		return False
	with get_connection() as conn:
		c = conn.cursor()
		row = c.execute("SELECT day FROM classes WHERE id = ?", (class_id,)).fetchone()
		if not row:
			return False
		class_day = row[0]
		query = """
			SELECT cl.day, st.start_time, COALESCE(st.lesson_duration, 30)
			FROM student_terms st JOIN classes cl ON cl.id = st.class_id
			WHERE st.student_id = ? AND st.end_date IS NULL
		"""
		params = [student_id]
		if exclude_term_id:
			query += " AND st.id != ?"
			params.append(exclude_term_id)
		c.execute(query, params)
		for day, stime, dur in c.fetchall():
			if day == class_day and _intervals_overlap(new_start, new_duration, _time_to_minutes(stime), int(dur or 30)):
				return True
	return False


def has_teacher_schedule_conflict(class_id, start_time, new_duration=30, exclude_term_id=None):
	"""Model-B: does the class's teacher already have an active term whose weekly slot overlaps this one?"""
	new_start = _time_to_minutes(start_time)
	if new_start is None:
		return False
	with get_connection() as conn:
		c = conn.cursor()
		row = c.execute("SELECT teacher_id, day FROM classes WHERE id = ?", (class_id,)).fetchone()
		if not row:
			return False
		teacher_id, class_day = row
		query = """
			SELECT cl.day, st.start_time, COALESCE(st.lesson_duration, 30)
			FROM student_terms st JOIN classes cl ON cl.id = st.class_id
			WHERE cl.teacher_id = ? AND st.end_date IS NULL
		"""
		params = [teacher_id]
		if exclude_term_id:
			query += " AND st.id != ?"
			params.append(exclude_term_id)
		c.execute(query, params)
		for day, stime, dur in c.fetchall():
			if day == class_day and _intervals_overlap(new_start, new_duration, _time_to_minutes(stime), int(dur or 30)):
				return True
	return False
