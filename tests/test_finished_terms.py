"""Tests for the finished-terms notification/clear logic (acasmart.data.repos.notifications_repo).

Two independent states:
  notified  — announced once by the on-open auto-popup (notified_terms)
  dismissed — hidden from the "نمایش…" list by the user's Clear button (dismissed_finished_terms)

Run with:  python -m unittest tests.test_finished_terms
"""
import os
import sqlite3
import tempfile
import unittest

import acasmart.data.db as db
from acasmart.data.repos.notifications_repo import (
    get_unnotified_expired_terms,
    get_visible_finished_terms,
    mark_terms_as_notified,
    dismiss_finished_terms,
)


_SCHEMA = """
CREATE TABLE students(id INTEGER PRIMARY KEY, name TEXT, national_code TEXT);
CREATE TABLE teachers(id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE classes(id INTEGER PRIMARY KEY, name TEXT, day TEXT, teacher_id INTEGER);
CREATE TABLE student_terms(id INTEGER PRIMARY KEY, student_id INT, class_id INT, start_time TEXT, end_date TEXT);
CREATE TABLE notified_terms(term_id INTEGER PRIMARY KEY, student_id INT, class_id INT, session_date TEXT, session_time TEXT);
CREATE TABLE dismissed_finished_terms(term_id INTEGER PRIMARY KEY, dismissed_at TEXT);
"""


def _ids(rows):
    return {r[6] for r in rows}  # r[6] = term_id


class TestFinishedTerms(unittest.TestCase):
    def setUp(self):
        fd, self._path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self._orig = db.DB_PATH
        db.DB_PATH = self._path
        con = sqlite3.connect(self._path)
        con.executescript(_SCHEMA)
        con.execute("INSERT INTO teachers VALUES (1,'T')")
        con.execute("INSERT INTO classes VALUES (1,'Guitar','شنبه',1)")
        con.executemany("INSERT INTO students VALUES (?,?,?)",
                        [(1, "A", "111"), (2, "B", "222"), (3, "C", "333")])
        con.executemany(
            "INSERT INTO student_terms(id, student_id, class_id, start_time, end_date) VALUES (?,?,?,?,?)",
            [
                (1, 1, 1, "10:00", "1403-05-01"),  # finished
                (2, 2, 1, "11:00", "1403-05-03"),  # finished
                (3, 3, 1, "12:00", None),          # active — must never appear
            ],
        )
        con.commit()
        con.close()

    def tearDown(self):
        db.DB_PATH = self._orig
        os.unlink(self._path)

    def test_finished_only_excludes_active(self):
        self.assertEqual(_ids(get_visible_finished_terms()), {1, 2})
        self.assertEqual(_ids(get_unnotified_expired_terms()), {1, 2})

    def test_mark_notified_drops_from_unnotified_but_stays_visible(self):
        mark_terms_as_notified([(1, 1, 1, "1403-05-01", "10:00")])
        self.assertEqual(_ids(get_unnotified_expired_terms()), {2})   # announced -> not "new"
        self.assertEqual(_ids(get_visible_finished_terms()), {1, 2})  # still in the list

    def test_dismiss_hides_from_both(self):
        dismiss_finished_terms([1])
        self.assertEqual(_ids(get_visible_finished_terms()), {2})      # cleared from the list
        self.assertEqual(_ids(get_unnotified_expired_terms()), {2})    # and won't re-announce

    def test_dismiss_is_idempotent_and_empty_safe(self):
        dismiss_finished_terms([])          # no-op, no error
        dismiss_finished_terms([1])
        dismiss_finished_terms([1])         # INSERT OR IGNORE — no duplicate error
        self.assertEqual(_ids(get_visible_finished_terms()), {2})


if __name__ == "__main__":
    unittest.main()
