# -*- coding: utf-8 -*-
"""Motor de texto-para-fala (edge-tts + libmpv). Fila serializada processada no
loop do monitor; a GUI envia pedidos via call_soon_threadsafe."""
import asyncio
import os
import time
import uuid

# O edge_tts custa ~0.9 s para importar e só faz falta na primeira fala, então
# entra por baixo para o Dinfinity abrir rápido.
_EDGE = None


def _edge():
    global _EDGE
    if _EDGE is None:
        import edge_tts
        _EDGE = edge_tts
    return _EDGE

from core import caminhos, logger
from core.audio import abrir_player, encerrar_player

DEFAULT_VOICE = "pt-BR-FranciscaNeural"

# Janela em que um texto idêntico é considerado repetição, e teto da fila.
REPETICAO_MIN = 10.0
FILA_MAX = 15


class TTSEngine:
    def __init__(self, config):
        self.config = config  # dict compartilhado com a GUI
        self.loop = None
        self._queue = None
        self._worker_task = None
        self._ultimo_texto = None
        self._ultimo_quando = 0.0

    # ---- integração com o loop do monitor ----
    def attach(self, loop):
        """Chamado dentro do loop (via call_soon_threadsafe) para criar a fila."""
        if self._queue is not None:
            return
        self.loop = loop
        self._queue = asyncio.Queue()
        self._worker_task = asyncio.create_task(self._worker())

    @property
    def enabled(self):
        return bool(self.config["tts"].get("enabled", True))

    def speak(self, text):
        """Enfileira um texto para ser falado. Thread-safe.

        Duas travas contra a fila descontrolada, porque o TTS é o lugar onde
        uma repetição aparece de forma mais incômoda: ele fala tudo até o fim,
        e não há como interromper no meio.
        """
        if not self.enabled or self._queue is None or self.loop is None:
            return

        agora = time.monotonic()
        # 1) Mesmo texto repetido em sequência: quase sempre é evento
        # reentregue ou duas reações falando a mesma coisa.
        if text == self._ultimo_texto and (agora - self._ultimo_quando) < REPETICAO_MIN:
            logger.log("warning", f"[TTS] Repetido em {REPETICAO_MIN}s, ignorado: {text[:60]}")
            return
        self._ultimo_texto, self._ultimo_quando = text, agora

        # put_nowait direto da thread da GUI enfileira mas não acorda o loop: o
        # pedido ficaria parado até algum evento do websocket passar por lá (e,
        # com o monitor desligado, para sempre). Quem chama de dentro do loop
        # também passa por aqui sem prejuízo.
        self.loop.call_soon_threadsafe(self._enfileirar, text)

    def _enfileirar(self, text):
        """Roda dentro do loop. O teto da fila é conferido aqui, e não em
        `speak`, porque lá o tamanho ainda é o de antes das chamadas que já
        foram agendadas — uma rajada furaria o limite."""
        if self._queue.qsize() >= FILA_MAX:
            logger.log("warning", f"[TTS] Fila cheia ({FILA_MAX}); mensagem descartada.")
            return
        self._queue.put_nowait(text)
        logger.log("tts", f"[TTS] Enfileirado: {text[:80]}")

    # ---- worker ----
    async def _worker(self):
        while True:
            text = await self._queue.get()
            try:
                await self.speak_async(text)
            except Exception as exc:
                logger.log("error", f"[TTS] {exc}")
            finally:
                self._queue.task_done()

    async def speak_async(self, text):
        cfg = self.config["tts"]
        voice = cfg.get("voice") or DEFAULT_VOICE
        rate = cfg.get("rate") or "+0%"
        temp_dir = cfg.get("temp_dir") or caminhos.temp_dir()
        os.makedirs(temp_dir, exist_ok=True)
        out = os.path.join(temp_dir, f"tts_{uuid.uuid4().hex}.mp3")
        player = None
        try:
            edge_tts = _edge()
            # O volume é aplicado só na hora de tocar. Pedir volume ao edge-tts
            # também deixaria o ajuste gravado no arquivo, e dois controles para
            # a mesma coisa só confundem quem mexe.
            comm = edge_tts.Communicate(text, voice, rate=rate)
            await comm.save(out)

            if not os.path.exists(out) or os.path.getsize(out) == 0:
                logger.log("error", f"[TTS] Nenhum áudio gerado para: {text!r} (voz: {voice})")
                return

            # Falar por uma saída própria (um cabo virtual, por exemplo) deixa a
            # voz ir para a live sem passar pelo alto-falante.
            player = abrir_player(int(cfg.get("player_volume", 100) or 100),
                                  cfg.get("device") or "")
            if player is None:
                logger.log("error", "[TTS] Áudio indisponível (libmpv não carregou).")
                return
            player.play(out)
            await asyncio.to_thread(player.wait_for_playback)
            logger.log("tts", f"[TTS] Falado: {text[:80]}")
        except Exception as exc:
            logger.log("error", f"[TTS] {exc}")
        finally:
            encerrar_player(player)
            try:
                if os.path.exists(out):
                    os.remove(out)
            except OSError:
                pass


# ---- listagem de vozes (thread curta própria, não usa o loop do monitor) ----
def list_voices(locale_filter=""):
    """Retorna lista de dicts {'ShortName','Gender','Locale'} baixada do edge-tts."""
    async def _load():
        edge_tts = _edge()
        voices = await edge_tts.list_voices()
        out = []
        for v in voices or []:
            loc = (v.get("Locale") or "").lower()
            if locale_filter and locale_filter.lower() not in loc:
                continue
            out.append({
                "ShortName": v.get("ShortName", ""),
                "Gender": v.get("Gender", ""),
                "Locale": loc,
            })
        return out

    try:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_load())
        finally:
            loop.close()
    except Exception as exc:
        logger.log("error", f"[TTS] Erro ao listar vozes: {exc}")
        return []
