# -*- coding: utf-8 -*-
"""Automação de envio de mensagens para o chat flutuante do TikTok LIVE Studio.

Portado do LiveTexts: usa ctypes/win32 para clicar no campo de texto, colar a
mensagem e clicar na setinha de enviar. Requer o Dinfinity rodando como
Administrador (o Live Studio roda elevado e o UIPI bloqueia mouse de processos
não elevados).
"""
import ctypes
from ctypes import wintypes
import time

# Instâncias próprias, e não ctypes.windll.*: aquele objeto é compartilhado com
# qualquer outra biblioteca do processo (uiautomation, comtypes), e as
# assinaturas declaradas logo abaixo iriam junto para elas.
user32 = ctypes.WinDLL("user32")
kernel32 = ctypes.WinDLL("kernel32")

# Sem declarar os tipos, o ctypes assume que toda função devolve um int de 32
# bits. Os handles do Windows cabem nisso, mas o ponteiro que o GlobalLock
# devolve não: num processo de 64 bits ele vem truncado e o memmove seguinte
# escreve num endereço inventado (violação de acesso no meio da live).
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalLock.restype = wintypes.LPVOID
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalUnlock.restype = wintypes.BOOL
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalFree.restype = wintypes.HGLOBAL
kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]

try:
    if not user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
        user32.SetProcessDPIAware()
except AttributeError:
    user32.SetProcessDPIAware()

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
VK_CONTROL, VK_V, VK_F8 = 0x11, 0x56, 0x77
KEYEVENTF_KEYUP = 0x0002
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
SW_RESTORE = 9


def window_process_name(hwnd):
    process_id = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
    process = kernel32.OpenProcess(0x1000, False, process_id.value)
    if not process:
        return ""
    try:
        buffer = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buffer))
        if kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
            return buffer.value.split("\\")[-1].rsplit(".", 1)[0]
    finally:
        kernel32.CloseHandle(process)
    return ""


def is_tiktok_live_window(hwnd):
    return "tiktok live studio" in window_process_name(hwnd).lower()


def find_tiktok_live_windows():
    found = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def collect(hwnd, _):
        if user32.IsWindowVisible(hwnd) and is_tiktok_live_window(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, len(buffer))
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            found.append((buffer.value, hwnd, rect.right - rect.left, rect.bottom - rect.top))
        return True

    user32.EnumWindows(collect, 0)
    return found


def find_floating_chat():
    """A janela visível do Live Studio com a menor área costuma ser o chat flutuante."""
    candidates = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def collect(hwnd, _):
        if user32.IsWindowVisible(hwnd) and is_tiktok_live_window(hwnd):
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            width, height = rect.right - rect.left, rect.bottom - rect.top
            if width >= 100 and height >= 100:
                candidates.append((width * height, hwnd))
        return True

    user32.EnumWindows(collect, 0)
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def window_rect(hwnd):
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect


def bring_to_foreground(hwnd):
    user32.ShowWindow(hwnd, SW_RESTORE)
    foreground = user32.GetForegroundWindow()
    foreground_thread = user32.GetWindowThreadProcessId(foreground, None)
    target_thread = user32.GetWindowThreadProcessId(hwnd, None)
    current_thread = kernel32.GetCurrentThreadId()
    attached = False
    if foreground_thread != current_thread and foreground_thread != target_thread:
        attached = bool(user32.AttachThreadInput(current_thread, foreground_thread, True))
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(current_thread, foreground_thread, False)


def left_click_at(x, y):
    user32.SetCursorPos(int(x), int(y))
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def double_click_at(x, y):
    user32.SetCursorPos(int(x), int(y))
    for _ in range(2):
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def copy_to_clipboard(text):
    data = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(data)
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
    if not handle:
        raise OSError("Não foi possível reservar a área de transferência.")
    pointer = kernel32.GlobalLock(handle)
    ctypes.memmove(pointer, data, size)
    kernel32.GlobalUnlock(handle)
    if not user32.OpenClipboard(None):
        kernel32.GlobalFree(handle)
        raise OSError("Não foi possível abrir a área de transferência.")
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)
            raise OSError("Não foi possível copiar a mensagem.")
        handle = None
    finally:
        user32.CloseClipboard()
        if handle:
            kernel32.GlobalFree(handle)


def press_key(*keys):
    for key in keys:
        user32.keybd_event(key, 0, 0, 0)
    for key in reversed(keys):
        user32.keybd_event(key, 0, KEYEVENTF_KEYUP, 0)


def rect_center(rect):
    return (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2


def uia_chat_info(hwnd):
    """Varre a árvore UIA do chat flutuante. Retorna (campo_rect, enviar_rect,
    bloqueado) ou None se o uiautomation não estiver disponível."""
    try:
        import uiautomation as auto
    except Exception:
        return None
    try:
        control = auto.ControlFromHandle(hwnd)
    except Exception:
        return None
    if control is None:
        return None
    field_rect = None
    send_rect = None
    edit_rect = None
    blocked = False
    stack = [control]
    visited = 0
    while stack and visited < 1000:
        current = stack.pop()
        visited += 1
        try:
            ctype = current.ControlTypeName
            name = (current.Name or "").lower()
        except Exception:
            continue
        try:
            rect = current.BoundingRectangle
            rect = (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
        except Exception:
            rect = None
        if ctype == "ButtonControl" and "enviar coment" in name:
            send_rect = rect
        elif ctype in ("EditControl", "DocumentControl") and rect:
            # O campo de digitar. Achado assim, não é preciso marcar a posição
            # à mão — e continua valendo se a janela do chat for redimensionada.
            if edit_rect is None or _area(rect) > _area(edit_rect):
                edit_rect = rect
        elif ctype == "TextControl" and rect and (
                ("live" in name and "coment" in name)
                or "off-line" in name or "offline" in name):
            blocked = True
            field_rect = rect
        try:
            children = current.GetChildren()
        except Exception:
            children = []
        stack.extend(children)
    return field_rect or edit_rect, send_rect, blocked


def _area(rect):
    return max(0, rect[2] - rect[0]) * max(0, rect[3] - rect[1])


class ChatSender:
    """Lógica de envio. Recebe os offsets configurados e um provedor de UIA
    (a GUI entrega pedidos executados na thread principal via request_uia)."""

    def __init__(self):
        self.chat_hwnd = None
        self.input_offset = None
        self.send_offset = None
        self.request_uia = None  # callable(hwnd) -> info, setado pela GUI

    def resolve_chat_window(self):
        if self.chat_hwnd and user32.IsWindow(self.chat_hwnd):
            return self.chat_hwnd
        found = find_floating_chat()
        if found:
            self.chat_hwnd = found
            return found
        return None

    def field_point(self, rect):
        return rect.left + self.input_offset[0], rect.bottom - self.input_offset[1]

    def send_point(self, rect):
        return rect.left + self.send_offset[0], rect.bottom - self.send_offset[1]

    def send_once(self, message):
        """Envia uma mensagem. Levanta RuntimeError com a explicação em caso de erro.

        O campo e o botão são procurados primeiro na árvore de acessibilidade
        do Live Studio, que acompanha a janela se ela mudar de tamanho. As
        posições marcadas à mão são a reserva de quando essa leitura não
        devolve nada.
        """
        hwnd = self.resolve_chat_window()
        if not hwnd:
            raise RuntimeError("Janela do chat não encontrada. Abra o TikTok LIVE Studio.")
        rect = window_rect(hwnd)
        bring_to_foreground(hwnd)
        time.sleep(0.25)

        info = None
        if self.request_uia is not None:
            info = self.request_uia(hwnd)
        if info is not None and info[2]:
            raise RuntimeError("Campo de mensagem bloqueado (live fechada). "
                               "Aguardando a live estar aberta.")

        ponto = None
        if info is not None and info[0]:
            ponto = rect_center(info[0])
        elif self.input_offset:
            ponto = self.field_point(rect)
        if ponto is None:
            raise RuntimeError("Não achei o campo de mensagem. Marque as posições "
                               "à mão pelo botão da aba.")
        left_click_at(*ponto)
        time.sleep(0.4)

        copy_to_clipboard(message)
        press_key(VK_CONTROL, VK_V)
        time.sleep(0.35)

        sx = sy = None
        if info is not None and info[1]:
            sx, sy = rect_center(info[1])
        elif self.send_offset:
            sx, sy = self.send_point(rect)
        if sx is None:
            raise RuntimeError("Não achei a setinha de enviar. Marque as posições "
                               "à mão pelo botão da aba.")
        left_click_at(sx, sy)
        time.sleep(0.1)
