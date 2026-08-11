# -*- coding: utf-8 -*-
"""Base de áudio do Dinfinity, sobre a libmpv.

Antes o som e o TTS usavam o VLC (`python-vlc`), que só funciona com o VLC
instalado na máquina — o último obstáculo para o programa ser portátil. A
libmpv já viajava junto por causa da prévia do editor, toca os mesmos formatos
e também deixa escolher a saída de áudio, então passou a ser a base das duas
coisas. Ninguém precisa instalar nada.

Este módulo carrega a biblioteca uma vez e concentra o que som e TTS têm em
comum: listar saídas e abrir um tocador já configurado.
"""
import os
import re
import threading

from core import caminhos, logger

_mpv = None
_erro_carga = ""
_lock_carga = threading.Lock()


def _carregar():
    """Importa o `mpv` uma vez, apontando o loader para a DLL que viaja junto."""
    global _mpv, _erro_carga
    with _lock_carga:
        if _mpv is not None or _erro_carga:
            return _mpv
        dll = caminhos.achar_libmpv()
        if dll:
            pasta = os.path.dirname(dll)
            try:
                os.add_dll_directory(pasta)
            except (AttributeError, OSError):
                pass
            os.environ["PATH"] = pasta + os.pathsep + os.environ.get("PATH", "")
        try:
            import mpv
            _mpv = mpv
        except (ImportError, OSError) as exc:
            _erro_carga = str(exc)
            logger.log("error", f"[ÁUDIO] Não consegui carregar a libmpv: {exc}")
        return _mpv


def disponivel():
    return _carregar() is not None


PADRAO = "auto"          # nome que a libmpv dá para "a saída padrão do sistema"
_ROTULO_PADRAO = "Padrão do Windows"

_dispositivos = None
_lock_dispositivos = threading.Lock()


def abrir_player(volume=100, device=None):
    """Um tocador só de áudio, pronto para receber um arquivo.

    Cada som ganha o seu (custa ~3 ms) — é o que permite dois efeitos se
    sobreporem, como a risada por cima do miado.
    """
    mpv = _carregar()
    if mpv is None:
        return None
    player = mpv.MPV(video=False, vo="null", audio_display="no",
                     terminal=False, input_default_bindings=False, ytdl=False)
    try:
        # O teto do volume no mpv é 130 por padrão; o programa vai só até 120.
        player.volume = max(0, min(130, int(volume)))
    except Exception as exc:  # noqa: BLE001
        logger.log("error", f"[ÁUDIO] Volume não aceito: {exc}")
    if device and device != PADRAO:
        # Antes de tocar: escolhida com o som já rolando, a troca só valeria
        # da próxima vez.
        try:
            player.audio_device = device
        except Exception as exc:  # noqa: BLE001
            logger.log("error", f"[ÁUDIO] Saída de áudio não aceita: {exc}")
    return player


def encerrar_player(player):
    if player is None:
        return
    try:
        player.terminate()
    except Exception:  # noqa: BLE001
        pass


def listar_dispositivos(recarregar=False):
    """Saídas de áudio: [{"id": ..., "nome": ...}].

    O primeiro item é sempre o padrão do sistema. A lista quase não muda
    durante uma live, então fica em cache.
    """
    global _dispositivos
    with _lock_dispositivos:
        if _dispositivos is not None and not recarregar:
            return list(_dispositivos)
        saida = [{"id": PADRAO, "nome": _ROTULO_PADRAO}]
        player = abrir_player()
        if player is not None:
            try:
                for d in player.audio_device_list or []:
                    ident = d.get("name") or ""
                    nome = d.get("description") or ident
                    if ident and ident != PADRAO:
                        saida.append({"id": ident, "nome": nome})
            except Exception as exc:  # noqa: BLE001
                logger.log("error", f"[ÁUDIO] Não consegui listar as saídas: {exc}")
            finally:
                encerrar_player(player)
        _dispositivos = saida
        return list(saida)


def nome_do_dispositivo(ident):
    if not ident or ident == PADRAO:
        return _ROTULO_PADRAO
    for d in listar_dispositivos():
        if d["id"] == ident:
            return d["nome"]
    return "(saída não encontrada)"


_GUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


def migrar_dispositivo(ident, nome=""):
    """Converte a saída salva no formato antigo (VLC) para o da libmpv.

    O VLC guardava `{0.0.0.00000000}.{guid}` e a libmpv usa `wasapi/{guid}` —
    o mesmo aparelho com outro nome. Sem esta conversão, quem já tinha a voz
    saindo por um cabo virtual voltaria calado para o alto-falante.

    Devolve (id_novo, mudou).
    """
    if not ident or ident == PADRAO:
        return PADRAO, bool(ident) and ident != PADRAO
    disponiveis = listar_dispositivos()
    if any(d["id"] == ident for d in disponiveis):
        return ident, False

    achado = _GUID.search(ident)
    if achado:
        guid = achado.group(0).lower()
        for d in disponiveis:
            if guid in d["id"].lower():
                return d["id"], True
    if nome:
        for d in disponiveis:
            if d["nome"] == nome:
                return d["id"], True
    # O aparelho sumiu de vez (fone desconectado, driver removido).
    return PADRAO, True


def migrar_dispositivos_salvos(config):
    """Converte as saídas de áudio guardadas no config, de uma vez.

    Não é só a voz: cada passo "Tocar som" pode ter a saída dele. Passar por
    todas aqui evita um efeito voltar calado para o alto-falante no meio da
    live. Devolve True se algo mudou (aí vale salvar o config).
    """
    mudou_algo = False

    def converter(dono):
        nonlocal mudou_algo
        ident = dono.get("device") or ""
        if not ident:
            return
        novo, mudou = migrar_dispositivo(ident, dono.get("device_nome", ""))
        if not mudou:
            return
        dono["device"] = "" if novo == PADRAO else novo
        dono["device_nome"] = nome_do_dispositivo(novo) if novo != PADRAO else ""
        mudou_algo = True

    converter(config.setdefault("tts", {}))
    for reacao in config.get("reactions", []) or []:
        for passo in reacao.get("actions", []) or []:
            if isinstance(passo, dict) and passo.get("type") == "sound_play":
                converter(passo)
    if mudou_algo:
        logger.log("system", "[ÁUDIO] Saídas de áudio convertidas para o formato novo.")
    return mudou_algo
