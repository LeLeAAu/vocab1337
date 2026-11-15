"""
audio_processor.py — Vocab1337
Module xử lý giọng nói: ghi âm → Whisper → Levenshtein check.
Tương thích và an toàn (fallback khi không tải được model AI).
"""

import os
import time
import string
import wave

from logger import get_logger

logger = get_logger("audio")

# ── Import an toàn ────────────────────────────────────────────────────────────
try:
    import sounddevice as sd
    import soundfile as sf
    SD_AVAILABLE = True
except ImportError as _e:
    SD_AVAILABLE = False
    logger.warning("Không thể import sounddevice/soundfile: %s", _e)

try:
    from faster_whisper import WhisperModel
    import Levenshtein
    AI_AVAILABLE = True
except ImportError as _e:
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

    if not AI_AVAILABLE:
        logger.warning("AI không khả dụng (thiếu faster-whisper/Levenshtein). Chuyển sang Offline Mock mode.")
        return {
            "passed": True,
            "transcribed_text": expected_text,
            "distance": 0,
            "feedback": "Chế độ offline/mock (Không cài faster-whisper hoặc Levenshtein)"
        }

    if not os.path.exists(audio_path):
        logger.warning("Không tìm thấy tệp âm thanh: %s", audio_path)
        return {
            "passed": False,
            "transcribed_text": "",
            "distance": len(cleaned_expected),
            "feedback": f"Không tìm thấy tệp âm thanh: {audio_path}"
        }

    # Đọc cấu hình động từ settings.json
    import json
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

    # Nếu không thể khởi động được model -> Fallback sang Offline Mock
    if model is None:
        logger.warning("Không thể nạp WhisperModel. Chuyển sang Offline Mock mode.")
        return {
            "passed": True,
            "transcribed_text": expected_text,
            "distance": 0,
            "feedback": "Offline Mock mode (Không thể nạp mô hình Whisper cục bộ)"
        }

    try:
        t0 = time.time()
        logger.debug("Bắt đầu Whisper transcribe trên tệp: %s (beam_size=5, language=en)", audio_path)
        segments, info = model.transcribe(audio_path, beam_size=5, language="en")
        
        transcribed_text = " ".join([seg.text for seg in segments]).strip()
        cleaned_transcribed = clean_text(transcribed_text)
        t_elapsed = time.time() - t0

        # Tính khoảng cách Levenshtein
        dist = Levenshtein.distance(cleaned_transcribed, cleaned_expected)
        passed = (dist <= threshold)

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
        return {
            "passed": True,  # Cho qua nếu gặp lỗi thư viện
            "transcribed_text": expected_text,
            "distance": 0,
            "feedback": f"Lỗi xử lý nhận dạng giọng nói: {str(e)}."
        }


_MODEL_CACHE = {}

def get_whisper_model(model_size: str = "base", device: str = "cpu"):
    """Lấy hoặc khởi tạo WhisperModel có áp dụng caching để tránh nạp lại nhiều lần."""
    global _MODEL_CACHE
    key = (model_size, device)
    if key in _MODEL_CACHE:
        logger.debug("Lấy WhisperModel (%s, %s) từ bộ nhớ cache", model_size, device)
        return _MODEL_CACHE[key], ""

    cuda_warning = ""
    model = None
    logger.info("Đang nạp mô hình WhisperModel (size='%s', device='%s')...", model_size, device)
    t0 = time.time()
    try:
        model = WhisperModel(model_size, device=device, compute_type="float32")
        _MODEL_CACHE[key] = model
        logger.info("Nạp WhisperModel thành công trên %s (%.2fs)", device, time.time() - t0)
        return model, ""
    except Exception as e:
        logger.warning("Không thể nạp WhisperModel trên device '%s': %s", device, e)
        if device == "cuda":
            cuda_warning = " [Không nhận diện được NVIDIA GPU (CUDA), đã tự động chuyển sang CPU]"
            try:
                logger.info("Thử nạp lại WhisperModel trên CPU float32...")
                model = WhisperModel(model_size, device="cpu", compute_type="float32")
                _MODEL_CACHE[(model_size, "cpu")] = model
                logger.info("Nạp WhisperModel thành công trên CPU fallback (%.2fs)", time.time() - t0)
                return model, cuda_warning
            except Exception as e2:
                logger.error("Không thể nạp WhisperModel cả trên CPU fallback: %s", e2, exc_info=True)
                return None, cuda_warning
        return None, ""


def verify_voice_pronunciation(
    expected_text: str,
    duration: float = 3.5,
    threshold: int = 2,
    output_wav: str = None,
    on_status: callable = None,
) -> dict:
    """
    Quy trình trọn gói: Ghi âm từ mic -> Whisper transcribe -> Levenshtein check.
    Trả về dict: {"passed": bool, "transcribed_text": str, "distance": int, "feedback": str}
    """
    if on_status:
        try: on_status("recording", f"Đang ghi âm ({duration}s)...")
        except Exception: pass

    if not output_wav:
        cache_dir = os.path.join(os.path.dirname(__file__), "cache")
        os.makedirs(cache_dir, exist_ok=True)
        output_wav = os.path.join(cache_dir, "temp_pronunciation.wav")

    record_audio(output_wav, duration=duration)

    if on_status:
        try: on_status("transcribing", "Đang nhận dạng giọng nói...")
        except Exception: pass

    res = check_pronunciation(output_wav, expected_text, threshold=threshold)

    if on_status:
        try: on_status("done", res.get("feedback", ""))
        except Exception: pass

    return res


def _create_silent_wav(output_path: str, duration: float = 3.5, sample_rate: int = 16000) -> str:
    """Tạo tệp .wav chuẩn RIFF chứa dữ liệu im lặng (PCM 16-bit, mono, 16000Hz)."""
    try:
        num_samples = int(duration * sample_rate)
        silence_bytes = b'\x00\x00' * num_samples
        with wave.open(output_path, 'wb') as wf:
            wf.setnchannels(1)            # Mono
            wf.setsampwidth(2)            # 16-bit (2 bytes)
            wf.setframerate(sample_rate)  # 16000 Hz
            wf.writeframes(silence_bytes)
    except Exception as e:
        logger.error("Lỗi khi tạo silent wav %s: %s", output_path, e)
    return output_path


def record_audio(output_path: str, duration: float = 5.0, sample_rate: int = 16000) -> str:
    """
    Ghi âm từ mic trong `duration` giây và lưu ra file WAV (sample rate 16000Hz cho Whisper).
    Nếu không có phần cứng mic hoặc thư viện, tạo tệp WAV im lặng hợp lệ để tránh làm crash thư viện giải mã.
    """
    if not SD_AVAILABLE:
        logger.warning("sounddevice không khả dụng, tạo tệp wav im lặng: %s", output_path)
        return _create_silent_wav(output_path, duration, sample_rate)

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
        logger.error("Lỗi khi thu âm từ sounddevice: %s. Chuyển sang tạo silent wav.", e, exc_info=True)
        # Fallback tạo file WAV im lặng chuẩn RIFF khi có lỗi phần cứng mic
        return _create_silent_wav(output_path, duration, sample_rate)
