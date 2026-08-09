from __future__ import annotations

from acasmart.data.repos.students_repo import fetch_students, get_student_contact
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
    QCheckBox, QMessageBox, QHBoxLayout, QApplication
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from acasmart.services.sms_notifier import SmsNotifier, SmsStatus
from acasmart.ui.widgets.theme_manager import ThemeManager
from acasmart.ui.widgets.base_secondary_window import BaseSecondaryWindow

class SmsNotificationWindow(BaseSecondaryWindow):
    def __init__(self, return_target: QWidget | None = None):
        super().__init__("📲 ارسال پیامک به هنرجویان", return_target)
        self.setGeometry(300, 200, 500, 600)
        self.students = []
        self.checkboxes = []
        self.notifier = SmsNotifier()
        self.build_ui()

    def build_ui(self):
        layout = self.content_layout()
        layout.setSpacing(8)

        title = QLabel("📨 ارسال پیامک به هنرجویان")
        title.setAlignment(Qt.AlignCenter)
        title.setProperty("sectionTitle", True)
        layout.addWidget(title)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 جستجوی هنرجو بر اساس نام...")
        self.search_input.textChanged.connect(self.filter_students)
        layout.addWidget(self.search_input)

        # select_all_btn = QPushButton("✔️ انتخاب همه / لغو همه")
        # select_all_btn.clicked.connect(self.toggle_select_all)
        # select_all_btn.setStyleSheet("padding: 6px;")
        # layout.addWidget(select_all_btn)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(400)
        self.list_container = QWidget()
        self.list_layout = QVBoxLayout()
        self.list_layout.setSpacing(4)
        self.list_container.setLayout(self.list_layout)
        scroll.setWidget(self.list_container)
        layout.addWidget(scroll)

        self.btn_send_sms = QPushButton("📤 ارسال پیامک برای انتخاب‌شده‌ها")
        self.btn_send_sms.setProperty("variant", "primary")
        self.btn_send_sms.clicked.connect(self.send_sms_to_selected)
        layout.addWidget(self.btn_send_sms)
        # Apply QSS
        for w in (self.search_input, self.btn_send_sms, title):
            try:
                ThemeManager.repolish(w)
            except Exception:
                pass
        self.load_students()

    def toggle_select_all(self):
        all_selected = all(cb.isChecked() for cb in self.checkboxes)
        for cb in self.checkboxes:
            cb.setChecked(not all_selected)

    def load_students(self):
        self.students = fetch_students()
        self.refresh_student_list()

    def refresh_student_list(self, filtered=None):
        for i in reversed(range(self.list_layout.count())):
            widget = self.list_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        self.checkboxes.clear()

        data = filtered if filtered is not None else self.students
        for sid, name, gender, birth_date, national_code in data:
            cb = QCheckBox(f"{name} - کدملی: {national_code}")
            cb.setProperty("student_id", sid)
            self.checkboxes.append(cb)
            self.list_layout.addWidget(cb)

    def filter_students(self):
        text = self.search_input.text().strip().lower()
        if not text:
            self.refresh_student_list()
            return
        filtered = [s for s in self.students if text in s[1].lower()]
        self.refresh_student_list(filtered)

    def send_sms_to_selected(self):
        selected = [cb for cb in self.checkboxes if cb.isChecked()]
        if not selected:
            QMessageBox.warning(self, "هیچ انتخابی", "لطفاً حداقل یک هنرجو را انتخاب کنید.")
            return

        # اگر ارسالِ پیامک در تنظیمات خاموش است، همین‌جا شفاف بگو (به‌جای «۰ ارسال شد»)
        if not self.notifier.is_enabled():
            QMessageBox.information(self, "ارسال پیامک غیرفعال است",
                "ارسال پیامک در تنظیماتِ برنامه غیرفعال است. ابتدا آن را فعال کنید.")
            return

        # نکتهٔ حیاتی: تمامِ عملیات درونِ try/finally است تا هیچ استثنائی از این اسلات فرار نکند
        # (فرارِ استثناء از یک اسلاتِ Qt در نسخهٔ بسته‌بندی‌شده باعثِ بسته‌شدن/هنگِ برنامه می‌شود)،
        # و شبکه با timeout فراخوانی می‌شود تا رابطِ کاربری هیچ‌وقت برای همیشه بلاک نشود.
        self.btn_send_sms.setEnabled(False)
        QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
        sent = failed = 0
        try:
            for cb in selected:
                student_id = cb.property("student_id")
                try:
                    name, phone = self.get_student_contact(student_id)
                    if not (name and phone):
                        failed += 1
                        continue
                    result = self.notifier.send_new_term_invitation(name, phone)
                    status = result.get("status") if isinstance(result, dict) else None
                    if status == SmsStatus.SENT:
                        sent += 1
                    else:
                        failed += 1
                except Exception as e:
                    failed += 1
                    self.notifier._log(f"[SMS ERROR] ارسال دستی ناموفق (student_id={student_id}): {e}")
        finally:
            QApplication.restoreOverrideCursor()
            self.btn_send_sms.setEnabled(True)

        msg = f"ارسال پیامک برای {sent} هنرجو انجام شد."
        if failed:
            msg += f"\n{failed} مورد ناموفق بود (برای جزئیات به فایل لاگ مراجعه کنید)."
        QMessageBox.information(self, "پایان عملیات", msg)

    def get_student_contact(self, student_id):
        return get_student_contact(student_id)
