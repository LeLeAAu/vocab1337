"""
components/reading.py — Vocab1337
Hiển thị cốt truyện (story_context) và danh sách câu hỏi tương ứng.
Tự động đổi theme vàng kim cho Master Challenge ở câu cuối cùng.
Đảm bảo luôn hiển thị cốt truyện và câu hỏi rõ ràng, không bị lỗi layout.
"""

import flet as ft
from .theme import (TEXT_DARK, TEXT_GRAY, TEXT_WHITE, BG_WHITE, CLR_GREEN, CLR_RED,
                    CLR_BLUE, CLR_YELLOW, SHADOW_SM, SHADOW_MD, SHADOW_LG,
                    mk_border, pad, nb_card, close_dialog, nb_button as themed_button)
from logger import get_logger
from .quiz_renderer import build_quiz_view

logger = get_logger("reading")


MASTER_BG = "#fefce8"
MASTER_BORDER = "#ca8a04"
MASTER_SHADOW = "#854d0e"


def nb_button(label, icon="", on_click=None, bgcolor=TEXT_DARK, color=BG_WHITE):
    return themed_button(label, icon, on_click, bgcolor, color, h_padding=20)


def build_reading_view(
    lesson: dict,
    on_complete: callable = None,
    on_speak: callable = None,
    page: ft.Page = None,
) -> ft.Control:
    """
    Tạo màn hình Đọc hiểu gồm có cốt truyện (Story) và hiển thị các câu hỏi tuần tự.
    """
    title = lesson.get("title", "Bài học")
    global_story = lesson.get("story_context", "") or ""
    questions = lesson.get("questions", [])

    state = {"current_idx": 0, "current_passed": False, "correct_count": 0}

    # Không dùng expand=True để tránh collapse khi nằm trong Scrollable parent
    main_layout = ft.Column(spacing=20)

    # 1. Tiêu đề và Tiến trình
    progress_txt = ft.Text("TIẾN TRÌNH", size=11, weight=ft.FontWeight.W_700, color=TEXT_GRAY, style=ft.TextStyle(letter_spacing=1.5))
    progress_val = ft.Text(f"1 / {len(questions)}" if questions else "0 / 0", size=32, weight=ft.FontWeight.W_900, color=TEXT_DARK)

    phase_badge = ft.Container(
        content=ft.Text("BÀI ĐỌC HIỂU", size=11, weight=ft.FontWeight.W_800, color=TEXT_WHITE),
        bgcolor=TEXT_DARK,
        border=mk_border(2, TEXT_DARK),
        padding=pad(h=12, v=6),
    )

    def open_instant_ai_challenge(e=None):
        pg = page or (e.page if e and hasattr(e, "page") and e.page else None) or (e.control.page if e and hasattr(e, "control") and e.control else None) or main_layout.page
        if not pg:
            return

        vocab_words = []
        raw_vocab = lesson.get("vocab", [])
        if isinstance(raw_vocab, list):
            for v in raw_vocab:
                if isinstance(v, dict) and v.get("word"):
                    vocab_words.append(v["word"])
                elif isinstance(v, str):
                    vocab_words.append(v)

        loading_col = ft.Column([
            ft.ProgressRing(color=TEXT_DARK, width=32, height=32),
            ft.Container(height=12),
            ft.Text("Đang kết nối AI sinh câu hỏi thử thách...", size=14, weight=ft.FontWeight.W_700, color=TEXT_DARK),
            ft.Text("Câu hỏi sẽ bám sát ngữ cảnh cốt truyện hiện tại.", size=12, color=TEXT_GRAY, italic=True),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=0)

        modal_body = ft.Container(content=loading_col, padding=20, alignment=ft.Alignment(0, 0))

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Row([
                    ft.Text("⚡", size=20),
                    ft.Text("THỬ THÁCH AI NGẪU NHIÊN", size=16, weight=ft.FontWeight.W_900, color=TEXT_DARK),
                ], spacing=6),
                ft.IconButton(ft.Icons.CLOSE, on_click=lambda e: close_dialog(dlg), icon_color=TEXT_DARK),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            content=ft.Container(content=modal_body, width=580),
        )
        pg.show_dialog(dlg)

        def worker():
            try:
                from ai_generator import generate_instant_question
                new_q = generate_instant_question(global_story, vocab_words=vocab_words)

                def on_challenge_answer(passed, exp):
                    pass

                quiz_ctrl = build_quiz_view(new_q, on_answer=on_challenge_answer, on_speak=on_speak)
                modal_body.content = quiz_ctrl
            except Exception as err:
                logger.error("Lỗi khi sinh thử thách AI trong màn hình Reading: %s", err, exc_info=True)
                modal_body.content = ft.Column([
                    ft.Text("⚠ Không thể sinh thử thách AI", size=15, weight=ft.FontWeight.W_900, color="#991b1b"),
                    ft.Container(height=6),
                    ft.Text(f"Chi tiết: {err}", size=13, color=TEXT_DARK),
                    ft.Container(height=10),
                    ft.Text("Gợi ý: Kiểm tra Ollama service hoặc API key trong Cài đặt.", size=12, color=TEXT_GRAY),
                ], spacing=0)
            try:
                modal_body.update()
                pg.update()
            except Exception:
                pass

        import threading
        threading.Thread(target=worker, daemon=True).start()

    btn_instant_challenge = nb_button("⚡ Thử thách AI", bgcolor=CLR_YELLOW, color=TEXT_DARK, on_click=open_instant_ai_challenge)

    header_section = ft.Row(
        [
            ft.Column([progress_txt, progress_val], spacing=2),
            ft.Container(expand=True),
            btn_instant_challenge,
            ft.Container(width=10),
            phase_badge,
        ],
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )
    main_layout.controls.append(header_section)

    # 2. Cốt truyện / Ngữ cảnh (Story Box)
    story_header_title = ft.Text("📖 ĐOẠN VĂN CỐT TRUYỆN (STORY PASSAGE)", size=11, weight=ft.FontWeight.W_900, color=TEXT_DARK, style=ft.TextStyle(letter_spacing=1.5))
    story_txt = ft.Text(global_story, size=15, italic=True, weight=ft.FontWeight.W_500, color=TEXT_DARK, selectable=True)
    quote_icon = ft.Text("❝", size=26, weight=ft.FontWeight.W_900, color=TEXT_GRAY)

    speak_story_btn = ft.IconButton(
        ft.Icons.VOLUME_UP_ROUNDED,
        icon_size=20,
        icon_color=TEXT_DARK,
        tooltip="Nghe toàn bộ đoạn văn",
        on_click=lambda e: on_speak(story_txt.value) if on_speak else None,
        visible=bool(on_speak)
    )

    story_box = ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Row([quote_icon, story_header_title], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                speak_story_btn
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Container(height=4),
            story_txt,
        ], spacing=4),
        bgcolor=BG_WHITE,
        border=ft.Border(left=ft.BorderSide(6, TEXT_DARK), right=ft.BorderSide(2, "#d1d5db"), top=ft.BorderSide(2, "#d1d5db"), bottom=ft.BorderSide(2, "#d1d5db")),
        shadow=SHADOW_SM,
        padding=20,
        visible=True,
    )
    main_layout.controls.append(story_box)

    # 3. Chỗ hiển thị câu hỏi hiện tại
    quiz_container = ft.Container()
    main_layout.controls.append(quiz_container)

    # 4. Thanh điều hướng câu hỏi
    nav_container = ft.Container(visible=False)
    main_layout.controls.append(nav_container)

    def load_question(idx, first_load=False):
        if idx >= len(questions):
            if on_complete:
                try:
                    on_complete(state["correct_count"], len(questions))
                except TypeError:
                    on_complete()
            return

        state["current_idx"] = idx
        state["current_passed"] = False

        q_data = questions[idx] if isinstance(questions[idx], dict) else {}
        inst = str(q_data.get("instruction", ""))
        is_master = (
            inst.strip() == "Final Evaluation - Master Challenge"
            or "master" in inst.lower()
            or "final evaluation" in inst.lower()
            or bool(q_data.get("is_master"))
        )

        # Cập nhật UI tiến trình & badge
        progress_val.value = f"{idx + 1} / {len(questions)}"
        if is_master:
            phase_badge.content.value = "👑 MASTER CHALLENGE"
            phase_badge.bgcolor = MASTER_BORDER
            phase_badge.border = mk_border(2, MASTER_SHADOW)
            story_box.bgcolor = MASTER_BG
            story_box.border = ft.Border(left=ft.BorderSide(6, MASTER_BORDER), right=ft.BorderSide(2, MASTER_BORDER), top=ft.BorderSide(2, MASTER_BORDER), bottom=ft.BorderSide(2, MASTER_BORDER))
            quote_icon.color = MASTER_BORDER
            story_header_title.color = MASTER_BORDER
            story_header_title.value = "👑 NGỮ CẢNH TỔNG HỢP (SYNTHESIS DOSSIER)"
        else:
            phase_badge.content.value = "BÀI ĐỌC HIỂU"
            phase_badge.bgcolor = TEXT_DARK
            phase_badge.border = mk_border(2, TEXT_DARK)
            story_box.bgcolor = BG_WHITE
            story_box.border = ft.Border(left=ft.BorderSide(6, TEXT_DARK), right=ft.BorderSide(2, "#d1d5db"), top=ft.BorderSide(2, "#d1d5db"), bottom=ft.BorderSide(2, "#d1d5db"))
            quote_icon.color = TEXT_GRAY
            story_header_title.color = TEXT_DARK
            story_header_title.value = "📖 ĐOẠN VĂN CỐT TRUYỆN (STORY PASSAGE)"

        # Ngữ cảnh theo từng câu
        q_context = q_data.get("story") or q_data.get("context") or q_data.get("passage") or q_data.get("contextual_text") or global_story
        story_txt.value = q_context or "Bài học không có đoạn văn ngữ cảnh."
        story_box.visible = True

        # Đổi text nút khi đến câu cuối cùng
        if idx == len(questions) - 1:
            next_btn.content.controls[0].value = "✓"
            next_btn.content.controls[1].value = "HOÀN THÀNH"
            next_btn.bgcolor = "#166534"
        else:
            next_btn.content.controls[0].value = "➔"
            next_btn.content.controls[1].value = "TIẾP THEO"
            next_btn.bgcolor = TEXT_DARK

        if not first_load:
            try:
                progress_val.update()
                phase_badge.update()
                story_txt.update()
                story_box.update()
            except Exception:
                pass

        def on_answer_callback(passed: bool, exp: str):
            state["current_passed"] = passed
            if passed:
                state["correct_count"] += 1
            nav_container.visible = True
            try:
                nav_container.update()
            except Exception:
                pass

        quiz_container.content = build_quiz_view(q_data, on_answer=on_answer_callback, on_speak=on_speak)
        if not first_load:
            try:
                quiz_container.update()
                nav_container.visible = False
                nav_container.update()
            except Exception:
                pass
        else:
            nav_container.visible = False

    def go_next(e):
        load_question(state["current_idx"] + 1)

    next_btn = nb_button("Tiếp theo", icon="➔", on_click=go_next)
    nav_container.content = ft.Row([next_btn], alignment=ft.MainAxisAlignment.END)

    if questions:
        load_question(0, first_load=True)
    else:
        quiz_container.content = ft.Text("Bài học này chưa có câu hỏi nào.", size=14, color=TEXT_GRAY)

    return main_layout
