"""Tests for the attendance-recording use-case (acasmart.services.attendance_recording).

Drives the full flow — persist → recompute Term completion → maybe fire the Renewal
Reminder — against a temp DB with an injected FakeSender, so the end-to-end behaviour is
verified without a Qt window.

Run with:  python -m unittest tests.test_attendance_recording
"""
import os
import sqlite3
import tempfile
import unittest

import acasmart.data.db as db
from acasmart.services.sms_notifier import SmsStatus
from acasmart.services.renewal_reminder import RenewalOutcome
from acasmart.services.attendance_recording import record_attendance, AttendanceOutcome
from acasmart.data.repos.notifications_repo import has_renew_sms_been_sent
from acasmart.data.repos.terms_repo import term_progress


_SCHEMA = """
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE pricing_profiles (id INTEGER PRIMARY KEY, sessions_limit INTEGER, tuition_fee INTEGER, currency_unit TEXT);
CREATE TABLE teachers (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE classes (id INTEGER PRIMARY KEY, name TEXT, teacher_id INTEGER, day TEXT);
CREATE TABLE students (id INTEGER PRIMARY KEY, name TEXT, phone TEXT);
CREATE TABLE student_terms (
    id INTEGER PRIMARY KEY, student_id INTEGER, class_id INTEGER,
    start_date TEXT, start_time TEXT, end_date TEXT,
    sessions_limit INTEGER, tuition_fee INTEGER, currency_unit TEXT, profile_id INTEGER,
    lesson_duration INTEGER, updated_at TEXT
);
CREATE TABLE attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER, class_id INTEGER, term_id INTEGER,
    date TEXT, is_present INTEGER, status TEXT, cancel_reason TEXT,
    UNIQUE(student_id, class_id, term_id, date)
);
CREATE TABLE sms_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER, term_id INTEGER,
    UNIQUE(student_id, term_id)
);
"""


class FakeSender:
    def __init__(self, status=SmsStatus.SENT):
        self.status = status
        self.calls = []

    def send_renew_term_notification(self, name, phone, class_name):
        self.calls.append((name, phone, class_name))
        return {"status": self.status, "message": "x"}


class _Base(unittest.TestCase):
    TERM = 1
    SID = 1
    CID = 1

    def setUp(self):
        fd, self._path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self._orig = db.DB_PATH
        db.DB_PATH = self._path
        con = sqlite3.connect(self._path)
        con.executescript(_SCHEMA)
        con.execute("INSERT INTO settings(key,value) VALUES ('term_session_count','12')")
        con.execute("INSERT INTO teachers(id,name) VALUES (1,'T')")
        con.execute("INSERT INTO classes(id,name,teacher_id,day) VALUES (1,'Guitar',1,'شنبه')")
        con.execute("INSERT INTO students(id,name,phone) VALUES (1,'Sina','09120000000')")
        con.commit()
        con.close()

    def tearDown(self):
        db.DB_PATH = self._orig
        os.unlink(self._path)

    def _term(self, sessions_limit, consumed=0):
        con = sqlite3.connect(self._path)
        con.execute(
            "INSERT INTO student_terms(id, student_id, class_id, start_date, start_time, end_date, sessions_limit) "
            "VALUES (?,?,?,?,?,?,?)",
            (self.TERM, self.SID, self.CID, "1403-01-01", "10:00", None, sessions_limit),
        )
        for i in range(consumed):
            con.execute(
                "INSERT INTO attendance(student_id,class_id,term_id,date,is_present,status) VALUES (?,?,?,?,?,?)",
                (self.SID, self.CID, self.TERM, f"1403-01-{i + 1:02d}", 1, "present"),
            )
        con.commit()
        con.close()


class TestRecordAttendance(_Base):
    def test_returns_attendance_outcome(self):
        self._term(sessions_limit=12)
        r = record_attendance(self.TERM, self.SID, self.CID, "1403-01-01", "present", sender=FakeSender())
        self.assertIsInstance(r, AttendanceOutcome)

    def test_reminder_fires_at_one_remaining(self):
        # limit 3, already 1 consumed; recording the 2nd leaves exactly one remaining
        self._term(sessions_limit=3, consumed=1)
        fake = FakeSender(status=SmsStatus.SENT)
        r = record_attendance(self.TERM, self.SID, self.CID, "1403-01-08", "present", sender=fake)
        self.assertEqual(r.reminder, RenewalOutcome.SENT)
        self.assertFalse(r.completed)
        self.assertTrue(has_renew_sms_been_sent(self.SID, self.TERM))
        self.assertEqual(len(fake.calls), 1)

    def test_no_reminder_before_one_remaining(self):
        self._term(sessions_limit=3, consumed=0)  # after 1 -> remaining 2
        fake = FakeSender()
        r = record_attendance(self.TERM, self.SID, self.CID, "1403-01-01", "present", sender=fake)
        self.assertEqual(r.reminder, RenewalOutcome.NOT_DUE)
        self.assertEqual(fake.calls, [])
        self.assertFalse(has_renew_sms_been_sent(self.SID, self.TERM))

    def test_final_session_completes_term_without_reminder(self):
        # limit 2, already 1; recording the 2nd reaches the limit -> complete, remaining 0
        self._term(sessions_limit=2, consumed=1)
        fake = FakeSender()
        r = record_attendance(self.TERM, self.SID, self.CID, "1403-01-08", "present", sender=fake)
        self.assertTrue(r.completed)
        self.assertEqual(r.reminder, RenewalOutcome.NOT_DUE)  # remaining 0, not 1
        self.assertIsNotNone(term_progress(self.TERM).end_date)

    def test_canceled_does_not_consume_or_remind(self):
        self._term(sessions_limit=3, consumed=1)
        fake = FakeSender()
        r = record_attendance(self.TERM, self.SID, self.CID, "1403-02-01", "canceled",
                              cancel_reason="tعطیل", sender=fake)
        self.assertEqual(term_progress(self.TERM).consumed, 1)  # canceled not counted
        self.assertEqual(r.reminder, RenewalOutcome.NOT_DUE)
        self.assertEqual(fake.calls, [])


if __name__ == "__main__":
    unittest.main()
