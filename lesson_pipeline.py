"""
lesson_pipeline.py — Vocab1337
Pipeline sinh câu hỏi + flashcard tuần tự qua AI theo kiến trúc Story State Bible.

Luồng hoạt động (13 bước):
  Step 1→10 : Sinh từng câu hỏi một với Narrative Taxonomy & Cognitive Skill Rotation,
              mỗi bước cập nhật Story Bible State JSON (characters, events, mysteries...).
  Step 11   : Sinh 1 câu hỏi Final Evaluation (Master Challenge) tổng hợp toàn bộ manh mối.
  Step 12   : Tổng hợp toàn bộ câu chuyện thành Structured summary_story ([Beginning], [Development],...).
  Step 13   : Sinh toàn bộ Flashcard đa chiều (Nuance, Contrast, Usage Distinction, Story-anchored Example).

Hỗ trợ AI providers:
  - "ollama"  : Ollama cục bộ (http://localhost:11434)
  - "openai"  : OpenAI API (gpt-4o-mini, gpt-4o, ...)
  - "gemini"  : Google Gemini API (gemini-3.7-flash, gemini-3.5-flash, ...)
"""

import json
import os
import re
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from logger import get_logger

logger = get_logger("pipeline")

from story_taxonomy import (
    initial_story_state,
    validate_or_repair_story_state,
    format_story_taxonomy,
    COGNITIVE_SKILLS,
    TAXONOMY_PRESETS,
)

# ── Hằng số ───────────────────────────────────────────────────────────────────
PROMPTS_DIR = Path(__file__).parent / "prompts"

# Thứ tự xoay vòng loại câu hỏi và thao tác tư duy cho 10 bước (indices 0-9)
QUESTION_TYPE_ROTATION = [
    "single",       # 1: single choice - contextual inference
    "multiple",     # 2: multiple select - holistic deduction
    "fill_blank",   # 3: fill in the blank - direct lexical fit
    "matching",     # 4: matching pairs with distractors
    "single",       # 5: single choice - incorrect usage detection
    "single",       # 6: single choice - error identification
    "single",       # 7: single choice - causal reasoning
    "multiple",     # 8: multiple select - implication & contrast
    "fill_blank",   # 9: fill in the blank - narrative climax setup
    "matching",     # 10: matching concepts to world anomalies
]

COGNITIVE_SKILL_ROTATION = [
    "contextual_inference",
    "context_inconsistency",
    "literal_context",
    "semantic_distinction",
    "incorrect_usage_detection",
    "error_identification",
    "causal_reasoning",
    "implication",
    "hidden_relationship",
    "classification",
]


# ── Đọc file prompt ────────────────────────────────────────────────────────────
def _load_prompt(filename: str) -> str:
    """Đọc nội dung file prompt. Raise FileNotFoundError nếu thiếu."""
    path = PROMPTS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Prompt file không tìm thấy: {path}")
    return path.read_text(encoding="utf-8")


def _fill(template: str, **kwargs) -> str:
    """
    Thay thế các placeholder {key} trong template bằng giá trị tương ứng.
    Chỉ thay thế đúng key được truyền vào, giữ nguyên các cặp {} khác.
    """
    for key, value in kwargs.items():
        template = template.replace("{" + key + "}", str(value))
    return template


# ══════════════════════════════════════════════════════════════════════════════
# ── AI CALL WRAPPER ───────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class PipelineCancelledException(Exception):
    """Ngoại lệ khi người dùng chủ động hủy pipeline giữa chừng."""
    pass


def _call_ai_raw(
    user_prompt: str,
    system_prompt: str,
    provider: str,
    model: str,
    api_key: str = "",
    timeout: int = 120,
) -> str:
    """Gọi AI thực sự theo provider."""
    provider = provider.lower().strip()

    if provider == "ollama":
        return _call_ollama(user_prompt, system_prompt, model, timeout)

    elif provider == "openai":
        if not api_key:
            raise ValueError("OpenAI API key chưa được cấu hình trong Settings.")
        return _call_openai(user_prompt, system_prompt, model, api_key, timeout)

    elif provider == "gemini":
        if not api_key:
            raise ValueError("Gemini API key chưa được cấu hình trong Settings.")
        return _call_gemini(user_prompt, system_prompt, model, api_key, timeout)

    else:
        raise ValueError(f"AI provider không hợp lệ: '{provider}'. Chọn: ollama / openai / gemini")


def _call_ai(
    user_prompt: str,
    system_prompt: str,
    provider: str,
    model: str,
    api_key: str = "",
    timeout: int = 120,
    stop_event: threading.Event = None,
) -> str:
    """
    Gọi AI có hỗ trợ kiểm tra ngắt (stop_event) ngay lập tức.
    Poll stop_event mỗi 0.3s để ngắt ngay khi user nhấn Hủy.
    """
    if stop_event and stop_event.is_set():
        raise PipelineCancelledException("Pipeline bị hủy bởi người dùng.")

    import time
    from concurrent.futures import TimeoutError as FuturesTimeoutError

    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(
            _call_ai_raw, user_prompt, system_prompt, provider, model, api_key, timeout
        )
        start_time = time.monotonic()
        while True:
            if stop_event and stop_event.is_set():
                executor.shutdown(wait=False, cancel_futures=True)
                raise PipelineCancelledException("Pipeline bị hủy bởi người dùng.")
            try:
                res = future.result(timeout=0.3)
                if stop_event and stop_event.is_set():
                    raise PipelineCancelledException("Pipeline bị hủy bởi người dùng.")
                executor.shutdown(wait=False)
                return res
            except FuturesTimeoutError:
                if future.done():
                    raise
                if time.monotonic() - start_time > timeout:
                    executor.shutdown(wait=False, cancel_futures=True)
                    raise TimeoutError(f"AI phản hồi quá lâu (timeout {timeout}s). Hãy thử model nhẹ hơn.")
    except Exception:
        executor.shutdown(wait=False, cancel_futures=True)
        raise


def _call_ollama(user_prompt: str, system_prompt: str, model: str, timeout: int) -> str:
    """Gọi Ollama REST API cục bộ."""
    try:
        import ollama as ollama_sdk
        response = ollama_sdk.Client(timeout=timeout).chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            format="json",
            options={"temperature": 0.4},
        )
        content = ""
        if hasattr(response, "message") and hasattr(response.message, "content"):
            content = (response.message.content or "").strip()
        elif isinstance(response, dict):
            msg = response.get("message", {})
            content = (msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")).strip()
        return content
    except ImportError:
        pass  # Fallback HTTP nếu chưa cài ollama SDK

    # Fallback qua HTTP endpoint
    url = "http://localhost:11434/api/chat"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "format": "json",
        "stream": False,
        "options": {"temperature": 0.4},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as res:
        data = json.loads(res.read().decode("utf-8"))
        return data.get("message", {}).get("content", "").strip()


def _call_openai(user_prompt: str, system_prompt: str, model: str, api_key: str, timeout: int) -> str:
    """Gọi OpenAI Chat Completions API với xử lý lỗi HTTP chi tiết."""
    url = "https://api.openai.com/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "temperature": 0.4,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            data = json.loads(res.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            if not content:
                raise ValueError("OpenAI trả về nội dung rỗng.")
            return content.strip()
    except urllib.error.HTTPError as err:
        try:
            err_body = err.read().decode("utf-8")
            err_json = json.loads(err_body)
            msg = err_json.get("error", {}).get("message", str(err))
        except Exception:
            msg = str(err)
        raise ValueError(f"OpenAI API Lỗi ({err.code}): {msg}")


LOGS_DIR = Path(__file__).parent / "logs"


def _log_ai_raw_response(
    provider: str,
    model: str,
    stage_name: str,
    raw_content: str,
    is_error: bool = False,
    error_msg: str = "",
):
    """Ghi lại 100% nội dung phản hồi thô của AI vào file log chi tiết để người dùng dễ kiểm tra/debug."""
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        from datetime import datetime
        now_dt = datetime.now()
        date_str = now_dt.strftime("%Y-%m-%d")
        time_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
        log_file = LOGS_DIR / f"raw_ai_responses_{date_str}.txt"

        status_tag = f"ERROR ({error_msg})" if is_error else "SUCCESS"
        divider = "=" * 80
        entry = (
            f"\n{divider}\n"
            f"[{time_str}] [{status_tag}] Provider: {provider.upper()} | Model: {model} | Stage: {stage_name}\n"
            f"{'-' * 80}\n"
            f"RAW AI RESPONSE CONTENT ({len(raw_content)} chars):\n"
            f"{raw_content}\n"
            f"{divider}\n"
        )
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(entry)

        if is_error:
            logger.warning("[Pipeline AI Error] Stage '%s' (%s/%s): %s", stage_name, provider, model, error_msg)
        else:
            logger.debug("[Pipeline AI Response] Stage '%s' (%s/%s) nhận %d ký tự", stage_name, provider, model, len(raw_content))
    except Exception as e:
        logger.error("Lỗi khi ghi file raw AI log: %s", e)


GEMINI_MODEL_FAILOVER_POOL = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
]


def _call_gemini(user_prompt: str, system_prompt: str, model: str, api_key: str, timeout: int) -> str:
    """
    Gọi Google Gemini generateContent API với cơ chế failover xoay vòng đa model thông minh.
    Tự động chuyển ngay sang model khả dụng khác khi gặp lỗi 429 (hết quota free), 503 (quá tải) hoặc timeout.
    """
    import time
    import re

    # Xây dựng danh sách model thử nghiệm ưu tiên: model được chọn -> các model khác trong pool
    models_to_try = [model]
    for m in GEMINI_MODEL_FAILOVER_POOL:
        if m != model and m not in models_to_try:
            models_to_try.append(m)

    last_err = None
    start_call_time = time.time()

    for model_idx, current_model in enumerate(models_to_try):
        # Tính toán timeout thích ứng: Nếu còn model dự phòng trong pool, không để 1 model bị treo quá 30s
        elapsed = time.time() - start_call_time
        remaining = timeout - elapsed
        if remaining <= 5:
            break

        has_fallback = model_idx < len(models_to_try) - 1
        per_model_timeout = max(10, min(30, int(remaining - 5))) if has_fallback else max(10, int(remaining - 2))

        clean_model = current_model.replace("models/", "").strip()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}:generateContent?key={api_key}"
        is_gemma = "gemma" in clean_model.lower()
        if is_gemma:
            combined_prompt = f"[SYSTEM INSTRUCTION]\n{system_prompt}\n\n[USER REQUEST]\n{user_prompt}"
            payload = {
                "contents": [{"parts": [{"text": combined_prompt}]}],
                "generationConfig": {"temperature": 0.4},
            }
        else:
            payload = {
                "system_instruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"parts": [{"text": user_prompt}]}],
                "generationConfig": {
                    "temperature": 0.4,
                    "responseMimeType": "application/json",
                },
            }

        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data_bytes,
            headers={"Content-Type": "application/json"},
        )

        max_attempts = 1 if has_fallback else 2
        for attempt in range(max_attempts):
            try:
                with urllib.request.urlopen(req, timeout=per_model_timeout) as res:
                    data = json.loads(res.read().decode("utf-8"))
                    candidates = data.get("candidates", [])
                    if not candidates:
                        feedback = data.get("promptFeedback", {})
                        raise ValueError(f"Gemini từ chối xử lý prompt (Feedback: {feedback})")

                    cand = candidates[0]
                    parts = cand.get("content", {}).get("parts", [])
                    if not parts:
                        reason = cand.get("finishReason", "UNKNOWN")
                        raise ValueError(f"Gemini không trả về văn bản (Lý do finishReason: {reason})")

                    # Lọc các text parts bỏ qua thinking/thought parts nếu có
                    valid_parts = [p.get("text", "") for p in parts if not p.get("thought", False) and p.get("text")]
                    if not valid_parts:
                        valid_parts = [p.get("text", "") for p in parts if p.get("text")]

                    text = "".join(valid_parts).strip()
                    if not text:
                        raise ValueError("Gemini phản hồi văn bản rỗng.")
                    return text

            except urllib.error.HTTPError as err:
                try:
                    err_body = err.read().decode("utf-8", errors="ignore")
                    err_json = json.loads(err_body)
                    msg = err_json.get("error", {}).get("message", str(err))
                except Exception:
                    msg = str(err)

                last_err = ValueError(f"Gemini API ({current_model}) Lỗi {err.code}: {msg}")

                # Khi gặp 429 hoặc 503: Nếu còn model khác trong pool -> chuyển ngay lập tức sang model khác!
                if err.code in (429, 503, 500, 502, 504):
                    if has_fallback:
                        logger.warning("Gemini model '%s' gặp lỗi HTTP %d: %s. Chuyển sang model tiếp theo trong pool...", current_model, err.code, msg[:100])
                        break
                    else:
                        logger.warning("Gemini model '%s' gặp lỗi HTTP %d (model cuối cùng trong pool): %s", current_model, err.code, msg[:100])
                        if attempt == 0 and max_attempts > 1:
                            match = re.search(r"retry in ([0-9.]+)s", msg)
                            wait_s = min(float(match.group(1)) + 1.0, 15.0) if match else 3.0
                            time.sleep(wait_s)
                            continue
                        raise last_err
                else:
                    # Lỗi khác (400, 401, 403, 404) -> chuyển model nếu có
                    if has_fallback:
                        logger.warning("Gemini model '%s' gặp lỗi HTTP %d: %s. Chuyển sang model tiếp theo...", current_model, err.code, msg[:100])
                        break
                    raise last_err

            except (urllib.error.URLError, TimeoutError, Exception) as err:
                last_err = err
                if has_fallback:
                    logger.warning("Gemini model '%s' gặp lỗi mạng/timeout: %s. Chuyển sang model tiếp theo...", current_model, err)
                    break
                if attempt == 0 and max_attempts > 1:
                    time.sleep(2.0)
                    continue
                raise err

    if last_err:
        raise last_err
    raise ValueError("Toàn bộ các model Gemini trong Pool đều không phản hồi.")


# ══════════════════════════════════════════════════════════════════════════════
# ── JSON PARSER ĐA KHỐI & LINH HOẠT TỰ ĐỘNG PHỤC HỒI ──────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

def _parse_json(content: str, stage_name: str = "", provider: str = "", model: str = "") -> dict:
    """
    Parse JSON từ chuỗi AI trả về với thuật toán tự động phục hồi cấu trúc (Auto JSON Repair).
    Tự động xử lý: markdown fences, thiếu ngoặc đóng }, ngoặc đóng mảng ], thiếu đóng nháy kép,
    dấu phẩy dư thừa (trailing commas), hoặc nhiều khối JSON.
    Tự động lưu lại raw response vào logs/raw_ai_responses_*.txt.
    """
    if not content or not content.strip():
        _log_ai_raw_response(provider, model, stage_name, content or "(EMPTY)", is_error=True, error_msg="Empty response")
        raise ValueError("AI trả về phản hồi rỗng.")

    import re
    s = content.strip()

    # 1. Kiểm tra nhiều khối markdown ```json ... ```
    if "```json" in s:
        blocks = [b.split("```")[0].strip() for b in s.split("```json")[1:] if b.strip()]
        if len(blocks) >= 2:
            try:
                q_obj = _parse_json(blocks[0], stage_name=f"{stage_name} [part 1]", provider=provider, model=model)
                story_obj = _parse_json(blocks[1], stage_name=f"{stage_name} [part 2]", provider=provider, model=model)
                _log_ai_raw_response(provider, model, stage_name, content, is_error=False)
                return {"question": q_obj, "updated_story": story_obj}
            except Exception:
                s = blocks[0]
        elif len(blocks) == 1:
            s = blocks[0]

    elif "```" in s:
        s = s.split("```")[1].split("```")[0].strip()

    # 2. Thử parse trực tiếp
    try:
        data = json.loads(s, strict=False)
        _log_ai_raw_response(provider, model, stage_name, content, is_error=False)
        return data
    except Exception:
        pass

    # 3. Định vị điểm bắt đầu của JSON object hoặc array
    first_brace = s.find('{')
    first_bracket = s.find('[')

    start_idx = -1
    if first_brace != -1 and (first_bracket == -1 or first_brace < first_bracket):
        start_idx = first_brace
    elif first_bracket != -1:
        start_idx = first_bracket

    if start_idx != -1:
        candidate = s[start_idx:].strip()

        # Thử parse candidate trực tiếp
        try:
            data = json.loads(candidate, strict=False)
            _log_ai_raw_response(provider, model, stage_name, content, is_error=False)
            return data
        except Exception:
            pass

        # Thử xóa C++ comments và dấu phẩy dư trước } hoặc ] (trailing commas)
        cleaned = re.sub(r'//.*', '', candidate)
        cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)
        try:
            data = json.loads(cleaned, strict=False)
            _log_ai_raw_response(provider, model, stage_name, content, is_error=False)
            return data
        except Exception:
            pass

        # 4. Thuật toán cân bằng ngoặc và chuỗi thông minh (Bracket & Quote Stack Auto-Repair)
        fixed_chars = []
        in_string = False
        escape = False
        stack = []
        has_opened = False
        for ch in candidate:
            if escape:
                escape = False
                fixed_chars.append(ch)
                continue
            if ch == '\\':
                escape = True
                fixed_chars.append(ch)
                continue
            if ch == '"':
                in_string = not in_string
                fixed_chars.append(ch)
                continue
            if not in_string:
                if ch in '{[':
                    has_opened = True
                    stack.append(ch)
                elif ch == '}':
                    if stack and stack[-1] == '{':
                        stack.pop()
                elif ch == ']':
                    if stack and stack[-1] == '[':
                        stack.pop()
            fixed_chars.append(ch)
            # Ngắt ngay khi cấu trúc JSON ngoài cùng đóng hoàn tất (loại bỏ mọi lời bình luận trailing phía sau)
            if has_opened and not in_string and len(stack) == 0:
                break

        # Nếu chuỗi nháy kép chưa đóng -> đóng nháy kép
        if in_string:
            fixed_chars.append('"')

        # Đóng tất cả các ngoặc mở còn tồn đọng theo đúng thứ tự LIFO
        while stack:
            opener = stack.pop()
            if opener == '{':
                fixed_chars.append('}')
            elif opener == '[':
                fixed_chars.append(']')

        repaired_str = "".join(fixed_chars)
        repaired_str = re.sub(r'//.*', '', repaired_str)
        repaired_str = re.sub(r',\s*([}\]])', r'\1', repaired_str)
        try:
            data = json.loads(repaired_str, strict=False)
            _log_ai_raw_response(provider, model, stage_name, content, is_error=False)
            return data
        except Exception:
            pass

    _log_ai_raw_response(provider, model, stage_name, content, is_error=True, error_msg="JSON decode error")
    preview = s.replace("\n", " ")[:120]
    raise ValueError(
        f"Phản hồi từ AI không đúng định dạng JSON: '{preview}...'\n"
        f"[Log chi tiết toàn bộ câu trả lời gốc đã được lưu vào logs/raw_ai_responses_*.txt]"
    )


# ══════════════════════════════════════════════════════════════════════════════
# ── PIPELINE SYSTEM PROMPT ────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

PIPELINE_SYSTEM_PROMPT = (
    "You are an expert academic English vocabulary curriculum architect and narrative designer. "
    "You ALWAYS output ONLY valid JSON matching the requested schema with no surrounding prose or markdown formatting."
)


# ══════════════════════════════════════════════════════════════════════════════
# ── BƯỚC 1-10: SINH TỪNG CÂU HỎI & CẬP NHẬT STORY STATE BIBLE ────────────────
# ══════════════════════════════════════════════════════════════════════════════

def _normalize_question(q_data: dict, expected_type: str = "single", question_num: int = 1, total_q: int = 10) -> dict:
    """
    Chuẩn hóa và tự động sửa lỗi cho dict câu hỏi sinh ra từ AI:
    - Đồng bộ các trường alias (q <-> question, story <-> context/passage).
    - Chuẩn hóa 'correct': chuyển chữ cái 'A', 'B', 'C', 'D' hoặc chuỗi thành chỉ mục số nguyên 0, 1, 2, 3.
    - Với dạng 'multiple', chuẩn hóa correct thành list các chỉ mục [0, 2].
    - Đảm bảo options luôn là list hợp lệ không rỗng.
    - Fallback an toàn cho dạng 'matching' nếu AI quên sinh pairs.
    """
    if not isinstance(q_data, dict):
        q_data = {}

    q = dict(q_data)

    # 1. Đồng bộ q / question
    q_str = str(q.get("q") or q.get("question") or q.get("prompt") or "").strip()
    if not q_str:
        q_str = f"Reading Comprehension Question {question_num}"
    q["q"] = q_str
    q["question"] = q_str

    # 2. Đồng bộ story / context
    story_str = str(q.get("story") or q.get("context") or q.get("passage") or q.get("contextual_text") or "").strip()
    q["story"] = story_str
    q["context"] = story_str

    # 3. Instruction & Type
    raw_type = str(q.get("type", expected_type or "single")).strip().lower()
    if raw_type in ["multiple_choice_single", "mcq_single", "single_choice"]:
        q_type = "single"
    elif raw_type in ["multiple_choice_multiple", "multi_select", "multiple_select"]:
        q_type = "multiple"
    else:
        q_type = raw_type
    q["type"] = q_type

    if not q.get("instruction"):
        if q_type == "multiple":
            q["instruction"] = "Multiple choice - multiple answers"
        elif q_type == "matching":
            q["instruction"] = "Matching concepts"
        elif q_type == "fill_blank":
            q["instruction"] = "Fill in the blank"
        else:
            q["instruction"] = "Multiple choice - single answer"

    # 4. Options
    raw_opts = q.get("options", [])
    if isinstance(raw_opts, dict):
        options = [str(v) for v in raw_opts.values()]
    elif isinstance(raw_opts, list):
        options = [str(o) for o in raw_opts if o is not None]
    else:
        options = []

    # 5. Matching validation & fallback
    if q_type == "matching":
        raw_pairs = q.get("pairs", [])
        valid_pairs = []
        if isinstance(raw_pairs, dict):
            for k, v in raw_pairs.items():
                if k is not None and v is not None:
                    valid_pairs.append({
                        "id": len(valid_pairs) + 1,
                        "left": str(k).strip(),
                        "right": str(v).strip(),
                    })
        elif isinstance(raw_pairs, list):
            for p in raw_pairs:
                if isinstance(p, dict):
                    l_val = p.get("left") or p.get("term") or p.get("word") or p.get("q")
                    r_val = p.get("right") or p.get("definition") or p.get("meaning") or p.get("ans")
                    if l_val is not None and r_val is not None:
                        valid_pairs.append({
                            "id": p.get("id", len(valid_pairs) + 1),
                            "left": str(l_val).strip(),
                            "right": str(r_val).strip(),
                        })
        if not valid_pairs:
            # Fallback sang single nếu matching không có pairs hợp lệ
            q["type"] = "single"
            q_type = "single"
        else:
            q["pairs"] = valid_pairs
            if not isinstance(q.get("distractors"), list):
                q["distractors"] = []

    if q_type != "matching":
        if len(options) < 2:
            options = ["Option A", "Option B", "Option C", "Option D"]
        q["options"] = options

    # 6. Correct normalization (A, B, C, D -> 0, 1, 2, 3)
    raw_corr = q.get("correct")
    if raw_corr is None:
        raw_corr = q.get("correct_index")
    if raw_corr is None:
        raw_corr = q.get("correct_answer")
    if raw_corr is None:
        raw_corr = q.get("answer")
    letter_map = {"a": 0, "b": 1, "c": 2, "d": 3, "e": 4, "f": 5}

    def _parse_idx(val):
        if isinstance(val, int):
            return val
        if isinstance(val, str):
            s_val = val.strip().lower()
            if s_val in letter_map:
                return letter_map[s_val]
            for k, idx in letter_map.items():
                if f"option {k}" in s_val or f"choice {k}" in s_val or f"({k})" in s_val:
                    return idx
            digits = re.sub(r"[^\d]", "", s_val)
            if digits:
                try:
                    return int(digits)
                except Exception:
                    pass
        return 0

    if q_type == "multiple":
        corr_list = []
        if isinstance(raw_corr, list):
            for c in raw_corr:
                corr_list.append(_parse_idx(c))
        elif isinstance(raw_corr, str):
            parts = [p.strip() for p in raw_corr.replace(";", ",").split(",") if p.strip()]
            for p in parts:
                corr_list.append(_parse_idx(p))
        elif isinstance(raw_corr, int):
            corr_list = [raw_corr]
        else:
            corr_list = [0]
        num_o = len(q.get("options", [])) or 4
        corr_list = [c if 0 <= c < num_o else 0 for c in corr_list]
        q["correct"] = list(set(corr_list)) if corr_list else [0]
    else:
        c_idx = _parse_idx(raw_corr)
        num_o = len(q.get("options", [])) or 4
        if c_idx >= num_o or c_idx < 0:
            c_idx = 0
        q["correct"] = c_idx

    # 7. Explanation
    q["explain"] = q.get("explain") or q.get("explanation") or "No detailed explanation provided."

    return q


def _generate_one_question(
    question_number: int,
    total_questions: int,
    updated_story_state: dict,
    story_taxonomy_formatted: str,
    vocab_list: list[dict],
    provider: str,
    model: str,
    api_key: str,
    timeout: int,
    stop_event: threading.Event = None,
    user_notes: str = "",
) -> dict:
    """
    Gọi AI tạo 1 câu hỏi đọc hiểu và cập nhật Story Bible state.
    Trả về: { "question": dict, "updated_story": dict }
    """
    idx = (question_number - 1) % len(QUESTION_TYPE_ROTATION)
    question_type = QUESTION_TYPE_ROTATION[idx]
    cognitive_skill = COGNITIVE_SKILL_ROTATION[idx % len(COGNITIVE_SKILL_ROTATION)]

    # Phân bổ từ vựng: Nếu số từ vựng nhiều hơn số câu hỏi, gom nhóm đều vào từng câu để không bỏ sót từ
    vocab_count = len(vocab_list)
    if vocab_count > 0:
        if vocab_count > total_questions:
            start_v_idx = (question_number - 1) * vocab_count // total_questions
            end_v_idx = question_number * vocab_count // total_questions
            assigned_items = vocab_list[start_v_idx:max(start_v_idx + 1, end_v_idx)]
            target_vocab_str = "; ".join(
                f"{v.get('word', '')} ({v.get('pos') or 'n/a'}): {v.get('definition_short_en') or v.get('definition_vi') or ''}".strip()
                for v in assigned_items if v.get("word")
            ) or f"{assigned_items[0].get('word', '')}"
        else:
            target_vocab_item = vocab_list[(question_number - 1) % vocab_count]
            pos_val = target_vocab_item.get('pos') or 'n/a'
            def_val = target_vocab_item.get('definition_short_en') or target_vocab_item.get('definition_vi') or ''
            target_vocab_str = f"{target_vocab_item.get('word', '')} ({pos_val}): {def_val}".strip()
    else:
        target_vocab_str = "General academic context"

    # Tóm tắt toàn bộ danh sách từ vựng
    vocab_summary = "\n".join(
        f"- {v.get('word', '')} ({v.get('pos') or 'n/a'}): {v.get('definition_short_en') or v.get('definition_vi') or ''}".strip()
        for v in vocab_list if v.get("word")
    )

    # Serialize Story State thành JSON đẹp mắt
    state_json_str = json.dumps(updated_story_state, ensure_ascii=False, indent=2)

    # Format user_notes cho prompt (nếu trống thì thông báo rõ ràng)
    notes_block = user_notes.strip() if user_notes and user_notes.strip() else "(No personal notes provided.)"

    prompt_template = _load_prompt("pipeline_step_question.txt")
    user_prompt = _fill(
        prompt_template,
        question_number=question_number,
        total_questions=total_questions,
        vocab_list=vocab_summary,
        target_vocabulary=target_vocab_str,
        story_taxonomy=story_taxonomy_formatted,
        cognitive_skill=cognitive_skill,
        question_type=question_type,
        updated_story=state_json_str,
        user_notes=notes_block,
    )

    content = _call_ai(user_prompt, PIPELINE_SYSTEM_PROMPT, provider, model, api_key, timeout, stop_event=stop_event)
    data = _parse_json(content, stage_name=f"Step {question_number} Question ({question_type})", provider=provider, model=model)

    # Đảm bảo có key question và updated_story
    if "question" not in data:
        # Nếu AI trả về trực tiếp dict của question
        if "type" in data and ("q" in data or "story" in data or "options" in data):
            data = {"question": data, "updated_story": updated_story_state}
        else:
            raise ValueError(f"AI output ở Step {question_number} thiếu key 'question'.")

    raw_story = data.get("updated_story")
    validated_state = validate_or_repair_story_state(raw_story, previous_state=updated_story_state)
    data["updated_story"] = validated_state

    # Chuẩn hóa cấu trúc câu hỏi
    data["question"] = _normalize_question(data["question"], expected_type=question_type, question_num=question_number, total_q=total_questions)

    return data


# ══════════════════════════════════════════════════════════════════════════════
# ── BƯỚC 11: SINH FINAL EVALUATION (MASTER CHALLENGE) ─────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

def _generate_challenge(
    questions: list[dict],
    vocab_list: list[dict],
    updated_story_state: dict,
    story_taxonomy_formatted: str,
    provider: str,
    model: str,
    api_key: str,
    timeout: int,
    stop_event: threading.Event = None,
    user_notes: str = "",
    challenge_step: int = 11,
) -> dict:
    """
    Tạo câu hỏi Final Evaluation (Master Challenge) tổng hợp toàn bộ câu chuyện.
    """
    vocab_summary = "\n".join(
        f"- {v.get('word', '')} ({v.get('pos', 'n/a')}): {v.get('definition_short_en', v.get('definition_vi', ''))}"
        for v in vocab_list
    )

    # Liệt kê tóm tắt các câu hỏi trước đó và đoạn văn
    qs_summary_lines = []
    for i, q in enumerate(questions, 1):
        q_text = q.get('q', q.get('question', ''))
        story_snip = (q.get('story', '') or q.get('context', ''))[:120]
        qs_summary_lines.append(f"Question {i} [{q.get('type', 'single')}]: Story snip: '{story_snip}...' -> Q: {q_text}")
    all_prev_questions_text = "\n\n".join(qs_summary_lines)

    state_json_str = json.dumps(updated_story_state, ensure_ascii=False, indent=2)
    notes_block = user_notes.strip() if user_notes and user_notes.strip() else "(No personal notes provided.)"

    prompt_template = _load_prompt("pipeline_challenge.txt")
    user_prompt = _fill(
        prompt_template,
        vocab_list=vocab_summary,
        story_taxonomy=story_taxonomy_formatted,
        updated_story=state_json_str,
        all_previous_questions=all_prev_questions_text,
        user_notes=notes_block,
    )

    content = _call_ai(user_prompt, PIPELINE_SYSTEM_PROMPT, provider, model, api_key, timeout, stop_event=stop_event)
    data = _parse_json(content, stage_name=f"Step {challenge_step} Master Challenge", provider=provider, model=model)

    if "question" in data:
        q_obj = data["question"]
    else:
        q_obj = data

    # Chuẩn hóa cấu trúc câu hỏi challenge
    q_norm = _normalize_question(q_obj, expected_type=q_obj.get("type", "single"), question_num=challenge_step, total_q=challenge_step)
    q_norm["instruction"] = "Final Evaluation - Master Challenge"

    return q_norm


# ══════════════════════════════════════════════════════════════════════════════
# ── BƯỚC 12: SINH STRUCTURED SUMMARY STORY ────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

def _generate_summary_story(
    questions: list[dict],
    vocab_list: list[dict],
    updated_story_state: dict,
    provider: str,
    model: str,
    api_key: str,
    timeout: int,
    stop_event: threading.Event = None,
    user_notes: str = "",
    summary_step: int = 12,
) -> str:
    """
    Tạo summary_story có cấu trúc ([Beginning], [Development], ...)
    từ toàn bộ các đoạn story fragment và Story State.
    """
    fragments = []
    for i, q in enumerate(questions, 1):
        story = q.get("story", q.get("context", ""))
        inst = q.get("instruction", "")
        if story:
            fragments.append(f"[Chapter/Fragment {i} - {inst}]:\n{story}")

    story_fragments_text = "\n\n".join(fragments) if fragments else "(No story fragments available.)"
    vocab_summary = ", ".join(v.get("word", "") for v in vocab_list if v.get("word"))
    state_json_str = json.dumps(updated_story_state, ensure_ascii=False, indent=2)
    notes_block = user_notes.strip() if user_notes and user_notes.strip() else "(No personal notes provided.)"

    prompt_template = _load_prompt("pipeline_summary_story.txt")
    user_prompt = _fill(
        prompt_template,
        vocab_list=vocab_summary,
        story_fragments=story_fragments_text,
        updated_story=state_json_str,
        user_notes=notes_block,
    )

    content = _call_ai(user_prompt, PIPELINE_SYSTEM_PROMPT, provider, model, api_key, timeout, stop_event=stop_event)
    data = _parse_json(content, stage_name=f"Step {summary_step} Summary Story", provider=provider, model=model)

    if "summary_story" in data and str(data["summary_story"]).strip():
        return str(data["summary_story"]).strip()
    elif isinstance(data, dict) and len(data) > 0:
        # Nếu trả về dict các phần
        lines = []
        for k, v in data.items():
            if v and str(v).strip():
                lines.append(f"[{k.title()}]\n{v}")
        if lines:
            return "\n\n".join(lines)

    # Fallback dự phòng an toàn nếu AI trả về rỗng
    if updated_story_state.get("story_summary"):
        return str(updated_story_state["story_summary"]).strip()
    if fragments:
        return "\n\n".join(fragments)
    return str(data) if data else "Summary story could not be generated."


# ══════════════════════════════════════════════════════════════════════════════
# ── BƯỚC 13: SINH FLASHCARD ĐẦY ĐỦ CÁC TRƯỜNG NGỮ NGHĨA SÂU ──────────────────
# ══════════════════════════════════════════════════════════════════════════════

def _lookup_db_ipa(word: str) -> str:
    """Tra cứu IPA chuẩn từ database SQLite nếu từ đã từng được lưu."""
    if not word or not str(word).strip():
        return ""
    try:
        from database import get_connection
        conn = get_connection()
        try:
            c = conn.cursor()
            c.execute(
                "SELECT ipa_uk, ipa FROM Vocab WHERE LOWER(word) = LOWER(?) AND (ipa_uk IS NOT NULL OR ipa IS NOT NULL) LIMIT 1",
                (str(word).strip(),)
            )
            row = c.fetchone()
            if row:
                found = (row[0] or row[1] or "").strip()
                if found and found.strip("/"):
                    return f"/{found.strip('/')}/"
        finally:
            conn.close()
    except Exception:
        pass
    return ""


def _normalize_flashcard(vocab_item: dict, data: dict) -> dict:
    """Chuẩn hóa dữ liệu flashcard và merge an toàn vào vocab_item."""
    if not isinstance(data, dict):
        return dict(vocab_item)

    # Unwrap nếu bị bọc trong dict cha (flashcard / card / vocab / data)
    for wrapper in ["flashcard", "card", "vocab", "vocabulary", "data", "result"]:
        if wrapper in data and isinstance(data[wrapper], dict):
            data = data[wrapper]
            break

    # Ánh xạ alias trường phổ biến
    alias_map = {
        "definition": "definition_simple_en",
        "definition_en": "definition_simple_en",
        "meaning_en": "definition_simple_en",
        "meaning_vi": "definition_vi_simple",
        "definition_vi": "definition_vi_simple",
        "example": "example_en",
        "sentence": "example_en",
        "example_vietnamese": "example_vi",
        "part_of_speech": "pos",
        "type": "pos",
        "nuance": "nuance_en",
        "tone": "tone_en",
    }
    for alias_key, target_key in alias_map.items():
        if alias_key in data and target_key not in data:
            data[target_key] = data[alias_key]

    updated = dict(vocab_item)
    for field in [
        "pos", "ipa_uk", "definition_simple_en", "definition_minimal_en",
        "definition_vi_simple", "nuance_en", "nuance_vi", "example_en",
        "example_vi", "contrast", "contrast_vi", "usage_distinction",
        "usage_distinction_vi", "tone_en"
    ]:
        if field in data and data[field]:
            updated[field] = data[field]

    word = vocab_item.get("word", updated.get("word", ""))
    w_clean = word.strip().lower()

    # Kiểm tra và chuẩn hóa Cambridge IPA (đảm bảo chuẩn /.../ không bị lặp //...//)
    raw_ipa = str(updated.get("ipa_uk", "")).strip().strip("'\"`")
    clean_ipa_inner = raw_ipa.strip("/\\ ")
    while "//" in clean_ipa_inner:
        clean_ipa_inner = clean_ipa_inner.replace("//", "/")

    # Danh sách các mẫu IPA hallucinated phổ biến mà AI nhỏ copy từ ví dụ prompt
    known_hallucinated_ipas = [
        ("keɪ.bəl", "cable"),
        ("keɪbəl", "cable"),
        ("eə.bɔːn", "airborne"),
        ("eəbɔːn", "airborne"),
        ("kæt.əˈstrɒf.ɪk", "catastrophic"),
        ("kæt.ə.strɒf.ɪk", "catastrophic"),
        ("kætəstrɒfɪk", "catastrophic"),
        ("dɪˌfɒr.ɪˈsteɪ.ʃən", "deforestation"),
        ("dɪ.fɒr.ɪ.steɪ.ʃən", "deforestation"),
        ("dɪfɒrɪsteɪʃən", "deforestation"),
        ("juːˈbɪk.wɪ.təs", "ubiquitous"),
        ("juː.bɪk.wɪ.təs", "ubiquitous"),
        ("juːbɪkwɪtəs", "ubiquitous"),
        ("phát âm ipa", ""),
        ("phat am ipa", ""),
        ("...", ""),
    ]
    for bad_ipa, legit_w in known_hallucinated_ipas:
        if bad_ipa in clean_ipa_inner.lower():
            if not legit_w or legit_w not in w_clean:
                clean_ipa_inner = ""
                break

    if clean_ipa_inner:
        updated["ipa_uk"] = f"/{clean_ipa_inner}/"
    else:
        updated["ipa_uk"] = ""

    # Nếu AI không sinh được IPA hoặc bị lọc bỏ placeholder, tra cứu lại DB đã lưu
    if not updated.get("ipa_uk"):
        old_ipa = str(updated.get("ipa", "")).strip().strip("'\"`/\\ ")
        if old_ipa and not any(bad in old_ipa.lower() for bad, _ in known_hallucinated_ipas):
            updated["ipa_uk"] = f"/{old_ipa}/"
        else:
            db_ipa = _lookup_db_ipa(word)
            if db_ipa:
                updated["ipa_uk"] = db_ipa

    # Đảm bảo target word hiện diện rõ ràng trong câu ví dụ (example_en)
    ex_en = str(updated.get("example_en", "")).strip()
    if ex_en:
        ex_lower = ex_en.lower()
        stems = [w_clean]
        if len(w_clean) > 3:
            stems.append(w_clean.rstrip("es").rstrip("ed").rstrip("ing").rstrip("s"))
        if not any(s in ex_lower for s in stems if len(s) >= 3):
            updated["example_en"] = f"{ex_en.rstrip('.')} — demonstrating the concept of {w_clean}."
    else:
        # Fallback ví dụ nếu AI không sinh
        updated["example_en"] = f"The research demonstrated the significance of {w_clean} in academic discourse."

    # Chuẩn hóa tone_en: Chỉ chấp nhận các Linguistic Registers học thuật tổng quát,
    # loại bỏ hoàn toàn các thể loại truyện/không khí hư cấu (fiction, mystery, thriller, apocalyptic,...)
    STANDARD_REGISTERS = {
        "formal / academic": "Formal / Academic",
        "academic": "Formal / Academic",
        "formal": "Formal / Academic",
        "scholarly": "Formal / Academic",
        "technical / scientific": "Technical / Scientific",
        "technical": "Technical / Scientific",
        "scientific": "Technical / Scientific",
        "neutral / general": "Neutral / General",
        "neutral": "Neutral / General",
        "general": "Neutral / General",
        "literary / poetic": "Literary / Poetic",
        "literary": "Literary / Poetic",
        "poetic": "Literary / Poetic",
        "formal / elevated": "Formal / Elevated",
        "elevated": "Formal / Elevated",
        "informal / casual": "Informal / Casual",
        "informal": "Informal / Casual",
        "casual": "Informal / Casual",
        "colloquial": "Informal / Casual",
        "descriptive / formal": "Descriptive / Formal",
    }

    curr_tone = str(updated.get("tone_en", "")).strip()
    norm_tone_key = curr_tone.lower()

    story_theme_keywords = [
        "scp", "steampunk", "cyberpunk", "biopunk", "arcanepunk", "apocalyptic",
        "fiction", "cosmic", "anomaly", "narrative", "mystery", "mysterious",
        "suspense", "suspenseful", "dark", "gloomy", "eerie", "grim", "foreboding",
        "tense", "thriller", "horror", "fantasy", "mythical", "investigation",
        "climax", "climactic", "dramatic", "ominous", "tragic", "dystopian",
        "adventure", "action", "story", "bunker", "laboratory", "facility",
        "serious", "intense", "subterranean"
    ]

    is_story_tone = any(k in norm_tone_key for k in story_theme_keywords)

    if not is_story_tone and norm_tone_key in STANDARD_REGISTERS:
        updated["tone_en"] = STANDARD_REGISTERS[norm_tone_key]
    else:
        # Suy luận Linguistic Register dựa trên từ loại và thuộc tính từ vựng
        pos_val = str(updated.get("pos", "")).lower()
        if pos_val in ["verb", "noun"]:
            updated["tone_en"] = "Formal / Academic"
        elif pos_val in ["adjective", "adverb"]:
            updated["tone_en"] = "Descriptive / Formal"
        else:
            updated["tone_en"] = "Neutral / General"

    # Làm sạch nuance_en: Nếu AI viết về cốt truyện thay vì sắc thái ngữ nghĩa nội tại của từ
    nuance_val = str(updated.get("nuance_en", "")).strip()
    story_terms = [
        "the character", "the protagonist", "in the story", "in this story",
        "the narrative", "the bunker", "the anomaly", "in the plot",
        "in the text", "in chapter", "the reader", "the author", "in the context of the story"
    ]
    if any(st in nuance_val.lower() for st in story_terms):
        pos_tag = str(updated.get("pos", "word")).lower()
        tone_tag = str(updated.get("tone_en", "Academic / Formal")).strip()
        updated["nuance_en"] = f"Functions as a {tone_tag} {pos_tag} conveying precise, objective semantic meaning in formal and general English contexts."
        updated["nuance_vi"] = f"Đóng vai trò là {pos_tag} mang sắc thái {tone_tag}, truyền tải ý nghĩa khách quan, chuẩn xác trong ngữ cảnh tiếng Anh học thuật và phổ thông."


    # Đồng bộ tương thích ngược các alias cũ
    if "ipa_uk" in updated and not updated.get("ipa"):
        updated["ipa"] = updated["ipa_uk"]
    if "definition_simple_en" in updated and not updated.get("definition_full_en"):
        updated["definition_full_en"] = updated["definition_simple_en"]
    if "definition_minimal_en" in updated and not updated.get("definition_short_en"):
        updated["definition_short_en"] = updated["definition_minimal_en"]
    if "definition_vi_simple" in updated and not updated.get("definition_vi"):
        updated["definition_vi"] = updated["definition_vi_simple"]
    if "usage_distinction" in updated and not updated.get("usage_note"):
        updated["usage_note"] = updated["usage_distinction"]
    if "tone_en" in updated and not updated.get("tone"):
        updated["tone"] = updated["tone_en"]

    return updated


class _StopScope:
    """Cancel sibling jobs on failure without changing the caller's stop signal."""
    def __init__(self, parent=None):
        self.parent = parent
        self.event = threading.Event()

    def is_set(self):
        return self.event.is_set() or bool(self.parent and self.parent.is_set())

    def set(self):
        self.event.set()

    def wait(self, seconds):
        deadline = time.monotonic() + seconds
        while not self.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            self.event.wait(min(remaining, 0.1))
        return True


def _pause(seconds: float, stop_event=None):
    """Retry/stagger waits must remain cancellable."""
    if stop_event is None:
        time.sleep(seconds)
    elif stop_event.wait(seconds):
        raise PipelineCancelledException("Pipeline bị hủy bởi người dùng.")


def _generate_one_flashcard(
    vocab_item: dict,
    vocab_list_str: str,
    summary_story: str,
    provider: str,
    model: str,
    api_key: str,
    timeout: int,
    stop_event: threading.Event = None,
    user_notes: str = "",
    step_idx: int = 13,
) -> dict:
    """
    Tạo flashcard đầy đủ các trường ranh giới ngữ nghĩa (nuance, contrast, usage distinction, example)
    dựa vào summary_story với cơ chế retry tự động.
    """
    word = vocab_item.get("word", "")
    notes_block = user_notes.strip() if user_notes and user_notes.strip() else "(No personal notes provided.)"
    prompt_template = _load_prompt("pipeline_flashcard_example.txt")
    user_prompt = _fill(
        prompt_template,
        word=word,
        vocab_list=vocab_list_str,
        summary_story=summary_story,
        user_notes=notes_block,
    )

    data = None
    last_err = None
    for retry_idx in range(2):
        if stop_event and stop_event.is_set():
            raise PipelineCancelledException("Pipeline bị hủy bởi người dùng.")
        try:
            content = _call_ai(user_prompt, PIPELINE_SYSTEM_PROMPT, provider, model, api_key, timeout, stop_event=stop_event)
            data = _parse_json(content, stage_name=f"Step {step_idx} Flashcard: {word}", provider=provider, model=model)
            if data and isinstance(data, dict):
                break
        except PipelineCancelledException:
            raise
        except Exception as e:
            last_err = e
            import time
            _pause(1.0, stop_event)

    if not data or not isinstance(data, dict):
        if last_err:
            raise last_err
        raise ValueError(f"Không thể sinh flashcard cho từ '{word}'")

    return _normalize_flashcard(vocab_item, data)


def _generate_all_flashcards(
    vocab_list: list[dict],
    summary_story: str,
    provider: str,
    model: str,
    api_key: str,
    timeout: int,
    on_progress=None,
    step_base: int = 13,
    total_pipeline_steps: int = 13,
    stop_event: threading.Event = None,
    user_notes: str = "",
) -> list[dict]:
    """
    Sinh toàn bộ Flashcard chuyên sâu đa chiều theo từng từ riêng biệt (Dedicated 1-by-1 Generation),
    đảm bảo độ sâu ngữ nghĩa, sắc thái và ví dụ đạt chuẩn cao nhất.
    Tự động phân bổ xoay vòng các model trong Failover Pool cho từng từ để tối ưu tốc độ và không bị nghẽn Rate Limit (RPM).
    """
    stop_event = _StopScope(stop_event)
    total_vocab = len(vocab_list)
    results = [None] * total_vocab
    vocab_names_list = [v.get("word", "").strip() for v in vocab_list if v.get("word")]
    vocab_names_str = ", ".join(vocab_names_list)

    is_cloud = provider.lower() in ("gemini", "openai")
    max_workers = 2 if is_cloud else 4

    # Tạo danh sách model xoay vòng cho từng từ nếu dùng Gemini
    if provider.lower() == "gemini":
        pool = [model] + [m for m in GEMINI_MODEL_FAILOVER_POOL if m != model]
    else:
        pool = [model]

    def worker(idx, vocab_item):
        if stop_event and stop_event.is_set():
            raise PipelineCancelledException("Pipeline bị hủy bởi người dùng.")

        # Nhẹ nhàng stagger các thread cách nhau một chút
        if is_cloud and idx > 0:
            _pause(0.2, stop_event)

        assigned_model = pool[idx % len(pool)]
        try:
            updated = _generate_one_flashcard(
                vocab_item, vocab_names_str, summary_story, provider, assigned_model, api_key, timeout,
                stop_event=stop_event, user_notes=user_notes, step_idx=step_base,
            )
            return idx, updated
        except PipelineCancelledException:
            raise
        except Exception:
            # Fallback với model tiếp theo trong pool
            try:
                fallback_model = pool[(idx + 1) % len(pool)]
                _pause(1.0, stop_event)
                updated = _generate_one_flashcard(
                    vocab_item, vocab_names_str, summary_story, provider, fallback_model, api_key, timeout,
                    stop_event=stop_event, user_notes=user_notes, step_idx=step_base,
                )
                return idx, updated
            except PipelineCancelledException:
                raise
            except Exception as exc:
                raise ValueError(f"Không thể tạo flashcard cho từ {vocab_item.get('word', '?')}: {exc}") from exc

    executor = ThreadPoolExecutor(max_workers=max_workers)
    try:
        futures = {executor.submit(worker, i, v): i for i, v in enumerate(vocab_list)}
        completed = 0
        for future in as_completed(futures):
            completed += 1
            try:
                idx, updated_vocab = future.result()
                results[idx] = updated_vocab
            except PipelineCancelledException:
                executor.shutdown(wait=False, cancel_futures=True)
                raise
            except Exception:
                raise

            if on_progress:
                on_progress({
                    "step": step_base,
                    "total": total_pipeline_steps,
                    "label": f"Đang tạo flashcards chuyên sâu ({completed}/{total_vocab})...",
                    "status": "running",
                    "sub_progress": completed / max(1, total_vocab),
                })

    finally:
        stop_event.set()
        executor.shutdown(wait=False, cancel_futures=True)

    for i, r in enumerate(results):
        if r is None:
            results[i] = dict(vocab_list[i])

    # Phát hiện và loại bỏ lỗi AI yếu gán cùng một phát âm (IPA) cho nhiều từ vựng khác nhau
    ipa_groups = {}
    for card in results:
        if card and card.get("ipa_uk"):
            ipa_clean = card["ipa_uk"].strip("/").strip()
            if ipa_clean:
                ipa_groups.setdefault(ipa_clean, []).append(card)

    for ipa_clean, cards in ipa_groups.items():
        if len(cards) > 1:
            distinct_words = {c.get("word", "").strip().lower() for c in cards}
            if len(distinct_words) > 1:
                # Trùng lặp phát âm giữa các từ khác nhau -> AI yếu bị hallucinate lặp lại
                for c in cards:
                    w = c.get("word", "")
                    db_ipa = _lookup_db_ipa(w)
                    c["ipa_uk"] = db_ipa
                    c["ipa"] = db_ipa

    return results


# ══════════════════════════════════════════════════════════════════════════════
# ── HÀM CHÍNH: RUN LESSON PIPELINE ───────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

def run_lesson_pipeline(
    vocab_list: list[dict],
    seed_story: str,
    num_questions: int = 10,
    taxonomy_settings: dict = None,
    provider: str = "ollama",
    model: str = "qwen3.5:4b",
    api_key: str = "",
    timeout: int = 120,
    on_progress=None,
    stop_event: threading.Event = None,
    user_notes: str = "",
) -> dict:
    """
    Chạy toàn bộ quy trình sinh bài học tuần tự nâng cao.

    Args:
        vocab_list         : Danh sách từ vựng (mỗi dict có ít nhất 'word', 'pos').
        seed_story         : Cốt truyện / gợi ý ban đầu.
        num_questions      : Số câu hỏi tuần tự (mặc định 10 câu + 1 Challenge).
        taxonomy_settings  : Dict cấu hình Story Taxonomy (genre, aesthetic, pov, tone, etc.).
        provider           : "ollama" | "openai" | "gemini".
        model              : Tên model AI.
        api_key            : Khóa API cho cloud providers.
        timeout            : Thời gian chờ tối đa mỗi request (giây).
        on_progress        : Callback nhận trạng thái tiến trình { step, total, label, status }.
        stop_event         : threading.Event để hủy khi người dùng yêu cầu.
        user_notes         : Ghi chú cá nhân của người dùng — AI sẽ dùng để cá nhân hóa nội dung.

    Returns:
        {
            "success": bool,
            "questions": list[dict],
            "summary_story": str,
            "story_state": dict,
            "vocab_with_examples": list[dict],
            "error": str | None
        }
    """
    TOTAL = num_questions + 3

    def _progress(step: int, label: str, status: str = "running", **kwargs):
        if on_progress:
            try:
                on_progress({"step": step, "total": TOTAL, "label": label, "status": status, **kwargs})
            except Exception:
                pass

    def _is_stopped() -> bool:
        return stop_event is not None and stop_event.is_set()

    questions: list[dict] = []
    story_state = initial_story_state(seed_story)
    story_taxonomy_formatted = format_story_taxonomy(taxonomy_settings)

    try:
        # ── Bước 1 → num_questions: Sinh câu hỏi tuần tự & cập nhật Story State ─
        for step in range(1, num_questions + 1):
            if _is_stopped():
                raise PipelineCancelledException("Pipeline bị hủy bởi người dùng.")

            skill_name = COGNITIVE_SKILL_ROTATION[(step - 1) % len(COGNITIVE_SKILL_ROTATION)]
            _progress(step, f"Đang tạo câu hỏi {step}/{num_questions} (Dạng: {skill_name})...")

            result = _generate_one_question(
                question_number=step,
                total_questions=num_questions,
                updated_story_state=story_state,
                story_taxonomy_formatted=story_taxonomy_formatted,
                vocab_list=vocab_list,
                provider=provider,
                model=model,
                api_key=api_key,
                timeout=timeout,
                stop_event=stop_event,
                user_notes=user_notes,
            )

            questions.append(result["question"])
            story_state = result["updated_story"]

            chars_count = len(story_state.get("characters", []))
            events_count = len(story_state.get("established_events", []))
            _progress(
                step,
                f"✓ Câu hỏi {step}/{num_questions} hoàn tất (State: {chars_count} NV, {events_count} SK).",
                status="step_done"
            )

        # ── Bước Challenge (Final Evaluation) ─────────────────────────────────
        challenge_step = num_questions + 1
        summary_step = num_questions + 2
        flashcard_step = num_questions + 3

        if _is_stopped():
            raise PipelineCancelledException("Pipeline bị hủy bởi người dùng.")

        _progress(challenge_step, "Đang tổng hợp Final Evaluation (Master Challenge)...")
        challenge_q = _generate_challenge(
            questions=questions,
            vocab_list=vocab_list,
            updated_story_state=story_state,
            story_taxonomy_formatted=story_taxonomy_formatted,
            provider=provider,
            model=model,
            api_key=api_key,
            timeout=timeout,
            stop_event=stop_event,
            user_notes=user_notes,
            challenge_step=challenge_step,
        )
        questions.append(challenge_q)
        _progress(challenge_step, "✓ Master Challenge hoàn thành.", status="step_done")

        # ── Bước Tổng hợp Structured Summary Story ───────────────────────────
        if _is_stopped():
            raise PipelineCancelledException("Pipeline bị hủy bởi người dùng.")

        _progress(summary_step, "Đang kiến tạo Structured Summary Story...")
        summary_story = _generate_summary_story(
            questions=questions,
            vocab_list=vocab_list,
            updated_story_state=story_state,
            provider=provider,
            model=model,
            api_key=api_key,
            timeout=timeout,
            stop_event=stop_event,
            user_notes=user_notes,
            summary_step=summary_step,
        )
        _progress(summary_step, "✓ Structured Summary Story hoàn thành.", status="step_done")

        # ── Bước Flashcard Đa chiều ───────────────────────────────────────────
        if _is_stopped():
            raise PipelineCancelledException("Pipeline bị hủy bởi người dùng.")

        _progress(flashcard_step, f"Đang tạo {len(vocab_list)} Flashcard đa chiều...")
        vocab_with_flashcards = _generate_all_flashcards(
            vocab_list=vocab_list,
            summary_story=summary_story,
            provider=provider,
            model=model,
            api_key=api_key,
            timeout=timeout,
            on_progress=on_progress,
            step_base=flashcard_step,
            total_pipeline_steps=TOTAL,
            stop_event=stop_event,
            user_notes=user_notes,
        )
        if _is_stopped():
            raise PipelineCancelledException("Pipeline bị hủy bởi người dùng.")
        _progress(flashcard_step, f"✓ Toàn bộ {len(vocab_list)} Flashcards hoàn thành.", status="step_done")

        # ── Hoàn tất toàn bộ Pipeline ─────────────────────────────────────────
        _progress(TOTAL, "✓ Toàn bộ bài học đã được sinh thành công!", status="done")
        return {
            "success": True,
            "questions": questions,
            "summary_story": summary_story,
            "story_state": story_state,
            "vocab_with_examples": vocab_with_flashcards,
            "error": None,
        }

    except PipelineCancelledException:
        _progress(0, "✕ Pipeline đã bị hủy bởi người dùng.", status="warn")
        return {
            "success": False,
            "cancelled": True,
            "questions": questions,
            "summary_story": story_state.get("story_summary", ""),
            "story_state": story_state,
            "vocab_with_examples": list(vocab_list),
            "error": "Pipeline bị hủy bởi người dùng.",
        }
    except Exception as ex:
        err_msg = str(ex)
        if "timed out" in err_msg.lower() or "timeout" in err_msg.lower():
            err_msg = f"AI phản hồi quá lâu (timeout {timeout}s). Hãy thử model nhẹ hơn hoặc tăng timeout."
        _progress(0, f"✕ Lỗi: {err_msg}", status="error")
        return {
            "success": False,
            "questions": questions,
            "summary_story": "",
            "story_state": story_state,
            "vocab_with_examples": list(vocab_list),
            "error": err_msg,
        }
