# -*- coding: utf-8 -*-
"""Deixa só um Dinfinity aberto por vez.

Abrir o programa duas vezes daria dois monitores na mesma live (eventos em
dobro), dois gravadores disputando o mesmo arquivo e dois servidores tentando a
mesma porta do Jogo Perfil. Aqui a segunda abertura simplesmente traz a janela
que já existe para a frente e sai, sem mensagem nenhuma.

O controle usa duas peças:

  - um **mutex nomeado** do Windows, que é a resposta confiável para "já tem
    um rodando?" — ele some sozinho quando o processo morre, então um
    fechamento forçado não deixa o programa travado para sempre;
  - um **arquivo com o PID** da instância viva, para a segunda saber de quem é
    a janela que deve trazer para a frente.

A conferência acontece *antes* da elevação (ver Dinfinity.pyw): sem isso o
usuário veria o pedido do UAC para, em seguida, nada acontecer.
"""
import ctypes
import os
from ctypes import wintypes

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARQUIVO_PID = os.path.join(APP_DIR, ".instancia")
NOME_MUTEX = "Dinfinity_UnicaInstancia_9f2a"

ERROR_ALREADY_EXISTS = 183
SYNCHRONIZE = 0x00100000
SW_RESTORE = 9

_mutex = None  # segurado enquanto o processo viver

user32 = ctypes.WinDLL("user32")
# use_last_error: é o código de erro do CreateMutexW que diz se a vaga já
# estava ocupada, e sem isso ele se perde entre uma chamada e outra.
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CreateMutexW.argtypes = [wintypes.LPCVOID, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.OpenMutexW.restype = wintypes.HANDLE
kernel32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def outra_ja_aberta() -> bool:
    """Só olha, sem criar nada: serve para o processo que ainda vai elevar."""
    try:
        h = kernel32.OpenMutexW(SYNCHRONIZE, False, NOME_MUTEX)
    except Exception:  # noqa: BLE001
        return False
    if not h:
        return False
    kernel32.CloseHandle(h)
    return True


def marcar() -> bool:
    """Reserva a vaga desta instância. False = já havia outra.

    Chamado pelo processo que de fato vai abrir a janela (já elevado). O mutex
    fica segurado numa variável de módulo porque soltar o handle liberaria a
    vaga com o programa ainda aberto.
    """
    global _mutex
    try:
        ctypes.set_last_error(0)
        _mutex = kernel32.CreateMutexW(None, False, NOME_MUTEX)
        if not _mutex:
            return True                      # sem mutex, não trava o programa
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            return False
    except Exception:  # noqa: BLE001
        return True
    try:
        with open(ARQUIVO_PID, "w", encoding="utf-8") as fh:
            fh.write(str(os.getpid()))
    except OSError:
        pass
    return True


def liberar() -> None:
    """Some com o arquivo de PID ao fechar (o mutex o Windows já recolhe)."""
    try:
        if os.path.exists(ARQUIVO_PID):
            os.remove(ARQUIVO_PID)
    except OSError:
        pass


def soltar_vaga() -> None:
    """Larga a vaga com o processo ainda vivo.

    Serve para o relançamento como Administrador (ver core/admin.py): a nova
    instância confere o mutex antes de o UAC responder, e encontraria a vaga
    ocupada por este processo, que ainda não fechou. Quem chama é responsável
    por sair logo em seguida — ou por chamar `marcar()` de novo, se o
    relançamento não acontecer.
    """
    global _mutex
    if _mutex:
        try:
            kernel32.CloseHandle(_mutex)
        except Exception:  # noqa: BLE001
            pass
        _mutex = None
    liberar()


def _pid_da_instancia():
    try:
        with open(ARQUIVO_PID, "r", encoding="utf-8") as fh:
            return int((fh.read() or "0").strip())
    except (OSError, ValueError):
        return 0


def focar() -> bool:
    """Traz a janela da instância que já está aberta para a frente.

    Best-effort: se o Windows recusar (a outra roda elevada e esta não), a
    segunda abertura apenas encerra em silêncio, que é o combinado.
    """
    pid = _pid_da_instancia()
    if not pid:
        return False

    encontrada = []
    tipo = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @tipo
    def visitar(hwnd, _lparam):
        dono = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(dono))
        if dono.value == pid and user32.IsWindowVisible(hwnd):
            # A janela principal é a que tem título; as auxiliares do Tk não têm.
            if user32.GetWindowTextLengthW(hwnd) > 0:
                encontrada.append(hwnd)
                return False
        return True

    try:
        user32.EnumWindows(visitar, 0)
    except Exception:  # noqa: BLE001
        return False
    if not encontrada:
        return False

    hwnd = encontrada[0]
    try:
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:  # noqa: BLE001
        return False
