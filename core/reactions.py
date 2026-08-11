# -*- coding: utf-8 -*-
"""Reações: gatilho + sequência de ações.

Uma reação é uma entrada do config no formato:

    {
      "id": "presente_rosa_1723400000",
      "name": "Rosa toca miado",
      "enabled": true,
      "trigger": { ...ver core/triggers.py... },
      "actions": [ ...ver core/actions.py... ]
    }

O gatilho decide quando disparar; a lista de ações roda de cima para baixo.
É a mesma divisão do Streamer.bot, com a diferença de que aqui as duas metades
moram no mesmo lugar e não dependem de nenhum programa intermediário.

`migrar` converte as reações do formato antigo (um "type" fixo por reação:
print_thanks, ws_gift, tts_command...) para este, então quem já tinha o
config montado não perde nada.
"""
import asyncio
import time

from core import logger, triggers


class ReactionContext:
    """Dados compartilhados do evento atual, com fetch de avatar em cache."""

    def __init__(self, engine, event):
        self.engine = engine
        self.event = event
        self._avatar = b""
        self._avatar_fetched = False

    async def avatar_bytes(self):
        if not self._avatar_fetched:
            self._avatar_fetched = True
            try:
                self._avatar = await self.engine.client.web.fetch_image_data(
                    self.event.user.avatar_thumb
                )
            except Exception as exc:
                logger.log("error", f"Erro ao baixar avatar: {exc}")
        return self._avatar


class Reaction:
    """Uma reação viva: guarda o estado de rajada e de cooldown do gatilho."""

    def __init__(self, cfg, engine):
        self.cfg = cfg
        self.engine = engine
        self._cooldown = triggers.Cooldown()
        self._acc = {}
        self._tasks = set()

    # ---------------- atalhos de leitura ----------------
    @property
    def id(self):
        return self.cfg.get("id", "")

    @property
    def name(self):
        return self.cfg.get("name", "Reação")

    @property
    def enabled(self):
        return bool(self.cfg.get("enabled", True))

    @property
    def trigger(self):
        return self.cfg.get("trigger") or {}

    @property
    def actions(self):
        return self.cfg.get("actions") or []

    @property
    def evento(self):
        return triggers.evento_de(self.trigger)

    def start(self):
        self._acc = {}

    def stop(self):
        for task in list(self._tasks):
            task.cancel()
        self._tasks.clear()
        self._acc.clear()

    def _spawn(self, coro):
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # ---------------- disparo ----------------
    async def handle(self, evento_tipo, event, ctx):
        if evento_tipo != self.evento:
            return
        if not triggers.combina(self.trigger, event):
            return
        if not triggers.pode_ativar(self.trigger, event, self.engine.placar):
            return

        chave = self._chave(event)
        if triggers.agrupa_rajada(self.trigger):
            self._acumular(event, ctx, chave)
            return
        if not self._cooldown.liberado(self.trigger, chave):
            return
        await self._executar(event, ctx)

    def _chave(self, event):
        """Cooldown e rajada são por pessoa (e por presente, quando há um)."""
        user = getattr(event, "user", None)
        uid = ""
        try:
            uid = user.unique_id or str(user.id)
        except Exception:  # noqa: BLE001
            pass
        presente = ""
        try:
            presente = event.gift.name or ""
        except Exception:  # noqa: BLE001
            pass
        return f"{self.id}|{uid}|{presente}"

    def _acumular(self, event, ctx, chave):
        """Segura a rajada de presentes e conta tudo junto no fim.

        O TikTok manda o mesmo presente repetido enquanto a pessoa segura o
        botão; sem isto uma rajada de 50 rosas viraria 50 disparos.
        """
        repeticoes = event.repeat_count or 1
        agora = time.monotonic()
        if chave in self._acc:
            dados = self._acc[chave]
            # O contador da rajada às vezes reinicia: quando ele cresce é o
            # total corrente, quando cai é uma rajada nova que começou.
            if repeticoes >= dados["ultimo"]:
                dados["total"] = repeticoes
            else:
                dados["total"] += repeticoes
            dados["ultimo"] = repeticoes
            dados["quando"] = agora
            return
        self._acc[chave] = {"total": repeticoes, "ultimo": repeticoes, "quando": agora}
        self._spawn(self._esperar_rajada(event, ctx, chave))

    async def _esperar_rajada(self, event, ctx, chave):
        try:
            inatividade = float(self.trigger.get("inatividade", 2.0) or 2.0)
        except (TypeError, ValueError):
            inatividade = 2.0
        while True:
            await asyncio.sleep(0.2)
            dados = self._acc.get(chave)
            if not dados:
                return
            if time.monotonic() - dados["quando"] >= inatividade:
                break
        dados = self._acc.pop(chave, None)
        if not dados:
            return
        if not self._cooldown.liberado(self.trigger, chave):
            logger.log("info", f"[{self.name}] ignorado pelo cooldown.")
            return
        await self._executar(event, ctx, contagem=dados["total"])

    async def _executar(self, event, ctx, contagem=None):
        extras = triggers.extras_do_evento(self.evento, event, self.trigger, contagem)
        logger.log("reacao", f"[REAÇÃO] {self.name} — {extras.get('nickname') or 'alguém'}")
        await self.engine.actions.run_script(self.actions, extras, ctx)


class ReactionManager:
    def __init__(self, engine):
        self.engine = engine
        self._reactions = []

    def set_definitions(self, definitions):
        """(Re)constrói as reações ativas. Deve rodar dentro do loop do monitor."""
        self.stop_all()
        for cfg in definitions or []:
            if not triggers.evento_de(cfg.get("trigger")):
                logger.log("warning",
                           f"Reação sem gatilho válido: {cfg.get('name') or cfg.get('id')}")
                continue
            try:
                reaction = Reaction(cfg, self.engine)
                reaction.start()
                self._reactions.append(reaction)
            except Exception as exc:
                logger.log("error", f"Falha ao criar reação {cfg.get('id')}: {exc}")

    def set_enabled(self, reaction_id, enabled):
        for r in self._reactions:
            if r.id == reaction_id:
                r.cfg["enabled"] = bool(enabled)

    def reactions(self):
        return list(self._reactions)

    async def dispatch(self, evento_tipo, event, ctx):
        for r in self._reactions:
            if not r.enabled or r.evento != evento_tipo:
                continue
            try:
                await r.handle(evento_tipo, event, ctx)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.log("error", f"[Reação {r.name}] {exc}")

    def stop_all(self):
        for r in self._reactions:
            try:
                r.stop()
            except Exception:
                pass
        self._reactions = []


# ------------------------------------------------------------------ migração

def _acoes_do_tipo_antigo(cfg):
    """Traduz uma reação do formato antigo na lista de ações equivalente."""
    tipo = cfg.get("type")
    params = cfg.get("config") or {}
    if tipo == "print_thanks":
        return [{"type": "print_thanks", "texto_gift": ""}]
    if tipo in ("ws_gift", "ws_command"):
        return [{"type": "ws_send",
                 "uri": params.get("uri", ""),
                 "action": params.get("action", "")}]
    if tipo == "tts_command":
        return [{"type": "tts_speak", "texto": "{message}"}]
    if tipo == "log_chat":
        return [{"type": "log", "texto": "{username}: {message}"}]
    if tipo in ("scripted_gift", "scripted_comment"):
        return [dict(p) for p in (params.get("script") or [])]
    return []


def _gatilho_do_tipo_antigo(cfg):
    tipo = cfg.get("type")
    params = cfg.get("config") or {}
    comum = {"quem": "todos", "top_n": 3, "nivel_min": 1,
             "cooldown": params.get("cooldown", 0) or 0}
    if tipo == "print_thanks":
        comum.update({"tipo": "presente_valor", "comparador": ">=",
                      "valor": params.get("min_diamonds", 199), "valor2": 0,
                      "agrupar": True,
                      "inatividade": params.get("inactivity", 2.0)})
        return comum
    if tipo in ("ws_gift", "scripted_gift"):
        comum.update({"tipo": "presente", "gift": params.get("gift", ""),
                      "agrupar": False, "inatividade": 2.0})
        return comum
    if tipo in ("ws_command", "tts_command", "scripted_comment"):
        comum.update({"tipo": "chat_comando", "command": params.get("command", "!dana")})
        return comum
    if tipo == "log_chat":
        comum.update({"tipo": "chat_qualquer"})
        return comum
    return {}


def migrar(definicoes):
    """Converte a lista do config para o formato gatilho + ações.

    Roda a cada abertura e é idempotente: quem já está no formato novo passa
    intacto. Assim o config antigo continua valendo sem nenhum passo manual.
    """
    saida = []
    convertidas = 0
    for cfg in definicoes or []:
        if isinstance(cfg.get("trigger"), dict) and "actions" in cfg:
            saida.append(cfg)
            continue
        gatilho = _gatilho_do_tipo_antigo(cfg)
        if not gatilho:
            logger.log("warning", f"Reação antiga não reconhecida, ignorada: {cfg.get('id')}")
            continue
        saida.append({
            "id": cfg.get("id") or f"reacao_{int(time.time() * 1000)}",
            "name": cfg.get("name", "Reação"),
            "enabled": bool(cfg.get("enabled", True)),
            "trigger": gatilho,
            "actions": _acoes_do_tipo_antigo(cfg),
        })
        convertidas += 1
    if convertidas:
        logger.log("system", f"{convertidas} reação(ões) convertidas para o formato "
                             f"gatilho + ações.")
    return saida
