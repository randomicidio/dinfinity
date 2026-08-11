# -*- mode: python ; coding: utf-8 -*-
"""Receita do PyInstaller para o Dinfinity portátil.

O objetivo é um .exe que roda em qualquer Windows sem instalar nada: as
ferramentas (ffmpeg, ffprobe, libmpv), as fontes e o pacote de emojis viajam
dentro dele. Ao abrir, os recursos são extraídos para uma pasta temporária, e
`core/caminhos.py` sabe procurá-los tanto lá quanto ao lado do executável.

Para compilar:  pyinstaller Dinfinity.spec --noconfirm
"""
import os

RAIZ = os.path.abspath(SPECPATH)


def _se_existir(origem, destino):
    """Só entra na lista o que está no disco — o pacote não quebra por falta
    de um opcional, e a mensagem de erro do PyInstaller seria obscura."""
    caminho = os.path.join(RAIZ, origem)
    return [(caminho, destino)] if os.path.exists(caminho) else []


# --- o que viaja junto -----------------------------------------------------
binarios = (
    _se_existir("bin/ffmpeg.exe", "bin")
    + _se_existir("bin/ffprobe.exe", "bin")
    + _se_existir("rd/mpvlib/libmpv-2.dll", "mpvlib")
)

dados = (
    _se_existir("rd/assets/fonts/TikTokSans.ttf", "assets/fonts")
    + _se_existir("rd/assets/fonts/OFL.txt", "assets/fonts")
    + _se_existir("rd/assets/emoji.zip", "assets")
    + _se_existir("gifts_catalog.json", ".")
)

# O TikTokLive gera os protos na primeira carga e o edge_tts descobre as vozes
# em tempo de execução: sem estes, o PyInstaller não enxerga a dependência.
ocultos = [
    "TikTokLive", "edge_tts", "mpv", "uiautomation", "comtypes",
    "win32print", "win32ui", "win32con", "PIL._tkinter_finder",
]

a = Analysis(
    ["Dinfinity.pyw"],
    pathex=[RAIZ],
    binaries=binarios,
    datas=dados,
    hiddenimports=ocultos,
    hookspath=[],
    runtime_hooks=[],
    # O python-vlc saiu do projeto (a libmpv o substituiu); excluir evita que
    # ele entre de carona por uma importação antiga em algum canto.
    excludes=["vlc", "matplotlib", "numpy.distutils", "pytest", "setuptools"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Dinfinity",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    # Sem console: é um programa de janela, e o console preto atrás dela é
    # justamente o que o .pyw evita quando se roda pelo código-fonte.
    console=False,
    disable_windowed_traceback=False,
    icon=os.path.join(RAIZ, "assets", "dinfinity.ico"),
)
