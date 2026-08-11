# -*- coding: utf-8 -*-
"""Baixa as ferramentas que o Dinfinity embute mas não versiona.

São três binários de terceiros — ffmpeg, ffprobe e a libmpv — que passam do
limite de 100 MB por arquivo do GitHub. Ficam fora do repositório e vêm daqui,
das fontes oficiais, para a mesma estrutura de pastas que o programa espera:

    bin/ffmpeg.exe        gravação e exportação
    bin/ffprobe.exe       leitura de duração e dimensões
    rd/mpvlib/libmpv-2.dll   som, voz e a prévia do editor

Uso:  python ferramentas.py
"""
from __future__ import annotations

import io
import os
import shutil
import sys
import tempfile
import urllib.request
import zipfile

RAIZ = os.path.dirname(os.path.abspath(__file__))

FFMPEG = ("https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
          "ffmpeg-n8.1-latest-win64-gpl-8.1.zip")
MPV = ("https://github.com/shinchiro/mpv-winbuild-cmake/releases/latest/"
       "download/mpv-dev-x86_64.7z")


def _baixar(url, descricao):
    print(f"  baixando {descricao}...")
    print(f"    {url}")
    with urllib.request.urlopen(url) as resposta:
        return resposta.read()


def _ja_tem(caminho):
    return os.path.isfile(caminho) and os.path.getsize(caminho) > 1024


def instalar_ffmpeg(forcar=False):
    destino = os.path.join(RAIZ, "bin")
    alvos = [os.path.join(destino, n) for n in ("ffmpeg.exe", "ffprobe.exe")]
    if not forcar and all(_ja_tem(a) for a in alvos):
        print("  ffmpeg e ffprobe já estão em bin/ — pulando.")
        return True
    os.makedirs(destino, exist_ok=True)
    dados = _baixar(FFMPEG, "ffmpeg + ffprobe (~168 MB)")
    with zipfile.ZipFile(io.BytesIO(dados)) as z:
        achados = 0
        for item in z.infolist():
            nome = os.path.basename(item.filename)
            if nome in ("ffmpeg.exe", "ffprobe.exe"):
                with z.open(item) as origem, open(os.path.join(destino, nome), "wb") as saida:
                    shutil.copyfileobj(origem, saida)
                print(f"    -> bin/{nome}")
                achados += 1
    if achados < 2:
        print("  ERRO: não achei os dois executáveis dentro do pacote.")
        return False
    return True


def instalar_libmpv(forcar=False):
    destino = os.path.join(RAIZ, "rd", "mpvlib")
    alvo = os.path.join(destino, "libmpv-2.dll")
    if not forcar and _ja_tem(alvo):
        print("  libmpv-2.dll já está em rd/mpvlib/ — pulando.")
        return True
    try:
        import py7zr  # noqa: F401
    except ImportError:
        print("  A libmpv vem num .7z e falta a biblioteca para abrir.")
        print("  Instale com:  pip install py7zr")
        print(f"  Ou baixe à mão e ponha a DLL em rd/mpvlib/:\n    {MPV}")
        return False
    import py7zr

    os.makedirs(destino, exist_ok=True)
    dados = _baixar(MPV, "libmpv (~31 MB)")
    with tempfile.TemporaryDirectory() as temp:
        pacote = os.path.join(temp, "mpv-dev.7z")
        with open(pacote, "wb") as fh:
            fh.write(dados)
        with py7zr.SevenZipFile(pacote, "r") as z:
            nomes = [n for n in z.getnames() if n.lower().endswith("libmpv-2.dll")]
            if not nomes:
                print("  ERRO: não achei a libmpv-2.dll dentro do pacote.")
                return False
            z.extract(temp, targets=nomes)
            shutil.copy(os.path.join(temp, nomes[0]), alvo)
    print("    -> rd/mpvlib/libmpv-2.dll")
    return True


def main():
    forcar = "--forcar" in sys.argv
    print("Ferramentas do Dinfinity")
    print("=" * 60)
    ok = instalar_ffmpeg(forcar)
    ok = instalar_libmpv(forcar) and ok
    print("=" * 60)
    if ok:
        print("Tudo pronto. Rode o programa com:  pythonw Dinfinity.pyw")
    else:
        print("Faltou alguma coisa — veja as mensagens acima.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
