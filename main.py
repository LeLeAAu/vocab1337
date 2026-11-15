"""
main.py — Vocab1337
Entry point và Điều phối luồng học. Toàn bộ UI Neubrutalism tương thích Flet 0.85.
"""

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

import json
from copy import deepcopy
import random
import threading
import flet as ft
from pathlib import Path

from logger import (
    setup_logging, get_logger, set_log_level, get_current_log_level,
    get_memory_handler, get_logs_dir, install_exception_hooks,
    log_system_diagnostics, clean_old_logs
)

logger = get_logger("main")

from database import (
    init_db, get_all_lessons, get_lesson_by_id, get_vocab_by_id,
    get_all_vocab, get_random_vocab, get_total_vocab_count,
    get_total_lesson_count, get_mastered_count, upsert_progress,
    get_progress_by_lesson,
    update_lesson, update_vocab, delete_lesson, upsert_vocab,
    export_lesson_to_file, export_lesson_to_dict,
    get_all_vocab_with_stats, apply_daily_score_decay,
)
from ingestion import load_lesson_from_dict
from components.flashcard import build_flashcard_view
from components.reading import build_reading_view
from components.audio_player import PageAudioPlayer

# ── Palette Neubrutalism ───────────────────────────────────────────────────────
from components.theme import (
    BG_PAGE, BG_WHITE, BG_SIDEBAR, TEXT_DARK, TEXT_GRAY, TEXT_WHITE,
    CLR_GREEN, CLR_BLUE, CLR_YELLOW, CLR_RED, SHADOW_SM, SHADOW_MD, SHADOW_LG,
    mk_border, pad, marg, nb_button, nb_card, label_text, heading_text, close_dialog,
)
from views.dashboard import build_dashboard
from views.sidebar import build_sidebar
from views.random_practice import build_random_screen


import os
SETTINGS_FILE = Path("settings.json")

DEFAULT_SETTINGS = {
    "whisper_model": "base",
    "device": "cpu",
    "tts_voice": "en-GB-SoniaNeural",
    "tts_rate": "+0%",
    "ai_provider": "gemini",
    "pipeline_model_ollama": "qwen3:4b",
    "pipeline_model_openai": "gpt-4o-mini",
    "pipeline_model_gemini": "gemini-3.5-flash",
    "openai_api_key": "",
    "gemini_api_key": "",
    "pipeline_timeout": 120,
    "log_level": "INFO",
}


def load_settings() -> dict:
    cfg = dict(DEFAULT_SETTINGS)
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    cfg.update(loaded)
        except Exception:
            pass
    return cfg


def save_settings(settings: dict):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


# ── Helpers ───────────────────────────────────────────────────────────────────


def copy_to_clipboard(page: ft.Page, text: str) -> bool:
    """Sao chép chuỗi văn bản vào bộ nhớ tạm (Clipboard) của hệ thống (hỗ trợ Unicode UTF-16LE)."""
    success = False
    try:
        if hasattr(page, "set_clipboard"):
            page.set_clipboard(text)
            success = True
        elif hasattr(page, "clipboard"):
            page.clipboard = text
            success = True
    except Exception:
        pass

    try:
        import subprocess
        creationflags = 0x08000000 if os.name == "nt" else 0
        subprocess.run(["clip"], input=text.encode("utf-16le"), check=True, creationflags=creationflags)
        success = True
    except Exception:
        pass

    return success


def speak_text(page: ft.Page, text: str, voice: str = None):
    """
    Phát âm từ vựng bằng Edge-TTS (Microsoft Azure Neural Voice).
    Âm thanh được cache; Windows desktop dùng MCI/SAPI, web phát ở máy người dùng.
    Mặc định sử dụng chuẩn giọng Anh - Anh (en-GB-SoniaNeural).
    """
    import tts_processor
    settings = load_settings()
    act_voice = voice or settings.get("tts_voice", tts_processor.DEFAULT_VOICE)
    rate = settings.get("tts_rate", tts_processor.DEFAULT_RATE)

    def on_err(e):
        if page:
            page.show_dialog(ft.SnackBar(
                ft.Text(f"Không thể phát âm thanh: {e}", color=TEXT_WHITE),
                bgcolor=TEXT_DARK
            ))
            page.update()

    if os.name == "nt" and not page.web:
        tts_processor.speak(text, voice=act_voice, rate=rate, on_error=on_err)
    else:
        page.data["audio_player"].speak(text, voice=act_voice, rate=rate, on_error=on_err)


def safe_close_dialog(page: ft.Page, dlg: ft.Control):
    """Close the intended dialog rather than a more recent notification."""
    try:
        close_dialog(dlg)
    except RuntimeError:
        pass  # The dialog may already have been removed from its page.


# ══════════════════════════════════════════════════════════════════════════════
# ── SCREENS ───────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

def show_vocab_list_dialog(page: ft.Page, initial_mode: str = "all", on_navigate=None):
    """
    Hộp thoại danh sách từ vựng trong tất cả các bài học.
    Hỗ trợ 2 chế độ:
      - 'all': Tất cả từ vựng trong toàn bộ các bài học
      - 'mastered': Từ vựng đã thuộc (Score >= 6 hoặc status = 'mastered')
    Tính năng:
      - Tải sẵn toàn bộ từ vựng và lọc tức thì (dưới 5ms) qua ListView ảo hóa
      - Tìm kiếm tức thì theo từ, nghĩa VI, nghĩa EN, bài học
      - Lọc theo từng bài học cụ thể
      - Phát âm âm thanh Edge-TTS
    """
    all_vocabs = get_all_vocab_with_stats(mastered_only=False)
    lesson_names = sorted(list({lt for v in all_vocabs for lt in v.get("lesson_titles", [])}))
    mastered_count_total = sum(1 for v in all_vocabs if v.get("is_mastered"))

    state = {
        "mode": initial_mode,
        "selected_lesson": "all",
    }

    def get_dropdown_val(dd, e=None) -> str:
        if e is not None and getattr(e, "data", None) is not None:
            d_val = str(e.data).strip()
            if d_val:
                dd.value = d_val
                return d_val
        if e is not None and hasattr(e, "control") and getattr(e.control, "value", None) is not None:
            c_val = str(e.control.value).strip()
            if c_val:
                dd.value = c_val
                return c_val
        return str(getattr(dd, "value", None) or "all").strip()

    def on_lesson_select(e=None):
        val = get_dropdown_val(lesson_dropdown, e)
        state["selected_lesson"] = val
        apply_filter()

    title_text = ft.Text(
        "DANH SÁCH TỪ VỰNG" if initial_mode == "all" else "TỪ VỰNG ĐÃ THUỘC (ĐIỂM >= 6)",
        size=17,
        weight=ft.FontWeight.W_900,
        color=TEXT_DARK,
    )
    title_icon = ft.Text("📖" if initial_mode == "all" else "✅", size=22)

    btn_tab_all = ft.Container(
        content=ft.Row([
            ft.Text("📖", size=13),
            ft.Text(f"TẤT CẢ ({len(all_vocabs)})", size=11, weight=ft.FontWeight.W_800, color=TEXT_DARK),
        ], spacing=5, alignment=ft.MainAxisAlignment.CENTER),
        bgcolor=CLR_YELLOW if initial_mode == "all" else BG_WHITE,
        border=mk_border(2, TEXT_DARK if initial_mode == "all" else "#d1d5db"),
        shadow=SHADOW_SM if initial_mode == "all" else None,
        padding=pad(h=12, v=7),
        ink=True,
    )

    btn_tab_mast = ft.Container(
        content=ft.Row([
            ft.Text("✅", size=13),
            ft.Text(f"ĐÃ THUỘC ({mastered_count_total})", size=11, weight=ft.FontWeight.W_800, color="#166534" if initial_mode == "mastered" else TEXT_DARK),
        ], spacing=5, alignment=ft.MainAxisAlignment.CENTER),
        bgcolor=CLR_GREEN if initial_mode == "mastered" else BG_WHITE,
        border=mk_border(2, "#166534" if initial_mode == "mastered" else "#d1d5db"),
        shadow=SHADOW_SM if initial_mode == "mastered" else None,
        padding=pad(h=12, v=7),
        ink=True,
    )

    search_inp = ft.TextField(
        hint_text="Tìm kiếm từ vựng, phiên âm, nghĩa tiếng Việt, tiếng Anh...",
        prefix_icon=ft.Icons.SEARCH,
        dense=True,
        border_color=TEXT_DARK,
        border_width=2,
        border_radius=0,
        width=380,
        content_padding=pad(h=10, v=9),
    )

    lesson_dropdown = ft.Dropdown(
        value="all",
        dense=True,
        border_color=TEXT_DARK,
        border_width=2,
        border_radius=0,
        width=250,
        options=[ft.dropdown.Option("all", "📚 Tất cả bài học")] + [
            ft.dropdown.Option(name, f"📚 {name}") for name in lesson_names
        ],
        on_select=on_lesson_select,
    )
    lesson_dropdown.on_select = on_lesson_select
    lesson_dropdown.on_change = on_lesson_select

    count_txt = ft.Text("", size=11, weight=ft.FontWeight.W_700, color=TEXT_GRAY)

    def close_dlg(e=None):
        safe_close_dialog(page, dlg)

    def nav_to_lessons(e=None):
        close_dlg()
        if on_navigate:
            on_navigate("lessons")

    # Empty states
    empty_mastered_box = ft.Container(
        content=ft.Column([
            ft.Text("🌱", size=32),
            ft.Text("Chưa có từ vựng nào đạt trạng thái Đã thuộc (Điểm >= 6)", size=13, weight=ft.FontWeight.W_800, color=TEXT_DARK),
            ft.Text("Hãy luyện tập Flashcard để ghi nhớ từ vựng sâu hơn!", size=12, color=TEXT_GRAY),
            ft.Container(height=8),
            nb_button("BẮT ĐẦU HỌC NGAY", on_click=nav_to_lessons, bgcolor=TEXT_DARK, color=TEXT_WHITE),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=4),
        alignment=ft.Alignment(0, 0),
        padding=pad(all_=30),
        visible=False,
    )

    empty_search_box = ft.Container(
        content=ft.Column([
            ft.Text("🔍", size=32),
            ft.Text("Không tìm thấy từ vựng nào phù hợp", size=13, weight=ft.FontWeight.W_800, color=TEXT_DARK),
            ft.Text("Hãy thử tìm bằng từ khóa khác hoặc đặt lại bộ lọc bài học.", size=12, color=TEXT_GRAY),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=4),
        alignment=ft.Alignment(0, 0),
        padding=pad(all_=30),
        visible=False,
    )

    vocab_cards = []
    card_idx_texts = []

    for idx, vocab in enumerate(all_vocabs):
        word = vocab.get("word", "")
        pos = vocab.get("pos", "")
        ipa = vocab.get("ipa", "") or vocab.get("ipa_uk", "")
        def_vi = vocab.get("definition_vi") or vocab.get("definition_vi_simple") or ""
        def_en = vocab.get("definition_short_en") or vocab.get("definition_simple_en") or ""
        ex_en = vocab.get("example_en") or ""
        ex_vi = vocab.get("example_vi") or ""
        lesson_titles = vocab.get("lesson_titles") or []
        max_score = vocab.get("max_score", 0)
        is_mastered = vocab.get("is_mastered", False)
        score_str = f"{max_score:g}" if isinstance(max_score, (int, float)) else str(max_score)

        if is_mastered:
            badge_score = ft.Container(
                content=ft.Row([
                    ft.Text("✅", size=10),
                    ft.Text(f"ĐÃ THUỘC • {score_str} ĐIỂM", size=9, weight=ft.FontWeight.W_800, color="#166534"),
                ], spacing=3),
                bgcolor="#bbf7d0",
                border=mk_border(1, "#166534"),
                padding=pad(h=6, v=2),
            )
        elif max_score > 0:
            badge_score = ft.Container(
                content=ft.Row([
                    ft.Text("⏳", size=10),
                    ft.Text(f"ĐANG HỌC • {score_str} ĐIỂM", size=9, weight=ft.FontWeight.W_800, color="#1e40af"),
                ], spacing=3),
                bgcolor="#bfdbfe",
                border=mk_border(1, "#1e40af"),
                padding=pad(h=6, v=2),
            )
        else:
            badge_score = ft.Container(
                content=ft.Row([
                    ft.Text("⚪", size=10),
                    ft.Text("CHƯA HỌC • 0 ĐIỂM", size=9, weight=ft.FontWeight.W_800, color="#4b5563"),
                ], spacing=3),
                bgcolor="#f3f4f6",
                border=mk_border(1, "#9ca3af"),
                padding=pad(h=6, v=2),
            )

        audio_btn = ft.Container(
            content=ft.Row([
                ft.Text("🔊", size=11),
                ft.Text("NGHE", size=9, weight=ft.FontWeight.W_800, color=TEXT_DARK),
            ], spacing=2, alignment=ft.MainAxisAlignment.CENTER),
            bgcolor=BG_WHITE,
            border=mk_border(1, TEXT_DARK),
            padding=pad(h=6, v=3),
            on_click=lambda e, w=word: speak_text(page, w),
            ink=True,
            tooltip="Phát âm từ vựng (Edge-TTS)",
        )

        lesson_badges = [
            ft.Container(
                content=ft.Text(f"📚 {lt}", size=9, weight=ft.FontWeight.W_700, color=TEXT_DARK),
                bgcolor="#fef08a",
                border=mk_border(1, TEXT_DARK),
                padding=pad(h=5, v=2),
            )
            for lt in lesson_titles
        ]

        txt_idx = ft.Text(f"{idx+1}.", size=11, weight=ft.FontWeight.W_700, color=TEXT_GRAY)
        card_idx_texts.append(txt_idx)

        left_items = [
            txt_idx,
            ft.Text(word.upper(), size=14, weight=ft.FontWeight.W_900, color=TEXT_DARK),
        ]
        if pos:
            left_items.append(
                ft.Container(
                    content=ft.Text(pos, size=9, weight=ft.FontWeight.W_700, color=TEXT_WHITE),
                    bgcolor="#3730a3",
                    padding=pad(h=5, v=1),
                )
            )
        if ipa:
            left_items.append(ft.Text(f"/{ipa}/", size=11, color=TEXT_GRAY, italic=True))
        left_items.append(audio_btn)

        right_items = []
        if lesson_badges:
            right_items.append(ft.Row(lesson_badges, spacing=4))
        right_items.append(badge_score)

        card_content = [
            ft.Row([
                ft.Row(left_items, spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Row(right_items, spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ]

        if def_vi or def_en:
            def_col_items = []
            if def_vi:
                def_col_items.append(ft.Text(f"🇻🇳 {def_vi}", size=12, weight=ft.FontWeight.W_700, color="#166534"))
            if def_en:
                def_col_items.append(ft.Text(f"🇬🇧 {def_en}", size=11, color=TEXT_DARK))
            card_content.append(ft.Column(def_col_items, spacing=2))

        if ex_en:
            card_content.append(
                ft.Container(
                    content=ft.Column([
                        ft.Text(f'💬 "{ex_en}"', size=11, color=TEXT_DARK, italic=True),
                        ft.Text(f'   ↳ {ex_vi}', size=11, color=TEXT_GRAY) if ex_vi else ft.Container(),
                    ], spacing=1),
                    bgcolor="#f9fafb",
                    border=ft.Border(left=ft.BorderSide(3, "#d1d5db")),
                    padding=pad(h=8, v=4),
                )
            )

        search_tokens = " ".join([
            word,
            ipa,
            def_vi,
            vocab.get("definition_vi_simple") or "",
            def_en,
            vocab.get("definition_simple_en") or "",
            " ".join(lesson_titles),
        ]).lower()

        card = ft.Container(
            content=ft.Column(card_content, spacing=3),
            bgcolor="#f0fdf4" if is_mastered else BG_WHITE,
            border=mk_border(2, "#166534" if is_mastered else TEXT_DARK),
            shadow=ft.BoxShadow(offset=ft.Offset(2, 2), blur_radius=0, color="#166534" if is_mastered else TEXT_DARK),
            padding=pad(h=12, v=8),
            data={
                "lesson_titles": set(lesson_titles),
                "is_mastered": is_mastered,
                "search_text": search_tokens,
            },
        )
        vocab_cards.append(card)

    list_view = ft.ListView(controls=vocab_cards + [empty_mastered_box, empty_search_box], spacing=8)
    list_box = ft.Container(
        content=list_view,
        height=420,
    )

    def apply_filter(e=None):
        kw = (search_inp.value or "").strip().lower()
        selected_lesson = state.get("selected_lesson", "all")
        is_all = (state["mode"] == "all")

        visible_count = 0
        total_in_mode = 0

        for card, idx_txt in zip(vocab_cards, card_idx_texts):
            d = card.data
            in_mode = is_all or d["is_mastered"]
            if in_mode:
                total_in_mode += 1

            match_lesson = (selected_lesson == "all") or (selected_lesson in d["lesson_titles"])
            match_kw = (not kw) or (kw in d["search_text"])

            show = in_mode and match_lesson and match_kw
            card.visible = show
            if show:
                visible_count += 1
                idx_txt.value = f"{visible_count}."

        empty_mastered_box.visible = (state["mode"] == "mastered" and total_in_mode == 0)
        empty_search_box.visible = (visible_count == 0 and not empty_mastered_box.visible)

        count_txt.value = f"Hiển thị {visible_count} / {total_in_mode} từ vựng"

        try:
            list_view.update()
            count_txt.update()
        except Exception:
            try:
                page.update()
            except Exception:
                pass

    def set_mode(new_mode: str):
        state["mode"] = new_mode
        if new_mode == "all":
            btn_tab_all.bgcolor = CLR_YELLOW
            btn_tab_all.border = mk_border(2, TEXT_DARK)
            btn_tab_all.shadow = SHADOW_SM
            btn_tab_mast.bgcolor = BG_WHITE
            btn_tab_mast.border = mk_border(1, "#d1d5db")
            btn_tab_mast.shadow = None
            title_text.value = "DANH SÁCH TỪ VỰNG"
            title_icon.value = "📖"
        else:
            btn_tab_mast.bgcolor = CLR_GREEN
            btn_tab_mast.border = mk_border(2, "#166534")
            btn_tab_mast.shadow = SHADOW_SM
            btn_tab_all.bgcolor = BG_WHITE
            btn_tab_all.border = mk_border(1, "#d1d5db")
            btn_tab_all.shadow = None
            title_text.value = "TỪ VỰNG ĐÃ THUỘC (ĐIỂM >= 6)"
            title_icon.value = "✅"

        try:
            btn_tab_all.update()
            btn_tab_mast.update()
            title_text.update()
            title_icon.update()
        except Exception:
            pass
        apply_filter()

    btn_tab_all.on_click = lambda e: set_mode("all")
    btn_tab_mast.on_click = lambda e: set_mode("mastered")

    search_inp.on_change = lambda e: apply_filter(e)
    lesson_dropdown.on_select = on_lesson_select
    lesson_dropdown.on_change = on_lesson_select

    # Initial visibility computation
    apply_filter()

    dlg = ft.AlertDialog(
        modal=True,
        title=ft.Row([
            ft.Row([
                title_icon,
                title_text,
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.IconButton(ft.Icons.CLOSE, on_click=close_dlg, icon_color=TEXT_DARK),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        content=ft.Column([
            ft.Row([
                btn_tab_all,
                btn_tab_mast,
                search_inp,
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Container(height=6),
            ft.Row([
                lesson_dropdown,
                ft.Container(width=10),
                count_txt,
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Container(height=1, bgcolor=TEXT_DARK, margin=marg(top=6, bottom=8)),
            list_box,
        ], spacing=0, tight=True, width=760),
    )

    page.show_dialog(dlg)


def show_log_viewer_dialog(page: ft.Page):
    """
    Modal Dialog hiển thị nhật ký thời gian thực (Live Log Viewer).
    Hỗ trợ lọc theo Level (ALL, DEBUG, INFO, WARNING, ERROR), tìm kiếm từ khóa,
    sao chép toàn bộ log vào clipboard, xóa bộ đệm, và tự động cuộn.
    """
    mem_handler = get_memory_handler()
    active_filter = ["ALL"]
    search_query = [""]

    log_list_col = ft.Column(spacing=4, scroll=ft.ScrollMode.AUTO, expand=True)
    count_label = ft.Text("0 bản ghi", size=11, color=TEXT_GRAY)

    def get_color_for_level(lvl: str) -> str:
        lvl = (lvl or "").upper()
        if lvl == "DEBUG":
            return "#94a3b8"  # Slate gray
        elif lvl in ("INFO", "SUCCESS"):
            return "#38bdf8"  # Sky blue
        elif lvl == "WARNING":
            return "#fbbf24"  # Amber
        elif lvl in ("ERROR", "CRITICAL"):
            return "#f87171"  # Red
        return "#ffffff"

    def refresh_logs(e=None):
        log_list_col.controls.clear()
        if not mem_handler:
            log_list_col.controls.append(
                ft.Container(
                    content=ft.Text("Hệ thống log chưa được khởi tạo.", color="#f87171", size=13),
                    padding=20, alignment=ft.Alignment(0, 0)
                )
            )
            count_label.value = "0 bản ghi"
            try:
                log_list_col.update()
                count_label.update()
            except Exception:
                pass
            return

        entries = mem_handler.get_history(
            level=active_filter[0],
            query=search_query[0],
            limit=400
        )
        count_label.value = f"Hiển thị {len(entries)} bản ghi gần nhất"

        if not entries:
            log_list_col.controls.append(
                ft.Container(
                    content=ft.Text("Không có bản ghi log nào khớp với bộ lọc hiện tại.", color="#9ca3af", size=12, italic=True),
                    padding=30, alignment=ft.Alignment(0, 0)
                )
            )
        else:
            for item in reversed(entries):
                lvl_color = get_color_for_level(item["level"])
                is_err = item["level"] in ("ERROR", "CRITICAL")
                is_warn = item["level"] == "WARNING"

                header_row = ft.Row([
                    ft.Text(f"[{item['time_short']}]", size=11, color="#94a3b8", font_family="monospace"),
                    ft.Container(
                        content=ft.Text(item["level"], size=10, weight=ft.FontWeight.W_900, color=TEXT_DARK),
                        bgcolor=lvl_color,
                        padding=ft.Padding(4, 1, 4, 1),
                        border=mk_border(1, TEXT_DARK),
                    ),
                    ft.Text(f"[{item['name']}]", size=11, color="#c084fc", weight=ft.FontWeight.W_700, font_family="monospace"),
                    ft.Text(f"{item['filename']}:{item['lineno']}", size=10, color="#6b7280", font_family="monospace"),
                    ft.Container(expand=True),
                    ft.Text(item.get("threadName", ""), size=10, color="#64748b", font_family="monospace"),
                ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER)

                msg_ctrl = ft.Text(
                    item["message"],
                    size=12,
                    color="#fecaca" if is_err else ("#fef08a" if is_warn else "#f3f4f6"),
                    weight=ft.FontWeight.W_700 if is_err else ft.FontWeight.NORMAL,
                    font_family="monospace",
                    selectable=True
                )

                card_children = [header_row, msg_ctrl]

                # Nếu có Traceback
                if item.get("exc_text"):
                    card_children.append(
                        ft.Container(
                            content=ft.Text(
                                item["exc_text"],
                                size=11,
                                color="#fca5a5",
                                font_family="monospace",
                                selectable=True
                            ),
                            bgcolor="#450a0a",
                            border=mk_border(1, "#991b1b"),
                            padding=8,
                            margin=ft.Margin(0, 4, 0, 0)
                        )
                    )

                entry_card = ft.Container(
                    content=ft.Column(card_children, spacing=2),
                    bgcolor="#1e293b" if not is_err else "#3b1111",
                    padding=8,
                    border=ft.Border(
                        left=ft.BorderSide(3, "#ef4444" if is_err else ("#eab308" if is_warn else "#3b82f6")),
                        bottom=ft.BorderSide(1, "#334155")
                    ),
                )
                log_list_col.controls.append(entry_card)

        try:
            log_list_col.update()
            count_label.update()
        except Exception:
            pass

    filter_buttons = {}
    def set_filter(lvl: str):
        active_filter[0] = lvl
        for k, b in filter_buttons.items():
            b.bgcolor = CLR_YELLOW if k == lvl else BG_WHITE
            try:
                b.update()
            except Exception:
                pass
        refresh_logs()

    def filter_btn(lvl: str, label: str):
        b = ft.Container(
            content=ft.Text(label, size=11, weight=ft.FontWeight.W_800, color=TEXT_DARK),
            bgcolor=CLR_YELLOW if lvl == active_filter[0] else BG_WHITE,
            border=mk_border(1, TEXT_DARK),
            padding=pad(h=8, v=4),
            on_click=lambda e, l=lvl: set_filter(l),
            ink=True,
        )
        filter_buttons[lvl] = b
        return b

    search_field = ft.TextField(
        hint_text="🔍 Tìm kiếm log (từ khóa, hàm, lỗi...)",
        text_size=12,
        height=36,
        content_padding=pad(h=10, v=6),
        border_color=TEXT_DARK,
        border_width=1,
        expand=True,
        on_change=lambda e: (search_query.__setitem__(0, e.control.value), refresh_logs()),
    )

    def copy_all_logs(e=None):
        if not mem_handler:
            return
        entries = mem_handler.get_history(level=active_filter[0], query=search_query[0], limit=500)
        lines = []
        for it in entries:
            lines.append(f"[{it['timestamp']}] [{it['level']}] [{it['name']}] [{it['filename']}:{it['lineno']}] {it['message']}")
            if it.get("exc_text"):
                lines.append(it["exc_text"])
        text_to_copy = "\n".join(lines)
        copy_to_clipboard(page, text_to_copy)
        page.show_dialog(ft.SnackBar(ft.Text(f"✓ Đã sao chép {len(entries)} bản ghi log vào Clipboard!"), bgcolor=TEXT_DARK))
        page.update()

    def clear_memory_logs(e=None):
        if mem_handler:
            mem_handler.clear()
        refresh_logs()
        page.show_dialog(ft.SnackBar(ft.Text("✓ Đã xóa sạch bộ đệm nhật ký trên UI."), bgcolor=TEXT_DARK))
        page.update()

    dlg = ft.AlertDialog(
        modal=True,
        title=ft.Row([
            ft.Row([
                ft.Text("📋", size=18),
                ft.Text("NHẬT KÝ ỨNG DỤNG (LIVE LOG VIEWER)", size=16, weight=ft.FontWeight.W_900, color=TEXT_DARK),
            ], spacing=8),
            ft.IconButton(ft.Icons.CLOSE, on_click=lambda e: safe_close_dialog(page, dlg), icon_color=TEXT_DARK),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        content=ft.Container(
            content=ft.Column([
                ft.Row([
                    filter_btn("ALL", "TẤT CẢ"),
                    filter_btn("DEBUG", "DEBUG"),
                    filter_btn("INFO", "INFO"),
                    filter_btn("WARNING", "WARN"),
                    filter_btn("ERROR", "ERROR"),
                    ft.Container(width=10),
                    search_field,
                    nb_button("🔄", on_click=refresh_logs, bgcolor=BG_WHITE, color=TEXT_DARK),
                    nb_button("📋 Sao chép", on_click=copy_all_logs, bgcolor=BG_WHITE, color=TEXT_DARK),
                    nb_button("🧹 Xóa", on_click=clear_memory_logs, bgcolor=BG_WHITE, color=TEXT_DARK),
                ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Row([
                    count_label,
                    ft.Container(expand=True),
                    ft.Text("Tự động bắt lỗi Uncaught Exceptions & Background Threads", size=10, color=TEXT_GRAY, italic=True),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Container(height=4),
                ft.Container(
                    content=log_list_col,
                    bgcolor="#0f172a",
                    border=mk_border(2, TEXT_DARK),
                    padding=8,
                    height=450,
                    expand=True,
                ),
            ], spacing=6),
            width=920,
            height=540,
        ),
    )

    page.show_dialog(dlg)
    refresh_logs()


def handle_export_lesson(page: ft.Page, lesson_id: int, lesson_title: str):
    """Xuất bài học ra tệp JSON chuẩn, hỗ trợ mở thư mục và copy vào clipboard."""
    try:
        filepath = export_lesson_to_file(lesson_id)
        if not filepath:
            page.show_dialog(ft.SnackBar(ft.Text("Không tìm thấy dữ liệu bài học để xuất."), bgcolor="#991b1b"))
            page.update()
            return

        exported_dict = export_lesson_to_dict(lesson_id)
        json_str = json.dumps(exported_dict, ensure_ascii=False, indent=2)

        def open_folder(e):
            import os
            try:
                os.startfile(str(filepath.parent))
            except Exception:
                pass

        def copy_json(e):
            copy_to_clipboard(page, json_str)
            page.show_dialog(ft.SnackBar(ft.Text("✓ Đã sao chép toàn bộ JSON bài học vào Clipboard!"), bgcolor="#166534"))
            page.update()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Text("📤 XUẤT BÀI HỌC THÀNH CÔNG", size=16, weight=ft.FontWeight.W_900, color=TEXT_DARK),
                ft.IconButton(ft.Icons.CLOSE, on_click=lambda e: safe_close_dialog(page, dlg), icon_color=TEXT_DARK),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            content=ft.Column([
                ft.Text(f"Bài học \"{lesson_title}\" đã được xuất thành tệp JSON chuẩn:", size=13, color=TEXT_DARK),
                ft.Container(height=6),
                ft.Container(
                    content=ft.Text(str(filepath), size=12, weight=ft.FontWeight.W_700, color="#1e1b4b", selectable=True),
                    bgcolor="#e0e7ff",
                    border=mk_border(1, "#6366f1"),
                    padding=10,
                ),
                ft.Container(height=14),
                ft.Text("Tệp này chứa toàn bộ Flashcard, cốt truyện và câu hỏi đọc hiểu. Bạn có thể gửi tệp này cho người khác nạp qua tab 'TẠO BÀI HỌC > Dán mã JSON'.", size=12, color=TEXT_GRAY),
                ft.Container(height=16),
                ft.Row([
                    nb_button("📁 Mở thư mục", on_click=open_folder, bgcolor=CLR_YELLOW, color=TEXT_DARK),
                    ft.Container(width=8),
                    nb_button("📋 Sao chép JSON", on_click=copy_json, bgcolor=TEXT_DARK, color=TEXT_WHITE),
                ], alignment=ft.MainAxisAlignment.END),
            ], spacing=0, tight=True, width=480),
        )
        page.show_dialog(dlg)
    except Exception as ex:
        page.show_dialog(ft.SnackBar(ft.Text(f"Lỗi khi xuất bài học: {ex}"), bgcolor="#991b1b"))
        page.update()


def build_lessons_screen(page: ft.Page, on_start_session, on_edit_lesson) -> ft.Control:
    lessons = get_all_lessons()
    
    lessons_list = ft.Column(spacing=16, scroll=ft.ScrollMode.AUTO, expand=True)

    def show_flashcard_mode_dialog(lesson_id: int):
        """Hiện dialog cho phép user chọn chế độ Flashcard: Đảo thẻ hoặc Giữ nguyên thứ tự."""
        def close_and_navigate(shuffle: bool):
            safe_close_dialog(page, dlg)
            on_start_session("flashcard", lesson_id, shuffle=shuffle)

        def on_shuffled(e):
            close_and_navigate(shuffle=True)

        def on_ordered(e):
            close_and_navigate(shuffle=False)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("CHỌN CHẾ ĐỘ FLASHCARD", size=16, weight=ft.FontWeight.W_900, color=TEXT_DARK),
            content=ft.Column([
                ft.Text("Bạn muốn học Flashcard theo thứ tự nào?", size=13, color=TEXT_GRAY),
                ft.Container(height=20),
                ft.Row([
                    nb_button("🔀  Đảo thẻ", on_click=on_shuffled, bgcolor=CLR_YELLOW, color=TEXT_DARK),
                    ft.Container(width=10),
                    nb_button("📜  Giữ nguyên thứ tự", on_click=on_ordered, bgcolor=TEXT_DARK, color=TEXT_WHITE),
                ], alignment=ft.MainAxisAlignment.END),
            ], spacing=0, tight=True, width=380),
        )
        page.show_dialog(dlg)

    def show_reading_mode_dialog(lesson_id: int):
        """Hiện dialog cho phép user chọn chế độ Đọc hiểu: Đảo câu hoặc Không đảo câu."""
        def close_and_navigate(shuffle: bool):
            safe_close_dialog(page, dlg)
            on_start_session("reading", lesson_id, shuffle=shuffle)

        def on_shuffled(e):
            close_and_navigate(shuffle=True)

        def on_ordered(e):
            close_and_navigate(shuffle=False)

        warning_note = ft.Container(
            content=ft.Row([
                ft.Text("⚠", size=14, color="#92400e"),
                ft.Text(
                    "Đảo câu sẽ khiến bạn không rõ đầu đuôi câu chuyện khi lướt qua các lựa chọn.",
                    size=12,
                    color="#92400e",
                    weight=ft.FontWeight.W_600,
                    expand=True,
                ),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.START),
            bgcolor="#fef3c7",
            border=mk_border(2, "#92400e"),
            padding=pad(h=12, v=10),
        )

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("CHỌN CHẾ ĐỘ ĐỌC HIỂU", size=16, weight=ft.FontWeight.W_900, color=TEXT_DARK),
            content=ft.Column([
                ft.Text("Bạn muốn đọc hiểu theo thứ tự nào?", size=13, color=TEXT_GRAY),
                ft.Container(height=12),
                warning_note,
                ft.Container(height=20),
                ft.Row([
                    nb_button("🔀  Đảo câu", on_click=on_shuffled, bgcolor=CLR_YELLOW, color=TEXT_DARK),
                    ft.Container(width=10),
                    nb_button("📖  Không đảo câu", on_click=on_ordered, bgcolor=TEXT_DARK, color=TEXT_WHITE),
                ], alignment=ft.MainAxisAlignment.END),
            ], spacing=0, tight=True, width=380),
        )
        page.show_dialog(dlg)


    def show_help_dialog():
        fc_tab_btn = nb_button("FLASHCARD", bgcolor=CLR_YELLOW, color=TEXT_DARK)
        rd_tab_btn = nb_button("ĐỌC HIỂU", bgcolor=BG_WHITE, color=TEXT_DARK)

        fc_content = ft.Column([
            ft.Text("Bước 1. Recall (Không dùng đáp án)", size=14, weight=ft.FontWeight.W_900, color=TEXT_DARK),
            ft.Text("• Nhìn vào mặt trước của flashcard.\n• Cố gắng nhớ:\n   - Nghĩa\n   - Cách viết\n   - Cách phát âm\n• Nếu nhớ được ➔ Chuyển sang Bước 2.\n• Nếu không nhớ ➔ Vẫn thử đoán trước khi lật.", size=13, color=TEXT_DARK),
            ft.Container(height=12),

            ft.Text("Bước 2. Đầu ra lần 1 (Trước khi lật)", size=14, weight=ft.FontWeight.W_900, color=TEXT_DARK),
            ft.Text("• Viết từ đó ra giấy.\n• Phát âm thành tiếng 1-2 lần.", size=13, color=TEXT_DARK),
            ft.Container(height=12),

            ft.Text("Bước 3. Kiểm tra", size=14, weight=ft.FontWeight.W_900, color=TEXT_DARK),
            ft.Text("• Lật flashcard.\n• So sánh với:\n   - Nghĩa đúng\n   - Chính tả đúng\n   - Phát âm đúng", size=13, color=TEXT_DARK),
            ft.Container(height=12),

            ft.Text("Bước 4. Sửa lỗi", size=14, weight=ft.FontWeight.W_900, color=TEXT_DARK),
            ft.Text("• Nếu có sai:\n   - Sửa lại chính tả.\n   - Điều chỉnh lại phát âm.\n• Nếu đúng: Xác nhận lại.", size=13, color=TEXT_DARK),
            ft.Container(height=12),

            ft.Container(
                content=ft.Column([
                    ft.Text("Bước 5. Đầu ra lần 2 (Sau khi sửa)", size=14, weight=ft.FontWeight.W_900, color="#3730a3"),
                    ft.Text("// Bước quan trọng nhất, giúp củng cố sau feedback", size=11, weight=ft.FontWeight.W_700, color="#6366f1"),
                    ft.Text("• Viết lại từ đúng.\n• Phát âm lại 1-3 lần tuỳ độ chắc.", size=13, color="#3730a3", weight=ft.FontWeight.W_600),
                ], spacing=2),
                bgcolor="#e0e7ff",
                border=ft.Border(left=ft.BorderSide(4, "#3730a3")),
                padding=pad(h=12, v=10),
            ),
            ft.Container(height=12),

            ft.Text("Bước 6. Chuyển sang thẻ tiếp theo", size=14, weight=ft.FontWeight.W_900, color=TEXT_DARK),
            ft.Text("• Tiếp tục vòng lặp cho đến khi hết thẻ.", size=13, color=TEXT_DARK),
            ft.Container(height=16),

            ft.Container(height=2, bgcolor=TEXT_DARK),
            ft.Container(height=12),

            ft.Text("☠ Quy tắc bổ sung", size=16, weight=ft.FontWeight.W_900, color="#991b1b"),
            ft.Text("• Không skip trước khi recall: Nếu nhìn đáp án quá sớm, đó không phải là \"ghi nhớ\" mà là \"nhận diện\".\n• Luôn có đầu ra (viết + nói): Nếu chỉ nhìn, đó gọi là học thụ động.\n• Về việc sai: Sai ở Bước 1-2 là có chủ đích. Sai ở Bước 5 mới là vấn đề!", size=13, color=TEXT_DARK),
            ft.Container(height=14),

            ft.Container(
                content=ft.Column([
                    ft.Text("CƠ CHẾ HOẠT ĐỘNG CỦA THUẬT TOÁN:", size=12, weight=ft.FontWeight.W_900, color=TEXT_DARK),
                    ft.Text("• Giai đoạn 1 (Score 0-2): Học định nghĩa cơ bản và tiếp xúc với ví dụ đa chiều.\n• Giai đoạn 2 (Score >= 3): Rèn luyện phản xạ cứng. Bạn bị tước quyền lật thẻ bằng cú click, thay vào đó phải gõ chính xác từ vựng. Gõ sai sẽ bị trừ 1 điểm!\n• Mục tiêu: Đạt 6 điểm (Master) để khóa chặt bộ nhớ. Đừng vội vàng bấm \"Quá dễ\".", size=12, color=TEXT_GRAY),
                ], spacing=4),
                bgcolor="#f3f4f6",
                border=mk_border(2, TEXT_DARK),
                padding=pad(all_=12),
            )
        ], spacing=0, scroll=ft.ScrollMode.AUTO)

        rd_content = ft.Container(
            content=ft.Text("TRỐNG", size=18, weight=ft.FontWeight.W_900, color=TEXT_GRAY),
            alignment=ft.Alignment(0, 0),
            padding=pad(all_=60),
        )

        body_box = ft.Container(content=fc_content, height=420, expand=True)

        def set_tab(mode: str):
            if mode == "fc":
                fc_tab_btn.bgcolor = CLR_YELLOW
                fc_tab_btn.content.controls[0].color = TEXT_DARK
                rd_tab_btn.bgcolor = BG_WHITE
                rd_tab_btn.content.controls[0].color = TEXT_DARK
                body_box.content = fc_content
            else:
                rd_tab_btn.bgcolor = CLR_BLUE
                rd_tab_btn.content.controls[0].color = TEXT_DARK
                fc_tab_btn.bgcolor = BG_WHITE
                fc_tab_btn.content.controls[0].color = TEXT_DARK
                body_box.content = rd_content
            fc_tab_btn.update()
            rd_tab_btn.update()
            body_box.update()

        fc_tab_btn.on_click = lambda e: set_tab("fc")
        rd_tab_btn.on_click = lambda e: set_tab("rd")

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Text("📖 HƯỚNG DẪN HỌC", size=18, weight=ft.FontWeight.W_900, color=TEXT_DARK, expand=True),
                ft.IconButton(ft.Icons.CLOSE, on_click=lambda e: safe_close_dialog(page, dlg), icon_color=TEXT_DARK),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            content=ft.Column([
                ft.Row([fc_tab_btn, rd_tab_btn], spacing=10),
                ft.Container(height=12),
                body_box,
            ], spacing=0, tight=True, width=540),
        )
        page.show_dialog(dlg)

    if not lessons:
        lessons_list.controls.append(
            ft.Text("Chưa có bài học nào. Hãy qua tab 'TẠO BÀI HỌC' để thêm bài mới!", size=14, color=TEXT_GRAY, italic=True)
        )
    else:
        for les in lessons:
            # Lấy thông tin chi tiết bài học để đếm số từ
            full_les = get_lesson_by_id(les["id"])
            try:
                vocab_ids = json.loads(full_les.get("vocab_ids") or "[]") if full_les else []
            except Exception:
                vocab_ids = []
            vocab_count = len(vocab_ids)

            les_title = les.get("title") or "BÀI HỌC"
            les_story = les.get("story_context") or ""
            lesson_card = nb_card(
                ft.Row([
                    ft.Column([
                        ft.Text(les_title.upper(), size=18, weight=ft.FontWeight.W_900, color=TEXT_DARK),
                        ft.Text(f"Số từ vựng: {vocab_count} từ  |  Tạo ngày: {str(les.get('created_at', ''))[:10]}", size=12, color=TEXT_GRAY, weight=ft.FontWeight.W_600),
                        ft.Container(height=6),
                        ft.Text(les_story[:120] + "..." if len(les_story) > 120 else les_story, size=13, color=TEXT_GRAY, italic=True),
                    ], expand=True, spacing=2),
                    ft.Row([
                        nb_button("FLASHCARD", on_click=lambda e, lid=les["id"]: show_flashcard_mode_dialog(lid), bgcolor=CLR_YELLOW),
                        nb_button("ĐỌC HIỂU", on_click=lambda e, lid=les["id"]: show_reading_mode_dialog(lid), bgcolor=CLR_BLUE),
                        ft.Container(
                            content=ft.Text("📤", size=16, color=TEXT_DARK),
                            bgcolor=BG_WHITE,
                            border=mk_border(2, TEXT_DARK),
                            shadow=SHADOW_SM,
                            padding=pad(h=12, v=12),
                            on_click=lambda e, lid=les["id"], lt=les_title: handle_export_lesson(page, lid, lt),
                            ink=True,
                            tooltip="Xuất bài học (JSON)",
                        ),
                        ft.Container(
                            content=ft.Text("⚙", size=16, color=TEXT_WHITE),
                            bgcolor=TEXT_DARK,
                            border=mk_border(2, TEXT_DARK),
                            shadow=SHADOW_SM,
                            padding=pad(h=12, v=12),
                            on_click=lambda e, lid=les["id"]: on_edit_lesson(lid),
                            ink=True,
                            tooltip="Chỉnh sửa bài học",
                        ),
                    ], spacing=10)
                ], spacing=20),
                shadow_size="sm"
            )
            lessons_list.controls.append(lesson_card)

    btn_help = ft.Container(
        content=ft.Text("?", size=18, weight=ft.FontWeight.W_900, color=TEXT_DARK, text_align=ft.TextAlign.CENTER),
        bgcolor=CLR_YELLOW,
        border=mk_border(2, TEXT_DARK),
        shadow=SHADOW_SM,
        padding=pad(h=14, v=8),
        on_click=lambda e: show_help_dialog(),
        ink=True,
        tooltip="Hướng dẫn học",
    )

    header_row = ft.Row(
        [
            ft.Column([
                label_text("Học tập"),
                heading_text("Bài học"),
            ], spacing=0, expand=True),
            btn_help,
        ],
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    return ft.Column(
        [
            header_row,
            ft.Container(height=1, bgcolor=TEXT_DARK, margin=marg(top=6, bottom=20)),
            lessons_list,
        ],
        spacing=0, expand=True,
    )


def build_create_screen(page: ft.Page, on_success, on_lock_nav=None) -> ft.Control:
    is_generating = {"status": False}
    # Tab 1: Nhập tay trực tiếp
    title_inp = ft.TextField(label="Tiêu đề bài học", border_color=TEXT_DARK, border_width=2, border_radius=0)
    story_inp = ft.TextField(label="Cốt truyện / Ngữ cảnh", border_color=TEXT_DARK, border_width=2, border_radius=0, multiline=True, min_lines=3)
    
    # Khu vực thêm từ vựng đơn giản (JSON array hoặc gõ tay dạng văn bản)
    vocab_raw_inp = ft.TextField(
        label="Danh sách từ vựng (Nhập từ cách nhau bằng dấu phẩy hoặc dán JSON Array)", 
        border_color=TEXT_DARK, border_width=2, border_radius=0,
        multiline=True, min_lines=4,
        hint_text='Cách 1 (Gõ tự do): bearing, buoyancy, calibrate, circumstance\nCách 2 (Kèm nghĩa): bearing: ổ trục, calibrate: hiệu chuẩn\nCách 3 (Dán JSON Array): [{"word": "equilibrium", "pos": "noun", "definition_vi_simple": "Trạng thái cân bằng"}]'
    )

    # Tab 2: Nạp qua file JSON
    json_text_inp = ft.TextField(
        label="Dán nội dung JSON chuẩn của bài học (hoặc mảng JSON Array từ vựng):",
        border_color=TEXT_DARK, border_width=2, border_radius=0,
        multiline=True, min_lines=10,
        hint_text="Dán JSON bài học đầy đủ { 'title': ..., 'vocab': [...] } hoặc dán mảng JSON Array từ vựng [ {...}, {...} ]..."
    )

    error_txt = ft.Text("", color="#991b1b", weight=ft.FontWeight.W_700)

    # 1. Logic submit qua Form Nhập Tay
    def submit_form(e):
        error_txt.value = ""
        title_val = (title_inp.value or "").strip()
        if not title_val:
            error_txt.value = "Vui lòng điền tiêu đề bài học."
            page.update()
            return
        
        try:
            vocab_list = []
            raw_v = (vocab_raw_inp.value or "").strip()
            if raw_v:
                # Kiểm tra nếu là JSON Array
                if raw_v.startswith("[") and raw_v.endswith("]"):
                    vocab_list = json.loads(raw_v)
                    if not isinstance(vocab_list, list):
                        raise ValueError("Từ vựng JSON phải là một danh sách các object (JSON Array).")
                else:
                    # Hỗ trợ nhập danh sách từ phân tách bằng dấu phẩy, chấm phẩy hoặc xuống dòng
                    items = [w.strip() for w in raw_v.replace(";", ",").replace("\n", ",").split(",") if w.strip()]
                    for it in items:
                        if ":" in it or " - " in it:
                            sep = ":" if ":" in it else " - "
                            w, d = it.split(sep, 1)
                            vocab_list.append({"word": w.strip(), "definition_vi": d.strip()})
                        else:
                            vocab_list.append({"word": it})
            
            lesson_dict = {
                "title": title_val,
                "story_context": (story_inp.value or "").strip(),
                "vocab": vocab_list,
                "questions": [],
                "flashcards": []
            }
            
            res = load_lesson_from_dict(lesson_dict)
            if res["success"]:
                page.show_dialog(ft.SnackBar(ft.Text("✓ Tạo bài học thành công!"), bgcolor="#166534"))
                on_success()
            else:
                error_txt.value = "\n".join(res["errors"])
        except Exception as ex:
            error_txt.value = f"Lỗi xử lý từ vựng: {ex}"
        page.update()

    # 2. Logic submit qua JSON dán trực tiếp
    def submit_json(e):
        error_txt.value = ""
        raw_text = (json_text_inp.value or "").strip()
        if not raw_text:
            error_txt.value = "Nội dung JSON đang rỗng."
            page.update()
            return
        
        try:
            data = json.loads(raw_text)
            is_array = isinstance(data, list)
            res = load_lesson_from_dict(data)
            if res["success"]:
                msg = "✓ Nạp mảng từ vựng JSON Array thành công!" if is_array else "✓ Nạp bài học bằng JSON thành công!"
                page.show_dialog(ft.SnackBar(ft.Text(msg), bgcolor="#166534"))
                on_success()
            else:
                error_txt.value = "\n".join(res["errors"])
        except Exception as ex:
            error_txt.value = f"JSON không hợp lệ: {ex}"
        page.update()


    # ── TAB 1: NHẬP TAY ĐƠN GIẢN ──────────────────────────────────────────
    manual_sample_json = (
        '[\n'
        '  {\n'
        '    "word": "airborne",\n'
        '    "pos": "adjective",\n'
        '    "ipa_uk": "/ˈeə.bɔːn/",\n'
        '    "definition_simple_en": "Carried or moved through the air.",\n'
        '    "definition_minimal_en": "Carried by air currents",\n'
        '    "definition_vi_simple": "Lơ lửng trong không khí",\n'
        '    "nuance_en": "Technical / passive transport by air currents",\n'
        '    "nuance_vi": "Chỉ vật thể/bào tử bị dòng khí cuốn đi thụ động.",\n'
        '    "example_en": "The airborne spore particles entered the bunker ventilation.",\n'
        '    "example_vi": "Các bào tử lơ lửng trong không khí đã xâm nhập vào hệ thống thông gió hầm ngầm.",\n'
        '    "contrast": "Differs from \'flying\' which requires active self-propulsion.",\n'
        '    "contrast_vi": "Khác với \'flying\' (bay chủ động nhờ động lực), \'airborne\' là trôi dạt thụ động.",\n'
        '    "usage_distinction": "Used for dust, viruses, seeds, or aircraft already aloft.",\n'
        '    "usage_distinction_vi": "Dùng cho bụi, virus, hạt giống hoặc phi cơ đã cất cánh.",\n'
        '    "tone_en": "Technical / Scientific"\n'
        '  },\n'
        '  {\n'
        '    "word": "equilibrium",\n'
        '    "pos": "noun",\n'
        '    "ipa_uk": "/ˌiː.kwɪˈlɪb.ri.əm/",\n'
        '    "definition_simple_en": "A state in which opposing forces or influences are balanced.",\n'
        '    "definition_vi_simple": "Trạng thái cân bằng",\n'
        '    "tone_en": "Formal / Academic"\n'
        '  }\n'
        ']'
    )

    def copy_manual_sample(e):
        copy_to_clipboard(page, manual_sample_json)
        page.show_dialog(ft.SnackBar(ft.Text("📋 Đã sao chép mẫu JSON Array vào bộ nhớ tạm!"), bgcolor="#166534"))
        try:
            page.update()
        except Exception:
            pass

    vocab_preview = ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Text("MẪU JSON ARRAY", size=9, weight=ft.FontWeight.W_800, color=TEXT_GRAY, style=ft.TextStyle(letter_spacing=1.5), expand=True),
                ft.TextButton("Sao chép", icon=ft.Icons.CONTENT_COPY_ROUNDED, on_click=copy_manual_sample, style=ft.ButtonStyle(color="#3730a3")),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Container(height=4),
            ft.Text(
                manual_sample_json,
                size=10,
                color=TEXT_DARK,
                font_family="monospace",
                selectable=True,
            )
        ], spacing=0, scroll=ft.ScrollMode.AUTO),
        bgcolor="#f9fafb",
        border=mk_border(1, "#d1d5db"),
        padding=pad(h=12, v=10),
        col={"xs": 12, "lg": 4},
        height=380,
    )

    manual_view = ft.Column([
        ft.ResponsiveRow([
            ft.Column([
                ft.Container(height=10),
                title_inp,
                story_inp,
                vocab_raw_inp,
                ft.Container(height=10),
                nb_button("Tạo bài học", on_click=submit_form, bgcolor=TEXT_DARK, color=TEXT_WHITE)
            ], col={"xs": 12, "lg": 8}, spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
            vocab_preview,
        ], spacing=16, vertical_alignment=ft.CrossAxisAlignment.START)
    ], scroll=ft.ScrollMode.AUTO, expand=True, spacing=0)

    # ── TAB 2: DÁN FILE JSON CHUẨN ───────────────────────────────────────
    array_sample_json = (
        '[\n'
        '  {\n'
        '    "word": "airborne",\n'
        '    "pos": "adjective",\n'
        '    "ipa_uk": "/ˈeə.bɔːn/",\n'
        '    "definition_simple_en": "Carried or moved through the air.",\n'
        '    "definition_minimal_en": "Carried by air currents",\n'
        '    "definition_vi_simple": "Lơ lửng trong không khí",\n'
        '    "nuance_en": "Technical / passive transport",\n'
        '    "nuance_vi": "Chỉ vật thể bị dòng khí cuốn đi thụ động.",\n'
        '    "example_en": "The airborne spore particles entered the bunker ventilation.",\n'
        '    "example_vi": "Các bào tử lơ lửng trong không khí đã xâm nhập vào hệ thống thông gió hầm ngầm.",\n'
        '    "contrast": "Differs from \'flying\' which requires self-propulsion.",\n'
        '    "contrast_vi": "Khác với \'flying\' (bay chủ động), \'airborne\' là trôi dạt thụ động.",\n'
        '    "usage_distinction": "Used for particles, pathogens, or aircraft in flight.",\n'
        '    "usage_distinction_vi": "Dùng cho bụi mịn, mầm bệnh hoặc máy bay đang bay.",\n'
        '    "tone_en": "Technical / Scientific"\n'
        '  },\n'
        '  {\n'
        '    "word": "equilibrium",\n'
        '    "pos": "noun",\n'
        '    "ipa_uk": "/ˌiː.kwɪˈlɪb.ri.əm/",\n'
        '    "definition_simple_en": "A state in which opposing forces are balanced.",\n'
        '    "definition_vi_simple": "Trạng thái cân bằng",\n'
        '    "tone_en": "Formal / Academic"\n'
        '  }\n'
        ']'
    )

    full_sample_json = (
        "{\n"
        '  "title": "Subterranean Research Archive",\n'
        '  "story_context": "[Beginning]\\nDeep inside the underground facility...\\n[Development]\\nDr. Vance detected an anomaly...",\n'
        '  "vocab": [\n'
        '    {\n'
        '      "word": "airborne",\n'
        '      "pos": "adjective",\n'
        '      "ipa_uk": "/ˈeə.bɔːn/",\n'
        '      "definition_simple_en": "Carried or moved through the air.",\n'
        '      "definition_minimal_en": "Carried by air currents",\n'
        '      "definition_vi_simple": "Lơ lửng trong không khí",\n'
        '      "nuance_en": "Technical / passive transport",\n'
        '      "nuance_vi": "Chỉ vật thể bị dòng khí cuốn đi thụ động.",\n'
        '      "example_en": "The airborne spore particles entered the bunker ventilation.",\n'
        '      "example_vi": "Các bào tử lơ lửng trong không khí đã xâm nhập vào hệ thống thông gió hầm ngầm.",\n'
        '      "contrast": "Differs from \'flying\' which requires self-propulsion.",\n'
        '      "contrast_vi": "Khác với \'flying\' (bay chủ động), \'airborne\' là trôi dạt thụ động.",\n'
        '      "usage_distinction": "Used for particles, pathogens, or aircraft in flight.",\n'
        '      "usage_distinction_vi": "Dùng cho bụi mịn, mầm bệnh hoặc máy bay đang bay.",\n'
        '      "tone_en": "Technical / Scientific"\n'
        '    }\n'
        '  ],\n'
        '  "questions": [\n'
        '    {\n'
        '      "type": "single",\n'
        '      "instruction": "Contextual inference",\n'
        '      "story": "Dr. Vance observed the glowing spores drifting through the chamber...",\n'
        '      "q": "What characteristic of the spores makes them dangerous to the ventilation system?",\n'
        '      "options": [\n'
        '        "They are airborne and carried passively by air currents",\n'
        '        "They have powerful mechanical engines",\n'
        '        "They only travel through solid bedrock",\n'
        '        "They are completely stationary"\n'
        '      ],\n'
        '      "correct": 0,\n'
        '      "explain": "\'Airborne\' indicates the spores drift freely in the air, allowing them to enter intake ducts."\n'
        '    }\n'
        '  ]\n'
        '}'
    )

    current_mode = {"type": "array"}

    sample_text_ctl = ft.Text(
        array_sample_json,
        size=10,
        color=TEXT_DARK,
        font_family="monospace",
        selectable=True,
    )

    def update_json_mode(mode: str):
        current_mode["type"] = mode
        if mode == "array":
            sample_text_ctl.value = array_sample_json
            btn_mode_array.bgcolor = TEXT_DARK
            btn_mode_array.content.color = BG_WHITE
            btn_mode_full.bgcolor = BG_WHITE
            btn_mode_full.content.color = TEXT_DARK
        else:
            sample_text_ctl.value = full_sample_json
            btn_mode_full.bgcolor = TEXT_DARK
            btn_mode_full.content.color = BG_WHITE
            btn_mode_array.bgcolor = BG_WHITE
            btn_mode_array.content.color = TEXT_DARK
        try:
            page.update()
        except Exception:
            pass

    def copy_active_sample(e):
        val = array_sample_json if current_mode["type"] == "array" else full_sample_json
        copy_to_clipboard(page, val)
        lbl = "Mảng JSON Array" if current_mode["type"] == "array" else "Mẫu JSON toàn bài"
        page.show_dialog(ft.SnackBar(ft.Text(f"📋 Đã sao chép {lbl} vào bộ nhớ tạm!"), bgcolor="#166534"))
        try:
            page.update()
        except Exception:
            pass

    btn_mode_array = ft.Container(
        content=ft.Text("MẢNG JSON ARRAY", size=9, weight=ft.FontWeight.W_800, color=BG_WHITE),
        bgcolor=TEXT_DARK,
        border=mk_border(1, TEXT_DARK),
        padding=pad(h=8, v=4),
        on_click=lambda e: update_json_mode("array"),
        ink=True,
    )
    btn_mode_full = ft.Container(
        content=ft.Text("TOÀN BÀI HỌC", size=9, weight=ft.FontWeight.W_800, color=TEXT_DARK),
        bgcolor=BG_WHITE,
        border=mk_border(1, TEXT_DARK),
        padding=pad(h=8, v=4),
        on_click=lambda e: update_json_mode("full"),
        ink=True,
    )

    json_guide = nb_card(
        ft.Column([
            ft.Row([
                ft.Row([btn_mode_array, btn_mode_full], spacing=4),
                ft.TextButton("Sao chép", icon=ft.Icons.CONTENT_COPY_ROUNDED, on_click=copy_active_sample, style=ft.ButtonStyle(color="#3730a3")),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER, alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Container(height=6),
            sample_text_ctl
        ], spacing=0, scroll=ft.ScrollMode.AUTO),
        shadow_size="sm",
        bgcolor="#f9fafb",
    )
    json_guide.col = {"xs": 12, "lg": 4}
    json_guide.height = 380

    json_view = ft.Column([
        ft.ResponsiveRow([
            ft.Column([
                ft.Container(height=10),
                json_text_inp,
                ft.Container(height=10),
                nb_button("Nạp bài học bằng JSON", on_click=submit_json, bgcolor=TEXT_DARK, color=TEXT_WHITE)
            ], col={"xs": 12, "lg": 8}, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
            json_guide
        ], spacing=20, vertical_alignment=ft.CrossAxisAlignment.START)
    ], scroll=ft.ScrollMode.AUTO, expand=True, spacing=0)

    # ── TAB SWITCHER STATE ────────────────────────────────────────────────
    pipeline_cache = {"view": None}
    tab_state = {"current": "manual"}
    tab_content_area = ft.Container(content=manual_view, expand=True)
    is_mounted = [False]

    def switch_tab(tab_name):
        if is_generating["status"]:
            page.show_dialog(ft.SnackBar(
                ft.Text("🔒 AI đang tạo bài học. Vui lòng đợi hoàn thành!"),
                bgcolor="#991b1b"
            ))
            try:
                page.update()
            except Exception:
                pass
            return

        tab_state["current"] = tab_name
        # Cập nhật style nút
        for btn, name in [(manual_btn, "manual"), (json_btn, "json"), (ai_btn, "pipeline")]:
            is_active = (tab_name == name)
            btn.bgcolor = TEXT_DARK if is_active else BG_WHITE
            if hasattr(btn, "content") and hasattr(btn.content, "controls"):
                for c in btn.content.controls:
                    if hasattr(c, "color"):
                        c.color = BG_WHITE if is_active else TEXT_DARK
        
        # Cập nhật content
        if tab_name == "manual":
            tab_content_area.content = manual_view
        elif tab_name == "json":
            tab_content_area.content = json_view
        else:  # pipeline / ai tab (unified)
            if pipeline_cache["view"] is None:
                pipeline_cache["view"] = build_pipeline_tab_content(
                    page=page,
                    on_success=on_success,
                    on_lock_nav=on_lock_nav,
                    is_generating=is_generating,
                )
            tab_content_area.content = pipeline_cache["view"]
        
        if is_mounted[0]:
            try:
                page.update()
            except Exception:
                try:
                    manual_btn.update()
                    json_btn.update()
                    ai_btn.update()
                    tab_content_area.update()
                except Exception:
                    pass

    manual_btn = nb_button("NHẬP TAY", width=160,     on_click=lambda e: switch_tab("manual"),   bgcolor=TEXT_DARK, color=TEXT_WHITE)
    json_btn   = nb_button("NHẬP JSON", width=160,    on_click=lambda e: switch_tab("json"),     bgcolor=BG_WHITE, color=TEXT_DARK)
    ai_btn     = nb_button("TẠO BẰNG AI", width=180, on_click=lambda e: switch_tab("pipeline"), bgcolor=BG_WHITE, color=TEXT_DARK)

    tab_header = ft.Row([manual_btn, json_btn, ai_btn], spacing=10, wrap=True)
    is_mounted[0] = True

    return ft.Column(
        [
            label_text("Nội dung"),
            heading_text("Tạo bài học"),
            ft.Container(height=1, bgcolor=TEXT_DARK, margin=marg(top=6, bottom=20)),
            tab_header,
            ft.Container(height=10),
            tab_content_area,
            ft.Container(height=10),
            error_txt,
        ],
        spacing=0, expand=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# ── PIPELINE BUILDER TAB CONTENT ──────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

def load_all_model_options(settings: dict) -> tuple[list[ft.dropdown.Option], str]:
    """Tự động gom danh sách model Ollama local và các model Cloud kèm nhãn phù hợp."""
    has_openai_key = bool(settings.get("openai_api_key", "").strip())
    has_gemini_key = bool(settings.get("gemini_api_key", "").strip())

    import subprocess
    ollama_models = []
    try:
        res = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=3)
        lines = res.stdout.strip().splitlines()
        for line in lines[1:]:
            parts = line.split()
            if parts:
                ollama_models.append(parts[0])
    except Exception:
        pass

    default_locals = ["qwen3:4b", "llama3.2", "mistral", "gemma2"]
    if settings.get("pipeline_model_ollama"):
        default_locals.append(settings.get("pipeline_model_ollama"))
    for m in default_locals:
        if m not in ollama_models:
            ollama_models.append(m)

    options = []

    # Local models
    for m in ollama_models:
        options.append(ft.dropdown.Option(
            key=f"ollama:{m}",
            text=f"🤖 {m}  - local -",
        ))

    # Cloud models - Gemini (Google AI)
    gemini_models = ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-flash-latest", "gemini-flash-lite-latest", "gemma-4-31b-it"]
    if settings.get("pipeline_model_gemini") and settings.get("pipeline_model_gemini") not in gemini_models:
        gemini_models.append(settings.get("pipeline_model_gemini"))

    tag_gemini = "- cloud -" if has_gemini_key else "- cloud, require API key -"
    for m in gemini_models:
        options.append(ft.dropdown.Option(
            key=f"gemini:{m}",
            text=f"☁️ {m}  {tag_gemini}",
        ))

    # Cloud models - OpenAI
    openai_models = ["gpt-4o-mini", "gpt-4o", "gpt-3.5-turbo"]
    if settings.get("pipeline_model_openai") and settings.get("pipeline_model_openai") not in openai_models:
        openai_models.append(settings.get("pipeline_model_openai"))

    tag_openai = "- cloud -" if has_openai_key else "- cloud, require API key -"
    for m in openai_models:
        options.append(ft.dropdown.Option(
            key=f"openai:{m}",
            text=f"☁️ {m}  {tag_openai}",
        ))

    # Tuỳ chọn nhập model tùy chỉnh
    options.append(ft.dropdown.Option(
        key="custom:custom",
        text="✍️ Nhập tên model tùy chỉnh khác...",
    ))

    curr_prov = settings.get("ai_provider", "ollama")
    curr_mod = settings.get(f"pipeline_model_{curr_prov}", "qwen3:4b")
    default_key = f"{curr_prov}:{curr_mod}"

    valid_keys = [o.key for o in options]
    if default_key not in valid_keys:
        default_key = valid_keys[0] if valid_keys else "ollama:qwen3:4b"

    return options, default_key


def build_pipeline_tab_content(page: ft.Page, on_success, on_lock_nav=None, is_generating=None) -> ft.Control:
    """
    Nội dung tab 'Tự động tạo bằng AI' bên trong màn hình Tạo bài học.
    Bao gồm: form input, Story Taxonomy presets & custom controls, model dropdown, stepper 13 bước, log realtime, nút Start/Cancel.
    """
    import threading
    from datetime import datetime
    from story_taxonomy import (
        TAXONOMY_PRESETS, GENRES, TECH_AESTHETICS, POINTS_OF_VIEW,
        INFORMATION_STRUCTURES, TONES, REALITY_RULES
    )

    # ── State ────────────────────────────────────────────────────────────────
    pipeline_state = {
        "running": False,
        "stop_event": None,
        "result": None,
        "checkpoint": None,
        "request": None,
        "title": "",
    }

    run_lock = threading.RLock()

    # ── Inputs ───────────────────────────────────────────────────────────────
    pl_settings = load_settings()

    pl_vocab_inp = ft.TextField(
        label="Từ vựng (cách nhau bằng dấu phẩy)",
        border_color=TEXT_DARK, border_width=2, border_radius=0,
        hint_text="Ví dụ: airborne, degradation, abundant, neutrality, harmony, emissions",
    )

    # ── Story Taxonomy Selectors ─────────────────────────────────────────────
    preset_keys = list(TAXONOMY_PRESETS.keys())
    preset_dropdown_options = [ft.dropdown.Option(k, k) for k in preset_keys] + [ft.dropdown.Option("custom", "Tùy chỉnh (Custom)...")]

    pl_preset_dropdown = ft.Dropdown(
        label="🎭 Phong cách cốt truyện (Story Taxonomy Preset)",
        border_color=TEXT_DARK, border_width=2, border_radius=0,
        options=preset_dropdown_options,
        value="SCP / Anomaly Archive",
    )

    pl_custom_preset_inp = ft.TextField(
        label="✍️ Tên phong cách cốt truyện tùy chỉnh",
        border_color="#4f46e5", border_width=2, border_radius=0,
        hint_text="Ví dụ: Cyberpunk Noir / Cybernetic Investigation...",
        visible=False,
        bgcolor="#f5f3ff",
    )

    pl_genre_dropdown = ft.Dropdown(
        label="Thể loại (Genre)", dense=True,
        border_color=TEXT_DARK, border_width=2, border_radius=0,
        options=[ft.dropdown.Option(g, g) for g in GENRES] + [ft.dropdown.Option("custom", "Tùy chỉnh (Custom)...")],
        value="SCP_like",
    )
    pl_custom_genre_inp = ft.TextField(
        label="Nhập Thể loại tùy chỉnh", dense=True,
        border_color=TEXT_DARK, border_width=2, border_radius=0,
        hint_text="Ví dụ: cosmic_horror, psychological_thriller...",
        visible=False,
    )

    pl_aesthetic_dropdown = ft.Dropdown(
        label="Thẩm mỹ công nghệ (Tech Aesthetic)", dense=True,
        border_color=TEXT_DARK, border_width=2, border_radius=0,
        options=[ft.dropdown.Option(t, t) for t in TECH_AESTHETICS] + [ft.dropdown.Option("custom", "Tùy chỉnh (Custom)...")],
        value="biopunk",
    )
    pl_custom_aesthetic_inp = ft.TextField(
        label="Nhập Thẩm mỹ công nghệ tùy chỉnh", dense=True,
        border_color=TEXT_DARK, border_width=2, border_radius=0,
        hint_text="Ví dụ: solarpunk, retrofuturism, atompunk...",
        visible=False,
    )

    pl_pov_dropdown = ft.Dropdown(
        label="Góc nhìn (POV)", dense=True,
        border_color=TEXT_DARK, border_width=2, border_radius=0,
        options=[ft.dropdown.Option(p, p) for p in POINTS_OF_VIEW] + [ft.dropdown.Option("custom", "Tùy chỉnh (Custom)...")],
        value="documentary",
    )
    pl_custom_pov_inp = ft.TextField(
        label="Nhập Góc nhìn (POV) tùy chỉnh", dense=True,
        border_color=TEXT_DARK, border_width=2, border_radius=0,
        hint_text="Ví dụ: second_person, collective_we...",
        visible=False,
    )

    pl_infostruct_dropdown = ft.Dropdown(
        label="Hình thức tài liệu (Info Delivery)", dense=True,
        border_color=TEXT_DARK, border_width=2, border_radius=0,
        options=[ft.dropdown.Option(i, i) for i in INFORMATION_STRUCTURES] + [ft.dropdown.Option("custom", "Tùy chỉnh (Custom)...")],
        value="classified_memo",
    )
    pl_custom_infostruct_inp = ft.TextField(
        label="Nhập Hình thức tài liệu tùy chỉnh", dense=True,
        border_color=TEXT_DARK, border_width=2, border_radius=0,
        hint_text="Ví dụ: autopsy_report, court_transcript...",
        visible=False,
    )

    pl_tone_dropdown = ft.Dropdown(
        label="Âm hưởng / Sắc thái (Tone)", dense=True,
        border_color=TEXT_DARK, border_width=2, border_radius=0,
        options=[ft.dropdown.Option(t, t) for t in TONES] + [ft.dropdown.Option("custom", "Tùy chỉnh (Custom)...")],
        value="clinical",
    )
    pl_custom_tone_inp = ft.TextField(
        label="Nhập Sắc thái (Tone) tùy chỉnh", dense=True,
        border_color=TEXT_DARK, border_width=2, border_radius=0,
        hint_text="Ví dụ: cynical, satirical, melancholic...",
        visible=False,
    )

    pl_reality_dropdown = ft.Dropdown(
        label="Quy luật thế giới (Reality Rules)", dense=True,
        border_color=TEXT_DARK, border_width=2, border_radius=0,
        options=[ft.dropdown.Option(r, r) for r in REALITY_RULES] + [ft.dropdown.Option("custom", "Tùy chỉnh (Custom)...")],
        value="speculative",
    )
    pl_custom_reality_inp = ft.TextField(
        label="Nhập Quy luật thế giới tùy chỉnh", dense=True,
        border_color=TEXT_DARK, border_width=2, border_radius=0,
        hint_text="Ví dụ: surrealism, hard_magic, dream_logic...",
        visible=False,
    )

    def _is_custom(val) -> bool:
        if not val:
            return False
        s = str(val).strip().lower()
        return s == "custom" or "custom" in s or "tùy chỉnh" in s

    def _get_dropdown_val(dd, e=None) -> str:
        if e is not None and getattr(e, "data", None) is not None:
            d_val = str(e.data).strip()
            if d_val:
                dd.value = d_val
                return d_val
        if e is not None and hasattr(e, "control") and getattr(e.control, "value", None) is not None:
            c_val = str(e.control.value).strip()
            if c_val:
                dd.value = c_val
                return c_val
        return str(getattr(dd, "value", None) or "").strip()

    def on_genre_change(e=None):
        val = _get_dropdown_val(pl_genre_dropdown, e)
        pl_custom_genre_inp.visible = _is_custom(val)
        try:
            page.update()
        except Exception:
            pass

    def on_aesthetic_change(e=None):
        val = _get_dropdown_val(pl_aesthetic_dropdown, e)
        pl_custom_aesthetic_inp.visible = _is_custom(val)
        try:
            page.update()
        except Exception:
            pass

    def on_pov_change(e=None):
        val = _get_dropdown_val(pl_pov_dropdown, e)
        pl_custom_pov_inp.visible = _is_custom(val)
        try:
            page.update()
        except Exception:
            pass

    def on_infostruct_change(e=None):
        val = _get_dropdown_val(pl_infostruct_dropdown, e)
        pl_custom_infostruct_inp.visible = _is_custom(val)
        try:
            page.update()
        except Exception:
            pass

    def on_tone_change(e=None):
        val = _get_dropdown_val(pl_tone_dropdown, e)
        pl_custom_tone_inp.visible = _is_custom(val)
        try:
            page.update()
        except Exception:
            pass

    def on_reality_change(e=None):
        val = _get_dropdown_val(pl_reality_dropdown, e)
        pl_custom_reality_inp.visible = _is_custom(val)
        try:
            page.update()
        except Exception:
            pass

    pl_genre_dropdown.on_select = on_genre_change
    pl_genre_dropdown.on_change = on_genre_change
    pl_aesthetic_dropdown.on_select = on_aesthetic_change
    pl_aesthetic_dropdown.on_change = on_aesthetic_change
    pl_pov_dropdown.on_select = on_pov_change
    pl_pov_dropdown.on_change = on_pov_change
    pl_infostruct_dropdown.on_select = on_infostruct_change
    pl_infostruct_dropdown.on_change = on_infostruct_change
    pl_tone_dropdown.on_select = on_tone_change
    pl_tone_dropdown.on_change = on_tone_change
    pl_reality_dropdown.on_select = on_reality_change
    pl_reality_dropdown.on_change = on_reality_change

    col_genre = ft.Column([pl_genre_dropdown, pl_custom_genre_inp], spacing=4, expand=True)
    col_aesthetic = ft.Column([pl_aesthetic_dropdown, pl_custom_aesthetic_inp], spacing=4, expand=True)
    col_pov = ft.Column([pl_pov_dropdown, pl_custom_pov_inp], spacing=4, expand=True)
    col_infostruct = ft.Column([pl_infostruct_dropdown, pl_custom_infostruct_inp], spacing=4, expand=True)
    col_tone = ft.Column([pl_tone_dropdown, pl_custom_tone_inp], spacing=4, expand=True)
    col_reality = ft.Column([pl_reality_dropdown, pl_custom_reality_inp], spacing=4, expand=True)

    taxonomy_details_box = ft.Container(
        content=ft.Column([
            ft.Row([col_genre, col_aesthetic], spacing=10),
            ft.Row([col_pov, col_infostruct], spacing=10),
            ft.Row([col_tone, col_reality], spacing=10),
        ], spacing=8),
        visible=False,
        bgcolor="#f9fafb",
        border=mk_border(1, "#d1d5db"),
        padding=12,
    )

    taxonomy_toggle_btn = ft.Container(
        content=ft.Row([
            ft.Text("⚙️  TÙY CHỈNH CHI TIẾT STORY TAXONOMY  ➔", size=11, weight=ft.FontWeight.W_800, color="#3730a3")
        ]),
        on_click=lambda e: toggle_taxonomy_details(),
        ink=True
    )

    def toggle_taxonomy_details():
        taxonomy_details_box.visible = not taxonomy_details_box.visible
        taxonomy_toggle_btn.content.controls[0].value = "⚙️  ẨN TÙY CHỈNH STORY TAXONOMY  ⮎" if taxonomy_details_box.visible else "⚙️  TÙY CHỈNH CHI TIẾT STORY TAXONOMY  ➔"
        try:
            page.update()
        except Exception:
            pass

    def on_preset_change(e=None):
        val = _get_dropdown_val(pl_preset_dropdown, e)
        if _is_custom(val):
            pl_custom_preset_inp.visible = True
            taxonomy_details_box.visible = True
            taxonomy_toggle_btn.content.controls[0].value = "⚙️  ẨN TÙY CHỈNH STORY TAXONOMY  ⮎"
            try:
                page.update()
            except Exception:
                pass
            return
        pl_custom_preset_inp.visible = False
        if val in TAXONOMY_PRESETS:
            cfg = TAXONOMY_PRESETS[val]
            pl_genre_dropdown.value = cfg.get("genre", "science_fiction")
            pl_custom_genre_inp.visible = False
            pl_aesthetic_dropdown.value = cfg.get("technology_aesthetic", "none")
            pl_custom_aesthetic_inp.visible = False
            pl_pov_dropdown.value = cfg.get("point_of_view", "third_person_limited")
            pl_custom_pov_inp.visible = False
            pl_infostruct_dropdown.value = cfg.get("information_structure", "investigation")
            pl_custom_infostruct_inp.visible = False
            pl_tone_dropdown.value = cfg.get("tone", "clinical")
            pl_custom_tone_inp.visible = False
            pl_reality_dropdown.value = cfg.get("reality_rules", "speculative")
            pl_custom_reality_inp.visible = False
            try:
                page.update()
            except Exception:
                pass

    pl_preset_dropdown.on_select = on_preset_change
    pl_preset_dropdown.on_change = on_preset_change

    pl_story_inp = ft.TextField(
        label="Cốt truyện gợi ý ban đầu (Seed story)",
        border_color=TEXT_DARK, border_width=2, border_radius=0,
        multiline=True, min_lines=2,
        hint_text="Ví dụ: Deep underground research bunker analyzing anomalous botanical memory frequencies...",
    )

    pl_notes_inp = ft.TextField(
        label="📝 Ghi chú cá nhân (Tùy chọn — AI sẽ dùng để cá nhân hóa bài học)",
        border_color="#4f46e5", border_width=2, border_radius=0,
        multiline=True, min_lines=3, max_lines=8,
        hint_text=(
            "Ví dụ:\n"
            "- Tôi hay nhầm lẫn giữa 'abundant' và 'plentiful', hãy giải thích rõ sự khác biệt.\n"
            "- Tôi thích ví dụ liên quan đến khoa học môi trường.\n"
            "- Hãy dùng ngôn ngữ đơn giản trong phần giải thích tiếng Việt."
        ),
        bgcolor="#f5f3ff",
    )

    model_options, default_model_key = load_all_model_options(pl_settings)

    pl_model_dropdown = ft.Dropdown(
        label="Chọn Model AI (Local & Cloud)",
        border_color=TEXT_DARK, border_width=2, border_radius=0,
        options=model_options,
        value=default_model_key,
    )

    pl_custom_provider_dropdown = ft.Dropdown(
        label="Chọn Provider cho Model tùy chỉnh",
        border_color=TEXT_DARK, border_width=2, border_radius=0,
        options=[
            ft.dropdown.Option("gemini", "Google Gemini / Google AI (Cloud)"),
            ft.dropdown.Option("openai", "OpenAI (Cloud)"),
            ft.dropdown.Option("ollama", "Ollama (Local)"),
        ],
        value="gemini",
        visible=False,
    )

    pl_custom_model_inp = ft.TextField(
        label="Tên model tùy chỉnh (Ví dụ: gemini-3.5-flash, gemini-3.7-flash, gemma-4-31b-it, deepseek-chat, llama3:70b)",
        border_color=TEXT_DARK, border_width=2, border_radius=0,
        hint_text="gemini-3.5-flash",
        value=pl_settings.get("pipeline_model_gemini", "gemini-3.5-flash"),
        visible=False,
    )

    pl_apikey_inp = ft.TextField(
        label="API Key",
        border_color=TEXT_DARK, border_width=2, border_radius=0,
        password=True, can_reveal_password=True,
        visible=False,
    )

    init_done = [False]

    def on_model_change(e=None):
        val = _get_dropdown_val(pl_model_dropdown, e)
        if val == "custom:custom" or _is_custom(val):
            pl_custom_model_inp.visible = True
            pl_custom_provider_dropdown.visible = True
            c_prov = _get_dropdown_val(pl_custom_provider_dropdown) or "gemini"
            if c_prov == "gemini":
                pl_apikey_inp.label = "Gemini API Key (bắt buộc cho Cloud)"
                pl_apikey_inp.value = pl_settings.get("gemini_api_key", "")
                pl_apikey_inp.visible = True
            elif c_prov == "openai":
                pl_apikey_inp.label = "OpenAI API Key (bắt buộc cho Cloud)"
                pl_apikey_inp.value = pl_settings.get("openai_api_key", "")
                pl_apikey_inp.visible = True
            else:
                pl_apikey_inp.visible = False
        elif ":" in val:
            pl_custom_model_inp.visible = False
            pl_custom_provider_dropdown.visible = False
            prov, _ = val.split(":", 1)
            if prov == "openai":
                pl_apikey_inp.label = "OpenAI API Key (bắt buộc cho Cloud)"
                pl_apikey_inp.value = pl_settings.get("openai_api_key", "")
                pl_apikey_inp.visible = True
            elif prov == "gemini":
                pl_apikey_inp.label = "Gemini API Key (bắt buộc cho Cloud)"
                pl_apikey_inp.value = pl_settings.get("gemini_api_key", "")
                pl_apikey_inp.visible = True
            else:
                pl_apikey_inp.visible = False
        else:
            pl_custom_model_inp.visible = False
            pl_custom_provider_dropdown.visible = False
            pl_apikey_inp.visible = False

        if init_done[0]:
            try:
                page.update()
            except Exception:
                pass

    pl_model_dropdown.on_select = on_model_change
    pl_model_dropdown.on_change = on_model_change
    pl_custom_provider_dropdown.on_select = on_model_change
    pl_custom_provider_dropdown.on_change = on_model_change
    on_model_change()

    pl_nq_inp = ft.TextField(
        label="Số câu hỏi (mặc định 10)",
        border_color=TEXT_DARK, border_width=2, border_radius=0,
        value=str(pl_settings.get("pipeline_num_questions", 10)),
        width=160,
    )
    pl_error_txt = ft.Text("", color="#991b1b", size=12, weight=ft.FontWeight.W_700)

    # ── Stepper ───────────────────────────────────────────────────────────────
    current_total_steps = [int(pl_settings.get("pipeline_num_questions", 10)) + 3]
    step_dots: list[ft.Container] = []
    stepper_row = ft.Row([], spacing=4, wrap=True)

    def _rebuild_step_dots(total: int):
        current_total_steps[0] = total
        step_dots.clear()
        for i in range(1, total + 1):
            if i <= total - 3:
                tooltip = f"Câu hỏi {i}"
            elif i == total - 2:
                tooltip = "Master Challenge"
            elif i == total - 1:
                tooltip = "Summary Story"
            else:
                tooltip = "Flashcards"
            step_dots.append(ft.Container(
                content=ft.Text(str(i), size=9, weight=ft.FontWeight.W_700, color=TEXT_GRAY),
                width=26, height=26,
                border_radius=13,
                bgcolor="#e5e7eb",
                border=mk_border(2, "#d1d5db"),
                alignment=ft.Alignment(0, 0),
                tooltip=tooltip,
            ))
        stepper_row.controls = list(step_dots)
        try:
            stepper_row.update()
        except Exception:
            pass

    _rebuild_step_dots(current_total_steps[0])

    def _update_step_dot(step: int, status: str):
        """Cập nhật màu dot: running=vàng, done=xanh, error=đỏ"""
        idx = step - 1
        if 0 <= idx < len(step_dots):
            dot = step_dots[idx]
            if status == "running":
                dot.bgcolor = CLR_YELLOW
                dot.border   = mk_border(2, "#92400e")
                dot.content.color = "#92400e"
            elif status in ("done", "step_done"):
                dot.bgcolor = CLR_GREEN
                dot.border   = mk_border(2, "#166534")
                dot.content.color = "#166534"
            elif status == "error":
                dot.bgcolor = CLR_RED
                dot.border   = mk_border(2, "#991b1b")
                dot.content.color = "#991b1b"
            try:
                dot.update()
            except Exception:
                pass

    def _reset_step_dots():
        for i, dot in enumerate(step_dots):
            dot.bgcolor     = "#e5e7eb"
            dot.border      = mk_border(2, "#d1d5db")
            dot.content.color = TEXT_GRAY
            try:
                dot.update()
            except Exception:
                pass

    # ── Progress bar ──────────────────────────────────────────────────────────
    pl_progress_bar = ft.ProgressBar(
        value=0, width=None, height=8,
        color=TEXT_DARK, bgcolor="#e5e7eb",
    )
    pl_step_label = ft.Text("Nhấn 'Bắt đầu' để tự động tạo bài học.", size=12, color=TEXT_GRAY)

    # ── Log box ───────────────────────────────────────────────────────────────
    pl_log_col = ft.Column(spacing=3, scroll=ft.ScrollMode.AUTO, expand=True)

    LOGS_DIR_PL = Path(__file__).parent / "logs"

    def _add_log(msg: str, level: str = "INFO"):
        now_str = datetime.now().strftime("%H:%M:%S")
        color_map = {
            "INFO": "#60a5fa", "SUCCESS": "#4ade80",
            "WARN": "#facc15", "ERROR": "#f87171",
        }
        tag_color = color_map.get(level, "#ffffff")
        row = ft.Row([
            ft.Text(f"[{now_str}]",   size=10, color="#9ca3af", font_family="monospace"),
            ft.Text(f"[{level}]",     size=10, color=tag_color, weight=ft.FontWeight.W_700, font_family="monospace"),
            ft.Text(msg,              size=11, color="#f3f4f6",  font_family="monospace", expand=True, selectable=True),
        ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.START)
        pl_log_col.controls.append(row)
        if len(pl_log_col.controls) > 200:
            pl_log_col.controls.pop(0)
        try:
            pl_log_col.update()
        except Exception:
            pass
        # Gửi tới logger tập trung
        lvl_u = level.upper()
        pl_logger = get_logger("pipeline")
        if lvl_u in ("SUCCESS", "INFO"):
            pl_logger.info("[Pipeline] %s", msg)
        elif lvl_u == "WARN":
            pl_logger.warning("[Pipeline] %s", msg)
        elif lvl_u == "ERROR":
            pl_logger.error("[Pipeline] %s", msg)
        else:
            pl_logger.debug("[Pipeline] %s", msg)

        # Ghi file log pipeline riêng
        try:
            LOGS_DIR_PL.mkdir(parents=True, exist_ok=True)
            now_dt = datetime.now()
            with open(LOGS_DIR_PL / f"pipeline_{now_dt.strftime('%Y-%m-%d')}.txt", "a", encoding="utf-8") as f:
                f.write(f"[{now_dt.strftime('%Y-%m-%d %H:%M:%S')}] [{level}] {msg}\n")
        except Exception:
            pass

    pl_log_box = ft.Container(
        content=pl_log_col,
        bgcolor="#111827",
        border=mk_border(2, TEXT_DARK),
        padding=12,
        height=260,
        expand=True,
    )

    # ── Result preview area ───────────────────────────────────────────────────
    pl_result_area = ft.Container(visible=False)

    # ── Buttons ───────────────────────────────────────────────────────────────
    pl_start_btn  = nb_button("▶ Bắt đầu tạo bài học", bgcolor=TEXT_DARK, color=TEXT_WHITE)
    pl_retry_btn = nb_button("Thử lại bước bị lỗi", bgcolor=CLR_YELLOW, color=TEXT_DARK, width=220)
    pl_restart_btn = nb_button("Làm lại từ đầu", bgcolor=BG_WHITE, color=TEXT_DARK, width=180)
    pl_retry_btn.visible = pl_restart_btn.visible = False
    pl_resume_note = ft.Text("", size=12, color=TEXT_GRAY, visible=False)
    pl_failure_detail = ft.Text("", size=12, color="#991b1b", visible=False)
    pl_cancel_btn = nb_button("✕ Hủy", bgcolor=CLR_RED, color=TEXT_DARK)
    pl_cancel_btn.visible = False
    pl_save_btn   = nb_button("💾 Lưu bài học vào DB", bgcolor=CLR_GREEN, color=TEXT_DARK)
    pl_save_btn.visible = False

    # ── on_progress callback ──────────────────────────────────────────────────
    def _on_progress(info: dict):
        step   = info.get("step", 0)
        total  = info.get("total", current_total_steps[0])
        label  = info.get("label", "")
        status = info.get("status", "running")

        if total > 0 and step > 0:
            fraction = 1 if status in ("done", "step_done") else info.get("sub_progress", 0)
            pct = min(((step - 1) + fraction) / total, 1.0)
            pl_progress_bar.value = pct
            try:
                pl_progress_bar.update()
            except Exception:
                pass

        pl_step_label.value = label
        try:
            pl_step_label.update()
        except Exception:
            pass

        if step > 0:
            _update_step_dot(step, status)

        level = "SUCCESS" if status in ("done", "step_done") else ("ERROR" if status == "error" else "INFO")
        _add_log(label, level)

    # ── Start pipeline ────────────────────────────────────────────────────────
    def connection_options(num_q):
        # Phân tích Model đã chọn từ Dropdown
        selected_val = pl_model_dropdown.value or "ollama:qwen3:4b"
        if selected_val == "custom:custom":
            model = (pl_custom_model_inp.value or "").strip()
            if not model:
                pl_error_txt.value = "Vui lòng nhập tên model tùy chỉnh."
                page.update()
                return
            provider = pl_custom_provider_dropdown.value or "gemini"
        else:
            provider, model = selected_val.split(":", 1)

        s = load_settings()
        api_key = ""
        if provider in ("openai", "gemini"):
            api_key = (pl_apikey_inp.value or "").strip() or s.get(f"{provider}_api_key", "")
            if not api_key:
                pl_error_txt.value = f"Model cloud '{model}' yêu cầu {provider.upper()} API Key."
                page.update()
                return
            s[f"{provider}_api_key"] = api_key

        s["ai_provider"] = provider
        s[f"pipeline_model_{provider}"] = model
        s["pipeline_num_questions"] = num_q
        save_settings(s)

        timeout = s.get("pipeline_timeout", 120)

        return dict(provider=provider, model=model, api_key=api_key, timeout=timeout)

    def do_start(e=None):
        if pipeline_state["running"]:
            return
        pl_error_txt.value = ""

        vocab_raw = (pl_vocab_inp.value or "").strip()
        if not vocab_raw:
            pl_error_txt.value = "Vui lòng nhập danh sách từ vựng."
            page.update()
            return

        try:
            num_q = int((pl_nq_inp.value or "").strip())
            if not (1 <= num_q <= 20):
                raise ValueError
        except ValueError:
            pl_error_txt.value = "Số câu hỏi phải là số nguyên từ 1 đến 20."
            page.update()
            return

        connection = connection_options(num_q)
        if connection is None:
            return

        vocab_list = [{"word": w.strip()} for w in vocab_raw.split(",") if w.strip()]
        seed_story = (pl_story_inp.value or "").strip() or "Academic English reading lesson."

        # Trích xuất giá trị taxonomy (ưu tiên custom text nếu chọn custom)
        def _get_val(dropdown, custom_inp, default_val):
            val = dropdown.value or default_val
            if _is_custom(val):
                c_val = (custom_inp.value or "").strip()
                return c_val if c_val else default_val
            return val

        resolved_genre = _get_val(pl_genre_dropdown, pl_custom_genre_inp, "science_fiction")
        resolved_aesthetic = _get_val(pl_aesthetic_dropdown, pl_custom_aesthetic_inp, "none")
        resolved_pov = _get_val(pl_pov_dropdown, pl_custom_pov_inp, "third_person_limited")
        resolved_infostruct = _get_val(pl_infostruct_dropdown, pl_custom_infostruct_inp, "investigation")
        resolved_tone = _get_val(pl_tone_dropdown, pl_custom_tone_inp, "clinical")
        resolved_reality = _get_val(pl_reality_dropdown, pl_custom_reality_inp, "speculative")

        taxonomy_settings = {
            "genre": resolved_genre,
            "technology_aesthetic": resolved_aesthetic,
            "point_of_view": resolved_pov,
            "information_structure": resolved_infostruct,
            "tone": resolved_tone,
            "reality_rules": resolved_reality,
            "difficulty": "hard",
            "narrative_density": "high",
        }
        custom_preset_name = (pl_custom_preset_inp.value or "").strip()
        if _is_custom(pl_preset_dropdown.value) and custom_preset_name:
            taxonomy_settings["story_style"] = custom_preset_name

        if not vocab_list:
            pl_error_txt.value = "Vui lòng nhập ít nhất một từ vựng."
            page.update()
            return
        user_notes = (pl_notes_inp.value or "").strip()
        request = dict(vocab_list=vocab_list, seed_story=seed_story, num_questions=num_q,
                       taxonomy_settings=taxonomy_settings, user_notes=user_notes)
        preset_display = custom_preset_name if (_is_custom(pl_preset_dropdown.value) and custom_preset_name) else pl_preset_dropdown.value
        title = (pl_story_inp.value or "").strip()[:50] or f"Bài học {preset_display}"
        launch(request, connection, title=title)

    def launch(request, connection, resume_from=None, title=""):
        with run_lock:
            if pipeline_state["running"]:
                return
            # Copy the content and completed work before a new background run can start.
            request = deepcopy(request)
            resume_from = deepcopy(resume_from)
            pipeline_state["request"] = deepcopy(request)
            pipeline_state["checkpoint"] = resume_from
            pipeline_state["title"] = title
            pipeline_state["result"] = None
            pipeline_state["running"] = True
            stop_event = threading.Event()
            pipeline_state["stop_event"] = stop_event
        total_steps = request["num_questions"] + 3
        _rebuild_step_dots(total_steps)
        _reset_step_dots()
        if resume_from is None:
            pl_log_col.controls.clear()
        pl_result_area.visible = False
        pl_save_btn.visible = False
        pl_retry_btn.visible = pl_restart_btn.visible = False
        pl_resume_note.visible = False
        pl_failure_detail.visible = False
        pl_progress_bar.value = 0
        pl_step_label.value = "Đang tiếp tục từ phần bị lỗi..." if resume_from else "Đang khởi động..."
        pl_step_label.color = TEXT_GRAY
        pl_start_btn.visible = False
        pl_cancel_btn.visible = True
        pl_error_txt.value = ""
        if is_generating:
            is_generating["status"] = True
        if on_lock_nav:
            on_lock_nav(True)
        page.update()
        _add_log("Thử lại phần chưa hoàn thành." if resume_from else "Bắt đầu lượt tạo bài học mới.", "INFO")
        _add_log(f"Provider: {connection['provider'].upper()} | Model: {connection['model']}", "INFO")

        def active():
            return pipeline_state["stop_event"] is stop_event and not stop_event.is_set()

        def remember(checkpoint):
            with run_lock:
                if active():
                    pipeline_state["checkpoint"] = deepcopy(checkpoint)

        def report(info):
            with run_lock:
                if active():
                    _on_progress(info)

        def worker():
            try:
                from lesson_pipeline import run_lesson_pipeline
                result = run_lesson_pipeline(
                    **request, **connection, resume_from=resume_from,
                    on_checkpoint=remember, stop_event=stop_event,
                    on_progress=report,
                )
            except Exception as exc:
                logger.exception("Lỗi không mong đợi trong pipeline")
                result = {"success": False, "error": str(exc)}
            with run_lock:
                if not active():
                    return
                pipeline_state["result"] = result
                pipeline_state["running"] = False
                if "checkpoint" in result:
                    pipeline_state["checkpoint"] = result["checkpoint"]
                pl_cancel_btn.visible = False
                if is_generating:
                    is_generating["status"] = False
                if on_lock_nav:
                    on_lock_nav(False)
                success = result["success"]
                pl_start_btn.visible = success
                if success:
                    pl_step_label.value = f"✓ Hoàn tất! {len(result['questions'])} câu hỏi | {len(result['vocab_with_examples'])} flashcard"
                    pl_save_btn.visible = True
                    _add_log("Tạo bài học bằng AI thành công!", "SUCCESS")
                else:
                    failed_label = result.get("failed_label") or "bước đang thực hiện"
                    pl_step_label.value = f"Lỗi tại {failed_label}"
                    pl_failure_detail.value = result.get("error", "Không thể hoàn thành bước này.")
                    pl_failure_detail.visible = True
                    pl_retry_btn.visible = pl_restart_btn.visible = True
                    pl_retry_btn.disabled = pipeline_state["checkpoint"] is None
                    pl_resume_note.value = (
                        "Thử lại sẽ giữ nội dung và các phần đã tạo. Có thể đổi model/API key trước khi thử lại. "
                        "Muốn đổi từ vựng hoặc cốt truyện, hãy chọn Làm lại từ đầu. "
                        "Tiến trình được giữ khi bạn ở màn hình này."
                        if pipeline_state["checkpoint"] is not None else
                        "Không có tiến trình để tiếp tục. Hãy chọn Làm lại từ đầu."
                    )
                    pl_resume_note.visible = True
                    _add_log(f"{pl_step_label.value}: {result.get('error', '?')}", "ERROR")
                pl_step_label.color = "#166534" if success else "#991b1b"
                try:
                    page.update()
                except RuntimeError:
                    pass

        threading.Thread(target=worker, daemon=True).start()

    def do_retry(e=None):
        if pipeline_state["running"] or pipeline_state["checkpoint"] is None:
            return
        request = pipeline_state["request"]
        connection = connection_options(request["num_questions"])
        if connection is not None:
            launch(request, connection, resume_from=pipeline_state["checkpoint"], title=pipeline_state["title"])

    def do_cancel(e=None):
        with run_lock:
            stop_event = pipeline_state.get("stop_event")
            if stop_event:
                stop_event.set()
            pipeline_state["running"] = False
            pipeline_state["result"] = None
            pl_save_btn.visible = False
            pl_step_label.value = "Đã hủy. Các phần hoàn thành vẫn được giữ ở màn hình này."
            pl_step_label.color = TEXT_GRAY
            has_checkpoint = pipeline_state["checkpoint"] is not None
            pl_start_btn.visible = not has_checkpoint
            pl_retry_btn.visible = pl_restart_btn.visible = has_checkpoint
            pl_retry_btn.disabled = False
            pl_cancel_btn.visible = False
            if is_generating:
                is_generating["status"] = False
            if on_lock_nav:
                on_lock_nav(False)
            page.update()
            _add_log("Người dùng yêu cầu hủy.", "WARN")

    def do_save(e=None):
        result = pipeline_state.get("result")
        if not result or not result.get("success"):
            return
        try:
            from ingestion import load_lesson_from_dict
            lesson_dict = {
                "title": pipeline_state["title"],
                "story_context": result["summary_story"],
                "story_state": result.get("story_state", {}),
                "vocab": result["vocab_with_examples"],
                "questions": result["questions"],
                "flashcards": result["vocab_with_examples"],
            }
            db_res = load_lesson_from_dict(lesson_dict)
            if db_res["success"]:
                page.show_dialog(ft.SnackBar(ft.Text("✓ Lưu bài học thành công!"), bgcolor="#166534"))
                if on_lock_nav:
                    on_lock_nav(False)
                on_success()
            else:
                err = "\n".join(db_res["errors"])
                pl_error_txt.value = f"Lỗi lưu DB: {err}"
            page.update()
        except Exception as ex:
            pl_error_txt.value = f"Lỗi lưu DB: {ex}"
            page.update()

    pl_start_btn.on_click  = do_start
    pl_retry_btn.on_click = do_retry
    pl_restart_btn.on_click = do_start
    pl_cancel_btn.on_click = do_cancel
    pl_save_btn.on_click   = do_save

    # ── Layout ────────────────────────────────────────────────────────────────
    form_col = ft.Column([
        ft.Container(height=10),
        pl_vocab_inp,
        pl_preset_dropdown,
        pl_custom_preset_inp,
        taxonomy_toggle_btn,
        taxonomy_details_box,
        pl_story_inp,
        pl_notes_inp,
        pl_model_dropdown,
        pl_custom_provider_dropdown,
        pl_custom_model_inp,
        pl_apikey_inp,
        ft.Row([pl_nq_inp], spacing=10),
        pl_error_txt,
        ft.Container(height=8),
        ft.Row([pl_start_btn, pl_cancel_btn, pl_save_btn], spacing=8, wrap=True),
    ], spacing=8, expand=True)

    def open_logs_dir(e=None):
        import sys, subprocess
        logs_path = Path(__file__).parent / "logs"
        logs_path.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "win32":
                os.startfile(str(logs_path))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(logs_path)])
            else:
                subprocess.Popen(["xdg-open", str(logs_path)])
        except Exception:
            pass

    monitor_col = ft.Column([
        ft.Container(height=10),
        # Stepper
        nb_card(
            ft.Column([
                ft.Row([
                    ft.Text("TIẾN TRÌNH", size=9, weight=ft.FontWeight.W_800,
                            color=TEXT_GRAY, style=ft.TextStyle(letter_spacing=1.5)),
                    ft.Container(expand=True),
                    pl_step_label,
                ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Container(height=8),
                stepper_row,
                ft.Container(height=8),
                pl_progress_bar,
                pl_failure_detail,
                ft.Row([pl_retry_btn, pl_restart_btn], spacing=10, wrap=True),
                pl_resume_note,
            ], spacing=8),
            shadow_size="sm", padding=16,
        ),
        ft.Container(height=12),
        # Log box
        nb_card(
            ft.Column([
                ft.Row([
                    ft.Text("📟 PIPELINE LIVE LOGS", size=9, weight=ft.FontWeight.W_800,
                            color=TEXT_GRAY, style=ft.TextStyle(letter_spacing=1.5)),
                    ft.Container(expand=True),
                    ft.Container(
                        content=ft.Row([
                            ft.Text("📂", size=10),
                            ft.Text("MỞ FOLDER LOGS", size=9, weight=ft.FontWeight.W_800, color=TEXT_DARK),
                        ], spacing=4),
                        bgcolor=CLR_YELLOW,
                        border=mk_border(1, TEXT_DARK),
                        padding=pad(h=6, v=3),
                        on_click=open_logs_dir,
                        ink=True,
                        tooltip="Mở thư mục chứa file log chi tiết và câu trả lời thô của AI (raw responses)",
                    ),
                ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Container(height=6),
                pl_log_box,
            ], spacing=0),
            shadow_size="sm", padding=12,
        ),
    ], spacing=0, expand=True)

    init_done[0] = True

    return ft.Column([
        ft.Row([
            form_col,
            ft.VerticalDivider(width=1, color="#d1d5db"),
            monitor_col,
        ], spacing=20, expand=True, vertical_alignment=ft.CrossAxisAlignment.START),
    ], spacing=0, expand=True, scroll=ft.ScrollMode.AUTO)


def build_settings_screen(page: ft.Page) -> ft.Control:
    settings = load_settings()
    current_model = settings.get("whisper_model", "base")
    current_device = settings.get("device", "cpu")

    model_containers = {}
    device_containers = {}

    def select_model(model_name: str):
        nonlocal current_model
        current_model = model_name
        settings["whisper_model"] = model_name
        save_settings(settings)

        # Cập nhật UI
        for m_name, container in model_containers.items():
            active = m_name == model_name
            container.border = mk_border(2, TEXT_DARK if active else "#d1d5db")
            container.content.controls[0].value = "●" if active else "○"
            container.content.controls[0].color = TEXT_DARK if active else TEXT_GRAY
            container.update()

        page.show_dialog(ft.SnackBar(ft.Text(f"✓ Đã lưu Whisper model: {model_name}"), bgcolor=TEXT_DARK))
        page.update()

    def select_device(device_name: str):
        nonlocal current_device
        current_device = device_name
        settings["device"] = device_name
        save_settings(settings)

        # Cập nhật UI
        for d_name, container in device_containers.items():
            active = d_name == device_name
            container.border = mk_border(2, TEXT_DARK if active else "#d1d5db")
            container.content.controls[0].value = "●" if active else "○"
            container.content.controls[0].color = TEXT_DARK if active else TEXT_GRAY
            container.update()

        page.show_dialog(ft.SnackBar(ft.Text(f"✓ Đã chọn thiết bị: {device_name.upper()}"), bgcolor=TEXT_DARK))
        page.update()

    def model_row(name: str, desc: str) -> ft.Container:
        active = name == current_model
        c = ft.Container(
            content=ft.Row([
                ft.Text("●" if active else "○", size=16, color=TEXT_DARK if active else TEXT_GRAY, weight=ft.FontWeight.W_900),
                ft.Column([
                    ft.Text(name, size=13, weight=ft.FontWeight.W_700, color=TEXT_DARK),
                    ft.Text(desc, size=12, color=TEXT_GRAY),
                ], spacing=2),
            ], spacing=12),
            bgcolor=BG_WHITE,
            border=mk_border(2, TEXT_DARK if active else "#d1d5db"),
            padding=pad(h=16, v=10),
            on_click=lambda e, name=name: select_model(name),
            ink=True
        )
        model_containers[name] = c
        return c

    def device_row(name: str, desc: str) -> ft.Container:
        active = name.lower() == current_device.lower()
        c = ft.Container(
            content=ft.Row([
                ft.Text("●" if active else "○", size=16, color=TEXT_DARK if active else TEXT_GRAY, weight=ft.FontWeight.W_900),
                ft.Column([
                    ft.Text(name, size=13, weight=ft.FontWeight.W_700, color=TEXT_DARK),
                    ft.Text(desc, size=12, color=TEXT_GRAY),
                ], spacing=2),
            ], spacing=12),
            bgcolor=BG_WHITE,
            border=mk_border(2, TEXT_DARK if active else "#d1d5db"),
            padding=pad(h=16, v=10),
            on_click=lambda e, name=name: select_device(name.lower()),
            ink=True
        )
        device_containers[name.lower()] = c
        return c

    whisper_card = nb_card(
        ft.Column([
            ft.Text("FASTER-WHISPER MODEL", size=12,
                    weight=ft.FontWeight.W_700, color=TEXT_GRAY,
                    style=ft.TextStyle(letter_spacing=1.5)),
            ft.Container(height=12),
            model_row("base",           "Nhanh nhất — độ chính xác thấp"),
            ft.Container(height=4),
            model_row("small",          "Cân bằng — phù hợp CPU"),
            ft.Container(height=4),
            model_row("medium",         "Tốt — yêu cầu RAM cao"),
            ft.Container(height=4),
            model_row("large-v3",       "Tốt nhất — cần GPU mạnh"),
            ft.Container(height=4),
            model_row("turbo",          "Nhanh + tốt — khuyên dùng"),
            ft.Container(height=4),
            model_row("large-v3-turbo", "Turbo + large — cần VRAM cao"),
        ], spacing=0),
        shadow_size="sm",
    )

    device_card = nb_card(
        ft.Column([
            ft.Text("THIẾT BỊ", size=12,
                    weight=ft.FontWeight.W_700, color=TEXT_GRAY,
                    style=ft.TextStyle(letter_spacing=1.5)),
            ft.Container(height=12),
            device_row("CPU",  "Chạy trên CPU — chậm hơn nhưng không cần GPU"),
            ft.Container(height=4),
            device_row("CUDA", "NVIDIA GPU — nhanh hơn nhiều (Yêu cầu CUDA toolkit)"),
            ft.Container(height=10),
            ft.Text("Áp dụng sau khi khởi động lại ứng dụng.",
                    size=12, color=TEXT_GRAY, italic=True),
        ], spacing=0),
        shadow_size="sm",
    )

    # ── TTS Voice Card (Edge-TTS) ──────────────────────────────────────────────
    current_tts_voice = settings.get("tts_voice", "en-GB-SoniaNeural")
    current_tts_rate = settings.get("tts_rate", "+0%")
    tts_voice_containers = {}
    tts_rate_containers = {}

    def select_tts_voice(vname: str):
        nonlocal current_tts_voice
        current_tts_voice = vname
        settings["tts_voice"] = vname
        save_settings(settings)
        for v, c in tts_voice_containers.items():
            active = (v == vname)
            c.border = mk_border(2, TEXT_DARK if active else "#d1d5db")
            c.content.controls[0].value = "●" if active else "○"
            c.content.controls[0].color = TEXT_DARK if active else TEXT_GRAY
            c.update()
        page.show_dialog(ft.SnackBar(ft.Text(f"✓ Đã chọn giọng đọc: {vname}"), bgcolor=TEXT_DARK))
        page.update()

    def tts_voice_row(vname: str, label: str, desc: str) -> ft.Container:
        active = (vname == current_tts_voice)
        c = ft.Container(
            content=ft.Row([
                ft.Text("●" if active else "○", size=16,
                        color=TEXT_DARK if active else TEXT_GRAY, weight=ft.FontWeight.W_900),
                ft.Column([
                    ft.Text(label, size=13, weight=ft.FontWeight.W_700, color=TEXT_DARK),
                    ft.Text(desc, size=12, color=TEXT_GRAY),
                ], spacing=2),
            ], spacing=12),
            bgcolor=BG_WHITE,
            border=mk_border(2, TEXT_DARK if active else "#d1d5db"),
            padding=pad(h=16, v=10),
            on_click=lambda e, v=vname: select_tts_voice(v),
            ink=True,
        )
        tts_voice_containers[vname] = c
        return c

    def select_tts_rate(rval: str):
        nonlocal current_tts_rate
        current_tts_rate = rval
        settings["tts_rate"] = rval
        save_settings(settings)
        for r, c in tts_rate_containers.items():
            active = (r == rval)
            c.border = mk_border(2, TEXT_DARK if active else "#d1d5db")
            c.content.controls[0].value = "●" if active else "○"
            c.content.controls[0].color = TEXT_DARK if active else TEXT_GRAY
            c.update()
        page.show_dialog(ft.SnackBar(ft.Text(f"✓ Tốc độ phát âm: {rval}"), bgcolor=TEXT_DARK))
        page.update()

    def tts_rate_row(rval: str, label: str) -> ft.Container:
        active = (rval == current_tts_rate)
        c = ft.Container(
            content=ft.Row([
                ft.Text("●" if active else "○", size=14,
                        color=TEXT_DARK if active else TEXT_GRAY, weight=ft.FontWeight.W_900),
                ft.Text(label, size=13, weight=ft.FontWeight.W_700, color=TEXT_DARK),
            ], spacing=8),
            bgcolor=BG_WHITE,
            border=mk_border(2, TEXT_DARK if active else "#d1d5db"),
            padding=pad(h=12, v=8),
            on_click=lambda e, r=rval: select_tts_rate(r),
            ink=True,
        )
        tts_rate_containers[rval] = c
        return c

    def test_speak_click(e=None):
        speak_text(page, "Hello! This is British English Neural Text to Speech for Vocab 1337.")

    tts_card = nb_card(
        ft.Column([
            ft.Row([
                ft.Text("GIỌNG ĐỌC PHÁT ÂM (EDGE-TTS NEURAL)", size=12,
                        weight=ft.FontWeight.W_700, color=TEXT_GRAY,
                        style=ft.TextStyle(letter_spacing=1.5)),
                nb_button("🔊 Nghe thử giọng", on_click=test_speak_click, bgcolor=CLR_GREEN, color=TEXT_DARK),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Container(height=12),
            ft.Text("CHUẨN ANH - ANH (BRITISH ACCENT) — KHUYÊN DÙNG HỌC TỪ VỰNG", size=11, weight=ft.FontWeight.W_800,
                    color="#4338ca", style=ft.TextStyle(letter_spacing=1.2)),
            ft.Container(height=6),
            tts_voice_row("en-GB-SoniaNeural", "Sonia (Nữ - Anh) [Mặc định]", "Chuẩn British RP thanh lịch — Khuyên dùng theo chuẩn từ điển Cambridge"),
            ft.Container(height=4),
            tts_voice_row("en-GB-LibbyNeural", "Libby (Nữ - Anh)", "Chuẩn giọng Anh - Anh tự nhiên, phát âm cực rõ ràng & truyền cảm"),
            ft.Container(height=4),
            tts_voice_row("en-GB-RyanNeural", "Ryan (Nam - Anh)", "Chuẩn giọng nam Anh - Anh (British RP) trầm ấm, bản ngữ"),
            ft.Container(height=4),
            tts_voice_row("en-GB-ThomasNeural", "Thomas (Nam - Anh)", "Chuẩn giọng nam Anh - Anh dứt khoát, hiện đại"),
            ft.Container(height=4),
            tts_voice_row("en-GB-MaisieNeural", "Maisie (Nữ - Anh)", "Chuẩn giọng nữ Anh - Anh trẻ trung & tự nhiên"),
            ft.Container(height=12),
            ft.Text("GIỌNG KHÁC (ANH - MỸ)", size=11, weight=ft.FontWeight.W_700,
                    color=TEXT_GRAY, style=ft.TextStyle(letter_spacing=1.2)),
            ft.Container(height=6),
            tts_voice_row("en-US-JennyNeural", "Jenny (Nữ - Mỹ)", "Tự nhiên, phát âm rõ chữ — Giọng Mỹ chuẩn"),
            ft.Container(height=4),
            tts_voice_row("en-US-GuyNeural", "Guy (Nam - Mỹ)", "Trầm ấm, truyền cảm — Giọng nam Mỹ"),
            ft.Container(height=4),
            tts_voice_row("en-US-AriaNeural", "Aria (Nữ - Mỹ)", "Biểu cảm phong phú, sống động"),
            ft.Container(height=14),
            ft.Text("TỐC ĐỘ PHÁT ÂM", size=11, weight=ft.FontWeight.W_700,
                    color=TEXT_GRAY, style=ft.TextStyle(letter_spacing=1.5)),
            ft.Container(height=8),
            ft.Row([
                tts_rate_row("-15%", "Chậm (0.85x)"),
                tts_rate_row("+0%", "Chuẩn (1.0x)"),
                tts_rate_row("+15%", "Nhanh (1.15x)"),
            ], spacing=10),
            ft.Container(height=10),
            ft.Text("Tích hợp Smart Caching: Tải 1 lần lưu cục bộ vĩnh viễn, phát lại ngay lập tức 0ms không cần mạng.",
                    size=12, color=TEXT_GRAY, italic=True),
        ], spacing=0),
        shadow_size="sm",
    )

    # ── AI Provider Card ───────────────────────────────────────────────────────
    current_provider = settings.get("ai_provider", "ollama")
    provider_containers = {}

    pl_model_ollama_f = ft.TextField(
        label="Ollama Model", dense=True,
        border_color=TEXT_DARK, border_width=2, border_radius=0,
        value=settings.get("pipeline_model_ollama", "qwen3:4b"),
    )
    pl_model_openai_f = ft.TextField(
        label="OpenAI Model", dense=True,
        border_color=TEXT_DARK, border_width=2, border_radius=0,
        value=settings.get("pipeline_model_openai", "gpt-4o-mini"),
    )
    pl_model_gemini_f = ft.TextField(
        label="Gemini Model", dense=True,
        border_color=TEXT_DARK, border_width=2, border_radius=0,
        value=settings.get("pipeline_model_gemini", "gemini-3.5-flash"),
    )
    openai_key_f = ft.TextField(
        label="OpenAI API Key", dense=True, password=True, can_reveal_password=True,
        border_color=TEXT_DARK, border_width=2, border_radius=0,
        value=settings.get("openai_api_key", ""),
    )
    gemini_key_f = ft.TextField(
        label="Gemini API Key", dense=True, password=True, can_reveal_password=True,
        border_color=TEXT_DARK, border_width=2, border_radius=0,
        value=settings.get("gemini_api_key", ""),
    )
    pl_timeout_f = ft.TextField(
        label="Timeout mỗi bước (giây)", dense=True,
        border_color=TEXT_DARK, border_width=2, border_radius=0,
        value=str(settings.get("pipeline_timeout", 120)),
        width=200,
    )

    def select_provider(pname: str):
        nonlocal current_provider
        current_provider = pname
        settings["ai_provider"] = pname
        save_settings(settings)
        for p, c in provider_containers.items():
            active = p == pname
            c.border = mk_border(2, TEXT_DARK if active else "#d1d5db")
            c.content.controls[0].value = "●" if active else "○"
            c.content.controls[0].color = TEXT_DARK if active else TEXT_GRAY
            c.update()
        page.show_dialog(ft.SnackBar(ft.Text(f"✓ AI Provider: {pname.upper()}"), bgcolor=TEXT_DARK))
        page.update()

    def provider_row(pname: str, label: str, desc: str) -> ft.Container:
        active = pname == current_provider
        c = ft.Container(
            content=ft.Row([
                ft.Text("●" if active else "○", size=16,
                        color=TEXT_DARK if active else TEXT_GRAY, weight=ft.FontWeight.W_900),
                ft.Column([
                    ft.Text(label, size=13, weight=ft.FontWeight.W_700, color=TEXT_DARK),
                    ft.Text(desc, size=12, color=TEXT_GRAY),
                ], spacing=2),
            ], spacing=12),
            bgcolor=BG_WHITE,
            border=mk_border(2, TEXT_DARK if active else "#d1d5db"),
            padding=pad(h=16, v=10),
            on_click=lambda e, p=pname: select_provider(p),
            ink=True,
        )
        provider_containers[pname] = c
        return c

    def save_pipeline_settings(e=None):
        settings["pipeline_model_ollama"] = (pl_model_ollama_f.value or "").strip()
        settings["pipeline_model_openai"] = (pl_model_openai_f.value or "").strip()
        settings["pipeline_model_gemini"] = (pl_model_gemini_f.value or "").strip()
        settings["openai_api_key"]          = (openai_key_f.value or "").strip()
        settings["gemini_api_key"]          = (gemini_key_f.value or "").strip()
        try:
            settings["pipeline_timeout"] = int((pl_timeout_f.value or "").strip())
        except ValueError:
            settings["pipeline_timeout"] = 120
        save_settings(settings)
        page.show_dialog(ft.SnackBar(ft.Text("✓ Đã lưu cài đặt Pipeline!"), bgcolor="#166534"))
        page.update()

    ai_provider_card = nb_card(
        ft.Column([
            ft.Text("AI PROVIDER — PIPELINE BUILDER", size=12,
                    weight=ft.FontWeight.W_700, color=TEXT_GRAY,
                    style=ft.TextStyle(letter_spacing=1.5)),
            ft.Container(height=12),
            provider_row("ollama", "Ollama (Cục bộ)",
                         "Chạy model AI trên máy tính của bạn — miễn phí, riêng tư."),
            ft.Container(height=4),
            provider_row("openai", "OpenAI API",
                         "Gọi GPT-4o-mini / GPT-4o — nhanh, cần API Key."),
            ft.Container(height=4),
            provider_row("gemini", "Google Gemini API",
                         "Gọi Gemini 2.0 Flash / Pro — nhanh, cần API Key."),
            ft.Container(height=16),
            ft.Text("CẤU HÌNH MODEL & API KEY", size=10, weight=ft.FontWeight.W_700,
                    color=TEXT_GRAY, style=ft.TextStyle(letter_spacing=1.5)),
            ft.Container(height=8),
            pl_model_ollama_f,
            ft.Container(height=6),
            pl_model_openai_f,
            openai_key_f,
            ft.Container(height=6),
            pl_model_gemini_f,
            gemini_key_f,
            ft.Container(height=8),
            pl_timeout_f,
            ft.Container(height=12),
            nb_button("💾 Lưu cài đặt Pipeline", on_click=save_pipeline_settings,
                      bgcolor=TEXT_DARK, color=TEXT_WHITE),
        ], spacing=4),
        shadow_size="sm",
    )

    # ── LOGGING & DIAGNOSTICS CARD ─────────────────────────────────────────────
    current_log_lvl = settings.get("log_level", "INFO").upper()
    log_level_containers = {}

    def select_log_level(lvl_name: str):
        nonlocal current_log_lvl
        current_log_lvl = lvl_name
        settings["log_level"] = lvl_name
        save_settings(settings)
        set_log_level(lvl_name)

        for l_name, container in log_level_containers.items():
            active = l_name == lvl_name
            container.border = mk_border(2, TEXT_DARK if active else "#d1d5db")
            container.content.controls[0].value = "●" if active else "○"
            container.content.controls[0].color = TEXT_DARK if active else TEXT_GRAY
            container.update()

        page.show_dialog(ft.SnackBar(ft.Text(f"✓ Đã đặt mức ghi log: {lvl_name}"), bgcolor=TEXT_DARK))
        page.update()

    def log_level_row(lvl_name: str, desc: str) -> ft.Container:
        active = lvl_name == current_log_lvl
        c = ft.Container(
            content=ft.Row([
                ft.Text("●" if active else "○", size=16, color=TEXT_DARK if active else TEXT_GRAY, weight=ft.FontWeight.W_900),
                ft.Column([
                    ft.Text(lvl_name, size=13, weight=ft.FontWeight.W_700, color=TEXT_DARK),
                    ft.Text(desc, size=12, color=TEXT_GRAY),
                ], spacing=2),
            ], spacing=12),
            bgcolor=BG_WHITE,
            border=mk_border(2, TEXT_DARK if active else "#d1d5db"),
            padding=pad(h=16, v=10),
            on_click=lambda e, lvl=lvl_name: select_log_level(lvl),
            ink=True
        )
        log_level_containers[lvl_name] = c
        return c

    def open_logs_folder(e=None):
        try:
            logs_dir = get_logs_dir()
            if os.name == "nt":
                os.startfile(logs_dir)
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(logs_dir)])
        except Exception as ex:
            logger.error(f"Lỗi khi mở thư mục logs: {ex}")
            page.show_dialog(ft.SnackBar(ft.Text(f"Không thể mở thư mục: {ex}"), bgcolor="#991b1b"))
            page.update()

    def generate_test_logs(e=None):
        test_logger = get_logger("diagnostic")
        test_logger.debug("Kiểm tra log mức DEBUG: Các tham số nội bộ hoạt động bình thường.")
        test_logger.info("Kiểm tra log mức INFO: Hệ thống Vocab1337 đang sẵn sàng.")
        test_logger.warning("Kiểm tra log mức WARNING: Cảnh báo tài nguyên hoặc phản hồi chậm.")
        try:
            raise ValueError("Lỗi thử nghiệm phục vụ kiểm tra hệ thống bắt lỗi tự động!")
        except Exception as ex:
            test_logger.error(f"Kiểm tra log mức ERROR: {ex}", exc_info=True)
        
        page.show_dialog(ft.SnackBar(ft.Text("✓ Đã sinh 4 bản ghi log kiểm tra (DEBUG, INFO, WARN, ERROR)!"), bgcolor="#166534"))
        page.update()

    def do_clean_old_logs(e=None):
        deleted = clean_old_logs(days=14)
        page.show_dialog(ft.SnackBar(ft.Text(f"✓ Đã dọn dẹp {deleted} tệp log cũ quá 14 ngày."), bgcolor="#166534"))
        page.update()

    logs_dir_path = get_logs_dir()

    logging_card = nb_card(
        ft.Column([
            ft.Text("NHẬT KÝ HỆ THỐNG & GỠ LỖI (LOGGING & DIAGNOSTICS)", size=12,
                    weight=ft.FontWeight.W_700, color=TEXT_GRAY,
                    style=ft.TextStyle(letter_spacing=1.5)),
            ft.Container(height=4),
            ft.Text(f"Lưu trữ tự động xoay vòng tại: {logs_dir_path}", size=11, color=TEXT_GRAY, font_family="monospace"),
            ft.Container(height=12),
            log_level_row("DEBUG",   "Chi tiết nhất — ghi lại toàn bộ luồng xử lý, tham số, raw AI, audio latency."),
            ft.Container(height=4),
            log_level_row("INFO",    "Khuyên dùng — ghi nhận các sự kiện chính (bắt đầu học, tải model, lưu DB)."),
            ft.Container(height=4),
            log_level_row("WARNING", "Chỉ ghi lại các cảnh báo bất thường hoặc fallback chuyển đổi."),
            ft.Container(height=4),
            log_level_row("ERROR",   "Tối giản — chỉ ghi lại lỗi nghiêm trọng và ngoại lệ có Traceback."),
            ft.Container(height=16),
            ft.Text("CÔNG CỤ QUẢN TRỊ NHẬT KÝ", size=10, weight=ft.FontWeight.W_700,
                    color=TEXT_GRAY, style=ft.TextStyle(letter_spacing=1.5)),
            ft.Container(height=8),
            ft.Row([
                nb_button("📋 Mở trình xem Log trực tiếp", on_click=lambda e: show_log_viewer_dialog(page), bgcolor=CLR_YELLOW, color=TEXT_DARK),
                nb_button("📂 Mở thư mục Logs", on_click=open_logs_folder, bgcolor=BG_WHITE, color=TEXT_DARK),
                nb_button("🧪 Ghi log kiểm tra", on_click=generate_test_logs, bgcolor=CLR_BLUE, color=TEXT_DARK),
                nb_button("🧹 Dọn dẹp log cũ (>14 ngày)", on_click=do_clean_old_logs, bgcolor=BG_WHITE, color=TEXT_DARK),
            ], wrap=True, spacing=10, run_spacing=8),
        ], spacing=4),
        shadow_size="sm",
    )

    return ft.Column(
        [
            label_text("Hệ thống"),
            heading_text("Cài đặt"),
            ft.Container(height=1, bgcolor=TEXT_DARK, margin=marg(top=6, bottom=20)),
            ft.Text("Nhấp trực tiếp để lưu cấu hình Whisper chạy cục bộ:", size=13, color=TEXT_GRAY),
            ft.Container(height=16),
            whisper_card,
            ft.Container(height=16),
            device_card,
            ft.Container(height=24),
            tts_card,
            ft.Container(height=24),
            ai_provider_card,
            ft.Container(height=24),
            logging_card,
        ],
        spacing=0, expand=True, scroll=ft.ScrollMode.AUTO,
    )


# ══════════════════════════════════════════════════════════════════════════════
# ── ACTIVE LEARNING SESSIONS ──────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

def build_flashcard_session(page: ft.Page, lesson_id: int, on_exit, shuffle: bool = True) -> ft.Control:
    """Màn hình chạy phiên học Flashcard của 1 bài học."""
    lesson = get_lesson_by_id(lesson_id)
    try:
        vocab_ids = json.loads(lesson.get("vocab_ids") or "[]") if lesson else []
    except Exception:
        vocab_ids = []
    
    # Load toàn bộ vocab tương ứng
    vocab_list = []
    for vid in vocab_ids:
        v = get_vocab_by_id(vid)
        if v:
            vocab_list.append(dict(v))

    # Đảo ngẫu nhiên thứ tự từ nếu shuffle=True
    if shuffle:
        random.shuffle(vocab_list)

    # Tải tiến độ hiện tại từ SQLite (nếu có)
    progress_rows = get_progress_by_lesson(lesson_id)
    progress_map = {p["vocab_id"]: p for p in progress_rows}

    init_scores = []
    init_seens = []
    init_mastered = []
    for v in vocab_list:
        p = progress_map.get(v.get("id"))
        if p:
            sc = p.get("score", 0) or 0
            init_scores.append(sc)
            init_seens.append(1 if sc > 0 else 0)
            init_mastered.append(p.get("status") == "mastered" or sc >= 6)
        else:
            init_scores.append(0)
            init_seens.append(0)
            init_mastered.append(False)

    active_queue = [i for i in range(len(vocab_list)) if not init_mastered[i]]
    if not active_queue and vocab_list:
        active_queue = list(range(len(vocab_list)))
        init_mastered = [False] * len(vocab_list)

    state = {
        "queue": active_queue,
        "current_ptr": 0,
        "scores": init_scores,
        "seens": init_seens,
        "mastered": init_mastered,
    }

    # Dict dùng để truyền flip_action ra ngoài từ build_flashcard_view
    flip_ref = {}

    session_view = ft.Column(spacing=20, expand=True)

    # 1. Header & Tiến độ
    les_t = (lesson.get("title") if lesson else None) or "FLASHCARD"
    title_lbl = ft.Text(les_t.upper(), size=18, weight=ft.FontWeight.W_900, color=TEXT_DARK)
    progress_bar = ft.ProgressBar(value=0, color="#166534", bgcolor="#e5e7eb", height=8)
    
    def _exit_session():
        page.on_keyboard_event = None
        on_exit()

    # Nút thoát session
    exit_btn = nb_button("Thoát phiên học", on_click=lambda e: _exit_session())

    header_row = ft.Row([
        ft.Column([title_lbl, ft.Text("Thẻ học từ vựng Spaced Repetition", size=12, color=TEXT_GRAY)], spacing=2),
        ft.Container(expand=True),
        exit_btn
    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

    session_view.controls.append(header_row)
    session_view.controls.append(progress_bar)

    # Nơi chứa view thẻ học
    card_area = ft.Container()
    session_view.controls.append(card_area)

    def update_progress(first_load=False):
        mastered_count = sum(1 for m in state["mastered"] if m)
        total = len(vocab_list)
        if total > 0:
            progress_bar.value = mastered_count / total
        else:
            progress_bar.value = 1.0
        if not first_load:
            progress_bar.update()

    def show_next(first_load=False):
        # Lọc các chỉ mục chưa mastered khỏi queue
        state["queue"] = [i for i in state["queue"] if not state["mastered"][i]]
        
        if not state["queue"]:
            # Hoàn thành phiên học!
            show_finish_screen(first_load=first_load)
            return

        # Lấy chỉ mục tiếp theo từ đầu hàng đợi (queue)
        curr_idx = state["queue"][0]
        state["current_ptr"] = curr_idx
        
        # Gọi rate callback
        def on_rate_callback(rating: str):
            rate_rates = {"FORGOT": -1, "VAGUE": 0, "RECALL": 1, "EASY": 2}
            pts = rate_rates.get(rating, 0)
            
            # Cập nhật điểm & seens
            state["seens"][curr_idx] += 1
            state["scores"][curr_idx] = max(0.0, round(float(state["scores"][curr_idx]) + pts, 2))
            
            # Master threshold = 6
            if state["scores"][curr_idx] >= 6:
                state["mastered"][curr_idx] = True
                # Lưu vào SQLite
                upsert_progress(lesson_id, vocab_list[curr_idx]["id"], "mastered", state["scores"][curr_idx])
            else:
                # Cập nhật SQLite đang học
                upsert_progress(lesson_id, vocab_list[curr_idx]["id"], "learning", state["scores"][curr_idx])

            update_progress()
            
            # Đẩy từ vừa học xuống cuối hàng đợi học nếu chưa thuộc
            if curr_idx in state["queue"]:
                state["queue"].remove(curr_idx)
            if not state["mastered"][curr_idx]:
                state["queue"].append(curr_idx)
                
            # Reload
            show_next()

        def on_next_card():
            on_rate_callback("EASY")

        flip_ref["on_next"] = on_next_card
        flip_ref["on_rate"] = on_rate_callback

        card_area.content = build_flashcard_view(
            vocab=vocab_list[curr_idx],
            score=state["scores"][curr_idx],
            seen=state["seens"][curr_idx],
            on_rate=on_rate_callback,
            on_speak=lambda text: speak_text(page, text),
            on_next=on_next_card,
            flip_ref=flip_ref,
        )
        if not first_load:
            card_area.update()

    def show_finish_screen(first_load=False):
        card_area.content = nb_card(
            ft.Column([
                ft.Text("🎉 HOÀN THÀNH PHIÊN HỌC", size=24, weight=ft.FontWeight.W_900, color="#166534"),
                ft.Container(height=8),
                ft.Text("Tất cả các từ vựng trong bài học này đã được ghi nhớ thành công!", size=14, color=TEXT_DARK),
                ft.Container(height=24),
                nb_button("Quay lại danh sách", on_click=lambda e: _exit_session(), bgcolor=TEXT_DARK, color=TEXT_WHITE)
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            padding=48
        )
        if not first_load:
            card_area.update()

    # ── Keyboard shortcuts: Space = lật thẻ, Enter = thẻ tiếp theo, 1-4 = đánh giá ─────────────
    def _on_keyboard(e: ft.KeyboardEvent):
        key = e.key
        if key == " ":
            # Space → lật thẻ (chỉ lật khi score < 3 hoặc thẻ đã lật)
            can_flip = flip_ref.get("can_flip_space")
            if can_flip and not can_flip():
                return
            fn = flip_ref.get("flip")
            if fn:
                fn()
        elif key == "Enter":
            # Enter → chuyển thẻ tiếp theo (chỉ khi đã lật sang mặt sau)
            is_flipped = flip_ref.get("is_flipped")
            if is_flipped and is_flipped():
                next_fn = flip_ref.get("on_next")
                if next_fn:
                    next_fn()
        elif key in ["1", "2", "3", "4", "Numpad 1", "Numpad 2", "Numpad 3", "Numpad 4"]:
            is_flipped = flip_ref.get("is_flipped")
            if is_flipped and is_flipped():
                rate_map = {
                    "1": "FORGOT", "Numpad 1": "FORGOT",
                    "2": "VAGUE",  "Numpad 2": "VAGUE",
                    "3": "RECALL", "Numpad 3": "RECALL",
                    "4": "EASY",   "Numpad 4": "EASY"
                }
                rate_fn = flip_ref.get("on_rate")
                if rate_fn and key in rate_map:
                    rate_fn(rate_map[key])

    page.on_keyboard_event = _on_keyboard

    if vocab_list:
        show_next(first_load=True)
    else:
        card_area.content = ft.Text("Bài học này chưa có từ vựng nào.", size=14, color=TEXT_GRAY)

    return session_view


def build_random_flashcard_session(page: ft.Page, count: int, on_exit) -> ft.Control:
    """Phiên học Flashcard tạm thời với N từ ngẫu nhiên."""
    vocab_list = get_random_vocab(count)

    # Đảo thêm lần nữa để đảm bảo thứ tự hoàn toàn ngẫu nhiên
    random.shuffle(vocab_list)

    state = {
        "queue": list(range(len(vocab_list))),
        "current_ptr": 0,
        "scores": [0] * len(vocab_list),
        "seens": [0] * len(vocab_list),
        "mastered": [False] * len(vocab_list),
    }

    flip_ref = {}

    session_view = ft.Column(spacing=20, expand=True)

    # 1. Header & Tiến độ
    title_lbl = ft.Text("HỌC NGẪU NHIÊN", size=18, weight=ft.FontWeight.W_900, color=TEXT_DARK)
    progress_bar = ft.ProgressBar(value=0, color="#166534", bgcolor="#e5e7eb", height=8)

    def _exit_session():
        page.on_keyboard_event = None
        on_exit()

    exit_btn = nb_button("Thoát", on_click=lambda e: _exit_session())

    header_row = ft.Row([
        ft.Column([title_lbl, ft.Text(f"Phiên học tạm thời với {len(vocab_list)} từ vựng ngẫu nhiên", size=12, color=TEXT_GRAY)], spacing=2),
        ft.Container(expand=True),
        exit_btn
    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

    session_view.controls.append(header_row)
    session_view.controls.append(progress_bar)

    card_area = ft.Container()
    session_view.controls.append(card_area)

    def update_progress(first_load=False):
        mastered_count = sum(1 for m in state["mastered"] if m)
        total = len(vocab_list)
        if total > 0:
            progress_bar.value = mastered_count / total
        if not first_load:
            progress_bar.update()

    def show_next(first_load=False):
        state["queue"] = [i for i in state["queue"] if not state["mastered"][i]]
        if not state["queue"]:
            show_finish_screen(first_load=first_load)
            return

        curr_idx = state["queue"][0]
        state["current_ptr"] = curr_idx

        def on_rate_callback(rating: str):
            rate_rates = {"FORGOT": -1, "VAGUE": 0, "RECALL": 1, "EASY": 2}
            pts = rate_rates.get(rating, 0)
            state["seens"][curr_idx] += 1
            state["scores"][curr_idx] = max(0.0, round(float(state["scores"][curr_idx]) + pts, 2))
            
            if state["scores"][curr_idx] >= 6:
                state["mastered"][curr_idx] = True

            update_progress()
            
            if curr_idx in state["queue"]:
                state["queue"].remove(curr_idx)
            if not state["mastered"][curr_idx]:
                state["queue"].append(curr_idx)
            show_next()

        def on_next_card():
            on_rate_callback("EASY")

        flip_ref["on_next"] = on_next_card
        flip_ref["on_rate"] = on_rate_callback

        card_area.content = build_flashcard_view(
            vocab=vocab_list[curr_idx],
            score=state["scores"][curr_idx],
            seen=state["seens"][curr_idx],
            on_rate=on_rate_callback,
            on_speak=lambda text: speak_text(page, text),
            on_next=on_next_card,
            flip_ref=flip_ref,
        )
        if not first_load:
            card_area.update()

    def show_finish_screen(first_load=False):
        card_area.content = nb_card(
            ft.Column([
                ft.Text("🎉 PHIÊN HỌC HOÀN THÀNH", size=24, weight=ft.FontWeight.W_900, color="#166534"),
                ft.Container(height=8),
                ft.Text("Hoàn thành luyện tập ngẫu nhiên!", size=14, color=TEXT_DARK),
                ft.Container(height=24),
                nb_button("Quay lại", on_click=lambda e: _exit_session(), bgcolor=TEXT_DARK, color=TEXT_WHITE)
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            padding=48
        )
        if not first_load:
            card_area.update()

    # ── Keyboard shortcuts: Space = lật thẻ, Enter = thẻ tiếp theo, 1-4 = đánh giá ─────────────
    def _on_keyboard(e: ft.KeyboardEvent):
        key = e.key
        if key == " ":
            # Space → lật thẻ (chỉ lật khi score < 3 hoặc thẻ đã lật)
            can_flip = flip_ref.get("can_flip_space")
            if can_flip and not can_flip():
                return
            fn = flip_ref.get("flip")
            if fn:
                fn()
        elif key == "Enter":
            # Enter → chuyển thẻ tiếp theo (chỉ khi đã lật sang mặt sau)
            is_flipped = flip_ref.get("is_flipped")
            if is_flipped and is_flipped():
                next_fn = flip_ref.get("on_next")
                if next_fn:
                    next_fn()
        elif key in ["1", "2", "3", "4", "Numpad 1", "Numpad 2", "Numpad 3", "Numpad 4"]:
            is_flipped = flip_ref.get("is_flipped")
            if is_flipped and is_flipped():
                rate_map = {
                    "1": "FORGOT", "Numpad 1": "FORGOT",
                    "2": "VAGUE",  "Numpad 2": "VAGUE",
                    "3": "RECALL", "Numpad 3": "RECALL",
                    "4": "EASY",   "Numpad 4": "EASY"
                }
                rate_fn = flip_ref.get("on_rate")
                if rate_fn and key in rate_map:
                    rate_fn(rate_map[key])

    page.on_keyboard_event = _on_keyboard

    if vocab_list:
        show_next(first_load=True)
    else:
        card_area.content = ft.Text("Không lấy được từ vựng nào.", size=14, color=TEXT_GRAY)

    return session_view


def build_lesson_editor(page: ft.Page, lesson_id: int, on_back) -> ft.Control:
    """Màn hình chỉnh sửa bài học đầy đủ (metadata, vocab, thumbnail)."""
    lesson = get_lesson_by_id(lesson_id)
    if not lesson:
        return ft.Text("Không tìm thấy bài học.", color=CLR_RED)

    try:
        vocab_ids = json.loads(lesson.get("vocab_ids") or "[]")
    except Exception:
        vocab_ids = []
    raw_vocabs = [get_vocab_by_id(vid) for vid in vocab_ids]

    # ── Mutable state ────────────────────────────────────────────────────────
    state = {
        "vocab_order": [dict(v) for v in raw_vocabs if v],
        "thumbnail": lesson.get("thumbnail", "") or "",
        "editing_idx": None,   # index của vocab đang mở form edit
    }

    # ── Helpers ──────────────────────────────────────────────────────────────
    def safe_overlay_remove(ctrl):
        try:
            if ctrl in page.overlay:
                page.overlay.remove(ctrl)
            if ctrl in page.services:
                page.services.remove(ctrl)
        except Exception:
            pass

    # ── LEFT: Tiêu đề & Bài đọc ─────────────────────────────────────────────
    title_inp = ft.TextField(
        value=lesson["title"],
        label="Tiêu đề bài học",
        border_color=TEXT_DARK, border_width=2, border_radius=0,
        text_style=ft.TextStyle(size=15, weight=ft.FontWeight.W_700),
    )

    word_count_txt = ft.Text("", size=11, color=TEXT_GRAY, weight=ft.FontWeight.W_600)

    def update_word_count(e=None):
        story = story_inp.value or ""
        words = len(story.split()) if story.strip() else 0
        vocab_words = {v.get("word", "").lower() for v in state["vocab_order"] if v.get("word")}
        found = sum(
            1 for w in story.lower().split()
            if w.strip(".,;:!?\"'()[]") in vocab_words
        )
        word_count_txt.value = (
            f"📝 {words} từ   •   🔍 {found}/{len(state['vocab_order'])} từ vựng xuất hiện trong bài"
        )
        if e:
            word_count_txt.update()

    story_inp = ft.TextField(
        value=lesson.get("story_context", ""),
        label="Bài đọc / Ngữ cảnh",
        border_color=TEXT_DARK, border_width=2, border_radius=0,
        multiline=True, min_lines=8, max_lines=20,
        on_change=update_word_count,
    )
    update_word_count()

    # ── LEFT: Thumbnail ──────────────────────────────────────────────────────
    from pathlib import Path as _Path
    thumb_preview = ft.Container(
        width=220, height=150,
        alignment=ft.Alignment(0, 0),
        bgcolor="#f9fafb",
        border=mk_border(2, "#d1d5db"),
    )

    def _refresh_thumb():
        p = state["thumbnail"]
        if p and _Path(p).exists():
            thumb_preview.content = ft.Image(src=p, fit="cover", width=220, height=150)
        else:
            thumb_preview.content = ft.Column([
                ft.Text("🖼", size=32),
                ft.Text("Chưa có ảnh", size=12, color=TEXT_GRAY, italic=True),
            ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER)

    _refresh_thumb()

    def on_file_picked(e):
        if e.files and len(e.files) > 0:
            state["thumbnail"] = e.files[0].path
            _refresh_thumb()
            thumb_preview.update()

    file_picker = ft.FilePicker()
    file_picker.on_result = on_file_picked
    if hasattr(page, "services"):
        page.services.append(file_picker)
    else:
        page.overlay.append(file_picker)

    def pick_image(e):
        file_picker.pick_files(
            file_type=ft.FilePickerFileType.IMAGE,
            allowed_extensions=["jpg", "jpeg", "png", "webp"]
        )

    def _remove_thumbnail(e=None):
        state["thumbnail"] = ""
        _refresh_thumb()
        thumb_preview.update()

    # ── RIGHT: Vocab card builder ─────────────────────────────────────────────
    vocab_list_col = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO, expand=True)

    def refresh_vocab_list(update_ui: bool = True):
        update_word_count()
        vocab_list_col.controls.clear()
        for i, v in enumerate(state["vocab_order"]):
            vocab_list_col.controls.append(_build_vocab_card(v, i))
        if update_ui:
            vocab_list_col.update()
            word_count_txt.update()

    def _build_vocab_card(vocab: dict, idx: int) -> ft.Control:
        word = vocab.get("word", "")
        pos  = vocab.get("pos", "")
        ipa  = vocab.get("ipa", "")
        def_en = vocab.get("definition_short_en", "")
        def_vi = vocab.get("definition_vi", "")
        ex_en  = vocab.get("example_en", "")
        total  = len(state["vocab_order"])

        if state["editing_idx"] == idx:
            # ── EDIT FORM IN-PLACE ──────────────────────────────────────────
            e_word     = ft.TextField(value=vocab.get("word",""), label="Từ *", dense=True, border_color=TEXT_DARK, border_width=2, border_radius=0)
            e_pos      = ft.Dropdown(value=vocab.get("pos","noun"), label="Từ loại", dense=True, border_color=TEXT_DARK, border_width=2, border_radius=0,
                                     options=[ft.dropdown.Option(p) for p in ["noun","verb","adj","adv","phrase","idiom","other"]])
            e_ipa      = ft.TextField(value=vocab.get("ipa",""), label="IPA", dense=True, border_color=TEXT_DARK, border_width=2, border_radius=0)
            e_def_en   = ft.TextField(value=vocab.get("definition_short_en",""), label="Định nghĩa EN (ngắn)", dense=True, border_color=TEXT_DARK, border_width=2, border_radius=0)
            e_def_full = ft.TextField(value=vocab.get("definition_full_en",""), label="Định nghĩa EN (đầy đủ)", dense=True, border_color=TEXT_DARK, border_width=2, border_radius=0)
            e_def_vi   = ft.TextField(value=vocab.get("definition_vi",""), label="Định nghĩa VI", dense=True, border_color=TEXT_DARK, border_width=2, border_radius=0)
            e_ex_en    = ft.TextField(value=vocab.get("example_en",""), label="Ví dụ EN", dense=True, border_color=TEXT_DARK, border_width=2, border_radius=0, multiline=True, min_lines=2)
            e_ex_vi    = ft.TextField(value=vocab.get("example_vi",""), label="Ví dụ VI", dense=True, border_color=TEXT_DARK, border_width=2, border_radius=0, multiline=True, min_lines=2)
            e_nuance   = ft.TextField(value=vocab.get("nuance_en",""), label="Nuance EN", dense=True, border_color=TEXT_DARK, border_width=2, border_radius=0)
            e_err      = ft.Text("", color="#991b1b", size=11, weight=ft.FontWeight.W_700)

            def save_vocab_edit(e, _i=idx, _vid=vocab.get("id")):
                new_word = (e_word.value or "").strip()
                if not new_word:
                    e_err.value = "Từ không được để trống."; e_err.update(); return
                fields = {
                    "word": new_word, "pos": e_pos.value or "noun",
                    "ipa": (e_ipa.value or "").strip(),
                    "ipa_uk": (e_ipa.value or "").strip(),
                    "definition_short_en": (e_def_en.value or "").strip(),
                    "definition_minimal_en": (e_def_en.value or "").strip(),
                    "definition_full_en": (e_def_full.value or "").strip(),
                    "definition_simple_en": (e_def_full.value or "").strip(),
                    "definition_vi": (e_def_vi.value or "").strip(),
                    "definition_vi_simple": (e_def_vi.value or "").strip(),
                    "example_en": (e_ex_en.value or "").strip(),
                    "example_vi": (e_ex_vi.value or "").strip(),
                    "nuance_en": (e_nuance.value or "").strip(),
                }
                try:
                    if _vid:
                        update_vocab(_vid, fields)
                        updated = get_vocab_by_id(_vid)
                        if updated:
                            state["vocab_order"][_i] = dict(updated)
                        else:
                            state["vocab_order"][_i].update(fields)
                    else:
                        state["vocab_order"][_i].update(fields)
                    state["editing_idx"] = None
                    refresh_vocab_list()
                except Exception as ex:
                    e_err.value = f"Lỗi: {ex}"; e_err.update()

            def cancel_vocab_edit(e):
                state["editing_idx"] = None
                refresh_vocab_list()

            return ft.Container(
                content=ft.Column([
                    ft.Text(f"✏ CHỈNH SỬA: {(word or '').upper()}", size=10, weight=ft.FontWeight.W_800, color="#3730a3", style=ft.TextStyle(letter_spacing=1.2)),
                    ft.Container(height=6),
                    ft.Row([e_word, e_pos], spacing=10),
                    e_ipa, e_def_en, e_def_full, e_def_vi, e_ex_en, e_ex_vi, e_nuance,
                    e_err,
                    ft.Container(height=4),
                    ft.Row([
                        nb_button("💾  Lưu từ", on_click=save_vocab_edit, bgcolor=TEXT_DARK, color=TEXT_WHITE),
                        nb_button("✕  Hủy", on_click=cancel_vocab_edit, bgcolor=BG_WHITE, color=TEXT_DARK),
                    ], spacing=8),
                ], spacing=8),
                bgcolor="#f0f0ff",
                border=mk_border(2, "#3730a3"),
                shadow=SHADOW_SM,
                padding=pad(all_=16),
            )

        # ── DISPLAY MODE ────────────────────────────────────────────────────
        def start_edit(e, _i=idx):
            state["editing_idx"] = _i; refresh_vocab_list()

        def move_up(e, _i=idx):
            if _i > 0:
                state["vocab_order"][_i-1], state["vocab_order"][_i] = state["vocab_order"][_i], state["vocab_order"][_i-1]
                refresh_vocab_list()

        def move_down(e, _i=idx):
            if _i < len(state["vocab_order"]) - 1:
                state["vocab_order"][_i+1], state["vocab_order"][_i] = state["vocab_order"][_i], state["vocab_order"][_i+1]
                refresh_vocab_list()

        def confirm_remove(e, _i=idx, _w=word):
            def do_remove(e2):
                safe_close_dialog(page, del_dlg)
                state["vocab_order"].pop(_i)
                if state["editing_idx"] == _i:
                    state["editing_idx"] = None
                refresh_vocab_list()

            def cancel_remove(e2):
                safe_close_dialog(page, del_dlg)

            del_dlg = ft.AlertDialog(
                modal=True,
                title=ft.Text(f"Xóa \"{_w}\" khỏi bài?", size=14, weight=ft.FontWeight.W_900, color=TEXT_DARK),
                content=ft.Column([
                    ft.Text("Từ này sẽ bị xóa khỏi bài học. Dữ liệu gốc trong kho từ vựng vẫn được giữ nguyên.", size=13, color=TEXT_GRAY),
                    ft.Container(height=16),
                    ft.Row([
                        nb_button("🗑  Xóa", on_click=do_remove, bgcolor=CLR_RED, color=TEXT_DARK),
                        ft.Container(width=8),
                        nb_button("Hủy", on_click=cancel_remove, bgcolor=BG_WHITE, color=TEXT_DARK),
                    ], alignment=ft.MainAxisAlignment.END),
                ], spacing=0, tight=True),
            )
            try:
                page.show_dialog(del_dlg)
            except Exception:
                page.overlay.append(del_dlg)
                del_dlg.open = True
                page.update()

        _active = "#e5e7eb"
        _inactive = "#d1d5db"
        can_up = idx > 0
        can_dn = idx < total - 1

        def _reorder_btn(symbol, active, on_click_fn):
            return ft.Container(
                content=ft.Text(symbol, size=13, weight=ft.FontWeight.W_900,
                                color=TEXT_DARK if active else _inactive),
                bgcolor=BG_WHITE,
                border=mk_border(2, TEXT_DARK if active else _inactive),
                padding=pad(h=7, v=4),
                on_click=on_click_fn if active else None,
                ink=active,
            )

        return ft.Container(
            content=ft.Row([
                ft.Container(
                    content=ft.Text(f"{idx+1}", size=10, weight=ft.FontWeight.W_700, color=TEXT_GRAY),
                    width=22, alignment=ft.Alignment(0, 0),
                ),
                ft.Column([
                    ft.Row([
                        ft.Text((word or "").upper(), size=13, weight=ft.FontWeight.W_900, color=TEXT_DARK),
                        ft.Container(
                            content=ft.Text(pos, size=9, weight=ft.FontWeight.W_700, color=TEXT_WHITE),
                            bgcolor="#3730a3", padding=pad(h=5, v=2),
                        ) if pos else ft.Container(),
                        ft.Text(f"/{ipa}/", size=10, color=TEXT_GRAY) if ipa else ft.Container(),
                    ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    ft.Text(def_en, size=11, color="#3730a3", weight=ft.FontWeight.W_600) if def_en else ft.Container(),
                    ft.Text(def_vi, size=11, color="#166534", italic=True) if def_vi else ft.Container(),
                    ft.Text(f'"{ex_en}"', size=10, color=TEXT_GRAY, italic=True) if ex_en else ft.Container(),
                ], spacing=2, expand=True),
                ft.Column([_reorder_btn("↑", can_up, move_up), _reorder_btn("↓", can_dn, move_down)], spacing=3),
                ft.Column([
                    ft.Container(
                        content=ft.Text("✏", size=12),
                        bgcolor=CLR_BLUE, border=mk_border(2, TEXT_DARK),
                        padding=pad(h=8, v=4), on_click=start_edit, ink=True, tooltip="Chỉnh sửa",
                    ),
                    ft.Container(
                        content=ft.Text("🗑", size=12),
                        bgcolor=CLR_RED, border=mk_border(2, TEXT_DARK),
                        padding=pad(h=8, v=4), on_click=confirm_remove, ink=True, tooltip="Xóa khỏi bài",
                    ),
                ], spacing=3),
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            bgcolor=BG_WHITE,
            border=mk_border(2, "#e5e7eb"),
            shadow=SHADOW_SM,
            padding=pad(h=12, v=8),
        )

    # ── RIGHT: Add form ──────────────────────────────────────────────────────
    add_word_f  = ft.TextField(label="Từ (word) *", dense=True, border_color=TEXT_DARK, border_width=2, border_radius=0)
    add_pos_f   = ft.Dropdown(value="noun", label="Từ loại", dense=True, border_color=TEXT_DARK, border_width=2, border_radius=0,
                               options=[ft.dropdown.Option(p) for p in ["noun","verb","adj","adv","phrase","idiom","other"]])
    add_ipa_f   = ft.TextField(label="IPA", dense=True, border_color=TEXT_DARK, border_width=2, border_radius=0)
    add_den_f   = ft.TextField(label="Định nghĩa EN (ngắn)", dense=True, border_color=TEXT_DARK, border_width=2, border_radius=0)
    add_dvi_f   = ft.TextField(label="Định nghĩa VI", dense=True, border_color=TEXT_DARK, border_width=2, border_radius=0)
    add_exen_f  = ft.TextField(label="Ví dụ EN", dense=True, border_color=TEXT_DARK, border_width=2, border_radius=0, multiline=True, min_lines=2)
    add_exvi_f  = ft.TextField(label="Ví dụ VI", dense=True, border_color=TEXT_DARK, border_width=2, border_radius=0)
    add_err_txt = ft.Text("", color="#991b1b", size=12, weight=ft.FontWeight.W_700)

    import_json_f   = ft.TextField(label="Dán JSON Array để import nhanh", dense=True,
                                    border_color=TEXT_DARK, border_width=2, border_radius=0,
                                    multiline=True, min_lines=5,
                                    hint_text='[{"word": "...", "pos": "noun", ...}]')
    import_err_txt = ft.Text("", color="#991b1b", size=12, weight=ft.FontWeight.W_700)

    add_form_box    = ft.Container(visible=False)
    import_form_box = ft.Container(visible=False)

    _form_state = {"adding": False, "importing": False}

    def toggle_add(e=None):
        _form_state["adding"] = not _form_state["adding"]
        if _form_state["adding"]:
            _form_state["importing"] = False
            import_form_box.visible = False
            import_form_box.update()
        add_form_box.visible = _form_state["adding"]
        add_form_box.update()

    def toggle_import(e=None):
        _form_state["importing"] = not _form_state["importing"]
        if _form_state["importing"]:
            _form_state["adding"] = False
            add_form_box.visible = False
            add_form_box.update()
        import_form_box.visible = _form_state["importing"]
        import_form_box.update()

    def do_add_vocab(e):
        add_err_txt.value = ""
        word = (add_word_f.value or "").strip()
        if not word:
            add_err_txt.value = "Vui lòng nhập từ vựng."; add_err_txt.update(); return
        try:
            vid = upsert_vocab({
                "word": word, "pos": add_pos_f.value or "noun",
                "ipa": (add_ipa_f.value or "").strip(),
                "ipa_uk": (add_ipa_f.value or "").strip(),
                "definition_short_en": (add_den_f.value or "").strip(),
                "definition_minimal_en": (add_den_f.value or "").strip(),
                "definition_simple_en": (add_den_f.value or "").strip(),
                "definition_vi": (add_dvi_f.value or "").strip(),
                "definition_vi_simple": (add_dvi_f.value or "").strip(),
                "example_en": (add_exen_f.value or "").strip(),
                "example_vi": (add_exvi_f.value or "").strip(),
            })
            new_v = get_vocab_by_id(vid)
            existing_ids = {v["id"] for v in state["vocab_order"]}
            if vid not in existing_ids:
                state["vocab_order"].append(dict(new_v))
            for f in [add_word_f, add_ipa_f, add_den_f, add_dvi_f, add_exen_f, add_exvi_f]:
                f.value = ""
            add_pos_f.value = "noun"
            add_err_txt.value = ""
            toggle_add()
            refresh_vocab_list()
        except Exception as ex:
            add_err_txt.value = f"Lỗi: {ex}"; add_err_txt.update()

    def do_import_json(e):
        import_err_txt.value = ""
        raw = (import_json_f.value or "").strip()
        if not raw:
            import_err_txt.value = "Nội dung JSON rỗng."; import_err_txt.update(); return
        try:
            items = json.loads(raw)
            if not isinstance(items, list):
                raise ValueError("Phải là JSON Array")
            existing_ids = {v["id"] for v in state["vocab_order"]}
            added = 0
            for item in items:
                if not item.get("word"):
                    continue
                vid = upsert_vocab(item)
                if vid not in existing_ids:
                    nv = get_vocab_by_id(vid)
                    if nv:
                        state["vocab_order"].append(dict(nv))
                        existing_ids.add(vid)
                        added += 1
            import_json_f.value = ""
            toggle_import()
            refresh_vocab_list()
            page.show_dialog(ft.SnackBar(ft.Text(f"✓ Import {added} từ vựng thành công!"), bgcolor="#166534"))
            page.update()
        except Exception as ex:
            import_err_txt.value = f"JSON không hợp lệ: {ex}"; import_err_txt.update()

    add_form_box.content = ft.Container(
        content=ft.Column([
            ft.Text("THÊM TỪ VỰNG MỚI", size=9, weight=ft.FontWeight.W_800, color=TEXT_GRAY, style=ft.TextStyle(letter_spacing=1.5)),
            ft.Container(height=6),
            ft.Row([add_word_f, add_pos_f], spacing=10),
            add_ipa_f, add_den_f, add_dvi_f, add_exen_f, add_exvi_f,
            add_err_txt,
            ft.Row([
                nb_button("+ Thêm vào bài", on_click=do_add_vocab, bgcolor=TEXT_DARK, color=TEXT_WHITE),
                nb_button("✕ Hủy", on_click=toggle_add, bgcolor=BG_WHITE, color=TEXT_DARK),
            ], spacing=8),
        ], spacing=8),
        bgcolor="#f0fff4", border=mk_border(2, "#166534"), padding=pad(all_=16), shadow=SHADOW_SM,
    )

    import_form_box.content = ft.Container(
        content=ft.Column([
            ft.Text("IMPORT NHANH JSON ARRAY", size=9, weight=ft.FontWeight.W_800, color=TEXT_GRAY, style=ft.TextStyle(letter_spacing=1.5)),
            ft.Container(height=6),
            import_json_f, import_err_txt,
            ft.Row([
                nb_button("📥 Import", on_click=do_import_json, bgcolor=TEXT_DARK, color=TEXT_WHITE),
                nb_button("✕ Hủy", on_click=toggle_import, bgcolor=BG_WHITE, color=TEXT_DARK),
            ], spacing=8),
        ], spacing=8),
        bgcolor="#f0f4ff", border=mk_border(2, "#3730a3"), padding=pad(all_=16), shadow=SHADOW_SM,
    )

    # ── Save / Delete lesson ─────────────────────────────────────────────────
    def save_all(e=None):
        new_ids = json.dumps([v["id"] for v in state["vocab_order"]])
        update_lesson(
            lesson_id,
            title=(title_inp.value or "").strip() or lesson.get("title", "Bài học"),
            story_context=(story_inp.value or "").strip(),
            vocab_ids_json=new_ids,
            thumbnail=state["thumbnail"] or None,
        )
        page.show_dialog(ft.SnackBar(ft.Text("✓ Đã lưu bài học thành công!"), bgcolor="#166534"))
        page.update()

    def on_keyboard_event(e):
        if e.key.lower() == "s" and e.ctrl:
            save_all()

    page.on_keyboard_event = on_keyboard_event

    def confirm_delete_lesson(e):
        def do_delete(e2):
            safe_close_dialog(page, del_dlg)
            page.on_keyboard_event = None
            safe_overlay_remove(file_picker)
            delete_lesson(lesson_id)
            page.show_dialog(ft.SnackBar(ft.Text("✓ Đã xóa bài học thành công!"), bgcolor="#166534"))
            on_back()

        def cancel_delete(e2):
            safe_close_dialog(page, del_dlg)

        del_dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Xóa bài học?", size=16, weight=ft.FontWeight.W_900, color="#991b1b"),
            content=ft.Column([
                ft.Text(f"Bài học \"{lesson['title']}\" sẽ bị xóa vĩnh viễn.", size=13, color=TEXT_GRAY),
                ft.Text("Toàn bộ tiến độ học và các từ vựng thuộc bài học này sẽ bị xóa khỏi cơ sở dữ liệu.", size=12, color="#991b1b", weight=ft.FontWeight.W_600),
                ft.Container(height=16),
                ft.Row([
                    nb_button("🗑  Xóa bài học", on_click=do_delete, bgcolor="#fecaca", color="#991b1b"),
                    ft.Container(width=8),
                    nb_button("Hủy", on_click=cancel_delete, bgcolor=BG_WHITE, color=TEXT_DARK),
                ], alignment=ft.MainAxisAlignment.END),
            ], spacing=4, tight=True),
        )
        page.show_dialog(del_dlg)

    def on_back_click(e=None):
        page.on_keyboard_event = None
        safe_overlay_remove(file_picker)
        on_back()

    # ── Toolbar ──────────────────────────────────────────────────────────────
    toolbar = nb_card(
        ft.Row([
            nb_button("← Quay lại", on_click=on_back_click, bgcolor=BG_WHITE, color=TEXT_DARK),
            ft.Container(expand=True),
            ft.Text("CHỈNH SỬA BÀI HỌC", size=12, weight=ft.FontWeight.W_900,
                    color=TEXT_DARK, style=ft.TextStyle(letter_spacing=2)),
            ft.Container(expand=True),
            nb_button("📤  Xuất JSON", on_click=lambda e: handle_export_lesson(page, lesson_id, title_inp.value or lesson.get("title", "Bài học")), bgcolor=BG_WHITE, color=TEXT_DARK),
            ft.Container(width=10),
            nb_button("🗑  Xóa bài học", on_click=confirm_delete_lesson, bgcolor=CLR_RED, color=TEXT_DARK),
            ft.Container(width=10),
            nb_button("💾  Lưu thay đổi  (Ctrl+S)", on_click=save_all, bgcolor=TEXT_DARK, color=TEXT_WHITE),
        ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
        shadow_size="sm", padding=pad(h=16, v=12),
    )

    # ── Left column ──────────────────────────────────────────────────────────
    left_col = ft.Container(
        content=ft.Column([
            # Lesson info card
            nb_card(ft.Column([
                ft.Text("THÔNG TIN BÀI HỌC", size=9, weight=ft.FontWeight.W_800,
                        color=TEXT_GRAY, style=ft.TextStyle(letter_spacing=1.8)),
                ft.Container(height=10),
                title_inp,
                ft.Container(height=10),
                story_inp,
                ft.Container(height=6),
                word_count_txt,
            ], spacing=0), shadow_size="sm", padding=20),
            ft.Container(height=16),
            # Thumbnail card
            nb_card(ft.Column([
                ft.Text("THUMBNAIL / ẢNH ĐẠI DIỆN", size=9, weight=ft.FontWeight.W_800,
                        color=TEXT_GRAY, style=ft.TextStyle(letter_spacing=1.8)),
                ft.Container(height=10),
                thumb_preview,
                ft.Container(height=8),
                ft.Row([
                    nb_button("📂 Chọn ảnh", on_click=pick_image, bgcolor=BG_WHITE, color=TEXT_DARK),
                    nb_button("✕ Xóa ảnh", on_click=_remove_thumbnail, bgcolor=CLR_RED, color=TEXT_DARK),
                ], spacing=8),
            ], spacing=0), shadow_size="sm", padding=20),
        ], scroll=ft.ScrollMode.AUTO),
        width=390,
    )

    # ── Right column ─────────────────────────────────────────────────────────
    right_col = ft.Container(
        content=nb_card(
            ft.Column([
                ft.Row([
                    ft.Text("DANH SÁCH TỪ VỰNG", size=9, weight=ft.FontWeight.W_800,
                            color=TEXT_GRAY, style=ft.TextStyle(letter_spacing=1.8)),
                    ft.Container(expand=True),
                    nb_button("📥 Import JSON", on_click=toggle_import, bgcolor=CLR_BLUE, color=TEXT_DARK),
                    ft.Container(width=8),
                    nb_button("+ Thêm từ", on_click=toggle_add, bgcolor=CLR_GREEN, color=TEXT_DARK),
                ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Container(height=10),
                import_form_box,
                add_form_box,
                ft.Container(height=8),
                vocab_list_col,
            ], spacing=0, expand=True),
            shadow_size="sm", padding=20,
        ),
        expand=True,
    )

    # Khởi tạo vocab list
    refresh_vocab_list(update_ui=False)

    # ── Final layout ─────────────────────────────────────────────────────────
    return ft.Column([
        toolbar,
        ft.Container(height=16),
        ft.Container(
            content=ft.Row([
                left_col,
                ft.Container(width=3, bgcolor="#e5e7eb"),
                right_col,
            ], spacing=20, expand=True, vertical_alignment=ft.CrossAxisAlignment.START),
            expand=True,
        ),
    ], spacing=0, expand=True)


def build_reading_session(page: ft.Page, lesson_id: int, on_exit, shuffle: bool = False) -> ft.Control:
    """Màn hình chạy Đọc hiểu & Câu hỏi của 1 bài học."""
    full_lesson = get_lesson_by_id(lesson_id)
    if not full_lesson:
        return ft.Text("Lỗi tải bài học.", color=CLR_RED)
    
    # Parse questions & flashcards
    try:
        questions = json.loads(full_lesson.get("questions_json") or "[]")
    except Exception:
        questions = []

    # Đảo thứ tự câu hỏi nếu người dùng chọn chế độ đảo câu (giữ Master Challenge luôn ở cuối cùng)
    if shuffle and questions:
        master_q = None
        other_qs = []
        for q in questions:
            inst = str(q.get("instruction", "")).lower()
            if "master" in inst or "final evaluation" in inst or q.get("is_master"):
                master_q = q
            else:
                other_qs.append(q)
        random.shuffle(other_qs)
        if master_q:
            questions = other_qs + [master_q]
        else:
            questions = other_qs
    
    vocab_list = []
    try:
        v_ids = json.loads(full_lesson.get("vocab_ids") or "[]")
        for vid in v_ids:
            v = get_vocab_by_id(vid)
            if v:
                vocab_list.append(v)
    except Exception:
        pass

    lesson_dict = {
        "title": full_lesson["title"],
        "story_context": full_lesson["story_context"],
        "questions": questions,
        "vocab": vocab_list,
    }

    session_view = ft.Column(spacing=20, expand=True, scroll=ft.ScrollMode.AUTO)

    # Nút thoát session
    exit_btn = nb_button("Thoát", on_click=lambda e: on_exit())

    les_rt = (full_lesson.get("title") if full_lesson else None) or "BÀI ĐỌC HIỂU"
    header_row = ft.Row([
        ft.Column([
            ft.Text(les_rt.upper(), size=18, weight=ft.FontWeight.W_900, color=TEXT_DARK),
            ft.Text("Đọc hiểu và trả lời câu hỏi liên quan", size=12, color=TEXT_GRAY)
        ], spacing=2),
        ft.Container(expand=True),
        exit_btn
    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

    session_view.controls.append(header_row)

    # Thân bài đọc hiểu
    reading_area = ft.Container()
    session_view.controls.append(reading_area)

    def on_reading_complete(correct=None, total=None):
        if correct is not None and total is not None and total > 0:
            pct = int(correct / total * 100)
            if correct == total:
                title_text = "🎉 XUẤT SẮC! HOÀN THÀNH TOÀN BỘ"
                title_color = "#166534"
                msg_text = f"Tuyệt vời! Bạn đã trả lời chính xác toàn bộ {correct}/{total} câu hỏi đọc hiểu (100%)!"
            elif pct >= 60:
                title_text = "👏 HOÀN THÀNH BÀI ĐỌC HIỂU"
                title_color = "#15803d"
                msg_text = f"Chúc mừng! Bạn đã trả lời đúng {correct}/{total} câu hỏi ({pct}%)."
            else:
                title_text = "📚 HOÀN THÀNH PHIÊN LUYỆN TẬP"
                title_color = "#b45309"
                msg_text = f"Bạn đã trả lời đúng {correct}/{total} câu hỏi ({pct}%). Hãy xem lại bài đọc và thử lại để cải thiện kết quả nhé!"
        else:
            title_text = "🎉 BÀI HỌC HOÀN THÀNH"
            title_color = "#166534"
            msg_text = "Chúc mừng bạn đã hoàn thành bài đọc hiểu!"

        reading_area.content = nb_card(
            ft.Column([
                ft.Text(title_text, size=24, weight=ft.FontWeight.W_900, color=title_color),
                ft.Container(height=8),
                ft.Text(msg_text, size=14, color=TEXT_DARK, text_align=ft.TextAlign.CENTER),
                ft.Container(height=24),
                nb_button("Quay lại danh sách", on_click=lambda e: on_exit(), bgcolor=TEXT_DARK, color=TEXT_WHITE)
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            padding=48
        )
        reading_area.update()

    reading_area.content = build_reading_view(
        lesson_dict,
        on_complete=on_reading_complete,
        on_speak=lambda text: speak_text(page, text),
        page=page
    )

    return session_view


# ══════════════════════════════════════════════════════════════════════════════
# ── SIDEBAR ───────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
# ── MAIN APP ──────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

def main(page: ft.Page) -> None:
    page.title      = "Vocab1337"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.bgcolor    = BG_PAGE
    page.padding    = 0
    page.data = {"audio_player": PageAudioPlayer(page)}
    # Roboto is bundled with the Flet client and works without a font CDN.
    page.theme = ft.Theme(font_family="Roboto")

    # Cửa sổ mặc định
    page.window.width      = 1240
    page.window.height     = 780
    page.window.min_width  = 960
    page.window.min_height = 620

    # Khởi tạo cấu hình & hệ thống logging tập trung
    settings = load_settings()
    log_level = settings.get("log_level", "INFO")
    setup_logging(log_level)
    install_exception_hooks()
    logger.info("=== Ứng dụng Vocab1337 đang khởi động ===")

    # Chạy chẩn đoán hệ thống ngầm và dọn dẹp log cũ
    def _bg_init():
        try:
            log_system_diagnostics()
            clean_old_logs(days=14)
        except Exception as e:
            logger.warning(f"Lỗi khi thực thi chẩn đoán ban đầu: {e}")

    threading.Thread(target=_bg_init, daemon=True, name="InitDiagnostics").start()

    # Khởi tạo DB SQLite & kiểm tra suy giảm điểm mỗi ngày không học (-0.5 điểm/ngày)
    init_db()
    try:
        decay_res = apply_daily_score_decay()
        if decay_res.get("decayed_count", 0) > 0:
            logger.info(f"[SRS Decay] Đã áp dụng giảm điểm cho {decay_res['decayed_count']} từ vựng chưa ôn tập.")
    except Exception as e:
        logger.error(f"[SRS Decay Error] {e}", exc_info=True)

    # Trạng thái điều hướng chính
    state = {"route": "dashboard"}
    nav_state = {"locked": False}

    def set_nav_locked(locked: bool):
        nav_state["locked"] = locked

    content_area = ft.Container(
        expand=True,
        padding=pad(all_=20 if page.width and page.width < 1000 else 36),
        bgcolor=BG_PAGE,
    )

    layout = ft.Row(spacing=0, expand=True)

    def handle_open_logs():
        show_log_viewer_dialog(page)

    def make_sidebar(route):
        return build_sidebar(route, navigate, on_open_logs=handle_open_logs,
                             compact=bool(page.width and page.width < 1000))

    def on_resize(e=None):
        layout.controls[0] = make_sidebar(state["route"])
        content_area.padding = pad(all_=20 if page.width and page.width < 1000 else 36)
        page.update()

    page.on_resize = on_resize

    # Trả về màn hình tương ứng
    def navigate(route: str) -> None:
        page.on_keyboard_event = None
        if nav_state["locked"]:
            page.show_dialog(ft.SnackBar(
                ft.Text("🔒 AI đang tạo bài học. Vui lòng đợi hoàn thành!"),
                bgcolor="#991b1b"
            ))
            page.update()
            return

        logger.info(f"Chuyển màn hình: {route}")
        state["route"] = route
        layout.controls[0] = make_sidebar(route)

        if route == "dashboard":
            try:
                apply_daily_score_decay()
            except Exception:
                pass
            content_area.content = build_dashboard(page, navigate, show_vocab_list_dialog)
        elif route == "lessons":
            content_area.content = build_lessons_screen(page, start_active_session, open_lesson_editor)
        elif route == "random":
            content_area.content = build_random_screen(page, start_active_session)
        elif route == "create":
            content_area.content = build_create_screen(
                page,
                on_success=lambda: navigate("lessons"),
                on_lock_nav=set_nav_locked
            )
        elif route == "settings":
            content_area.content = build_settings_screen(page)
        
        page.update()

    # Hàm bắt đầu session học tập (Flashcard / Reading)
    def start_active_session(session_type: str, item_id: int, shuffle: bool = True):
        page.on_keyboard_event = None
        logger.info(f"Bắt đầu phiên học: {session_type} (id={item_id}, shuffle={shuffle})")
        # Tắt sidebar tạm thời khi đang học để tối ưu không gian hiển thị
        if session_type == "flashcard":
            content_area.content = build_flashcard_session(page, item_id, on_exit=lambda: navigate("lessons"), shuffle=shuffle)
        elif session_type == "reading":
            content_area.content = build_reading_session(page, item_id, on_exit=lambda: navigate("lessons"), shuffle=shuffle)
        elif session_type == "random_flashcard":
            content_area.content = build_random_flashcard_session(page, item_id, on_exit=lambda: navigate("random"))
        page.update()

    def open_lesson_editor(lesson_id: int):
        """Mở màn hình chỉnh sửa bài học. Sidebar giữ nguyên tab 'lessons' active."""
        page.on_keyboard_event = None
        logger.info(f"Mở trình chỉnh sửa bài học: id={lesson_id}")
        content_area.content = build_lesson_editor(
            page, lesson_id,
            on_back=lambda: navigate("lessons")
        )
        page.update()

    # Mặc định mở dashboard
    layout.controls = [
        make_sidebar("dashboard"),
        ft.Container(width=3, bgcolor=TEXT_DARK),
        content_area,
    ]
    
    content_area.content = build_dashboard(page, navigate, show_vocab_list_dialog)
    
    page.add(layout)


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    ft.app(target=main)
