"""
tts_processor.py — Vocab1337
Module xử lý Text-to-Speech bằng Edge-TTS (Microsoft Azure Neural Voice).
Tích hợp Smart Caching và Native Windows MCI Audio Player (không giật lag, không block UI).
"""

import os
import time
import ctypes
import hashlib
import asyncio
import threading
import subprocess

from logger import get_logger

logger = get_logger("tts")

try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError as _e:
    EDGE_TTS_AVAILABLE = False
    logger.warning("Không thể import edge_tts: %s", _e)

# Thư mục cache âm thanh
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "audio")
os.makedirs(CACHE_DIR, exist_ok=True)

# Danh sách giọng đọc đề xuất (ưu tiên chuẩn Anh - Anh / British English)
AVAILABLE_VOICES = [
    ("en-GB-SoniaNeural", "Sonia (Nữ - Anh, Chuẩn British RP thanh lịch — Khuyên dùng)"),
    ("en-GB-LibbyNeural", "Libby (Nữ - Anh, Chuẩn British tự nhiên, rất rõ chữ)"),
    ("en-GB-RyanNeural", "Ryan (Nam - Anh, Chuẩn British RP trầm ấm & truyền cảm)"),
    ("en-GB-ThomasNeural", "Thomas (Nam - Anh, Rõ ràng & Dứt khoát)"),
    ("en-GB-MaisieNeural", "Maisie (Nữ - Anh, Trẻ trung & Tự nhiên)"),
    ("en-US-JennyNeural", "Jenny (Nữ - Mỹ, Tự nhiên & Rõ chữ)"),
    ("en-US-GuyNeural", "Guy (Nam - Mỹ, Trầm ấm & Truyền cảm)"),
    ("en-US-AriaNeural", "Aria (Nữ - Mỹ, Biểu cảm & Sống động)"),
]

DEFAULT_VOICE = "en-GB-SoniaNeural"
DEFAULT_RATE = "+0%"

# MCI Native Audio Player
_mci = ctypes.windll.winmm.mciSendStringW if hasattr(ctypes, "windll") else None
_audio_lock = threading.Lock()
_alias_counter = 0


def _get_next_alias() -> str:
    global _alias_counter
    _alias_counter = (_alias_counter + 1) % 1000
    return f"v1337_tts_{_alias_counter}"


_current_alias = "v1337_tts_main"


def stop_audio():
    """Dừng và giải phóng bất kỳ âm thanh nào đang phát."""
    global _current_alias
    if not _mci:
        return
    try:
        _mci(f"stop {_current_alias}", None, 0, 0)
        _mci(f"close {_current_alias}", None, 0, 0)
    except Exception:
        pass


def _get_short_path(path: str) -> str:
    if hasattr(ctypes, "windll") and hasattr(ctypes.windll, "kernel32"):
        try:
            buf = ctypes.create_unicode_buffer(512)
            if ctypes.windll.kernel32.GetShortPathNameW(path, buf, 512):
                return buf.value
        except Exception:
            pass
    return path


def play_audio_file(file_path: str):
    """Phát file mp3 bằng Windows MCI Native không cần tiến trình ngoài."""
    global _current_alias
    if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
        logger.warning("Không thể phát âm thanh: tệp không tồn tại hoặc rỗng: %s", file_path)
        return

    if not _mci:
        logger.warning("Windows MCI không khả dụng trên hệ thống này")
        return

    with _audio_lock:
        stop_audio()
        _current_alias = _get_next_alias()
        abs_path = os.path.abspath(file_path)
        short_path = _get_short_path(abs_path)
        open_cmd = f'open "{short_path}" type mpegvideo alias {_current_alias}'
        res = _mci(open_cmd, None, 0, 0)
        if res == 0:
            logger.debug("MCI mở thành công alias '%s'. Đang phát: %s", _current_alias, abs_path)
            _mci(f"play {_current_alias}", None, 0, 0)
        else:
            err_buf = ctypes.create_unicode_buffer(256)
            if hasattr(ctypes, "windll") and hasattr(ctypes.windll, "winmm") and hasattr(ctypes.windll.winmm, "mciGetErrorStringW"):
                ctypes.windll.winmm.mciGetErrorStringW(res, err_buf, 256)
                logger.error("Lỗi lệnh MCI open (mã %d): %s (file: %s)", res, err_buf.value, file_path)
            else:
                logger.error("Lỗi lệnh MCI open (mã %d) khi mở tệp: %s", res, file_path)


def get_cache_path(text: str, voice: str, rate: str) -> str:
    """Tạo đường dẫn file cache theo md5 hash của (voice, rate, text)."""
    norm_text = text.strip().lower()
    raw_key = f"{voice}|{rate}|{norm_text}".encode("utf-8")
    hash_name = hashlib.md5(raw_key).hexdigest()
    return os.path.join(CACHE_DIR, f"{hash_name}.mp3")


async def _download_edge_tts(text: str, output_path: str, voice: str, rate: str):
    """Gọi Edge-TTS để tạo file mp3 chất lượng cao."""
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(output_path)


def _sapi_fallback(text: str):
    """Fallback an toàn bằng SAPI nếu hoàn toàn không có mạng và file chưa cache."""
    logger.info("Kích hoạt SAPI SpVoice fallback cho: '%s'", (text or "")[:40])
    try:
        safe_text = (text or "").replace("'", "''")
        ps_cmd = f"(New-Object -ComObject SAPI.SpVoice).Speak('{safe_text}')"
        creationflags = 0x08000000 if os.name == "nt" else 0
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            creationflags=creationflags,
            timeout=10,
        )
        logger.debug("SAPI SpVoice hoàn thành")
    except Exception as e:
        logger.error("Lỗi SAPI SpVoice fallback: %s", e, exc_info=True)


def speak(text: str, voice: str = None, rate: str = None, on_error: callable = None):
    """
    Phát âm thanh text trong background thread (không block UI).
    Tự động kiểm tra cache, nếu chưa có sẽ tải về qua Edge-TTS rồi phát ngay.
    """
    if not text or not text.strip():
        return

    clean_text = text.strip()
    act_voice = voice or DEFAULT_VOICE
    act_rate = rate or DEFAULT_RATE

    def _worker():
        target_file = get_cache_path(clean_text, act_voice, act_rate)

        # 1. Kiểm tra cache
        if os.path.exists(target_file) and os.path.getsize(target_file) > 100:
            logger.debug("TTS Cache HIT: '%s' -> %s (%d bytes)", clean_text[:35], os.path.basename(target_file), os.path.getsize(target_file))
            play_audio_file(target_file)
            return

        # 2. Tải qua Edge-TTS
        if EDGE_TTS_AVAILABLE:
            tmp_file = f"{target_file}.tmp_{os.getpid()}_{threading.get_ident()}"
            t0 = time.time()
            logger.info("TTS Cache MISS: Tải Edge-TTS cho '%s' (voice=%s, rate=%s)...", clean_text[:35], act_voice, act_rate)
            try:
                # Tạo event loop riêng cho thread này
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(_download_edge_tts(clean_text, tmp_file, act_voice, act_rate))
                loop.close()

                if os.path.exists(tmp_file) and os.path.getsize(tmp_file) > 100:
                    os.replace(tmp_file, target_file)
                    sz = os.path.getsize(target_file)
                    logger.info("Tải Edge-TTS thành công (%.2fs, %d bytes): %s", time.time() - t0, sz, os.path.basename(target_file))
                    play_audio_file(target_file)
                    return
                elif os.path.exists(tmp_file):
                    os.remove(tmp_file)
            except Exception as e:
                logger.warning("Lỗi tải Edge-TTS cho '%s': %s (fallback sang SAPI)", clean_text[:35], e, exc_info=True)
                if os.path.exists(tmp_file):
                    try:
                        os.remove(tmp_file)
                    except Exception:
                        pass
                if on_error:
                    try:
                        on_error(e)
                    except Exception:
                        pass

        # 3. Fallback SAPI nếu thất bại
        _sapi_fallback(clean_text)

    threading.Thread(target=_worker, daemon=True, name="TTS-Worker").start()
