import sys
import traceback
import logging
from datetime import datetime, timedelta
from pathlib import Path

from acasmart.paths import APP_DATA_DIR, DB_PATH, resource_path
from acasmart.core import config
from PySide6.QtWidgets import QApplication, QMessageBox

from acasmart.core.app_init import initialize_database
from acasmart.ui.windows.login_window import LoginWindow

from PySide6.QtCore import Qt, QObject
from acasmart.ui.widgets.theme_manager import ThemeManager, apply_theme_icon

# ---------- Environment ----------
config.load()  # load .env once (path-aware); accessors also lazy-load on first use

def _ensure_logging():
    root = logging.getLogger()
    if root.handlers:
        return  # respect existing setup
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    log_file = APP_DATA_DIR / "acasmart.log"
    
    # Create a file handler
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    
    # Create formatter
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler.setFormatter(formatter)
    
    # Configure root logger
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    
    # Only add console handler for non-frozen applications
    if not getattr(sys, 'frozen', False):
        # For non-frozen apps, try to add console handler
        try:
            if hasattr(sys, '__stdout__') and sys.__stdout__ is not None:
                console_handler = logging.StreamHandler(sys.__stdout__)
            else:
                console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(logging.INFO)
            console_handler.setFormatter(formatter)
            root.addHandler(console_handler)
        except Exception as e:
            # If console handler fails, just log to file
            pass  # Silent fail for console handler

_ensure_logging()

# Only create LoggerWriter and redirect stdout/stderr for non-frozen applications
if not getattr(sys, 'frozen', False):
    class LoggerWriter:
        def __init__(self, level):
            self.level = level
            self._original_stdout = getattr(sys, '__stdout__', sys.stdout)
            self._original_stderr = getattr(sys, '__stderr__', sys.stderr)
        
        def write(self, message):
            if message.strip():
                # Write to original stdout/stderr to avoid recursion
                try:
                    if self.level == logging.info:
                        self._original_stdout.write(message)
                    else:
                        self._original_stderr.write(message)
                    # Also log it
                    self.level(message)
                except Exception:
                    # If logging fails, just write to original stream
                    if self.level == logging.info:
                        self._original_stdout.write(message)
                    else:
                        self._original_stderr.write(message)
        
        def flush(self):
            try:
                if self.level == logging.info:
                    self._original_stdout.flush()
                else:
                    self._original_stderr.flush()
            except Exception:
                pass  # Silent fail for flush
    
    # Only redirect if we have access to the original streams
    try:
        if hasattr(sys, '__stdout__') and hasattr(sys, '__stderr__'):
            sys.stdout = LoggerWriter(logging.info)
            sys.stderr = LoggerWriter(logging.error)
    except Exception:
        pass  # Silent fail for redirection

# ---------- Safe Logging Functions ----------
def safe_log_info(message):
    """Safely log info message without causing recursion"""
    try:
        logging.info(message)
    except Exception:
        # If logging fails, try to write to file directly
        try:
            with open(APP_DATA_DIR / "acasmart.log", "a", encoding="utf-8") as f:
                f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} INFO: {message}\n")
        except Exception:
            pass  # Silent fail

def safe_log_error(message):
    """Safely log error message without causing recursion"""
    try:
        logging.error(message)
    except Exception:
        # If logging fails, try to write to file directly
        try:
            with open(APP_DATA_DIR / "acasmart.log", "a", encoding="utf-8") as f:
                f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ERROR: {message}\n")
        except Exception:
            pass  # Silent fail

# ---------- Qt event/slot exception handler ----------
class SafeApplication(QApplication):
    """
    Captures exceptions raised inside Qt event handlers / slots.
    Without this, PySide apps can appear to "do nothing" on clicks,
    especially in frozen builds where stdout/stderr are not visible.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._handling_exception = False

    def notify(self, receiver, event):
        # QApplication.notify expects a QObject as the first argument.
        # Sometimes Qt passes non-QObjects (like QTableWidgetItem) which causes TypeError.
        if not isinstance(receiver, QObject):
            return False

        try:
            return super().notify(receiver, event)
        except Exception:
            if self._handling_exception:
                raise

            self._handling_exception = True
            try:
                tb = traceback.format_exc()
                safe_log_error("Unhandled exception in Qt event/slot:\n" + tb)

                try:
                    log_path = APP_DATA_DIR / "acasmart.log"
                    text = (
                        "❌ خطای داخلی رخ داد.\n\n"
                        "لطفاً فایل لاگ را برای پشتیبانی ارسال کنید:\n"
                        "%LOCALAPPDATA%\\AcaSmart\\acasmart.log\n"
                        "(یا)\n"
                        f"{log_path}"
                    )
                    QMessageBox.critical(self.activeWindow(), "خطای داخلی", text)
                except Exception:
                    pass
            finally:
                self._handling_exception = False

            return False

# ---------- Uncaught Exception Handler ----------
def log_uncaught_exceptions(exctype, value, tb):
    error_message = "".join(traceback.format_exception(exctype, value, tb))
    safe_log_error(error_message)

sys.excepthook = log_uncaught_exceptions

# ---------- Cleanup ----------
CLEANUP_FILE = APP_DATA_DIR / ".last_cleanup.txt"

def should_cleanup() -> bool:
    if not CLEANUP_FILE.exists():
        return True
    try:
        last_cleanup = datetime.strptime(CLEANUP_FILE.read_text().strip(), "%Y-%m-%d")
    except ValueError:
        return True
    return datetime.today() - last_cleanup >= timedelta(days=3)

def update_cleanup_timestamp():
    CLEANUP_FILE.write_text(datetime.today().strftime("%Y-%m-%d"))

def clear_local_log_file():
    try:
        with open(APP_DATA_DIR / "error.log", "w", encoding="utf-8") as f:
            f.truncate(0)
        print("🧹 Cleared local error.log file.")
    except Exception as e:
        safe_log_error(f"❌ Error clearing local log file: {e}")


if __name__ == "__main__":
    try:
        print("🚀 Starting AcaSmart application...")
        print(f"📁 Data dir: {APP_DATA_DIR}")
        print(f"📁 DB path : {DB_PATH}")
        print(f"📁 CWD     : {Path.cwd()}")

        if should_cleanup():
            try:
                clear_local_log_file()
                update_cleanup_timestamp()
            except Exception as e:
                safe_log_error(f"❌ Error during cleanup: {e}")

        print("🔧 Initializing database...")
        initialize_database()
        print("✅ Database initialized successfully")
        
        print("🎨 Starting GUI...")
    
        # (اختیاری) HiDPI
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    
        app = SafeApplication(sys.argv)
        ThemeManager.apply(app, mode=None)   # از QSettings می‌خوانَد؛ یا "light"/"dark"
        
        # Apply theme icon before starting the GUI
        try:
            from acasmart.ui.widgets.theme_manager import apply_theme_icon
            apply_theme_icon()
            print("🎨 Applied theme icon successfully")
        except Exception as e:
            print(f"⚠️ Could not apply theme icon: {e}")

        
        from acasmart.ui.windows.login_window import LoginWindow
        window = LoginWindow()
        window.show()
        print("✅ GUI started successfully")

        # سازگار با PySide6 قدیمی/جدید
        exit_code = app.exec() if hasattr(app, "exec") else app.exec_()
        sys.exit(exit_code)

    except Exception as e:
        print(f"❌ Critical error during startup: {e}")
        safe_log_error(f"Critical error during startup: {e}")
        traceback.print_exc()
        raise
