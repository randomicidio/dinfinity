# -*- coding: utf-8 -*-
"""Tema visual compartilhado.

O Dinfinity usa widgets customtkinter, mas o Puzzle (Jogo Perfil) e o Gravador
embutido (ReplayDownloader) são construídos com ttk/tk. Sem um tema próprio,
essas partes herdam o tema claro do Windows e destoam do resto. Aqui moram as
cores oficiais do Dinfinity e um tema ttk que as espelha, para o programa inteiro
parecer um só.

Também expõe helpers para que os trechos em tk puro (diálogos, canvas) usem as
mesmas cores em vez de valores fixos de tema claro.
"""
import tkinter.ttk as ttk

# Cores oficiais (modo escuro) — espelham o customtkinter padrão.
BG = "#2b2b2b"
BG_ALT = "#242424"
BG_CARD = "#333333"
FG = "#dce4ee"
FG_MUTED = "#9aa3ad"
ACCENT = "#c792ea"
INPUT_BG = "#1e1e1e"
SELECT_BG = "#3f3350"

# Paleta clara, usada quando o Dinfinity roda em tema claro.
BG_LIGHT = "#ebebeb"
BG_LIGHT_ALT = "#f5f5f5"
FG_LIGHT = "#1f1f1f"
FG_MUTED_LIGHT = "#5b5b5b"
INPUT_BG_LIGHT = "#ffffff"
SELECT_BG_LIGHT = "#d9c7ee"


def is_dark(appearance: str) -> bool:
    return (appearance or "dark") == "dark"


def window_bg(appearance: str) -> str:
    return BG if is_dark(appearance) else BG_LIGHT


def text_fg(appearance: str) -> str:
    return FG if is_dark(appearance) else FG_LIGHT


def muted_fg(appearance: str) -> str:
    return FG_MUTED if is_dark(appearance) else FG_MUTED_LIGHT


def input_bg(appearance: str) -> str:
    return INPUT_BG if is_dark(appearance) else INPUT_BG_LIGHT


def select_bg(appearance: str) -> str:
    return SELECT_BG if is_dark(appearance) else SELECT_BG_LIGHT


def apply_ttk_theme(appearance: str = "dark"):
    """Configura o ttk.Style global para combinar com o tema do Dinfinity.

    Todo widget ttk/ttk-themed (Puzzle e ReplayDownloader embutidos) passa a
    respeitar o tema. O customtkinter não usa ttk, então não é afetado.
    """
    dark = is_dark(appearance)
    bg = BG if dark else BG_LIGHT
    bg_alt = BG_ALT if dark else BG_LIGHT_ALT
    card = BG_CARD if dark else "#ffffff"
    fg = FG if dark else FG_LIGHT
    muted = FG_MUTED if dark else FG_MUTED_LIGHT
    inp = INPUT_BG if dark else INPUT_BG_LIGHT
    sel = SELECT_BG if dark else SELECT_BG_LIGHT

    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        return

    f = ("Segoe UI", 10)
    f_bold = ("Segoe UI", 10, "bold")

    style.configure(".", background=bg, foreground=fg, fieldbackground=inp,
                    bordercolor=bg_alt, font=f, padding=2)
    style.map(".", background=[("active", card), ("pressed", card)])

    style.configure("TFrame", background=bg)
    style.configure("TLabel", background=bg, foreground=fg)
    style.configure("TLabelframe", background=bg, bordercolor=bg_alt)
    style.configure("TLabelframe.Label", background=bg, foreground=fg, font=f_bold)

    style.configure("TButton", background=card, foreground=fg, bordercolor=bg_alt,
                    focuscolor="none", padding=(12, 6))
    style.map("TButton",
              background=[("active", sel), ("pressed", sel)],
              foreground=[("disabled", muted)])

    style.configure("Rec.TButton", background="#b3402f", foreground="#ffffff",
                    bordercolor="#b3402f", focuscolor="none", padding=(18, 6))
    style.map("Rec.TButton",
              background=[("active", "#d15441"), ("pressed", "#8f3022")],
              foreground=[("disabled", "#8a8f98")])

    style.configure("TCheckbutton", background=bg, foreground=fg, focuscolor="none")
    style.map("TCheckbutton",
              background=[("active", bg)],
              foreground=[("disabled", muted)])

    style.configure("TEntry", fieldbackground=inp, foreground=fg,
                    insertcolor=fg, bordercolor=bg_alt)
    style.map("TEntry",
              fieldbackground=[("focus", inp)],
              bordercolor=[("focus", ACCENT)])

    style.configure("TSpinbox", fieldbackground=inp, foreground=fg,
                    insertcolor=fg, bordercolor=bg_alt, arrowsize=14)
    style.map("TSpinbox", bordercolor=[("focus", ACCENT)])

    style.configure("TNotebook", background=bg, bordercolor=bg_alt)
    style.configure("TNotebook.Tab",
                    background=bg_alt, foreground=fg, padding=(14, 7),
                    font=f_bold)
    # O clam traz padding próprio para a aba selecionada (6 4 6 2), o que a
    # deixa visivelmente menor que as demais. Padrão igual nos dois estados.
    style.map("TNotebook.Tab",
              padding=[("selected", (14, 7))],
              background=[("selected", card)],
              foreground=[("selected", "#ffffff")])

    style.configure("TScale", background=bg, troughcolor=inp)
    style.map("TScale", background=[("active", bg)])

    style.configure("TProgressbar", background=ACCENT, troughcolor=inp, bordercolor=bg)

    style.configure("Vertical.TScrollbar", background=bg_alt, troughcolor=bg,
                    bordercolor=bg, arrowsize=13)
    style.configure("Horizontal.TScrollbar", background=bg_alt, troughcolor=bg,
                    bordercolor=bg, arrowsize=13)

    style.configure("TSeparator", background=bg_alt)
    style.configure("Treeview", background=inp, fieldbackground=inp, foreground=fg,
                    bordercolor=bg_alt)
    style.configure("Treeview.Heading", background=bg_alt, foreground=fg, font=f_bold)

    style.configure("TCombobox", fieldbackground=inp, background=card,
                    foreground=fg, bordercolor=bg_alt, arrowcolor=fg)
    style.map("TCombobox",
              fieldbackground=[("readonly", inp)],
              bordercolor=[("focus", ACCENT)])

    style.configure("Muted.TLabel", foreground=muted)
    style.configure("Accent.TLabel", foreground=ACCENT)
