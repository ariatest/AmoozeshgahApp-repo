from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

from acasmart.data.db import get_connection

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TermProgress:
	"""پیشرفتِ یک ترم: چند جلسه مصرف شده و آیا تکمیل شده است.

	`consumed` = حاضر + غایب (جلسهٔ لغوشده شمرده نمی‌شود).
	`limit` با آبشارِ واحد حل می‌شود: student_terms → pricing_profiles → تنظیمِ term_session_count.
	`remaining` و `is_complete` مشتق‌اند تا هرگز با consumed/limit ناسازگار نشوند.
	"""
	term_id: int
	consumed: int
	limit: int
	last_date: str | None
	end_date: str | None

	@property
	def remaining(self) -> int:
		return max(0, self.limit - self.consumed)

	@property
	def is_complete(self) -> bool:
		return self.consumed >= self.limit


@dataclass(frozen=True)
class TermConfig:
	"""پیکربندیِ قیمت‌گذاریِ یک ترم: سقفِ جلسات، شهریه، واحدِ پول.

	هر سه با آبشارِ واحد حل می‌شوند: snapshotِ ترم → pricing_profile → تنظیمِ پیش‌فرض.
	جدا از TermProgress نگه داشته می‌شود (پیشرفت در برابرِ قیمت‌گذاری).
	"""
	term_id: int
	sessions_limit: int
	tuition_fee: int
	currency_unit: str


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


def _resolve_term_pricing(c, term_id):
	"""قیمت‌گذاریِ ترم را با آبشارِ واحد حل می‌کند: student_terms → pricing_profiles → تنظیمِ پیش‌فرض.

	تنها محلِ حلِ (سقفِ جلسات، شهریه، واحدِ پول)؛ پیش‌تر هرکدام در چند repo جدا و ناسازگار
	حل می‌شدند. خروجی: (sessions_limit, tuition_fee, currency_unit). `c` یک cursor باز است.
	"""
	from acasmart.data.repos.settings_repo import get_setting  # local to avoid cycles
	c.execute("""
		SELECT COALESCE(st.sessions_limit, pp.sessions_limit),
		       COALESCE(st.tuition_fee,    pp.tuition_fee),
		       COALESCE(st.currency_unit,  pp.currency_unit)
		FROM student_terms st
		LEFT JOIN pricing_profiles pp ON pp.id = st.profile_id
		WHERE st.id = ?
	""", (term_id,))
	row = c.fetchone()
	limit, fee, unit = row if row else (None, None, None)
	if limit is None:
		limit = int(get_setting("term_session_count", 12))
	if fee is None:
		fee = int(get_setting("term_fee", get_setting("term_tuition", 6000000)))
	if not unit:
		unit = get_setting("currency_unit", "toman")
	return int(limit), int(fee), unit


def _resolve_session_limit(c, term_id):
	"""سقفِ جلساتِ ترم — واگذار به آبشارِ واحدِ _resolve_term_pricing."""
	return _resolve_term_pricing(c, term_id)[0]


def term_progress(term_id):
	"""پیشرفتِ ترم را یک‌جا برمی‌گرداند (TermProgress) یا None اگر ترم نبود.

	تنها منبعِ حقیقت برای «چند جلسه مصرف شده و آیا ترم تکمیل است». مصرف = حاضر+غایب (بی‌لغو).
	"""
	with get_connection() as conn:
		c = conn.cursor()
		c.execute("SELECT end_date FROM student_terms WHERE id = ?", (term_id,))
		row = c.fetchone()
		if not row:
			return None
		end_date = row[0]
		limit = _resolve_session_limit(c, term_id)
		c.execute("""
			SELECT COUNT(*), MAX(date) FROM attendance
			WHERE term_id = ? AND status != 'canceled'
		""", (term_id,))
		crow = c.fetchone()
		return TermProgress(
			term_id=term_id,
			consumed=crow[0] or 0,
			limit=limit,
			last_date=crow[1],
			end_date=end_date,
		)


def term_config(term_id):
	"""پیکربندیِ قیمت‌گذاریِ ترم (TermConfig) یا None اگر ترم نبود.

	تنها منبعِ حقیقت برای «شهریه/سقف/واحدِ پولِ این ترم چیست». همان آبشارِ term_progress برای سقف.
	"""
	with get_connection() as conn:
		c = conn.cursor()
		c.execute("SELECT 1 FROM student_terms WHERE id = ?", (term_id,))
		if c.fetchone() is None:
			return None
		limit, fee, unit = _resolve_term_pricing(c, term_id)
		return TermConfig(term_id=term_id, sessions_limit=limit, tuition_fee=fee, currency_unit=unit)


def consumed(term_id):
	"""جلساتِ مصرف‌شدهٔ ترم (حاضر + غایب). شکرِ رویِ term_progress."""
	p = term_progress(term_id)
	return p.consumed if p else 0


def remaining(term_id):
	"""جلساتِ باقی‌ماندهٔ ترم. شکرِ رویِ term_progress."""
	p = term_progress(term_id)
	return p.remaining if p else 0


def consumed_by_terms(term_ids):
	"""{term_id: مصرف‌شده} برای مجموعه‌ای از ترم‌ها — یک کوئریِ گروهی (برای گزارش‌ها).

	همان قاعدهٔ «status != 'canceled'» را در یک‌جا نگه می‌دارد، بدونِ N+1.
	"""
	ids = list(term_ids)
	if not ids:
		return {}
	placeholders = ",".join("?" * len(ids))
	with get_connection() as conn:
		c = conn.cursor()
		c.execute(f"""
			SELECT term_id, COUNT(*) FROM attendance
			WHERE term_id IN ({placeholders}) AND status != 'canceled'
			GROUP BY term_id
		""", ids)
		counts = {row[0]: row[1] for row in c.fetchall()}
	return {tid: counts.get(tid, 0) for tid in ids}


def tuition_by_terms(term_ids):
	"""{term_id: شهریه} برای مجموعه‌ای از ترم‌ها — با همان آبشارِ واحد (برای گزارش‌های مالی).

	یک کوئریِ گروهی (بدون N+1)؛ ترم‌هایی که snapshot و پروفایل هر دو تهی‌اند، از تنظیمِ پیش‌فرض پر می‌شوند.
	"""
	from acasmart.data.repos.settings_repo import get_setting  # local to avoid cycles
	ids = list(term_ids)
	if not ids:
		return {}
	placeholders = ",".join("?" * len(ids))
	default_fee = int(get_setting("term_fee", get_setting("term_tuition", 6000000)))
	with get_connection() as conn:
		c = conn.cursor()
		c.execute(f"""
			SELECT st.id, COALESCE(st.tuition_fee, pp.tuition_fee)
			FROM student_terms st
			LEFT JOIN pricing_profiles pp ON pp.id = st.profile_id
			WHERE st.id IN ({placeholders})
		""", ids)
		resolved = {row[0]: (int(row[1]) if row[1] is not None else default_fee) for row in c.fetchall()}
	return {tid: resolved.get(tid, default_fee) for tid in ids}


def _evaluate_completion(consumed_count, limit, last_date, current_end):
	"""تصمیمِ تکمیل — تابعِ خالص، بدونِ DB. قابلِ تستِ مستقل.

	خروجی: (is_complete, target_end). target_end همان end_date است که ترم «باید» داشته باشد،
	بدونِ درنظرگرفتنِ قاعدهٔ «یک ترمِ فعال»:
	  تکمیل   → last_date یا current_end
	  ناتکمیل → None (باید دوباره باز شود)
	"""
	if consumed_count >= limit:
		return True, (last_date or current_end)
	return False, None


def refresh_completion(term_id):
	"""وضعیتِ تکمیلِ ترم را از روی شمارشِ حضور (حاضر+غایب) بازمحاسبه و ذخیره می‌کند (ADR-0005).

	تکمیل یک «وضعیتِ مشتق‌شده» است، نه قفلِ یک‌طرفه:
	- اگر جلسات مصرف‌شده (به‌جزِ لغوشده) به سقفِ ترم برسد → end_date = آخرین تاریخِ مصرف‌شده.
	- در غیرِ این صورت → end_date = NULL (ترم دوباره فعال می‌شود و ویرایشِ گذشته ممکن می‌گردد).

	برای حفظِ قاعدهٔ «یک ترمِ فعال»، اگر بازکردنِ این ترم باعثِ وجودِ دو ترمِ فعال برای
	همان هنرجو/کلاس شود، end_date را NULL نمی‌کند و مارکر را نگه می‌دارد.
	خروجی: True اگر ترم اکنون تکمیل‌شده است.
	"""
	with get_connection() as conn:
		c = conn.cursor()
		c.execute("SELECT student_id, class_id, end_date FROM student_terms WHERE id = ?", (term_id,))
		row = c.fetchone()
		if not row:
			return False
		sid, cid, current_end = row[0], row[1], row[2]
		limit = _resolve_session_limit(c, term_id)
		c.execute("""
			SELECT COUNT(*), MAX(date) FROM attendance
			WHERE term_id = ? AND status != 'canceled'
		""", (term_id,))
		crow = c.fetchone()
		total = crow[0] or 0
		last_date = crow[1]

		is_complete, target_end = _evaluate_completion(total, limit, last_date, current_end)
		if is_complete:
			if current_end != target_end:
				c.execute("""
					UPDATE student_terms SET end_date = ?, updated_at = datetime('now','localtime')
					WHERE id = ?
				""", (target_end, term_id))
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


def get_term_dates(term_id):
	with get_connection() as conn:
		c = conn.cursor()
		c.execute("""
			SELECT start_date, end_date FROM student_terms
			WHERE id = ?
		""", (term_id,))
		return c.fetchone()


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
