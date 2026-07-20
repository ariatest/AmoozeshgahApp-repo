from __future__ import annotations

from acasmart.data.repos.classes_repo import get_day_and_time_for_class, get_class_by_id
from acasmart.data.repos.notifications_repo import get_unnotified_expired_terms, get_visible_finished_terms, dismiss_finished_terms, mark_terms_as_notified
from acasmart.data.repos.payments_repo import delete_term_if_no_history
from acasmart.data.repos.profiles_repo import list_pricing_profiles, set_term_config, apply_profile_to_term
from acasmart.data.repos.enrollment_repo import enroll, reschedule, fetch_enrollments_for_class, EnrollmentStatus
from acasmart.data.repos.settings_repo import get_setting
from acasmart.data.repos.students_repo import fetch_students_with_teachers
from acasmart.data.repos.terms_repo import get_last_term_end_date, get_term_id_by_student_and_class, get_active_term_count_per_student, get_term_pricing, refresh_completion
from acasmart.core.schedule import first_on_or_after
from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QListWidget, QListWidgetItem,
    QVBoxLayout, QTimeEdit, QMessageBox, QDialog,
    QDialogButtonBox, QHBoxLayout, QComboBox, QRadioButton, QSpinBox, QCheckBox
)
from PySide6.QtGui import QColor
from PySide6.QtCore import QTime, Qt, QSize, QDate
from acasmart.ui.widgets.shamsi_date_popup import ShamsiDatePopup
from acasmart.ui.widgets.shamsi_date_picker import ShamsiDatePicker
from acasmart.ui.widgets.student_picker_popup import StudentPickerPopup
from acasmart.ui.widgets.class_picker_popup import ClassPickerPopup
import jdatetime
import sqlite3
from acasmart.core.fa_collation import sort_records_fa, fa_digits
from acasmart.core.utils import currency_label, format_currency_with_unit, parse_user_amount_to_toman
from acasmart.ui.widgets.theme_manager import ThemeManager
from acasmart.ui.widgets.base_secondary_window import BaseSecondaryWindow

class TermConfigDialog(QDialog):
    """
    انتخاب پروفایل/ترم سفارشی برای ساخت ترم همراه با جلسهٔ اول.
    خروجی: dict با کلیدهای sessions_limit, tuition_fee, currency_unit, profile_id (همه Optional)
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("تنظیمات ترم")

        # حالت‌ها
        self.rb_profile = QRadioButton("استفاده از پروفایل شهریه")
        self.rb_custom  = QRadioButton("سفارشی")
        self.rb_profile.setChecked(True)
        self.ui_unit = currency_label()  # "تومان" یا "ریال"

        # پروفایل‌ها
        self.profile_combo = QComboBox()
        self.profiles = list_pricing_profiles()  # [(id, name, sessions_limit, tuition_fee, currency_unit, is_default)]
        for pid, name, sl, fee_toman, unit, is_def in self.profiles:
            label = f"{name} — {sl} جلسه، {format_currency_with_unit(fee_toman)}"
            self.profile_combo.addItem(label, pid)
            if is_def:
                self.profile_combo.setCurrentIndex(self.profile_combo.count() - 1)

        # بعد از حلقهٔ افزودن آیتم‌های پروفایل به کمبو:
        if not self.profiles:
            self.rb_profile.setEnabled(False)
            self.profile_combo.setEnabled(False)
            self.rb_custom.setChecked(True)

        # ورودی سفارشی
        self.spin_sessions = QSpinBox()
        self.spin_sessions.setRange(1, 100)
        self.spin_sessions.setValue(int(get_setting("term_session_count", 12)))

        self.spin_fee = QSpinBox()
        self.spin_fee.setRange(0, 1_000_000_000)
        self.spin_fee.setSingleStep(10000)

        # مقدار اولیه‌ی «تومان خام» از تنظیمات:
        base_fee_toman = int(get_setting("term_fee", get_setting("term_tuition", 6000000)))
        # برای نمایش: اگر UI روی ریال است، ×۱۰
        display_fee = base_fee_toman * 10 if self.ui_unit == "ریال" else base_fee_toman
        self.spin_fee.setValue(int(display_fee))

        # نمایش واحد
        self.currency_unit = get_setting("currency_unit", "toman")
        self.lbl_unit = QLabel(f"واحد: {self.ui_unit}")  # ← واحد نمایش فعلی

        # چیدمان
        lay = QVBoxLayout(self)
        lay.addWidget(self.rb_profile)
        lay.addWidget(self.profile_combo)
        lay.addSpacing(8)
        lay.addWidget(self.rb_custom)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("سقف جلسات:"))
        row1.addWidget(self.spin_sessions)
        lay.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel(f"شهریه ترم (به {self.ui_unit}):"))
        row2.addWidget(self.spin_fee)
        lay.addLayout(row2)

        lay.addWidget(self.lbl_unit)

        # مدت هر جلسه (۳۰ یا ۶۰ دقیقه) — برای تشخیص تداخل و نمایش
        self.combo_duration = QComboBox()
        self.combo_duration.addItem("۳۰ دقیقه", 30)
        self.combo_duration.addItem("۶۰ دقیقه (یک‌ساعته)", 60)
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("مدت هر جلسه:"))
        row3.addWidget(self.combo_duration)
        lay.addLayout(row3)

        # دکمه‌ها
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

        # Style dialog buttons with theme variants
        try:
            ok_btn = btns.button(QDialogButtonBox.Ok)
            cancel_btn = btns.button(QDialogButtonBox.Cancel)
            if ok_btn:
                ok_btn.setProperty("variant", "primary")
                ThemeManager.repolish(ok_btn)
            if cancel_btn:
                cancel_btn.setProperty("variant", "secondary")
                ThemeManager.repolish(cancel_btn)
        except Exception:
            pass

        # فعال/غیرفعال‌سازی ورودی‌های سفارشی
        def sync_enabled():
            custom = self.rb_custom.isChecked()
            self.spin_sessions.setEnabled(custom)
            self.spin_fee.setEnabled(custom)
        self.rb_profile.toggled.connect(sync_enabled)
        self.rb_custom.toggled.connect(sync_enabled)
        sync_enabled()

    def get_config(self):
        duration = int(self.combo_duration.currentData())
        if self.rb_custom.isChecked():
            # مقدار نمایش‌داده‌شده (ممکن است ریال باشد) → تبدیل به «تومان خام»
            fee_toman = parse_user_amount_to_toman(str(self.spin_fee.value()))
            return {
                "sessions_limit": int(self.spin_sessions.value()),
                "tuition_fee":   int(fee_toman),   # همیشه تومان
                "currency_unit": self.currency_unit,
                "profile_id":    None,
                "lesson_duration": duration,
            }
        else:
            pid = self.profile_combo.currentData()
            row = next((p for p in self.profiles if p[0] == pid), None)
            if row:
                _, _, sl, fee_toman, unit, _ = row
                return {
                    "sessions_limit": int(sl),
                    "tuition_fee":   int(fee_toman),                 # تومان خام از پروفایل
                    "currency_unit": unit or self.currency_unit,
                    "profile_id":    pid,
                    "lesson_duration": duration,
                }
            return {"sessions_limit": None, "tuition_fee": None, "currency_unit": None,
                    "profile_id": None, "lesson_duration": duration}


class EditEnrollmentDialog(QDialog):
    """ویرایش ساعت/مدت یک ثبت‌نام موجود (بدون حذف و ثبت دوباره).

    خروجی از طریق exec_(): result() یکی از 'save' یا 'delete' است؛ در حالت save
    مقادیر new_time (HH:mm) و new_duration در دسترس‌اند.
    """
    SAVE = 1
    DELETE = 2

    def __init__(self, parent, student_name, class_start_time, current_time, current_duration,
                 current_sessions=None, current_fee_toman=None, current_profile_id=None,
                 current_start_date=None):
        super().__init__(parent)
        self.setWindowTitle("ویرایش ثبت‌نام")
        self.action = None
        self.new_time = None
        self.new_duration = None
        self.new_start_date = None
        self._class_start_time = class_start_time

        lay = QVBoxLayout(self)
        lbl = QLabel(f"هنرجو: {student_name}")
        lbl.setProperty("sectionTitle", True)
        lay.addWidget(lbl)

        row_t = QHBoxLayout()
        row_t.addWidget(QLabel("ساعت جلسه:"))
        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat("HH:mm")
        try:
            self.time_edit.setTime(QTime.fromString(str(current_time), "HH:mm"))
        except Exception:
            self.time_edit.setTime(QTime(12, 0))
        row_t.addWidget(self.time_edit)
        lay.addLayout(row_t)

        row_d = QHBoxLayout()
        row_d.addWidget(QLabel("مدت هر جلسه:"))
        self.combo_duration = QComboBox()
        self.combo_duration.addItem("۳۰ دقیقه", 30)
        self.combo_duration.addItem("۶۰ دقیقه (یک‌ساعته)", 60)
        self.combo_duration.setCurrentIndex(1 if int(current_duration or 30) >= 60 else 0)
        row_d.addWidget(self.combo_duration)
        lay.addLayout(row_d)

        # تاریخِ شروعِ ترم — قابلِ ویرایش (روی روزِ کلاس snap می‌شود)
        self.date_start = ShamsiDatePicker("تاریخ شروع ترم:")
        if current_start_date:
            try:
                g = jdatetime.date.fromisoformat(current_start_date).togregorian()
                self.date_start.setDate(QDate(g.year, g.month, g.day))
            except Exception:
                pass
        lay.addWidget(self.date_start)

        # --- قیمت‌گذاری (پروفایل/سفارشی) — همیشه قابلِ ویرایش ---
        self.ui_unit = currency_label()
        self.currency_unit = get_setting("currency_unit", "toman")
        self.profiles = list_pricing_profiles()  # [(id, name, sessions_limit, tuition_fee, currency_unit, is_default)]

        lbl_price = QLabel("قیمت‌گذاری:")
        lbl_price.setProperty("sectionTitle", True)
        lay.addWidget(lbl_price)

        self.rb_profile = QRadioButton("استفاده از پروفایل شهریه")
        self.rb_custom = QRadioButton("شهریهٔ سفارشی")
        self.profile_combo = QComboBox()
        for pid, pname, sl, fee_toman, unit, is_def in self.profiles:
            self.profile_combo.addItem(f"{pname} — {sl} جلسه، {format_currency_with_unit(fee_toman)}", pid)

        self.spin_sessions = QSpinBox()
        self.spin_sessions.setRange(1, 100)
        self.spin_sessions.setValue(int(current_sessions) if current_sessions else int(get_setting("term_session_count", 12)))

        self.spin_fee = QSpinBox()
        self.spin_fee.setRange(0, 1_000_000_000)
        self.spin_fee.setSingleStep(10000)
        cur_fee_toman = int(current_fee_toman) if current_fee_toman else int(get_setting("term_fee", get_setting("term_tuition", 6000000)))
        self.spin_fee.setValue(cur_fee_toman * 10 if self.ui_unit == "ریال" else cur_fee_toman)

        lay.addWidget(self.rb_profile)
        lay.addWidget(self.profile_combo)
        lay.addWidget(self.rb_custom)
        row_s = QHBoxLayout()
        row_s.addWidget(QLabel("سقف جلسات:"))
        row_s.addWidget(self.spin_sessions)
        lay.addLayout(row_s)
        row_f = QHBoxLayout()
        row_f.addWidget(QLabel(f"شهریه (به {self.ui_unit}):"))
        row_f.addWidget(self.spin_fee)
        lay.addLayout(row_f)

        # حالتِ اولیه بر اساس وضعیتِ فعلیِ ترم: اگر روی پروفایلی بوده و آن پروفایل هست → پروفایل، وگرنه سفارشی
        preselect = -1
        if current_profile_id is not None:
            for idx in range(self.profile_combo.count()):
                if self.profile_combo.itemData(idx) == current_profile_id:
                    preselect = idx
                    break
        if not self.profiles:
            self.rb_profile.setEnabled(False)
            self.profile_combo.setEnabled(False)
            self.rb_custom.setChecked(True)
        elif preselect >= 0:
            self.profile_combo.setCurrentIndex(preselect)
            self.rb_profile.setChecked(True)
        else:
            self.rb_custom.setChecked(True)

        def _sync_pricing():
            custom = self.rb_custom.isChecked()
            self.spin_sessions.setEnabled(custom)
            self.spin_fee.setEnabled(custom)
            self.profile_combo.setEnabled(not custom and bool(self.profiles))
        self.rb_profile.toggled.connect(_sync_pricing)
        self.rb_custom.toggled.connect(_sync_pricing)
        _sync_pricing()

        btns = QHBoxLayout()
        self.btn_save = QPushButton("💾 ذخیرهٔ تغییرات")
        self.btn_save.setProperty("variant", "primary")
        self.btn_save.clicked.connect(self._on_save)
        self.btn_delete = QPushButton("🗑 حذف ثبت‌نام")
        self.btn_delete.setProperty("variant", "secondary")
        self.btn_delete.clicked.connect(self._on_delete)
        self.btn_cancel = QPushButton("انصراف")
        self.btn_cancel.setProperty("variant", "ghost")
        self.btn_cancel.clicked.connect(self.reject)
        btns.addWidget(self.btn_save)
        btns.addWidget(self.btn_delete)
        btns.addWidget(self.btn_cancel)
        lay.addLayout(btns)

        for w in (self.btn_save, self.btn_delete, self.btn_cancel):
            try:
                ThemeManager.repolish(w)
            except Exception:
                pass

    def _on_save(self):
        new_time = self.time_edit.time().toString("HH:mm")
        # ساعت جلسه نباید قبل از شروع کلاس باشد (هماهنگ با منطق ثبت‌نام)
        if self._class_start_time:
            try:
                if self.time_edit.time() < QTime.fromString(self._class_start_time, "HH:mm"):
                    QMessageBox.warning(self, "خطا",
                        "ساعت جلسه نمی‌تواند قبل از شروع کلاس باشد.")
                    return
            except Exception:
                pass
        self.action = self.SAVE
        self.new_time = new_time
        self.new_duration = int(self.combo_duration.currentData())
        self.new_start_date = self.date_start.selected_shamsi if self.date_start.has_date() else None
        self.accept()

    def _on_delete(self):
        self.action = self.DELETE
        self.accept()

    def get_pricing(self):
        """قیمت‌گذاریِ انتخاب‌شده: dict با کلیدهای sessions_limit/tuition_fee/currency_unit/profile_id."""
        if self.rb_custom.isChecked() or not self.profiles:
            return {
                "sessions_limit": int(self.spin_sessions.value()),
                "tuition_fee": int(parse_user_amount_to_toman(str(self.spin_fee.value()))),
                "currency_unit": self.currency_unit,
                "profile_id": None,
            }
        pid = self.profile_combo.currentData()
        row = next((p for p in self.profiles if p[0] == pid), None)
        if row:
            _, _, sl, fee_toman, unit, _ = row
            return {"sessions_limit": int(sl), "tuition_fee": int(fee_toman),
                    "currency_unit": unit or self.currency_unit, "profile_id": pid}
        return {"sessions_limit": int(self.spin_sessions.value()),
                "tuition_fee": int(parse_user_amount_to_toman(str(self.spin_fee.value()))),
                "currency_unit": self.currency_unit, "profile_id": None}


class FinishedTermsDialog(QDialog):
    """فهرستِ ترم‌های پایان‌یافته با امکانِ «حذف موارد انتخاب‌شده» یا «پاک‌کردن کلِ فهرست».

    خروجی:
      - cleared == True اگر کاربر «پاک‌کردن کل فهرست» را زده باشد (همهٔ ترم‌ها پنهان شوند).
      - dismissed_term_ids: term_idهایی که کاربر تک‌تک از فهرست حذف کرده است.
    حذف فقط از نما پنهان می‌کند؛ ترم و سابقهٔ آن حذف نمی‌شود.
    """
    def __init__(self, parent, rows):
        super().__init__(parent)
        self.setWindowTitle("ترم‌های پایان‌یافته")
        self.resize(560, 480)
        self.cleared = False
        self.dismissed_term_ids = []

        lay = QVBoxLayout(self)

        # نوار بالا: حذفِ انتخاب‌شده‌ها + پاک‌کردنِ کل + بستن — بالای فهرست تا همیشه دیده شوند
        top = QHBoxLayout()
        self.btn_remove = QPushButton("🗑 حذف موارد انتخاب‌شده")
        self.btn_remove.setProperty("variant", "secondary")
        self.btn_remove.clicked.connect(self._on_remove_selected)
        self.btn_clear = QPushButton("🧹 پاک‌کردن کل فهرست")
        self.btn_clear.setProperty("variant", "secondary")
        self.btn_clear.clicked.connect(self._on_clear)
        btn_close = QPushButton("بستن")
        btn_close.setProperty("variant", "ghost")
        btn_close.clicked.connect(self.reject)
        top.addWidget(self.btn_remove)
        top.addWidget(self.btn_clear)
        top.addStretch(1)
        top.addWidget(btn_close)
        lay.addLayout(top)

        lbl = QLabel("هنرجویان زیر ترم‌شان به پایان رسیده است (برای حذف، کنارِ موارد تیک بزنید):")
        lbl.setProperty("sectionTitle", True)
        lay.addWidget(lbl)

        # فهرستِ اسکرول‌شونده — هر ردیف یک چک‌باکس دارد تا انتخابِ چندتایی ساده باشد
        self.list = QListWidget()
        for (student_id, class_id, student_name, national_code,
             class_name, day, term_id, session_date, session_time) in rows:
            item = QListWidgetItem(
                f"• {student_name} | کدملی: {national_code} | {class_name} ({day}) — {session_date} ساعت {session_time}"
            )
            item.setData(Qt.UserRole, term_id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.list.addItem(item)
        lay.addWidget(self.list)

        for w in (self.btn_remove, self.btn_clear, btn_close):
            try:
                ThemeManager.repolish(w)
            except Exception:
                pass

    def _on_remove_selected(self):
        checked = [self.list.item(i) for i in range(self.list.count())
                   if self.list.item(i).checkState() == Qt.Checked]
        if not checked:
            QMessageBox.information(self, "انتخابی نشده",
                "ابتدا کنارِ یک یا چند مورد تیک بزنید.")
            return
        for item in checked:
            tid = item.data(Qt.UserRole)
            if tid is not None:
                self.dismissed_term_ids.append(tid)
            self.list.takeItem(self.list.row(item))
        # اگر فهرست خالی شد، دیگر چیزی برای نمایش نیست
        if self.list.count() == 0:
            self.accept()

    def _on_clear(self):
        self.cleared = True
        self.accept()


class SessionManager(BaseSecondaryWindow):
    def __init__(self, return_target: QWidget | None = None):
        super().__init__("مدیریت ثبت‌نام هنرجویان", return_target)
        self.setGeometry(350, 250, 500, 500)


        self.last_selected_date = jdatetime.date.today().strftime("%Y-%m-%d")
        self.selected_student_teacher_name = None
        self.students_data = []  # [(id, name, teacher)]
        self.selected_student_id = None
        self.selected_class_id = None

        self.selected_term_id = None

        self.is_editing = False
        self.selected_session_id = None

        self.last_selected_time = None
        self.last_time_per_class = {}  # کلاس به ساعت آخر ثبت‌شده

        self.session_counts_by_student = {}  # {student_id: count}
        self.refresh_session_counts()        # ← اولین بارگیری

        layout = self.content_layout()
        layout.setSpacing(10)

        # انتخاب هنرجو (popup)
        lbl_student = QLabel("هنرجو:")
        lbl_student.setProperty("sectionTitle", True)
        layout.addWidget(lbl_student)
        self.student_btn = QPushButton("👤 انتخاب هنرجو")
        self.student_btn.setProperty("variant", "secondary")
        self.student_btn.setCursor(Qt.PointingHandCursor)
        self.student_btn.setToolTip("برای انتخاب هنرجو کلیک کنید")
        self.student_btn.clicked.connect(self.open_student_picker)
        layout.addWidget(self.student_btn)

        # انتخاب کلاس (popup، بعد از انتخاب هنرجو)
        lbl_class = QLabel("کلاس:")
        lbl_class.setProperty("sectionTitle", True)
        layout.addWidget(lbl_class)
        self.class_btn = QPushButton("📚 انتخاب کلاس")
        self.class_btn.setProperty("variant", "secondary")
        self.class_btn.setCursor(Qt.PointingHandCursor)
        self.class_btn.setToolTip("ابتدا هنرجو را انتخاب کنید")
        self.class_btn.setEnabled(False)
        self.class_btn.clicked.connect(self.open_class_picker)
        layout.addWidget(self.class_btn)

        # تاریخ شروع ترم
        self.date_btn = QPushButton("📅 انتخاب تاریخ شروع ترم")
        self.date_btn.setProperty("variant", "secondary")
        self.date_btn.setCursor(Qt.PointingHandCursor)
        self.date_btn.setToolTip("برای انتخاب تاریخ کلیک کنید")
        self.date_btn.clicked.connect(self.open_date_picker)
        layout.addWidget(self.date_btn)
        self.selected_shamsi_date = None
        self.selected_shamsi_date = self.last_selected_date
        self.date_btn.setText(f"📅 تاریخ شروع ترم: {self.selected_shamsi_date}")

        # ساعت جلسه
        lbl_time = QLabel("ساعت جلسه:")
        lbl_time.setProperty("sectionTitle", True)
        layout.addWidget(lbl_time)
        self.time_session = QTimeEdit()
        self.time_session.setTime(QTime(12, 0))
        self.time_session.timeChanged.connect(self.on_time_changed)
        layout.addWidget(self.time_session)

        # دکمه ثبت‌نام هنرجو (ایجاد ترم)
        self.btn_add_session = QPushButton("➕ ثبت‌نام هنرجو")
        self.btn_add_session.setProperty("variant", "primary")
        self.btn_add_session.clicked.connect(self.add_session_to_class)

        layout.addWidget(self.btn_add_session)

        # دکمه پاک‌سازی فرم
        self.btn_clear = QPushButton("🧹 پاک‌سازی فرم")
        self.btn_clear.setProperty("variant", "ghost")
        self.btn_clear.clicked.connect(self.clear_form)
        layout.addWidget(self.btn_clear)

        # دکمه پاکسازی ترم پایان یافته
        self.btn_notify_expired = QPushButton("📣 نمایش ترم‌های پایان‌یافته (بدون حذف)")
        self.btn_notify_expired.setProperty("variant", "secondary")
        self.btn_notify_expired.clicked.connect(self.show_finished_terms)
        layout.addWidget(self.btn_notify_expired)

        # Enrollments list (Model-B: ثبت‌نام‌های فعال این کلاس)
        lbl_sessions = QLabel("ثبت‌نام‌های این کلاس (برای ویرایش/حذف دوبار کلیک کنید):")
        lbl_sessions.setProperty("sectionTitle", True)
        layout.addWidget(lbl_sessions)
        # نمایشِ ترم‌های تمام‌شده هم — تا بتوان شهریه/قیمت‌گذاریِ آن‌ها را هم ویرایش کرد
        self.chk_show_finished = QCheckBox("نمایش ترم‌های تمام‌شده (برای ویرایش شهریه)")
        self.chk_show_finished.toggled.connect(self.load_sessions)
        layout.addWidget(self.chk_show_finished)
        self.list_sessions = QListWidget()
        self.list_sessions.setSortingEnabled(False) # Qt خودش با متن سورت نکند
        self.list_sessions.itemDoubleClicked.connect(self.edit_or_delete_session)
        layout.addWidget(self.list_sessions)

        # Apply theme/QSS to new widgets
        for w in (self.date_btn, self.btn_add_session, self.btn_clear, self.btn_notify_expired,
                  self.student_btn, self.class_btn, self.list_sessions, self.chk_show_finished,
                  lbl_student, lbl_class, lbl_time, lbl_sessions):
            try:
                ThemeManager.repolish(w)
            except Exception:
                pass
        self.load_students()

        self.check_and_notify_term_ends()
        self.showMaximized()

    def refresh_session_counts(self):
        try:
            # Model-B: شمارشِ ترم‌های فعالِ هر هنرجو (نه جلسات) برای نمایش در پنجرهٔ انتخاب
            self.session_counts_by_student = get_active_term_count_per_student() or {}
        except Exception:
            self.session_counts_by_student = {}

    def check_and_notify_term_ends(self):
        """اعلانِ خودکارِ ترم‌های تازه‌پایان‌یافته هنگام باز شدنِ پنجره — هر ترم فقط یک‌بار."""
        expired = get_unnotified_expired_terms()
        if not expired:
            return
        QMessageBox.information(self, "پایان ترم‌ها", self._format_finished_terms(expired))
        # ثبت به‌عنوان «اطلاع‌داده‌شده» تا با هر بار بازکردنِ پنجره دوباره اعلام نشوند
        to_mark = [(r[6], r[0], r[1], r[7], r[8]) for r in expired]  # (term_id, student_id, class_id, date, time)
        mark_terms_as_notified(to_mark)

    def show_finished_terms(self):
        """دکمهٔ «نمایش ترم‌های پایان‌یافته (بدون حذف)»: ترم‌های پایان‌یافتهٔ پاک‌نشده را در یک دیالوگِ
        اسکرول‌شونده نشان می‌دهد؛ دکمهٔ «پاک‌کردن فهرست» در بالا آن‌ها را فقط از نما پنهان می‌کند."""
        finished = get_visible_finished_terms()
        if not finished:
            QMessageBox.information(self, "ترم‌های پایان‌یافته", "در حال حاضر ترمِ پایان‌یافته‌ای برای نمایش وجود ندارد.")
            return
        dlg = FinishedTermsDialog(self, finished)
        dlg.exec_()
        if dlg.cleared:
            dismiss_finished_terms([r[6] for r in finished])  # r[6] = term_id
            QMessageBox.information(self, "انجام شد",
                "فهرست ترم‌های پایان‌یافته پاک شد. (ترم‌ها و سابقهٔ آن‌ها حذف نشده‌اند.)")
        elif dlg.dismissed_term_ids:
            dismiss_finished_terms(dlg.dismissed_term_ids)
            QMessageBox.information(self, "انجام شد",
                f"{fa_digits(len(dlg.dismissed_term_ids))} مورد از فهرست حذف شد. "
                "(ترم‌ها و سابقهٔ آن‌ها حذف نشده‌اند.)")

    def _format_finished_terms(self, rows):
        message = "هنرجویان زیر ترم‌شان به پایان رسیده است :\n"
        for student_id, class_id, student_name, national_code, class_name, day, term_id, session_date, session_time in rows:
            message += f"\n• {student_name} | کدملی: {national_code} | {class_name} ({day}) — {session_date} ساعت {session_time}"
        return message

    def open_student_picker(self):
        """باز کردن popup انتخاب هنرجو؛ بعد از تأیید، هنرجو در ویجت نمایش داده می‌شود."""
        dlg = StudentPickerPopup(self, students_data=self.students_data, session_counts=self.session_counts_by_student)
        if dlg.exec_() == QDialog.Accepted:
            result = dlg.get_selected_student()
            if result:
                sid, name, teacher = result
                self.selected_student_id = sid
                self.selected_student_teacher_name = teacher
                self.class_btn.setEnabled(True)
                self.student_btn.setText(f"👤 {name} — استاد: {teacher}")
                self.selected_class_id = None
                self.class_btn.setText("📚 انتخاب کلاس")
                self.list_sessions.clear()

    def open_class_picker(self):
        """باز کردن popup انتخاب کلاس؛ بعد از تأیید، کلاس در ویجت نمایش داده می‌شود."""
        if not self.selected_student_id:
            return
        dlg = ClassPickerPopup(self, student_id=self.selected_student_id)
        if dlg.exec_() == QDialog.Accepted:
            cid = dlg.get_selected_class_id()
            if cid is not None:
                self.selected_class_id = cid
                try:
                    cls = get_class_by_id(cid)
                    if cls:
                        _name, _tid, instrument, day_str, start_time, end_time, room = cls
                        display = f"{_name}"
                        if day_str:
                            display += f" — {day_str}"
                        if start_time:
                            display += f" {start_time}"
                        self.class_btn.setText(f"📚 {display}")
                    else:
                        self.class_btn.setText(f"📚 کلاس #{cid}")
                except Exception:
                    self.class_btn.setText(f"📚 کلاس #{cid}")
                # تنظیم ساعت و بارگذاری جلسات
                class_day, class_start_time = get_day_and_time_for_class(self.selected_class_id)
                if class_start_time:
                    try:
                        self.time_session.setTime(QTime.fromString(class_start_time, "HH:mm"))
                    except Exception:
                        pass
                elif self.last_time_per_class.get(self.selected_class_id):
                    self.time_session.setTime(self.last_time_per_class[self.selected_class_id])
                else:
                    self.time_session.setTime(QTime(12, 0))
                self.load_sessions()

    def clear_form(self):
        """Reset date/time and editing state; reset student/class selection and buttons."""
        self.selected_student_id = None
        self.selected_student_teacher_name = None
        self.selected_class_id = None
        self.student_btn.setText("👤 انتخاب هنرجو")
        self.class_btn.setText("📚 انتخاب کلاس")
        self.class_btn.setEnabled(False)
        self.selected_shamsi_date = self.last_selected_date
        self.date_btn.setText(f"📅 تاریخ شروع ترم: {self.selected_shamsi_date}")
        self.is_editing = False
        self.btn_add_session.setText("➕ ثبت‌نام هنرجو")
        self.selected_session_id = None
        self.list_sessions.clear()
        self.time_session.setTime(QTime(12, 0))
        self.last_selected_time = None

    def on_time_changed(self):
        """Remember the time when user changes it"""
        if self.selected_class_id:
            self.last_selected_time = self.time_session.time()
            self.last_time_per_class[self.selected_class_id] = self.last_selected_time
            # Reset the global last_selected_time so it doesn't override class start times
            self.last_selected_time = None

    def load_students(self):
        """بارگذاری لیست هنرجویان برای استفاده در popup انتخاب هنرجو."""
        rows = fetch_students_with_teachers()  # [(sid, national_code, name, teacher), ...]
        self.students_data = sort_records_fa(rows, name_index=2, tiebreak_index=1)
    def add_session_to_class(self):
        # بررسی انتخاب هنرجو و کلاس
        if not self.selected_class_id or not self.selected_student_id:
            QMessageBox.warning(self, "خطا", "لطفاً هنرجو و کلاس را انتخاب کنید.")
            return

        # استفاده از تاریخ شمسی انتخاب‌شده
        if not self.selected_shamsi_date:
            QMessageBox.warning(self, "خطا", "لطفاً تاریخ جلسه (شمسی) را انتخاب کنید.")
            return

        date = self.selected_shamsi_date
        time = self.time_session.time().toString("HH:mm")

        class_day, class_start_time = get_day_and_time_for_class(self.selected_class_id)
        session_time = self.time_session.time().toString("HH:mm")

        # --- دریافت پیکربندی ترم از کاربر ---
        cfg = {}
        dlg = TermConfigDialog(self)
        if dlg.exec_() == QDialog.Accepted:
            cfg = dlg.get_config()  # dict: sessions_limit, tuition_fee, currency_unit, profile_id
        else:
            return  # کاربر لغو کرد
        

        # بررسی اینکه ساعت جلسه قبل از شروع کلاس نباشد
        if class_start_time:
            try:
                class_start_qtime = QTime.fromString(class_start_time, "HH:mm")
                session_qtime = self.time_session.time()
                if session_qtime < class_start_qtime:
                    QMessageBox.warning(self, "خطا", "ساعت شروع جلسه نمی‌تواند قبل از شروع کلاس مربوطه باشد.")
                    return
            except:
                pass  # اگر فرمت زمان مشکل داشت، ادامه بده

        # Model-B: هر هنرجو در هر کلاس فقط یک ترم فعال دارد — از ثبت‌نام تکراری جلوگیری کن
        if get_term_id_by_student_and_class(self.selected_student_id, self.selected_class_id):
            QMessageBox.warning(self, "ثبت‌نام تکراری",
                "این هنرجو از قبل در این کلاس ترم فعال دارد. "
                "برای تغییر، ابتدا ثبت‌نام فعلی را (با دوبار کلیک در فهرست پایین) حذف کنید.")
            return

        # Model-B: تاریخ شروع را به روزِ هفتگیِ کلاس بچسبان تا جلسات هفتگی روی روزِ کلاس بیفتند
        if class_day:
            date = first_on_or_after(self.selected_shamsi_date, class_day)

        # Model-B ثبت‌نام: ساخت ترم (بدون رکوردِ جلسه؛ جلسات هفتگی از روی برنامه محاسبه می‌شوند).
        # تداخل‌های هنرجو/استاد و قاعدهٔ «یک ترم فعال» داخل enroll() بررسی می‌شوند و دلیلِ دقیق برمی‌گردد.
        start_time = self.time_session.time().toString("HH:mm")
        result = enroll(
            self.selected_student_id,
            self.selected_class_id,
            date,
            start_time,
            sessions_limit = cfg.get("sessions_limit"),
            tuition_fee    = cfg.get("tuition_fee"),
            currency_unit  = cfg.get("currency_unit"),
            profile_id     = cfg.get("profile_id"),
            lesson_duration= cfg.get("lesson_duration"),
        )

        if not result.ok:
            if result.status == EnrollmentStatus.BEFORE_PREVIOUS_END:
                last_term_end_date = get_last_term_end_date(self.selected_student_id, self.selected_class_id)
                QMessageBox.warning(self, "عدم امکان ثبت‌نام",
                    f"ترم قبلی هنرجو در این کلاس در تاریخ {last_term_end_date} به پایان رسیده است.\n"
                    f"امکان ثبت‌نام جدید از تاریخ {last_term_end_date} به بعد وجود دارد.")
            elif result.status == EnrollmentStatus.DUPLICATE_ACTIVE:
                QMessageBox.warning(self, "عدم امکان ثبت‌نام",
                    "این هنرجو از قبل ترم فعالی در این کلاس دارد.")
            elif result.status == EnrollmentStatus.TEACHER_CONFLICT:
                QMessageBox.warning(self, "تداخل زمانی",
                    "این زمان با برنامهٔ هفتگیِ استادِ این کلاس تداخل دارد.")
            elif result.status == EnrollmentStatus.STUDENT_CONFLICT:
                QMessageBox.warning(self, "تداخل زمانی",
                    "این زمان با یکی دیگر از ترم‌های فعالِ همین هنرجو تداخل دارد.")
            else:
                QMessageBox.warning(self, "عدم امکان ثبت‌نام", "ثبت‌نام ممکن نبود.")
            return

        self.selected_term_id = result.term_id

        QMessageBox.information(self, "موفق",
            f"ثبت‌نام هنرجو با شروع از {date} ساعت {start_time} انجام شد.")
        self.last_selected_time = self.time_session.time()
        self.last_time_per_class[self.selected_class_id] = self.last_selected_time
        self.refresh_session_counts()
        self.load_students()
        self.load_sessions()
        self.update_class_list()
        self.update_summary_bar()
        self.last_selected_date = self.selected_shamsi_date

    def load_sessions(self):
        """Model-B: نمایش ثبت‌نام‌های این کلاس (ترم‌ها) با نام هنرجو، ساعت و مدت جلسه.

        به‌طورِ پیش‌فرض فقط ترم‌های فعال؛ با تیکِ «نمایش ترم‌های تمام‌شده» ترم‌های
        پایان‌یافته هم (با نشانِ ✓ تمام‌شده) نمایش داده می‌شوند تا شهریه‌شان قابلِ ویرایش باشد.
        """
        self.list_sessions.setSortingEnabled(False)
        self.list_sessions.clear()
        if not self.selected_class_id:
            return
        include_completed = self.chk_show_finished.isChecked()
        try:
            rows = fetch_enrollments_for_class(self.selected_class_id, include_completed=include_completed)
        except Exception as e:
            QMessageBox.warning(self, "خطا", f"خطا در بارگذاری ثبت‌نام‌های این کلاس:\n{e}")
            return
        for (term_id, student_id, name, start_date, start_time, dur, limit, held, end_date) in rows:
            dur_label = "یک‌ساعته" if int(dur or 30) >= 60 else "۳۰ دقیقه"
            text = (f"{start_time} — {name} — {fa_digits(held)}/{fa_digits(limit)} جلسه "
                    f"({dur_label}، شروع {start_date})")
            if end_date:
                text = f"✓ تمام‌شده — {text}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, term_id)
            item.setData(Qt.UserRole + 1, student_id)
            item.setData(Qt.UserRole + 2, start_time)
            item.setData(Qt.UserRole + 3, int(dur or 30))
            item.setData(Qt.UserRole + 4, name)
            item.setData(Qt.UserRole + 5, end_date)  # ترمِ تمام‌شده؟ (برای منطقِ ویرایش)
            item.setData(Qt.UserRole + 6, start_date)  # برای پیش‌پرکردن/مقایسهٔ تاریخِ شروع در ویرایش
            if end_date:
                item.setForeground(QColor("#8A8A8A"))  # کم‌رنگ‌تر برای تمایزِ ترم تمام‌شده
            self.list_sessions.addItem(item)

    def edit_or_delete_session(self, item):
        """Model-B: دوبار کلیک روی یک ثبت‌نام → دیالوگ ویرایشِ ساعت/مدت یا حذف.

        ویرایش ساعت روی همان ترم انجام می‌شود (بدون حذف و ثبت دوباره)، پس سابقهٔ
        پرداخت/حضور حفظ می‌شود. حذف مثل قبل فقط برای ترمِ بدون سابقه مجاز است.
        """
        term_id = item.data(Qt.UserRole)
        student_id = item.data(Qt.UserRole + 1)
        cur_time = item.data(Qt.UserRole + 2)
        cur_dur = item.data(Qt.UserRole + 3)
        name = item.data(Qt.UserRole + 4)
        is_finished = bool(item.data(Qt.UserRole + 5))
        cur_start_date = item.data(Qt.UserRole + 6)
        if term_id is None or student_id is None:
            return

        class_day, class_start_time = get_day_and_time_for_class(self.selected_class_id)
        pricing = get_term_pricing(term_id)  # (sessions_limit, tuition_fee, currency_unit, profile_id) یا None
        cur_sl, cur_fee, _cur_unit, cur_pid = pricing if pricing else (None, None, None, None)
        dlg = EditEnrollmentDialog(self, name, class_start_time, cur_time, cur_dur,
                                   current_sessions=cur_sl, current_fee_toman=cur_fee, current_profile_id=cur_pid,
                                   current_start_date=cur_start_date)
        if dlg.exec_() != QDialog.Accepted:
            return

        if dlg.action == EditEnrollmentDialog.SAVE:
            # ۱) ساعت/مدت/تاریخِ شروع — فقط اگر واقعاً تغییر کرده باشد بررسیِ تداخل و reschedule انجام شود.
            # این‌طوری ویرایشِ فقط‌شهریه (به‌ویژه روی ترمِ تمام‌شده) با تداخلِ یک ترمِ فعالِ
            # بعدی مسدود نمی‌شود. تاریخِ شروع روی روزِ کلاس snap می‌شود (مثل ثبت‌نام).
            _new_qt = QTime.fromString(str(dlg.new_time), "HH:mm")
            _cur_qt = QTime.fromString(str(cur_time), "HH:mm")
            time_changed = _new_qt.isValid() and _cur_qt.isValid() and _new_qt != _cur_qt
            dur_changed = int(dlg.new_duration) != int(cur_dur or 30)
            snapped_start = first_on_or_after(dlg.new_start_date, class_day) if dlg.new_start_date else None
            date_changed = snapped_start is not None and snapped_start != cur_start_date
            if time_changed or dur_changed or date_changed:
                result = reschedule(term_id, dlg.new_time, dlg.new_duration,
                                    new_start_date=snapped_start if date_changed else None)
                if not result.ok:
                    if result.status == EnrollmentStatus.TEACHER_CONFLICT:
                        QMessageBox.warning(self, "تداخل زمانی",
                            "این ساعت با برنامهٔ هفتگیِ استادِ این کلاس تداخل دارد.")
                    elif result.status == EnrollmentStatus.STUDENT_CONFLICT:
                        QMessageBox.warning(self, "تداخل زمانی",
                            "این ساعت با یکی دیگر از ترم‌های فعالِ همین هنرجو تداخل دارد.")
                    else:
                        QMessageBox.warning(self, "خطا", "ثبت‌نام برای ویرایش پیدا نشد.")
                    return
            # ۲) قیمت‌گذاری (همیشه قابلِ ویرایش — حتی با وجودِ سابقهٔ پرداخت/حضور یا ترمِ تمام‌شده)
            pr = dlg.get_pricing()
            if pr.get("profile_id") is not None:
                apply_profile_to_term(term_id, pr["profile_id"])
            else:
                set_term_config(term_id, sessions_limit=pr["sessions_limit"],
                                tuition_fee=pr["tuition_fee"], currency_unit=pr["currency_unit"], profile_id=None)
            # ۳) تغییرِ سقفِ جلسات می‌تواند وضعیتِ تکمیل را عوض کند (دوطرفه):
            # بالابردنِ سقف روی ترمِ تمام‌شده آن را دوباره فعال می‌کند، پایین‌آوردن آن را می‌بندد.
            refresh_completion(term_id)
            QMessageBox.information(self, "موفق", "ثبت‌نام به‌روزرسانی شد.")
        elif dlg.action == EditEnrollmentDialog.DELETE:
            reply = QMessageBox.question(self, "حذف ثبت‌نام", "آیا این ثبت‌نام (ترم) حذف شود؟",
                                         QMessageBox.Yes | QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
            has_history = not delete_term_if_no_history(student_id, self.selected_class_id, term_id)
            if has_history:
                QMessageBox.warning(self, "حذف ممکن نیست",
                                    "برای ترم این هنرجو سابقه (پرداخت یا حضور و غیاب) ثبت شده است. "
                                    "ترمی که سابقه دارد حذف نمی‌شود؛ در صورت نیاز ساعت آن را ویرایش کنید.")
                return
            QMessageBox.information(self, "موفق", "ثبت‌نام با موفقیت حذف شد.")
        else:
            return

        self.refresh_session_counts()
        self.load_students()
        self.load_sessions()
        self.update_class_list()
        self.update_summary_bar()

    def open_date_picker(self):
        dlg = ShamsiDatePopup(initial_date=self.selected_shamsi_date)
        if dlg.exec_() == QDialog.Accepted:
            self.selected_shamsi_date = dlg.get_selected_date()
            self.last_selected_date = self.selected_shamsi_date
            self.date_btn.setText(f"📅 {self.selected_shamsi_date}")

    def update_class_list(self):
        """بروزرسانی شمارش جلسات برای نمایش در popupها"""
        self.refresh_session_counts()

    def update_summary_bar(self):
     """در صورت وجود نوار وضعیت، اطلاعات جلسات یا ترم‌ها را بروزرسانی می‌کند"""
    # فرض: self.statusBar یا یک QLabel دارید، آنجا اطلاعات جدید قرار می‌گیرد
    pass  # اگر وجود ندارد، لازم نیست چیزی بنویسی

