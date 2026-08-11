# -*- coding: utf-8 -*-
"""Fila de log thread-safe. As threads de fundo gravam aqui; a GUI drena
periodicamente (after()) e exibe no console de texto.

Cada linha tem um *nível* (que decide a cor) e, a partir dele, uma *categoria*
(que decide se ela aparece). A aba Conexão liga e desliga categorias, então os
níveis precisam ser específicos o bastante para separar o que interessa: um
presente não pode cair no mesmo balaio que "monitor iniciado".
"""
import threading
import time

_lock = threading.Lock()
_pending = []

LEVEL_COLORS = {
    "info": "white",
    "error": "#ff6b6b",
    "warning": "#ffb86c",
    "gift": "#c792ea",
    "chat": "#9ad1d4",
    "tts": "#5ff0b0",
    "sound": "#7ec4f0",
    "reacao": "#f0c674",
    "acao": "#7ec4f0",
    "success": "#7bed9f",
    "system": "#8a8f98",
}

# categoria -> (rótulo na GUI, níveis que caem nela)
CATEGORIAS = {
    "chat": ("Chat", ("chat",)),
    "presentes": ("Presentes", ("gift",)),
    "reacoes": ("Reações", ("reacao", "acao", "sound")),
    "voz": ("Voz (TTS)", ("tts",)),
    "sistema": ("Sistema", ("system", "info", "success")),
    "erros": ("Erros e avisos", ("error", "warning")),
}

CATEGORIA_DE = {nivel: chave
                for chave, (_rotulo, niveis) in CATEGORIAS.items()
                for nivel in niveis}


def categoria(nivel):
    """A categoria de um nível. O que não estiver mapeado vai para Sistema."""
    return CATEGORIA_DE.get(nivel, "sistema")


def log(level, message):
    with _lock:
        _pending.append((time.strftime("%H:%M:%S"), level, message))


def drain():
    with _lock:
        items = _pending[:]
        _pending.clear()
        return items


def clear():
    with _lock:
        _pending.clear()
