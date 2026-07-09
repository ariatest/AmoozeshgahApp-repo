# AcaSmart

AcaSmart manages the operational records of a music academy, including student enrollments, class scheduling, attendance, tuition, payments, and renewal reminders.

## Language

**Student**:
A learner enrolled in academy lessons, uniquely identified by national code. The Student owns the financial account for their Terms, even when a parent or guardian pays in practice. Phone is optional for enrollment but required for SMS delivery.
_Avoid_: Client, payer

**Teacher**:
An instructor who teaches one or more Instruments, uniquely identified by national code. A Class has exactly one primary Teacher. Teacher phone is optional contact information.
_Avoid_: Staff member, substitute

**Instrument**:
A named subject taught by Teachers and offered through Classes.
_Avoid_: Skill, course type

**Financial Account**:
The tuition, extra payments, debt, and settlement state for a Student's Term.
_Avoid_: Parent account, payer account

**Tuition Payment**:
A Payment applied to a Term's tuition debt. Tuition can be collected any time after the Term is created, including before the first Session is held, but a Tuition Payment cannot exceed the remaining tuition debt for that Term.
_Avoid_: Extra payment

**Extra Payment**:
A non-tuition charge or payment associated with a Student's Term. Extra Payments are tracked for reporting but are not applied to tuition debt, and should have a description explaining why the money was collected.
_Avoid_: Tuition payment

**Term**:
A paid enrollment cycle for one Student in one Class. A Term is created when the academy confirms the Student's Enrollment Schedule for that Class, snapshots the agreed tuition and session limit, completes when total Attendance records, Present plus Absence, reach that limit, and owns that cycle's tuition, extra payments, attendance records, and renewal reminders. Completion is a derived status, not a frozen lock: a completed Term stays visible and editable, and editing its Attendance recomputes whether it is complete.
_Avoid_: Course, semester, registration

**Renewal Reminder**:
An SMS reminder sent when exactly one session remains in a Term, after recording the Attendance that leaves one remaining. A Renewal Reminder counts as sent only when the SMS provider returns an explicit successful or accepted response; disabled sending, errors, provider rejection, and unknown responses remain eligible for resend.
_Avoid_: End-of-term message, generic SMS

**Manual SMS**:
A user-initiated message sent to selected Students outside the automatic Renewal Reminder workflow. Manual SMS may be logged, but it does not mark a Term's Renewal Reminder as sent unless explicitly sent as that Term's Renewal Reminder.
_Avoid_: Renewal reminder

**Business Date**:
A Shamsi/Jalali calendar date used for academy operations, stored and displayed as `YYYY-MM-DD`.
_Avoid_: Gregorian business date

**Lesson Time**:
A local academy time for scheduling lessons, stored and displayed as `HH:mm`.
_Avoid_: Timezone-aware lesson time

**Lesson Duration**:
The length of every lesson in a Term, fixed when the Term is created (typically 30 or 60 minutes). Duration affects scheduling conflict detection and tuition, but not the session count: a 60-minute lesson is one Session that counts once toward the Term's session limit.
_Avoid_: Slot, session weight

**Class**:
An academy offering taught by one Teacher for one Instrument, optionally associated with a room and default weekly time. A Class is not a Student's enrollment and does not by itself prove any Student attends.
_Avoid_: Term, enrollment

**Session**:
One actual dated meeting for one Student in one Class.
_Avoid_: Weekly slot, class schedule

**One-to-One Lesson**:
A lesson between one Teacher and one Student. AcaSmart's core scheduling and attendance model is centered on One-to-One Lessons.
_Avoid_: Group class

**Group Class**:
A class format where multiple Students attend the same Session together. Group Classes are out of scope for AcaSmart's current scheduling, attendance, tuition, and reminder model.
_Avoid_: One-to-one lesson

**Enrollment Schedule**:
The recurring day and time commitment for one Student in one Class during a Term. The Enrollment Schedule is the source of truth for normal future occurrences, and neither a Student nor a Teacher can have overlapping Enrollment Schedules, where overlap is judged by Lesson Duration (a 60-minute lesson conflicts with anything in its full interval), not by an exact start-time match. Room is a descriptive label only and is not a conflict dimension.
_Avoid_: Session, class

**Attendance**:
The recorded outcome of a Session that actually happened. Attendance is either Present or Absence, and each consumes one session from the Term. A scheduled lesson that did not happen is recorded as a Canceled Session instead, which is not Attendance and consumes no session.
_Avoid_: Cancellation, rescheduling

**Present**:
An Attendance record showing that the Student attended a Session that the academy held.
_Avoid_: Completed session

**Absence**:
An Attendance record showing that the academy held the scheduled Session and the Student missed it. An Absence consumes one session from the Term.
_Avoid_: Cancellation, skipped session

**Canceled Session**:
A scheduled Session that does not happen and therefore does not consume a session from the Student's Term. Canceled Sessions stay visible in history with a cancellation status or reason, but do not appear as attendable Sessions.
_Avoid_: Absence, deleted session

**Session Consumption**:
The number of sessions a Term has used, counted as its Present plus Absence Attendance records; a Canceled Session never counts. A Term is complete when consumption reaches its session limit, where the limit is resolved as Term snapshot → Pricing Profile → the default `term_session_count` setting. Because completion is derived, deleting an Attendance record lowers consumption and can re-open a completed Term.
_Avoid_: Held sessions, attended count (present-only)

**Rescheduled Session**:
A scheduled Session moved to a different date or time while staying in the same Term. Rescheduling is not a distinct record: it is modeled as a Canceled Session (reason "rescheduled") on the original date plus normal Attendance on the new date, so the Term still consumes exactly one session.
_Avoid_: Absence, separate reschedule entity

**Deletion**:
Removal of a Term or Session that has no recorded history. Deletion is blocked once a Term has any Tuition Payment, Extra Payment, or Attendance. A Term that already has history is corrected by editing it directly — a deliberate, warned action — never by deletion.
_Avoid_: Cancellation, rescheduling, adjustment
