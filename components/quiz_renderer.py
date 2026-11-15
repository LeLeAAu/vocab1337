"""
components/quiz_renderer.py — Vocab1337
Renderer hiển thị 10 loại câu hỏi và Final Evaluation (Master Challenge).
Tương thích Flet 0.85 và phong cách Neubrutalism sắc nét.
Đảm bảo luôn hiển thị đầy đủ đáp án và ngữ cảnh cho mọi dạng câu hỏi.
"""

import re
import random
import string
import flet as ft
from .theme import (TEXT_DARK, TEXT_GRAY, TEXT_WHITE, BG_WHITE, CLR_GREEN, CLR_RED,
                    CLR_BLUE, CLR_YELLOW, SHADOW_SM, SHADOW_MD, SHADOW_LG,
                    mk_border, pad, nb_card, nb_button as themed_button)
from logger import get_logger

logger = get_logger("quiz")

# ── Palette & Helpers ──────────────────────────────────────────────────────────

# Master Challenge Palette
MASTER_BG = "#fefce8"
MASTER_BORDER = "#ca8a04"
MASTER_SHADOW = "#854d0e"
MASTER_TEXT = "#713f12"


def nb_button(label, icon="", on_click=None, bgcolor=BG_WHITE, color=TEXT_DARK, shadow=SHADOW_SM, width=None):
    return themed_button(label, icon, on_click, bgcolor, color, width, text_size=13, h_padding=20, shadow=shadow)


def _normalize_correct_idx(val, options_count: int = 4) -> int:
    """Chuẩn hóa đáp án thành chỉ mục số nguyên (0, 1, 2, 3...) an toàn tuyệt đối."""
    if isinstance(val, int):
        return val if 0 <= val < max(1, options_count) else 0
    if isinstance(val, (list, tuple)):
        val = val[0] if val else 0
        return _normalize_correct_idx(val, options_count)
    if isinstance(val, str):
        s = val.strip().lower()
        letter_map = {"a": 0, "b": 1, "c": 2, "d": 3, "e": 4, "f": 5}
        if s in letter_map:
            return letter_map[s]
        for k, idx in letter_map.items():
            if f"option {k}" in s or f"choice {k}" in s or f"({k})" in s:
                return idx
        import re
        digits = re.sub(r"[^\d]", "", s)
        if digits:
            try:
                idx = int(digits)
                if 1 <= idx <= options_count and idx == options_count and options_count > 1:
                    idx = idx - 1
                return idx if 0 <= idx < max(1, options_count) else 0
            except Exception:
                pass
    return 0


def _normalize_correct_indices(val, options_count: int = 4) -> set[int]:
    """Chuẩn hóa danh sách đáp án nhiều lựa chọn thành set các chỉ mục số nguyên."""
    if isinstance(val, int):
        return {val} if 0 <= val < max(1, options_count) else {0}
    if isinstance(val, str):
        parts = [p.strip() for p in val.replace(";", ",").split(",") if p.strip()]
        res = {_normalize_correct_idx(p, options_count) for p in parts}
        return res if res else {0}
    if isinstance(val, (list, tuple, set)):
        res = {_normalize_correct_idx(item, options_count) for item in val}
        return res if res else {0}
    return {0}


# ══════════════════════════════════════════════════════════════════════════════
# ── MAIN DISPATCHER ───────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

def build_quiz_view(
    question: dict,
    on_answer: callable = None,
    on_speak: callable = None,
) -> ft.Control:
    """
    Tạo Control hiển thị câu hỏi và nút nộp bài.
    Khi nộp bài, sẽ gọi `on_answer(passed: bool, explanation: str)`.
    Tự động áp dụng Golden Master Styling nếu là Final Evaluation Challenge.
    """
    raw_type = str(question.get("type", "single")).lower().strip()
    if raw_type in ["multiple_choice_single", "mcq_single", "single_choice", "contextual_inference", "causal_reasoning", "semantic_distinction"]:
        q_type = "single"
    elif raw_type in ["multiple_choice_multiple", "multi_select", "multiple_select"]:
        q_type = "multiple"
    else:
        q_type = raw_type

    inst = str(question.get("instruction", "Thử thách đọc hiểu"))
    is_master = (
        inst.strip() == "Final Evaluation - Master Challenge"
        or "master" in inst.lower()
        or "final evaluation" in inst.lower()
        or question.get("is_master", False)
    )

    # Header hiển thị loại câu hỏi
    if is_master:
        header = ft.Container(
            content=ft.Row([
                ft.Text("👑", size=13),
                ft.Text("FINAL EVALUATION — MASTER CHALLENGE", size=11, weight=ft.FontWeight.W_900, color=TEXT_WHITE),
            ], spacing=6),
            bgcolor=MASTER_BORDER,
            border=mk_border(2, MASTER_SHADOW),
            padding=pad(h=14, v=7),
            shadow=ft.BoxShadow(offset=ft.Offset(3, 3), blur_radius=0, color=MASTER_SHADOW),
        )
    else:
        header = ft.Container(
            content=ft.Text(inst.upper(), size=11, weight=ft.FontWeight.W_800, color=TEXT_DARK),
            bgcolor=CLR_BLUE,
            border=mk_border(2, TEXT_DARK),
            padding=pad(h=12, v=6),
            shadow=SHADOW_SM,
        )

    # Câu hỏi
    q_str = question.get("question", question.get("q", "Chọn câu trả lời đúng:"))
    q_text = ft.Text(
        q_str,
        size=17,
        weight=ft.FontWeight.W_800,
        color=MASTER_TEXT if is_master else TEXT_DARK,
        expand=True,
    )

    # Question Header Row (kèm nút loa phát âm nếu có)
    if on_speak:
        speak_btn = ft.IconButton(
            ft.Icons.VOLUME_UP_ROUNDED,
            icon_size=20,
            icon_color=MASTER_TEXT if is_master else TEXT_DARK,
            tooltip="Nghe câu hỏi",
            on_click=lambda e: on_speak(q_str),
        )
        q_header_row = ft.Row([q_text, speak_btn], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.START)
    else:
        q_header_row = ft.Row([q_text], alignment=ft.MainAxisAlignment.START)

    # Nơi chứa các phương án
    workspace = ft.Column(spacing=10)

    # State lưu trữ câu trả lời của user
    user_state = {
        "selected": None,
        "checked": set(),
        "pairs": {},
        "matching_selected": None,
        "text": "",
        "submitted": False
    }

    submit_fn = None

    # Lấy danh sách options an toàn
    raw_options = question.get("options", [])
    if isinstance(raw_options, dict):
        options = [f"{k}: {v}" for k, v in raw_options.items()]
    elif isinstance(raw_options, list):
        options = []
        for opt in raw_options:
            if isinstance(opt, dict):
                options.append(opt.get("text") or opt.get("label") or str(opt))
            else:
                options.append(str(opt))
    else:
        options = []

    # 1. MATCHING (Nối cặp có distractors)
    if q_type == "matching":
        pairs = question.get("pairs", [])
        distractors = question.get("distractors", [])

        # Kiểm tra nếu pairs có dữ liệu
        left_items = []
        right_items = []
        pair_solution = {}

        if isinstance(pairs, dict):
            for k, v in pairs.items():
                if k and v:
                    left_items.append(str(k))
                    right_items.append(str(v))
                    pair_solution[str(k)] = str(v)
        elif isinstance(pairs, list) and pairs:
            for p in pairs:
                if isinstance(p, dict):
                    l_val = p.get("left") or p.get("term") or p.get("word") or p.get("q")
                    r_val = p.get("right") or p.get("definition") or p.get("meaning") or p.get("ans")
                    if l_val is not None and r_val is not None:
                        l_s, r_s = str(l_val), str(r_val)
                        left_items.append(l_s)
                        right_items.append(r_s)
                        pair_solution[l_s] = r_s

        if left_items and right_items:
            for d in distractors:
                if str(d) not in right_items:
                    right_items.append(str(d))
            shuffled_right = list(dict.fromkeys(right_items))
            random.shuffle(shuffled_right)
            right_items = shuffled_right

            left_cols = ft.Column(spacing=8, expand=True)
            right_cols = ft.Column(spacing=8, expand=True)
            left_buttons = []
            right_buttons = []

            def update_matching_ui():
                selected_left = user_state["matching_selected"]
                for i, btn in enumerate(left_buttons):
                    if i == selected_left:
                        btn.bgcolor = CLR_BLUE
                    elif i in user_state["pairs"]:
                        btn.bgcolor = "#e5e7eb"
                    else:
                        btn.bgcolor = BG_WHITE

                    txt = left_items[i]
                    if i in user_state["pairs"]:
                        matched_val = user_state["pairs"][i]
                        txt = f"{left_items[i]} ➔ {matched_val}"
                    btn.content.controls[0].value = txt
                    btn.update()

                for i, btn in enumerate(right_buttons):
                    r_text = right_items[i]
                    matched_lidx = None
                    for lidx, r_val in user_state["pairs"].items():
                        if r_val == r_text:
                            matched_lidx = lidx
                            break

                    if selected_left is not None and matched_lidx == selected_left:
                        btn.bgcolor = CLR_BLUE
                    elif matched_lidx is not None:
                        btn.bgcolor = "#e5e7eb"
                    else:
                        btn.bgcolor = BG_WHITE
                    btn.update()

            def click_left(idx):
                if user_state.get("submitted"): return
                if user_state["matching_selected"] == idx:
                    user_state["matching_selected"] = None
                else:
                    user_state["matching_selected"] = idx
                update_matching_ui()

            def click_right(ridx, right_text):
                if user_state.get("submitted"): return
                lidx = user_state["matching_selected"]
                if lidx is None:
                    return

                for existing_lidx, existing_r in list(user_state["pairs"].items()):
                    if existing_r == right_text:
                        del user_state["pairs"][existing_lidx]

                user_state["pairs"][lidx] = right_text
                user_state["matching_selected"] = None
                update_matching_ui()

            for idx, text in enumerate(left_items):
                btn = ft.Container(
                    content=ft.Row([ft.Text(text, size=13, weight=ft.FontWeight.W_700, color=TEXT_DARK, expand=True)]),
                    bgcolor=BG_WHITE, border=mk_border(2, TEXT_DARK), padding=pad(h=12, v=10), shadow=SHADOW_SM,
                    on_click=lambda e, idx=idx: click_left(idx)
                )
                left_buttons.append(btn)
                left_cols.controls.append(btn)

            for idx, text in enumerate(right_items):
                btn = ft.Container(
                    content=ft.Row([ft.Text(text, size=13, weight=ft.FontWeight.W_700, color=TEXT_DARK, expand=True)]),
                    bgcolor=BG_WHITE, border=mk_border(2, TEXT_DARK), padding=pad(h=12, v=10), shadow=SHADOW_SM,
                    on_click=lambda e, idx=idx, text=text: click_right(idx, text)
                )
                right_buttons.append(btn)
                right_cols.controls.append(btn)

            workspace.controls.append(ft.Row([left_cols, right_cols], spacing=16))

            def submit_matching():
                ans = user_state["pairs"]
                if len(ans) < len(left_items):
                    return None, "Hãy hoàn thành tất cả các cặp nối."

                is_correct = True
                for lidx, left_val in enumerate(left_items):
                    correct_right = pair_solution.get(left_val)
                    user_right = ans.get(lidx)

                    if user_right == correct_right:
                        left_buttons[lidx].bgcolor = CLR_GREEN
                    else:
                        left_buttons[lidx].bgcolor = CLR_RED
                        is_correct = False
                    left_buttons[lidx].content.controls[0].value = f"{left_val} ➔ {correct_right}"
                    left_buttons[lidx].update()

                for btn in right_buttons:
                    btn.bgcolor = "#e5e7eb"
                    btn.update()

                return is_correct, question.get("explanation", question.get("explain", ""))

            submit_fn = submit_matching

        else:
            # Fallback nếu matching không có pairs nhưng có options
            q_type = "single"

    # 2. MULTIPLE CHOICE (Checkboxes)
    if q_type == "multiple":
        checkbox_items = []
        text_refs = []

        def toggle_multiple(idx):
            if user_state.get("submitted"): return
            if idx in user_state["checked"]:
                user_state["checked"].remove(idx)
            else:
                user_state["checked"].add(idx)

            for i, btn in enumerate(checkbox_items):
                active = i in user_state["checked"]
                btn.bgcolor = TEXT_DARK if active else BG_WHITE
                text_refs[i].color = BG_WHITE if active else TEXT_DARK
                text_refs[i].value = f"☑  {options[i]}" if active else f"☐  {options[i]}"
                btn.update()

        for idx, opt in enumerate(options):
            txt_ctrl = ft.Text(f"☐  {opt}", size=14, weight=ft.FontWeight.W_700, color=TEXT_DARK, expand=True)
            text_refs.append(txt_ctrl)
            btn = ft.Container(
                content=ft.Row([txt_ctrl]),
                bgcolor=BG_WHITE,
                border=mk_border(2, TEXT_DARK),
                shadow=SHADOW_SM,
                padding=pad(h=16, v=12),
                on_click=lambda e, idx=idx: toggle_multiple(idx),
                ink=True,
            )
            checkbox_items.append(btn)
            workspace.controls.append(btn)

        def submit_multiple():
            sel_set = user_state["checked"]
            if not sel_set:
                return None, "Hãy chọn ít nhất một phương án."
            correct_set = _normalize_correct_indices(question.get("correct_indices", question.get("correct_answers", question.get("answers", question.get("correct", [])))), len(options))
            is_correct = (sel_set == correct_set)

            for i, btn in enumerate(checkbox_items):
                if i in correct_set:
                    btn.bgcolor = CLR_GREEN
                    text_refs[i].value = f"✓  {options[i]}"
                    text_refs[i].color = TEXT_DARK
                elif i in sel_set and i not in correct_set:
                    btn.bgcolor = CLR_RED
                    text_refs[i].value = f"✗  {options[i]}"
                    text_refs[i].color = TEXT_DARK
                btn.update()
            return is_correct, question.get("explanation", question.get("explain", ""))

        submit_fn = submit_multiple

    # 3. FILL BLANK
    elif q_type == "fill_blank":
        option_buttons = []
        text_refs = []

        context_lbl = ft.Text(question.get("contextual_text", ""), size=15, italic=True, color=TEXT_DARK)
        if question.get("contextual_text"):
            workspace.controls.append(context_lbl)

        def select_blank(idx):
            if user_state.get("submitted"): return
            user_state["selected"] = idx
            for i, btn in enumerate(option_buttons):
                active = (i == idx)
                btn.bgcolor = TEXT_DARK if active else BG_WHITE
                text_refs[i].color = BG_WHITE if active else TEXT_DARK
                btn.update()

        for idx, opt in enumerate(options):
            txt_ctrl = ft.Text(opt, size=14, weight=ft.FontWeight.W_700, color=TEXT_DARK, expand=True)
            text_refs.append(txt_ctrl)
            btn = ft.Container(
                content=ft.Row([txt_ctrl]),
                bgcolor=BG_WHITE,
                border=mk_border(2, TEXT_DARK),
                shadow=SHADOW_SM,
                padding=pad(h=16, v=12),
                on_click=lambda e, idx=idx: select_blank(idx),
                ink=True,
            )
            option_buttons.append(btn)
            workspace.controls.append(btn)

        def submit_blank():
            sel = user_state["selected"]
            if sel is None:
                return None, "Vui lòng chọn từ điền vào chỗ trống."
            correct = _normalize_correct_idx(question.get("correct_index", question.get("correct_answer", question.get("answer", question.get("correct", 0)))), len(options))
            is_correct = (sel == correct)
            for i, btn in enumerate(option_buttons):
                if i == correct:
                    btn.bgcolor = CLR_GREEN
                    text_refs[i].color = TEXT_DARK
                elif i == sel and not is_correct:
                    btn.bgcolor = CLR_RED
                    text_refs[i].color = TEXT_DARK
                btn.update()
            return is_correct, question.get("explanation", question.get("explain", ""))

        submit_fn = submit_blank

    # 4. ERROR IDENTIFICATION & INCORRECT USAGE DETECTION
    elif q_type in ["error_identification", "incorrect_usage_detection"]:
        context = question.get("contextual_text", question.get("context", ""))
        if context:
            workspace.controls.append(
                ft.Container(
                    content=ft.Text(f'"{context}"', size=15, weight=ft.FontWeight.W_600, color=TEXT_DARK, italic=True),
                    bgcolor="#f3f4f6",
                    padding=12,
                    border=mk_border(1, "#d1d5db"),
                )
            )

        option_buttons = []
        text_refs = []

        def select_error(idx):
            if user_state.get("submitted"): return
            user_state["selected"] = idx
            for i, btn in enumerate(option_buttons):
                active = (i == idx)
                btn.bgcolor = TEXT_DARK if active else BG_WHITE
                text_refs[i].color = BG_WHITE if active else TEXT_DARK
                btn.update()

        disp_options = options if options else ["Phương án A", "Phương án B", "Phương án C", "Phương án D"]

        for idx, opt in enumerate(disp_options):
            txt_ctrl = ft.Text(opt, size=14, weight=ft.FontWeight.W_700, color=TEXT_DARK, expand=True)
            text_refs.append(txt_ctrl)
            btn = ft.Container(
                content=ft.Row([txt_ctrl]),
                bgcolor=BG_WHITE, border=mk_border(2, TEXT_DARK), shadow=SHADOW_SM, padding=pad(h=16, v=12),
                on_click=lambda e, idx=idx: select_error(idx),
                ink=True,
            )
            option_buttons.append(btn)
            workspace.controls.append(btn)

        def submit_error():
            sel = user_state["selected"]
            if sel is None:
                return None, "Vui lòng chọn phương án."
            correct = _normalize_correct_idx(question.get("correct_index", question.get("correct_answer", question.get("answer", question.get("correct", 0)))), len(disp_options))
            is_correct = (sel == correct)
            for i, btn in enumerate(option_buttons):
                if i == correct:
                    btn.bgcolor = CLR_GREEN
                    text_refs[i].color = TEXT_DARK
                elif i == sel and not is_correct:
                    btn.bgcolor = CLR_RED
                    text_refs[i].color = TEXT_DARK
                btn.update()
            return is_correct, question.get("explanation", question.get("explain", ""))

        submit_fn = submit_error

    # 5. TRUE / FALSE
    elif q_type == "true_false":
        statement = question.get("statement", question.get("q", ""))
        workspace.controls.append(ft.Text(f"Nhận định: \"{statement}\"", size=15, weight=ft.FontWeight.W_700, color=TEXT_DARK))

        txt_t = ft.Text("ĐÚNG (TRUE)", weight=ft.FontWeight.W_900, color=TEXT_DARK)
        txt_f = ft.Text("SAI (FALSE)", weight=ft.FontWeight.W_900, color=TEXT_DARK)

        btn_t = ft.Container(content=ft.Row([txt_t]), bgcolor=BG_WHITE, border=mk_border(2, TEXT_DARK), padding=pad(h=16, v=12), shadow=SHADOW_SM, ink=True)
        btn_f = ft.Container(content=ft.Row([txt_f]), bgcolor=BG_WHITE, border=mk_border(2, TEXT_DARK), padding=pad(h=16, v=12), shadow=SHADOW_SM, ink=True)

        def select_tf(val: bool):
            if user_state.get("submitted"): return
            user_state["selected"] = val
            btn_t.bgcolor = TEXT_DARK if val is True else BG_WHITE
            txt_t.color = BG_WHITE if val is True else TEXT_DARK
            btn_f.bgcolor = TEXT_DARK if val is False else BG_WHITE
            txt_f.color = BG_WHITE if val is False else TEXT_DARK
            btn_t.update()
            btn_f.update()

        btn_t.on_click = lambda e: select_tf(True)
        btn_f.on_click = lambda e: select_tf(False)
        workspace.controls.append(ft.Row([btn_t, btn_f], spacing=12))

        def submit_tf():
            sel = user_state["selected"]
            if sel is None:
                return None, "Hãy chọn Đúng hoặc Sai."
            raw_it = question.get("is_true", question.get("answer", question.get("correct_answer", question.get("correct", True))))
            if isinstance(raw_it, str):
                is_true = raw_it.strip().lower() in ["true", "1", "yes", "t", "đúng"]
            else:
                is_true = bool(raw_it)
            is_correct = (sel == is_true)
            if is_true:
                btn_t.bgcolor = CLR_GREEN
                txt_t.color = TEXT_DARK
                btn_f.bgcolor = CLR_RED if sel is False else BG_WHITE
            else:
                btn_f.bgcolor = CLR_GREEN
                txt_f.color = TEXT_DARK
                btn_t.bgcolor = CLR_RED if sel is True else BG_WHITE
            btn_t.update()
            btn_f.update()
            return is_correct, question.get("explanation", question.get("explain", ""))

        submit_fn = submit_tf

    # 6. TYPING EXACT
    elif q_type in ["typing_exact", "typing", "fill_text"]:
        context = question.get("contextual_text", question.get("context", ""))
        if context:
            workspace.controls.append(
                ft.Container(
                    content=ft.Text(f'"{context}"', size=15, weight=ft.FontWeight.W_600, color=TEXT_DARK, italic=True),
                    bgcolor="#f3f4f6",
                    padding=12,
                    border=mk_border(1, "#d1d5db"),
                )
            )

        inp_field = ft.TextField(
            hint_text="Gõ câu trả lời của bạn...",
            border_color=TEXT_DARK,
            border_width=2,
            border_radius=0,
            text_style=ft.TextStyle(size=16, weight=ft.FontWeight.W_700, color=TEXT_DARK),
        )
        workspace.controls.append(inp_field)

        def submit_typing():
            val = (inp_field.value or "").strip().lower()
            if not val:
                return None, "Vui lòng nhập câu trả lời."
            expected_text = str(question.get("correct_text", question.get("correct_answer", question.get("answer", question.get("correct", ""))))).strip().lower()
            accepted = [str(t).strip().lower() for t in question.get("accepted_typos", [])]
            is_correct = (val == expected_text or val in accepted)
            if is_correct:
                inp_field.bgcolor = CLR_GREEN
            else:
                inp_field.bgcolor = CLR_RED
            inp_field.disabled = True
            inp_field.update()
            exp = question.get("explanation", question.get("explain", ""))
            if not is_correct and expected_text:
                exp = f"Đáp án chính xác: '{expected_text}'. {exp}".strip()
            return is_correct, exp

        submit_fn = submit_typing

    # 7. UNSCRAMBLE (Sắp xếp từ thành câu hoàn chỉnh)
    elif q_type in ["unscramble", "sentence_unscramble", "word_order"]:
        context = question.get("contextual_text", question.get("context", ""))
        if context:
            workspace.controls.append(
                ft.Container(
                    content=ft.Text(f'"{context}"', size=15, weight=ft.FontWeight.W_600, color=TEXT_DARK, italic=True),
                    bgcolor="#f3f4f6",
                    padding=12,
                    border=mk_border(1, "#d1d5db"),
                )
            )

        # Trích xuất danh sách các mảnh từ (fragments)
        raw_frags = question.get("fragments") or question.get("words") or question.get("tokens") or []
        if isinstance(raw_frags, str):
            raw_frags = [s.strip() for s in re.split(r"[/|]+", raw_frags) if s.strip()]
        fragments = [str(f).strip() for f in raw_frags if str(f).strip()]

        user_state["unscramble_order"] = []  # list các index trong fragments
        user_sentence_row = ft.Row(wrap=True, spacing=8)
        sentence_box = ft.Container(
            content=user_sentence_row,
            bgcolor="#f8fafc",
            border=mk_border(2, TEXT_DARK),
            padding=16,
        )

        pool_row = ft.Row(wrap=True, spacing=8)
        pool_box = ft.Container(
            content=pool_row,
            padding=pad(v=8),
        )

        def update_unscramble_ui():
            user_sentence_row.controls.clear()
            if not user_state["unscramble_order"]:
                user_sentence_row.controls.append(
                    ft.Text("(Bấm vào các từ bên dưới để ghép câu)", size=13, color=TEXT_GRAY, italic=True)
                )
            else:
                for pos, f_idx in enumerate(user_state["unscramble_order"]):
                    word_label = fragments[f_idx]
                    chip = ft.Container(
                        content=ft.Row([
                            ft.Text(word_label, size=14, weight=ft.FontWeight.W_700, color=TEXT_DARK),
                            ft.Text("✕", size=10, weight=ft.FontWeight.W_900, color=CLR_RED if not user_state.get("submitted") else TEXT_GRAY),
                        ], spacing=6, tight=True),
                        bgcolor=BG_WHITE,
                        border=mk_border(2, TEXT_DARK),
                        shadow=SHADOW_SM,
                        padding=pad(h=12, v=8),
                        ink=True,
                        on_click=lambda e, _pos=pos: remove_from_sentence(_pos) if not user_state.get("submitted") else None,
                    )
                    user_sentence_row.controls.append(chip)

            pool_row.controls.clear()
            used_set = set(user_state["unscramble_order"])
            for f_idx, word_label in enumerate(fragments):
                is_used = f_idx in used_set
                pool_btn = ft.Container(
                    content=ft.Text(
                        word_label,
                        size=14,
                        weight=ft.FontWeight.W_700,
                        color=TEXT_GRAY if is_used else TEXT_DARK,
                    ),
                    bgcolor="#e5e7eb" if is_used else BG_WHITE,
                    border=mk_border(2, "#9ca3af" if is_used else TEXT_DARK),
                    shadow=None if is_used else SHADOW_SM,
                    padding=pad(h=12, v=8),
                    ink=not is_used,
                    on_click=lambda e, _idx=f_idx: add_to_sentence(_idx) if (not is_used and not user_state.get("submitted")) else None,
                )
                pool_row.controls.append(pool_btn)

            try:
                sentence_box.update()
                pool_box.update()
            except Exception:
                pass

        def add_to_sentence(f_idx):
            if user_state.get("submitted"): return
            if f_idx not in user_state["unscramble_order"]:
                user_state["unscramble_order"].append(f_idx)
                update_unscramble_ui()

        def remove_from_sentence(pos):
            if user_state.get("submitted"): return
            if 0 <= pos < len(user_state["unscramble_order"]):
                del user_state["unscramble_order"][pos]
                update_unscramble_ui()

        def reset_sentence(e=None):
            if user_state.get("submitted"): return
            user_state["unscramble_order"].clear()
            update_unscramble_ui()

        reset_btn = ft.TextButton("🔄 Làm lại", on_click=reset_sentence)

        workspace.controls.append(
            ft.Row([
                ft.Text("CÂU GHÉP CỦA BẠN:", size=11, weight=ft.FontWeight.W_800, color=TEXT_GRAY, style=ft.TextStyle(letter_spacing=1.5)),
                reset_btn,
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        )
        workspace.controls.append(sentence_box)
        workspace.controls.append(ft.Container(height=6))
        workspace.controls.append(
            ft.Text("KHỐI TỪ VỰNG CÓ SẴN (BẤM ĐỂ CHỌN):", size=11, weight=ft.FontWeight.W_800, color=TEXT_GRAY, style=ft.TextStyle(letter_spacing=1.5))
        )
        workspace.controls.append(pool_box)

        update_unscramble_ui()

        def submit_unscramble():
            chosen_order = user_state["unscramble_order"]
            if len(chosen_order) < len(fragments):
                return None, "Vui lòng sắp xếp tất cả các khối từ để tạo thành câu hoàn chỉnh."

            raw_target_order = question.get("correct_order")
            is_correct = False
            if isinstance(raw_target_order, list) and len(raw_target_order) == len(fragments):
                is_correct = (chosen_order == [int(x) for x in raw_target_order])

            constructed_sentence = " ".join([fragments[i] for i in chosen_order]).strip().lower()
            expected_sentence = str(question.get("correct_sentence") or question.get("sentence") or question.get("answer") or "").strip().lower()

            tr = str.maketrans('', '', string.punctuation)
            clean_constructed = constructed_sentence.translate(tr)
            clean_expected = expected_sentence.translate(tr)

            if expected_sentence and clean_constructed == clean_expected:
                is_correct = True

            if is_correct:
                sentence_box.bgcolor = CLR_GREEN
            else:
                sentence_box.bgcolor = CLR_RED

            sentence_box.update()
            exp = question.get("explanation", question.get("explain", ""))
            if not is_correct and expected_sentence:
                exp = f"Câu chính xác: '{expected_sentence}'. {exp}".strip()
            return is_correct, exp

        submit_fn = submit_unscramble

    # 8. CATEGORIZATION (Phân loại từ vựng / khái niệm vào các nhóm)
    elif q_type in ["categorization", "classify", "classification"]:
        raw_cats = question.get("categories") or []
        raw_items = question.get("items") or []

        items_list = []
        categories = list(raw_cats)

        if isinstance(raw_items, dict):
            for cat, words in raw_items.items():
                if cat not in categories:
                    categories.append(str(cat))
                if isinstance(words, list):
                    for w in words:
                        items_list.append({"text": str(w), "category": str(cat)})
                else:
                    items_list.append({"text": str(words), "category": str(cat)})
        elif isinstance(raw_items, list):
            for it in raw_items:
                if isinstance(it, dict):
                    t = it.get("text") or it.get("word") or it.get("item") or it.get("name") or ""
                    c = it.get("category") or it.get("group") or it.get("type") or ""
                    if c and c not in categories:
                        categories.append(str(c))
                    items_list.append({"text": str(t), "category": str(c)})
                elif isinstance(it, str):
                    items_list.append({"text": it, "category": ""})

        if "shuffled_items" not in user_state:
            shuffled = list(items_list)
            random.shuffle(shuffled)
            user_state["shuffled_items"] = shuffled
            user_state["categorization"] = {}

        items_to_render = user_state["shuffled_items"]

        item_cards = []
        for i_idx, item_obj in enumerate(items_to_render):
            item_text = item_obj["text"]
            cat_buttons = []

            for cat_name in categories:
                btn_cat = ft.Container(
                    content=ft.Text(cat_name, size=12, weight=ft.FontWeight.W_800, color=TEXT_DARK),
                    bgcolor=BG_WHITE,
                    border=mk_border(2, TEXT_DARK),
                    shadow=SHADOW_SM,
                    padding=pad(h=12, v=6),
                    ink=True,
                )
                cat_buttons.append((cat_name, btn_cat))

            def make_cat_clicker(_idx, _cname, _btn_list):
                def on_click(e):
                    if user_state.get("submitted"): return
                    user_state["categorization"][_idx] = _cname
                    for cn, b in _btn_list:
                        is_sel = (cn == _cname)
                        b.bgcolor = TEXT_DARK if is_sel else BG_WHITE
                        b.content.color = BG_WHITE if is_sel else TEXT_DARK
                        b.update()
                return on_click

            for cname, btn in cat_buttons:
                btn.on_click = make_cat_clicker(i_idx, cname, cat_buttons)

            card_row = ft.Container(
                content=ft.Column([
                    ft.Text(item_text, size=15, weight=ft.FontWeight.W_800, color=TEXT_DARK),
                    ft.Container(height=4),
                    ft.Row([b for _, b in cat_buttons], wrap=True, spacing=8),
                ], spacing=2),
                bgcolor=BG_WHITE,
                border=mk_border(2, TEXT_DARK),
                shadow=SHADOW_SM,
                padding=12,
            )
            item_cards.append((card_row, cat_buttons, item_obj))
            workspace.controls.append(card_row)

        def submit_categorization():
            assignments = user_state["categorization"]
            if len(assignments) < len(items_to_render):
                return None, "Vui lòng phân loại tất cả các mục vào nhóm tương ứng."

            all_correct = True
            for i_idx, (card_row, btn_list, item_obj) in enumerate(item_cards):
                user_chosen_cat = assignments.get(i_idx)
                expected_cat = item_obj.get("category")
                is_item_correct = (str(user_chosen_cat).strip().lower() == str(expected_cat).strip().lower())

                if is_item_correct:
                    card_row.bgcolor = CLR_GREEN
                else:
                    card_row.bgcolor = CLR_RED
                    all_correct = False

                for cn, b in btn_list:
                    if cn.strip().lower() == str(expected_cat).strip().lower():
                        b.bgcolor = CLR_GREEN
                        b.content.color = TEXT_DARK
                    elif cn == user_chosen_cat and not is_item_correct:
                        b.bgcolor = CLR_RED
                        b.content.color = TEXT_DARK
                    b.update()
                card_row.update()

            return all_correct, question.get("explanation", question.get("explain", ""))

        submit_fn = submit_categorization

    # 9. SPEECH VERIFICATION (Thử thách phát âm qua Microphone & Whisper)
    elif q_type in ["speech_verification", "speech", "pronunciation", "pronunciation_test", "pronounce"]:
        target_text = str(
            question.get("target_text")
            or question.get("expected_text")
            or question.get("word")
            or question.get("sentence")
            or question.get("answer")
            or question.get("correct", "")
        ).strip()

        context = question.get("contextual_text", question.get("context", ""))
        if context:
            workspace.controls.append(
                ft.Container(
                    content=ft.Text(f'"{context}"', size=15, weight=ft.FontWeight.W_600, color=TEXT_DARK, italic=True),
                    bgcolor="#f3f4f6",
                    padding=12,
                    border=mk_border(1, "#d1d5db"),
                )
            )

        listen_sample_btn = ft.IconButton(
            ft.Icons.VOLUME_UP_ROUNDED,
            icon_size=24,
            icon_color="#4338ca",
            tooltip="Nghe phát âm chuẩn (UK)",
            on_click=lambda e: on_speak(target_text) if on_speak else None,
            visible=bool(on_speak)
        )

        target_box = ft.Container(
            content=ft.Row([
                ft.Text("PHÁT ÂM TỪ / CÂU:", size=11, weight=ft.FontWeight.W_900, color=TEXT_GRAY),
                ft.Text(f'"{target_text}"', size=20, weight=ft.FontWeight.W_900, color=TEXT_DARK),
                listen_sample_btn,
            ], alignment=ft.MainAxisAlignment.CENTER, spacing=10, wrap=True),
            bgcolor="#eff6ff",
            border=mk_border(2, "#3b82f6"),
            padding=16,
            shadow=SHADOW_SM,
        )
        workspace.controls.append(target_box)

        status_icon = ft.Text("🎙", size=24)
        status_lbl = ft.Text("Bấm nút bên dưới để ghi âm phát âm của bạn (3.5s).", size=13, color=TEXT_GRAY)
        mic_status_row = ft.Row([status_icon, status_lbl], alignment=ft.MainAxisAlignment.CENTER, spacing=8)

        result_box = ft.Container(visible=False)

        user_state["speech_recorded"] = False
        user_state["speech_passed"] = False
        user_state["speech_transcript"] = ""

        rec_btn = nb_button("🎙 BẮT ĐẦU NÓI (3.5S)", bgcolor=TEXT_DARK, color=TEXT_WHITE)

        def on_record_click(e):
            if user_state.get("submitted") or user_state.get("speech_busy"): return
            user_state["speech_busy"] = True
            user_state["speech_recorded"] = False
            user_state["speech_passed"] = False
            user_state["speech_transcript"] = ""
            rec_btn.disabled = True
            rec_btn.bgcolor = "#9ca3af"
            rec_btn.content.controls[-1].value = "ĐANG THU ÂM (3.5S)..."
            status_icon.value = "🔴"
            status_lbl.value = "Đang ghi âm... hãy phát âm to và rõ ràng"
            status_lbl.color = "#dc2626"
            result_box.visible = False
            rec_btn.update()
            mic_status_row.update()

            def worker():
                try:
                    from audio_processor import verify_voice_pronunciation
                    thresh = int(question.get("threshold", 2))
                    res = verify_voice_pronunciation(target_text, duration=3.5, threshold=thresh)
                    if res.get("error"):
                        status_icon.value = "!"
                        status_lbl.value = res["feedback"]
                        status_lbl.color = "#92400e"
                        return
                    passed = res.get("passed", False)
                    transcribed = res.get("transcribed_text", "")

                    user_state["speech_recorded"] = True
                    user_state["speech_passed"] = passed
                    user_state["speech_transcript"] = transcribed

                    status_icon.value = "✓" if passed else "✗"
                    status_lbl.value = "Đã thu âm xong!"
                    status_lbl.color = "#166534" if passed else "#991b1b"

                    result_box.content = ft.Container(
                        content=ft.Column([
                            ft.Text("✓ PHÁT ÂM ĐẠT YÊU CẦU" if passed else "✗ PHÁT ÂM CHƯA ĐẠT", size=14, weight=ft.FontWeight.W_900, color="#166534" if passed else "#991b1b"),
                            ft.Text(f"AI nghe được: \"{transcribed or '(im lặng)'}\"", size=13, weight=ft.FontWeight.W_700, color=TEXT_DARK),
                            ft.Text(res.get("feedback", ""), size=12, color=TEXT_GRAY, italic=True),
                        ], spacing=4),
                        bgcolor=CLR_GREEN if passed else CLR_RED,
                        border=mk_border(2, "#166534" if passed else "#991b1b"),
                        padding=12,
                    )
                    result_box.visible = True
                except Exception as ex:
                    logger.error("Lỗi thu âm kiểm tra phát âm trong quiz: %s", ex, exc_info=True)
                    status_icon.value = "⚠"
                    status_lbl.value = f"Lỗi thu âm: {ex}"
                    status_lbl.color = "#991b1b"
                finally:
                    user_state["speech_busy"] = False
                    rec_btn.disabled = False
                    rec_btn.bgcolor = TEXT_DARK
                    rec_btn.content.controls[-1].value = "🎙 NÓI LẠI (3.5S)"
                    try:
                        rec_btn.update()
                        mic_status_row.update()
                        result_box.update()
                    except Exception:
                        pass

            import threading
            threading.Thread(target=worker, daemon=True).start()

        rec_btn.on_click = on_record_click

        workspace.controls.append(ft.Container(height=8))
        workspace.controls.append(mic_status_row)
        workspace.controls.append(ft.Container(height=8))
        workspace.controls.append(ft.Row([rec_btn], alignment=ft.MainAxisAlignment.CENTER))
        workspace.controls.append(ft.Container(height=8))
        workspace.controls.append(result_box)

        def submit_speech():
            if user_state.get("speech_busy"):
                return None, "Vui lòng chờ ghi âm và nhận dạng hoàn tất."
            if not user_state.get("speech_recorded"):
                return None, "Vui lòng bấm nút ghi âm và phát âm từ trước khi nộp bài."
            passed = user_state.get("speech_passed", False)
            exp = question.get("explanation", question.get("explain", ""))
            trans = user_state.get("speech_transcript", "")
            full_exp = f"Phát âm bạn đọc: '{trans}'. {exp}".strip()
            return passed, full_exp

        submit_fn = submit_speech

    # 10. UNIVERSAL SINGLE-CHOICE & FALLBACK
    elif submit_fn is None:
        option_buttons = []
        text_refs = []

        def select_single(idx):
            if user_state.get("submitted"): return
            user_state["selected"] = idx
            for i, btn in enumerate(option_buttons):
                active = (i == idx)
                btn.bgcolor = (MASTER_SHADOW if is_master else TEXT_DARK) if active else BG_WHITE
                text_refs[i].color = BG_WHITE if active else TEXT_DARK
                btn.update()

        # Nếu không có options nào trong câu hỏi, tự tạo placeholder
        disp_options = options if options else ["Phương án A", "Phương án B", "Phương án C", "Phương án D"]

        for idx, opt in enumerate(disp_options):
            txt_ctrl = ft.Text(opt, size=14, weight=ft.FontWeight.W_700, color=TEXT_DARK, expand=True)
            text_refs.append(txt_ctrl)
            btn = ft.Container(
                content=ft.Row([txt_ctrl]),
                bgcolor=BG_WHITE,
                border=mk_border(2, MASTER_BORDER if is_master else TEXT_DARK),
                shadow=SHADOW_SM,
                padding=pad(h=16, v=12),
                on_click=lambda e, idx=idx: select_single(idx),
                ink=True,
            )
            option_buttons.append(btn)
            workspace.controls.append(btn)

        def submit_single():
            sel = user_state["selected"]
            if sel is None:
                return None, "Hãy chọn một phương án."
            correct = _normalize_correct_idx(question.get("correct_index", question.get("correct_answer", question.get("answer", question.get("correct", 0)))), len(disp_options))
            is_correct = (sel == correct)
            for i, btn in enumerate(option_buttons):
                if i == correct:
                    btn.bgcolor = CLR_GREEN
                    text_refs[i].color = TEXT_DARK
                elif i == sel and not is_correct:
                    btn.bgcolor = CLR_RED
                    text_refs[i].color = TEXT_DARK
                btn.update()
            return is_correct, question.get("explanation", question.get("explain", ""))

        submit_fn = submit_single

    # Feedback box
    feedback_box = ft.Container(visible=False)

    # Submit Button
    btn_submit = nb_button(
        "Nộp bài",
        icon="⚡",
        bgcolor=MASTER_BORDER if is_master else TEXT_DARK,
        color=TEXT_WHITE,
    )

    def handle_submit(e):
        if submit_fn:
            passed, exp = submit_fn()
            if passed is None:
                page = btn_submit.page
                if page:
                    page.show_dialog(ft.SnackBar(ft.Text(str(exp or ""), color=TEXT_WHITE), bgcolor="#991b1b"))
                    page.update()
                return

            btn_submit.disabled = True
            btn_submit.bgcolor = TEXT_GRAY
            btn_submit.update()

            user_state["submitted"] = True

            feedback_box.content = nb_card(
                ft.Column([
                    ft.Text("CHÍNH XÁC! ✓" if passed else "CHƯA ĐÚNG ✗", size=16, weight=ft.FontWeight.W_900,
                            color="#166534" if passed else "#991b1b"),
                    ft.Container(height=4),
                    ft.Text(str(exp or ""), size=13, color=TEXT_DARK, italic=True),
                ], spacing=0),
                bgcolor=CLR_GREEN if passed else CLR_RED,
                shadow_size="sm"
            )
            feedback_box.visible = True
            feedback_box.update()

            if on_answer:
                on_answer(passed, exp)

    btn_submit.on_click = handle_submit

    card_bg = MASTER_BG if is_master else BG_WHITE
    card_border = MASTER_BORDER if is_master else TEXT_DARK
    card_shadow = "lg"

    return nb_card(
        ft.Column(
            [
                ft.Row([header], alignment=ft.MainAxisAlignment.START),
                ft.Container(height=14),
                q_header_row,
                ft.Container(height=18),
                workspace,
                ft.Container(height=24),
                feedback_box,
                ft.Container(height=12),
                ft.Row([btn_submit], alignment=ft.MainAxisAlignment.END)
            ],
            spacing=0,
        ),
        bgcolor=card_bg,
        border_color=card_border,
        border_width=4 if is_master else 3,
        shadow_size=card_shadow,
    )
