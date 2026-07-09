"""Tests for the Renewal Reminder policy (acasmart.services.renewal_reminder).

The SMS transport is injected as a FakeSender, so these exercise the whole policy —
trigger (exactly one remaining), the not-already-sent guard, and the "record only on
SENT / stay resendable on DISABLED|FAILED|NO_PHONE" rule — without any network.

Run with:  python -m unittest tests.test_renewal_reminder
"""
import os
import sqlite3
import tempfile
import unittest

import acasmart.data.db as db
from acasmart.services.sms_notifier import SmsStatus
from acasmart.services.renewal_reminder import RenewalOutcome, maybe_send, force_resend, already_sent
from acasmart.data.repos.notifications_repo import has_renew_sms_been_sent


_SCHEMA = """
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE pricing_profiles (id INTEGER PRIMARY KEY, sessions_limit INTEGER, tuition_fee INTEGER, currency_unit TEXT);
CREATE TABLE teachers (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE classes (id INTEGER PRIMARY KEY, name TEXT, teacher_id INTEGER);
CREATE TABLE students (id INTEGER PRIMARY KEY, name TEXT, phone TEXT);
CREATE TABLE student_terms (
    id INTEGER PRIMARY KEY, student_id INTEGER, class_id INTEGER,
    start_date TEXT, end_date TEXT,
    sessions_limit INTEGER, tuition_fee INTEGER, currency_unit TEXT, profile_id INTEGER
);
CREATE TABLE attendance (
    id INTEGER PRIMARY KEY, student_id INTEGER, class_id INTEGER, term_id INTEGER,
    date TEXT, is_present INTEGER, status TEXT
);
CREATE TABLE sms_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER, term_id INTEGER,
    UNIQUE(student_id, term_id)
);
"""


class FakeSender:
    """Duck-typed SMS transport: records calls, returns a canned status (or raises)."""

    def __init__(self, status=SmsStatus.SENT, raise_exc=False):
        self.status = status
        self.raise_exc = raise_exc
        self.calls = []

    def send_renew_term_notification(self, name, phone, class_name):
        self.calls.append((name, phone, class_name))
        if self.raise_exc:
            raise RuntimeError("network down")
        return {"status": self.status, "message": "x"}


class _RenewalTest(unittest.TestCase):
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
        con.execute("INSERT INTO settings(key, value) VALUES ('term_session_count','12')")
        con.execute("INSERT INTO teachers(id, name) VALUES (1, 'Teacher')")
        con.execute("INSERT INTO classes(id, name, teacher_id) VALUES (1, 'Guitar', 1)")
        con.commit()
        con.close()

    def tearDown(self):
        db.DB_PATH = self._orig
        os.unlink(self._path)

    # -- helpers -----------------------------------------------------------
    def _setup_term(self, sessions_limit=3, consumed=0, phone="09120000000"):
        con = sqlite3.connect(self._path)
        con.execute("INSERT INTO students(id, name, phone) VALUES (?,?,?)", (self.SID, "Sina", phone))
        con.execute(
            "INSERT INTO student_terms(id, student_id, class_id, start_date, end_date, sessions_limit) "
            "VALUES (?,?,?,?,?,?)",
            (self.TERM, self.SID, self.CID, "1403-01-01", None, sessions_limit),
        )
        for i in range(consumed):
            con.execute(
                "INSERT INTO attendance(student_id, class_id, term_id, date, is_present, status) "
                "VALUES (?,?,?,?,?,?)",
                (self.SID, self.CID, self.TERM, f"1403-01-{i + 1:02d}", 1, "present"),
            )
        con.commit()
        con.close()

    def _mark_sent(self):
        con = sqlite3.connect(self._path)
        con.execute("INSERT INTO sms_notifications(student_id, term_id) VALUES (?,?)", (self.SID, self.TERM))
        con.commit()
        con.close()

    def _due_term(self, phone="09120000000"):
        # limit 3, consumed 2 -> remaining 1 -> due
        self._setup_term(sessions_limit=3, consumed=2, phone=phone)


class TestMaybeSend(_RenewalTest):
    def test_not_due_when_more_than_one_remaining(self):
        self._setup_term(sessions_limit=12, consumed=5)  # remaining 7
        fake = FakeSender()
        self.assertEqual(maybe_send(self.TERM, self.SID, self.CID, sender=fake), RenewalOutcome.NOT_DUE)
        self.assertEqual(fake.calls, [])
        self.assertFalse(has_renew_sms_been_sent(self.SID, self.TERM))

    def test_sent_writes_ledger_when_exactly_one_remaining(self):
        self._due_term()
        fake = FakeSender(status=SmsStatus.SENT)
        self.assertEqual(maybe_send(self.TERM, self.SID, self.CID, sender=fake), RenewalOutcome.SENT)
        self.assertEqual(len(fake.calls), 1)
        self.assertTrue(has_renew_sms_been_sent(self.SID, self.TERM))

    def test_already_sent_is_noop(self):
        self._due_term()
        self._mark_sent()
        fake = FakeSender()
        self.assertEqual(maybe_send(self.TERM, self.SID, self.CID, sender=fake), RenewalOutcome.ALREADY_SENT)
        self.assertEqual(fake.calls, [])

    def test_disabled_does_not_write_ledger(self):
        self._due_term()
        fake = FakeSender(status=SmsStatus.DISABLED)
        self.assertEqual(maybe_send(self.TERM, self.SID, self.CID, sender=fake), RenewalOutcome.DISABLED)
        self.assertFalse(has_renew_sms_been_sent(self.SID, self.TERM))  # stays resendable

    def test_failed_send_does_not_write_ledger(self):
        self._due_term()
        fake = FakeSender(status=SmsStatus.FAILED)
        self.assertEqual(maybe_send(self.TERM, self.SID, self.CID, sender=fake), RenewalOutcome.FAILED)
        self.assertFalse(has_renew_sms_been_sent(self.SID, self.TERM))

    def test_raising_sender_is_failed(self):
        self._due_term()
        fake = FakeSender(raise_exc=True)
        self.assertEqual(maybe_send(self.TERM, self.SID, self.CID, sender=fake), RenewalOutcome.FAILED)
        self.assertFalse(has_renew_sms_been_sent(self.SID, self.TERM))

    def test_no_phone(self):
        self._due_term(phone="")
        fake = FakeSender()
        self.assertEqual(maybe_send(self.TERM, self.SID, self.CID, sender=fake), RenewalOutcome.NO_PHONE)
        self.assertEqual(fake.calls, [])
        self.assertFalse(has_renew_sms_been_sent(self.SID, self.TERM))


class TestForceResend(_RenewalTest):
    def test_resends_even_when_not_due_and_already_sent(self):
        self._setup_term(sessions_limit=12, consumed=5)  # not due
        self._mark_sent()
        fake = FakeSender(status=SmsStatus.SENT)
        self.assertEqual(force_resend(self.TERM, self.SID, self.CID, sender=fake), RenewalOutcome.SENT)
        self.assertEqual(len(fake.calls), 1)
        self.assertTrue(has_renew_sms_been_sent(self.SID, self.TERM))

    def test_failed_resend_clears_flag_and_stays_resendable(self):
        self._due_term()
        self._mark_sent()
        fake = FakeSender(status=SmsStatus.FAILED)
        self.assertEqual(force_resend(self.TERM, self.SID, self.CID, sender=fake), RenewalOutcome.FAILED)
        # the old flag was cleared and NOT re-written -> resendable
        self.assertFalse(has_renew_sms_been_sent(self.SID, self.TERM))


class TestAlreadySent(_RenewalTest):
    def test_reflects_ledger(self):
        self._due_term()
        self.assertFalse(already_sent(self.TERM, self.SID))
        self._mark_sent()
        self.assertTrue(already_sent(self.TERM, self.SID))


if __name__ == "__main__":
    unittest.main()
