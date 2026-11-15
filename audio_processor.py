"""
audio_processor.py — Vocab1337
Module xử lý giọng nói: ghi âm → Whisper → Levenshtein check.
Tương thích và an toàn (fallback khi không tải được model AI).
"""

import json
import os
import time
import string
import tempfile
import threading

from logger import get_logger

logger = get_logger("audio")

# ── Import an toàn ────────────────────────────────────────────────────────────
try:
    import sounddevice as sd
    import soundfile as sf
    SD_AVAILABLE = True
except (ImportError, OSError) as _e:
    SD_AVAILABLE = False
    logger.warning("Không thể import sounddevice/soundfile: %s", _e)

try:
    from faster_whisper import WhisperModel
    import Levenshtein
    AI_AVAILABLE = True
except (ImportError, OSError) as _e:
    AI_AVAILABLE = False
    logger.warning("Không thể import faster_whisper/Levenshtein: %s", _e)


def clean_text(text: str) -> str:
    """Loại bỏ ký tự đặc biệt, dấu câu và đưa về viết thường để so sánh."""
    text = text.lower().strip()
    # Loại bỏ punctuation
    translator = str.maketrans('', '', string.punctuation)
    text = text.translate(translator)
    # Loại bỏ khoảng trắng thừa
    return " ".join(text.split())


def _unavailable(feedback: str) -> dict:
    """Lỗi thiết bị/mô hình không phải là kết quả chấm điểm của người học."""
    return {
        "passed": False, "error": True, "transcribed_text": "",
        "distance": None, "feedback": feedback,
    }


def check_pronunciation(
    audio_path: str,
    expected_text: str,
    threshold: int = 2,  # Đổi sang 2 cho thoải mái sai lệch khoảng trắng/ký tự nhỏ
    model_size: str = "base",
    device: str = "cpu",
) -> dict:
    """
    Nhận dạng giọng nói từ file ghi âm và so sánh phát âm với expected_text.
    """
    cleaned_expected = clean_text(expected_text)

    if not cleaned_expected:
        return _unavailable("Chưa có từ hoặc câu mẫu để kiểm tra.")

    if not AI_AVAILABLE:
        return _unavailable("Chưa thể chấm: cần cài faster-whisper và Levenshtein.")

    if not os.path.exists(audio_path):
        logger.warning("Không tìm thấy tệp âm thanh: %s", audio_path)
        return _unavailable("Không tìm thấy bản ghi âm. Hãy thử ghi âm lại.")

    # Đọc cấu hình động từ settings.json
    settings_model = model_size
    settings_device = device
    try:
        if os.path.exists("settings.json"):
            with open("settings.json", "r", encoding="utf-8") as f:
                cfg = json.load(f)
                settings_model = cfg.get("whisper_model", model_size)
                settings_device = cfg.get("device", device)
    except Exception as e:
        logger.debug("Không thể đọc settings.json cho Whisper: %s", e)

    model, cuda_warning = get_whisper_model(settings_model, settings_device)

    # Không tự cho điểm khi mô hình không hoạt động.
    if model is None:
        return _unavailable("Chưa thể nạp mô hình nhận dạng. Kiểm tra cấu hình và thử lại.")

    try:
        t0 = time.time()
        logger.debug("Bắt đầu Whisper transcribe trên tệp: %s (beam_size=5, language=en)", audio_path)
        segments, info = model.transcribe(audio_path, beam_size=5, language="en")
        
        transcribed_text = " ".join([seg.text for seg in segments]).strip()
        cleaned_transcribed = clean_text(transcribed_text)
        t_elapsed = time.time() - t0

        # Tính khoảng cách Levenshtein
        dist = Levenshtein.distance(cleaned_transcribed, cleaned_expected)
        passed = bool(cleaned_transcribed) and dist <= threshold

        logger.info(
            "Whisper nhận dạng xong (%.2fs): '%s' | Kỳ vọng: '%s' | Levenshtein: %d (ngưỡng: %d) -> %s",
            t_elapsed, transcribed_text, cleaned_expected, dist, threshold, "ĐẠT" if passed else "CHƯA KHỚP"
        )

        feedback = f"Phát âm chuẩn ✓{cuda_warning}" if passed else f"Phát âm chưa khớp{cuda_warning} (Sai lệch: {dist})"

        return {
            "passed": passed,
            "transcribed_text": transcribed_text,
            "distance": dist,
            "feedback": feedback
        }

    except Exception as e:
        logger.error("Lỗi xử lý nhận dạng giọng nói Whisper cho %s: %s", audio_path, e, exc_info=True)
        return _unavailable("Chưa thể nhận dạng bản ghi âm. Hãy thử lại; điểm chưa được ghi nhận.")


_MODEL_CACHE = {}
_MODEL_WARNINGS = {}
_MODEL_LOCK = threading.Lock()


def get_whisper_model(model_size: str = "base", device: str = "cpu"):
    """Load once per configuration, including a cached CUDA -> CPU fallback."""
    key = (model_size, device)
    with _MODEL_LOCK:
        if key in _MODEL_CACHE:
            return _MODEL_CACHE[key], _MODEL_WARNINGS.get(key, "")
        if not AI_AVAILABLE:
            return None, ""
        try:
            model = WhisperModel(model_size, device=device, compute_type="float32")
            _MODEL_CACHE[key] = model
            return model, ""
        except Exception as exc:
            logger.warning("Không thể nạp Whisper trên %s: %s", device, exc)
            if device != "cuda":
                return None, ""

        warning = " [CUDA không khả dụng, đang sử dụng CPU]"
        cpu_key = (model_size, "cpu")
        try:
            model = _MODEL_CACHE.get(cpu_key)
            if model is None:
                model = WhisperModel(model_size, device="cpu", compute_type="float32")
                _MODEL_CACHE[cpu_key] = model
            # Alias the requested device so later calls do not retry CUDA or reload CPU.
            _MODEL_CACHE[key] = model
            _MODEL_WARNINGS[key] = warning
            return model, warning
        except Exception as exc:
            logger.error("Không thể nạp Whisper trên CPU fallback: %s", exc)
            return None, warning


def verify_voice_pronunciation(
    expected_text: str,
    duration: float = 3.5,
    threshold: int = 2,
    output_wav: str = None,
    on_status: callable = None,
) -> dict:
    """
    Quy trình trọn gói: Ghi âm từ mic -> Whisper transcribe -> Levenshtein check.
    Lỗi thiết bị/mô hình có error=True và distance=None; UI không chấm điểm lượt đó.
    """
    if on_status:
        try: on_status("recording", f"Đang ghi âm ({duration}s)...")
        except Exception: pass

    temporary = output_wav is None
    if temporary:
        cache_dir = os.path.join(os.path.dirname(__file__), "cache")
        os.makedirs(cache_dir, exist_ok=True)
        fd, output_wav = tempfile.mkstemp(suffix=".wav", dir=cache_dir)
        os.close(fd)

    try:
        record_audio(output_wav, duration=duration)
        if on_status:
            try: on_status("transcribing", "Đang nhận dạng giọng nói...")
            except Exception: pass
        res = check_pronunciation(output_wav, expected_text, threshold=threshold)
    except Exception as exc:
        logger.warning("Không thể ghi âm để kiểm tra: %s", exc)
        res = _unavailable("Không thể ghi âm. Kiểm tra micro và quyền truy cập rồi thử lại.")
    finally:
        if temporary:
            try:
                os.remove(output_wav)
            except OSError:
                pass

    if on_status:
        try: on_status("done", res.get("feedback", ""))
        except Exception: pass
    return res


def record_audio(output_path: str, duration: float = 5.0, sample_rate: int = 16000) -> str:
    """
    Ghi âm từ mic trong `duration` giây và lưu ra file WAV (sample rate 16000Hz cho Whisper).
    Báo lỗi khi không ghi âm được; không thay lời nói bằng âm thanh giả.
    """
    if not SD_AVAILABLE:
        raise RuntimeError("Thư viện ghi âm không khả dụng.")

    try:
        logger.debug("Bắt đầu ghi âm micro: duration=%.1fs, rate=%d -> %s", duration, sample_rate, output_path)
        # Record từ sounddevice (16000 Hz, 1 channel mono, float32)
        recording = sd.rec(
            int(duration * sample_rate),
            samplerate=sample_rate,
            channels=1,
            dtype='float32'
        )
        sd.wait()  # Chờ đến khi ghi âm hoàn tất
        
        # Lưu ra tệp bằng soundfile
        sf.write(output_path, recording, sample_rate)
        sz = os.path.getsize(output_path) if os.path.exists(output_path) else 0
        logger.debug("Thu âm thành công, file size=%d bytes", sz)
        return output_path
    except Exception as e:
        logger.error("Lỗi khi thu âm từ sounddevice: %s", e, exc_info=True)
        raise RuntimeError("Không thể thu âm từ micro.") from e
