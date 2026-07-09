"""Tests for the Term pricing resolver (acasmart.data.repos.terms_repo).

Covers `term_config` / `TermConfig` and the bulk `tuition_by_terms`, including the
one canonical cascade shared with the session limit:
    student_terms snapshot -> pricing_profiles -> default setting

Self-contained: stands up a throwaway SQLite DB with the columns the resolver needs.
Run with:  python -m unittest tests.test_term_config
"""
import os
import sqlite3
import tempfile
import unittest

import acasmart.data.db as db
from acasmart.data.repos.terms_repo import TermConfig, term_config, tuition_by_terms


_SCHEMA = """
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE pricing_profiles (
    id INTEGER PRIMARY KEY,
    sessions_limit INTEGER,
    tuition_fee INTEGER,
    currency_unit TEXT
);
CREATE TABLE student_terms (
    id INTEGER PRIMARY KEY,
    student_id INTEGER, class_id INTEGER,
    start_date TEXT, end_date TEXT,
    sessions_limit INTEGER, tuition_fee INTEGER, currency_unit TEXT,
    profile_id INTEGER
);
"""

# Default settings used by the last cascade step.
_DEFAULT_LIMIT = 12
_DEFAULT_FEE = 750000
_DEFAULT_CURRENCY = "toman"


class _TempDBTest(unittest.TestCase):
    def setUp(self):
        fd, self._path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self._orig_db_path = db.DB_PATH
        db.DB_PATH = self._path
        con = sqlite3.connect(self._path)
        con.executescript(_SCHEMA)
        con.executemany(
            "INSERT INTO settings(key, value) VALUES (?, ?)",
            [
                ("term_session_count", str(_DEFAULT_LIMIT)),
                ("term_fee", str(_DEFAULT_FEE)),
                ("currency_unit", _DEFAULT_CURRENCY),
            ],
        )
        con.commit()
        con.close()

    def tearDown(self):
        db.DB_PATH = self._orig_db_path
        os.unlink(self._path)

    def _add_profile(self, profile_id, sessions_limit=None, tuition_fee=None, currency_unit=None):
        con = sqlite3.connect(self._path)
        con.execute(
            "INSERT INTO pricing_profiles(id, sessions_limit, tuition_fee, currency_unit) "
            "VALUES (?,?,?,?)",
            (profile_id, sessions_limit, tuition_fee, currency_unit),
        )
        con.commit()
        con.close()

    def _add_term(self, term_id=1, sessions_limit=None, tuition_fee=None, currency_unit=None,
                  profile_id=None, student_id=1, class_id=1):
        con = sqlite3.connect(self._path)
        con.execute(
            "INSERT INTO student_terms(id, student_id, class_id, start_date, end_date, "
            "sessions_limit, tuition_fee, currency_unit, profile_id) VALUES (?,?,?,?,?,?,?,?,?)",
            (term_id, student_id, class_id, "1403-01-01", None,
             sessions_limit, tuition_fee, currency_unit, profile_id),
        )
        con.commit()
        con.close()


class TestTermConfigValueObject(unittest.TestCase):
    def test_is_frozen(self):
        c = TermConfig(term_id=1, sessions_limit=12, tuition_fee=1, currency_unit="toman")
        with self.assertRaises(Exception):
            c.tuition_fee = 2  # type: ignore[misc]


class TestTermConfigResolution(_TempDBTest):
    def test_missing_term_returns_none(self):
        self.assertIsNone(term_config(999))

    def test_snapshot_wins_for_all_fields(self):
        self._add_profile(5, sessions_limit=8, tuition_fee=111, currency_unit="rial")
        self._add_term(term_id=1, sessions_limit=5, tuition_fee=999, currency_unit="toman", profile_id=5)
        cfg = term_config(1)
        self.assertEqual((cfg.sessions_limit, cfg.tuition_fee, cfg.currency_unit),
                         (5, 999, "toman"))

    def test_profile_fallback_when_snapshot_null(self):
        # the bug-shaped case: tuition/currency must consult the profile, like the limit does
        self._add_profile(5, sessions_limit=8, tuition_fee=333, currency_unit="rial")
        self._add_term(term_id=1, sessions_limit=None, tuition_fee=None, currency_unit=None, profile_id=5)
        cfg = term_config(1)
        self.assertEqual((cfg.sessions_limit, cfg.tuition_fee, cfg.currency_unit),
                         (8, 333, "rial"))

    def test_setting_fallback_when_no_snapshot_or_profile(self):
        self._add_term(term_id=1, sessions_limit=None, tuition_fee=None, currency_unit=None, profile_id=None)
        cfg = term_config(1)
        self.assertEqual(
            (cfg.sessions_limit, cfg.tuition_fee, cfg.currency_unit),
            (_DEFAULT_LIMIT, _DEFAULT_FEE, _DEFAULT_CURRENCY),
        )

    def test_mixed_snapshot_and_profile(self):
        # limit from snapshot, fee from profile, currency from setting
        self._add_profile(5, sessions_limit=None, tuition_fee=444, currency_unit=None)
        self._add_term(term_id=1, sessions_limit=6, tuition_fee=None, currency_unit=None, profile_id=5)
        cfg = term_config(1)
        self.assertEqual((cfg.sessions_limit, cfg.tuition_fee, cfg.currency_unit),
                         (6, 444, _DEFAULT_CURRENCY))


class TestTuitionByTerms(_TempDBTest):
    def test_bulk_resolves_with_same_cascade(self):
        self._add_profile(5, tuition_fee=333)
        self._add_term(term_id=1, tuition_fee=999)                       # snapshot
        self._add_term(term_id=2, tuition_fee=None, profile_id=5, student_id=2)  # profile
        self._add_term(term_id=3, tuition_fee=None, student_id=3)        # setting
        self.assertEqual(
            tuition_by_terms([1, 2, 3]),
            {1: 999, 2: 333, 3: _DEFAULT_FEE},
        )

    def test_unknown_term_id_gets_default(self):
        self._add_term(term_id=1, tuition_fee=500)
        self.assertEqual(tuition_by_terms([1, 42]), {1: 500, 42: _DEFAULT_FEE})

    def test_empty_input(self):
        self.assertEqual(tuition_by_terms([]), {})


if __name__ == "__main__":
    unittest.main()
