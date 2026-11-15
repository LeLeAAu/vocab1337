"""Overview and entry points into learning."""
import flet as ft
from components.theme import (
    BG_PAGE, BG_WHITE, BG_SIDEBAR, TEXT_DARK, TEXT_GRAY, TEXT_WHITE,
    CLR_GREEN, CLR_BLUE, CLR_YELLOW, CLR_RED, SHADOW_SM, SHADOW_MD, SHADOW_LG,
    mk_border, pad, marg, nb_button, nb_card, label_text, heading_text,
)

from database import get_total_vocab_count, get_total_lesson_count, get_mastered_count

def build_dashboard(page: ft.Page, on_navigate, on_vocab_list) -> ft.Control:
    vocab_count  = get_total_vocab_count()
    lesson_count = get_total_lesson_count()
    mastered     = get_mastered_count()

    def stat_card(icon: ft.IconData, value: str, lbl: str, border_c: str, on_click=None, tooltip: str = None) -> ft.Container:
        return ft.Container(
            content=ft.Column(
                [
                    ft.Icon(icon, size=26, color=border_c),
                    ft.Text(value, size=34, weight=ft.FontWeight.W_900, color=TEXT_DARK),
                    ft.Container(height=2),
                    ft.Text(lbl.upper(), size=11, weight=ft.FontWeight.W_700, color=TEXT_GRAY, style=ft.TextStyle(letter_spacing=1.5)),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=4,
            ),
            bgcolor=BG_WHITE,
            border=mk_border(3, border_c),
            shadow=ft.BoxShadow(offset=ft.Offset(3, 3), blur_radius=0, color=border_c),
            padding=pad(h=20, v=22),
            col={"xs": 12, "md": 4},
            on_click=on_click,
            ink=True if on_click else False,
            tooltip=tooltip,
        )

    tip_card = nb_card(
        ft.Row([
            ft.Container(
                content=ft.Icon(ft.Icons.LIGHTBULB_OUTLINE_ROUNDED, size=22, color=TEXT_DARK),
                bgcolor=CLR_YELLOW,
                border=mk_border(2, TEXT_DARK),
                padding=pad(all_=10),
            ),
            ft.Column([
                ft.Text("TẠO BÀI HỌC ĐẦU TIÊN" if lesson_count == 0 else "TIẾP TỤC HỌC", size=14, weight=ft.FontWeight.W_900, color=TEXT_DARK),
                ft.Text("Thêm từ vựng bằng tay, nhập JSON hoặc tạo bài học với AI." if lesson_count == 0 else "Ôn lại flashcard hoặc luyện đọc hiểu trong bài học của bạn.", size=13, color=TEXT_GRAY),
            ], spacing=4, expand=True),
            nb_button("TẠO BÀI HỌC" if lesson_count == 0 else "HỌC NGAY", on_click=lambda e: on_navigate("create" if lesson_count == 0 else "lessons"), bgcolor=TEXT_DARK, color=TEXT_WHITE)
        ], spacing=16),
        shadow_size="sm",
    )

    return ft.Column(
        [
            label_text("Tổng quan"),
            heading_text("Góc học tập"),
            ft.Container(height=1, bgcolor=TEXT_DARK, margin=marg(top=6, bottom=20)),
            ft.ResponsiveRow(
                [
                    stat_card(
                        ft.Icons.ABC_ROUNDED,
                        str(vocab_count),
                        "Từ vựng",
                        TEXT_DARK,
                        on_click=lambda e: on_vocab_list(page, initial_mode="all", on_navigate=on_navigate),
                        tooltip="Xem danh sách từ vựng trong tất cả các bài học",
                    ),
                    stat_card(
                        ft.Icons.MENU_BOOK_ROUNDED,
                        str(lesson_count),
                        "Bài học",
                        TEXT_DARK,
                        on_click=lambda e: on_navigate("lessons"),
                        tooltip="Chuyển sang màn hình Bài học",
                    ),
                    stat_card(
                        ft.Icons.TASK_ALT_ROUNDED,
                        str(mastered),
                        "Đã thuộc",
                        "#166534",
                        on_click=lambda e: on_vocab_list(page, initial_mode="mastered", on_navigate=on_navigate),
                        tooltip="Xem danh sách từ vựng đã thuộc (Điểm >= 6)",
                    ),
                ],
                spacing=20,
            ),
            ft.Container(height=16),
            tip_card,
        ],
        spacing=0,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )


