from acasmart.data.db import get_connection
from acasmart.data.migrator import run_migrations
from acasmart.data.repos.settings_repo import ensure_bool_setting
import os
import sqlite3
import shutil
import stat
import logging

from acasmart.core import config
from acasmart.core.utils import hash_password
from acasmart.paths import DB_PATH, APP_DATA_DIR, resource_path

def initialize_database():
    # ۱) اگر دیتابیس هنوز ساخته نشده، از روی تمپلیت کپی کن
    if not DB_PATH.exists():
        template = resource_path("resources", "acasmart_template.db")
        if not template.exists():
            raise FileNotFoundError(f"❌ Template DB not found at: {template}")

        APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(template, DB_PATH)

        try:
            # فقط کاربر فعلی بتواند فایل DB را بخواند/بنویسد
            os.chmod(DB_PATH, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
        except Exception as e:
            logging.warning(f"⚠️ chmod failed on DB: {e}")

        print(f"✅ Database template copied → {DB_PATH}")

    # ۲) ساخت جداول و اجرای مهاجرت‌های نسخه‌بندی‌شده (با بکاپ و بازگردانی در صورت خطا)
    run_migrations()

    # ۳) حالا که جداول تضمین شدند، سراغ تنظیمات برو
    ensure_bool_setting("sms_enabled", default=True) 
    # ۴) بارگذاری متغیرهای محیطی
    admin_mobile = config.admin_mobile()
    admin_password = config.admin_password()

    # الف) ارور شفاف اگر پسورد تعیین نشده/خالی است
    if not admin_password:
        raise RuntimeError(
            "❌ ADMIN_PASSWORD not set in .env file! "
            "یک مقدار معتبر برای ADMIN_PASSWORD در فایل .env قرار بده."
        )

    hashed = hash_password(admin_password)

    # ۵) اضافه کردن ادمین پیش‌فرض اگر جدول users خالی بود
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users")
        row = c.fetchone()                 # فقط یک‌بار بخوان
        user_count = row[0] if row else 0  # اگر هیچ سطری برنگشت، ۰ در نظر بگیر

        if user_count == 0:
            c.execute(
                "INSERT INTO users (mobile, password) VALUES (?, ?)",
                (admin_mobile, hashed),
            )
            conn.commit()
            print("👤 Default admin user created.")