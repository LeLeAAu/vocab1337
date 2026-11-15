"""
ai_generator.py — Vocab1337
Module sinh câu hỏi ngẫu nhiên và flashcard bằng Ollama (AI cục bộ).
Tương thích và an toàn (fallback khi không kết nối được Ollama).
"""

import json
import os
import time
import urllib.request
import urllib.error

from logger import get_logger

logger = get_logger("ai")

# ── Import an toàn ────────────────────────────────────────────────────────────
try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError as _e:
    OLLAMA_AVAILABLE = False
    logger.debug("ollama-python package không có sẵn: %s", _e)


# ── Quản lý tập tin Prompts ──────────────────────────────────────────────────
PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")

def load_prompt_file(filename: str, default_content: str = "") -> str:
    """
    Đọc nội dung prompt từ tập tin .txt nằm trong thư mục prompts/.
    Nếu không tìm thấy tập tin, sử dụng chuỗi nội dung mặc định (fallback).
    """
    filepath = os.path.join(PROMPTS_DIR, filename)
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            pass
    return default_content


DEFAULT_SYSTEM_PROMPT = """Bạn là một trợ lý AI chuyên thiết kế tài liệu học tiếng Anh học thuật.
Nhiệm vụ của bạn là tạo ra một bài học từ vựng tiếng Anh theo cấu trúc JSON.
Yêu cầu bắt buộc:
1. Output CHỈ chứa nội dung JSON hợp lệ, không chứa bất kỳ lời giải thích nào ở đầu hay cuối.
2. Mỗi câu hỏi trong "questions" NÊN có một ngữ cảnh/tình huống đọc hiểu ngắn riêng biệt ("context") liên quan tới từ vựng để tạo sự đa dạng và thử thách cho người học.
3. Cấu trúc JSON phải tuân thủ chính xác mẫu sau:
{
  "title": "Tên bài học",
  "story_context": "Cốt truyện tổng thể hoặc văn bản ngữ cảnh bài học (tiếng Anh)",
  "vocab": [
    {
      "word": "Từ vựng",
      "pos": "Từ loại (noun/adjective/verb...)",
      "ipa": "/phiên âm IPA chính xác của từ tương ứng/",
      "definition_short_en": "Định nghĩa ngắn tiếng Anh",
      "definition_full_en": "Định nghĩa đầy đủ tiếng Anh",
      "definition_vi": "Dịch nghĩa tiếng Việt",
      "example_en": "Câu ví dụ tiếng Anh liên quan đến cốt truyện trên",
      "example_vi": "Dịch ví dụ tiếng Việt",
      "nuance_en": "Sắc thái từ tiếng Anh",
      "nuance_vi": "Sắc thái từ tiếng Việt",
      "contrast": "Phân biệt từ tiếng Anh",
      "contrast_vi": "Phân biệt từ tiếng Việt",
      "usage_note": "Cách dùng tiếng Anh",
      "usage_distinction_vi": "Cách dùng tiếng Việt",
      "tone": "Academic"
    }
  ],
  "questions": [
    {
      "type": "single",
      "instruction": "Multiple choice - single answer",
      "context": "Short contextual story excerpt in English",
      "q": "English reading comprehension question based on the excerpt",
      "options": ["Option A in English", "Option B in English", "Option C in English", "Option D in English"],
      "correct": 0,
      "explain": "Giải thích chi tiết bằng tiếng Việt vì sao chọn đáp án này"
    }
  ]
}
"""

DEFAULT_USER_PROMPT_TEMPLATE = """Hãy sinh một bài học mới.
Cốt truyện gốc: "{story_context}"
Danh sách từ vựng cần tích hợp: {vocab_names}
Hãy sinh ra {num_questions} câu hỏi đọc hiểu đa dạng thuộc các loại (single, multiple, fill_blank, matching, true_false).
Yêu cầu trả về đúng cấu trúc JSON chuẩn."""


def is_ollama_running() -> bool:
    """
    Kiểm tra xem Ollama service có đang chạy cục bộ trên cổng mặc định 11434 không.
    """
    try:
        # Gọi thử api list của Ollama với timeout 5s
        response = urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5)
        return response.getcode() == 200
    except (urllib.error.URLError, Exception):
        return False


def generate_challenge(
    vocab_list: list[dict],
    story_context: str,
    model: str = "qwen3.5:4b",
    num_questions: int = 5,
    on_log: callable = None,
) -> dict:
    """
    Gọi Ollama cục bộ để sinh các thử thách đọc hiểu cho từ vựng mới dựa trên cốt truyện.
    Hỗ trợ callback on_log(msg: str, level: str) để hiển thị log realtime trên UI.
    """
    def log(msg: str, level: str = "INFO"):
        lvl = level.upper()
        if lvl in ("SUCCESS", "INFO"):
            logger.info("[Challenge Generator] %s", msg)
        elif lvl == "WARN":
            logger.warning("[Challenge Generator] %s", msg)
        elif lvl == "ERROR":
            logger.error("[Challenge Generator] %s", msg)
        else:
            logger.debug("[Challenge Generator] %s", msg)

        if on_log:
            try:
                on_log(msg, level)
            except Exception:
                pass

    log(f"Khởi tạo tiến trình sinh bài học. Model: '{model}'", "INFO")

    # 1. Kiểm tra trạng thái Ollama
    log("Đang kiểm tra kết nối tới dịch vụ Ollama (http://localhost:11434)...", "INFO")
    if not is_ollama_running():
        err = "Ollama service chưa được bật. Vui lòng bật ứng dụng Ollama trên máy tính của bạn."
        log(err, "ERROR")
        return {
            "success": False,
            "questions": [],
            "flashcards": [],
            "error": err
        }
    
    log("Dịch vụ Ollama đang hoạt động bình thường.", "SUCCESS")

    # 2. Đọc Prompts từ thư mục prompts/ (.txt files)
    system_prompt = load_prompt_file("system_prompt.txt", DEFAULT_SYSTEM_PROMPT)
    user_prompt_template = load_prompt_file("user_prompt_template.txt", DEFAULT_USER_PROMPT_TEMPLATE)

    vocab_names = [v.get("word", "") for v in vocab_list]
    log(f"Danh sách từ vựng tích hợp ({len(vocab_names)} từ): {vocab_names}", "INFO")
    
    user_prompt = user_prompt_template
    for k, v in {
        "story_context": story_context,
        "vocab_names": json.dumps(vocab_names, ensure_ascii=False),
        "num_questions": num_questions,
    }.items():
        user_prompt = user_prompt.replace(f"{{{k}}}", str(v))
    log("Đã nạp Prompt mẫu thành công từ file text 'prompts/*.txt'", "INFO")

    try:
        content = ""
        if OLLAMA_AVAILABLE:
            log(f"Đang gửi dữ liệu Prompt tới Ollama SDK (Model: {model}, Mode: JSON)...", "WARN")
            response = ollama.chat(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                format="json",
                options={"temperature": 0.3}
            )
            if hasattr(response, "message") and hasattr(response.message, "content"):
                content = (response.message.content or "").strip()
            elif isinstance(response, dict):
                msg = response.get("message", {})
                content = (msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")).strip()
            else:
                content = str(response).strip()
            log(f"Ollama SDK đã trả về kết quả ({len(content)} bytes).", "SUCCESS")
        else:
            log(f"Đang gửi HTTP POST request tới http://localhost:11434/api/chat (Timeout 180s)...", "WARN")
            url = "http://localhost:11434/api/chat"
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "format": "json",
                "stream": False,
                "options": {
                    "temperature": 0.3
                }
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=180) as res:
                res_data = json.loads(res.read().decode("utf-8"))
                content = res_data.get("message", {}).get("content", "").strip()
            log(f"Nhận phản hồi HTTP 200 từ Ollama API ({len(content)} bytes).", "SUCCESS")

        log("Đang phân tích cấu trúc dữ liệu JSON từ phản hồi AI...", "INFO")

        # Tìm và trích xuất JSON trong kết quả trả về của AI (nếu có markdown fence)
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        data = json.loads(content, strict=False)
        questions_count = len(data.get("questions", []))
        vocab_count = len(data.get("vocab", []))
        title = data.get("title", "Bài học tự động")

        log(f"Parse JSON thành công! Tiêu đề: '{title}' | Vocab: {vocab_count} từ | Câu hỏi: {questions_count} câu.", "SUCCESS")

        return {
            "success": True,
            "questions": data.get("questions", []),
            "vocab": data.get("vocab", []),
            "title": title,
            "story_context": data.get("story_context", story_context),
            "error": None
        }

    except Exception as e:
        err_msg = str(e)
        if "timed out" in err_msg.lower() or "timeout" in err_msg.lower():
            err_msg = f"Model '{model}' phản hồi quá lâu (quá 3 phút). Gợi ý: Chọn model nhẹ hơn như 'qwen3:1.7b' hoặc 'qwen3.5:4b' để xử lý nhanh hơn."
        log(f"Xảy ra lỗi trong tiến trình AI: {err_msg}", "ERROR")
        return {
            "success": False,
            "questions": [],
            "flashcards": [],
            "error": f"Lỗi gọi Ollama: {err_msg}"
        }


def generate_instant_question(
    story_context: str,
    vocab_words: list[str] = None,
    preferred_type: str = None,
) -> dict:
    """
    Sinh 1 câu hỏi thử thách ngẫu nhiên ngay lập tức (On-the-fly)
    dựa trên ngữ cảnh cốt truyện và danh sách từ vựng của bài học hiện tại.
    Hỗ trợ linh hoạt Ollama, Gemini hoặc OpenAI theo cấu hình trong settings.json.
    """
    from lesson_pipeline import _call_ai_raw

    # Đọc cấu hình settings.json
    settings = {}
    cfg_path = os.path.join(os.path.dirname(__file__), "settings.json")
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                settings = json.load(f)
        except Exception:
            pass

    provider = settings.get("ai_provider", "ollama")
    api_key = ""
    model = "base"
    if provider == "gemini":
        model = settings.get("pipeline_model_gemini", "gemini-2.5-flash")
        api_key = settings.get("gemini_api_key", "")
    elif provider == "openai":
        model = settings.get("pipeline_model_openai", "gpt-4o-mini")
        api_key = settings.get("openai_api_key", "")
    else:
        provider = "ollama"
        model = settings.get("pipeline_model_ollama", "qwen3:1.7b")

    vocab_str = ", ".join(vocab_words) if vocab_words else "focus vocabulary from the story"

    system_prompt = (
        "You are an expert English reading comprehension and vocabulary assessment designer (IELTS/TOEFL/SAT level).\n"
        "Your task is to generate EXACTLY ONE rigorous challenge question based on the provided story excerpt and target vocabulary.\n\n"
        "CRITICAL LANGUAGE AND OUTPUT RULES:\n"
        "1. QUESTION & CONTENT MUST BE IN ENGLISH: The question text ('question'), reading excerpt ('contextual_text'), options ('options'), word fragments ('fragments'), and speech pronunciation text ('target_text') MUST ALL BE 100% IN NATURAL, GRAMMATICALLY ACCURATE ENGLISH. Do NOT write or translate questions or options into Vietnamese.\n"
        "2. EXPLANATION IN VIETNAMESE: The explanation ('explain') MUST be in Vietnamese (or bilingual Vietnamese-English) to provide deep pedagogical guidance, explaining why the correct answer is right and why the distractors are wrong based on the story.\n"
        "3. INSTRUCTION: A short directive in Vietnamese (e.g. 'Chọn 1 đáp án đúng nhất', 'Thử thách phát âm qua Microphone', 'Sắp xếp từ thành câu').\n"
        "4. STRICT JSON ONLY: Return ONLY a valid JSON object matching the requested schema. No markdown fences, no conversational prose."
    )

    type_instruction = ""
    if preferred_type:
        type_instruction = f"The question type must be '{preferred_type}'."
    else:
        type_instruction = "The question type can be 'single', 'multiple', 'fill_blank', 'unscramble', or 'speech_verification'."

    user_prompt = f"""STORY PASSAGE:
\"\"\"{story_context}\"\"\"

TARGET VOCABULARY:
{vocab_str}

{type_instruction}

JSON SCHEMA SPECIFICATIONS (Notice: All 'question' and 'options' content MUST be in English):

If type is "single":
{{
  "type": "single",
  "instruction": "Chọn 1 đáp án đúng nhất",
  "question": "<Rigorous reading comprehension question in English testing deduction or vocabulary in context>",
  "options": [
    "<Option A in English>",
    "<Option B in English>",
    "<Option C in English>",
    "<Option D in English>"
  ],
  "correct": 0,
  "explain": "<Giải thích chi tiết bằng tiếng Việt dựa vào các chi tiết và sắc thái từ trong bài đọc>"
}}

If type is "multiple":
{{
  "type": "multiple",
  "instruction": "Chọn tất cả đáp án đúng",
  "question": "<Question in English asking to select all valid statements>",
  "options": [
    "<Option A in English>",
    "<Option B in English>",
    "<Option C in English>",
    "<Option D in English>"
  ],
  "correct_indices": [0, 2],
  "explain": "<Giải thích chi tiết bằng tiếng Việt>"
}}

If type is "fill_blank":
{{
  "type": "fill_blank",
  "instruction": "Điền từ thích hợp vào chỗ trống",
  "question": "Which vocabulary word best completes the following sentence from the story?",
  "contextual_text": "<Sentence in English with _____ blank>",
  "options": ["<English word 1>", "<English word 2>", "<English word 3>", "<English word 4>"],
  "correct_index": 0,
  "explain": "<Giải thích chi tiết bằng tiếng Việt>"
}}

If type is "unscramble":
{{
  "type": "unscramble",
  "instruction": "Sắp xếp từ thành câu hoàn chỉnh",
  "question": "Reconstruct this key sentence from the narrative by placing the phrases in correct grammatical order:",
  "fragments": ["<English phrase 1>", "<English phrase 2>", "<English phrase 3>", "<English phrase 4>"],
  "correct_sentence": "<Complete grammatically correct English sentence>",
  "correct_order": [0, 1, 2, 3],
  "explain": "<Giải thích cấu trúc ngữ pháp câu bằng tiếng Việt>"
}}

If type is "speech_verification":
{{
  "type": "speech_verification",
  "instruction": "Thử thách phát âm qua Microphone",
  "question": "Pronounce this target vocabulary term or phrase aloud clearly:",
  "target_text": "<Target English word or short phrase from vocabulary>",
  "contextual_text": "<Excerpt sentence in English showcasing the target word>",
  "explain": "<Giải thích nghĩa từ vựng và lưu ý phát âm bằng tiếng Việt>"
}}

Return ONLY valid JSON:
"""
    logger.info("Yêu cầu sinh câu hỏi On-the-fly: provider=%s, model=%s, preferred_type=%s, vocab_count=%d", provider, model, preferred_type, len(vocab_words) if vocab_words else 0)
    t0 = time.time()
    try:
        raw_res = _call_ai_raw(user_prompt, system_prompt, provider=provider, model=model, api_key=api_key, timeout=60)
        content = raw_res.strip()
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        question_data = json.loads(content, strict=False)
        if isinstance(question_data, list) and question_data:
            question_data = question_data[0]
        elif isinstance(question_data, dict) and "question" not in question_data and "questions" in question_data:
            question_data = question_data["questions"][0]

        logger.info(
            "Sinh câu hỏi On-the-fly thành công (%.2fs): type='%s', question='%s'",
            time.time() - t0, question_data.get("type"), str(question_data.get("question"))[:50]
        )
        return question_data
    except Exception as e:
        logger.error("Lỗi khi sinh câu hỏi On-the-fly: %s", e, exc_info=True)
        raise


