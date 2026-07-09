"""
پنجرهٔ انتخاب کلاس برای بخش پرداخت.
فقط کلاس‌هایی که هنرجو در آن‌ها ترم ثبت‌شده دارد (fetch_registered_classes_for_student).
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QShortcut, QKeySequence

from acasmart.data.repos.students_repo import fetch_registered_classes_for_student
from acasmart.ui.widgets.theme_manager import ThemeManager


class PaymentClassPickerPopup(QDialog):
    """انتخاب کلاس برای پرداخت — فقط کلاس‌های ثبت‌شدهٔ هنرجو (دارای ترم)."""

    def __init__(self, parent=None, student_id=None):
        super().__init__(parent)
        self.setWindowTitle("انتخاب کلاس")
        self.setMinimumSize(520, 480)
        self.resize(560, 520)
        self.setLayout(QVBoxLayout())

        self.student_id = student_id
        self._selected_class_id = None
        self._selected_class_display = None

        lbl = QLabel("انتخاب کلاس (کلاس‌هایی که هنرجو در آن‌ها ترم دارد):")
        lbl.setProperty("sectionTitle", True)
        self.layout().addWidget(lbl)

        self.input_filter = QLineEdit()
        self.input_filter.setPlaceholderText("جستجو بین کلاس‌ها...")
        self.input_filter.textChanged.connect(self._filter_list)
        self.layout().addWidget(self.input_filter)

        self.list_classes = QListWidget()
        self.list_classes.setObjectName("PaymentClassList")
        self.list_classes.itemClicked.connect(self._on_item_clicked)
        self.list_classes.itemDoubleClicked.connect(self._confirm)  # دوبار کلیک = انتخاب
        self.layout().addWidget(self.list_classes)

        btn_ok = QPushButton("تأیید")
        btn_ok.setProperty("variant", "primary")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self._confirm)
        self.layout().addWidget(btn_ok)

        try:
            ThemeManager.repolish(btn_ok)
            ThemeManager.repolish(self.list_classes)
        except Exception:
            pass

        QShortcut(QKeySequence(Qt.Key_Return), self).activated.connect(self._confirm)
        QShortcut(QKeySequence(Qt.Key_Enter), self).activated.connect(self._confirm)

        self._build_class_list()

    def _build_class_list(self):
        self.list_classes.clear()
        if not self.student_id:
            return
        student_classes = fetch_registered_classes_for_student(self.student_id)
        for cid, cname, tname, instr, day, start, end, room in student_classes:
            display = f"{cname} ({day} {start}-{end}) - {tname}"
            item = QListWidgetItem(display)
            item.setData(Qt.UserRole, cid)
            item.setData(Qt.UserRole + 1, display.lower())
            self.list_classes.addItem(item)

    def _filter_list(self):
        q = self.input_filter.text().strip().lower()
        for i in range(self.list_classes.count()):
            item = self.list_classes.item(i)
            text = (item.data(Qt.UserRole + 1) or "").lower()
            item.setHidden(bool(q and q not in text))

    def _on_item_clicked(self, item):
        self._current_item = item

    def _confirm(self):
        current = self.list_classes.currentItem()
        if not current:
            return
        self._selected_class_id = current.data(Qt.UserRole)
        self._selected_class_display = current.text()
        if self._selected_class_id is not None:
            self.accept()

    def get_selected_class_id(self):
        return self._selected_class_id

    def get_selected_class_display(self):
        return self._selected_class_display or ""
