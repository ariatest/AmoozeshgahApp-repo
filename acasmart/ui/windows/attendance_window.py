from __future__ import annotations

from acasmart.data.repos.attendance_repo import (
    fetch_attendance_status_by_date,
    delete_attendance,
)
from acasmart.data.repos.settings_repo import get_setting_bool
from acasmart.data.repos.terms_repo import get_term_dates, refresh_completion, term_progress
from acasmart.data.repos.enrollment_repo import (
    fetch_scheduled_students_for_class_on_date,
)
from acasmart.data.repos.classes_repo import fetch_classes_on_weekday
from acasmart.data.repos.students_repo import get_student_contact
from acasmart.services import renewal_reminder
from acasmart.services.renewal_reminder import RenewalOutcome
from acasmart.services.attendance_recording import record_attendance

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QCheckBox, QDialog, QInputDialog
)
from PySide6.QtCore import Qt
import functools
import sqlite3
import jdatetime

from acasmart.ui.widgets.shamsi_date_popup import ShamsiDatePopup

from acasmart.ui.widgets.theme_manager import ThemeManager
from acasmart.ui.widgets.base_secondary_window import BaseSecondaryWindow

class AttendanceManager(BaseSecondaryWindow):
    def __init__(self, return_target: QWidget | None = None):
        super().__init__("مدیریت حضور و غیاب", return_target)
        self.setGeometry(300, 200, 600, 500)
        
        self.selected_class_id = None
        self.last_selected_date = jdatetime.date.today().isoformat()  # "1403-02-31"

        # Model-B: دیگر رکوردِ جلسه‌ای ساخته نمی‌شود؛ پاک‌سازیِ جلساتِ منقضی لازم نیست.


        layout = self.content_layout()
        layout.setSpacing(10)


        # --------- ردیف تاریخ ----------
        date_layout = QHBoxLayout()
        date_label = QLabel(": تاریخ جلسه")
        self.selected_shamsi_date = None
        
        self.date_btn = QPushButton("📅 انتخاب تاریخ جلسه")
        self.date_btn.setProperty("variant", "secondary")
        self.date_btn.setCursor(Qt.PointingHandCursor)
        self.date_btn.setToolTip("برای انتخاب تاریخ کلیک کنید")
        self.date_btn.clicked.connect(self.open_date_picker)
        
        date_layout.addWidget(date_label)
        date_layout.addWidget(self.date_btn)
        layout.addLayout(date_layout)

        # --------- ردیف انتخاب کلاس  (غیرفعال تا قبل از انتخاب تاریخ) ----------
        class_layout = QHBoxLayout()
        class_label = QLabel(": انتخاب کلاس")
        
        self.combo_class = QComboBox()
        self.combo_class.setEnabled(False)
        self.combo_class.currentIndexChanged.connect(self.on_class_changed)
        
        class_layout.addWidget(class_label)
        class_layout.addWidget(self.combo_class)
        layout.addLayout(class_layout)

        # --------- نمایش ترم‌های تکمیل‌شده (برای ویرایش گذشته / ارسال مجدد پیامک) ----------
        self.chk_show_completed = QCheckBox("نمایش ترم‌های تکمیل‌شده هم (برای ویرایش جلسات گذشته یا ارسال مجدد پیامک)")
        self.chk_show_completed.setToolTip("ترم‌هایی که به پایان رسیده‌اند را هم برای این تاریخ نشان بده")
        self.chk_show_completed.stateChanged.connect(self._on_show_completed_changed)
        layout.addWidget(self.chk_show_completed)

        # --------- جدول حضور ----------
        # جدول حضور: ID مخفی، نام هنرجو، چک‌باکس حاضر، چک‌باکس غائب
        self.table = QTableWidget()
        self.table.setObjectName("AttendanceTable")
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(["ID", "نام هنرجو", "ساعت", "حاضر", "غائب", "term_id", "عملیات"])
        self.table.setColumnHidden(0, True)
        self.table.setColumnHidden(5, True)

        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table)

        # --------- دکمه ذخیره ----------
        self.btn_save = QPushButton("ذخیره حضور و غیاب ➕")
        self.btn_save.setProperty("variant", "primary")
        self.btn_save.clicked.connect(self.save_attendance)
        layout.addWidget(self.btn_save)

        self.showMaximized()

        # مقداردهی اولیه بر اساس تاریخ آخر استفاده‌شده
        self.selected_shamsi_date = self.last_selected_date
        self.date_btn.setText(f"📅 {self.selected_shamsi_date}")
        self.load_classes()

        # بعد از ساخت ویجت‌ها، repolish
        for w in (self.date_btn, self.btn_save):
            ThemeManager.repolish(w)
        ThemeManager.repolish(self.combo_class)

    # ------------------- UI / DATA -------------------

    def load_classes(self):
        """Populate the class combobox based on selected date"""
        self.combo_class.clear()
        weekday_map = {
            0: "دوشنبه",
            1: "سه‌شنبه",
            2: "چهارشنبه",
            3: "پنجشنبه",
            4: "جمعه",
            5: "شنبه",
            6: "یکشنبه",
        }

        if not self.selected_shamsi_date:
            return

        # محاسبه دقیق روز هفته با تبدیل به میلادی
        jdate_obj = jdatetime.date.fromisoformat(self.selected_shamsi_date)
        gregorian = jdate_obj.togregorian()
        weekday = gregorian.weekday()  # Monday = 0
        current_day = weekday_map[weekday]

        # واکشی کلاس‌هایی که در این روز برگزار می‌شوند
        classes = fetch_classes_on_weekday(current_day)

        if not classes:
            QMessageBox.information(
                self,
                "هیچ کلاسی یافت نشد",
                f"در روز {current_day} ({self.selected_shamsi_date}) کلاسی یافت نشد.",
            )
            self.combo_class.setEnabled(False)
            return

        for cid, name, teacher, instr, cls_day, start, end, room in classes:
            # استایل تم: فقط اسم + ساعت
            self.combo_class.addItem(f"{name} — {start}", cid)

        self.combo_class.setEnabled(True)
        self.combo_class.setCurrentIndex(0)

    def on_class_changed(self, idx):
        """تنظیم کلاس انتخاب‌شده و بارگذاری حضور آن."""
        self.selected_class_id = self.combo_class.itemData(idx)
        # فقط زمانی فراخوانی کن که کلاس واقعاً انتخاب شده
        if self.selected_class_id is not None:
            self.load_attendance()

    def _on_show_completed_changed(self, _state):
        """بازخوانی جدول هنگام تغییرِ نمایشِ ترم‌های تکمیل‌شده."""
        if self.selected_class_id is not None:
            self.load_attendance()

    def load_attendance(self):
        """بارگذاری لیست حضور/غیاب با سقفِ per-term و شمارش کل جلسات (حاضر+غایب)."""
        if self.selected_class_id is None:
            QMessageBox.warning(self, "خطا", "لطفاً ابتدا یک کلاس را انتخاب کنید.")
            return

        if not self.selected_shamsi_date:
            QMessageBox.warning(self, "خطا", "لطفاً ابتدا تاریخ جلسه (شمسی) را انتخاب کنید.")
            return

        selected_date = self.selected_shamsi_date
        self.table.setRowCount(0)

# رنگ‌ها از تم
        tokens = ThemeManager.tokens()
        muted = tokens["muted"]
        danger = tokens["error"]
        primary = tokens["primary"]

        # Model-B: فهرستِ هنرجویانِ این کلاس در این تاریخ از روی برنامهٔ هفتگیِ ترم‌ها محاسبه می‌شود
        # (نه از جدولِ sessions). با تیکِ «نمایش ترم‌های تکمیل‌شده» ترم‌های پایان‌یافته هم می‌آیند.
        show_completed = getattr(self, "chk_show_completed", None) is not None and self.chk_show_completed.isChecked()
        rows = fetch_scheduled_students_for_class_on_date(
            self.selected_class_id, selected_date, include_completed=show_completed
        )
        for sid, name, teacher, session_time, term_id in rows:
            progress = term_progress(term_id)
            if progress is None:
                continue
            term_limit = progress.limit
            notify_session_number = max(0, term_limit - 1)

            # شمارش کل ثبت‌ها برای همان ترم (حاضر + غایب)
            done_total = progress.consumed

            # وضعیت امروز: None (ثبت‌نشده) / 'present' / 'absent' / 'canceled'
            record_status = fetch_attendance_status_by_date(sid, self.selected_class_id, selected_date, term_id)

            row = self.table.rowCount()
            self.table.insertRow(row)

            # ستون مخفی: student_id
            id_item = QTableWidgetItem(str(sid))
            id_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(row, 0, id_item)

            # ستون مخفی: term_id
            term_item = QTableWidgetItem(str(term_id))
            term_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(row, 5, term_item)

            # نام + وضعیت SMS
            display_name = name
            name_item = QTableWidgetItem()
            name_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            tooltip = f"جلسات ثبت‌شده (کل): {done_total} از {term_limit} — باقی‌مانده: {max(0, term_limit - done_total)}"

            # وضعیت SMS برای نمایش آیکون/ایموجی کنار نام و tooltip
            sent_flag = renewal_reminder.already_sent(term_id, sid)
            sms_enabled = get_setting_bool("sms_enabled", True)
            if sent_flag:
                display_name += "  ✅"
                tooltip += "\nپیامک تمدید ارسال شده است."
            else:
                if not sms_enabled:
                    display_name += "  ⚠️"
                    tooltip += "\nارسال پیامک غیرفعال است."
                elif done_total >= notify_session_number:
                    display_name += "  ❌"
                    tooltip += "\nارسال پیامک ناموفق/در انتظار"

            if record_status == "canceled":
                display_name += "  🚫 لغو"
                tooltip += "\nجلسهٔ لغوشده (در سقف ترم شمرده نمی‌شود)."

            name_item.setText(display_name)
            name_item.setToolTip(tooltip)
            self.table.setItem(row, 1, name_item)

            # ساعت جلسه
            time_item = QTableWidgetItem(session_time)
            time_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(row, 2, time_item)

            # چک‌باکس‌ها
            present_chk = QCheckBox()
            absent_chk = QCheckBox()

            is_canceled = (record_status == "canceled")

            # جلسهٔ لغوشده قابل علامت‌گذاری نیست؛ همچنین اگر ترم پر شده و امروز چیزی ثبت نشده
            if is_canceled or (done_total >= term_limit and record_status is None):
                present_chk.setEnabled(False)
                absent_chk.setEnabled(False)

            present_chk.stateChanged.connect(
                functools.partial(self._on_present_changed, absent_chk)
            )
            absent_chk.stateChanged.connect(
                functools.partial(self._on_absent_changed, present_chk)
            )

            if record_status == "present":
                present_chk.setChecked(True)
            elif record_status == "absent":
                absent_chk.setChecked(True)

            self.table.setCellWidget(row, 3, present_chk)
            self.table.setCellWidget(row, 4, absent_chk)
            self.table.setRowHeight(row, 28)

            # دکمه حذف رکورد امروز
            btn_delete = QPushButton("❌ حذف")
            btn_delete.setProperty("variant", "danger")
            btn_delete.setToolTip("حذف حضور/غیاب ثبت‌شده در این تاریخ")
            # اگر رکوردی برای این روز ثبت نشده، دکمه را غیرفعال کن
            btn_delete.setEnabled(record_status is not None)

            btn_delete.clicked.connect(
                functools.partial(
                    self.delete_attendance_row,
                    sid,
                    self.selected_class_id,
                    term_id,
                    selected_date
                )
            )

            # چون داخل جدولیم، بعد از setProperty باید repolish کنیم
            ThemeManager.repolish(btn_delete)

            op_wrap = QWidget()
            op_layout = QHBoxLayout(op_wrap)
            op_layout.addWidget(btn_delete)
            op_layout.setContentsMargins(0, 0, 0, 0)
            op_layout.setAlignment(Qt.AlignCenter)

            # دکمه ارسال مجدد پیامک یادآوری (وقتی موعدِ یادآوری رسیده و ارسال فعال است)
            if sms_enabled and done_total >= notify_session_number:
                btn_resend = QPushButton("📩 ارسال مجدد")
                btn_resend.setProperty("variant", "primary")
                btn_resend.setToolTip("ارسال مجدد پیامک یادآوری تمدید")
                btn_resend.clicked.connect(
                    functools.partial(self.resend_renewal_sms, sid, term_id)
                )
                ThemeManager.repolish(btn_resend)
                op_layout.addWidget(btn_resend)

            # دکمه «لغو جلسه»: ثبت جلسهٔ لغوشده با دلیل (بدون مصرف جلسه از ترم)
            if not is_canceled:
                btn_cancel = QPushButton("🚫 لغو")
                btn_cancel.setProperty("variant", "danger")
                btn_cancel.setToolTip("ثبت این جلسه به‌عنوان «لغو شده» (بدون مصرف جلسه از ترم)")
                btn_cancel.clicked.connect(
                    functools.partial(
                        self.cancel_session_row, sid, self.selected_class_id, term_id, selected_date
                    )
                )
                ThemeManager.repolish(btn_cancel)
                op_layout.addWidget(btn_cancel)

            self.table.setCellWidget(row, 6, op_wrap)

    # ------------------- MUTUAL EXCLUSIVITY -------------------

    def _on_present_changed(self, other_chk, state):
        if state == Qt.Checked:
            other_chk.setChecked(False)

    def _on_absent_changed(self, other_chk, state):
        if state == Qt.Checked:
            other_chk.setChecked(False)


    # ------------------- RENEWAL SMS -------------------

    def resend_renewal_sms(self, sid: int, term_id: int):
        """ارسال مجدد دستیِ پیامک یادآوری تمدید توسط کاربر (سیاست در ماژولِ renewal_reminder)."""
        outcome = renewal_reminder.force_resend(term_id, sid, self.selected_class_id)
        if outcome == RenewalOutcome.SENT:
            QMessageBox.information(self, "موفق", "پیامک یادآوری تمدید ارسال شد.")
        elif outcome == RenewalOutcome.DISABLED:
            QMessageBox.warning(self, "غیرفعال", "ارسال پیامک در تنظیمات غیرفعال است.")
        elif outcome == RenewalOutcome.NO_PHONE:
            QMessageBox.warning(self, "بدون شماره", "برای این هنرجو شماره‌ای ثبت نشده است.")
        else:
            QMessageBox.warning(
                self, "خطای پیامک",
                "ارسال مجدد پیامک ناموفق بود. می‌توانید دوباره تلاش کنید."
            )
        self.load_attendance()


    # ------------------- SAVE -------------------

    def save_attendance(self):
        """ذخیره حضور/غیاب؛ SMS وقتی ۱ جلسه باقی مانده؛ حذف جلسات آینده پس از ست‌شدن end_date."""
        if not self.selected_shamsi_date:
            QMessageBox.warning(self, "خطا", "لطفاً ابتدا تاریخ جلسه (شمسی) را انتخاب کنید.")
            return
        
        if self.selected_class_id is None:
            QMessageBox.warning(self, "خطا", "ابتدا کلاس را انتخاب کنید.")
            return
        
        selected_date = self.selected_shamsi_date
        failed_sms = []
        any_saved = False

        for row in range(self.table.rowCount()):
            sid = int(self.table.item(row, 0).text())
            present_chk = self.table.cellWidget(row, 3)
            absent_chk  = self.table.cellWidget(row, 4)
            present = present_chk.isChecked() if present_chk else False
            absent  = absent_chk.isChecked()  if absent_chk  else False

            try:
                term_id_item = self.table.item(row, 5)
                if term_id_item is None:
                    continue
                term_id = int(term_id_item.text())

                # بازه ترم
                term_dates = get_term_dates(term_id)  # (start_date, end_date)
                if not term_dates:
                    continue
                start_date, end_date = term_dates

                # بیرون از بازه ترم ثبت نکن
                if selected_date < start_date or (end_date and selected_date > end_date):
                    continue

                # فقط اگر یکی از چک‌باکس‌ها زده شده باشد ثبت کن
                if present or absent:
                    any_saved = True   # ✅ الان می‌دونیم حداقل یک ردیف ذخیره شد
                    status = "present" if present else "absent"

                    # ثبت رکورد امروز + اثرهای پیرو (تکمیلِ ترم و یادآوریِ تمدید) در یک فراخوانی
                    result = record_attendance(term_id, sid, self.selected_class_id, selected_date, status)
                    # فقط شکستِ واقعیِ پیامک گزارش می‌شود؛ NOT_DUE/ALREADY_SENT/SENT/DISABLED خطا نیستند.
                    if result.reminder in (RenewalOutcome.FAILED, RenewalOutcome.NO_PHONE):
                        name, _ = get_student_contact(sid)
                        failed_sms.append(name)

                    # Model-B: ترم که کامل شد، جلسات آینده محاسبه‌ای‌اند و چیزی برای حذف نیست.

            except sqlite3.IntegrityError as e:
                QMessageBox.warning(self, "خطا", f"خطا در ذخیره‌سازی: {e}")

        if not any_saved:
            QMessageBox.warning(self, "عدم ثبت", "هیچ هنرجویی انتخاب نشده است. لطفاً حداقل یکی را حاضر یا غایب کنید.")
            return
        
        if failed_sms:
            QMessageBox.warning(self, "خطای پیامک", "ارسال پیام برای هنرجویان زیر انجام نشد:\n" + "\n".join(failed_sms))
        else:
            QMessageBox.information(self, "موفق", "حضور و غیاب با موفقیت ذخیره شد.")

        self.load_attendance()

    # ------------------- DATE PICKER -------------------

    def open_date_picker(self):
        dlg = ShamsiDatePopup(initial_date=self.selected_shamsi_date)
        if dlg.exec_() == QDialog.Accepted:
            shamsi_date = dlg.get_selected_date()
            self.selected_shamsi_date = shamsi_date
            self.date_btn.setText(f"📅 {shamsi_date}")
            self.last_selected_date = shamsi_date  # چون string شمسی هست
            self.load_classes()

    # ------------------- DELETE ROW -------------------

    def cancel_session_row(self, student_id: int, class_id: int, term_id: int, date_value: str):
        """ثبت «لغو جلسه» با دلیل برای این تاریخ؛ جلسهٔ لغوشده در سقف ترم شمرده نمی‌شود."""
        reason, ok = QInputDialog.getText(self, "لغو جلسه", "دلیل لغو جلسه را وارد کنید:")
        if not ok:
            return
        reason = (reason or "").strip() or None
        try:
            record_attendance(term_id, student_id, class_id, date_value, "canceled", cancel_reason=reason)
        except Exception as e:
            QMessageBox.warning(self, "خطا", f"ثبت لغو جلسه با خطا مواجه شد:\n{e}")
            return
        self.load_attendance()

    def delete_attendance_row(self, student_id: int, class_id: int, term_id: int, date_value: str):
        """حذف حضور/غیابِ همان روز و بازخوانی جدول؛ سپس بازمحاسبهٔ پایان ترم."""
        try:
            # حذف بر اساس ستون date
            deleted = delete_attendance(student_id, class_id, term_id, date_value)

            # اگر با حذف، مجموع از limit کمتر شد و end_date قبلاً ست بود → بازش کن
            try:
                refresh_completion(term_id)
            except Exception:
                pass

            if deleted == 0:
                print(f"[WARN] No attendance row deleted for ({student_id}, {class_id}, {term_id}, {date_value})")

            self.load_attendance()
        except Exception as e:
            QMessageBox.warning(self, "خطا", f"حذف حضور/غیاب با خطا مواجه شد:\n{e}")
