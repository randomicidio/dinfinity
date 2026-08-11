# -*- coding: utf-8 -*-
"""Catálogo de presentes do TikTok (nome, diamantes e imagem).

A lista vem de `client.web.fetch_gift_list()` do TikTokLive — o mesmo endpoint
que o app usa para desenhar o painel de presentes — e fica em cache local
(gifts_catalog.json) para a GUI não depender de internet o tempo todo.

A atualização acontece na hora de gerar a lista: ao abrir o seletor de
presentes, se o cache estiver vazio ou com mais de um dia (`VALIDADE`), ele é
rebaixado em segundo plano e as figuras aparecem sozinhas quando chegam. O
botão "Atualizar lista" do seletor força a busca fora desse prazo.

As imagens são baixadas sob demanda e guardadas em `gifts_cache/`, então só a
primeira abertura do seletor depende da rede.
"""
import asyncio
import json
import os
import threading
import time
import urllib.request

# Importação pesada (gera protos do TikTokLiveProto na primeira carga).
# Deixa o Dinfinity abrir rápido: carrega só quando o catálogo é buscado.
_TIKTOKLIVE = None


def _tiktoklive():
    global _TIKTOKLIVE
    if _TIKTOKLIVE is None:
        from TikTokLive.client.client import TikTokLiveClient
        from TikTokLive.client.errors import TikTokLiveError
        _TIKTOKLIVE = {"TikTokLiveClient": TikTokLiveClient,
                       "TikTokLiveError": TikTokLiveError}
    return _TIKTOKLIVE

from core import logger

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG_FILE = os.path.join(APP_DIR, "gifts_catalog.json")
ICON_DIR = os.path.join(APP_DIR, "gifts_cache")

# Um dia. Presente novo do TikTok não aparece de hora em hora, e uma consulta
# por dia não pesa em nada.
VALIDADE = 24 * 3600

# A biblioteca sorteia um país (GB, CA, AU, NZ, ZA, IE, JM, BZ, TT) a cada
# execução e o Brasil não está na lista dela. Fixando os parâmetros aqui, o
# TikTok devolve o painel do Brasil e os nomes já em português.
PARAMS_BR = {
    "app_language": "pt-BR",
    "browser_language": "pt-BR",
    "webcast_language": "pt-BR",
    "priority_region": "BR",
    "region": "BR",
    "tz_name": "America/Sao_Paulo",
}
REGIAO = "BR"

_catalog = []
_atualizado = 0.0
_lock = threading.Lock()


# ---------------- cache em disco ----------------
def load_cache():
    global _catalog, _atualizado
    try:
        with open(CATALOG_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        _catalog, _atualizado = [], 0.0
        return
    if isinstance(data, list):
        # Formato antigo (lista pura): vale, mas conta como vencido para que a
        # primeira oportunidade traga a data junto.
        _catalog, _atualizado = data, 0.0
    elif isinstance(data, dict):
        _catalog = data.get("gifts") or []
        try:
            _atualizado = float(data.get("atualizado") or 0)
        except (TypeError, ValueError):
            _atualizado = 0.0


def save_cache(items):
    global _catalog, _atualizado
    _catalog = items
    _atualizado = time.time()
    try:
        with open(CATALOG_FILE, "w", encoding="utf-8") as fh:
            json.dump({"atualizado": _atualizado, "gifts": items}, fh,
                      ensure_ascii=False, indent=2)
    except OSError as exc:
        logger.log("error", f"[GIFTS] Não foi possível salvar o catálogo: {exc}")


def catalog():
    if not _catalog:
        load_cache()
    return list(_catalog)


def atualizado_em():
    if not _catalog:
        load_cache()
    return _atualizado


def vencido():
    """Diz se vale a pena buscar de novo (vazio ou com mais de um dia)."""
    return not catalog() or (time.time() - atualizado_em()) > VALIDADE


def find_gift(name):
    target = (name or "").strip().lower()
    if not target:
        return None
    for g in catalog():
        if (g.get("name") or "").strip().lower() == target:
            return g
    return None


# ---------------- parse ----------------
def _primeira_url(campo):
    if not isinstance(campo, dict):
        return ""
    for chave in ("url_list", "m_urls"):
        urls = campo.get(chave) or []
        if urls:
            return urls[0]
    return ""


def _presentes_do_painel(data):
    """Os presentes que aparecem no painel do Brasil.

    A resposta traz duas coisas: `gifts`, um saco com tudo que existe no mundo,
    e `pages`, que é o painel de verdade — cada aba com sua região. Usar o
    painel corta os presentes que nunca vão aparecer numa live brasileira
    (609 viram 568). Se o formato mudar, cai de volta na lista crua.
    """
    paginas = (data or {}).get("pages") or []
    escolhidas = [p for p in paginas
                  if isinstance(p, dict) and (p.get("region") or "").upper() == REGIAO]
    if not escolhidas:
        escolhidas = [p for p in paginas if isinstance(p, dict) and p.get("gifts")]
    vistos, saida = set(), []
    for pagina in escolhidas:
        for g in pagina.get("gifts") or []:
            if isinstance(g, dict) and str(g.get("id")) not in vistos:
                vistos.add(str(g.get("id")))
                saida.append(g)
    return saida or ((data or {}).get("gifts") or [])


def _parse(data):
    gifts = _presentes_do_painel(data)
    out = []
    for g in gifts:
        if not isinstance(g, dict):
            continue
        try:
            diamonds = int(g.get("diamond_count") or 0)
        except (TypeError, ValueError):
            diamonds = 0
        out.append({
            "id": str(g.get("id") or ""),
            "name": str(g.get("name") or g.get("describe") or ""),
            "diamonds": diamonds,
            "image": (_primeira_url(g.get("icon")) or _primeira_url(g.get("image"))
                      or _primeira_url(g.get("preview_image"))),
        })
    return out


# ---------------- busca ----------------
async def fetch_gifts(username="", timeout=30):
    """Baixa o catálogo abrindo um cliente só para isso. Retorna a lista.

    O catálogo vem de uma live qualquer, mas o TikTok exige um @ para abrir a
    conexão — sem ele, fica valendo o que já estava em cache.
    """
    username = (username or "").strip().lstrip("@")
    if not username:
        logger.log("warning", "[GIFTS] Defina o usuário da live na aba Conexão "
                              "para atualizar o catálogo de presentes.")
        return catalog()
    tl = _tiktoklive()
    client = tl["TikTokLiveClient"](unique_id=username)
    client.web.params.update(PARAMS_BR)
    try:
        data = await asyncio.wait_for(client.web.fetch_gift_list(), timeout=timeout)
        items = _parse(data)
        if items:
            save_cache(items)
            logger.log("success", f"[GIFTS] Catálogo atualizado: {len(items)} presentes.")
            return items
    except asyncio.TimeoutError:
        logger.log("error", "[GIFTS] Timeout ao buscar o catálogo de presentes.")
    except Exception as exc:
        logger.log("error", f"[GIFTS] Erro ao buscar o catálogo: {exc}")
    finally:
        try:
            await client.web.close()
        except Exception:
            pass
    return catalog()


def fetch_gifts_async(username="", timeout=30):
    """Versão executável numa thread (sem loop externo). Retorna a lista."""
    try:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(fetch_gifts(username, timeout))
        finally:
            loop.close()
    except Exception as exc:
        logger.log("error", f"[GIFTS] {exc}")
        return catalog()


# ---------------- imagens ----------------
def icone(gift):
    """Caminho local do ícone do presente, baixando na primeira vez.

    Bloqueante de propósito: quem chama é uma thread de fundo do seletor. Se a
    rede falhar devolve "" e o seletor mostra o presente sem figura.
    """
    url = (gift or {}).get("image") or ""
    if not url:
        return ""
    nome = (gift.get("id") or gift.get("name") or "").strip()
    if not nome:
        return ""
    destino = os.path.join(ICON_DIR, f"{nome}.img")
    if os.path.exists(destino) and os.path.getsize(destino) > 0:
        return destino
    try:
        os.makedirs(ICON_DIR, exist_ok=True)
        pedido = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(pedido, timeout=15) as resp:
            dados = resp.read()
        if not dados:
            return ""
        parcial = destino + ".part"
        with open(parcial, "wb") as fh:
            fh.write(dados)
        os.replace(parcial, destino)
        return destino
    except Exception:  # noqa: BLE001
        return ""
