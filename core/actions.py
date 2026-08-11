# -*- coding: utf-8 -*-
"""Motor de ações: a consequência de uma reação.

Cada reação guarda uma lista ordenada de passos, como uma ação do
Streamer.bot. A lista roda de cima para baixo, um passo por vez:

    [
      {"type": "delay",       "seconds_ms": 300},
      {"type": "sound_play",  "file": "C:/sons/miau.mp3", "volume": 70},
      {"type": "obs_filter",  "source": "Câmera", "filter": "Chroma", "enable": true},
      {"type": "delay",       "seconds_ms": 1000},
      {"type": "obs_filter",  "source": "Câmera", "filter": "Chroma", "enable": false}
    ]

Campos de substituição em qualquer texto/caminho: {username}, {nickname},
{gift}, {count}, {diamonds}, {message}, {likes}.

Para criar um passo novo: acrescente a entrada em STEP_TYPES (a GUI monta o
formulário sozinha a partir dela) e o trecho correspondente em `run_script`.
"""
import asyncio
import json

import websockets

from core import logger, printer
from core.obs_client import OBSClient
from core.sound import SoundPlayer

# Os grupos só organizam a lista na hora de escolher o passo.
GRUPO_GERAL = "Geral"
GRUPO_SOM = "Som e voz"
GRUPO_OBS = "OBS Studio"
GRUPO_TIKTOK = "TikTok"

STEP_TYPES = {
    # ------------------------------------------------------------- geral
    "delay": {"label": "Aguardar (delay)", "grupo": GRUPO_GERAL, "fields": [
        {"key": "seconds_ms", "label": "Tempo (milissegundos)", "kind": "number", "default": 500},
    ]},
    "log": {"label": "Escrever no log do Dinfinity", "grupo": GRUPO_GERAL, "fields": [
        {"key": "texto", "label": "Texto", "kind": "text", "default": "{nickname} ativou a reação"},
    ]},
    "ws_send": {"label": "Enviar ação WebSocket (Streamer.bot)", "grupo": GRUPO_GERAL, "fields": [
        {"key": "uri", "label": "Endereço WebSocket", "kind": "text",
         "default": "ws://127.0.0.1:9091/Acao"},
        {"key": "action", "label": "Nome da ação", "kind": "text", "default": ""},
    ]},

    # --------------------------------------------------------------- som
    "sound_play": {"label": "Tocar som", "grupo": GRUPO_SOM, "testavel": True, "fields": [
        {"key": "file", "label": "Arquivo de som", "kind": "arquivo", "default": ""},
        {"key": "volume", "label": "Volume", "kind": "volume", "default": 100,
         "minimo": 0, "maximo": 120},
        # O id da saída é um GUID enorme; no resumo aparece o nome amigável,
        # que viaja junto em "device_nome".
        {"key": "device", "label": "Sair pelo dispositivo", "kind": "audio_device",
         "default": "", "resumo_de": "device_nome"},
        {"key": "wait", "label": "Esperar o som terminar antes do próximo passo",
         "kind": "bool", "default": False},
    ]},
    "sound_stop": {"label": "Parar todos os sons", "grupo": GRUPO_SOM, "fields": []},
    "tts_speak": {"label": "Falar com o TTS", "grupo": GRUPO_SOM, "fields": [
        {"key": "texto", "label": "Texto a falar", "kind": "text", "default": "{message}"},
    ]},

    # --------------------------------------------------------------- OBS
    # As listas destes campos são lidas do OBS aberto (ver core/obs_config.py e
    # os menus da aba Reações). Continuam aceitando texto digitado, para
    # configurar com o OBS fechado ou numa cena que ainda não existe.
    "obs_set_scene": {"label": "Trocar de cena", "grupo": GRUPO_OBS, "fields": [
        {"key": "scene", "label": "Cena", "kind": "obs_cena", "default": ""},
    ]},
    "obs_source_show": {"label": "Mostrar fonte", "grupo": GRUPO_OBS, "fields": [
        {"key": "scene", "label": "Cena", "kind": "obs_cena", "default": ""},
        {"key": "source", "label": "Fonte", "kind": "obs_fonte_da_cena", "default": ""},
    ]},
    "obs_source_hide": {"label": "Esconder fonte", "grupo": GRUPO_OBS, "fields": [
        {"key": "scene", "label": "Cena", "kind": "obs_cena", "default": ""},
        {"key": "source", "label": "Fonte", "kind": "obs_fonte_da_cena", "default": ""},
    ]},
    "obs_source_toggle": {"label": "Alternar fonte (mostrar/esconder)", "grupo": GRUPO_OBS, "fields": [
        {"key": "scene", "label": "Cena", "kind": "obs_cena", "default": ""},
        {"key": "source", "label": "Fonte", "kind": "obs_fonte_da_cena", "default": ""},
    ]},
    "obs_filter": {"label": "Ativar / desativar filtro", "grupo": GRUPO_OBS, "fields": [
        {"key": "source", "label": "Fonte", "kind": "obs_fonte", "default": ""},
        {"key": "filter", "label": "Filtro", "kind": "obs_filtro", "default": ""},
        {"key": "enable", "label": "Ativar o filtro", "kind": "bool", "default": True},
    ]},
    "obs_filter_toggle": {"label": "Alternar filtro", "grupo": GRUPO_OBS, "fields": [
        {"key": "source", "label": "Fonte", "kind": "obs_fonte", "default": ""},
        {"key": "filter", "label": "Filtro", "kind": "obs_filtro", "default": ""},
    ]},
    "obs_mute": {"label": "Mutar / desmutar áudio", "grupo": GRUPO_OBS, "fields": [
        {"key": "source", "label": "Fonte de áudio", "kind": "obs_entrada", "default": ""},
        {"key": "modo", "label": "O que fazer", "kind": "escolha",
         "opcoes": ["mutar", "desmutar", "alternar"], "default": "alternar"},
    ]},
    "obs_set_volume": {"label": "Mudar o volume de uma fonte", "grupo": GRUPO_OBS, "fields": [
        {"key": "source", "label": "Fonte de áudio", "kind": "obs_entrada", "default": ""},
        {"key": "volume_db", "label": "Volume (dB, 0 = normal)", "kind": "number", "default": 0},
    ]},

    # ------------------------------------------------------------ tiktok
    # A tela desta ação é própria (ver gui/tab_reactions._editor_impressao): traz
    # a prévia do cartão montada ao vivo, os curingas à mão e os botões de
    # imprimir teste e reimprimir a última.
    "print_thanks": {"label": "Imprimir cartão de agradecimento", "grupo": GRUPO_TIKTOK,
                     "editor": "impressao", "fields": [
        # Várias linhas: uma linha em branco vira espaço em branco no cupom, e
        # é assim que se ajusta o respiro antes do corte do papel.
        {"key": "texto_topo", "label": "Texto de cima", "kind": "texto_longo",
         "default": printer.TOPO_PADRAO, "linhas": 2},
        {"key": "texto_rodape", "label": "Texto de baixo", "kind": "texto_longo",
         "default": printer.RODAPE_PADRAO, "linhas": 4},
        {"key": "espelhar", "label": "Imprimir espelhado", "kind": "bool", "default": True},
        {"key": "printer_name", "label": "Impressora", "kind": "impressora", "default": ""},
    ]},
}

# Passos que exigem OBS conectado.
_OBS_STEPS = {k for k in STEP_TYPES if k.startswith("obs_")}


def substituir(texto, extras=None):
    if not texto:
        return texto
    extras = extras or {}
    out = str(texto)
    for chave, valor in extras.items():
        out = out.replace("{" + chave + "}", str(valor))
    return out


def resumo_passo(passo):
    """Uma linha legível do passo, para a lista de ações da GUI."""
    tipo = passo.get("type", "?")
    info = STEP_TYPES.get(tipo)
    if info is None:
        return f"{tipo} (desconhecido)"
    partes = []
    for campo in info["fields"]:
        valor = passo.get(campo["key"], campo.get("default", ""))
        if valor in ("", None):
            continue
        # Alguns campos guardam um identificador feio e trazem o nome legível
        # num campo irmão (a saída de áudio, por exemplo).
        if campo.get("resumo_de"):
            valor = passo.get(campo["resumo_de"]) or valor
        if campo.get("kind") == "bool":
            valor = "sim" if valor else "não"
        partes.append(f"{campo['label'].split(' (')[0]}: {valor}")
    return info["label"] + ("  —  " + "   ·   ".join(partes) if partes else "")


class ActionsRunner:
    """Compartilhado por todas as reações: mantém o cliente OBS e o player de
    som, e executa a sequência de passos."""

    def __init__(self):
        self.obs = OBSClient()
        self.sound = None
        self.tts = None          # preenchido pelo MonitorEngine
        self.config = None       # idem: o cartão de agradecimento precisa dele
        self._sound_volume = 80
        self._obs_host = "localhost"
        self._obs_port = 4455
        self._obs_password = ""

    def configure(self, obs_cfg=None, sound_cfg=None):
        obs_cfg = obs_cfg or {}
        sound_cfg = sound_cfg or {}
        self._obs_host = obs_cfg.get("host", "localhost") or "localhost"
        try:
            self._obs_port = int(obs_cfg.get("port", 4455))
        except (TypeError, ValueError):
            self._obs_port = 4455
        self._obs_password = obs_cfg.get("password", "") or ""
        self.set_sound_volume(sound_cfg.get("player_volume", 80))

    def set_sound_volume(self, volume):
        self._sound_volume = int(volume or 80)

    def _ensure_sound(self):
        if self.sound is None:
            self.sound = SoundPlayer(self._sound_volume)
        return self.sound

    async def run_script(self, steps, extras=None, ctx=None):
        if not steps:
            return
        precisa_obs = any((s.get("type") in _OBS_STEPS) for s in steps)
        if precisa_obs and not self.obs.connected:
            try:
                await asyncio.wait_for(self.obs.connect(
                    self._obs_host, self._obs_port, self._obs_password), timeout=8)
            except Exception as exc:
                logger.log("error", f"[AÇÕES] Sem conexão com o OBS: {exc}")
                return

        for passo in steps:
            try:
                await self._executar(passo, extras, ctx)
                logger.log("acao", f"[AÇÃO] {resumo_passo(passo)}")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.log("error", f"[AÇÃO] {resumo_passo(passo)} falhou: {exc}")

    async def _executar(self, passo, extras, ctx):
        stype = passo.get("type")

        if stype == "delay":
            await asyncio.sleep(max(0, float(passo.get("seconds_ms", 0)) / 1000.0))

        elif stype == "log":
            logger.log("info", substituir(passo.get("texto", ""), extras))

        elif stype == "sound_play":
            player = self._ensure_sound()
            arquivo = substituir(passo.get("file", ""), extras)
            await asyncio.to_thread(player.play, arquivo, passo.get("volume"),
                                    bool(passo.get("wait", False)),
                                    passo.get("device") or None)

        elif stype == "sound_stop":
            if self.sound is not None:
                await asyncio.to_thread(self.sound.stop_all)

        elif stype == "tts_speak":
            texto = substituir(passo.get("texto", "{message}"), extras).strip()
            if texto and self.tts is not None:
                self.tts.speak(texto)

        elif stype == "print_thanks":
            await self._imprimir(passo, extras, ctx)

        elif stype == "obs_set_scene":
            await self.obs.set_scene(substituir(passo.get("scene", ""), extras))

        elif stype in ("obs_source_show", "obs_source_hide"):
            await self.obs.set_source_visible(substituir(passo.get("scene", ""), extras),
                                              substituir(passo.get("source", ""), extras),
                                              stype == "obs_source_show")

        elif stype == "obs_source_toggle":
            await self.obs.toggle_source(substituir(passo.get("scene", ""), extras),
                                         substituir(passo.get("source", ""), extras))

        elif stype == "obs_filter":
            await self.obs.set_filter(substituir(passo.get("source", ""), extras),
                                      substituir(passo.get("filter", ""), extras),
                                      bool(passo.get("enable", True)))

        elif stype == "obs_filter_toggle":
            await self.obs.toggle_filter(substituir(passo.get("source", ""), extras),
                                         substituir(passo.get("filter", ""), extras))

        elif stype == "obs_mute":
            fonte = substituir(passo.get("source", ""), extras)
            modo = passo.get("modo", "alternar")
            if modo == "mutar":
                await self.obs.set_input_muted(fonte, True)
            elif modo == "desmutar":
                await self.obs.set_input_muted(fonte, False)
            else:
                await self.obs.toggle_mute(fonte)

        elif stype == "obs_set_volume":
            await self.obs.set_input_volume(substituir(passo.get("source", ""), extras),
                                            float(passo.get("volume_db", 0) or 0))

        elif stype == "ws_send":
            await _send_ws(passo, extras)

    async def _imprimir(self, passo, extras, ctx):
        """Cartão de agradecimento, com os textos definidos na própria ação."""
        extras = dict(extras or {})
        # O cartão mostra o presente em português; o {gift} cru continua
        # disponível para quem preferir o nome como o TikTok manda.
        extras.setdefault("gift_pt", traduzir_gift(extras.get("gift", "")))
        imagem = b""
        if ctx is not None:
            imagem = await ctx.avatar_bytes()

        topo = substituir(passo.get("texto_topo", printer.TOPO_PADRAO), extras)
        rodape = substituir(passo.get("texto_rodape", printer.RODAPE_PADRAO), extras)
        # Os .txt espelho são para quem lê isso numa fonte de texto do OBS.
        cfg_printer = (self.config or {}).get("printer", {})
        dados_txt = (extras.get("nickname", ""), extras.get("gift_pt", ""),
                     extras.get("count", 1))
        await asyncio.to_thread(
            printer.imprimir, topo, rodape, imagem,
            passo.get("printer_name", ""), bool(passo.get("espelhar", True)),
            cfg_printer, dados_txt, True, extras)

    async def shutdown(self):
        try:
            await self.obs.disconnect()
        except Exception:
            pass
        if self.sound is not None:
            await asyncio.to_thread(self.sound.shutdown)


def traduzir_gift(name):
    # Import tardio: gifts_pt é só uma tabela, mas o módulo de ações é
    # carregado no arranque e não precisa dela até imprimir alguma coisa.
    from core.gifts_pt import GIFTS_PT
    return GIFTS_PT.get((name or "").lower(), name)


async def _send_ws(passo, extras):
    uri = substituir(passo.get("uri", ""), extras)
    action = substituir(passo.get("action", ""), extras)
    if not uri:
        return
    try:
        ws = await asyncio.wait_for(websockets.connect(uri), timeout=3)
        try:
            await asyncio.wait_for(
                ws.send(json.dumps({"type": "Action", "name": action})), timeout=3)
            try:
                resposta = await asyncio.wait_for(ws.recv(), timeout=3)
            except asyncio.TimeoutError:
                resposta = "(sem resposta)"
            logger.log("success", f"[AÇÃO] WS '{action}' enviado: {resposta}")
        finally:
            try:
                await ws.close()
            except Exception:
                pass
    except Exception as exc:
        logger.log("error", f"[AÇÃO] Erro ao enviar WS ({action}): {exc}")
