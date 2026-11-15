"""Choose a random vocabulary practice session."""
import flet as ft
from components.theme import (
    BG_PAGE, BG_WHITE, BG_SIDEBAR, TEXT_DARK, TEXT_GRAY, TEXT_WHITE,
    CLR_GREEN, CLR_BLUE, CLR_YELLOW, CLR_RED, SHADOW_SM, SHADOW_MD, SHADOW_LG,
    mk_border, pad, marg, nb_button, nb_card, label_text, heading_text,
)

from database import get_total_vocab_count

def build_random_screen(page: ft.Page, on_start_session) -> ft.Control:
    total = get_total_vocab_count()
    error_ref = ft.Text("", color="#991b1b", weight=ft.FontWeight.W_700, size=13)

    n_field = ft.TextField(
        hint_text="Nhập số...",
        keyboard_type=ft.KeyboardType.NUMBER,
        text_style=ft.TextStyle(size=22, weight=ft.FontWeight.W_900, color=TEXT_DARK),
        hint_style=ft.TextStyle(color=TEXT_GRAY, size=22),
        border_color=TEXT_DARK,
        border_width=3,
        border_radius=0,
        filled=True,
        fill_color=BG_WHITE,
        width=180,
        text_align=ft.TextAlign.CENTER,
        content_padding=pad(h=16, v=14),
    )

    def on_start(e):
        error_ref.value = ""
        try:
            if total == 0:
                raise ValueError("Kho từ vựng hiện đang trống. Hãy tạo bài học trước!")
            n = int(n_field.value or "0")
            if n <= 0:
                raise ValueError("Số phải lớn hơn 0")
            if n > total:
                raise ValueError(f"Chỉ có {total} từ trong kho")
            
            on_start_session("random_flashcard", n)
        except ValueError as ex:
            error_ref.value = str(ex)
        page.update()

    return ft.Column(
        [
            label_text("Luyện tập"),
            heading_text("Học ngẫu nhiên"),
            ft.Container(height=1, bgcolor=TEXT_DARK, margin=marg(top=6, bottom=20)),
            ft.Row([
                nb_card(
                    ft.Column([
                        ft.Text("CHỌN SỐ TỪ VỰNG NGẪU NHIÊN", size=13, weight=ft.FontWeight.W_700, color=TEXT_GRAY, style=ft.TextStyle(letter_spacing=1.5)),
                        ft.Container(height=6),
                        ft.Text(f"Tổng kho hiện có: {total} từ", size=13, color=TEXT_GRAY),
                        ft.Container(height=20),
                        n_field,
                        ft.Container(height=6),
                        error_ref,
                        ft.Container(height=20),
                        nb_button("Bắt đầu học", on_click=on_start, icon="🎲", bgcolor=TEXT_DARK, color=TEXT_WHITE, width=260),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=0),
                    padding=40, shadow_size="lg",
                )
            ], alignment=ft.MainAxisAlignment.CENTER),
        ],
        spacing=0, expand=True,
    )


