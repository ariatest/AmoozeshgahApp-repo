from __future__ import annotations

from acasmart.data.repos.teachers_repo import (
    delete_teacher_by_id,
    fetch_teachers,
    insert_teacher,
    is_teacher_assigned_to_students,
    get_teacher_by_id,
    update_teacher_by_id,
    get_teacher_id_by_national_code,
)
from acasmart.data.repos.students_repo import is_national_code_exists_for_other
from acasmart.data.repos.teacher_instruments_repo import (
    add_instrument_to_teacher,
    remove_instrument_from_teacher,
    get_instruments_for_teacher,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QListWidget, QListWidgetItem, QMessageBox, QFormLayout, QGridLayout, QToolButton,
    QStyle, QComboBox, QDialog
)
from PySide6.QtCore import Qt

from acasmart.ui.widgets.shamsi_date_popup import ShamsiDatePopup
import jdatetime
import re
from acasmart.core.fa_collation import sort_records_fa, contains_fa, fa_collator
from functools import cmp_to_key
from acasmart.ui.widgets.theme_manager import ThemeManager
from acasmart.ui.widgets.base_secondary_window import BaseSecondaryWindow

class TeacherManager(BaseSecondaryWindow):
    def __init__(self, return_target: QWidget | None = None):
        super().__init__("مدیریت اساتید", return_target)
        self.setGeometry(250, 250, 500, 600)


        #layout برای چیدن ویجت‌ها در یک ستون عمودی استفاده می‌شه
        layout = self.content_layout()
        layout.setSpacing(10)

        # اضافه کردن ساز(سازها)
        self.input_instrument = QLineEdit()
        self.input_instrument.setPlaceholderText("نام ساز های تدریس شده توسط این استاد را اضافه کنید")
        
        # دکمه افزودن ساز
        self.btn_add_instrument = QPushButton("➕ افزودن ساز")
        self.btn_add_instrument.clicked.connect(self.add_instrument_to_list)
        self.btn_add_instrument.setProperty("variant", "secondary")

        self.list_instruments = QListWidget()
        self.list_instruments.setMaximumHeight(90)  # فهرست سازها کوتاه بماند تا فضا هدر نرود
        self.list_instruments.itemDoubleClicked.connect(self.remove_instrument_from_list)


        #Input fields for getting teachers name and instrument
        self.input_name = QLineEdit()
        self.input_name.setPlaceholderText("نام و نام خانوادگی استاد")
        self.input_name.textChanged.connect(self.check_form_validity)

        # birthday field
        self.input_birth_date = QLineEdit()
        self.input_birth_date.setPlaceholderText("تاریخ تولد (شمسی)")
        self.input_birth_date.setReadOnly(True)
        calendar_btn = QToolButton()
        calendar_btn.setIcon(self.style().standardIcon(QStyle.SP_DesktopIcon))
        calendar_btn.setCursor(Qt.PointingHandCursor)
        calendar_btn.setStyleSheet("border: none; padding: 0px;")
        calendar_btn.clicked.connect(self.show_calendar_popup)

        self.input_birth_date.setTextMargins(0, 0, 25, 0)
        calendar_btn.setParent(self.input_birth_date)
        calendar_btn.move(self.input_birth_date.rect().right() - 20, (self.input_birth_date.height() - 16) // 2)
        calendar_btn.resize(20, 20)

        # جنسیت
        self.combo_gender = QComboBox()
        self.combo_gender.setPlaceholderText("جنسیت استاد")
        self.combo_gender.addItems(["آقا", "خانم"])
        self.combo_gender.setCurrentIndex(0)
        self.combo_gender.currentIndexChanged.connect(self.check_form_validity)

        # کد ملی
        self.input_national_code = QLineEdit()
        self.input_national_code.setPlaceholderText("کد ملی")
        self.input_national_code.textChanged.connect(self.check_form_validity)

        # کد هنری
        self.input_teaching_card = QLineEdit()
        self.input_teaching_card.setPlaceholderText("شماره کارت تدریس (اختیاری)")
        self.input_teaching_card.textChanged.connect(self.check_form_validity)

        #شماره تلفن
        self.input_phone = QLineEdit()
        self.input_phone.setPlaceholderText("09*********")
        self.input_phone.textChanged.connect(self.check_form_validity)

        #شماره کارت
        self.input_card_number = QLineEdit()
        self.input_card_number.setPlaceholderText("شماره کارت (اختیاری، مثل 1234-5678-9012-3456)")
        self.input_card_number.textChanged.connect(self.check_form_validity)

        # شماره شبا (اختیاری، باید با IR شروع شود و ۲۶ کاراکتر باشد)
        self.input_iban = QLineEdit()
        self.input_iban.setPlaceholderText("شماره شبا (اختیاری، مثل IR123456789012345678901234)")
        self.input_iban.textChanged.connect(self.check_form_validity)

        # Add teacher Button
        self.btn_add = QPushButton("➕ افزودن استاد")
        self.btn_add.clicked.connect(self.add_teacher)
        self.btn_add.setEnabled(False)
        self.btn_add.setFixedHeight(40)
        self.btn_add.setProperty("variant", "primary")
        
        # Update teacher data Button
        self.btn_update = QPushButton("✏ ویرایش استاد ️")
        self.btn_update.clicked.connect(self.update_teacher)
        self.btn_update.setEnabled(False)
        self.btn_update.setFixedHeight(40)
        self.btn_update.setProperty("variant", "secondary")
        
        # Clear form Button
        self.btn_clear = QPushButton("🧹 پاک‌سازی فرم")
        self.btn_clear.clicked.connect(self.clear_form)
        self.btn_clear.setProperty("variant", "ghost")

        #Search teachers form
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("جستجو بر اساس نام یا ساز تدریسی استاد")
        self.search_input.textChanged.connect(self.search_teachers)

        #QListWidget لیست اساتید رو نشون می‌ده
        self.list_teachers = QListWidget()
        # if double clicked, delete teacher data
        self.list_teachers.itemDoubleClicked.connect(self.delete_teacher)
        # if clicked, fill form with data
        self.list_teachers.itemClicked.connect(self.fill_form)

        # label count for teachers
        self.lbl_count = QLabel("تعداد اساتید: ۰ نفر")
        self.lbl_count.setStyleSheet("font-size: 13px; color: gray; margin-top: 5px;")


        # add widgets to layout
        # فرم دو-ستونه تا فضای عمودی کمتری بگیرد و لیست اساتید در پایین جای بیشتری داشته باشد
        form_grid = QGridLayout()
        form_grid.setHorizontalSpacing(16)
        form_grid.setVerticalSpacing(8)

        def _form_pair(r, c, label_text, widget):
            form_grid.addWidget(QLabel(label_text), r, c * 2)
            form_grid.addWidget(widget, r, c * 2 + 1)

        _form_pair(0, 0, ": نام استاد", self.input_name)
        _form_pair(0, 1, ": کد ملی", self.input_national_code)
        _form_pair(1, 0, ": تاریخ تولد", self.input_birth_date)
        _form_pair(1, 1, ": شماره کارت تدریس", self.input_teaching_card)
        _form_pair(2, 0, ": جنسیت", self.combo_gender)
        _form_pair(2, 1, ": شماره تلفن", self.input_phone)
        _form_pair(3, 0, ": شماره کارت بانکی", self.input_card_number)
        _form_pair(3, 1, ": شماره شبا", self.input_iban)
        form_grid.setColumnStretch(1, 1)
        form_grid.setColumnStretch(3, 1)
        layout.addWidget(QLabel("سازها:"))
        layout.addWidget(self.input_instrument)
        layout.addWidget(self.btn_add_instrument)
        layout.addWidget(QLabel("لیست سازهای انتخاب‌شده (برای حذف دوبار کلیک کنید):"))
        layout.addWidget(self.list_instruments)

        layout.addLayout(form_grid)
        button_row = QHBoxLayout()
        button_row.addWidget(self.btn_add)
        button_row.addWidget(self.btn_update)
        layout.addWidget(self.btn_clear)
        layout.addLayout(button_row)# move this if you want to change add and edit location buttons

        layout.addWidget(QLabel("جستجو در لیست اساتید:"))
        layout.addWidget(self.search_input)
        layout.addWidget(QLabel("لیست اساتید (برای حذف دوبار کلیک کنید):"))
        layout.addWidget(self.list_teachers, 1)  # کشیده شود تا فضای بیشتری برای خواندن داشته باشد
        layout.addWidget(self.lbl_count)

        # برای اینکه QSS جدید رو بخونه
        for btn in (self.btn_add, self.btn_update, self.btn_clear, self.btn_add_instrument):
            ThemeManager.repolish(btn)
        self.selected_teacher_id = None # این متغیر ID استاد انتخاب‌شده رو نگه می‌داره,لازمه برای اینکه بدونیم کدوم رکورد باید ویرایش بشه
        self.teachers_data = []
        self.load_teachers()
        self.check_form_validity()
        self.showMaximized()

    def add_teacher(self):
        """Read form, validate, insert teacher and their instruments."""
        name = self.input_name.text().strip()
        national_code = self.input_national_code.text().strip()
        teaching_card = self.input_teaching_card.text().strip() or None
        phone = self.input_phone.text().strip()
        gender = self.combo_gender.currentText()
        birth_date = self.input_birth_date.text().strip()
        card_number = self.input_card_number.text().strip() or None
        iban = self.input_iban.text().strip() or None

        # بررسی تکراری بودن کد ملی
        if is_national_code_exists_for_other("teachers", national_code, -1):
            QMessageBox.warning(self, "خطا", "کد ملی تکراری است.")
            return

        if self.list_instruments.count() == 0:
            QMessageBox.warning(self, "خطا", "لطفاً حداقل یک ساز برای استاد وارد کنید.")
            return
        # بررسی شماره تلفن (در صورت وجود مقدار)
        if not phone or not phone.isdigit() or len(phone) != 11:
            QMessageBox.warning(self, "خطا", "شماره تلفن باید وارد شده، ۱۱ رقمی و فقط عدد باشد.")
            return
        # بررسی 16 رقمی بودن شماره کارت
        if card_number and not re.match(r"^\d{4}-\d{4}-\d{4}-\d{4}$", card_number):
            QMessageBox.warning(self, "خطا", "شماره کارت نامعتبر است. باید ۱۶ رقم با خط تیره باشد.")
            return
        # بررسی اینکه شماره شبا 26 کاراکتر باشد و با ir آغاز شود
        if iban and (not iban.startswith("IR") or len(iban) != 26):
            QMessageBox.warning(self, "خطا", "شماره شبا باید با 'IR' شروع شود و دقیقاً ۲۶ کاراکتر باشد.")
            return

        # ذخیره استاد
        insert_teacher(name, national_code, teaching_card, gender, phone, birth_date, card_number, iban)

        # گرفتن آیدی استاد جدید
        teacher_id = get_teacher_id_by_national_code(national_code)

        # ذخیره سازها
        for i in range(self.list_instruments.count()):
            instrument = self.list_instruments.item(i).text()
            add_instrument_to_teacher(teacher_id, instrument)

        QMessageBox.information(self, "موفق", "استاد با موفقیت اضافه شد.")
        self.clear_form()
        self.load_teachers()

    def load_teachers(self):
        self.list_teachers.clear()
        rows = fetch_teachers()  # [(teacher_id, name), ...]
        # ← سورت بر اساس نام فارسی؛ در صورت تساوی، بر اساس ID
        rows = sort_records_fa(rows, name_index=1, tiebreak_index=0)
        self.teachers_data = rows

        for teacher_id, name in rows:
            instruments = get_instruments_for_teacher(teacher_id) or []
            # سورت فارسی برای سازها (زیبا و یکدست)
            instruments_sorted = sorted(instruments, key=cmp_to_key(fa_collator.compare))
            instruments_text = "، ".join(instruments_sorted) if instruments_sorted else "بدون ساز"

            item = QListWidgetItem(f"{name} - ({instruments_text})")
            item.setData(1, teacher_id)
            self.list_teachers.addItem(item)

        self.lbl_count.setText(f"تعداد اساتید: {len(rows)} نفر")

    def search_teachers(self):
        query = self.search_input.text().strip()  # lower نکن! contains_fa خودش نرمال می‌کند
        self.list_teachers.clear()

        filtered = []
        for teacher_id, name in self.teachers_data:
            instruments = get_instruments_for_teacher(teacher_id) or []
            # جست‌وجوی فارسی روی نام یا هر یک از سازها
            if contains_fa(name, query) or any(contains_fa(ins, query) for ins in instruments):
                filtered.append((teacher_id, name))

        # سورت فارسی نتایج فیلترشده
        filtered = sort_records_fa(filtered, name_index=1, tiebreak_index=0)

        for teacher_id, name in filtered:
            instruments = get_instruments_for_teacher(teacher_id) or []
            instruments_sorted = sorted(instruments, key=cmp_to_key(fa_collator.compare))
            display_text = f"{name} - ({'، '.join(instruments_sorted) if instruments_sorted else 'بدون ساز'})"
            item = QListWidgetItem(display_text)
            item.setData(1, teacher_id)
            self.list_teachers.addItem(item)

        self.lbl_count.setText(f"تعداد اساتید: {len(filtered)} نفر")

    def fill_form(self, item):
        """Fill form with selected teacher's data including instruments."""
        teacher_id = item.data(1)
        self.selected_teacher_id = teacher_id
        row = get_teacher_by_id(teacher_id)

        if row:
            name, national_code, teaching_card, gender, phone, birth_date, card_number, iban = row

            self.input_name.setText(name)
            self.input_national_code.setText(national_code)
            self.input_teaching_card.setText(teaching_card or "")
            self.input_phone.setText(phone or "")
            self.combo_gender.setCurrentText(gender)
            self.input_birth_date.setText(birth_date or "")
            self.input_card_number.setText(card_number or "")
            self.input_iban.setText(iban or "")
            self.btn_update.setEnabled(True)

            # بارگذاری سازها
            self.list_instruments.clear()
            instruments = get_instruments_for_teacher(teacher_id)
            for ins in instruments:
                self.list_instruments.addItem(ins)

        self.btn_add.setEnabled(False)
        self.check_form_validity()

    def update_teacher(self):
        """Update teacher data and replace their instruments."""
        if not self.selected_teacher_id:
            return

        name = self.input_name.text().strip()
        national_code = self.input_national_code.text().strip()
        teaching_card = self.input_teaching_card.text().strip() or None
        phone = self.input_phone.text().strip()
        gender = self.combo_gender.currentText()
        birth_date = self.input_birth_date.text().strip()
        card_number = self.input_card_number.text().strip() or None
        iban = self.input_iban.text().strip() or None

        # بررسی اینکه آیا این کد ملی برای استاد دیگری ثبت شده یا نه
        if is_national_code_exists_for_other("teachers", national_code, self.selected_teacher_id):
            QMessageBox.warning(self, "خطا", "کد ملی تکراری است.")
            return
        # بررسی شماره تلفن (در صورت وجود مقدار)
        if not phone or not phone.isdigit() or len(phone) != 11:
            QMessageBox.warning(self, "خطا", "شماره تلفن باید وارد شده، ۱۱ رقمی و فقط عدد باشد.")
            return
        # 16 رقمی بودن شماره کارت
        if card_number and not re.match(r"^\d{4}-\d{4}-\d{4}-\d{4}$", card_number):
            QMessageBox.warning(self, "خطا", "شماره کارت نامعتبر است. باید ۱۶ رقم با خط تیره باشد.")
            return
        # بررسی اینکه شماره شبا 26 کاراکتر باشد و با ir آغاز شود
        if iban and (not iban.startswith("IR") or len(iban) != 26):
            QMessageBox.warning(self, "خطا", "شماره شبا باید با 'IR' شروع شود و دقیقاً ۲۶ کاراکتر باشد.")
            return
        # به‌روزرسانی اطلاعات استاد
        update_teacher_by_id(self.selected_teacher_id, name, national_code, teaching_card, gender, phone, birth_date,card_number, iban)
        # حذف همه سازهای قبلی
        previous_instruments = get_instruments_for_teacher(self.selected_teacher_id)
        for ins in previous_instruments:
            remove_instrument_from_teacher(self.selected_teacher_id, ins)

        # افزودن سازهای جدید از فرم
        for i in range(self.list_instruments.count()):
            instrument = self.list_instruments.item(i).text()
            add_instrument_to_teacher(self.selected_teacher_id, instrument)

        QMessageBox.information(self, "موفق", "اطلاعات استاد و سازهای او با موفقیت ویرایش شدند.")
        self.clear_form()
        self.load_teachers()

    def delete_teacher(self, item):
        '''delete teacher data from database if there are no students connected to it'''
        teacher_id = item.data(1)
        name = item.text()

        # بررسی اتصال هنرجوها به این استاد
        if is_teacher_assigned_to_students(teacher_id):
            QMessageBox.warning(self, "خطا", "امکان حذف استاد وجود ندارد چون هنرجویی به او اختصاص دارد.")
            return

        reply = QMessageBox.question(self, "حذف استاد", f"آیا مطمئنید می‌خواهید '{name}' را حذف کنید؟",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)

        if reply == QMessageBox.Yes:
            delete_teacher_by_id(teacher_id)
            self.load_teachers()

    def clear_form(self):
        """clear datas from inputs"""
        self.input_name.clear()
        self.input_instrument.clear()
        self.input_national_code.clear()
        self.input_teaching_card.clear()
        self.list_instruments.clear()
        self.combo_gender.setCurrentIndex(0)
        self.input_birth_date.clear()
        self.input_phone.clear()
        self.input_card_number.clear()
        self.input_iban.clear()
        self.selected_teacher_id = None
        self.btn_update.setEnabled(False)
        self.btn_add.setEnabled(False)
        self.check_form_validity()
        self.input_name.setFocus() # برو به خط اول
        self.list_teachers.clearSelection() #آیتم انتخاب‌شده در لیست هم برداشته بشه

    def check_form_validity(self):
        name = self.input_name.text().strip()
        national_code = self.input_national_code.text().strip()
        has_instruments = self.list_instruments.count() > 0
        phone = self.input_phone.text().strip()
        birth_text = self.input_birth_date.text().strip()
        phone_valid = phone.isdigit() and len(phone) == 11

        try:
            birth_date_valid = bool(birth_text) and jdatetime.datetime.strptime(birth_text, "%Y-%m-%d")
        except Exception:
            birth_date_valid = False

        is_valid = bool(name and national_code and has_instruments and phone_valid and birth_date_valid)

        # حالت افزودن
        self.btn_add.setEnabled(is_valid and self.selected_teacher_id is None)

        # حالت ویرایش → فقط بررسی اینکه رکوردی انتخاب شده
        self.btn_update.setEnabled(self.selected_teacher_id is not None)

    def add_instrument_to_list(self):
        text = self.input_instrument.text().strip()
        if not text:
            return
        if text and not self.is_instrument_in_list(text):
            self.list_instruments.addItem(text)
        self.input_instrument.clear()
        self.check_form_validity()
        self.btn_update.setEnabled(self.selected_teacher_id is not None)

    def remove_instrument_from_list(self, item):
        self.list_instruments.takeItem(self.list_instruments.row(item))
        self.check_form_validity()
        self.btn_update.setEnabled(self.selected_teacher_id is not None)

    def is_instrument_in_list(self, instrument):
        for i in range(self.list_instruments.count()):
            if self.list_instruments.item(i).text().lower() == instrument.lower():
                return True
        return False

    def show_calendar_popup(self):
        dialog = ShamsiDatePopup(self)
        if dialog.exec_() == QDialog.Accepted:
            selected_date = dialog.get_selected_date()
            self.input_birth_date.setText(selected_date)
            self.check_form_validity()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        for child in self.input_birth_date.children():
            if isinstance(child, QToolButton):
                child.move(self.input_birth_date.rect().right() - 20, (self.input_birth_date.height() - 16) // 2)
