# -*- coding: utf-8 -*-
"""Onde ficam as coisas do Dinfinity, rodando como script ou como .exe.

O objetivo é o programa ser portátil: descompactar e rodar. Por isso nada aqui
devolve caminho de instalação do sistema — as ferramentas auxiliares vêm de
`bin/` ao lado do programa, e o que é gerado (config, temporários) fica em
`dados/`, na mesma pasta.

Empacotado com PyInstaller o programa vive em dois lugares ao mesmo tempo: os
recursos embutidos são extraídos para uma pasta temporária (`sys._MEIPASS`),
enquanto o executável está onde o usuário o deixou. O que é gravado tem que ir
para perto do executável, nunca para a temporária — que some ao fechar.
"""
import os
import shutil
import sys

IS_FROZEN = getattr(sys, "frozen", False)
IS_WINDOWS = os.name == "nt"


def app_dir():
    """Pasta do programa: onde está o .exe, ou a raiz do projeto."""
    if IS_FROZEN:
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def bundle_dir():
    """Pasta dos recursos embutidos no executável."""
    return getattr(sys, "_MEIPASS", app_dir())


APP_DIR = app_dir()


def _gravavel(caminho):
    try:
        os.makedirs(caminho, exist_ok=True)
        teste = os.path.join(caminho, ".escrita_teste")
        with open(teste, "w") as fh:
            fh.write("ok")
        os.remove(teste)
        return True
    except OSError:
        return False


_dados = None


def dados_dir():
    """Onde gravar o que o programa produz (config, miniaturas, temporários).

    Fica ao lado do programa — é o que faz o uso portátil funcionar, com tudo
    numa pasta só. Se essa pasta for somente leitura (Program Files, pendrive
    protegido), cai para a área do usuário em vez de falhar.
    """
    global _dados
    if _dados is not None:
        return _dados
    preferida = os.path.join(APP_DIR, "dados")
    if _gravavel(preferida):
        _dados = preferida
    else:
        base = (os.environ.get("APPDATA") or os.path.expanduser("~")) if IS_WINDOWS \
            else (os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"))
        _dados = os.path.join(base, "Dinfinity")
        os.makedirs(_dados, exist_ok=True)
    return _dados


def dados(*partes):
    """Caminho dentro de `dados/`, com as pastas do meio já criadas."""
    destino = os.path.join(dados_dir(), *partes)
    try:
        os.makedirs(os.path.dirname(destino) if os.path.splitext(destino)[1] else destino,
                    exist_ok=True)
    except OSError:
        pass
    return destino


def temp_dir():
    """Temporários do programa (áudio do TTS, jobs de impressão)."""
    return dados("temp")


def recurso(*partes):
    """Caminho de um recurso que viaja junto (fonte, ícone)."""
    return os.path.join(bundle_dir(), *partes)


def achar_binario(nome):
    """Acha um executável auxiliar: embutido primeiro, sistema depois.

    A cópia embutida vem antes de propósito — garante a mesma versão em
    qualquer máquina, sem depender do que o usuário tenha instalado. O PATH
    fica como rede de segurança para quem roda a partir do código-fonte sem ter
    baixado os binários.
    """
    alvo = nome + (".exe" if IS_WINDOWS else "")
    for pasta in (os.path.join(APP_DIR, "bin"), os.path.join(bundle_dir(), "bin"),
                  bundle_dir(), APP_DIR):
        caminho = os.path.join(pasta, alvo)
        if os.path.isfile(caminho):
            return caminho
    return shutil.which(nome)


def achar_libmpv():
    """A libmpv embutida. Usada pelo som, pelo TTS e pela prévia do editor."""
    nomes = ("libmpv-2.dll", "mpv-2.dll", "mpv-1.dll") if IS_WINDOWS \
        else ("libmpv.dylib", "libmpv.so.2", "libmpv.so")
    pastas = (os.path.join(APP_DIR, "rd", "mpvlib"), os.path.join(APP_DIR, "mpvlib"),
              os.path.join(bundle_dir(), "mpvlib"), bundle_dir(), APP_DIR)
    for pasta in pastas:
        for nome in nomes:
            caminho = os.path.join(pasta, nome)
            if os.path.isfile(caminho):
                return caminho
    return ""


def fonte(nome="TikTokSans.ttf"):
    """Uma fonte que viaja junto do programa, para o cartão de impressão."""
    for pasta in (os.path.join(APP_DIR, "rd", "assets", "fonts"),
                  os.path.join(bundle_dir(), "assets", "fonts"),
                  os.path.join(APP_DIR, "assets", "fonts")):
        caminho = os.path.join(pasta, nome)
        if os.path.isfile(caminho):
            return caminho
    return ""
