import logging
from acasmart.data.db import get_connection

logger = logging.getLogger(__name__)

def get_class_and_teacher_name(class_id):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT c.name, t.name
            FROM classes c
            JOIN teachers t ON c.teacher_id = t.id
            WHERE c.id = ?
        """, (class_id,))
        return c.fetchone() or ("—", "—")
	
def get_all_student_terms_with_financials():
	from acasmart.data.repos.payments_repo import get_total_paid_for_term
	from acasmart.data.repos.terms_repo import tuition_by_terms
	with get_connection() as conn:
		c = conn.cursor()
		c.execute("""
			SELECT
				t.id as term_id,
				s.name as student_name,
				s.national_code,
				c.name as class_name,
				c.instrument,
				c.id as class_id,
				t.start_date,
				t.end_date,
				tr.name as teacher_name
			FROM student_terms t
			JOIN students s ON s.id = t.student_id
			JOIN classes c   ON c.id = t.class_id
			JOIN teachers tr ON c.teacher_id = tr.id
			ORDER BY t.start_date DESC
		""")
		terms = c.fetchall()

		# شهریهٔ هر ترم با آبشارِ واحد (snapshot → profile → تنظیم) — بدون N+1
		fee_map = tuition_by_terms([t[0] for t in terms])
		result = []
		for (term_id, student_name, national_code, class_name, instrument,
			 class_id, start_date, end_date, teacher_name) in terms:

			term_fee = fee_map.get(term_id)

			paid_tuition = get_total_paid_for_term(term_id, 'tuition')
			paid_extra   = get_total_paid_for_term(term_id, 'extra')
			debt = term_fee - paid_tuition
			status = "تسویه" if debt == 0 else "بدهکار" if debt > 0 else "خطا در داده‌ها"
			term_status = "فعال" if end_date is None else "تکمیل شده"

			# آخرین تاریخ پرداخت
			c.execute("SELECT MAX(payment_date) FROM payments WHERE term_id = ?", (term_id,))
			last_payment_date = c.fetchone()[0]

			result.append({
				"term_id": term_id,
				"student_name": student_name,
				"national_code": national_code,
				"class_name": class_name,
				"class_id": class_id,
				"instrument": instrument,
				"teacher_name": teacher_name,
				"start_date": start_date,
				"end_date": end_date,
				"tuition": term_fee,
				"paid_tuition": paid_tuition,
				"paid_extra": paid_extra,
				"total_paid": paid_tuition + paid_extra,
				"debt": debt,
				"status": status,
				"term_status": term_status,
				"last_payment_date": last_payment_date
			})
	return result


def get_attendance_report_rows():
	with get_connection() as conn:
		c = conn.cursor()

		# مرحله ۱: گرفتن لیست ترم‌ها همراه با اطلاعات مرتبط
		c.execute("""
			SELECT 
				t.id as term_id,
				s.name as student_name,
				t.start_date,
				t.end_date,
				cls.id as class_id,
				cls.name as class_name,
				cls.instrument,
				tr.name as teacher_name
			FROM student_terms t
			JOIN students s ON s.id = t.student_id
			JOIN classes cls ON cls.id = t.class_id
			JOIN teachers tr ON cls.teacher_id = tr.id
			ORDER BY t.start_date ASC
		""")
		terms = c.fetchall()

		result = []

		# مرحله ۲: گرفتن حضور و غیاب هر ترم
		for (term_id, student_name, start_date, end_date,
			 class_id, class_name, instrument, teacher_name) in terms:

			c.execute("""
				SELECT date, status
				FROM attendance
				WHERE term_id = ?
				ORDER BY date ASC
			""", (term_id,))
			attendance_rows = c.fetchall()

			_label = {"present": "حاضر", "absent": "غایب", "canceled": "لغو"}
			attendance_dict = {
				row[0]: _label.get(row[1], "غایب")
				for row in attendance_rows
			}

			result.append({
				"student_name": student_name,
				"teacher_name": teacher_name,
				"class_id": class_id,
				"class_name": class_name,
				"instrument": instrument,
				"start_date": start_date,
				"end_date": end_date,
				"attendance": attendance_dict
			})

		return result


def get_student_term_summary_rows(student_name='', teacher_name='', class_name='',class_id='',instrument_name='', day='', date_from='', date_to='',term_status=''):
	conn = get_connection()
	cursor = conn.cursor()

	query = """
		SELECT
			st.id AS term_id,
			s.id AS student_id,
			s.name AS student_name,
			s.national_code,
			c.id AS class_id,
			c.name AS class_name,
			t.name AS teacher_name,
			c.instrument,
			c.day,
			c.start_time,
			st.start_date,
			st.end_date
		FROM student_terms st
		JOIN students s ON s.id = st.student_id
		JOIN classes c ON c.id = st.class_id
		JOIN teachers t ON t.id = c.teacher_id
		WHERE 1=1
	"""

	params = []

	if student_name:
		query += " AND s.name LIKE ?"
		params.append(f"%{student_name}%")
	if teacher_name:
		query += " AND t.name LIKE ?"
		params.append(f"%{teacher_name}%")
	if class_id:
		query += " AND c.id = ?"
		params.append(class_id)
	elif class_name:
		query += " AND c.name LIKE ?"
		params.append(f"%{class_name}%")
	if instrument_name:
		query += " AND c.instrument LIKE ?"
		params.append(f"%{instrument_name}%")
	if day:
		query += " AND c.day = ?"
		params.append(day)
	if date_from:
		query += " AND st.start_date >= ?"
		params.append(date_from)
	if date_to:
		query += " AND st.start_date <= ?"
		params.append(date_to)
	if term_status == "active":
		query += " AND st.end_date IS NULL"
	elif term_status == "finished":
		query += " AND st.end_date IS NOT NULL"

	query += " ORDER BY st.start_date DESC"
	cursor.execute(query, params)
	terms = cursor.fetchall()

	# مصرف‌شده (حاضر+غایب) هر ترم — قاعده در terms_repo متمرکز است (بدون N+1)
	from acasmart.data.repos.terms_repo import consumed_by_terms
	term_ids = [t[0] for t in terms]
	consumed_map = consumed_by_terms(term_ids)

	# حاضرها (سنجهٔ جدا از مصرف‌شده) — یک کوئریِ گروهی
	present_map = {}
	if term_ids:
		ph = ",".join("?" * len(term_ids))
		cursor.execute(f"""
			SELECT term_id, COUNT(*) FROM attendance
			WHERE term_id IN ({ph}) AND status = 'present'
			GROUP BY term_id
		""", term_ids)
		present_map = {r[0]: r[1] for r in cursor.fetchall()}

	result = []
	for term in terms:
		(
			term_id, student_id, student_name, national_code,class_id,
			class_name, teacher_name, instrument, day, start_time,
			start_date, end_date
		) = term

		total_sessions = consumed_map.get(term_id, 0)   # مصرف‌شده = حاضر + غایب (بدون لغوشده)
		present_sessions = present_map.get(term_id, 0)
		absent_sessions = total_sessions - present_sessions

		result.append([
			student_name,
			national_code,
			class_name,
			class_id,
			teacher_name,
			instrument,
			day,
			start_time,
			start_date,
			end_date,
			total_sessions,
			present_sessions,
			absent_sessions,
			round((present_sessions / total_sessions) * 100, 1) if total_sessions else 0
		])

	conn.close()
	return result


def fetch_all_contacts():
	with get_connection() as conn:
		c = conn.cursor()
		# هنرجویان
		c.execute("""
			SELECT name, national_code, phone, 'هنرجو' as role
			FROM students
		""")
		students = c.fetchall()

		# اساتید
		c.execute("""
			SELECT name, national_code, phone, 'استاد' as role
			FROM teachers
		""")
		teachers = c.fetchall()

		# ترکیب دو لیست
		return students + teachers


def get_teacher_summary_rows():
	with get_connection() as conn:
		c = conn.cursor()
		c.execute("""
			SELECT 
				t.name,
				t.national_code,
				t.teaching_card_number,
				t.phone,
				t.birth_date,
				t.card_number,
				t.iban,
				COALESCE(instrs.instruments, '—') AS instruments,
				COALESCE(days.days, '—') AS class_days
			FROM teachers t
			LEFT JOIN (
				SELECT teacher_id, GROUP_CONCAT(instrument, '/') AS instruments
				FROM teacher_instruments
				GROUP BY teacher_id
			) instrs ON t.id = instrs.teacher_id
			LEFT JOIN (
				SELECT teacher_id, GROUP_CONCAT(DISTINCT day) AS days
				FROM classes
				GROUP BY teacher_id
			) days ON t.id = days.teacher_id
			ORDER BY t.name COLLATE NOCASE
		""")
		result = []
		for row in c.fetchall():
			row = list(row)
			row[7] = row[7].replace(",", "/") if row[7] and row[7] != "—" else "—"
			row[8] = row[8].replace(",", "/") if row[8] and row[8] != "—" else "—"
			result.append(row)
		return result
