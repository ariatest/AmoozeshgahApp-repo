from acasmart.data.repos.settings_repo import get_setting_bool
import requests
import os
from acasmart.core import config
from acasmart.paths import APP_DATA_DIR
from enum import Enum
class SmsStatus(Enum):
    SENT = "sent"
    FAILED = "failed"
    DISABLED = "disabled"

class SmsNotifier:
    # مهلتِ اتصال/پاسخ (ثانیه) — تا هیچ‌وقت رشتهٔ رابطِ کاربری روی شبکهٔ کند/قطع بلاک نشود
    REQUEST_TIMEOUT = (5, 15)

    def __init__(self):
        # اطلاعاتِ IPPanel از تنظیماتِ متمرکز (config خودش .env را یک‌بار بار می‌کند)
        self.api_key = config.ippanel_api_key()
        self.from_number = config.ippanel_from_number()
        # دو الگوی مجزا: یادآوریِ خودکارِ «یک جلسه مانده» و دعوتِ دستیِ ثبت‌نامِ ترمِ جدید
        self.reminder_code = config.ippanel_pattern_code_reminder()       # IPPANEL_PATTERN_CODE_1
        self.invitation_code = config.ippanel_pattern_code_invitation()   # IPPANEL_PATTERN_CODE_2
        self.api_url = "https://edge.ippanel.com/v1/api/send"

        # مسیر مطمئن برای ذخیره لاگ (همان مسیر main.py)
        self.log_dir = APP_DATA_DIR
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = os.path.join(APP_DATA_DIR, "acasmart.log")

    def is_enabled(self) -> bool:
        '''check if auto sms send is enabled'''
        # پیش‌فرض: فعال
        return get_setting_bool("sms_enabled", True)

    def _log(self, line):
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line if line.endswith("\n") else line + "\n")
        except Exception as e:
            print(f"⚠️ خطا در نوشتن لاگ: {e}")

    def send_renew_term_notification(self, student_name, phone_number, class_name):
        """یادآوریِ خودکارِ تمدید (یک جلسه مانده) — الگوی ۱، متغیرها: student_name, class_name."""
        return self._send_pattern(
            self.reminder_code,
            {"student_name": student_name, "class_name": class_name},
            student_name, phone_number,
        )

    def send_new_term_invitation(self, student_name, phone_number):
        """دعوتِ دستیِ ثبت‌نامِ ترمِ جدید (پنجرهٔ ارسال پیامک) — الگوی ۲، متغیر: student_name."""
        return self._send_pattern(
            self.invitation_code,
            {"student_name": student_name},
            student_name, phone_number,
        )

    def _send_pattern(self, pattern_code, params, student_name, phone_number):
        """ارسالِ یک پیامکِ الگویی. برمی‌گرداند {"status": ...}؛ روی خطای HTTP استثناء پرتاب می‌کند
        (مثل قبل، تا UI هندل کند). روی خطای شبکه/timeout هم استثناء پرتاب می‌شود (به‌جای بلاک‌شدن)."""
        # 1) اگر ارسال پیامک غیرفعال است، بی‌سر و صدا برگرد
        if not self.is_enabled():
            self._log("[SMS SKIPPED] ارسال پیامک غیرفعال بود. ارسال انجام نشد.")
            return {"status": SmsStatus.DISABLED, "message": "ارسال پیامک غیرفعال است"}

        # 2) ولیدیشن حداقلی تنظیمات ENV
        if not self.api_key or not self.from_number or not pattern_code:
            self._log("[SMS ERROR] اطلاعات IPPanel ناقص است (API_KEY/ FROM_NUMBER/ PATTERN_CODE).")
            return {"status": SmsStatus.FAILED, "message": "پیکربندی IPPanel ناقص است"}

        # تبدیل شماره به فرمت +98
        if phone_number.startswith("0"):
            recipient = "+98" + phone_number[1:]
        elif phone_number.startswith("9"):
            recipient = "+98" + phone_number
        else:
            recipient = phone_number

        data = {
            "sending_type": "pattern",
            "from_number": self.from_number,
            "code": pattern_code,
            "recipients": [recipient],
            "params": params,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": self.api_key,
        }

        # timeout حیاتی است: بدونِ آن، شبکهٔ کند/قطع رشتهٔ UI را برای همیشه بلاک می‌کند و برنامه هنگ می‌کند.
        response = requests.post(self.api_url, headers=headers, json=data, timeout=self.REQUEST_TIMEOUT)

        if response.status_code != 200:
            error_message = (
                f"ارسال پیامک برای {student_name} ({phone_number}) با خطا مواجه شد:\n"
                f"کد وضعیت: {response.status_code}\n"
                f"متن خطا: {response.text}"
            )
            self._log(f"[SMS ERROR] {error_message}")
            # حفظ رفتار قبلی: پرتاب خطا برای هندل فعلی UI
            raise Exception(error_message)

        print(f"✅ پیامک برای {student_name} ارسال شد.")
        return {"status": SmsStatus.SENT, "message": "پیامک ارسال شد"}