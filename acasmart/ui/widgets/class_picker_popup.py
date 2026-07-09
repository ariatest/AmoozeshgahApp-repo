"""
پنجرهٔ انتخاب کلاس به صورت popup (مشابه ShamsiDatePopup).
لیست کلاس‌های هنرجو + جستجو + دکمهٔ تأیید؛ بعد از تأیید کلاس انتخاب‌شده برمی‌گردد.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton,
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QShortcut, QKeySequence

from acasmart.data.repos.classes_repo import get_class_by_id
from acasmart.data.repos.students_repo import fetch_classes_for_student
from acasmart.data.repos.terms_repo import get_active_term_count_per_class
from acasmart.ui.widgets.theme_manager import ThemeManager


DAY_COLORS = {
    "شنبه": "#ADD8E6",
    "یکشنبه": "#FFD580",
    "دوشنبه": "#E6E6FA",
    "سه‌شنبه": "#FFFACD",
    "چهارشنبه": "#FFC0CB",
    "پنجشنبه": "#D3D3D3",
    "جمعه": "#F5DEB3",
}
WEEK_ORDER = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه"]


class ClassPickerPopup(QDialog):
    def __init__(self, parent=None, student_id=None):
        super().__init__(parent)
        self.setWindowTitle("انتخاب کلاس")
        self.setMinimumSize(520, 480)
        self.resize(560, 520)
        self.setLayout(QVBoxLayout())

        self.student_id = student_id
        self._selected_class_id = None
        self._classes_data = []  # list of (cid, cname, teacher_name, day) for filter

        lbl = QLabel("انتخاب کلاس مرتبط:")
        lbl.setProperty("sectionTitle", True)
        self.layout().addWidget(lbl)

        self.input_filter = QLineEdit()
        self.input_filter.setPlaceholderText("جستجو بین کلاس‌ها...")
        self.input_filter.textChanged.connect(self._filter_list)
        self.layout().addWidget(self.input_filter)

        self.list_classes = QListWidget()
        self.list_classes.setObjectName("ClassList")
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
        self._classes_data = []
        if not self.student_id:
            return
        classes = fetch_classes_for_student(self.student_id)
        session_counts = get_active_term_count_per_class() or {}
        classes.sort(key=lambda x: WEEK_ORDER.index(x[3]) if x[3] in WEEK_ORDER else 7)
        self._classes_data = classes

        for cid, cname, teacher_name, day in classes:
            count = session_counts.get(cid, 0)
            try:
                cls = get_class_by_id(cid)
                if cls:
                    _name, _tid, instrument, day_str, start_time, end_time, room = cls
                else:
                    instrument, day_str, start_time, end_time, room = "", day, None, None, ""
            except Exception:
                instrument, day_str, start_time, end_time, room = "", day, None, None, ""

            main_text = f"<b>{cname}</b> - {teacher_name}"
            if instrument:
                main_text += f" - {instrument}"
            time_part = ""
            if start_time and end_time:
                time_part = f"{start_time} - {end_time}"
            elif start_time:
                time_part = f"شروع {start_time}"
            room_part = f" | اتاق: {room}" if room else ""
            detail_text = f"<span>{day_str} {time_part}{room_part} | {count} ترم فعال</span>"

            label = QLabel(f"{main_text}<br>{detail_text}")
            label.setTextFormat(Qt.RichText)
            label.setObjectName("ClassItem")
            label.setWordWrap(True)
            label.setFixedHeight(60)

            try:
                t = ThemeManager.tokens()
                bg = t.get("dayColors", {}).get(day_str or day, t["surface"])
                root_decl = (
                    f"padding: 10px 14px;"
                    f" background: {bg};"
                    f" border: 1px solid {t['border']};"
                    f" border-radius: {t['radius']};"
                )
                child_rules = f"""
                    QLabel#ClassItem b {{ font-size: 13px; color: {t['text']}; }}
                    QLabel#ClassItem span {{ font-size: 11px; color: {t['text']}; opacity: .85; display: block; margin-top: 4px; line-height: 1.4; }}
                """
                base_style = root_decl + child_rules
            except Exception:
                bg = DAY_COLORS.get(day_str or day, "#FFFFFF")
                root_decl = (
                    f"padding: 10px 14px; background: {bg}; border: 1px solid #ccc; border-radius: 10px;"
                )
                child_rules = """
                    QLabel#ClassItem b { font-size: 13px; color: #0B1F3A; }
                    QLabel#ClassItem span { font-size: 11px; color: #0B1F3A; opacity: .85; display: block; margin-top: 4px; line-height: 1.4; }
                """
                base_style = root_decl + child_rules

            label.setStyleSheet(base_style)
            label.setProperty("baseStyle", base_style)
            label.setAttribute(Qt.WA_TransparentForMouseEvents)

            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 70))
            item.setData(Qt.UserRole, cid)
            item.setData(Qt.UserRole + 1, f"{cname} {teacher_name} {day}")  # for text filter
            item.setBackground(Qt.transparent)
            self.list_classes.addItem(item)
            self.list_classes.setItemWidget(item, label)

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
        if self._selected_class_id is not None:
            self.accept()

    def get_selected_class_id(self):
        return self._selected_class_id
