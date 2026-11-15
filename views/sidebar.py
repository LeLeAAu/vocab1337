"""Application navigation shell."""
import flet as ft
from components.theme import (
    BG_PAGE, BG_WHITE, BG_SIDEBAR, TEXT_DARK, TEXT_GRAY, TEXT_WHITE,
    CLR_GREEN, CLR_BLUE, CLR_YELLOW, CLR_RED, SHADOW_SM, SHADOW_MD, SHADOW_LG,
    mk_border, pad, marg, nb_button, nb_card, label_text, heading_text,
)

NAV_ITEMS = [
    ("dashboard", ft.Icons.DASHBOARD_OUTLINED, "DASHBOARD"),
    ("lessons",   ft.Icons.MENU_BOOK_ROUNDED, "BÀI HỌC"),
    ("random",    ft.Icons.SHUFFLE_ROUNDED, "HỌC NGẪU NHIÊN"),
    ("create",    ft.Icons.ADD_BOX_OUTLINED, "TẠO BÀI HỌC"),
    ("settings",  ft.Icons.SETTINGS_OUTLINED, "CÀI ĐẶT"),
]

def build_sidebar(current: str, on_navigate, on_open_logs=None, compact=False) -> ft.Container:
    def nav_item(route: str, icon: ft.IconData, label: str) -> ft.Container:
        active = route == current

        def on_hover(e):
            if not active:
                e.control.bgcolor = "#1f2937" if e.data == "true" else BG_SIDEBAR
                e.control.update()

        return ft.Container(
            content=ft.Row([
                ft.Icon(icon, size=20, color=TEXT_DARK if active else "#cbd5e1"),
            ] + ([] if compact else [
                ft.Text(label, size=12, weight=ft.FontWeight.W_800, color=TEXT_DARK if active else TEXT_WHITE),
            ]), spacing=10, alignment=ft.MainAxisAlignment.CENTER if compact else ft.MainAxisAlignment.START),
            tooltip=label,
            data=route,
            bgcolor=BG_WHITE if active else BG_SIDEBAR,
            border=mk_border(2, TEXT_DARK) if active else mk_border(0, "transparent"),
            padding=pad(h=12 if compact else 16, v=13),
            height=52,
            width=64 if compact else 186,
            margin=marg(left=12, right=12),
            on_click=lambda e, r=route: on_navigate(r),
            on_hover=on_hover,
            ink=False,
            animate=ft.Animation(100, ft.AnimationCurve.EASE_OUT),
        )

    # Thanh nhấn cố định; không giãn theo chiều cao sidebar.
    rainbow = ft.Container(
        gradient=ft.LinearGradient(
            begin=ft.Alignment(-1, 0),
            end=ft.Alignment(1, 0),
            colors=["#bfdbfe", "#c4b5fd", "#bbf7d0"],
        ),
        height=5,
    )

    return ft.Container(
        content=ft.Column(
            [
                rainbow,
                ft.Container(
                    content=ft.Column([
                        ft.Text("V" if compact else "VOCAB", size=24, weight=ft.FontWeight.W_900, color=TEXT_WHITE),
                        ft.Text("1337",  size=24, weight=ft.FontWeight.W_900, color=CLR_YELLOW),
                    ], spacing=0, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    alignment=ft.Alignment(0, 0),
                    padding=pad(top=26, bottom=12),
                ),
                ft.Container(height=20),
                ft.Container(height=1, bgcolor="#374151"),
                ft.Container(height=10),
                *[nav_item(r, i, l) for r, i, l in NAV_ITEMS],
                ft.Container(expand=True),
                ft.Container(height=1, bgcolor="#374151"),
                ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.TERMINAL_ROUNDED, size=16, color="#cbd5e1"),
                        ft.Text("NHẬT KÝ HỆ THỐNG", visible=not compact, size=10, weight=ft.FontWeight.W_800, color=TEXT_WHITE),
                    ], spacing=8, alignment=ft.MainAxisAlignment.CENTER),
                    bgcolor="#1f2937",
                    border=mk_border(1, "#374151"),
                    padding=pad(h=8, v=6),
                    margin=marg(left=10, right=10, top=6, bottom=2),
                    on_click=lambda e: on_open_logs() if on_open_logs else None,
                    ink=True,
                    tooltip="Mở trình xem nhật ký ứng dụng thời gian thực (Live Log Viewer)",
                ),
                ft.Container(
                    content=ft.Text("v0.1.0-alpha", visible=not compact, size=10, color="#6b7280"),
                    padding=pad(all_=10),
                    alignment=ft.Alignment(0, 0),
                ),
            ],
            spacing=4,
            expand=True,
        ),
        bgcolor=BG_SIDEBAR,
        width=88 if compact else 210,
    )


