# -*- coding: utf-8 -*-
"""Gatilhos: o que liga uma reação.

Uma reação do Dinfinity tem duas metades, como no Streamer.bot: o *gatilho*
(este módulo) diz **quando** ela dispara, e a *sequência de ações*
(``core/actions.py``) diz **o que** acontece.

O gatilho é um dicionário no config:

    "trigger": {
      "tipo": "presente_valor",     # um dos TIPOS abaixo
      "comparador": ">=",           # parâmetros do tipo
      "valor": 199,
      "quem": "todos",              # quem tem permissão de ativar
      "cooldown": 7,                # segundos de silêncio por pessoa
      "agrupar": true,              # esperar a rajada de presentes acabar
      "inatividade": 2.0
    }

Os tipos e os campos de cada um saem daqui para a GUI montar o formulário
sozinha — acrescentar um gatilho novo é acrescentar uma entrada em ``TIPOS``
e o trecho correspondente em ``combina``.
"""
import time

# ---------------------------------------------------------------- permissões

# "Quem pode ativar". Os dados vêm dos badges que o TikTok manda junto do
# evento; quando um badge não vem (acontece em eventos mais simples), a regra
# nega em vez de liberar — melhor não disparar do que disparar para todo mundo.
QUEM = {
    "todos": "Qualquer pessoa",
    "seguidor": "Só quem segue",
    "assinante": "Só assinantes",
    "clube_fas": "Só o clube de fãs",
    "moderador": "Só moderadores",
    "top_badge": "Só quem tem o selo de top presenteador",
    "top_n": "Só o Top N de presentes da live",
}


class Placar:
    """Ranking de presentes da live atual, para o filtro "Top N".

    O selo de top presenteador do TikTok (``is_top_gifter``) diz apenas que a
    pessoa está no ranking dele, sem posição nem corte configurável. Somando os
    diamantes por aqui dá para responder "está entre os 3 primeiros?" — que é
    o que o TikFinity oferece.
    """

    def __init__(self):
        self._diamantes = {}
        self._ultimo_streak = {}

    def registrar(self, user_id, gift_name, diamantes, repeticoes):
        """Soma um presente ao placar, sem contar a rajada duas vezes."""
        if not user_id or diamantes <= 0:
            return
        chave = (user_id, gift_name)
        anterior = self._ultimo_streak.get(chave, 0)
        # A mesma rajada chega várias vezes com o contador crescendo; só o que
        # subiu desde a última vez é novidade.
        novos = repeticoes - anterior if repeticoes > anterior else repeticoes
        self._ultimo_streak[chave] = repeticoes
        self._diamantes[user_id] = self._diamantes.get(user_id, 0) + diamantes * max(1, novos)

    def posicao(self, user_id):
        """Posição da pessoa no ranking (1 = quem mais deu), ou None."""
        if user_id not in self._diamantes:
            return None
        ordenado = sorted(self._diamantes.items(), key=lambda item: item[1], reverse=True)
        for i, (uid, _total) in enumerate(ordenado, start=1):
            if uid == user_id:
                return i
        return None

    def limpar(self):
        self._diamantes.clear()
        self._ultimo_streak.clear()


def _seguro(fn, padrao=None):
    try:
        return fn()
    except Exception:  # noqa: BLE001
        return padrao


def pode_ativar(trigger, event, placar=None):
    """Confere o filtro "quem pode ativar" contra o usuário do evento."""
    quem = (trigger or {}).get("quem", "todos")
    if quem == "todos":
        return True
    user = getattr(event, "user", None)
    if user is None:
        return False

    if quem == "moderador":
        return bool(_seguro(lambda: user.is_moderator, False))
    if quem == "assinante":
        return bool(_seguro(lambda: user.has_badge("SUBSCRIBER"), False))
    if quem == "clube_fas":
        nivel = _seguro(lambda: user.member_level, None)
        if nivel is None:
            return False
        return int(nivel) >= int(trigger.get("nivel_min", 1) or 1)
    if quem == "seguidor":
        return bool(_seguro(lambda: user.follow_info.follow_status >= 1, False))
    if quem == "top_badge":
        return bool(_seguro(lambda: user.is_top_gifter, False))
    if quem == "top_n":
        if placar is None:
            return False
        posicao = placar.posicao(_seguro(lambda: user.id, None))
        if posicao is None:
            return False
        return posicao <= int(trigger.get("top_n", 3) or 3)
    return True


# ------------------------------------------------------------------- tipos

# Cada tipo declara o evento que escuta ("gift", "comment", "like", "follow",
# "share", "subscribe", "join") e os campos que a GUI deve pedir.
TIPOS = {
    "presente": {
        "label": "Presente específico",
        "evento": "gift",
        "descricao": "Dispara quando chega o presente escolhido.",
        "fields": [
            {"key": "gift", "label": "Presente", "kind": "gift", "default": ""},
        ],
        # `gift_id` viaja junto com o campo "gift" (o seletor devolve os dois).
    },
    "presente_valor": {
        "label": "Presente por valor (diamantes)",
        "evento": "gift",
        "descricao": "Dispara conforme o valor do presente em diamantes.",
        "fields": [
            {"key": "comparador", "label": "Condição", "kind": "escolha",
             "opcoes": [">=", "<=", "==", "entre"], "default": ">="},
            {"key": "valor", "label": "Valor (diamantes)", "kind": "number", "default": 199},
            {"key": "valor2", "label": "Valor máximo (só para \"entre\")",
             "kind": "number", "default": 0},
        ],
    },
    "presente_qualquer": {
        "label": "Qualquer presente",
        "evento": "gift",
        "descricao": "Dispara com qualquer presente, de qualquer valor.",
        "fields": [],
    },
    "chat_comando": {
        "label": "Comando no chat",
        "evento": "comment",
        "descricao": "Dispara quando um comentário começa com o comando (ex.: !dana).",
        "fields": [
            {"key": "command", "label": "Comando", "kind": "text", "default": "!dana"},
        ],
    },
    "chat_contem": {
        "label": "Comentário contém um texto",
        "evento": "comment",
        "descricao": "Dispara quando o comentário contém o texto em qualquer posição.",
        "fields": [
            {"key": "texto", "label": "Texto procurado", "kind": "text", "default": ""},
        ],
    },
    "chat_qualquer": {
        "label": "Qualquer comentário",
        "evento": "comment",
        "descricao": "Dispara em todo comentário da live.",
        "fields": [],
    },
    "curtida": {
        "label": "Curtidas",
        "evento": "like",
        "descricao": "Dispara quando alguém manda curtidas (o TikTok agrupa em lotes).",
        "fields": [
            {"key": "min_curtidas", "label": "Mínimo de curtidas no lote",
             "kind": "number", "default": 1},
        ],
    },
    "seguidor": {
        "label": "Novo seguidor",
        "evento": "follow",
        "descricao": "Dispara quando alguém começa a seguir durante a live.",
        "fields": [],
    },
    "compartilhou": {
        "label": "Compartilhou a live",
        "evento": "share",
        "descricao": "Dispara quando alguém compartilha a transmissão.",
        "fields": [],
    },
    "assinou": {
        "label": "Nova assinatura",
        "evento": "subscribe",
        "descricao": "Dispara quando alguém assina o canal.",
        "fields": [],
    },
    "entrou": {
        "label": "Entrou na live",
        "evento": "join",
        "descricao": "Dispara quando alguém entra na transmissão.",
        "fields": [],
    },
}

# Campos comuns a todos os gatilhos, mostrados numa segunda linha na GUI.
CAMPOS_COMUNS = [
    {"key": "quem", "label": "Quem pode ativar", "kind": "escolha",
     "opcoes": list(QUEM.keys()), "rotulos": QUEM, "default": "todos"},
    {"key": "top_n", "label": "Top N (para \"Top N de presentes\")",
     "kind": "number", "default": 3},
    {"key": "nivel_min", "label": "Nível mínimo no clube de fãs",
     "kind": "number", "default": 1},
    {"key": "cooldown", "label": "Cooldown por pessoa (segundos)",
     "kind": "number", "default": 0},
]

# Só faz sentido agrupar rajada em presente: o TikTok manda o mesmo presente
# repetido enquanto a pessoa segura o botão.
CAMPOS_PRESENTE = [
    {"key": "agrupar", "label": "Esperar a rajada terminar e contar tudo junto",
     "kind": "bool", "default": True},
    {"key": "inatividade", "label": "Silêncio que encerra a rajada (segundos)",
     "kind": "number", "default": 2.0},
]


def evento_de(trigger):
    """Qual evento da live este gatilho escuta."""
    return (TIPOS.get((trigger or {}).get("tipo")) or {}).get("evento", "")


def agrupa_rajada(trigger):
    return (evento_de(trigger) == "gift") and bool((trigger or {}).get("agrupar", False))


def combina(trigger, event):
    """Diz se o evento casa com o gatilho (sem contar as permissões)."""
    tipo = (trigger or {}).get("tipo")

    if tipo == "presente":
        # O ID vem primeiro: o catálogo guarda os nomes em português, mas o
        # websocket da live manda em inglês ("guarda-chuva" x "umbrella"). O
        # ID é o mesmo nos dois lados. O nome fica de reserva para os gatilhos
        # antigos, que só têm ele.
        alvo_id = str(trigger.get("gift_id") or "").strip()
        if alvo_id:
            do_evento = str(_seguro(lambda: event.gift.id, "") or
                            getattr(event, "gift_id", "") or "").strip()
            return bool(do_evento) and do_evento == alvo_id
        alvo = (trigger.get("gift") or "").strip().lower()
        return bool(alvo) and (getattr(event.gift, "name", "") or "").strip().lower() == alvo

    if tipo == "presente_valor":
        diamantes = int(getattr(event.gift, "diamond_count", 0) or 0)
        try:
            valor = float(trigger.get("valor", 0) or 0)
        except (TypeError, ValueError):
            valor = 0.0
        comparador = trigger.get("comparador", ">=")
        if comparador == "<=":
            return diamantes <= valor
        if comparador == "==":
            return diamantes == valor
        if comparador == "entre":
            try:
                valor2 = float(trigger.get("valor2", 0) or 0)
            except (TypeError, ValueError):
                valor2 = 0.0
            menor, maior = min(valor, valor2), max(valor, valor2)
            return menor <= diamantes <= maior
        return diamantes >= valor

    if tipo == "presente_qualquer":
        return True

    if tipo == "chat_comando":
        comando = (trigger.get("command") or "").strip().lower()
        texto = (getattr(event, "comment", "") or "").strip().lower()
        return bool(comando) and texto.startswith(comando)

    if tipo == "chat_contem":
        alvo = (trigger.get("texto") or "").strip().lower()
        return bool(alvo) and alvo in (getattr(event, "comment", "") or "").lower()

    if tipo == "chat_qualquer":
        return True

    if tipo == "curtida":
        try:
            minimo = int(trigger.get("min_curtidas", 1) or 1)
        except (TypeError, ValueError):
            minimo = 1
        return int(getattr(event, "count", 0) or 0) >= minimo

    if tipo in ("seguidor", "compartilhou", "assinou", "entrou"):
        return True

    return False


def extras_do_evento(evento_tipo, event, trigger=None, contagem=None):
    """Campos de substituição oferecidos às ações: {nickname}, {gift}, etc."""
    user = getattr(event, "user", None)
    extras = {
        "username": _seguro(lambda: user.unique_id, "") or "",
        "nickname": _seguro(lambda: user.nickname, "") or "",
        "gift": "",
        "count": 1,
        "diamonds": 0,
        "message": "",
        "likes": 0,
    }
    if evento_tipo == "gift":
        extras["gift"] = _seguro(lambda: event.gift.name, "") or ""
        extras["count"] = contagem if contagem is not None else (event.repeat_count or 1)
        extras["diamonds"] = int(_seguro(lambda: event.gift.diamond_count, 0) or 0)
    elif evento_tipo == "comment":
        texto = (getattr(event, "comment", "") or "").strip()
        extras["message"] = texto
        # Num comando, o que interessa para falar/exibir é o resto da frase.
        if (trigger or {}).get("tipo") == "chat_comando":
            comando = (trigger.get("command") or "").strip()
            if comando and texto.lower().startswith(comando.lower()):
                extras["message"] = texto[len(comando):].strip()
    elif evento_tipo == "like":
        extras["likes"] = int(getattr(event, "count", 0) or 0)
    return extras


class Cooldown:
    """Silêncio por pessoa depois de disparar, medido em segundos."""

    def __init__(self):
        self._ultimo = {}

    def liberado(self, trigger, chave):
        try:
            segundos = float((trigger or {}).get("cooldown", 0) or 0)
        except (TypeError, ValueError):
            segundos = 0.0
        if segundos <= 0:
            return True
        agora = time.monotonic()
        if agora - self._ultimo.get(chave, 0.0) < segundos:
            return False
        self._ultimo[chave] = agora
        return True


def resumo(trigger):
    """Uma linha descrevendo o gatilho, para o cartão da lista de reações."""
    tipo = (trigger or {}).get("tipo", "")
    info = TIPOS.get(tipo)
    if info is None:
        return "Gatilho não configurado"
    texto = info["label"]
    if tipo == "presente" and trigger.get("gift"):
        texto += f": {trigger['gift']}"
    elif tipo == "presente_valor":
        comparador = trigger.get("comparador", ">=")
        if comparador == "entre":
            texto += f": entre {trigger.get('valor', 0)} e {trigger.get('valor2', 0)} diamantes"
        else:
            texto += f": {comparador} {trigger.get('valor', 0)} diamantes"
    elif tipo in ("chat_comando", "chat_contem"):
        texto += f": {trigger.get('command') or trigger.get('texto') or ''}"
    elif tipo == "curtida":
        texto += f": {trigger.get('min_curtidas', 1)}+"
    quem = trigger.get("quem", "todos")
    if quem != "todos":
        rotulo = QUEM.get(quem, quem)
        if quem == "top_n":
            rotulo = f"Só o Top {trigger.get('top_n', 3)} de presentes"
        texto += f"  ·  {rotulo}"
    return texto
