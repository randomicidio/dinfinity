# -*- coding: utf-8 -*-
"""Motor de monitoramento da live.

Roda um loop asyncio em thread própria. Dentro do loop:
  - cliente TikTokLive + handlers de eventos;
  - supervisor (standby -> detecta live -> conecta -> volta ao standby);
  - watchdog (detecta conexão morta e força reconexão);
  - ReactionManager (reage a gifts/comentários conforme o config).

A GUI conversa com este motor por call_soon_threadsafe e por filas de
status/log drenadas via after().
"""
import asyncio
import collections
import threading
import time

# Ajuste do vigia que detecta conexão morta. É afinado para o comportamento do
# websocket do TikTok, não é decisão de quem usa o programa — por isso mora
# aqui e não na tela de configurações.
WATCHDOG_POLL = 10        # de quanto em quanto tempo conferir, em segundos
WATCHDOG_TIMEOUT = 45     # silêncio a partir do qual a conexão é dada como morta

# A importação do TikTokLive é pesada (gera os protos do TikTokLiveProto na
# primeira carga, ~1s). Para o programa abrir rápido, ela acontece só quando
# o monitor é de fato ligado — nunca no import do módulo.
_TIKTOKLIVE_IMPORTS = None


def _tiktoklive():
    """Carrega (uma única vez) o TikTokLive e devolve as classes usadas."""
    global _TIKTOKLIVE_IMPORTS
    if _TIKTOKLIVE_IMPORTS is None:
        from TikTokLive.client.client import TikTokLiveClient
        from TikTokLive.client.errors import UserOfflineError
        from TikTokLive.client.logger import LogLevel
        from TikTokLive.events import (
            CommentEvent, ConnectEvent, DisconnectEvent, FollowEvent, GiftEvent,
            JoinEvent, LikeEvent, LiveEndEvent, ShareEvent, SubNotifyEvent,
            WebsocketResponseEvent,
        )
        _TIKTOKLIVE_IMPORTS = {
            "TikTokLiveClient": TikTokLiveClient,
            "UserOfflineError": UserOfflineError,
            "LogLevel": LogLevel,
            "events": {
                "ConnectEvent": ConnectEvent, "DisconnectEvent": DisconnectEvent,
                "CommentEvent": CommentEvent, "GiftEvent": GiftEvent,
                "LiveEndEvent": LiveEndEvent, "WebsocketResponseEvent": WebsocketResponseEvent,
                "LikeEvent": LikeEvent, "FollowEvent": FollowEvent,
                "ShareEvent": ShareEvent, "SubNotifyEvent": SubNotifyEvent,
                "JoinEvent": JoinEvent,
            },
        }
    return _TIKTOKLIVE_IMPORTS

from core import logger, reactions as react, triggers
from core.actions import ActionsRunner


class MonitorEngine:
    def __init__(self, config, tts_engine):
        self.config = config
        self.tts = tts_engine
        self.loop = None
        self.thread = None
        self.client = None
        self.reactions = react.ReactionManager(self)
        # Ranking de presentes da live, usado pelo filtro "só o Top N".
        self.placar = triggers.Placar()
        self.actions = ActionsRunner()
        self.actions.configure(config.get("obs", {}), config.get("sound", {}))
        self.actions.tts = tts_engine
        self.actions.config = config

        self._monitoring = False
        self._last_alive = 0.0
        self._supervisor_task = None
        self._watchdog_task = None
        # O asyncio só guarda referência fraca das tasks soltas: sem isto o
        # coletor pode recolher uma no meio do caminho (ex.: a desconexão).
        self._bg_tasks = set()

        self._live_active = False
        self._live_started_cbs = []
        self._live_ended_cbs = []

        self._status = []   # lista de (state, texto)
        self._lock = threading.Lock()

        # Ids de mensagens já processadas, para não reagir duas vezes ao mesmo
        # evento quando o TikTok reentrega (ver _ja_visto).
        self._vistos = set()
        self._ordem_vistos = collections.deque()

    # ---------------- status / estado ----------------
    def set_status(self, state, text):
        with self._lock:
            self._status.append((state, text))

    def drain_status(self):
        with self._lock:
            items = self._status[:]
            self._status.clear()
            return items

    @property
    def monitoring(self):
        return self._monitoring

    @property
    def live_active(self):
        return self._live_active

    # ---------------- eventos de live (para o gravador etc.) ----------------
    def on_live_started(self, callback):
        """Registra um callback chamado quando uma live é detectada."""
        self._live_started_cbs.append(callback)

    def on_live_ended(self, callback):
        """Registra um callback chamado quando a live termina."""
        self._live_ended_cbs.append(callback)

    def _notify_live_started(self):
        for cb in self._live_started_cbs:
            try:
                cb()
            except Exception:
                pass

    def _notify_live_ended(self):
        # O Top N é da live que acabou: zerar aqui evita que o ranking de
        # ontem decida quem pode ativar as reações de hoje.
        self.placar.limpar()
        for cb in self._live_ended_cbs:
            try:
                cb()
            except Exception:
                pass

    # ---------------- ciclo de vida do loop ----------------
    def start(self):
        if self.thread is not None and self.thread.is_alive():
            return
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True, name="monitor-loop")
        self.thread.start()
        self.loop.call_soon_threadsafe(self.tts.attach, self.loop)

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_forever()
        finally:
            pending = asyncio.all_tasks(self.loop)
            for task in pending:
                task.cancel()
            try:
                self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass
            self.loop.close()

    def stop(self):
        self.stop_monitoring()
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self._shutdown_actions)
            self.loop.call_soon_threadsafe(self.loop.stop)
        if self.thread is not None:
            self.thread.join(timeout=3)
        self.loop = None
        self.thread = None

    def _shutdown_actions(self):
        try:
            asyncio.create_task(self.actions.shutdown())
        except Exception:
            pass

    def _async_call(self, fn, *args):
        if self.loop is not None:
            self.loop.call_soon_threadsafe(fn, *args)

    def testar_acoes(self, acoes, extras=None):
        """Executa a sequência agora, como se o gatilho tivesse disparado.

        Serve para conferir som, cena e filtro sem depender de alguém mandar um
        presente. Roda no mesmo loop das reações de verdade, então usa a mesma
        conexão com o OBS e o mesmo player.
        """
        if not acoes:
            return
        dados = {
            "username": "teste", "nickname": "Teste", "gift": "Presente de teste",
            "count": 1, "diamonds": 0, "message": "mensagem de teste", "likes": 1,
        }
        dados.update(extras or {})
        logger.log("system", f"[TESTE] Rodando {len(acoes)} passo(s)...")
        self._async_call(lambda: self._spawn(self.actions.run_script(acoes, dados)))

    # ---------------- ponte com o OBS (usada pela GUI) ----------------
    def conectar_obs(self):
        """Abre a conexão com o OBS sem segurar a janela.

        Sai do arranque do programa: o handshake é local e rápido, mas se o
        OBS estiver fechado o socket demora a desistir — e isso não pode
        aparecer como demora para abrir o Dinfinity.
        """
        self._async_call(lambda: self._spawn(self._conectar_obs()))

    async def _conectar_obs(self):
        obs = self.actions.obs
        if obs.connected:
            return True
        try:
            await asyncio.wait_for(
                obs.connect(self.actions._obs_host, self.actions._obs_port,
                            self.actions._obs_password), timeout=6)
            return True
        except Exception:  # noqa: BLE001 - o próprio cliente já registra o motivo
            return False

    def obs_consultar(self, consulta, quando_pronto):
        """Roda uma consulta no OBS a partir da thread da GUI.

        `consulta(obs)` devolve a corrotina; `quando_pronto(resultado, erro)` é
        chamado na thread do loop — quem desenha precisa voltar para a thread
        do Tk (via after) antes de mexer em widget.
        """
        if self.loop is None:
            quando_pronto([], RuntimeError("O motor não está rodando."))
            return

        async def executar():
            if not await self._conectar_obs():
                raise RuntimeError("OBS não conectado.")
            return await consulta(self.actions.obs)

        try:
            futuro = asyncio.run_coroutine_threadsafe(executar(), self.loop)
        except RuntimeError as exc:
            quando_pronto([], exc)
            return

        def terminou(f):
            try:
                quando_pronto(f.result(), None)
            except Exception as exc:  # noqa: BLE001
                quando_pronto([], exc)

        futuro.add_done_callback(terminou)

    def _spawn(self, coro):
        """Cria uma task e segura a referência até ela terminar."""
        task = asyncio.create_task(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        return task

    # ---------------- início / parada do monitor ----------------
    def start_monitoring(self):
        if self._monitoring:
            return
        self._monitoring = True
        self._async_call(self._setup_monitor)

    def stop_monitoring(self):
        if not self._monitoring:
            return
        self._monitoring = False
        self._async_call(self._teardown_monitor)

    def reload_reactions(self):
        """Aplica alterações nas reações (novas/removidas/editadas) sem reiniciar o monitor."""
        if not self._monitoring:
            return
        self._async_call(lambda: self.reactions.set_definitions(self.config["reactions"]))

    def _setup_monitor(self):
        try:
            tl = _tiktoklive()
            TikTokLiveClient = tl["TikTokLiveClient"]
            LogLevel = tl["LogLevel"]
            username = self.config["live"].get("username", "")
            self.client = TikTokLiveClient(unique_id=username)
            self.client.logger.setLevel(LogLevel.ERROR.value)
            self._register_handlers()
            self.reactions.set_definitions(self.config["reactions"])
            self._mark_alive()

            self._supervisor_task = asyncio.create_task(self._supervisor())
            self._watchdog_task = asyncio.create_task(self._watchdog())
            self.set_status("standby", f"Standby. Aguardando @{username} abrir a live...")
            logger.log("system", f"Monitor iniciado para @{username} (standby).")
        except Exception as exc:
            logger.log("error", f"Falha ao iniciar monitor: {exc}")
            self._monitoring = False

    def _teardown_monitor(self):
        for task in (self._supervisor_task, self._watchdog_task):
            if task is not None:
                task.cancel()
        self._supervisor_task = self._watchdog_task = None
        # O cliente sai de self.client agora, mas a desconexão só roda na volta
        # do loop: por isso ela recebe o objeto, em vez de reler self.client
        # (que já seria None e deixaria o websocket aberto).
        client, self.client = self.client, None
        if client is not None and client.connected:
            self._spawn(self._disconnect_safe(client))
        self.reactions.stop_all()
        self.set_status("off", "Monitor parado.")
        logger.log("system", "Monitor parado.")

    async def _disconnect_safe(self, client):
        try:
            await client.disconnect()
        except Exception as exc:
            logger.log("error", f"Erro ao desconectar: {exc}")

    # ---------------- marca de vida / watchdog ----------------
    def _mark_alive(self):
        self._last_alive = time.monotonic()

    async def _watchdog(self):
        while True:
            await asyncio.sleep(WATCHDOG_POLL)
            try:
                if self.client is None or not self.client.connected:
                    continue
                inactive = time.monotonic() - self._last_alive
                if inactive > WATCHDOG_TIMEOUT:
                    logger.log("warning",
                               f"[WATCHDOG] {inactive:.0f}s sem sinal do websocket. Forçando reconexão...")
                    try:
                        await self.client.disconnect()
                    except Exception as exc:
                        logger.log("error", f"[WATCHDOG] Erro ao forçar disconnect: {exc}")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.log("error", f"[WATCHDOG] Erro: {exc}")

    # ---------------- supervisor ----------------
    async def _supervisor(self):
        cfg = self.config["live"]
        UserOfflineError = _tiktoklive()["UserOfflineError"]
        while True:
            # Relido a cada volta: mudar o intervalo na aba Conexão passa a
            # valer na hora, sem precisar desconectar e conectar de novo. É o
            # mesmo número para esperar entre conferidas e para tentar de novo
            # depois de um erro — para quem usa, são a mesma pergunta.
            espera = max(1, int(cfg.get("verify_poll", 5) or 5))
            try:
                if self.client is None:
                    await asyncio.sleep(1)
                    continue
                try:
                    live = await self.client.is_live()
                except Exception:
                    live = True  # em caso de dúvida, tenta conectar
                if live is False:
                    if self._live_active:
                        self._live_active = False
                        self._notify_live_ended()
                    await asyncio.sleep(espera)
                    continue

                if not self._live_active:
                    self._live_active = True
                    self._notify_live_started()

                self.set_status("connecting", "Live detectada! Conectando...")
                self._mark_alive()
                await self.client.connect(process_connect_events=False, fetch_live_check=True)
                self.set_status("standby", "Conexão encerrada. Voltando ao standby...")
                await asyncio.sleep(3)
            except UserOfflineError:
                await asyncio.sleep(espera)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.log("error", f"Erro de conexão: {exc}. Tentando novamente em {espera}s...")
                await asyncio.sleep(espera)

    # ---------------- handlers do TikTok ----------------
    def _register_handlers(self):
        client = self.client
        ev = _tiktoklive()["events"]
        ConnectEvent, DisconnectEvent = ev["ConnectEvent"], ev["DisconnectEvent"]
        CommentEvent, GiftEvent = ev["CommentEvent"], ev["GiftEvent"]
        LiveEndEvent, WebsocketResponseEvent = ev["LiveEndEvent"], ev["WebsocketResponseEvent"]

        @client.on(ConnectEvent)
        async def on_connect(event):
            self.set_status("connected", f"Conectado à live de @{event.unique_id}!")
            logger.log("success", f"Conectado à live de @{event.unique_id}!")

        @client.on(DisconnectEvent)
        async def on_disconnect(event):
            self.set_status("standby", "Desconectado da live. Voltando ao standby...")
            logger.log("info", "Desconectado da live. Voltando ao standby...")

        @client.on(LiveEndEvent)
        async def on_live_end(event):
            if self._live_active:
                self._live_active = False
                self._notify_live_ended()
            self.set_status("standby", "A live terminou. Voltando ao standby...")
            logger.log("info", "A live terminou (LiveEnd). Voltando ao standby...")

        @client.on(WebsocketResponseEvent)
        async def on_ws(event):
            self._mark_alive()

        @client.on(CommentEvent)
        async def on_comment(event):
            self._mark_alive()
            # O chat é registrado sempre, na categoria dele: quem decide se
            # aparece é o filtro do console, na aba Conexão. Antes isso
            # dependia de existir uma reação configurada só para logar.
            try:
                logger.log("chat", f"{event.user.unique_id}: {event.comment}")
            except Exception:
                pass
            await self._dispatch("comment", event)

        @client.on(GiftEvent)
        async def on_gift(event):
            self._mark_alive()
            try:
                logger.log("gift", f"[GIFT] {event.user.nickname} -> {event.gift.name} "
                                   f"x{event.repeat_count or 1} (valor: {event.gift.diamond_count or 0})")
            except Exception:
                pass
            # O placar entra antes das reações: quem acabou de mandar o
            # presente já conta para o filtro "Top N" deste mesmo evento.
            try:
                self.placar.registrar(event.user.id, event.gift.name,
                                      int(event.gift.diamond_count or 0),
                                      int(event.repeat_count or 1))
            except Exception:
                pass
            await self._dispatch("gift", event)

        @client.on(ev["LikeEvent"])
        async def on_like(event):
            self._mark_alive()
            await self._dispatch("like", event)

        @client.on(ev["FollowEvent"])
        async def on_follow(event):
            self._mark_alive()
            await self._dispatch("follow", event)

        @client.on(ev["ShareEvent"])
        async def on_share(event):
            self._mark_alive()
            await self._dispatch("share", event)

        @client.on(ev["SubNotifyEvent"])
        async def on_subscribe(event):
            self._mark_alive()
            await self._dispatch("subscribe", event)

        @client.on(ev["JoinEvent"])
        async def on_join(event):
            self._mark_alive()
            await self._dispatch("join", event)

    def _ja_visto(self, event):
        """Diz se este evento já passou por aqui.

        O TikTok reentrega mensagens: na reconexão, em instabilidade de rede, e
        às vezes sem motivo aparente. Cada uma dispararia as reações de novo —
        e uma reação que lê o chat em voz alta repetiria a mesma frase. O
        `msg_id` é único por mensagem, então basta lembrar dos últimos.
        """
        try:
            ident = str(event.common.msg_id or "")
        except Exception:  # noqa: BLE001
            return False
        if not ident or ident == "0":
            return False          # sem id não dá para saber; deixa passar
        if ident in self._vistos:
            return True
        self._vistos.add(ident)
        self._ordem_vistos.append(ident)
        # Uma live movimentada faz algumas dezenas de eventos por minuto; 2000
        # cobre bem mais do que qualquer janela de reentrega.
        if len(self._ordem_vistos) > 2000:
            self._vistos.discard(self._ordem_vistos.popleft())
        return False

    async def _dispatch(self, evento_tipo, event):
        if self._ja_visto(event):
            logger.log("system", f"[DUPLICADO] Evento de {evento_tipo} reentregue "
                                 f"pelo TikTok — ignorado.")
            return
        ctx = react.ReactionContext(self, event)
        await self.reactions.dispatch(evento_tipo, event, ctx)
