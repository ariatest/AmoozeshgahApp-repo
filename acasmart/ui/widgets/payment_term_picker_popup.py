"""
پنجرهٔ انتخاب ترم برای بخش پرداخت.
ترم‌های هنرجو در کلاس انتخاب‌شده با وضعیت پرداخت.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QShortcut, QKeySequence

from acasmart.data.repos.payments_repo import get_terms_for_payment_management
from acasmart.core.utils import format_currency_with_unit
from acasmart.ui.widgets.theme_manager import ThemeManager


class PaymentTermPickerPopup(QDialog):
    """انتخاب ترم برای ثبت پرداخت — ترم‌های هنرجو در کلاس انتخاب‌شده."""

    def __init__(self, parent=None, student_id=None, class_id=None):
        super().__init__(parent)
        self.setWindowTitle("انتخاب ترم")
        self.setMinimumSize(480, 420)
        self.resize(520, 460)
        self.setLayout(QVBoxLayout())

        self.student_id = student_id
        self.class_id = class_id
        self._selected_term_id = None
        self._selected_term_display = None

        lbl = QLabel("انتخاب ترم (ترم‌های هنرجو در این کلاس):")
        lbl.setProperty("sectionTitle", True)
        self.layout().addWidget(lbl)

        self.list_terms = QListWidget()
        self.list_terms.setObjectName("PaymentTermList")
        self.list_terms.itemClicked.connect(self._on_item_clicked)
        self.list_terms.itemDoubleClicked.connect(self._confirm)  # دوبار کلیک = انتخاب
        self.layout().addWidget(self.list_terms)

        btn_ok = QPushButton("تأیید")
        btn_ok.setProperty("variant", "primary")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self._confirm)
        self.layout().addWidget(btn_ok)

        try:
            ThemeManager.repolish(btn_ok)
            ThemeManager.repolish(self.list_terms)
        except Exception:
            pass

        QShortcut(QKeySequence(Qt.Key_Return), self).activated.connect(self._confirm)
        QShortcut(QKeySequence(Qt.Key_Enter), self).activated.connect(self._confirm)

        self._build_term_list()

    def _build_term_list(self):
        self.list_terms.clear()
        if not (self.student_id and self.class_id):
            item = QListWidgetItem("هنرجو و کلاس را انتخاب کنید")
            item.setData(Qt.UserRole, None)
            self.list_terms.addItem(item)
            return
        terms = get_terms_for_payment_management(self.student_id, self.class_id)
        if not terms:
            item = QListWidgetItem("هیچ ترمی یافت نشد")
            item.setData(Qt.UserRole, None)
            self.list_terms.addItem(item)
            return
        for term in terms:
            term_id = term["term_id"]
            start_date = term["start_date"]
            end_date = term["end_date"]
            term_status = term["term_status"]
            total_paid = term["total_paid"]
            debt = term["debt"]
            display_text = f"ترم {start_date}"
            if end_date:
                display_text += f" تا {end_date}"
            display_text += f" - {term_status}"
            if debt == 0:
                payment_status = "تسویه شده"
            elif debt > 0:
                payment_status = f"بدهکار: {format_currency_with_unit(debt)}"
            else:
                payment_status = "خطا"
            display_text += f" - {payment_status}"
            if total_paid > 0:
                display_text += f" (پرداخت: {format_currency_with_unit(total_paid)})"
            item = QListWidgetItem(display_text)
            item.setData(Qt.UserRole, term_id)
            self.list_terms.addItem(item)

    def _on_item_clicked(self, item):
        self._current_item = item

    def _confirm(self):
        current = self.list_terms.currentItem()
        if not current:
            return
        term_id = current.data(Qt.UserRole)
        if term_id is not None:
            self._selected_term_id = term_id
            self._selected_term_display = current.text()
            self.accept()

    def get_selected_term_id(self):
        return self._selected_term_id

    def get_selected_term_display(self):
        return self._selected_term_display or ""
