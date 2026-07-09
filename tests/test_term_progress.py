"""Tests for the deep Term module (acasmart.data.repos.terms_repo).

Tier 1 — pure `_evaluate_completion` and the `TermProgress` value object: no DB, no Qt.
Tier 2 — `term_progress` / `refresh_completion` / `consumed_by_terms` against a throwaway
         SQLite DB, including the session-limit cascade that this refactor fixed
         (student_terms → pricing_profiles → term_session_count setting).

Run with:  python -m unittest tests.test_term_progress
"""
import os
import sqlite3
import tempfile
import unittest

import acasmart.data.db as db
from acasmart.data.repos.terms_repo import (
    TermProgress,
    _evaluate_completion,
    consumed,
    consumed_by_terms,
    refresh_completion,
    remaining,
    term_progress,
)


# --------------------------------------------------------------------------- #
# Tier 1 — pure logic, no database
# --------------------------------------------------------------------------- #
class TestEvaluateCompletion(unittest.TestCase):
    """The drift-prone rule that used to live (differently) in six places."""

    def test_at_limit_is_complete_and_closes_on_last_date(self):
        self.assertEqual(_evaluate_completion(12, 12, "1403-05-01", None),
                         (True, "1403-05-01"))

    def test_over_limit_stays_complete(self):
        self.assertEqual(_evaluate_completion(15, 12, "1403-06-01", "old"),
                         (True, "1403-06-01"))

    def test_one_under_is_not_complete(self):
        # the renewal-SMS neighbourhood (consumed == limit - 1) must NOT complete
        self.assertEqual(_evaluate_completion(11, 12, "1403-05-01", "old"),
                         (False, None))

    def test_zero_is_not_complete(self):
        self.assertEqual(_evaluate_completion(0, 12, None, None), (False, None))

    def test_complete_with_no_attendance_date_falls_back_to_current_end(self):
        # limit 0 (e.g. odd data) → already complete; keep the existing end_date
        self.assertEqual(_evaluate_completion(0, 0, None, "1403-01-01"),
                         (True, "1403-01-01"))

    def test_under_limit_signals_reopen(self):
        # (False, None) is the "should be re-opened" signal the mutation acts on
        is_complete, target_end = _evaluate_completion(3, 12, "1403-05-01", "old")
        self.assertFalse(is_complete)
        self.assertIsNone(target_end)


class TestTermProgressValueObject(unittest.TestCase):
    def test_remaining_and_is_complete_are_derived(self):
        p = TermProgress(term_id=1, consumed=11, limit=12, last_date="d", end_date=None)
        self.assertEqual(p.remaining, 1)
        self.assertFalse(p.is_complete)

    def test_full_term(self):
        p = TermProgress(term_id=1, consumed=12, limit=12, last_date="d", end_date="d")
        self.assertEqual(p.remaining, 0)
        self.assertTrue(p.is_complete)

    def test_over_full_term_clamps_remaining(self):
        p = TermProgress(term_id=1, consumed=15, limit=12, last_date="d", end_date="d")
        self.assertEqual(p.remaining, 0)
        self.assertTrue(p.is_complete)

    def test_is_frozen(self):
        p = TermProgress(term_id=1, consumed=1, limit=12, last_date=None, end_date=None)
        with self.assertRaises(Exception):
            p.consumed = 5  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# Tier 2 — against a throwaway SQLite DB
# --------------------------------------------------------------------------- #
_SCHEMA = """
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE pricing_profiles (id INTEGER PRIMARY KEY, sessions_limit INTEGER);
CREATE TABLE student_terms (
    id INTEGER PRIMARY KEY,
    student_id INTEGER, class_id INTEGER,
    start_date TEXT, end_date TEXT,
    sessions_limit INTEGER, profile_id INTEGER,
    updated_at TEXT
);
CREATE TABLE attendance (
    id INTEGER PRIMARY KEY,
    student_id INTEGER, class_id INTEGER, term_id INTEGER,
    date TEXT, is_present INTEGER, status TEXT
);
"""


class _TempDBTest(unittest.TestCase):
    """Points acasmart.data.db.DB_PATH at a throwaway file with a minimal schema."""

    def setUp(self):
        fd, self._path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self._orig_db_path = db.DB_PATH
        db.DB_PATH = self._path
        con = sqlite3.connect(self._path)
        con.executescript(_SCHEMA)
        con.execute("INSERT INTO settings(key, value) VALUES ('term_session_count', '12')")
        con.commit()
        con.close()

    def tearDown(self):
        db.DB_PATH = self._orig_db_path
        os.unlink(self._path)

    # -- helpers -----------------------------------------------------------
    def _add_term(self, term_id=1, sessions_limit=None, profile_id=None,
                  end_date=None, student_id=1, class_id=1, start_date="1403-01-01"):
        con = sqlite3.connect(self._path)
        con.execute(
            "INSERT INTO student_terms(id, student_id, class_id, start_date, end_date, "
            "sessions_limit, profile_id) VALUES (?,?,?,?,?,?,?)",
            (term_id, student_id, class_id, start_date, end_date, sessions_limit, profile_id),
        )
        con.commit()
        con.close()

    def _add_profile(self, profile_id, sessions_limit):
        con = sqlite3.connect(self._path)
        con.execute("INSERT INTO pricing_profiles(id, sessions_limit) VALUES (?,?)",
                    (profile_id, sessions_limit))
        con.commit()
        con.close()

    def _add_attendance(self, term_id, date, status, student_id=1, class_id=1):
        con = sqlite3.connect(self._path)
        con.execute(
            "INSERT INTO attendance(student_id, class_id, term_id, date, is_present, status) "
            "VALUES (?,?,?,?,?,?)",
            (student_id, class_id, term_id, date, 1 if status == "present" else 0, status),
        )
        con.commit()
        con.close()


class TestConsumedCounting(_TempDBTest):
    def test_consumed_excludes_canceled(self):
        self._add_term(term_id=1, sessions_limit=12)
        self._add_attendance(1, "1403-01-01", "present")
        self._add_attendance(1, "1403-01-08", "present")
        self._add_attendance(1, "1403-01-15", "absent")
        self._add_attendance(1, "1403-01-22", "canceled")  # must not count
        p = term_progress(1)
        self.assertEqual(p.consumed, 3)
        self.assertEqual(p.remaining, 9)
        self.assertFalse(p.is_complete)
        self.assertEqual(consumed(1), 3)
        self.assertEqual(remaining(1), 9)

    def test_missing_term_returns_none_and_zero(self):
        self.assertIsNone(term_progress(999))
        self.assertEqual(consumed(999), 0)
        self.assertEqual(remaining(999), 0)


class TestLimitCascade(_TempDBTest):
    """The bug this refactor fixed: completion and payments must agree on the limit."""

    def test_term_snapshot_wins(self):
        self._add_profile(5, sessions_limit=8)
        self._add_term(term_id=1, sessions_limit=5, profile_id=5)
        self.assertEqual(term_progress(1).limit, 5)

    def test_falls_back_to_profile_when_term_limit_null(self):
        # previously: refresh_term_completion ignored the profile and used the setting (12)
        self._add_profile(5, sessions_limit=8)
        self._add_term(term_id=1, sessions_limit=None, profile_id=5)
        self.assertEqual(term_progress(1).limit, 8)

    def test_falls_back_to_setting_when_no_term_or_profile_limit(self):
        self._add_term(term_id=1, sessions_limit=None, profile_id=None)
        self.assertEqual(term_progress(1).limit, 12)  # term_session_count setting


class TestRefreshCompletion(_TempDBTest):
    def test_closes_when_limit_reached_then_reopens_on_deletion(self):
        self._add_term(term_id=1, sessions_limit=2, end_date=None)
        self._add_attendance(1, "1403-01-01", "present")
        self._add_attendance(1, "1403-01-08", "present")

        self.assertTrue(refresh_completion(1))
        self.assertEqual(term_progress(1).end_date, "1403-01-08")  # last consumed date

        # remove one record → drops under the limit → two-way re-open
        con = sqlite3.connect(self._path)
        con.execute("DELETE FROM attendance WHERE date = '1403-01-08'")
        con.commit()
        con.close()

        self.assertFalse(refresh_completion(1))
        self.assertIsNone(term_progress(1).end_date)

    def test_does_not_close_below_limit(self):
        self._add_term(term_id=1, sessions_limit=3, end_date=None)
        self._add_attendance(1, "1403-01-01", "present")
        self.assertFalse(refresh_completion(1))
        self.assertIsNone(term_progress(1).end_date)


class TestConsumedByTerms(_TempDBTest):
    def test_bulk_counts_with_zero_for_empty_terms(self):
        self._add_term(term_id=1, sessions_limit=12)
        self._add_term(term_id=2, sessions_limit=12, student_id=2)
        self._add_term(term_id=3, sessions_limit=12, student_id=3)  # no attendance
        self._add_attendance(1, "1403-01-01", "present")
        self._add_attendance(1, "1403-01-08", "canceled")  # excluded
        self._add_attendance(2, "1403-01-01", "present", student_id=2)
        self._add_attendance(2, "1403-01-08", "absent", student_id=2)

        result = consumed_by_terms([1, 2, 3])
        self.assertEqual(result, {1: 1, 2: 2, 3: 0})

    def test_empty_input(self):
        self.assertEqual(consumed_by_terms([]), {})


if __name__ == "__main__":
    unittest.main()
