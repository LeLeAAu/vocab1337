"""
components/flashcard.py — Vocab1337
Thẻ Flashcard học từ vựng Neubrutalism tương thích Flet 0.85.
Hỗ trợ hiển thị đầy đủ các trường ranh giới ngữ nghĩa (Semantic Boundaries):
  - Nuance (Sắc thái EN/VI)
  - Contrast (Tương phản từ đồng nghĩa EN/VI)
  - Usage Distinction (Giới hạn ngữ cảnh và trường hợp không nên dùng EN/VI)
  - Definition (Simple & Minimal EN + VI)
  - Narrative Example (Ví dụ neo vào cốt truyện EN/VI)
  - Tone & British IPA

Hỗ trợ 2 chế độ:
  - Sơ cấp (score < 3): Lật thẻ xem nghĩa, click 4 nút rating SRS.
  - Phản xạ (score >= 3): Gõ chính xác từ vựng để lật thẻ.
"""

import flet as ft
from logger import get_logger

logger = get_logger("flashcard")

TEXT_DARK = "#111827"
TEXT_GRAY = "#6b7280"
TEXT_WHITE = "#ffffff"
BG_WHITE  = "#ffffff"
CLR_GREEN = "#bbf7d0"
CLR_RED   = "#fecaca"
CLR_BLUE  = "#bfdbfe"
CLR_YELLOW = "#fef08a"

SHADOW_SM = ft.BoxShadow(offset=ft.Offset(4, 4), blur_radius=0, color=TEXT_DARK)
SHADOW_MD = ft.BoxShadow(offset=ft.Offset(8, 8), blur_radius=0, color=TEXT_DARK)


def mk_border(w: int, c: str) -> ft.Border:
    s = ft.BorderSide(w, c)
    return ft.Border(left=s, right=s, top=s, bottom=s)


def pad(all_=None, h=None, v=None, left=0, top=0, right=0, bottom=0) -> ft.Padding:
    if all_ is not None:
        return ft.Padding(left=all_, top=all_, right=all_, bottom=all_)
    if h is not None or v is not None:
        _h = h or 0; _v = v or 0
        return ft.Padding(left=_h, top=_v, right=_h, bottom=_v)
    return ft.Padding(left=left, top=top, right=right, bottom=bottom)


def nb_button(label: str, icon: str = "", on_click=None, bgcolor=BG_WHITE, color=TEXT_DARK, width=None) -> ft.Container:
    row_content = []
    if icon:
        row_content.append(ft.Text(icon, size=15, color=color))
    row_content.append(ft.Text(label.upper(), size=12, weight=ft.FontWeight.W_800, color=color))

    return ft.Container(
        content=ft.Row(row_content, spacing=8, alignment=ft.MainAxisAlignment.CENTER),
        bgcolor=bgcolor,
        border=mk_border(2, TEXT_DARK),
        shadow=SHADOW_SM,
        padding=pad(h=16, v=12),
        on_click=on_click,
        width=width,
        ink=True,
    )


def show_pronunciation_modal(page: ft.Page, word: str, ipa: str = "", on_speak: callable = None):
    """Hiện dialog Neubrutalism cho phép người học phát âm từ qua Micro và nhận đánh giá từ AI Whisper."""
    if not page:
        return
    import threading
    from audio_processor import verify_voice_pronunciation

    status_icon = ft.Text("🎙", size=26)
    status_text = ft.Text("Bấm 'Bắt đầu nói' và phát âm rõ từ vựng trong 3.5 giây.", size=13, color=TEXT_GRAY)

    result_card = ft.Container(visible=False)

    btn_record = nb_button("🎙 Bắt đầu nói (3.5s)", bgcolor=TEXT_DARK, color=TEXT_WHITE)
    btn_close = nb_button("Đóng", bgcolor=BG_WHITE, color=TEXT_DARK)

    is_busy = False

    def close_dlg(e=None):
        page.pop_dialog()

    btn_close.on_click = close_dlg

    def on_record_click(e):
        nonlocal is_busy
        if is_busy:
            return
        is_busy = True
        btn_record.disabled = True
        btn_record.bgcolor = "#9ca3af"
        btn_record.content.controls[1].value = "ĐANG THU ÂM (3.5S)..."
        status_icon.value = "🔴"
        status_text.value = "Đang ghi âm... hãy phát âm to và rõ ràng"
        status_text.color = "#dc2626"
        result_card.visible = False
        dlg.update()

        def worker():
            nonlocal is_busy
            try:
                res = verify_voice_pronunciation(word, duration=3.5, threshold=2)
                passed = res.get("passed", False)
                transcribed = res.get("transcribed_text", "")
                dist = res.get("distance", 0)
                feedback = res.get("feedback", "")

                status_icon.value = "✓" if passed else "✗"
                status_text.value = "Phân tích xong!"
                status_text.color = "#166534" if passed else "#991b1b"

                result_card.content = ft.Container(
                    content=ft.Column([
                        ft.Text("✓ PHÁT ÂM CHUẨN!" if passed else "✗ CHƯA CHÍNH XÁC", size=14, weight=ft.FontWeight.W_900, color="#166534" if passed else "#991b1b"),
                        ft.Text(f"AI nhận diện: \"{transcribed or '(im lặng)'}\"", size=13, weight=ft.FontWeight.W_700, color=TEXT_DARK),
                        ft.Text(feedback, size=12, color=TEXT_GRAY, italic=True),
                    ], spacing=4),
                    bgcolor=CLR_GREEN if passed else CLR_RED,
                    border=mk_border(2, "#166534" if passed else "#991b1b"),
                    padding=12,
                )
                result_card.visible = True
            except Exception as err:
                logger.error("Lỗi khi kiểm tra phát âm Flashcard: %s", err, exc_info=True)
                status_icon.value = "⚠"
                status_text.value = f"Lỗi: {err}"
                status_text.color = "#991b1b"
            finally:
                is_busy = False
                btn_record.disabled = False
                btn_record.bgcolor = TEXT_DARK
                btn_record.content.controls[1].value = "🎙 NÓI LẠI (3.5S)"
                try:
                    dlg.update()
                except Exception:
                    pass

        threading.Thread(target=worker, daemon=True).start()

    btn_record.on_click = on_record_click

    dlg = ft.AlertDialog(
        modal=True,
        title=ft.Row([
            ft.Row([
                ft.Text("🎙", size=20),
                ft.Text("LUYỆN PHÁT ÂM (AI WHISPER)", size=16, weight=ft.FontWeight.W_900, color=TEXT_DARK),
            ], spacing=6),
            ft.IconButton(ft.Icons.CLOSE, on_click=close_dlg, icon_color=TEXT_DARK),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        content=ft.Column([
            ft.Container(
                content=ft.Row([
                    ft.Text(word.upper(), size=26, weight=ft.FontWeight.W_900, color=TEXT_DARK),
                    ft.Text(f"/{ipa.strip().strip('/')}/", size=15, weight=ft.FontWeight.W_600, color="#4f46e5") if ipa else ft.Container(),
                    ft.IconButton(
                        ft.Icons.VOLUME_UP_ROUNDED,
                        tooltip="Nghe phát âm chuẩn UK",
                        icon_color="#4338ca",
                        icon_size=20,
                        on_click=lambda e: on_speak(word) if on_speak else None,
                    ) if on_speak else ft.Container(),
                ], alignment=ft.MainAxisAlignment.CENTER, spacing=8),
                padding=pad(v=10),
            ),
            ft.Container(
                content=ft.Row([status_icon, status_text], alignment=ft.MainAxisAlignment.CENTER, spacing=10),
                padding=pad(v=8),
            ),
            result_card,
            ft.Container(height=16),
            ft.Row([btn_close, ft.Container(width=8), btn_record], alignment=ft.MainAxisAlignment.END),
        ], spacing=0, tight=True, width=440),
    )
    page.show_dialog(dlg)


def build_flashcard_view(
    vocab: dict,
    score: float | int = 0,
    seen: int = 0,
    on_rate: callable = None,  # callback(rating: str) -> rating in ['FORGOT', 'VAGUE', 'RECALL', 'EASY']
    on_speak: callable = None, # callback(text: str) -> phát âm từ vựng
    auto_speak_threshold: int = 3,  # score < threshold thì tự động đọc khi hiện thẻ và khi lật lần đầu
    on_next: callable = None,  # callback() -> chuyển thẻ tiếp theo (tương đương EASY) — dùng cho phím Enter
    flip_ref: dict = None,     # dict mutable để expose flip_action ra ngoài: flip_ref["flip"] = flip_action
) -> ft.Control:
    """
    Tạo Control hiển thị thẻ Flashcard Neubrutalism hoàn chỉnh với đầy đủ các tầng ngữ nghĩa.

    Hành vi phát âm tự động:
      - Khi score < auto_speak_threshold: tự đọc từ ngay khi thẻ hiển thị (mặt trước).
      - Khi lật thẻ: tự đọc từ **lần đầu tiên** lật trong mỗi thẻ (reset khi chuyển thẻ).
        Lật qua lật lại sau đó không tự đọc — phải bấm nút 🔊.

    Phím tắt (keyboard shortcuts):
      - Space  → lật thẻ (flip)
      - Enter  → chuyển thẻ tiếp theo (gọi on_next, tương đương EASY)
    """
    word = str(vocab.get("word") or "N/A")
    pos = str(vocab.get("pos") or "noun")
    ipa = str(vocab.get("ipa_uk") or vocab.get("ipa") or "")
    def_minimal = str(vocab.get("definition_minimal_en") or vocab.get("definition_short_en") or "")
    def_simple = str(vocab.get("definition_simple_en") or vocab.get("definition_full_en") or "")
    def_vi = str(vocab.get("definition_vi_simple") or vocab.get("definition_vi") or "")
    ex_en = str(vocab.get("example_en") or "")
    ex_vi = str(vocab.get("example_vi") or "")
    contrast = str(vocab.get("contrast") or "")
    contrast_vi = str(vocab.get("contrast_vi") or "")
    nuance = str(vocab.get("nuance_en") or "")
    nuance_vi = str(vocab.get("nuance_vi") or "")
    usage = str(vocab.get("usage_distinction") or vocab.get("usage_note") or "")
    usage_vi = str(vocab.get("usage_distinction_vi") or "")
    tone = str(vocab.get("tone_en") or vocab.get("tone") or "Academic")
    score_str = f"{score:g}" if isinstance(score, (int, float)) else str(score)

    state = {
        "flipped": False,
        # True sau khi đã tự động đọc lần đầu khi lật thẻ này; reset về False khi chuyển thẻ mới
        "flip_auto_spoken": False,
        "was_incorrect": False,
    }

    # Helper: gọi on_speak an toàn (non-blocking, chạy trong thread riêng)
    def _speak(text: str):
        if on_speak and text:
            import threading
            threading.Thread(target=on_speak, args=(text,), daemon=True).start()

    card_container = ft.Container(
        bgcolor=BG_WHITE,
        border=mk_border(3, TEXT_DARK),
        shadow=SHADOW_MD,
        padding=24,
        height=450,
        expand=True,
    )

    action_bar = ft.Container(visible=False)

    # ── MẶT TRƯỚC: SƠ CẤP (score < 3) ─────────────────────────────────────────
    def make_front_beginner():
        return ft.Column(
            [
                ft.Container(expand=True),
                ft.Row([
                    ft.Text(word, size=40, weight=ft.FontWeight.W_900, color=TEXT_DARK),
                    ft.Text(f"({pos})", size=16, weight=ft.FontWeight.W_600, color=TEXT_GRAY) if pos else ft.Container()
                ], alignment=ft.MainAxisAlignment.CENTER, wrap=True),
                ft.Container(height=8),
                ft.Row([
                    ft.Container(
                        content=ft.Text("🇬🇧 UK", size=10, weight=ft.FontWeight.W_800, color="#4338ca"),
                        bgcolor="#e0e7ff",
                        border=mk_border(1, "#c7d2fe"),
                        padding=pad(h=6, v=2),
                        border_radius=3,
                    ),
                    ft.Text(f"/{ipa.strip().strip('/')}/", size=16, weight=ft.FontWeight.W_600, color="#4f46e5"),
                    ft.IconButton(
                        ft.Icons.VOLUME_UP_ROUNDED,
                        tooltip="Phát âm chuẩn Anh - Anh (UK)",
                        on_click=lambda e: _speak(word),
                        icon_color="#4338ca",
                        icon_size=22,
                    ) if on_speak else ft.Container(),
                    ft.IconButton(
                        ft.Icons.MIC_ROUNDED,
                        tooltip="Luyện phát âm qua Micro (AI Whisper)",
                        on_click=lambda e: show_pronunciation_modal(card_container.page, word, ipa, on_speak),
                        icon_color="#059669",
                        icon_size=22,
                    ),
                ], alignment=ft.MainAxisAlignment.CENTER, spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER) if ipa else (
                    ft.Row([
                        ft.IconButton(
                            ft.Icons.VOLUME_UP_ROUNDED,
                            tooltip="Phát âm chuẩn Anh - Anh (UK)",
                            on_click=lambda e: _speak(word),
                            icon_color="#4338ca",
                            icon_size=22,
                        ) if on_speak else ft.Container(),
                        ft.IconButton(
                            ft.Icons.MIC_ROUNDED,
                            tooltip="Luyện phát âm qua Micro (AI Whisper)",
                            on_click=lambda e: show_pronunciation_modal(card_container.page, word, ipa, on_speak),
                            icon_color="#059669",
                            icon_size=22,
                        ),
                    ], alignment=ft.MainAxisAlignment.CENTER, spacing=6)
                ),
                ft.Container(height=12),
                ft.Container(
                    content=ft.Text(def_minimal or def_simple, size=16, weight=ft.FontWeight.W_600, color=TEXT_GRAY, text_align=ft.TextAlign.CENTER),
                    padding=pad(h=16),
                ),
                ft.Container(expand=True),
                ft.Row([
                    ft.Text("⚡ CHẠM VÀO THẺ ĐỂ LẬT NGHĨA CHI TIẾT", size=11, weight=ft.FontWeight.W_800, color=TEXT_GRAY)
                ], alignment=ft.MainAxisAlignment.CENTER),
                ft.Row([
                    ft.Text(f"SCORE: {score_str} | SEEN: {seen}", size=10, weight=ft.FontWeight.W_700, color=TEXT_GRAY)
                ], alignment=ft.MainAxisAlignment.START)
            ],
            spacing=0,
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            expand=True,
        )

    # ── MẶT TRƯỚC: PHẢN XẠ (score >= 3) ───────────────────────────────────────
    def make_front_active():
        input_field = ft.TextField(
            hint_text="gõ chính xác từ...",
            border_color=TEXT_DARK,
            border_width=3,
            border_radius=0,
            width=320,
            text_align=ft.TextAlign.CENTER,
            text_style=ft.TextStyle(size=20, weight=ft.FontWeight.W_900, color=TEXT_DARK),
            hint_style=ft.TextStyle(size=16, color="#9ca3af"),
        )
        feedback_txt = ft.Text("", color="#991b1b", weight=ft.FontWeight.W_800, size=13)

        def give_up_action(e=None):
            state["was_incorrect"] = True
            flip_action()

        give_up_btn = nb_button(
            "Xem đáp án",
            icon="👁",
            bgcolor="#fef2f2",
            color="#991b1b",
            on_click=give_up_action
        )

        def on_submit(e):
            val = " ".join((input_field.value or "").strip().lower().split())
            target_word = " ".join(word.strip().lower().split())
            if val == target_word:
                input_field.bgcolor = CLR_GREEN
                input_field.disabled = True
                feedback_txt.value = "Chính xác! ✓"
                feedback_txt.color = "#166534"
                try:
                    input_field.update()
                    feedback_txt.update()
                except Exception:
                    pass
                flip_action()
            else:
                input_field.bgcolor = CLR_RED
                state["was_incorrect"] = True
                feedback_txt.value = "Chưa chính xác! Thử lại hoặc bấm 'Xem đáp án'."
                feedback_txt.color = "#991b1b"
                try:
                    input_field.update()
                    feedback_txt.update()
                except Exception:
                    pass

        input_field.on_submit = on_submit

        return ft.Column(
            [
                ft.Row([
                    nb_button("Nghe phát âm (UK)", icon="🔊", on_click=lambda e: _speak(word), width=180),
                    ft.Container(width=8),
                    nb_button("Luyện nói (AI)", icon="🎙", on_click=lambda e: show_pronunciation_modal(card_container.page, word, ipa, on_speak), width=180),
                ], alignment=ft.MainAxisAlignment.CENTER),
                ft.Container(height=14),
                ft.Text(f"Gợi ý: {def_minimal or def_simple}", size=14, color=TEXT_GRAY, italic=True, text_align=ft.TextAlign.CENTER),
                ft.Container(height=14),
                input_field,
                ft.Container(height=6),
                feedback_txt,
                ft.Container(height=8),
                give_up_btn,
                ft.Container(expand=True),
                ft.Row([
                    ft.Text("GÕ CHÍNH XÁC TỪ ĐỂ MỞ KHÓA BỘ NHỚ", size=11, weight=ft.FontWeight.W_800, color=TEXT_GRAY)
                ], alignment=ft.MainAxisAlignment.CENTER),
                ft.Row([
                    ft.Text(f"SCORE: {score_str} | SEEN: {seen}", size=10, weight=ft.FontWeight.W_700, color=TEXT_GRAY)
                ], alignment=ft.MainAxisAlignment.START)
            ],
            spacing=0,
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            expand=True,
        )

    # ── MẶT SAU: CHI TIẾT ĐẦY ĐỦ RANH GIỚI NGỮ NGHĨA ─────────────────────────
    def make_back():
        # Toggle reveal VN dịch nghĩa của ví dụ
        reveal_vn_btn = ft.Container(
            content=ft.Row([
                ft.Text("👁  DỊCH VÍ DỤ", size=10, weight=ft.FontWeight.W_800, color=TEXT_GRAY)
            ], alignment=ft.MainAxisAlignment.CENTER),
            bgcolor=BG_WHITE,
            border=mk_border(1, TEXT_DARK),
            padding=pad(h=8, v=4),
            on_click=lambda e: toggle_reveal_vn(),
            width=120,
            ink=True
        )
        vn_trans_col = ft.Column([
            ft.Text(f"↳ {ex_vi}", size=13, color="#166534", italic=True, weight=ft.FontWeight.W_600),
        ], visible=False)

        def toggle_reveal_vn():
            vn_trans_col.visible = not vn_trans_col.visible
            reveal_vn_btn.content.controls[0].value = "👁  ẨN DỊCH" if vn_trans_col.visible else "👁  DỊCH VÍ DỤ"
            try:
                reveal_vn_btn.update()
                vn_trans_col.update()
            except Exception:
                pass

        # Semantic Boundary Box (Nuance, Contrast, Usage Distinction)
        semantic_details = []

        if nuance or nuance_vi:
            semantic_details.append(
                ft.Container(
                    content=ft.Column([
                        ft.Text("🎨 SẮC THÁI & HÀM Ý (NUANCE):", size=11, weight=ft.FontWeight.W_800, color="#1e1b4b"),
                        ft.Text(nuance, size=12, color=TEXT_DARK, weight=ft.FontWeight.W_500) if nuance else ft.Container(),
                        ft.Text(f"↳ {nuance_vi}", size=12, color="#4338ca", italic=True) if nuance_vi else ft.Container(),
                    ], spacing=3),
                    bgcolor="#e0e7ff",
                    border=mk_border(1, "#6366f1"),
                    padding=10,
                )
            )

        if contrast or contrast_vi:
            semantic_details.append(
                ft.Container(
                    content=ft.Column([
                        ft.Text("⚖️ PHÂN BIỆT RANH GIỚI TỪ ĐỒNG NGHĨA (CONTRAST):", size=11, weight=ft.FontWeight.W_800, color="#701a75"),
                        ft.Text(contrast, size=12, color=TEXT_DARK, weight=ft.FontWeight.W_500) if contrast else ft.Container(),
                        ft.Text(f"↳ {contrast_vi}", size=12, color="#86198f", italic=True) if contrast_vi else ft.Container(),
                    ], spacing=3),
                    bgcolor="#fae8ff",
                    border=mk_border(1, "#d946ef"),
                    padding=10,
                )
            )

        if usage or usage_vi:
            semantic_details.append(
                ft.Container(
                    content=ft.Column([
                        ft.Text("🚫 GIỚI HẠN & TRƯỜNG HỢP KHÔNG NÊN DÙNG (USAGE DISTINCTION):", size=11, weight=ft.FontWeight.W_800, color="#78350f"),
                        ft.Text(usage, size=12, color=TEXT_DARK, weight=ft.FontWeight.W_500) if usage else ft.Container(),
                        ft.Text(f"↳ {usage_vi}", size=12, color="#92400e", italic=True) if usage_vi else ft.Container(),
                    ], spacing=3),
                    bgcolor="#fef3c7",
                    border=mk_border(1, "#f59e0b"),
                    padding=10,
                )
            )

        read_more_box = ft.Container(
            content=ft.Column(semantic_details, spacing=8),
            visible=False,
            padding=pad(top=8),
        )

        read_more_btn = ft.Container(
            content=ft.Row([
                ft.Text("📖  CHI TIẾT RANH GIỚI NGỮ NGHĨA (ĐỌC THÊM) ➔", size=12, weight=ft.FontWeight.W_800, color="#3730a3")
            ]),
            on_click=lambda e: toggle_read_more(),
            ink=True
        )

        def toggle_read_more():
            read_more_box.visible = not read_more_box.visible
            read_more_btn.content.controls[0].value = "📖  ẨN CHI TIẾT ⮎" if read_more_box.visible else "📖  CHI TIẾT RANH GIỚI NGỮ NGHĨA (ĐỌC THÊM) ➔"
            try:
                read_more_btn.update()
                read_more_box.update()
            except Exception:
                pass

        # Tiếng Việt badge
        def_vi_box = ft.Container(
            content=ft.Text(f"Nghĩa VN: {def_vi}", size=13, weight=ft.FontWeight.W_800, color="#14532d"),
            bgcolor=CLR_GREEN,
            border=mk_border(1, TEXT_DARK),
            padding=pad(h=12, v=6),
            shadow=SHADOW_SM,
        )

        # Tone badge
        tone_badge = ft.Container(
            content=ft.Text((tone or "").upper(), size=9, weight=ft.FontWeight.W_800, color=TEXT_WHITE),
            bgcolor="#312e81",
            padding=pad(h=8, v=4),
            border=mk_border(1, TEXT_DARK),
        ) if tone else ft.Container()

        clean_ipa = f"/{ipa.strip().strip('/')}/".strip() if ipa and ipa.strip().strip('/') else ""

        return ft.Column(
            [
                # Word Header Row
                ft.Row([
                    ft.Text((word or "").upper(), size=28, weight=ft.FontWeight.W_900, color=TEXT_DARK),
                    ft.Text(f"({pos})", size=14, weight=ft.FontWeight.W_700, color=TEXT_GRAY, italic=True) if pos else ft.Container(),
                    ft.Container(
                        content=ft.Row([
                            ft.Container(
                                content=ft.Text("🇬🇧 UK", size=10, weight=ft.FontWeight.W_800, color="#4338ca"),
                                bgcolor="#e0e7ff",
                                border=mk_border(1, "#c7d2fe"),
                                padding=pad(h=5, v=2),
                                border_radius=3,
                            ),
                            ft.Text(clean_ipa, size=14, color="#4338ca", weight=ft.FontWeight.W_700) if clean_ipa else ft.Container(),
                            ft.IconButton(
                                ft.Icons.VOLUME_UP_ROUNDED,
                                tooltip="Phát âm chuẩn Anh - Anh (UK)",
                                on_click=lambda e: _speak(word),
                                icon_color="#4338ca",
                                icon_size=22
                            ),
                            ft.IconButton(
                                ft.Icons.MIC_ROUNDED,
                                tooltip="Luyện phát âm qua Micro (AI Whisper)",
                                on_click=lambda e: show_pronunciation_modal(card_container.page, word, ipa, on_speak),
                                icon_color="#059669",
                                icon_size=22
                            ),
                        ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER)
                    ) if on_speak or clean_ipa else ft.Container(),
                    ft.Container(expand=True),
                    tone_badge,
                ], alignment=ft.MainAxisAlignment.START, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Container(height=8),

                # Minimal & Simple Definition
                ft.Row([
                    ft.Container(
                        content=ft.Text(f"Core: {def_minimal}", size=11, weight=ft.FontWeight.W_800, color="#1e3a8a"),
                        bgcolor="#dbeafe",
                        padding=pad(h=8, v=3),
                        border=mk_border(1, "#3b82f6"),
                    )
                ]) if def_minimal else ft.Container(),
                ft.Container(height=4),
                ft.Text(def_simple, size=15, weight=ft.FontWeight.W_700, color="#1e1b4b"),
                ft.Container(height=8),
                ft.Row([def_vi_box]),
                ft.Container(height=16),

                # Narrative Story Example
                ft.Container(
                    content=ft.Column([
                        ft.Text("❝ VÍ DỤ TRONG THẾ GIỚI CÂU CHUYỆN", size=10, weight=ft.FontWeight.W_800, color=TEXT_GRAY),
                        ft.Text(f'"{ex_en}"', size=14, italic=True, weight=ft.FontWeight.W_500, color=TEXT_DARK),
                        ft.Row([reveal_vn_btn, vn_trans_col], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    ], spacing=8),
                    border=ft.Border(left=ft.BorderSide(4, TEXT_DARK)),
                    padding=pad(left=14, v=4),
                ),
                ft.Container(height=16),

                # Semantic Boundary Expansion
                read_more_btn if semantic_details else ft.Container(),
                read_more_box,
                ft.Container(height=16),

                # Stats bar
                ft.Row([
                    ft.Text(f"SCORE: {score_str} | SEEN: {seen}", size=9, weight=ft.FontWeight.W_800, color=TEXT_GRAY)
                ], alignment=ft.MainAxisAlignment.START)
            ],
            spacing=0,
            scroll=ft.ScrollMode.AUTO,
        )

    # ── LOGIC TIẾP THEO & ĐÁNH GIÁ ──────────────────────────────────────────
    def handle_next():
        if on_rate:
            if state.get("was_incorrect"):
                on_rate("FORGOT")
            elif on_next:
                on_next()
            else:
                on_rate("EASY")

    # ── LOGIC LẬT THẺ ────────────────────────────────────────────────────────
    def flip_action():
        state["flipped"] = not state["flipped"]
        if state["flipped"]:
            card_container.content = make_back()
            action_bar.visible = True
            # Tự đọc lần đầu khi lật sang mặt sau (bất kể score)
            if not state["flip_auto_spoken"]:
                state["flip_auto_spoken"] = True
                _speak(word)
        else:
            card_container.content = make_front_active() if score >= 3 else make_front_beginner()
            action_bar.visible = False
        update_kbd_hint()
        try:
            card_container.update()
            action_bar.update()
        except Exception:
            pass

    # Expose flip_action ra ngoài qua flip_ref (dùng cho keyboard handler ở main.py)
    if flip_ref is not None:
        flip_ref["flip"] = flip_action
        flip_ref["is_flipped"] = lambda: state["flipped"]
        flip_ref["can_flip_space"] = lambda: (score < 3 or state["flipped"])
        flip_ref["was_incorrect"] = lambda: state.get("was_incorrect", False)
        flip_ref["on_next"] = handle_next

    def on_card_click(e):
        if score >= 3 and not state["flipped"]:
            if not state.get("was_incorrect"):
                return
        flip_action()

    card_container.on_click = on_card_click
    card_container.content = make_front_active() if score >= 3 else make_front_beginner()

    # ── ACTION BUTTONS (4 nút đánh giá SRS Neubrutalism) ──────────────────────
    action_buttons_row = ft.Row(
        [
            nb_button("Quên hẳn", icon="💀", bgcolor=CLR_RED, on_click=lambda e: on_rate("FORGOT") if on_rate else None),
            nb_button("Mơ hồ", icon="☁️", bgcolor=CLR_YELLOW, on_click=lambda e: on_rate("VAGUE") if on_rate else None),
            nb_button("Nhớ được", icon="✓", bgcolor=CLR_BLUE, on_click=lambda e: on_rate("RECALL") if on_rate else None),
            nb_button("Quá dễ", icon="⚡", bgcolor=CLR_GREEN, on_click=lambda e: handle_next()),
        ],
        spacing=8,
        alignment=ft.MainAxisAlignment.CENTER,
    )
    action_bar.content = action_buttons_row

    # ── GHI CHÚ PHÍM TẮT ĐỘNG ─────────────────────────────────────────────────
    kbd_text_1 = ft.Text("Space", size=10, weight=ft.FontWeight.W_700, color=TEXT_DARK, font_family="monospace")
    kbd_desc_1 = ft.Text("lật thẻ", size=11, color=TEXT_GRAY)
    kbd_box_1 = ft.Container(content=kbd_text_1, bgcolor="#f3f4f6", border=mk_border(1, "#d1d5db"), padding=pad(h=6, v=2), border_radius=3)

    kbd_text_2 = ft.Text("Enter", size=10, weight=ft.FontWeight.W_700, color=TEXT_DARK, font_family="monospace")
    kbd_desc_2 = ft.Text("thẻ tiếp theo", size=11, color=TEXT_GRAY)
    kbd_box_2 = ft.Container(content=kbd_text_2, bgcolor="#f3f4f6", border=mk_border(1, "#d1d5db"), padding=pad(h=6, v=2), border_radius=3)

    kbd_hint = ft.Container(
        content=ft.Row([
            ft.Text("⌨", size=13, color=TEXT_GRAY),
            kbd_box_1,
            kbd_desc_1,
            ft.Container(width=16),
            kbd_box_2,
            kbd_desc_2,
        ], spacing=6, alignment=ft.MainAxisAlignment.CENTER, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        padding=pad(v=4),
    )

    def update_kbd_hint():
        if state["flipped"]:
            kbd_box_1.visible = True
            kbd_text_1.value = "Space"
            kbd_desc_1.value = "lật lại"
            kbd_box_2.visible = True
            kbd_text_2.value = "Enter"
            kbd_desc_2.value = "thẻ tiếp theo"
        elif score >= 3:
            kbd_box_1.visible = False
            kbd_desc_1.value = "Gõ từ và nhấn"
            kbd_box_2.visible = True
            kbd_text_2.value = "Enter"
            kbd_desc_2.value = "để nộp bài"
        else:
            kbd_box_1.visible = True
            kbd_text_1.value = "Space"
            kbd_desc_1.value = "lật thẻ"
            kbd_box_2.visible = False
            kbd_desc_2.value = "hoặc chạm vào thẻ"
        try:
            if kbd_hint.page:
                kbd_hint.update()
        except Exception:
            pass

    update_kbd_hint()

    # ── AUTO-SPEAK KHI HIỆN THẺ MỚI (score < auto_speak_threshold) ───────────
    # Dùng threading.Timer để delay nhẹ (~150ms) cho card kịp render trước khi phát âm.
    # Chỉ đọc ở mặt TRƯỚC cho chế độ sơ cấp (score < threshold).
    if score < auto_speak_threshold:
        import threading
        threading.Timer(0.15, lambda: _speak(word)).start()

    return ft.Column(
        [card_container, ft.Container(height=16), action_bar, ft.Container(height=8), kbd_hint],
        spacing=0,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
    )
