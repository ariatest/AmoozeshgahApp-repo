"""Enrollment Schedule (Model-B): create, reschedule, and query student enrollments.

The `sessions` table was dropped (migration v6); a lesson is not a stored row — it is
computed from each enrollment's weekly schedule (ADR-0002). This module owns the whole
enrollment lifecycle over `student_terms`: enrolling a student (creating the Term),
rescheduling an active enrollment's time/duration, interval-aware teacher/student
conflict detection, and the computed attendance-page listing.

Seam: `terms_repo` owns *reads about an existing Term* (progress, config, completion);
this module owns *enroll/reschedule* and the schedule-conflict rules. `core.schedule` is
the pure occurrence engine underneath. (Renamed from the misnamed `sessions_repo`.)
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import Enum

from acasmart.data.db import get_connection


class EnrollmentStatus(Enum):
	CREATED = "created"                          # a new Term was created
	EXISTING = "existing"                        # idempotent: the matching active Term was returned
	UPDATED = "updated"                          # an active enrollment's schedule was changed
	TEACHER_CONFLICT = "teacher_conflict"        # slot overlaps the teacher's weekly schedule
	STUDENT_CONFLICT = "student_conflict"        # slot overlaps the student's own weekly schedule
	DUPLICATE_ACTIVE = "duplicate_active"        # a different active Term already exists here
	BEFORE_PREVIOUS_END = "before_previous_end"  # start precedes the last completed Term's end
	NOT_FOUND = "not_found"                      # reschedule target Term does not exist


@dataclass(frozen=True)
class EnrollmentResult:
	"""Outcome of enroll()/reschedule(): a status plus the term_id on success."""
	status: EnrollmentStatus
	term_id: int | None = None

	@property
	def ok(self) -> bool:
		return self.term_id is not None and self.status in (
			EnrollmentStatus.CREATED, EnrollmentStatus.EXISTING, EnrollmentStatus.UPDATED,
		)


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


def enroll(student_id, class_id, start_date, start_time,
           sessions_limit=None, tuition_fee=None, currency_unit=None,
           profile_id=None, lesson_duration=None):
	"""Model-B enrollment: create the student's Term for this class (no session row).

	Weekly lessons are computed from the Term's schedule. Enforces interval-aware
	teacher/student schedule conflicts, the one-active-term rule, and no-start-before-
	the-previous-term's-end. Returns an EnrollmentResult carrying the term_id on success
	(CREATED, or EXISTING when the same active Term is re-submitted) and a precise reason
	on failure.
	"""
	from acasmart.data.repos.settings_repo import get_setting  # local to avoid cycles
	eff_duration = int(lesson_duration) if lesson_duration else 30
	with get_connection() as conn:
		c = conn.cursor()

		# اگر ترم فعالِ دقیقا با همین start_date/start_time هست، همان را برگردان (idempotent)
		c.execute("""
			SELECT id FROM student_terms
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
			return EnrollmentResult(EnrollmentStatus.EXISTING, term_id)

		# Model-B: تداخلِ برنامهٔ هفتگی، محاسبه‌شده از ترم‌ها (نه جلسات) — استاد و سپس هنرجو
		if _has_teacher_schedule_conflict(class_id, start_time, new_duration=eff_duration):
			return EnrollmentResult(EnrollmentStatus.TEACHER_CONFLICT)
		if _has_student_schedule_conflict(student_id, class_id, start_time, new_duration=eff_duration):
			return EnrollmentResult(EnrollmentStatus.STUDENT_CONFLICT)

		# عدم شروع قبل از پایان ترم قبلی
		c.execute("""
			SELECT end_date FROM student_terms
			WHERE student_id=? AND class_id=? AND end_date IS NOT NULL
			ORDER BY end_date DESC LIMIT 1
		""", (student_id, class_id))
		last = c.fetchone()
		if last and start_date < last[0]:
			return EnrollmentResult(EnrollmentStatus.BEFORE_PREVIOUS_END)

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
			return EnrollmentResult(EnrollmentStatus.CREATED, c.lastrowid)
		except sqlite3.IntegrityError:
			# نقضِ ایندکسِ «یک ترمِ فعال»: این هنرجو از قبل ترمِ فعال در این کلاس دارد
			return EnrollmentResult(EnrollmentStatus.DUPLICATE_ACTIVE)


def reschedule(term_id, new_start_time, new_duration=None, new_start_date=None):
	"""Model-B: change an active enrollment's weekly time (and optionally lesson duration / start_date).

	The time-of-day changes and — when new_start_date is given — the term's start_date too.
	new_start_date must already be snapped onto the class weekday by the caller (same convention
	as enroll), so the computed weekly occurrences keep landing on the class day. The weekday
	itself never changes. Re-runs interval-aware teacher/student conflict detection, excluding
	this Term itself. Returns an EnrollmentResult (UPDATED, or a precise
	TEACHER_CONFLICT / STUDENT_CONFLICT / NOT_FOUND).
	"""
	with get_connection() as conn:
		c = conn.cursor()
		row = c.execute(
			"SELECT student_id, class_id, COALESCE(lesson_duration, 30) FROM student_terms WHERE id=?",
			(term_id,),
		).fetchone()
		if not row:
			return EnrollmentResult(EnrollmentStatus.NOT_FOUND)
		student_id, class_id, cur_dur = row
		eff_dur = int(new_duration) if new_duration else int(cur_dur or 30)

		if _has_teacher_schedule_conflict(class_id, new_start_time, new_duration=eff_dur, exclude_term_id=term_id):
			return EnrollmentResult(EnrollmentStatus.TEACHER_CONFLICT)
		if _has_student_schedule_conflict(student_id, class_id, new_start_time, new_duration=eff_dur, exclude_term_id=term_id):
			return EnrollmentResult(EnrollmentStatus.STUDENT_CONFLICT)

		if new_start_date is not None:
			c.execute(
				"""UPDATE student_terms
				      SET start_date = ?, start_time = ?, lesson_duration = ?, updated_at = datetime('now','localtime')
				    WHERE id = ?""",
				(new_start_date, new_start_time, eff_dur, term_id),
			)
		else:
			c.execute(
				"""UPDATE student_terms
				      SET start_time = ?, lesson_duration = ?, updated_at = datetime('now','localtime')
				    WHERE id = ?""",
				(new_start_time, eff_dur, term_id),
			)
		conn.commit()
		return EnrollmentResult(EnrollmentStatus.UPDATED, term_id)


def fetch_scheduled_students_for_class_on_date(class_id, selected_date, include_completed=False):
	"""Model-B: students whose weekly schedule lands a lesson in this class on selected_date.

	Computed from student_terms (no sessions table). A term's student appears when the date is
	a weekly occurrence (start_date + 7·n) and the term still has room, OR when an attendance
	record already exists for that date (so recorded/makeup dates stay editable). With
	include_completed=True, completed terms are included too (for editing past dates).
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


def _has_student_schedule_conflict(student_id, class_id, start_time, new_duration=30, exclude_term_id=None):
	"""Model-B: does the student already have an active term whose weekly slot overlaps this one?

	Same weekday (class.day) AND interval overlap on start_time/lesson_duration.
	exclude_term_id skips a term being edited. Internal to the enrollment module.
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


def _has_teacher_schedule_conflict(class_id, start_time, new_duration=30, exclude_term_id=None):
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
