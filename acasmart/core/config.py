"""Single source of truth for the app's .env configuration.

Loads .env exactly once — path-aware, so it also works inside the PyInstaller bundle —
and exposes the handful of keys the app actually uses. Replaces the three scattered
``load_dotenv()`` calls (main, app_init, sms_notifier) and the ``os.getenv`` reads spread
across those modules.

Loading is lazy and idempotent: any accessor triggers ``load()`` on first use, so callers
never worry about ordering. ``main`` still calls ``load()`` explicitly at startup to keep
the load eager and in one obvious place.

Validation is intentionally left to the callers (unchanged): ``app_init`` raises if
ADMIN_PASSWORD is missing; the IPPanel keys stay optional (a missing key degrades SMS to a
FAILED result, it does not stop the app).
"""
import os

from dotenv import load_dotenv

from acasmart.paths import resource_path

_loaded = False


def load():
	"""Load .env once (path-aware). Idempotent — safe to call from anywhere, any number of times."""
	global _loaded
	if _loaded:
		return
	env_path = resource_path(".env")
	if env_path.exists():
		load_dotenv(env_path)
	else:
		load_dotenv()
	_loaded = True


def _get(key, default=None):
	load()
	return os.getenv(key, default)


def admin_mobile() -> str:
	return (_get("ADMIN_MOBILE") or "").strip()


def admin_password() -> str:
	return (_get("ADMIN_PASSWORD") or "").strip()


def ippanel_api_key():
	return _get("IPPANEL_API_KEY")


def ippanel_from_number():
	return _get("IPPANEL_FROM_NUMBER")


def ippanel_pattern_code_reminder():
	"""Pattern for the automatic 'one session left' renewal reminder (attendance flow)."""
	return _get("IPPANEL_PATTERN_CODE_1")


def ippanel_pattern_code_invitation():
	"""Pattern for the manual bulk 'register for a new term' SMS (send-SMS window)."""
	return _get("IPPANEL_PATTERN_CODE_2")
