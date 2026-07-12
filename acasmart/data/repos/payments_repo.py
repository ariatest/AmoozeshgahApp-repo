import logging
from acasmart.data.db import get_connection

logger = logging.getLogger(__name__)


def get_remaining_tuition_debt(term_id, exclude_payment_id=None):
	"""باقی‌ماندهٔ بدهی شهریهٔ یک ترم.

	= شهریهٔ ثبت‌شدهٔ ترم (با fallback به تنظیمات) منهای مجموع پرداخت‌های شهریه.
	در حالت ویرایش، پرداختِ در حال ویرایش (exclude_payment_id) از مجموع کنار گذاشته می‌شود.
	خروجی None یعنی سقفی اعمال نمی‌شود (ترم نامشخص).
	"""
	if term_id is None:
		return None
	from acasmart.data.repos.terms_repo import term_config
	cfg = term_config(term_id)
	if cfg is None:
		from acasmart.data.repos.settings_repo import get_setting
		term_fee = int(get_setting("term_fee", get_setting("term_tuition", 6000000)))
	else:
		term_fee = cfg.tuition_fee
	with get_connection() as conn:
		c = conn.cursor()
		query = "SELECT COALESCE(SUM(amount), 0) FROM payments WHERE term_id = ? AND payment_type = 'tuition'"
		params = [term_id]
		if exclude_payment_id is not None:
			query += " AND id != ?"
			params.append(exclude_payment_id)
		c.execute(query, params)
		paid = c.fetchone()[0]
	return term_fee - paid


def insert_payment(student_id, class_id, term_id, amount, payment_date, payment_type='tuition', description=None):
	"""
	ثبت پرداخت با ترم و نوع پرداخت.
	"""
	if payment_type not in {"tuition", "extra"}:
		raise ValueError("invalid payment_type")
	if amount <= 0:
		raise ValueError("amount must be positive")
	# سقف بدهی شهریه: پرداخت شهریه نباید از مانده بیشتر باشد (دفاع لایه‌ای، مستقل از UI)
	if payment_type == "tuition" and term_id is not None:
		remaining = get_remaining_tuition_debt(term_id)
		if remaining is not None and amount > remaining:
			raise ValueError(f"tuition payment {amount} exceeds remaining debt {remaining}")
	with get_connection() as conn:
		conn.execute(
			"""
			INSERT INTO payments (student_id, class_id, term_id, amount, payment_date, payment_type, description)
			VALUES (?, ?, ?, ?, ?, ?, ?)
			""",
			(student_id, class_id, term_id, amount, payment_date, payment_type, description)
		)
		conn.commit()


def fetch_payments(student_id=None, class_id=None, date_from=None, date_to=None, term_id=None):
	"""
	دریافت لیست پرداخت‌ها با فیلترهای اختیاری.
	"""
	query = """
		SELECT payments.id, students.name, classes.name, 
			   payments.amount, payments.payment_date, payments.description, payments.payment_type,
			   classes.id AS class_id
		FROM payments
		JOIN students ON payments.student_id = students.id
		JOIN classes ON payments.class_id = classes.id
	"""
	conditions = []
	params = []

	if student_id:
		conditions.append("payments.student_id = ?")
		params.append(student_id)
	if class_id:
		conditions.append("payments.class_id = ?")
		params.append(class_id)
	if term_id:
		conditions.append("payments.term_id = ?")
		params.append(term_id)
	if date_from:
		conditions.append("payments.payment_date >= ?")
		params.append(date_from)
	if date_to:
		conditions.append("payments.payment_date <= ?")
		params.append(date_to)

	if conditions:
		query += " WHERE " + " AND ".join(conditions)

	query += " ORDER BY payments.payment_date DESC"

	with get_connection() as conn:
		c = conn.cursor()
		c.execute(query, tuple(params))
		return c.fetchall()


def get_payments_with_notes_by_terms(term_ids):
	"""{term_id: [(payment_date, payment_type, amount, description), ...]} — پرداخت‌های هر ترم.

	مصرفِ گزارشِ مالی: هم برای ستونِ توضیحات و هم برای فیلتر/جمعِ مبلغ بر اساسِ تاریخِ پرداخت
	(payment_date به‌صورتِ شمسیِ 'YYYY-MM-DD' ذخیره می‌شود). یک کوئریِ گروهی (بدون N+1)؛
	description تهی به رشتهٔ خالی نگاشته می‌شود؛ خروجی به ترتیبِ تاریخِ پرداخت است.
	"""
	ids = list(term_ids)
	if not ids:
		return {}
	placeholders = ",".join("?" * len(ids))
	with get_connection() as conn:
		c = conn.cursor()
		c.execute(f"""
			SELECT term_id, payment_date, payment_type, amount, COALESCE(description, '')
			FROM payments
			WHERE term_id IN ({placeholders})
			ORDER BY payment_date
		""", ids)
		result = {}
		for term_id, pdate, ptype, amount, desc in c.fetchall():
			result.setdefault(term_id, []).append((pdate, ptype, amount, desc))
	return result


def get_total_paid_for_term(term_id, payment_type='tuition'):
	"""
	جمع مبلغ پرداختی برای یک ترم مشخص (پیش‌فرض فقط شهریه).
	"""
	with get_connection() as conn:
		c = conn.cursor()
		c.execute(
			"""
			SELECT COALESCE(SUM(amount), 0)
			FROM payments
			WHERE term_id = ? AND payment_type = ?
			""",
			(term_id, payment_type)
		)
		return c.fetchone()[0]


def delete_payment(payment_id):
	"""
	Delete a payment record by its ID.
	"""
	with get_connection() as conn:
		conn.execute("DELETE FROM payments WHERE id = ?", (payment_id,))
		conn.commit()


def get_terms_for_payment_management(student_id, class_id):
	from acasmart.data.repos.terms_repo import tuition_by_terms
	with get_connection() as conn:
		c = conn.cursor()
		c.execute(
			"""
			SELECT
				t.id as term_id,
				t.start_date,
				t.end_date,
				t.created_at,
				COALESCE(SUM(CASE WHEN p.payment_type='tuition' THEN p.amount ELSE 0 END), 0) as paid_tuition,
				COALESCE(SUM(CASE WHEN p.payment_type='extra' THEN p.amount ELSE 0 END), 0) as paid_extra,
				COUNT(p.id) as payment_count
			FROM student_terms t
			LEFT JOIN payments p ON t.id = p.term_id
			WHERE t.student_id = ? AND t.class_id = ?
			GROUP BY t.id, t.start_date, t.end_date, t.created_at
			ORDER BY t.start_date DESC
			""",
			(student_id, class_id)
		)
		rows = c.fetchall()

	# شهریهٔ هر ترم با آبشارِ واحد (snapshot → profile → تنظیم) — بدون N+1
	fee_map = tuition_by_terms([r[0] for r in rows])
	result = []
	for (term_id, start_date, end_date, created_at, paid_tuition, paid_extra, payment_count) in rows:
		term_fee = fee_map.get(term_id)
		debt = term_fee - paid_tuition
		status = "تسویه" if debt == 0 else "بدهکار" if debt > 0 else "خطا"
		term_status = "فعال" if end_date is None else "تکمیل شده"
		result.append({
			"term_id": term_id,
			"start_date": start_date,
			"end_date": end_date,
			"created_at": created_at,
			"paid_tuition": paid_tuition,
			"paid_extra": paid_extra,
			"total_paid": paid_tuition + paid_extra,
			"debt": debt,
			"status": status,
			"term_status": term_status,
			"payment_count": payment_count
		})
	return result


def fetch_extra_payments_for_term(term_id):
	with get_connection() as conn:
		c = conn.cursor()
		c.execute(
			"""
			SELECT amount, payment_date, description
			FROM payments
			WHERE term_id = ? AND payment_type = 'extra'
			ORDER BY payment_date
			""",
			(term_id,)
		)
		return c.fetchall()


def get_payment_by_id(payment_id):
	"""
	دریافت جزئیات یک پرداخت بر اساس ID.
	خروجی: dict شامل id, student_id, class_id, term_id, amount, payment_date (شمسی "YYYY-MM-DD"),
	        payment_type ('tuition'/'extra'), description
	"""
	with get_connection() as conn:
		c = conn.cursor()
		c.execute(
			"""
			SELECT id, student_id, class_id, term_id, amount, payment_date, payment_type, description
			FROM payments
			WHERE id = ?
			""",
			(payment_id,)
		)
		row = c.fetchone()
		if not row:
			return None
		return {
			"id": row[0],
			"student_id": row[1],
			"class_id": row[2],
			"term_id": row[3],
			"amount": row[4],
			"payment_date": row[5],
			"payment_type": row[6],
			"description": row[7],
		}


def update_payment_by_id(payment_id, amount, date, payment_type, description):
	# Soft validations
	if payment_type not in {"tuition", "extra"}:
		raise ValueError("invalid payment_type")
	if amount <= 0:
		raise ValueError("amount must be positive")
	# سقف بدهی شهریه هنگام ویرایش (مانده با کنارگذاشتنِ خودِ همین پرداخت محاسبه می‌شود)
	if payment_type == "tuition":
		with get_connection() as conn:
			row = conn.execute("SELECT term_id FROM payments WHERE id = ?", (payment_id,)).fetchone()
		term_id = row[0] if row else None
		if term_id is not None:
			remaining = get_remaining_tuition_debt(term_id, exclude_payment_id=payment_id)
			if remaining is not None and amount > remaining:
				raise ValueError(f"tuition payment {amount} exceeds remaining debt {remaining}")
	with get_connection() as conn:
		conn.execute(
			"""
			UPDATE payments
			SET amount = ?, payment_date = ?, payment_type = ?, description = ?, updated_at = datetime('now','localtime')
			WHERE id = ?
			""",
			(amount, date, payment_type, description, payment_id),
		)
		conn.commit()


def delete_term_if_no_history(student_id, class_id, term_id):
	"""حذف ترم و جلسات آن، فقط در صورتی که هیچ سابقه‌ای نداشته باشد.

	سابقه = هرگونه پرداخت (شهریه/مازاد) یا هرگونه رکورد حضور و غیاب.
	حذف فقط برای «اشتباهِ ثبتِ اولیه» مجاز است؛ ترمی که سابقه دارد ویرایش
	می‌شود، نه حذف. خروجی: True اگر حذف شد، False اگر به‌دلیل وجود سابقه حذف نشد.
	"""
	conn = get_connection()
	c = conn.cursor()
	c.execute(
		"""
		SELECT COUNT(*) FROM payments
		WHERE student_id = ? AND class_id = ? AND term_id = ?
		""",
		(student_id, class_id, term_id)
	)
	has_payments = c.fetchone()[0] > 0

	c.execute(
		"""
		SELECT COUNT(*) FROM attendance
		WHERE student_id = ? AND class_id = ? AND term_id = ?
		""",
		(student_id, class_id, term_id)
	)
	has_attendance = c.fetchone()[0] > 0

	if has_payments or has_attendance:
		conn.close()
		return False

	# Model-B: حذف ترم؛ حضور و غیاب از طریق FK (ON DELETE CASCADE) حذف می‌شود.
	c.execute(
		"""
		DELETE FROM student_terms WHERE student_id = ? AND class_id = ? AND id = ?
		""",
		(student_id, class_id, term_id)
	)

	conn.commit()
	conn.close()
	return True
