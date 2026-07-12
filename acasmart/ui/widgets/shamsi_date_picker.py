from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QHBoxLayout
)
from PySide6.QtCore import QDate, Qt, Signal

from acasmart.ui.widgets.shamsi_date_popup import ShamsiDatePopup
from acasmart.ui.widgets.theme_manager import ThemeManager
import jdatetime
from datetime import date
class ShamsiDatePicker(QWidget):
    """
    ویجت ساده انتخاب تاریخ شمسی برای فرم‌ها.
    دکمه‌ای دارد که با کلیک روی آن پنجره popup باز می‌شود.
    تاریخ‌ها در پس‌زمینه به فرمت شمسی و میلادی ذخیره می‌شوند.
    """

    # سیگنالی که هنگام تغییر واقعی تاریخ (نه صرفِ باز شدن تقویم) صادر می‌شود
    dateChanged = Signal()

    def __init__(self, label_text=""):
        super().__init__()

        # چیدمان افقی: لیبل + دکمه انتخاب تاریخ
        self.layout = QHBoxLayout()
        self.label = QLabel(label_text)
        self.button = QPushButton("📅 انتخاب تاریخ")
        # بهتر: رفتار و استایل دکمه تاریخ مثل سایر دکمه‌های ثانویه
        self.button.setProperty("variant", "secondary")
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.setToolTip("برای انتخاب تاریخ کلیک کنید")

        # تاریخ پیش‌فرض: امروز (هم میلادی هم شمسی)
        self.selected_gregorian = QDate.currentDate()
        self.selected_shamsi = jdatetime.date.today().strftime("%Y-%m-%d")
        # آیا کاربر تاریخی انتخاب کرده است؟ (برای حالتِ «بدون تاریخ» در فیلترها)
        self._has_date = True
        # اتصال دکمه به باز شدن popup
        self.button.clicked.connect(self.open_calendar)

        self.layout.addWidget(self.label)
        self.layout.addWidget(self.button)
        self.setLayout(self.layout)

        # اعمال QSS بعد از setProperty
        try:
            ThemeManager.repolish(self.button)
        except Exception:
            pass

    def open_calendar(self):
        """
        باز کردن پنجره انتخاب تاریخ و دریافت خروجی پس از تایید
        """

        popup = ShamsiDatePopup(self, initial_date=self.selected_shamsi)
        if popup.exec_():
            self.selected_shamsi = popup.get_selected_date()
            self.selected_gregorian = popup.calendar.selectedDate()
            self.button.setText(self.selected_shamsi)
            self._has_date = True
            self.dateChanged.emit()

    def get_miladi_str(self):
        """
                خروجی تاریخ میلادی به فرمت متنی (yyyy-mm-dd)
        """

        return self.selected_gregorian.toString("yyyy-MM-dd")

    def has_date(self) -> bool:
        """آیا تاریخی انتخاب شده است؟ (پس از clear() تا انتخاب بعدی نادرست است)"""
        return self._has_date

    def clear(self):
        """پاک کردن انتخاب تاریخ؛ دکمه به حالتِ راهنما برمی‌گردد و فیلتر بدون قیدِ تاریخ می‌شود."""
        self._has_date = False
        self.selected_gregorian = QDate.currentDate()
        self.selected_shamsi = jdatetime.date.today().strftime("%Y-%m-%d")
        self.button.setText("📅 انتخاب تاریخ")
        self.dateChanged.emit()

    def set_to_today(self):
        """
                تنظیم تاریخ روی امروز (هم برای میلادی و هم برای شمسی)
        """

        self.selected_gregorian = QDate.currentDate()
        self.selected_shamsi = jdatetime.date.today().strftime("%Y-%m-%d")
        self.button.setText("📅 انتخاب تاریخ")
        self._has_date = True
        self.dateChanged.emit()

    def setDate(self, qdate: QDate):
        """
        تنظیم تاریخ به صورت میلادی، و آپدیت تاریخ شمسی و متن دکمه.
        """
        self.selected_gregorian = qdate
        g_date = date(qdate.year(), qdate.month(), qdate.day())
        self.selected_shamsi = jdatetime.date.fromgregorian(date=g_date).strftime("%Y-%m-%d")
        self.button.setText(self.selected_shamsi)
        self._has_date = True
        self.dateChanged.emit()
