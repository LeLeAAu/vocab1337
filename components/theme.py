"""Shared Neubrutalism palette and controls. No page or application state."""
import flet as ft

BG_PAGE    = "#f3f4f6"
BG_WHITE   = "#ffffff"
BG_SIDEBAR = "#111827"
TEXT_DARK  = "#111827"
TEXT_GRAY  = "#6b7280"
TEXT_WHITE = "#ffffff"

CLR_GREEN  = "#bbf7d0"
CLR_BLUE   = "#bfdbfe"
CLR_YELLOW = "#fef08a"
CLR_RED    = "#fecaca"

SHADOW_SM  = ft.BoxShadow(offset=ft.Offset(4, 4),  blur_radius=0, color=TEXT_DARK)
SHADOW_MD  = ft.BoxShadow(offset=ft.Offset(8, 8),  blur_radius=0, color=TEXT_DARK)
SHADOW_LG  = ft.BoxShadow(offset=ft.Offset(12, 12), blur_radius=0, color=TEXT_DARK)

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


def marg(top=0, bottom=0, left=0, right=0) -> ft.Margin:
    return ft.Margin(left=left, top=top, right=right, bottom=bottom)


def nb_button(label: str, icon: str = "", on_click=None, bgcolor=BG_WHITE, color=TEXT_DARK, width=None, *, text_size=12, h_padding=16, shadow=SHADOW_SM) -> ft.Container:
    row_items = []
    if icon:
        row_items.append(ft.Text(icon, size=15, color=color))
    row_items.append(ft.Text((label or "").upper(), size=text_size, weight=ft.FontWeight.W_800, color=color))

    return ft.Container(
        content=ft.Row(row_items, spacing=8, alignment=ft.MainAxisAlignment.CENTER),
        bgcolor=bgcolor,
        border=mk_border(2, TEXT_DARK),
        shadow=shadow,
        padding=pad(h=h_padding, v=12),
        width=width,
        on_click=on_click,
        ink=True,
    )


def nb_card(content: ft.Control, shadow_size: str = "md", bgcolor=BG_WHITE, padding=24, *, border_color=TEXT_DARK, border_width=3) -> ft.Container:
    shadow = {"sm": SHADOW_SM, "md": SHADOW_MD, "lg": SHADOW_LG}.get(shadow_size, SHADOW_MD)
    return ft.Container(
        content=content,
        bgcolor=bgcolor,
        border=mk_border(border_width, border_color),
        border_radius=0,
        shadow=shadow,
        padding=padding,
    )


def label_text(text: str) -> ft.Text:
    return ft.Text(text.upper(), size=11, weight=ft.FontWeight.W_700, color=TEXT_GRAY, style=ft.TextStyle(letter_spacing=1.8))


def heading_text(text: str, size: int = 36) -> ft.Text:
    return ft.Text(text.upper(), size=size, weight=ft.FontWeight.W_900, color=TEXT_DARK)




def close_dialog(dialog):
    """Dismiss this dialog, even if a SnackBar is now at the top of the stack."""
    dialog.open = False
    dialog.update()
