# -*- coding: utf-8 -*-
"""Descobre sozinho como falar com o OBS Studio.

O plugin obs-websocket guarda porta, senha e se está ligado num arquivo do
próprio OBS:

    %APPDATA%\\obs-studio\\plugin_config\\obs-websocket\\config.json

Ler esse arquivo evita o erro mais chato de configurar à mão: a porta padrão
mudou de 4444 (obs-websocket 4.x) para 4455 (5.x), e quem atualizou o OBS
costuma ficar com a antiga. Sem isto, o Dinfinity tentaria a porta errada para
sempre e as ações de OBS simplesmente não aconteceriam, sem ninguém entender
por quê.

Quando `auth_required` é falso, o OBS aceita conexão sem senha mesmo tendo uma
guardada — por isso a senha só é usada quando ele diz que exige.
"""
import json
import os

# Caminhos onde o obs-websocket guarda a configuração, do mais provável ao
# menos. O portátil (OBS numa pasta só dele) fica ao lado do executável.
def _candidatos():
    caminhos = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        caminhos.append(os.path.join(appdata, "obs-studio", "plugin_config",
                                     "obs-websocket", "config.json"))
    home = os.path.expanduser("~")
    caminhos.append(os.path.join(home, "Library", "Application Support", "obs-studio",
                                 "plugin_config", "obs-websocket", "config.json"))
    caminhos.append(os.path.join(home, ".config", "obs-studio", "plugin_config",
                                 "obs-websocket", "config.json"))
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if base:
            caminhos.append(os.path.join(base, "obs-studio", "config", "obs-studio",
                                         "plugin_config", "obs-websocket", "config.json"))
    return caminhos


def descobrir():
    """Devolve o que o OBS instalado diz, ou None se não achar o arquivo.

    {"host": "localhost", "port": 4455, "password": "", "habilitado": True,
     "exige_senha": False, "arquivo": "<caminho>"}
    """
    for caminho in _candidatos():
        try:
            with open(caminho, "r", encoding="utf-8") as fh:
                dados = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(dados, dict):
            continue
        try:
            porta = int(dados.get("server_port") or 4455)
        except (TypeError, ValueError):
            porta = 4455
        exige = bool(dados.get("auth_required", False))
        return {
            "host": "localhost",
            "port": porta,
            # Sem exigência de senha, mandar a que está guardada só atrapalha.
            "password": str(dados.get("server_password") or "") if exige else "",
            "habilitado": bool(dados.get("server_enabled", False)),
            "exige_senha": exige,
            "arquivo": caminho,
        }
    return None


def aplicar(config):
    """Ajusta a seção "obs" do config com o que o OBS instalado informa.

    Devolve (mudou, achado). Respeita o que a pessoa digitou: só sobrescreve
    porta e senha quando elas ainda estão no valor padrão/vazio, para uma
    configuração manual (OBS noutro computador, por exemplo) não ser desfeita
    a cada abertura.
    """
    achado = descobrir()
    if not achado:
        return False, None
    obs = config.setdefault("obs", {})
    mudou = False
    if not obs.get("host"):
        obs["host"] = achado["host"]
        mudou = True
    try:
        porta_atual = int(obs.get("port") or 0)
    except (TypeError, ValueError):
        porta_atual = 0
    if porta_atual in (0, 4455, 4444) and porta_atual != achado["port"]:
        obs["port"] = achado["port"]
        mudou = True
    if not obs.get("password") and achado["password"]:
        obs["password"] = achado["password"]
        mudou = True
    if obs.get("password") and not achado["exige_senha"]:
        # O OBS deixou de exigir senha; mandar a antiga faria o handshake falhar.
        obs["password"] = ""
        mudou = True
    return mudou, achado
