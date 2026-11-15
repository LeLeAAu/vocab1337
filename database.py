"""
database.py — Vocab1337
Khởi tạo và quản lý kết nối SQLite (brain_archive.db).
Cung cấp các hàm helper để truy xuất dữ liệu từ DB, hỗ trợ đầy đủ
các trường ranh giới ngữ nghĩa (nuance, contrast, usage distinction, tone).
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime

from logger import get_logger

logger = get_logger("db")

# ── Đường dẫn database ────────────────────────────────────────────────────────
DB_PATH = Path(__file__).parent / "brain_archive.db"


# ── Kết nối ──────────────────────────────────────────────────────────────────
def get_connection() -> sqlite3.Connection:
    """Trả về connection với row_factory = Row (kết quả dưới dạng dict-like)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ── Khởi tạo schema & Auto-migration ──────────────────────────────────────────
def init_db() -> None:
    """
    Tạo file brain_archive.db và các bảng cốt lõi nếu chưa tồn tại.
    Tự động migrate các cột mới nếu DB đã tồn tại từ trước.
    """
    conn = get_connection()
    conn.executescript("""
        -- ── Bảng Vocab ──────────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS Vocab (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            word                  TEXT    NOT NULL UNIQUE,
            pos                   TEXT,
            ipa                   TEXT,
            ipa_uk                TEXT,
            definition_full_en    TEXT,
            definition_simple_en  TEXT,
            definition_short_en   TEXT,
            definition_minimal_en TEXT,
            definition_vi         TEXT,
            definition_vi_simple  TEXT,
            nuance_en             TEXT,
            nuance_vi             TEXT,
            example_en            TEXT,
            example_vi            TEXT,
            contrast              TEXT,
            contrast_vi           TEXT,
            usage_note            TEXT,
            usage_distinction     TEXT,
            usage_distinction_vi  TEXT,
            related_words         TEXT,
            related_words_vi      TEXT,
            tone                  TEXT,
            tone_en               TEXT,
            created_at            DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        -- ── Bảng Lessons ─────────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS Lessons (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            title           TEXT    NOT NULL,
            story_context   TEXT,
            story_state     TEXT,   -- JSON object lưu Story State Bible
            vocab_ids       TEXT,   -- JSON array of Vocab.id
            questions_json  TEXT,   -- JSON array of question objects
            flashcards_json TEXT,   -- JSON array of flashcard objects
            thumbnail       TEXT,   -- đường dẫn file ảnh đại diện (tuỳ chọn)
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        -- ── Bảng Progress ─────────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS Progress (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            lesson_id       INTEGER,
            vocab_id        INTEGER,
            status          TEXT    DEFAULT 'unseen',  -- unseen / learning / mastered
            score           REAL    DEFAULT 0,
            base_score      REAL    DEFAULT 6.0,
            reinforce_count INTEGER DEFAULT 0,
            last_reviewed   DATETIME,
            last_decay_date TEXT,
            UNIQUE (lesson_id, vocab_id),
            FOREIGN KEY (lesson_id) REFERENCES Lessons(id) ON DELETE CASCADE,
            FOREIGN KEY (vocab_id)  REFERENCES Vocab(id)   ON DELETE CASCADE
        );
    """)
    conn.commit()

    # Auto-migration an toàn cho các DB cũ
    new_vocab_cols = [
        ("ipa_uk", "TEXT"),
        ("definition_simple_en", "TEXT"),
        ("definition_minimal_en", "TEXT"),
        ("definition_vi_simple", "TEXT"),
        ("contrast", "TEXT"),
        ("contrast_vi", "TEXT"),
        ("usage_distinction", "TEXT"),
        ("usage_distinction_vi", "TEXT"),
        ("tone_en", "TEXT"),
    ]
    for col_name, col_type in new_vocab_cols:
        try:
            conn.execute(f"ALTER TABLE Vocab ADD COLUMN {col_name} {col_type}")
            conn.commit()
            logger.info("Migrated Vocab table: added column '%s' (%s)", col_name, col_type)
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                logger.debug("Column Vocab.%s already exists", col_name)
            else:
                logger.warning("Migration error adding Vocab.%s: %s", col_name, e)
        except Exception as e:
            logger.warning("Unexpected migration error on Vocab.%s: %s", col_name, e)

    new_lesson_cols = [
        ("story_state", "TEXT"),
        ("thumbnail", "TEXT"),
    ]
    for col_name, col_type in new_lesson_cols:
        try:
            conn.execute(f"ALTER TABLE Lessons ADD COLUMN {col_name} {col_type}")
            conn.commit()
            logger.info("Migrated Lessons table: added column '%s' (%s)", col_name, col_type)
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                logger.debug("Column Lessons.%s already exists", col_name)
            else:
                logger.warning("Migration error adding Lessons.%s: %s", col_name, e)
        except Exception as e:
            logger.warning("Unexpected migration error on Lessons.%s: %s", col_name, e)

    new_progress_cols = [
        ("last_decay_date", "TEXT"),
        ("base_score", "REAL DEFAULT 6.0"),
        ("reinforce_count", "INTEGER DEFAULT 0"),
    ]
    for col_name, col_type in new_progress_cols:
        try:
            conn.execute(f"ALTER TABLE Progress ADD COLUMN {col_name} {col_type}")
            conn.commit()
            logger.info("Migrated Progress table: added column '%s' (%s)", col_name, col_type)
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                logger.debug("Column Progress.%s already exists", col_name)
            else:
                logger.warning("Migration error adding Progress.%s: %s", col_name, e)
        except Exception as e:
            logger.warning("Unexpected migration error on Progress.%s: %s", col_name, e)

    # Chuẩn hóa base_score cho các bản ghi đã có
    try:
        conn.execute("UPDATE Progress SET base_score = MAX(6.0, score) WHERE (base_score IS NULL OR base_score = 0) AND score > 0")
        conn.commit()
    except Exception as e:
        logger.warning("Error normalizing base_score in Progress: %s", e)

    conn.close()
    logger.info("[DB] brain_archive.db initialized at: %s", DB_PATH)


def cleanup_orphaned_vocab(conn: sqlite3.Connection = None) -> int:
    """Xóa các bản ghi Vocab không còn thuộc về bất kỳ bài học nào trong bảng Lessons."""
    should_close = False
    if conn is None:
        conn = get_connection()
        should_close = True

    try:
        rows = conn.execute("SELECT vocab_ids FROM Lessons").fetchall()
        active_ids = set()
        for r in rows:
            v_ids_str = r["vocab_ids"]
            if v_ids_str:
                try:
                    v_ids = json.loads(v_ids_str)
                    if isinstance(v_ids, list):
                        for vid in v_ids:
                            if isinstance(vid, (int, str)) and str(vid).isdigit():
                                active_ids.add(int(vid))
                except Exception:
                    pass

        if not active_ids:
            return 0

        placeholders = ",".join("?" for _ in active_ids)
        cursor = conn.execute(f"DELETE FROM Vocab WHERE id NOT IN ({placeholders})", list(active_ids))
        deleted_count = cursor.rowcount
        conn.commit()
        return deleted_count
    finally:
        if should_close:
            conn.close()


# ── Vocab helpers ─────────────────────────────────────────────────────────────
def get_all_vocab() -> list[dict]:
    """Trả về toàn bộ từ vựng, sắp xếp theo alphabet."""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM Vocab ORDER BY word ASC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_vocab_by_id(vocab_id: int) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM Vocab WHERE id = ?", (vocab_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_random_vocab(n: int) -> list[dict]:
    """Chọn ngẫu nhiên n từ vựng từ DB (dùng cho màn hình Học ngẫu nhiên)."""
    if n <= 0:
        return []
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM Vocab ORDER BY RANDOM() LIMIT ?", (n,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_total_vocab_count() -> int:
    conn = get_connection()
    try:
        count = conn.execute("SELECT COUNT(*) FROM Vocab").fetchone()[0]
        return count
    finally:
        conn.close()


# ── Lessons helpers ───────────────────────────────────────────────────────────
def get_all_lessons() -> list[dict]:
    """Trả về danh sách bài học (không kèm JSON nặng), sắp xếp mới nhất trước."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, title, story_context, created_at, thumbnail FROM Lessons ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_lesson_by_id(lesson_id: int) -> dict | None:
    """Trả về bài học đầy đủ (kèm questions_json, flashcards_json, story_state)."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM Lessons WHERE id = ?", (lesson_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_total_lesson_count() -> int:
    conn = get_connection()
    try:
        count = conn.execute("SELECT COUNT(*) FROM Lessons").fetchone()[0]
        return count
    finally:
        conn.close()


# ── Progress helpers ──────────────────────────────────────────────────────────
def get_progress_by_lesson(lesson_id: int) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM Progress WHERE lesson_id = ?", (lesson_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def upsert_progress(lesson_id: int, vocab_id: int, status: str, score: float | int) -> None:
    """
    Cập nhật hoặc tạo mới entry tiến độ học.
    Tự động tăng cấp độ củng cố trí nhớ (reinforce_count) khi ôn tập lại từ vựng đạt >= 6 điểm ở ngày mới.
    """
    conn = get_connection()
    today = datetime.now().date()
    today_str = today.isoformat()
    try:
        existing = conn.execute("""
            SELECT id, status, score, base_score, reinforce_count, last_reviewed
            FROM Progress
            WHERE lesson_id = ? AND vocab_id = ?
        """, (lesson_id, vocab_id)).fetchone()

        if existing:
            current_reinforce = int(existing["reinforce_count"] or 0)
            last_rev_raw = existing["last_reviewed"]
            last_rev_date = None
            if last_rev_raw:
                try:
                    last_rev_date = datetime.strptime(str(last_rev_raw)[:10], "%Y-%m-%d").date()
                except Exception:
                    last_rev_date = None

            new_reinforce = current_reinforce
            new_base_score = float(score)

            # Nếu đạt mốc Mastered (>= 6 điểm) và đây là buổi ôn tập ở ngày khác -> Tăng cấp độ củng cố!
            if score >= 6.0:
                if last_rev_date and last_rev_date < today:
                    new_reinforce = current_reinforce + 1
                elif current_reinforce == 0 and existing["status"] == "mastered":
                    new_reinforce = 1

            conn.execute("""
                UPDATE Progress
                SET status          = ?,
                    score           = ?,
                    base_score      = ?,
                    reinforce_count = ?,
                    last_reviewed   = CURRENT_TIMESTAMP,
                    last_decay_date = ?
                WHERE id = ?
            """, (status, float(score), new_base_score, new_reinforce, today_str, existing["id"]))
        else:
            conn.execute("""
                INSERT INTO Progress (lesson_id, vocab_id, status, score, base_score, reinforce_count, last_reviewed, last_decay_date)
                VALUES (?, ?, ?, ?, ?, 0, CURRENT_TIMESTAMP, ?)
            """, (lesson_id, vocab_id, status, float(score), float(score), today_str))

        conn.commit()
    finally:
        conn.close()


# ── Thuật toán đường cong lãng quên thực tế & củng cố ngắt quãng (SRS) ──────
MAX_FORGET_DAYS = 30  # Ngưỡng trần tối đa: 1 tháng không đụng tới thì quên sạch


def get_forget_period(reinforce_count: int) -> int:
    """
    Tính thời gian quên sạch (T_forget tính theo ngày) dựa theo số lần củng cố (reinforce_count):
      - reinforce_count = 0 (mới học lần đầu): T_forget = 6 ngày
      - reinforce_count = 1 (recall lần 1 sau 1 tuần): T_forget = 11 ngày
      - reinforce_count = 2 (recall lần 2 sau 1 tuần): T_forget = 19 ngày
      - reinforce_count >= 3 (đã ôn nhiều lần): T_forget = 30 ngày (Chạm trần 1 tháng)
    """
    if reinforce_count <= 0:
        return 6
    calculated = round(6 * (1.8 ** reinforce_count))
    return min(MAX_FORGET_DAYS, int(calculated))


def calculate_score_decay(base_score: float, days_elapsed: int, reinforce_count: int = 0) -> float:
    """
    Tính điểm số mới dựa trên đường cong lãng quên thực tế & củng cố ngắt quãng (Reinforced Spaced Repetition):
      - Khi mới học lần đầu (T_forget = 6 ngày, base_score = 6.0):
          + Ngày 1 không học (t=1): Mất phản xạ nhớ nhanh (Score = 3.95 < 6.0)
          + Ngày 2 không học (t=2): Không nhớ cách viết (Score = 2.90 < 3.0, về chế độ Sơ cấp)
          + Tầm 6 ngày (t=6): Quên sạch hoàn toàn (Score = 0.0)
      - Khi được recall hàng tuần:
          + T_forget dãn dần ra (6 -> 11 -> 19 -> tối đa 30 ngày).
          + Kể cả từ đã thuộc và củng cố nhiều lần, nếu bỏ bẵng suốt 1 tháng (t=30) không đụng vào thì vẫn quên sạch (Score = 0.0).
    """
    if days_elapsed <= 0 or base_score <= 0:
        return float(base_score)

    t_forget = get_forget_period(reinforce_count)
    if days_elapsed >= t_forget:
        return 0.0

    retention_rate = 1.0 - (days_elapsed / t_forget) ** 0.6
    new_score = base_score * retention_rate
    return max(0.0, round(new_score, 2))


def apply_daily_score_decay() -> dict:
    """
    Kiểm tra và tính toán suy giảm điểm theo đường cong lãng quên thực tế & củng cố ngắt quãng.
    Điểm số được tính toán chuẩn xác từ khoảng cách ngày kể từ lần học gần nhất (days_since_reviewed).
    Chạy an toàn (Idempotent), không gây sai số tích lũy qua từng ngày.
    
    Trả về dict thống kê:
      {
        "decayed_count": số bản ghi bị giảm điểm,
        "details": [{"vocab_id": ..., "old_score": ..., "new_score": ..., "days": ...}, ...]
      }
    """
    conn = get_connection()
    today = datetime.now().date()
    today_str = today.isoformat()
    decayed_list = []

    try:
        # Lấy tất cả bản ghi đã từng được học (last_reviewed IS NOT NULL)
        rows = conn.execute("""
            SELECT id, lesson_id, vocab_id, status, score, base_score, reinforce_count, last_reviewed, last_decay_date
            FROM Progress
            WHERE last_reviewed IS NOT NULL AND (score > 0 OR status != 'unseen')
        """).fetchall()

        for r in rows:
            record_id = r["id"]
            current_score = float(r["score"] or 0)
            status = r["status"]
            base_score = float(r["base_score"] or max(6.0, current_score))
            reinforce_count = int(r["reinforce_count"] or 0)
            last_reviewed_raw = r["last_reviewed"]

            # Xác định ngày học gần nhất
            reviewed_date = None
            if last_reviewed_raw:
                try:
                    reviewed_date = datetime.strptime(str(last_reviewed_raw)[:10], "%Y-%m-%d").date()
                except Exception:
                    reviewed_date = None

            if reviewed_date is None:
                continue

            days_since_reviewed = (today - reviewed_date).days

            if days_since_reviewed > 0:
                new_score = calculate_score_decay(base_score, days_since_reviewed, reinforce_count)
                new_status = status
                # Nếu điểm tụt dưới ngưỡng master (6 điểm), cập nhật về 'learning'
                if new_score < 6 and status == "mastered":
                    new_status = "learning"

                if new_score != current_score or status != new_status or r["last_decay_date"] != today_str:
                    conn.execute("""
                        UPDATE Progress
                        SET score = ?, status = ?, last_decay_date = ?
                        WHERE id = ?
                    """, (new_score, new_status, today_str, record_id))

                    if new_score != current_score:
                        decayed_list.append({
                            "id": record_id,
                            "lesson_id": r["lesson_id"],
                            "vocab_id": r["vocab_id"],
                            "old_score": current_score,
                            "new_score": new_score,
                            "days_elapsed": days_since_reviewed,
                            "reinforce_count": reinforce_count,
                        })
            else:
                # Đã học hoặc đã cập nhật trong ngày hôm nay
                if r["last_decay_date"] != today_str:
                    conn.execute(
                        "UPDATE Progress SET last_decay_date = ? WHERE id = ?",
                        (today_str, record_id)
                    )

        conn.commit()
        if decayed_list:
            logger.info("[SRS Decay] Đã áp dụng giảm điểm cho %d từ vựng chưa ôn tập (tổng kiểm tra: %d).", len(decayed_list), len(rows))
        else:
            logger.debug("[SRS Decay] Kiểm tra %d bản ghi, không có từ nào cần giảm điểm hôm nay.", len(rows))
        return {
            "decayed_count": len(decayed_list),
            "details": decayed_list
        }
    except Exception as e:
        logger.error("[SRS Decay] Lỗi khi thực hiện giảm điểm hàng ngày: %s", e, exc_info=True)
        raise
    finally:
        conn.close()


def get_mastered_count() -> int:
    """Số từ vựng riêng biệt đã học thuộc (status = 'mastered' hoặc score >= 6)."""
    conn = get_connection()
    try:
        count = conn.execute(
            "SELECT COUNT(DISTINCT vocab_id) FROM Progress WHERE status = 'mastered' OR score >= 6"
        ).fetchone()[0]
        return count
    finally:
        conn.close()


def get_all_vocab_with_stats(mastered_only: bool = False) -> list[dict]:
    """
    Trả về danh sách từ vựng kèm:
    - lesson_titles: Danh sách tên các bài học chứa từ đó (chuẩn xác từ Lessons)
    - max_score: Điểm số cao nhất
    - is_mastered: True nếu max_score >= 6 hoặc status == 'mastered'
    Sắp xếp mặc định theo alphabet A-Z.
    Nếu mastered_only=True, chỉ trả về các từ có is_mastered = True.
    """
    conn = get_connection()
    try:
        lesson_rows = conn.execute("SELECT id, title, vocab_ids FROM Lessons ORDER BY id ASC").fetchall()
        lesson_map = {}
        for r in lesson_rows:
            vids = r["vocab_ids"]
            if vids:
                try:
                    parsed = json.loads(vids) if isinstance(vids, str) else vids
                    if isinstance(parsed, list):
                        for vid in parsed:
                            if isinstance(vid, (int, str)) and str(vid).isdigit():
                                lesson_map.setdefault(int(vid), []).append(r["title"])
                except Exception:
                    pass

        query = """
            SELECT 
                v.*,
                COALESCE(MAX(p.score), 0) AS max_score,
                MAX(CASE WHEN p.status = 'mastered' OR p.score >= 6 THEN 1 ELSE 0 END) AS is_mastered_flag
            FROM Vocab v
            LEFT JOIN Progress p ON v.id = p.vocab_id
            GROUP BY v.id
            ORDER BY v.word ASC
        """

        rows = conn.execute(query).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            vid = d["id"]
            d["lesson_titles"] = lesson_map.get(vid, [])
            d["is_mastered"] = bool(d.pop("is_mastered_flag", 0) or d["max_score"] >= 6)
            if mastered_only and not d["is_mastered"]:
                continue
            results.append(d)
        return results
    finally:
        conn.close()


# ── Editor & Mutator helpers ──────────────────────────────────────────────────

def update_lesson(
    lesson_id: int,
    title: str,
    story_context: str,
    vocab_ids_json: str,
    thumbnail: str = None,
    story_state: str = None,
) -> None:
    """Cập nhật thông tin Lesson và đồng bộ bảng Progress."""
    conn = get_connection()
    try:
        if story_state is not None:
            conn.execute("""
                UPDATE Lessons
                SET title = ?, story_context = ?, vocab_ids = ?, thumbnail = ?, story_state = ?
                WHERE id = ?
            """, (title, story_context, vocab_ids_json, thumbnail, story_state, lesson_id))
        else:
            conn.execute("""
                UPDATE Lessons
                SET title = ?, story_context = ?, vocab_ids = ?, thumbnail = ?
                WHERE id = ?
            """, (title, story_context, vocab_ids_json, thumbnail, lesson_id))

        # Đồng bộ khởi tạo Progress cho các từ mới thêm vào bài
        if vocab_ids_json:
            try:
                raw_ids = json.loads(vocab_ids_json) if isinstance(vocab_ids_json, str) else vocab_ids_json
                if isinstance(raw_ids, list):
                    for vid in raw_ids:
                        if isinstance(vid, (int, str)) and str(vid).isdigit():
                            conn.execute("""
                                INSERT OR IGNORE INTO Progress (lesson_id, vocab_id, status, score)
                                VALUES (?, ?, 'unseen', 0)
                            """, (lesson_id, int(vid)))
            except Exception:
                pass

        conn.commit()
        cleanup_orphaned_vocab(conn)
    finally:
        conn.close()


def update_vocab(vocab_id: int, fields: dict) -> None:
    """Cập nhật các trường của một từ vựng trong bảng Vocab."""
    allowed = {
        "word", "pos", "ipa", "ipa_uk",
        "definition_full_en", "definition_simple_en",
        "definition_short_en", "definition_minimal_en",
        "definition_vi", "definition_vi_simple",
        "nuance_en", "nuance_vi",
        "example_en", "example_vi",
        "contrast", "contrast_vi",
        "usage_note", "usage_distinction", "usage_distinction_vi",
        "related_words", "related_words_vi",
        "tone", "tone_en",
    }
    safe = {k: v for k, v in fields.items() if k in allowed}
    if not safe:
        return
    cols = ", ".join(f"{k} = ?" for k in safe)
    vals = list(safe.values()) + [vocab_id]
    conn = get_connection()
    try:
        conn.execute(f"UPDATE Vocab SET {cols} WHERE id = ?", vals)
        conn.commit()
    finally:
        conn.close()


def delete_lesson(lesson_id: int) -> None:
    """Xóa bài học, toàn bộ Progress và các từ vựng mồ côi thuộc bài học đó."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT vocab_ids FROM Lessons WHERE id = ?", (lesson_id,)).fetchone()
        old_vocab_ids = []
        if row and row["vocab_ids"]:
            try:
                raw = json.loads(row["vocab_ids"])
                if isinstance(raw, list):
                    old_vocab_ids = [int(x) for x in raw if isinstance(x, (int, str)) and str(x).isdigit()]
            except Exception:
                pass

        conn.execute("DELETE FROM Lessons WHERE id = ?", (lesson_id,))
        conn.commit()

        if old_vocab_ids:
            remaining_rows = conn.execute("SELECT vocab_ids FROM Lessons").fetchall()
            active_ids = set()
            for r in remaining_rows:
                if r["vocab_ids"]:
                    try:
                        v_ids = json.loads(r["vocab_ids"])
                        if isinstance(v_ids, list):
                            for x in v_ids:
                                if isinstance(x, (int, str)) and str(x).isdigit():
                                    active_ids.add(int(x))
                    except Exception:
                        pass

            orphans = [vid for vid in old_vocab_ids if vid not in active_ids]
            if orphans:
                placeholders = ",".join("?" for _ in orphans)
                conn.execute(f"DELETE FROM Vocab WHERE id IN ({placeholders})", orphans)
                conn.commit()
            logger.info("Đã xóa lesson id=%s thành công, dọn dẹp %d từ vựng mồ côi: %s", lesson_id, len(orphans), orphans)
        else:
            logger.info("Đã xóa lesson id=%s thành công", lesson_id)
    except Exception as e:
        logger.error("Lỗi khi xóa bài học id=%s: %s", lesson_id, e, exc_info=True)
        raise
    finally:
        conn.close()


def upsert_vocab(fields: dict) -> int:
    """Thêm mới hoặc cập nhật Vocab (dựa theo word)."""
    word = str(fields.get("word") or "").strip()
    if not word:
        raise ValueError("Trường 'word' không được để trống.")

    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT id FROM Vocab WHERE LOWER(word) = LOWER(?)", (word,)
        ).fetchone()

        allowed = [
            "pos", "ipa", "ipa_uk",
            "definition_full_en", "definition_simple_en",
            "definition_short_en", "definition_minimal_en",
            "definition_vi", "definition_vi_simple",
            "nuance_en", "nuance_vi",
            "example_en", "example_vi",
            "contrast", "contrast_vi",
            "usage_note", "usage_distinction", "usage_distinction_vi",
            "related_words", "related_words_vi",
            "tone", "tone_en",
        ]

        if existing:
            vid = existing["id"]
            safe_fields = {k: fields[k] for k in allowed if k in fields and fields[k] is not None}
            if safe_fields:
                cols = ", ".join(f"{k} = ?" for k in safe_fields)
                vals = list(safe_fields.values()) + [vid]
                conn.execute(f"UPDATE Vocab SET {cols} WHERE id = ?", vals)
                conn.commit()
            return vid
        else:
            safe = {k: fields[k] for k in allowed if k in fields and fields[k] is not None}
            safe["word"] = word
            cols = ", ".join(safe.keys())
            placeholders = ", ".join("?" for _ in safe)
            cursor = conn.execute(
                f"INSERT INTO Vocab ({cols}) VALUES ({placeholders})",
                list(safe.values())
            )
            conn.commit()
            return cursor.lastrowid
    finally:
        conn.close()


# ── Export helpers ────────────────────────────────────────────────────────────

def export_lesson_to_dict(lesson_id: int) -> dict | None:
    """Xuất bài học thành dict chuẩn tương thích 100% với ingestion.py."""
    lesson = get_lesson_by_id(lesson_id)
    if not lesson:
        return None

    vocab_ids = []
    if lesson.get("vocab_ids"):
        try:
            raw = json.loads(lesson["vocab_ids"])
            if isinstance(raw, list):
                vocab_ids = [int(x) for x in raw if isinstance(x, (int, str)) and str(x).isdigit()]
        except Exception:
            pass

    vocab_list = []
    for vid in vocab_ids:
        v = get_vocab_by_id(vid)
        if v:
            clean_v = {k: v[k] for k in v if k not in ("id", "created_at") and v[k] is not None}
            vocab_list.append(clean_v)

    questions = []
    if lesson.get("questions_json"):
        try:
            parsed = json.loads(lesson["questions_json"])
            if isinstance(parsed, list):
                questions = parsed
        except Exception:
            pass

    flashcards = []
    if lesson.get("flashcards_json"):
        try:
            parsed = json.loads(lesson["flashcards_json"])
            if isinstance(parsed, list):
                flashcards = parsed
        except Exception:
            pass

    story_state = None
    if lesson.get("story_state"):
        try:
            story_state = json.loads(lesson["story_state"])
        except Exception:
            story_state = lesson["story_state"]

    export_data = {
        "title": lesson.get("title") or "Bài học không tên",
        "story_context": lesson.get("story_context") or "",
        "vocab": vocab_list,
        "questions": questions,
        "flashcards": flashcards,
    }
    if story_state:
        export_data["story_state"] = story_state
    if lesson.get("thumbnail"):
        export_data["thumbnail"] = lesson["thumbnail"]

    return export_data


def export_lesson_to_file(lesson_id: int, output_dir: Path | str = None) -> Path | None:
    """Xuất bài học ra tệp .json chuẩn trong thư mục exports/ (hoặc output_dir)."""
    data = export_lesson_to_dict(lesson_id)
    if not data:
        return None

    if output_dir is None:
        target_dir = Path(__file__).parent / "exports"
    else:
        target_dir = Path(output_dir)

    target_dir.mkdir(parents=True, exist_ok=True)

    import re
    safe_title = re.sub(r'[\/:*?"<>| ]+', '_', data.get("title", "lesson")).strip("_")
    filename = f"{safe_title}_{lesson_id}.json"
    filepath = target_dir / filename

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.info("Xuất bài học id=%s ('%s') ra tệp thành công: %s", lesson_id, data.get("title"), filepath)
    return filepath


if __name__ == "__main__":
    init_db()
    print(f"Total vocab  : {get_total_vocab_count()}")
    print(f"Total lessons: {get_total_lesson_count()}")
    print(f"Mastered     : {get_mastered_count()}")
