"""
logger.py — Vocab1337
Hệ thống ghi log tập trung, chuẩn hóa và chuyên sâu phục vụ chẩn đoán & sửa lỗi.
- Đa đích: File xoay vòng (app.log, error.log), Console (stdout), và UI Ring Buffer (in-memory).
- Bắt lỗi tự động toàn cục (Global Uncaught Exception Hook & Threading Exception Hook).
- Thu thập chẩn đoán môi trường hệ thống (OS, Python, GPU/CUDA, Audio, DB).
- Hỗ trợ đổi Log Level động và xem log trực tiếp trên giao diện Flet.
"""

import os
import sys
import platform
import logging
import threading
from logging.handlers import RotatingFileHandler
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Dict, Optional, Any

# ── Đường dẫn thư mục & tệp log ────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.resolve()
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

APP_LOG_PATH = LOGS_DIR / "app.log"
ERROR_LOG_PATH = LOGS_DIR / "error.log"

# Định dạng chuẩn dành cho file log và console
LOG_FORMAT = "%(asctime)s | %(levelname)-7s | [%(name)s] [%(filename)s:%(lineno)d] [%(threadName)s] - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# ── In-Memory Ring Buffer cho UI Log Viewer ───────────────────────────────────
class MemoryLogHandler(logging.Handler):
    """
    Handler lưu trữ N bản ghi log gần nhất trong bộ nhớ (deque)
    phục vụ việc hiển thị trực tiếp lên giao diện ứng dụng (UI Log Viewer / Pipeline Studio).
    """
    def __init__(self, maxlen: int = 1000):
        super().__init__()
        self.maxlen = maxlen
        self.buffer: deque = deque(maxlen=maxlen)
        self._buf_lock = threading.RLock()
        self.listeners: List[Callable[[Dict[str, Any]], None]] = []

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            entry = {
                "timestamp": datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
                "time_short": datetime.fromtimestamp(record.created).strftime("%H:%M:%S"),
                "level": record.levelname,
                "name": record.name,
                "filename": record.filename,
                "lineno": record.lineno,
                "funcName": record.funcName,
                "threadName": record.threadName,
                "message": record.getMessage(),
                "formatted": msg,
                "exc_text": record.exc_text or (self.format(record) if record.exc_info else None)
            }
            with self._buf_lock:
                self.buffer.append(entry)
                current_listeners = list(self.listeners)

            # Bắn sự kiện tới các UI callback (không giữ lock)
            for listener in current_listeners:
                try:
                    listener(entry)
                except Exception:
                    pass
        except Exception:
            self.handleError(record)

    def add_listener(self, callback: Callable[[Dict[str, Any]], None]):
        with self._buf_lock:
            if callback not in self.listeners:
                self.listeners.append(callback)

    def remove_listener(self, callback: Callable[[Dict[str, Any]], None]):
        with self._buf_lock:
            if callback in self.listeners:
                self.listeners.remove(callback)

    def get_history(
        self,
        level: Optional[str] = None,
        query: Optional[str] = None,
        limit: int = 200
    ) -> List[Dict[str, Any]]:
        with self._buf_lock:
            items = list(self.buffer)

        if level and level.upper() != "ALL":
            target_level = level.upper()
            items = [item for item in items if item["level"] == target_level]

        if query and query.strip():
            q = query.strip().lower()
            items = [
                item for item in items
                if q in item["message"].lower() or q in item["name"].lower() or q in item["filename"].lower()
            ]

        return items[-limit:]

    def clear(self):
        with self._buf_lock:
            self.buffer.clear()


# Biến toàn cục quản lý Memory Handler
_memory_handler: Optional[MemoryLogHandler] = None
_is_initialized: bool = False
_current_level_str: str = "INFO"


# ── Console Handler an toàn trên Windows ─────────────────────────────────────
class SafeStreamHandler(logging.StreamHandler):
    """
    StreamHandler an toàn chống lỗi UnicodeEncodeError trên môi trường Windows Terminal
    hoặc khi output bị redirect qua pipe. Tự động chuyển đổi ký tự không map được bằng '?'.
    """
    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            stream = self.stream
            try:
                stream.write(msg + self.terminator)
                self.flush()
            except (UnicodeEncodeError, UnicodeError):
                enc = getattr(stream, "encoding", "utf-8") or "utf-8"
                safe_text = msg.encode(enc, errors="replace").decode(enc, errors="replace")
                stream.write(safe_text + self.terminator)
                self.flush()
        except Exception:
            self.handleError(record)


# ── Hàm khởi tạo Logging tập trung ───────────────────────────────────────────
def setup_logging(default_level: str = "INFO") -> logging.Logger:
    """
    Cấu hình toàn diện hệ thống logging cho Vocab1337:
    1. RotatingFileHandler: logs/app.log (tối đa 5MB x 5 backups)
    2. RotatingFileHandler: logs/error.log (chỉ WARN/ERROR/CRITICAL, tối đa 5MB x 3 backups)
    3. SafeStreamHandler: Console (stdout) với UTF-8 an toàn
    4. MemoryLogHandler: Buffer 1000 dòng log cho UI Flet
    """
    global _memory_handler, _is_initialized, _current_level_str

    level = getattr(logging, default_level.upper(), logging.INFO)
    _current_level_str = default_level.upper()

    # Đảm bảo console mã hóa UTF-8 an toàn nếu đang ở interactive TTY
    if sys.platform == "win32" and hasattr(sys.stdout, "isatty") and sys.stdout.isatty():
        try:
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            if hasattr(sys.stderr, "reconfigure"):
                sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Đảm bảo không gắn trùng handler nếu gọi lại
    if _is_initialized:
        set_log_level(default_level)
        return logging.getLogger("vocab1337")

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # 1. File app.log (Tất cả log từ level cấu hình trở lên)
    try:
        app_file_handler = RotatingFileHandler(
            APP_LOG_PATH,
            maxBytes=5 * 1024 * 1024,  # 5 MB
            backupCount=5,
            encoding="utf-8"
        )
        app_file_handler.setLevel(logging.DEBUG)  # Luôn lưu chi tiết vào file app.log nếu root cho phép
        app_file_handler.setFormatter(formatter)
        root_logger.addHandler(app_file_handler)
    except Exception as e:
        print(f"[LOGGER ERROR] Không thể khởi tạo app.log: {e}", file=sys.stderr)

    # 2. File error.log (Chỉ WARNING, ERROR, CRITICAL phục vụ sửa lỗi nhanh)
    try:
        error_file_handler = RotatingFileHandler(
            ERROR_LOG_PATH,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8"
        )
        error_file_handler.setLevel(logging.WARNING)
        error_file_handler.setFormatter(formatter)
        root_logger.addHandler(error_file_handler)
    except Exception as e:
        print(f"[LOGGER ERROR] Không thể khởi tạo error.log: {e}", file=sys.stderr)

    # 3. Console StreamHandler
    console_handler = SafeStreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 4. Memory Handler cho UI
    _memory_handler = MemoryLogHandler(maxlen=1000)
    _memory_handler.setLevel(logging.DEBUG)
    _memory_handler.setFormatter(formatter)
    root_logger.addHandler(_memory_handler)

    _is_initialized = True

    app_logger = logging.getLogger("vocab1337")
    app_logger.info("=== HỆ THỐNG GHI LOG VOCAB1337 ĐÃ KHỞI TẠO THÀNH CÔNG ===")
    app_logger.info(f"Log Level: {_current_level_str} | Thư mục logs: {LOGS_DIR}")
    return app_logger


def get_logger(name: str = "vocab1337") -> logging.Logger:
    """Trả về logger chuẩn hóa theo prefix 'vocab1337.'."""
    if not _is_initialized:
        setup_logging()

    if name == "vocab1337" or name.startswith("vocab1337."):
        return logging.getLogger(name)
    return logging.getLogger(f"vocab1337.{name}")


def set_log_level(level_name: str):
    """Thay đổi Log Level của ứng dụng trong thời gian thực."""
    global _current_level_str
    level = getattr(logging, level_name.upper(), logging.INFO)
    _current_level_str = level_name.upper()

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    for h in root_logger.handlers:
        if isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler):
            h.setLevel(level)

    logger = get_logger("core")
    logger.info(f"Đã thay đổi Log Level sang: {_current_level_str}")


def get_current_log_level() -> str:
    """Lấy tên Log Level hiện tại."""
    return _current_level_str


def get_memory_handler() -> Optional[MemoryLogHandler]:
    """Lấy handler in-memory để đăng ký UI listener hoặc truy xuất lịch sử log."""
    return _memory_handler


def get_logs_dir() -> Path:
    """Trả về đường dẫn tuyệt đối thư mục logs/."""
    return LOGS_DIR


# ── Bắt lỗi tự động toàn cục (Global Exception Hooks) ─────────────────────────
def install_exception_hooks():
    """
    Gắn hook toàn cục bắt các unhandled exception ở:
    1. Main UI Thread (sys.excepthook)
    2. Background Threads (threading.excepthook)
    Tất cả lỗi chưa được xử lý sẽ được ghi lại chi tiết vào error.log và app.log kèm traceback đầy đủ.
    """
    logger = get_logger("crash_handler")

    def handle_sys_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logger.critical(
            "UNCAUGHT EXCEPTION Ở TIẾN TRÌNH CHÍNH (MAIN THREAD):",
            exc_info=(exc_type, exc_value, exc_traceback)
        )

    sys.excepthook = handle_sys_exception

    def handle_thread_exception(args: threading.ExceptHookArgs):
        if issubclass(args.exc_type, KeyboardInterrupt):
            return
        logger.critical(
            f"UNCAUGHT EXCEPTION Ở LUỒNG NỀN [Thread: '{args.thread.name}' (ident={args.thread.ident})]:",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback)
        )

    if hasattr(threading, "excepthook"):
        threading.excepthook = handle_thread_exception

    logger.debug("Đã cài đặt Global Exception Hooks (Main thread & Background threads).")


# ── Thu thập chẩn đoán môi trường hệ thống ────────────────────────────────────
def log_system_diagnostics():
    """Ghi lại thông tin cấu hình môi trường, phần cứng, âm thanh và database khi app khởi động."""
    logger = get_logger("diagnostics")
    try:
        # 1. Hệ điều hành & Python
        py_ver = sys.version.replace("\n", " ")
        os_info = f"{platform.system()} {platform.release()} ({platform.version()}) Arch: {platform.machine()}"
        logger.info(f"[HỆ THỐNG] OS: {os_info}")
        logger.info(f"[HỆ THỐNG] Python: {py_ver}")
        logger.info(f"[HỆ THỐNG] Thư mục ứng dụng: {BASE_DIR}")

        # 2. Kiểm tra thư viện AI / Audio
        libs = {}
        for lib in ["flet", "sounddevice", "soundfile", "faster_whisper", "Levenshtein", "edge_tts", "sqlite3"]:
            try:
                mod = __import__(lib)
                libs[lib] = getattr(mod, "__version__", "Available")
            except ImportError as e:
                libs[lib] = f"MISSING ({e})"
        logger.info(f"[THƯ VIỆN] Trạng thái packages: {libs}")

        # 3. Kiểm tra GPU / CUDA
        try:
            import ctypes
            cuda_avail = False
            for dll in ["cublas64_12.dll", "cublas64_11.dll", "nvcuda.dll"]:
                try:
                    ctypes.CDLL(dll)
                    cuda_avail = True
                    logger.info(f"[PHẦN CỨNG] Đã phát hiện CUDA DLL: {dll}")
                    break
                except Exception:
                    pass
            if not cuda_avail:
                logger.info("[PHẦN CỨNG] Không tìm thấy CUDA DLL trực tiếp. Faster-Whisper sẽ sử dụng CPU float32.")
        except Exception as e:
            logger.debug(f"[PHẦN CỨNG] Kiểm tra CUDA DLL: {e}")

        # 4. Kiểm tra Thiết bị Âm thanh (Microphone & Loa)
        try:
            import sounddevice as sd
            devs = sd.query_devices()
            default_in = sd.default.device[0]
            default_out = sd.default.device[1]
            logger.info(f"[ÂM THANH] Thiết bị thu âm mặc định: index={default_in} | Thiết bị phát mặc định: index={default_out}")
            logger.debug(f"[ÂM THANH] Tổng số thiết bị audio phát hiện: {len(devs)}")
        except Exception as e:
            logger.warning(f"[ÂM THANH] Không thể truy vấn sounddevice: {e}")

        # 5. Kiểm tra SQLite DB
        db_path = BASE_DIR / "brain_archive.db"
        if db_path.exists():
            size_kb = db_path.stat().st_size / 1024
            logger.info(f"[DATABASE] brain_archive.db tồn tại ({size_kb:.1f} KB)")
        else:
            logger.warning(f"[DATABASE] brain_archive.db chưa được tạo tại {db_path}")

    except Exception as e:
        logger.error(f"Lỗi khi thu thập chẩn đoán hệ thống: {e}", exc_info=True)


# ── Hàm dọn dẹp log cũ ────────────────────────────────────────────────────────
def clean_old_logs(days: int = 14, keep_days: int = None) -> int:
    """Xóa các file raw_ai_responses hoặc file log cũ quá `days` ngày."""
    if keep_days is not None:
        days = keep_days
    logger = get_logger("cleanup")
    deleted_count = 0
    now = datetime.now()
    try:
        for pattern in ("*.txt", "*.log.*"):
            for f in LOGS_DIR.glob(pattern):
                try:
                    mtime = datetime.fromtimestamp(f.stat().st_mtime)
                    if (now - mtime).days > days:
                        f.unlink()
                        deleted_count += 1
                        logger.info(f"Đã xóa file log cũ: {f.name}")
                except Exception as e:
                    logger.warning(f"Không thể xóa file log {f.name}: {e}")
    except Exception as e:
        logger.error(f"Lỗi dọn dẹp log: {e}")
    return deleted_count
