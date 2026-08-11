# -*- coding: utf-8 -*-
"""Reprodução de efeitos sonoros. Cada arquivo toca no seu próprio tocador,
então vários sons podem se sobrepor (ex.: risada + miau)."""
import os
import threading

from core import logger
from core.audio import (PADRAO, abrir_player, encerrar_player, listar_dispositivos,
                        migrar_dispositivo, nome_do_dispositivo)

__all__ = ["SoundPlayer", "listar_dispositivos", "nome_do_dispositivo",
           "migrar_dispositivo", "PADRAO"]


class SoundPlayer:
    def __init__(self, default_volume=100):
        self.default_volume = int(default_volume)
        self._lock = threading.Lock()
        self._players = []

    def play(self, path, volume=None, wait=False, device=None):
        path = os.path.normpath(str(path or ""))
        if not path or not os.path.exists(path):
            logger.log("error", f"[SOM] Arquivo não encontrado: {path}")
            return
        vol = int(volume) if volume not in (None, "") else self.default_volume
        vol = max(0, min(120, vol))
        player = abrir_player(vol, device)
        if player is None:
            logger.log("error", "[SOM] Áudio indisponível (libmpv não carregou).")
            return
        try:
            with self._lock:
                self._players.append(player)
            player.play(path)
            destino = f" -> {nome_do_dispositivo(device)}" if device and device != PADRAO else ""
            logger.log("sound",
                       f"[SOM] Tocando: {os.path.basename(path)} (vol {vol}){destino}")
            if wait:
                self._esperar(player)
            else:
                threading.Thread(target=self._esperar, args=(player,), daemon=True).start()
        except Exception as exc:  # noqa: BLE001
            logger.log("error", f"[SOM] Erro ao tocar {path}: {exc}")
            self._descartar(player)

    def _esperar(self, player):
        try:
            player.wait_for_playback()
        except Exception:  # noqa: BLE001 — parar tudo no meio cai aqui
            pass
        finally:
            self._descartar(player)

    def _descartar(self, player):
        encerrar_player(player)
        with self._lock:
            if player in self._players:
                self._players.remove(player)

    def stop_all(self):
        with self._lock:
            players = list(self._players)
        # Encerrar o tocador acorda o `wait_for_playback`, que faz a limpeza.
        for player in players:
            encerrar_player(player)

    def shutdown(self):
        self.stop_all()
