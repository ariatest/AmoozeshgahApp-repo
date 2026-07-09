import logging
from acasmart.data.db import get_connection
from acasmart.data.repos.settings_repo import get_setting

logger = logging.getLogger(__name__)


def create_pricing_profile(name: str, sessions: int, fee: int, currency_unit: str = None, is_default: bool = False):
	if currency_unit is None:
		currency_unit = get_setting("currency_unit", "toman")
	with get_connection() as conn:
		c = conn.cursor()
		if is_default:
			c.execute("UPDATE pricing_profiles SET is_default = 0")
		c.execute("""
			INSERT INTO pricing_profiles(name, sessions_limit, tuition_fee, currency_unit, is_default)
			VALUES (?, ?, ?, ?, ?)
		""", (name, sessions, fee, currency_unit, 1 if is_default else 0))
		conn.commit()
		return c.lastrowid


def list_pricing_profiles():
	with get_connection() as conn:
		c = conn.cursor()
		c.execute("""
			SELECT id, name, sessions_limit, tuition_fee, currency_unit, is_default
			FROM pricing_profiles
			ORDER BY is_default DESC, name COLLATE NOCASE
		""")
		return c.fetchall()


def get_default_profile():
	with get_connection() as conn:
		c = conn.cursor()
		c.execute("""
			SELECT id, name, sessions_limit, tuition_fee, currency_unit
			FROM pricing_profiles
			WHERE is_default=1 LIMIT 1
		""")
		return c.fetchone()


def set_term_config(term_id: int, sessions_limit: int, tuition_fee: int, currency_unit: str = None, profile_id: int = None):
	if currency_unit is None:
		currency_unit = get_setting("currency_unit", "toman")
	with get_connection() as conn:
		c = conn.cursor()
		c.execute("""
			UPDATE student_terms
			   SET sessions_limit=?, tuition_fee=?, currency_unit=?, profile_id=?
			 WHERE id=?
		""", (sessions_limit, tuition_fee, currency_unit, profile_id, term_id))
		conn.commit()


def get_pricing_profile_by_id(profile_id: int):
	"""برگرداندن پروفایل بر اساس id (None اگر نبود)."""
	with get_connection() as conn:
		c = conn.cursor()
		c.execute("""
			SELECT id, name, sessions_limit, tuition_fee, currency_unit, is_default
			FROM pricing_profiles
			WHERE id = ?
		""", (profile_id,))
		row = c.fetchone()
		if not row:
			return None
		return {
			"id": row[0],
			"name": row[1],
			"sessions_limit": row[2],
			"tuition_fee": row[3],
			"currency_unit": row[4],
			"is_default": bool(row[5]),
		}


def apply_profile_to_term(term_id: int, profile_id: int):
	"""
	پروفایل شهریه را روی ترم اعمال می‌کند (sessions_limit/tuition_fee/currency_unit و profile_id).
	"""
	prof = get_pricing_profile_by_id(profile_id)
	if not prof:
		return False
	set_term_config(
		term_id,
		sessions_limit=prof["sessions_limit"],
		tuition_fee=prof["tuition_fee"],
		currency_unit=prof["currency_unit"],
		profile_id=prof["id"],
	)
	return True


def get_term_config_full(term_id: int):
	"""
	کانفیگ کامل ترم + اطلاعات پروفایل (اگر داشته باشد).
	"""
	with get_connection() as conn:
		c = conn.cursor()
		c.execute("""
			SELECT st.sessions_limit, st.tuition_fee, st.currency_unit, st.profile_id,
				   pp.name
			FROM student_terms st
			LEFT JOIN pricing_profiles pp ON pp.id = st.profile_id
			WHERE st.id = ?
		""", (term_id,))
		row = c.fetchone()
		if not row:
			return None
		sl, fee, unit, pid, pname = row
		if sl is None:
			sl = int(get_setting("term_session_count", 12))
		if fee is None:
			fee = int(get_setting("term_fee", get_setting("term_tuition", 6000000)))
		if not unit:
			unit = get_setting("currency_unit", "toman")
		return {
			"sessions_limit": sl,
			"tuition_fee": fee,
			"currency_unit": unit,
			"profile_id": pid,
			"profile_name": pname,
		}


def set_default_pricing_profile(profile_id: int):
	"""تغییر پروفایل پیش‌فرض (اختیاری اما مفید برای UI تنظیمات)."""
	with get_connection() as conn:
		c = conn.cursor()
		c.execute("UPDATE pricing_profiles SET is_default = 0")
		c.execute("UPDATE pricing_profiles SET is_default = 1 WHERE id = ?", (profile_id,))
		conn.commit()


def clear_term_profile(term_id: int):
	"""حذف نسبتِ پروفایل از ترم (ترم سفارشی می‌شود)."""
	with get_connection() as conn:
		c = conn.cursor()
		c.execute("""
			UPDATE student_terms
			   SET profile_id = NULL, updated_at = datetime('now','localtime')
			 WHERE id = ?
		""", (term_id,))
		conn.commit()
