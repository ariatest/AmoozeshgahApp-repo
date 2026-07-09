"""
پنجرهٔ انتخاب هنرجو به صورت popup (مشابه ShamsiDatePopup).
جستجو + لیست نتایج + دکمهٔ تأیید؛ بعد از تأیید هنرجوی انتخاب‌شده برمی‌گردد.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QShortcut, QKeySequence

from acasmart.core.fa_collation import sort_records_fa, contains_fa, nd, fa_digits
from acasmart.ui.widgets.theme_manager import ThemeManager


class StudentPickerPopup(QDialog):
    def __init__(self, parent=None, students_data=None, session_counts=None):
        super().__init__(parent)
        self.setWindowTitle("انتخاب هنرجو")
        self.setMinimumSize(480, 520)
        self.resize(500, 560)
        self.setLayout(QVBoxLayout())

        self.students_data = list(students_data or [])
        self.session_counts = dict(session_counts or {})
        self._selected_student_id = None
        self._selected_name = None
        self._selected_teacher = None

        # برچسب
        lbl = QLabel("جستجوی هنرجو:")
        lbl.setProperty("sectionTitle", True)
        self.layout().addWidget(lbl)

        self.input_search = QLineEdit()
        self.input_search.setPlaceholderText("نام هنرجو، نام استاد یا کد ملی...")
        self.input_search.textChanged.connect(self._search)
        self.layout().addWidget(self.input_search)

        self.list_results = QListWidget()
        self.list_results.setObjectName("StudentList")
        self.list_results.itemClicked.connect(self._on_item_clicked)
        self.list_results.itemDoubleClicked.connect(self._confirm)  # دوبار کلیک = انتخاب
        self.layout().addWidget(self.list_results)

        btn_ok = QPushButton("تأیید")
        btn_ok.setProperty("variant", "primary")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self._confirm)
        self.layout().addWidget(btn_ok)

        try:
            ThemeManager.repolish(btn_ok)
            ThemeManager.repolish(self.list_results)
        except Exception:
            pass

        QShortcut(QKeySequence(Qt.Key_Return), self).activated.connect(self._confirm)
        QShortcut(QKeySequence(Qt.Key_Enter), self).activated.connect(self._confirm)

        self._search()

    def _search(self):
        raw = self.input_search.text().strip()
        q_name = raw
        q_code = nd(raw)
        self.list_results.clear()
        filtered = []
        for sid, national_code, name, teacher in self.students_data:
            if (
                contains_fa(name, q_name)
                or contains_fa(teacher, q_name)
                or (q_code and q_code in nd(national_code))
            ):
                filtered.append((sid, national_code, name, teacher))
        filtered = sort_records_fa(filtered, name_index=2, tiebreak_index=1)
        for sid, national_code, name, teacher in filtered:
            count = self.session_counts.get(sid, 0)
            count_fa = fa_digits(count) or "۰"  # fa_digits(0) returns '' — show ۰ explicitly
            item = QListWidgetItem(f"{name} (استاد: {teacher}) — {count_fa} ترم فعال")
            item.setData(Qt.UserRole, (sid, national_code, name, teacher))
            self.list_results.addItem(item)

    def _on_item_clicked(self, item):
        self._current_item = item

    def _confirm(self):
        current = self.list_results.currentItem()
        if not current:
            return
        data = current.data(Qt.UserRole)
        if data:
            self._selected_student_id, _nc, self._selected_name, self._selected_teacher = data
            self.accept()

    def get_selected_student(self):
        """برگرداند (student_id, name, teacher) یا None"""
        if self._selected_student_id is None:
            return None
        return (self._selected_student_id, self._selected_name, self._selected_teacher)
