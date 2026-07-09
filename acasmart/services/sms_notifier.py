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
    def __init__(self):
        # اطلاعاتِ IPPanel از تنظیماتِ متمرکز (config خودش .env را یک‌بار بار می‌کند)
        self.api_key = config.ippanel_api_key()
        self.from_number = config.ippanel_from_number()
        self.pattern_code = config.ippanel_pattern_code()
        self.api_url = "https://edge.ippanel.com/v1/api/send"
        
        # مسیر مطمئن برای ذخیره لاگ (همان مسیر main.py)
        self.log_dir = APP_DATA_DIR
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = os.path.join(APP_DATA_DIR, "acasmart.log")
    

    def is_enabled(self) -> bool:
        '''check if auto sms send is enabled'''
        # پیش‌فرض: فعال
        return get_setting_bool("sms_enabled", True)

    def send_renew_term_notification(self, student_name, phone_number, class_name):
        # 1) اگر ارسال پیامک غیرفعال است، بی‌سر و صدا برگرد
        if not self.is_enabled():
            try:
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write("[SMS SKIPPED] ارسال پیامک غیرفعال بود. ارسال انجام نشد.\n")
            except Exception as e:
                print(f"⚠️ خطا در نوشتن لاگ (skip): {e}")
            return {"status": SmsStatus.DISABLED, "message": "ارسال پیامک غیرفعال است"}

        # 2) ولیدیشن حداقلی تنظیمات ENV
        if not self.api_key or not self.from_number or not self.pattern_code:
            try:
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write("[SMS ERROR] اطلاعات IPPanel ناقص است (API_KEY/ FROM_NUMBER/ PATTERN_CODE).\n")
            except Exception as e:
                print(f"⚠️ خطا در نوشتن لاگ (env): {e}")
            # برگرداندن وضعیت شکست برای استفادهٔ احتمالی در UI
            return {"status": SmsStatus.FAILED, "message": "پیکربندی IPPanel ناقص است"}

        # تبدیل شماره به فرمت +98
        if phone_number.startswith("0"):
            recipient = "+98" + phone_number[1:]
        elif phone_number.startswith("9"):
            recipient = "+98" + phone_number
        else:
            recipient = phone_number

        params = {
            "student_name": student_name,
            "class_name": class_name
        }

        data = {
            "sending_type": "pattern",
            "from_number": self.from_number,
            "code": self.pattern_code,
            "recipients": [recipient],
            "params": params
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization":self.api_key
        }

        response = requests.post(self.api_url, headers=headers, json=data)

        if response.status_code != 200:
            error_message = (
                f"ارسال پیامک برای {student_name} ({phone_number}) با خطا مواجه شد:\n"
                f"کد وضعیت: {response.status_code}\n"
                f"متن خطا: {response.text}"
            )
            # نوشتن در فایل لاگ (مسیر مطمئن)
            try:
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(f"[SMS ERROR] {error_message}\n")
            except Exception as e:
                print(f"❌ خطا در نوشتن لاگ: {e}")
            # حفظ رفتار قبلی: پرتاب خطا برای هندل فعلی UI
            raise Exception(error_message)

        print(f"✅ پیامک برای {student_name} ارسال شد.")
        return {"status": SmsStatus.SENT, "message": "پیامک ارسال شد"}