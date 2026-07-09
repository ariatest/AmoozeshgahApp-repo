import logging
from acasmart.data.db import get_connection
from acasmart.data.migrations import (
	migrate_attendance_unique_constraint,
)

logger = logging.getLogger(__name__)


def create_tables():
	"""Create all tables with FKs, UNIQUE constraints, indexes, and audit columns."""
	with get_connection() as conn:
		c = conn.cursor()

		# Users table
		c.execute('''
			CREATE TABLE IF NOT EXISTS users (
			  id INTEGER PRIMARY KEY AUTOINCREMENT,
			  mobile TEXT UNIQUE NOT NULL,
			  password TEXT NOT NULL
			);
		''')
		# Teachers table
		c.execute("""
			CREATE TABLE IF NOT EXISTS teachers (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				name TEXT NOT NULL,
				national_code TEXT UNIQUE NOT NULL,
				teaching_card_number TEXT,
				gender TEXT,
				phone TEXT,
				birth_date TEXT,
				card_number TEXT,
				iban TEXT,
				created_at TEXT DEFAULT (datetime('now','localtime')),
				updated_at TEXT DEFAULT (datetime('now','localtime'))
			);
		""")
		# teachers instruments table
		c.execute("""CREATE TABLE IF NOT EXISTS teacher_instruments (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				teacher_id INTEGER NOT NULL,
				instrument TEXT NOT NULL,
				FOREIGN KEY (teacher_id) REFERENCES teachers(id) ON DELETE CASCADE,
				UNIQUE(teacher_id, instrument)
				);  
		""")
		# Students table
		c.execute("""CREATE TABLE IF NOT EXISTS students (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				name TEXT NOT NULL,
				birth_date TEXT NOT NULL,
				gender TEXT NOT NULL,
				national_code TEXT UNIQUE NOT NULL,
				phone TEXT,
				father_name TEXT,
				created_at TEXT DEFAULT (datetime('now','localtime')),
				updated_at TEXT DEFAULT (datetime('now','localtime'))
			);

		""")

		# Classes table
		c.execute("""
			CREATE TABLE IF NOT EXISTS classes (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				name TEXT NOT NULL,
				teacher_id INTEGER NOT NULL,
				day TEXT NOT NULL,
				start_time TEXT NOT NULL,
				end_time TEXT NOT NULL,
				room TEXT,
				instrument TEXT,
				created_at TEXT DEFAULT (datetime('now','localtime')),
				updated_at TEXT DEFAULT (datetime('now','localtime')),
				FOREIGN KEY(teacher_id)
				  REFERENCES teachers(id)
				  ON DELETE CASCADE
				  ON UPDATE CASCADE,
				UNIQUE(teacher_id, day, start_time, end_time, room)
			);
		""")

		# Model-B (ADR-0002): the `sessions` table is intentionally not created here.
		# Lessons are computed from each term's weekly schedule; migration v6 drops any
		# legacy sessions table on existing databases.

		# student_terms table
		c.execute("""
			CREATE TABLE IF NOT EXISTS student_terms (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				student_id INTEGER NOT NULL,
				class_id INTEGER NOT NULL,
				start_date TEXT NOT NULL,
				end_date TEXT,
				created_at TEXT DEFAULT (datetime('now','localtime')),
				updated_at TEXT DEFAULT (datetime('now','localtime')),
				FOREIGN KEY(student_id)
					REFERENCES students(id)
					ON DELETE CASCADE
					ON UPDATE CASCADE,
				FOREIGN KEY(class_id)
					REFERENCES classes(id)
					ON DELETE CASCADE
					ON UPDATE CASCADE
			);
		""")
		# profiles table
		c.execute("""
			CREATE TABLE IF NOT EXISTS pricing_profiles (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				name TEXT UNIQUE NOT NULL,
				sessions_limit INTEGER NOT NULL,
				tuition_fee INTEGER NOT NULL,
				currency_unit TEXT DEFAULT 'toman',
				is_default INTEGER DEFAULT 0,
				created_at TEXT DEFAULT (datetime('now','localtime')),
				updated_at TEXT DEFAULT (datetime('now','localtime'))
			);
		""")

		c.execute("PRAGMA table_info(student_terms)")
		cols = [row[1] for row in c.fetchall()]
		if "sessions_limit" not in cols:
			c.execute("ALTER TABLE student_terms ADD COLUMN sessions_limit INTEGER")
		if "tuition_fee" not in cols:
			c.execute("ALTER TABLE student_terms ADD COLUMN tuition_fee INTEGER")
		if "currency_unit" not in cols:
			c.execute("ALTER TABLE student_terms ADD COLUMN currency_unit TEXT")
		if "profile_id" not in cols:
			c.execute("ALTER TABLE student_terms ADD COLUMN profile_id INTEGER REFERENCES pricing_profiles(id) ON DELETE SET NULL")

		# بک‌فیل مقادیر خالی
		from acasmart.data.repos.settings_repo import get_setting  # lazy import to avoid circular
		default_fee = int(get_setting("term_fee", get_setting("term_tuition", 6000000)))
		default_sessions = int(get_setting("term_session_count", 12))
		default_unit = get_setting("currency_unit", "toman")
		c.execute("""
			UPDATE student_terms
			SET sessions_limit = COALESCE(sessions_limit, ?),
				tuition_fee    = COALESCE(tuition_fee,    ?),
				currency_unit  = COALESCE(currency_unit,  ?)
		""", (default_sessions, default_fee, default_unit))

		# add start_time to student_terms (for distinguishing same-day sessions)
		c.execute("PRAGMA table_info(student_terms)")
		columns = [row[1] for row in c.fetchall()]
		if "start_time" not in columns:
			c.execute("ALTER TABLE student_terms ADD COLUMN start_time TEXT")
			logger.info("✅ ستون start_time به جدول student_terms اضافه شد.")

		# Payments table
		c.execute("""
			CREATE TABLE IF NOT EXISTS payments (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				student_id INTEGER NOT NULL,
				class_id INTEGER NOT NULL,
				term_id INTEGER,
				amount INTEGER NOT NULL,
				payment_date TEXT NOT NULL,
				payment_type TEXT DEFAULT 'tuition',  -- 'tuition' or 'extra'
				description TEXT,
				created_at TEXT DEFAULT (datetime('now','localtime')),
				updated_at TEXT DEFAULT (datetime('now','localtime')),
				FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE ON UPDATE CASCADE,
				FOREIGN KEY(class_id) REFERENCES classes(id) ON DELETE CASCADE ON UPDATE CASCADE,
				FOREIGN KEY(term_id) REFERENCES student_terms(id) ON DELETE CASCADE ON UPDATE CASCADE
			);
		""")

		# Settings table
		c.execute("""
			CREATE TABLE IF NOT EXISTS settings (
				key TEXT PRIMARY KEY,
				value TEXT NOT NULL
			);
		""")

		# Attendance table (ساخت اولیه یا بعد از مهاجرت)
		c.execute("""
			CREATE TABLE IF NOT EXISTS attendance (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			student_id INTEGER NOT NULL,
			class_id INTEGER NOT NULL,
			term_id INTEGER NOT NULL,
			date TEXT NOT NULL,
			is_present INTEGER NOT NULL DEFAULT 1,
			created_at TEXT DEFAULT (datetime('now','localtime')),
			updated_at TEXT DEFAULT (datetime('now','localtime')),
			FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE ON UPDATE CASCADE,
			FOREIGN KEY(class_id) REFERENCES classes(id) ON DELETE CASCADE ON UPDATE CASCADE,
			FOREIGN KEY(term_id) REFERENCES student_terms(id) ON DELETE CASCADE ON UPDATE CASCADE,
			UNIQUE(student_id, class_id, term_id, date)
		);
		""")
		# Table of registered terms for which the end-of-term message has already been displayed.
		c.execute("""
			CREATE TABLE IF NOT EXISTS notified_terms (
				term_id INTEGER PRIMARY KEY,
				student_id INTEGER NOT NULL,
				class_id INTEGER NOT NULL,
				FOREIGN KEY(term_id) REFERENCES student_terms(id) ON DELETE CASCADE,
				FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE,
				FOREIGN KEY(class_id) REFERENCES classes(id) ON DELETE CASCADE
			);
		""")
		# Table of recorded messages sent as reminders for term renewal 
		c.execute("""
			CREATE TABLE IF NOT EXISTS sms_notifications (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				student_id INTEGER NOT NULL,
				term_id INTEGER NOT NULL,
				sent_at TEXT DEFAULT (datetime('now','localtime')),
				FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE,
				FOREIGN KEY(term_id) REFERENCES student_terms(id) ON DELETE CASCADE,
				UNIQUE(student_id, term_id)
			);
		""")
		# Finished terms the user has cleared from the finished-terms view (for readability).
		# The Term row and its history stay in student_terms; this only hides it from the list.
		c.execute("""
			CREATE TABLE IF NOT EXISTS dismissed_finished_terms (
				term_id INTEGER PRIMARY KEY,
				dismissed_at TEXT DEFAULT (datetime('now','localtime')),
				FOREIGN KEY(term_id) REFERENCES student_terms(id) ON DELETE CASCADE
			);
		""")
		# بلافاصله بعد از ساخت جدول notified_terms
		c.execute("PRAGMA table_info(notified_terms)")
		columns = [row[1] for row in c.fetchall()]
		if "session_date" not in columns:
			c.execute("ALTER TABLE notified_terms ADD COLUMN session_date TEXT")
			print("✅ ستون session_date به جدول notified_terms اضافه شد.")

		if "session_time" not in columns:
			c.execute("ALTER TABLE notified_terms ADD COLUMN session_time TEXT")
			print("✅ ستون session_time به جدول notified_terms اضافه شد.")

		# Indexes for faster lookups
		# For linking the class with the instructor
		c.execute("CREATE INDEX IF NOT EXISTS idx_classes_teacher_id ON classes(teacher_id);")

		# If you search frequently, use the class day as a filter
		c.execute("CREATE INDEX IF NOT EXISTS idx_classes_day ON classes(day);")

		# If you want to sort the payments by student, class, or date
		c.execute("CREATE INDEX IF NOT EXISTS idx_payments_student_id ON payments(student_id);")
		c.execute("CREATE INDEX IF NOT EXISTS idx_payments_class_id ON payments(class_id);")
		c.execute("CREATE INDEX IF NOT EXISTS idx_payments_date ON payments(payment_date);")
		
		# create index for finance reports window and attendace 
		c.execute("CREATE INDEX IF NOT EXISTS idx_attendance_term_id ON attendance(term_id);")
		c.execute("CREATE INDEX IF NOT EXISTS idx_payments_term_id   ON payments(term_id);")
		c.execute("CREATE INDEX IF NOT EXISTS idx_terms_student_class ON student_terms(student_id, class_id);")
		# Composite indexes (idempotent)
		c.execute("CREATE INDEX IF NOT EXISTS idx_attendance_term_date     ON attendance(term_id, date);")
		c.execute("CREATE INDEX IF NOT EXISTS idx_payments_term_date       ON payments(term_id, payment_date);")
		# فقط وقتی دیتابیس تازه ساخته شده و جدول خالیه، مقادیر پیش‌فرض رو وارد کن
		c.execute("SELECT COUNT(*) FROM settings")
		if c.fetchone()[0] == 0:
			c.execute("INSERT INTO settings (key, value) VALUES (?, ?)", ("currency_unit", "toman"))
			c.execute("INSERT INTO settings (key, value) VALUES (?, ?)", ("sms_enabled", "فعال"))
			c.execute("INSERT INTO settings (key, value) VALUES (?, ?)", ("term_session_count", "12"))
			c.execute("INSERT INTO settings (key, value) VALUES (?, ?)", ("term_tuition", "6000000"))

		conn.commit()

	migrate_attendance_unique_constraint()  # اجرای مهاجرت بعد از ساخت جداول
