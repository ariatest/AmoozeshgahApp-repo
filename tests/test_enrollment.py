"""Tests for the Enrollment Schedule module (acasmart.data.repos.enrollment_repo).

Exercises enroll()/reschedule() and their precise EnrollmentResult reasons against a
temp DB that includes the one-active-term partial unique index (so DUPLICATE_ACTIVE is
real) and interval-aware teacher/student conflict detection.

Run with:  python -m unittest tests.test_enrollment
"""
import os
import sqlite3
import tempfile
import unittest

import acasmart.data.db as db
from acasmart.data.repos.enrollment_repo import enroll, reschedule, EnrollmentStatus


_SCHEMA = """
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE teachers (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE classes (id INTEGER PRIMARY KEY, name TEXT, teacher_id INTEGER, day TEXT);
CREATE TABLE students (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE student_terms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER, class_id INTEGER,
    start_date TEXT, start_time TEXT, end_date TEXT,
    sessions_limit INTEGER, tuition_fee INTEGER, currency_unit TEXT,
    profile_id INTEGER, lesson_duration INTEGER,
    updated_at TEXT
);
CREATE UNIQUE INDEX idx_one_active_term
    ON student_terms(student_id, class_id) WHERE end_date IS NULL;
"""

_DAY = "شنبه"


class _Base(unittest.TestCase):
    def setUp(self):
        fd, self._path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self._orig = db.DB_PATH
        db.DB_PATH = self._path
        con = sqlite3.connect(self._path)
        con.executescript(_SCHEMA)
        con.executemany("INSERT INTO settings(key,value) VALUES (?,?)",
                        [("term_session_count", "12"), ("term_fee", "500000"), ("currency_unit", "toman")])
        # two teachers, two classes on the SAME weekday (class1->T1, class2->T2), three students
        con.execute("INSERT INTO teachers(id,name) VALUES (1,'T1'),(2,'T2')")
        con.execute("INSERT INTO classes(id,name,teacher_id,day) VALUES (1,'Guitar',1,?),(2,'Piano',2,?)", (_DAY, _DAY))
        con.execute("INSERT INTO students(id,name) VALUES (1,'A'),(2,'B'),(3,'C')")
        con.commit()
        con.close()

    def tearDown(self):
        db.DB_PATH = self._orig
        os.unlink(self._path)

    def _insert_completed_term(self, student_id, class_id, start, end, start_time="10:00"):
        con = sqlite3.connect(self._path)
        con.execute(
            "INSERT INTO student_terms(student_id, class_id, start_date, start_time, end_date, "
            "sessions_limit, lesson_duration) VALUES (?,?,?,?,?,?,?)",
            (student_id, class_id, start, start_time, end, 12, 30),
        )
        con.commit()
        con.close()

    def _start_time(self, term_id):
        con = sqlite3.connect(self._path)
        row = con.execute("SELECT start_time FROM student_terms WHERE id=?", (term_id,)).fetchone()
        con.close()
        return row[0] if row else None


class TestEnroll(_Base):
    def test_created(self):
        r = enroll(1, 1, "1403-01-04", "10:00", lesson_duration=30)
        self.assertEqual(r.status, EnrollmentStatus.CREATED)
        self.assertTrue(r.ok)
        self.assertIsNotNone(r.term_id)

    def test_existing_is_idempotent(self):
        r1 = enroll(1, 1, "1403-01-04", "10:00", lesson_duration=30)
        r2 = enroll(1, 1, "1403-01-04", "10:00", lesson_duration=30)
        self.assertEqual(r2.status, EnrollmentStatus.EXISTING)
        self.assertEqual(r2.term_id, r1.term_id)

    def test_duplicate_active_different_time(self):
        # same student+class already active; a non-overlapping different time still trips the index
        enroll(1, 1, "1403-01-04", "10:00", lesson_duration=30)
        r = enroll(1, 1, "1403-01-04", "11:00", lesson_duration=30)
        self.assertEqual(r.status, EnrollmentStatus.DUPLICATE_ACTIVE)
        self.assertIsNone(r.term_id)

    def test_teacher_conflict(self):
        enroll(1, 1, "1403-01-04", "10:00", lesson_duration=30)          # student A, class1 (T1)
        r = enroll(2, 1, "1403-01-04", "10:00", lesson_duration=30)      # student B, same class/time
        self.assertEqual(r.status, EnrollmentStatus.TEACHER_CONFLICT)

    def test_student_conflict(self):
        enroll(1, 1, "1403-01-04", "10:00", lesson_duration=30)          # student A, class1 (T1)
        r = enroll(1, 2, "1403-01-04", "10:00", lesson_duration=30)      # student A, class2 (T2), same day/time
        self.assertEqual(r.status, EnrollmentStatus.STUDENT_CONFLICT)

    def test_before_previous_end(self):
        self._insert_completed_term(1, 1, start="1403-04-01", end="1403-05-01")
        r = enroll(1, 1, "1403-04-15", "10:00", lesson_duration=30)      # start precedes 1403-05-01
        self.assertEqual(r.status, EnrollmentStatus.BEFORE_PREVIOUS_END)


class TestReschedule(_Base):
    def test_updated_persists(self):
        r = enroll(1, 1, "1403-01-04", "10:00", lesson_duration=30)
        rr = reschedule(r.term_id, "12:00")
        self.assertEqual(rr.status, EnrollmentStatus.UPDATED)
        self.assertEqual(rr.term_id, r.term_id)
        self.assertEqual(self._start_time(r.term_id), "12:00")

    def test_not_found(self):
        self.assertEqual(reschedule(99999, "12:00").status, EnrollmentStatus.NOT_FOUND)

    def test_teacher_conflict(self):
        enroll(1, 1, "1403-01-04", "10:00", lesson_duration=30)          # student A, class1, 10:00
        r2 = enroll(2, 1, "1403-01-04", "11:00", lesson_duration=30)     # student B, class1, 11:00 (ok)
        rr = reschedule(r2.term_id, "10:00")                            # now overlaps A on same teacher
        self.assertEqual(rr.status, EnrollmentStatus.TEACHER_CONFLICT)

    def test_student_conflict(self):
        enroll(1, 1, "1403-01-04", "10:00", lesson_duration=30)          # student A, class1 (T1), 10:00
        r2 = enroll(1, 2, "1403-01-04", "12:00", lesson_duration=30)     # student A, class2 (T2), 12:00 (ok)
        rr = reschedule(r2.term_id, "10:00")                            # overlaps A's own class1 slot
        self.assertEqual(rr.status, EnrollmentStatus.STUDENT_CONFLICT)


if __name__ == "__main__":
    unittest.main()
