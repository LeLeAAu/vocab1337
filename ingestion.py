"""
ingestion.py — Vocab1337
Đọc và parse file lesson.json chuẩn → INSERT vào brain_archive.db.
Hỗ trợ lưu trữ đầy đủ các trường ranh giới ngữ nghĩa và Story State Bible.
Hỗ trợ 2 luồng nhập liệu:
  1. load_lesson_from_json(filepath) — đọc từ file .json
  2. load_lesson_from_dict(data)     — nhận dict trực tiếp từ UI form / AI pipeline
"""

import json
import sqlite3
from pathlib import Path

from logger import get_logger

logger = get_logger("ingestion")

from database import get_connection, init_db


# ── Các trường bắt buộc ───────────────────────────────────────────────────────
REQUIRED_LESSON_FIELDS = {"title"}
REQUIRED_VOCAB_FIELDS  = {"word"}

# ── Validation ────────────────────────────────────────────────────────────────
def _validate_lesson(data: dict) -> list[str]:
    errors = []
    for field in REQUIRED_LESSON_FIELDS:
        if not isinstance(data.get(field), str) or not data[field].strip():
            errors.append(f"Lesson thiếu trường bắt buộc: '{field}'")
    for field in ("questions", "flashcards"):
        if field in data and (not isinstance(data[field], list) or
                              any(not isinstance(item, dict) for item in data[field])):
            errors.append(f"'{field}' phải là danh sách các object.")
    return errors


def _validate_vocab(vocab: dict, index: int) -> list[str]:
    if not isinstance(vocab, dict):
        return [f"vocab[{index}]: phải là một object chứa trường 'word'."]
    errors = []
    for field in REQUIRED_VOCAB_FIELDS:
        if not isinstance(vocab.get(field), str) or not vocab[field].strip():
            errors.append(f"vocab[{index}]: thiếu trường bắt buộc '{field}'")
    return errors


# ── Insert helpers ────────────────────────────────────────────────────────────
def _insert_or_get_vocab(cursor: sqlite3.Cursor, vocab: dict) -> int:
    """
    Insert một vocab vào bảng Vocab.
    Nếu word đã tồn tại → cập nhật các trường mới và trả về id cũ.
    """
    word = (vocab.get("word") or "").strip()
    existing = cursor.execute(
        "SELECT id FROM Vocab WHERE LOWER(word) = LOWER(?)", (word,)
    ).fetchone()

    ipa_val = vocab.get("ipa_uk") or vocab.get("ipa")
    def_full_val = vocab.get("definition_simple_en") or vocab.get("definition_full_en")
    def_short_val = vocab.get("definition_minimal_en") or vocab.get("definition_short_en")
    def_vi_val = vocab.get("definition_vi_simple") or vocab.get("definition_vi")
    usage_val = vocab.get("usage_distinction") or vocab.get("usage_note")
    tone_val = vocab.get("tone_en") or vocab.get("tone")

    payload = {
        "word":                 word,
        "pos":                  vocab.get("pos"),
        "ipa":                  ipa_val,
        "ipa_uk":               vocab.get("ipa_uk", ipa_val),
        "definition_full_en":   def_full_val,
        "definition_simple_en": vocab.get("definition_simple_en", def_full_val),
        "definition_short_en":  def_short_val,
        "definition_minimal_en": vocab.get("definition_minimal_en", def_short_val),
        "definition_vi":        def_vi_val,
        "definition_vi_simple": vocab.get("definition_vi_simple", def_vi_val),
        "nuance_en":            vocab.get("nuance_en"),
        "nuance_vi":            vocab.get("nuance_vi"),
        "example_en":           vocab.get("example_en"),
        "example_vi":           vocab.get("example_vi"),
        "contrast":             vocab.get("contrast"),
        "contrast_vi":          vocab.get("contrast_vi"),
        "usage_note":           usage_val,
        "usage_distinction":    vocab.get("usage_distinction", usage_val),
        "usage_distinction_vi": vocab.get("usage_distinction_vi"),
        "related_words":        vocab.get("related_words"),
        "related_words_vi":     vocab.get("related_words_vi"),
        "tone":                 tone_val,
        "tone_en":              vocab.get("tone_en", tone_val),
    }

    if existing:
        vid = existing[0]
        # Cập nhật các trường có giá trị
        non_empty = {k: v for k, v in payload.items() if k != "word" and v is not None}
        if non_empty:
            cols = ", ".join(f"{k} = ?" for k in non_empty)
            vals = list(non_empty.values()) + [vid]
            cursor.execute(f"UPDATE Vocab SET {cols} WHERE id = ?", vals)
        return vid

    cursor.execute("""
        INSERT INTO Vocab (
            word, pos, ipa, ipa_uk,
            definition_full_en, definition_simple_en,
            definition_short_en, definition_minimal_en,
            definition_vi, definition_vi_simple,
            nuance_en, nuance_vi,
            example_en, example_vi,
            contrast, contrast_vi,
            usage_note, usage_distinction, usage_distinction_vi,
            related_words, related_words_vi,
            tone, tone_en
        ) VALUES (
            :word, :pos, :ipa, :ipa_uk,
            :definition_full_en, :definition_simple_en,
            :definition_short_en, :definition_minimal_en,
            :definition_vi, :definition_vi_simple,
            :nuance_en, :nuance_vi,
            :example_en, :example_vi,
            :contrast, :contrast_vi,
            :usage_note, :usage_distinction, :usage_distinction_vi,
            :related_words, :related_words_vi,
            :tone, :tone_en
        )
    """, payload)
    return cursor.lastrowid


# ── Core ingestion logic ──────────────────────────────────────────────────────
def _ingest(data: dict | list) -> dict:
    """
    Thực hiện toàn bộ quá trình validate → INSERT trong một transaction.
    Tự động hỗ trợ cả full lesson dict và vocab list (JSON Array).
    """
    if isinstance(data, list):
        data = {
            "title": "Bài học từ vựng (Nhập từ JSON Array)",
            "story_context": "",
            "vocab": data,
            "questions": [],
            "flashcards": []
        }
    elif not isinstance(data, dict):
        return {"success": False, "lesson_id": None, "errors": ["Dữ liệu nạp vào phải là JSON Object hoặc JSON Array."]}

    # 1. Validate lesson-level
    errors = _validate_lesson(data)

    # 2. Validate từng vocab item
    vocab_list = data.get("vocab", [])
    if not isinstance(vocab_list, list):
        errors.append("'vocab' phải là danh sách các object.")
    else:
        for i, v in enumerate(vocab_list):
            errors.extend(_validate_vocab(v, i))

    if errors:
        return {"success": False, "lesson_id": None, "errors": errors}

    # 3. Bắt đầu transaction
    conn = get_connection()
    try:
        cursor = conn.cursor()

        # 3a. Insert vocab items, thu thập vocab_ids
        vocab_ids: list[int] = []
        for v in vocab_list:
            vid = _insert_or_get_vocab(cursor, v)
            if vid not in vocab_ids:
                vocab_ids.append(vid)

        # Chuẩn hóa story_state nếu có
        story_state_val = data.get("story_state")
        if isinstance(story_state_val, dict):
            story_state_json = json.dumps(story_state_val, ensure_ascii=False)
        elif isinstance(story_state_val, str):
            story_state_json = story_state_val
        else:
            story_state_json = None

        # 3b. Insert bài học
        cursor.execute("""
            INSERT INTO Lessons (title, story_context, story_state, vocab_ids, questions_json, flashcards_json, thumbnail)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            data.get("title"),
            data.get("story_context", ""),
            story_state_json,
            json.dumps(vocab_ids, ensure_ascii=False),
            json.dumps(data.get("questions",  []), ensure_ascii=False),
            json.dumps(data.get("flashcards", data.get("vocab", [])), ensure_ascii=False),
            data.get("thumbnail", None),
        ))
        lesson_id = cursor.lastrowid

        # 3c. Khởi tạo Progress cho từng từ trong bài (status = 'unseen')
        for vid in vocab_ids:
            cursor.execute("""
                INSERT OR IGNORE INTO Progress (lesson_id, vocab_id, status, score)
                VALUES (?, ?, 'unseen', 0)
            """, (lesson_id, vid))

        conn.commit()
        logger.info(
            "Nạp bài học thành công: '%s' (lesson_id=%s, %d từ vựng)",
            data.get('title'), lesson_id, len(vocab_ids)
        )
        return {"success": True, "lesson_id": lesson_id, "errors": []}

    except Exception as e:
        conn.rollback()
        logger.error("Lỗi cơ sở dữ liệu khi ingest bài học '%s': %s", data.get('title'), e, exc_info=True)
        return {"success": False, "lesson_id": None, "errors": [f"Lỗi DB: {e}"]}
    finally:
        conn.close()


# ── Public API ────────────────────────────────────────────────────────────────
def load_lesson_from_json(filepath: str | Path) -> dict:
    """Nạp bài học từ một file JSON theo cấu trúc chuẩn."""
    filepath = Path(filepath)

    if not filepath.exists():
        logger.warning("Không tìm thấy file để nạp bài học: %s", filepath)
        return {
            "success": False,
            "lesson_id": None,
            "errors": [f"File không tồn tại: {filepath}"],
        }

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        logger.error("Lỗi cú pháp JSON trong file %s: %s", filepath, e)
        return {
            "success": False,
            "lesson_id": None,
            "errors": [f"JSON không hợp lệ: {e}"],
        }

    return _ingest(data)


def load_lesson_from_dict(data: dict | list) -> dict:
    """Nạp bài học trực tiếp từ Python dict hoặc list (JSON Array)."""
    return _ingest(data)


if __name__ == "__main__":
    init_db()
    result = load_lesson_from_json(
        Path(__file__).parent / "lessons" / "example_lesson.json"
    )
    if result["success"]:
        print(f"Lesson loaded, lesson_id = {result['lesson_id']}")
    else:
        print("Errors:")
        for e in result["errors"]:
            print(f"  - {e}")
