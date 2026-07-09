from __future__ import annotations

from acasmart.data.repos.payments_repo import get_payment_by_id, get_terms_for_payment_management, get_total_paid_for_term, insert_payment, update_payment_by_id
from acasmart.data.repos.settings_repo import get_setting
from acasmart.data.repos.students_repo import fetch_registered_classes_for_student, fetch_students_with_teachers
from acasmart.data.repos.terms_repo import consumed, get_term_id_by_student_and_class, term_config, term_progress
from PySide6.QtWidgets import (
    QWidget, QLabel, QLineEdit, QPushButton, QListWidget, QListWidgetItem,
    QVBoxLayout, QHBoxLayout, QFormLayout, QTextEdit, QComboBox, QMessageBox, QDialog
)
from PySide6.QtCore import QDate, Qt
from acasmart.ui.widgets.shamsi_date_picker import ShamsiDatePicker
from acasmart.ui.widgets.payment_student_picker_popup import PaymentStudentPickerPopup
from acasmart.ui.widgets.payment_class_picker_popup import PaymentClassPickerPopup
from acasmart.ui.widgets.payment_term_picker_popup import PaymentTermPickerPopup
import jdatetime
from acasmart.core.utils import format_currency_with_unit, get_currency_unit, format_currency, parse_user_amount_to_toman
from acasmart.ui.reports.payment_report_window import PaymentReportWindow
from acasmart.core.fa_collation import sort_records_fa
from acasmart.core.utils import currency_label, format_currency_with_unit, parse_user_amount_to_toman
from acasmart.ui.widgets.theme_manager import ThemeManager
from acasmart.ui.widgets.base_secondary_window import BaseSecondaryWindow

class PaymentManager(BaseSecondaryWindow):
    
    def __init__(self, return_target: QWidget | None = None):
        super().__init__("ثبت پرداخت‌ها و گزارش‌گیری مالی", return_target)
        self.setGeometry(300, 200, 900, 700)
        self.showMaximized()

        self.last_payment_date = QDate.currentDate()
        self.term_fee = int(get_setting("term_fee", 6000000))
        self.term_start = None
        self.term_end = None
        self.term_expired = True
        self.term_missing = False
        self.is_editing = False
        self.editing_payment_id = None
        self.selected_student_id = None
        self.selected_student_teacher = None
        self.selected_class_id = None
        self.selected_term_id = None
        self.students = []

        layout = self.content_layout()
        layout.setSpacing(12)

        # ---------- انتخاب هنرجو (popup) ----------
        title_student = QLabel("👤 هنرجو")
        title_student.setProperty("sectionTitle", True)
        layout.addWidget(title_student)
        self.student_btn = QPushButton("👤 انتخاب هنرجو")
        self.student_btn.setProperty("variant", "secondary")
        self.student_btn.setCursor(Qt.PointingHandCursor)
        self.student_btn.setToolTip("برای انتخاب هنرجو کلیک کنید")
        self.student_btn.clicked.connect(self.open_student_picker)
        layout.addWidget(self.student_btn)

        # ---------- انتخاب کلاس (popup) ----------
        title_class = QLabel("🏫 کلاس")
        title_class.setProperty("sectionTitle", True)
        layout.addWidget(title_class)
        self.class_btn = QPushButton("🏫 انتخاب کلاس")
        self.class_btn.setProperty("variant", "secondary")
        self.class_btn.setCursor(Qt.PointingHandCursor)
        self.class_btn.setToolTip("ابتدا هنرجو را انتخاب کنید")
        self.class_btn.setEnabled(False)
        self.class_btn.clicked.connect(self.open_class_picker)
        layout.addWidget(self.class_btn)

        # ---------- انتخاب ترم (popup) ----------
        title_term = QLabel("📅 ترم")
        title_term.setProperty("sectionTitle", True)
        layout.addWidget(title_term)
        self.term_btn = QPushButton("📅 انتخاب ترم")
        self.term_btn.setProperty("variant", "secondary")
        self.term_btn.setCursor(Qt.PointingHandCursor)
        self.term_btn.setToolTip("ابتدا هنرجو و کلاس را انتخاب کنید")
        self.term_btn.setEnabled(False)
        self.term_btn.clicked.connect(self.open_term_picker)
        layout.addWidget(self.term_btn)

        # ---------- فرم پرداخت ----------
        title_payment = QLabel("💳 فرم ثبت پرداخت")
        title_payment.setProperty("sectionTitle", True)
        layout.addWidget(title_payment)

        form_layout = QFormLayout()
        form_layout.setLabelAlignment(Qt.AlignRight)
        form_layout.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        form_layout.setHorizontalSpacing(10)
        form_layout.setVerticalSpacing(6)


        self.input_amount = QLineEdit()
        self.input_amount.setPlaceholderText("مبلغ ")
        self._set_amount_box_from_toman(self.term_fee)
        form_layout.addRow("💰 مبلغ پرداختی:", self.input_amount)

        self.date_payment_picker = ShamsiDatePicker()
        self.date_payment_picker.setDate(self.last_payment_date)  # استفاده از مقدار ذخیره‌شده
        form_layout.addRow("📅 تاریخ پرداخت:", self.date_payment_picker)

        self.combo_type = QComboBox()
        self.combo_type.addItems(["شهریه", "مازاد"])
        self.combo_type.currentIndexChanged.connect(self.update_financial_labels)
        form_layout.addRow("📂 نوع پرداخت:", self.combo_type)

        self.input_description = QTextEdit()
        self.input_description.setPlaceholderText("مثلاً بابت ثبت‌نام ترم زمستان...")
        self.input_description.setFixedHeight(70)
        form_layout.addRow("📝 توضیحات:", self.input_description)
        layout.addLayout(form_layout)

        # ---------- دکمه‌ها ----------
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.btn_clear = QPushButton("🧹 پاک‌سازی فرم")
        self.btn_clear.setProperty("variant", "secondary")
        self.btn_clear.clicked.connect(self.clear_form)

        self.btn_add_payment = QPushButton("💰 ثبت پرداخت")
        self.btn_add_payment.setProperty("variant", "primary")
        self.set_payment_button_enabled(False)
        self.btn_add_payment.clicked.connect(self.add_payment)

        btn_layout.addWidget(self.btn_clear)
        btn_layout.addWidget(self.btn_add_payment)
        layout.addLayout(btn_layout)

        # ---------- خلاصه مالی ----------
        self.lbl_total = QLabel("مجموع پرداخت شده: " + format_currency_with_unit(0))
        self.lbl_total.setProperty("caption", True)
        layout.addWidget(self.lbl_total)

        self.lbl_remaining = QLabel(f"باقی‌مانده شهریه (ترم جاری): {format_currency_with_unit(self.term_fee)}")
        self.lbl_remaining.setProperty("caption", True)
        layout.addWidget(self.lbl_remaining)

        # ---------- گزارش ----------
        self.btn_show_report = QPushButton("📊 مشاهده گزارش پرداخت‌ها")
        self.btn_show_report.setProperty("variant", "ghost")
        self.btn_show_report.clicked.connect(self.open_report_window)
        layout.addWidget(self.btn_show_report)


        # ---------- اعمال تم ----------
        for w in (self.btn_add_payment, self.btn_clear, self.btn_show_report, self.student_btn, self.class_btn, self.term_btn,
                  self.input_amount, self.combo_type):
            ThemeManager.repolish(w)

        # ---------- داده اولیه ----------
        self.load_students()

    # --- helpers for currency display ---
    def _display_amount(self, amount_toman: int) -> str:
        """
        مقدار تومان خام را برای نمایش در فیلد ورودی، برحسب واحد فعلی UI (تومان/ریال) برمی‌گرداند.
        خروجی فقط عدد است (بدون واحد/کاما).
        """
        try:
            if currency_label() == "ریال":
                return str(int(round(float(amount_toman) * 10)))
            return str(int(round(float(amount_toman))))
        except Exception:
            return str(amount_toman)

    def _set_amount_box_from_toman(self, amount_toman: int):
        """فیلد input_amount را با توجه به واحد فعلی (ریال/تومان) به‌روز می‌کند."""
        self.input_amount.setText(self._display_amount(amount_toman))

    def clear_form(self):
        self.term_fee = int(get_setting("term_fee", self.term_fee))
        self.selected_student_id = None
        self.selected_student_teacher = None
        self.selected_class_id = None
        self.selected_term_id = None
        self.term_start = None
        self.term_end = None
        self.term_expired = True
        self.term_missing = False

        self.student_btn.setText("👤 انتخاب هنرجو")
        self.class_btn.setText("🏫 انتخاب کلاس")
        self.class_btn.setEnabled(False)
        self.term_btn.setText("📅 انتخاب ترم")
        self.term_btn.setEnabled(False)
        self._set_amount_box_from_toman(self.term_fee)
        self.input_description.clear()
        self.combo_type.setCurrentIndex(0)

        self.lbl_total.setText("مجموع پرداخت شده: " + format_currency_with_unit(0))
        self.lbl_remaining.setText(f"باقی‌مانده شهریه (ترم جاری): {format_currency_with_unit(self.term_fee)}")

        self.load_students()
        self.btn_add_payment.setText("💰 ثبت پرداخت")
        self.set_payment_button_enabled(False)

        self.last_payment_date = QDate.currentDate()
        self.date_payment_picker.setDate(self.last_payment_date)


    def load_students(self):
        """بارگذاری لیست هنرجویان برای popup انتخاب هنرجو."""
        rows = fetch_students_with_teachers()
        self.students = sort_records_fa(rows, name_index=2, tiebreak_index=1)

    def open_student_picker(self):
        """باز کردن popup انتخاب هنرجو؛ بعد از تأیید، هنرجو در ویجت نمایش داده می‌شود."""
        dlg = PaymentStudentPickerPopup(self, students_data=self.students)
        if dlg.exec_() == QDialog.Accepted:
            result = dlg.get_selected_student()
            if result:
                sid, name, teacher = result
                self.selected_student_id = sid
                self.selected_student_teacher = teacher
                self.student_btn.setText(f"👤 {name} (استاد: {teacher})")
                self.selected_class_id = None
                self.selected_term_id = None
                self.class_btn.setText("🏫 انتخاب کلاس")
                self.class_btn.setEnabled(True)
                self.term_btn.setText("📅 انتخاب ترم")
                self.term_btn.setEnabled(False)
                self.lbl_total.setText("لطفاً یک کلاس را انتخاب کنید")
                self.lbl_remaining.setText("")
                self.set_payment_button_enabled(False)

    def open_class_picker(self):
        """باز کردن popup انتخاب کلاس (کلاس‌های ثبت‌شدهٔ هنرجو)."""
        if not self.selected_student_id:
            return
        dlg = PaymentClassPickerPopup(self, student_id=self.selected_student_id)
        if dlg.exec_() == QDialog.Accepted:
            cid = dlg.get_selected_class_id()
            if cid is not None:
                self.selected_class_id = cid
                self.class_btn.setText(f"🏫 {dlg.get_selected_class_display()}")
                self.selected_term_id = None
                self.term_btn.setText("📅 انتخاب ترم")
                self.term_btn.setEnabled(True)
                self._load_terms_after_class_selected()

    def _load_terms_after_class_selected(self):
        """بعد از انتخاب کلاس، وضعیت ترم و برچسب‌های مالی را به‌روز کن."""
        self.update_term_status()
        self.update_financial_labels()

    def open_term_picker(self):
        """باز کردن popup انتخاب ترم."""
        if not (self.selected_student_id and self.selected_class_id):
            return
        dlg = PaymentTermPickerPopup(self, student_id=self.selected_student_id, class_id=self.selected_class_id)
        if dlg.exec_() == QDialog.Accepted:
            term_id = dlg.get_selected_term_id()
            if term_id is not None:
                self.selected_term_id = term_id
                self.term_btn.setText(f"📅 {dlg.get_selected_term_display()}")
                self._load_term_fee_from_selected_term()
                self.update_term_status()
                self.update_financial_labels()

    def update_term_status(self):
        """Determine if student has a term, and if it's expired (by session count)."""
        if self.selected_student_id and self.selected_class_id:
            term_id = get_term_id_by_student_and_class(self.selected_student_id, self.selected_class_id)
            if not term_id:
                self.term_missing = True
                self.term_expired = True
                return

            self.term_missing = False
            done = consumed(term_id)
            limit = self._get_term_sessions_limit()
            self.term_expired = (done >= limit)
        else:
            self.term_missing = False
            self.term_expired = True

    def update_financial_labels(self):
        """به‌روزرسانی اطلاعات مالی و جلسات برای ترم انتخاب‌شده."""
        self.lbl_total.setText("")
        self.lbl_remaining.setText("")
        self.set_payment_button_enabled(False)

        if not (self.selected_student_id and self.selected_class_id):
            return

        if not self.selected_term_id:
            self.term_missing = True
            self.term_expired = True
            self.lbl_total.setText("لطفاً یک ترم را انتخاب کنید")
            return

        self.term_missing = False
        done = consumed(self.selected_term_id)
        limit = self._get_term_sessions_limit()
        self.term_expired = (done >= limit)

        # اطلاعات مالی ترم انتخاب‌شده
        total = get_total_paid_for_term(self.selected_term_id)
        rem_money = self.term_fee - total
        rem_sessions = limit - done
        
        # تعیین وضعیت ترم
        term_status = "تکمیل شده" if self.term_expired else "فعال"
        
        self.lbl_total.setText(f"ترم {term_status} — جلسات: {done} از {limit} — پرداخت: {format_currency_with_unit(total)}")
        self.lbl_total.setProperty("caption", True)
        ThemeManager.repolish(self.lbl_total)

        # مانده شهریه رنگ‌بندی شود
        if rem_money == 0:
            self.lbl_remaining.setProperty("status", "success")
        elif rem_money <= self.term_fee / 2:
            self.lbl_remaining.setProperty("status", "warning")
        else:
            self.lbl_remaining.setProperty("status", "error")

        self.lbl_remaining.setText(f"مانده شهریه: {format_currency_with_unit(rem_money)} — جلسات باقی: {rem_sessions}")
        ThemeManager.repolish(self.lbl_remaining)

        # sync amount box with current unit; prefer remaining for tuition ---
        try:
            if self.combo_type.currentText() == "شهریه":
                # نمایش مانده برای پرداخت شهریه
                self._set_amount_box_from_toman(max(rem_money, 0))
            else:
                # برای مازاد، اگر کاربر چیزی تایپ نکرده بود، صفر/خالی نگذاریم
                if not (self.input_amount.text() or "").strip():
                    self._set_amount_box_from_toman(0)
        except Exception:
            pass

        # نوع پرداخت انتخاب‌شده رو بگیر
        ptype = self.combo_type.currentText()
        if ptype == "شهریه":
            # فقط وقتی شهریه بدهکار هست دکمه فعال شه
            can_pay = rem_money > 0
        else:
            # برای پرداخت مازاد همیشه فعال باشه
            can_pay = True
        self.set_payment_button_enabled(can_pay)


    def add_payment(self):

        ptype = 'tuition' if self.combo_type.currentText() == "شهریه" else 'extra'

        try:
            # amount = int(self.input_amount.text())
            raw_text = self.input_amount.text()
            amount = parse_user_amount_to_toman(raw_text)
            if amount <= 0:
                QMessageBox.warning(self, "خطا", "مبلغ باید بزرگتر از صفر باشد.")
                return
        except ValueError:
            QMessageBox.warning(self, "خطا", "مبلغ باید عددی باشد.")
            return

        date_str = self.date_payment_picker.selected_shamsi
        desc = self.input_description.toPlainText().strip() or None

        # فقط در حالت درج جدید بررسی و دریافت term_id انجام شود
        if not self.is_editing:
            if not self.selected_term_id:
                QMessageBox.warning(self, "خطا", "لطفاً یک ترم را انتخاب کنید.")
                return

            # بررسی مانده در حالت شهریه و پرداخت جدید
            if ptype == 'tuition':
                total_paid = get_total_paid_for_term(self.selected_term_id)
                remaining = self.term_fee - total_paid
                
                if remaining <= 0:
                    QMessageBox.warning(self, "خطا", "این ترم قبلاً به طور کامل پرداخت شده است.")
                    return
                    
                if amount > remaining:
                    remaining_str = format_currency_with_unit(remaining)
                    QMessageBox.warning(
                        self, "خطا",
                        f"مبلغ واردشده از مانده شهریه بیشتر است ({(remaining_str)} باقی‌مانده)."
                    )
                    return

            # درج پرداخت جدید
            try:
                insert_payment(
                    self.selected_student_id,
                    self.selected_class_id,
                    self.selected_term_id,
                    amount,
                    date_str,
                    ptype,
                    desc
                )
            except ValueError:
                QMessageBox.warning(self, "خطا", "ثبت پرداخت ممکن نیست: مبلغ از مانده شهریه بیشتر است یا نامعتبر است.")
                return
            QMessageBox.information(self, "موفق", "پرداخت با موفقیت ثبت شد.")
        else:
            # ویرایش پرداخت قبلی (نیاز به term_id ندارد)
            try:
                update_payment_by_id(
                    payment_id=self.editing_payment_id,
                    amount=amount,
                    date=date_str,
                    payment_type=ptype,
                    description=desc
                )
            except ValueError:
                QMessageBox.warning(self, "خطا", "ویرایش پرداخت ممکن نیست: مبلغ از مانده شهریه بیشتر است یا نامعتبر است.")
                return
            QMessageBox.information(self, "ویرایش شد", "پرداخت با موفقیت ویرایش شد.")
            del self.editing_payment_id
            self.is_editing = False
            self.btn_add_payment.setText("💰 ثبت پرداخت")

        # ادامه پردازش
        try:

            self.last_payment_date = jdatetime.date.fromisoformat(date_str).togregorian()
        except Exception as e:
            QMessageBox.warning(self, "خطا", "مشکلی در تبدیل تاریخ پیش آمده است.")
            print(f"error in pay_manager: {e}")
        self.update_financial_labels()
        self.clear_form()
        # اگر پنجره گزارش باز است، داده‌ها را تازه‌سازی کن
        if hasattr(self, "report_window") and self.report_window.isVisible():
            self.report_window.load_payments()

    def set_payment_button_enabled(self, enabled: bool):
        self.btn_add_payment.setEnabled(enabled)
        if enabled:
            self.btn_add_payment.setStyleSheet("""
                QPushButton {
                    background-color: #28a745;
                    color: white;
                    padding: 6px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #218838;
                }
            """)
        else:
            self.btn_add_payment.setStyleSheet("""
                QPushButton {
                    background-color: #cccccc;
                    color: #666666;
                    padding: 6px;
                    font-weight: bold;
                }
            """)

    def open_report_window(self):
        self.report_window = PaymentReportWindow(
            student_id=self.selected_student_id,
            class_id=self.selected_class_id,
            return_target=self
        )
        self.report_window.payment_changed.connect(self.update_financial_labels)
        self.report_window.edit_requested.connect(self.load_payment_for_edit)
        self.report_window.show()

    def load_payment_for_edit(self, payment_id: int):
        data = get_payment_by_id(payment_id)
        if not data:
            QMessageBox.warning(self, "خطا", "پرداخت موردنظر یافت نشد.")
            return

        self.load_students()
        target_student_id = data["student_id"]
        target_class_id = data["class_id"]
        target_term_id = data.get("term_id")

        # تنظیم هنرجو و نمایش روی دکمه
        for row in self.students:
            if len(row) < 4:
                continue
            sid, _, name, teacher = row[:4]
            if sid == target_student_id:
                self.selected_student_id = sid
                self.selected_student_teacher = teacher
                self.student_btn.setText(f"👤 {name} (استاد: {teacher})")
                self.class_btn.setEnabled(True)
                break

        # تنظیم کلاس و نمایش روی دکمه
        student_classes = fetch_registered_classes_for_student(target_student_id)
        for cid, cname, tname, instr, day, start, end, room in student_classes:
            if cid == target_class_id:
                self.selected_class_id = cid
                self.class_btn.setText(f"🏫 {cname} ({day} {start}-{end}) - {tname}")
                self.term_btn.setEnabled(True)
                break

        # تنظیم ترم و نمایش روی دکمه
        terms = get_terms_for_payment_management(target_student_id, target_class_id)
        for term in terms:
            if term["term_id"] == target_term_id:
                self.selected_term_id = target_term_id
                start_date = term["start_date"]
                end_date = term["end_date"]
                term_status = term["term_status"]
                total_paid = term["total_paid"]
                debt = term["debt"]
                display = f"ترم {start_date}"
                if end_date:
                    display += f" تا {end_date}"
                display += f" - {term_status}"
                if debt == 0:
                    display += " - تسویه شده"
                elif debt > 0:
                    display += f" - بدهکار: {format_currency_with_unit(debt)}"
                if total_paid > 0:
                    display += f" (پرداخت: {format_currency_with_unit(total_paid)})"
                self.term_btn.setText(f"📅 {display}")
                break
        else:
            self.selected_term_id = target_term_id

        self._load_term_fee_from_selected_term()
        self.update_term_status()
        self.update_financial_labels()

        # مقداردهی فیلدهای فرم
        # مبلغ
        try:
            from acasmart.core.utils import format_currency
            self._set_amount_box_from_toman(int(data["amount"]))
        except Exception:
            self.input_amount.setText(str(data["amount"]))

        # نوع پرداخت
        if data["payment_type"] == 'tuition':
            self.combo_type.setCurrentIndex(0)  # "شهریه"
        else:
            self.combo_type.setCurrentIndex(1)  # "مازاد"

        # توضیحات
        self.input_description.setPlainText(data["description"] or "")

        # تاریخ: پرداخت‌ها به شمسی ذخیره شده‌اند ("YYYY-MM-DD")
        try:
            jdate = jdatetime.date.fromisoformat(data["payment_date"]).togregorian()
            self.date_payment_picker.setDate(QDate(jdate.year, jdate.month, jdate.day))
        except Exception:
            # اگر هر دلیلی شکست خورد، تاریخ امروز ست شود
            self.date_payment_picker.setDate(QDate.currentDate())

        # 3) رفتن به وضعیت ویرایش
        self.is_editing = True
        self.editing_payment_id = data["id"]
        self.btn_add_payment.setText("✏️ ذخیره ویرایش")
        self.set_payment_button_enabled(True)

        # پنجره را جلو بیاور
        self.raise_()
        self.activateWindow()

    def _load_term_fee_from_selected_term(self):
        """
        شهریهٔ ترم انتخاب‌شده را از جدول student_terms می‌خواند.
        اگر نبود، از مقدار پیش‌فرض تنظیمات استفاده می‌کند.
        """
        try:
            fee = None
            if self.selected_term_id:
                cfg = term_config(self.selected_term_id)
                fee = cfg.tuition_fee if cfg else None
            if fee is None:
                fee = int(get_setting("term_fee", 6000000))
            self.term_fee = int(fee)

            # اگر نوع پرداخت «شهریه» است، کادر مبلغ را با مانده یا شهریه تنظیم کن
            # (ترجیح من: با مانده؛ اگر هنوز محاسبه نشده، فعلاً کل شهریه)
            self._set_amount_box_from_toman(self.term_fee)
        except Exception:
            # در بدترین حالت همان پیش‌فرض
            self.term_fee = int(get_setting("term_fee", 6000000))
            self._set_amount_box_from_toman(self.term_fee)

    def _get_term_sessions_limit(self) -> int:
        """سقف جلسات ترم انتخاب‌شده را از DB می‌خواند؛ در صورت عدم وجود، از تنظیمات پیش‌فرض."""
        try:
            if self.selected_term_id:
                p = term_progress(self.selected_term_id)
                if p:
                    return p.limit
        except Exception:
            pass
        return int(get_setting("term_session_count", 12))
