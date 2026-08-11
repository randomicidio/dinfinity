# -*- coding: utf-8 -*-
"""Configuração central do Dinfinity. Lê/escreve config.json na raiz do app."""
import copy
import json
import os

from core import caminhos

APP_DIR = caminhos.APP_DIR
CONFIG_FILE = os.path.join(APP_DIR, "config.json")

# Caminhos que o programa calcula sozinho, conforme onde ele está rodando.
# Salvá-los no config.json quebraria a portabilidade: o arquivo copiado para
# outra máquina (ou para outra pasta) apontaria para um lugar inexistente.
DERIVADOS = (("tts", "temp_dir"),)

# Reações de quem está começando: as que funcionam sem depender de nada
# configurado fora daqui. As de OBS ficam de fora de propósito — elas apontam
# para cenas e fontes que só existem no OBS de quem montou, e chegariam
# quebradas numa instalação nova.
GIFT_REACTIONS_DEFAULT = [
    {
        "id": "print_thanks",
        "name": "Imprimir agradecimento",
        "enabled": False,
        "trigger": {
            "tipo": "presente_valor", "comparador": ">=", "valor": 199, "valor2": 0,
            "quem": "todos", "cooldown": 7, "agrupar": True, "inatividade": 2.0,
        },
        "actions": [{"type": "print_thanks"}],
    },
    {
        "id": "tts_falar",
        "name": "Falar comentários (!falar)",
        "enabled": True,
        "trigger": {"tipo": "chat_comando", "command": "!falar",
                    "quem": "todos", "cooldown": 0},
        "actions": [{"type": "tts_speak", "texto": "{message}"}],
    },
]

DEFAULT_CONFIG = {
    "app": {
        "appearance": "dark",
        "color_theme": "blue",
        # Pedir Administrador logo ao abrir, antes de o monitor e o gravador
        # subirem. Só o Chat Automático precisa do privilégio, mas elevar no
        # meio da sessão obriga a reabrir o programa — e aí a live cai, a
        # gravação para e o log some. Quem usa o Chat Automático liga isto e
        # não passa mais por isso.
        "abrir_como_admin": False,
    },
    "live": {
        "username": "",
        # De quanto em quanto tempo conferir se a live abriu — e também quanto
        # esperar para tentar de novo depois de um erro de conexão.
        "verify_poll": 5,
        "auto_connect": False,
    },
    "recorder": {
        "outdir": os.path.join(APP_DIR, "Gravacoes"),
        "keep_waiting": True,
        "auto_rec": False,
        "registrar_presentes": True,
        "preview_live": True,
        "preview_audio": False,
        "preview_volume": 50,
        "cookie": "",
    },
    "printer": {
        # A impressora é escolhida na própria ação de imprimir (aba Reações).
        # Aqui fica só isto: vazio = não espelha os dados em .txt. Serve para
        # quem lê esses arquivos numa fonte de texto do OBS.
        "txt_dir": "",
    },
    "tts": {
        "enabled": True,
        "voice": "pt-BR-FranciscaNeural",
        "rate": "+0%",
        "player_volume": 100,
        # Vazio = saída padrão do sistema (ver core/audio.listar_dispositivos).
        "device": "",
        "device_nome": "",
        "temp_dir": caminhos.temp_dir(),
    },
    "reactions": GIFT_REACTIONS_DEFAULT,
    "chat": {
        "interval_minutes": 60,
        "messages": [],
        "input_offset": None,
        "send_offset": None,
    },
    "puzzle": {
        # As imagens do jogo são conteúdo de quem usa, não ferramenta: podem
        # morar em qualquer lugar. A pasta é escolhida na própria aba Jogo
        # Perfil; esta é só a sugestão da primeira execução.
        "folders": [os.path.join(APP_DIR, "imagens_perfil")],
        "recursive": False,
        "cols": 3,
        "rows": 6,
        "hover_alpha": 220,
        "obs_port": 8765,
    },
    "obs": {
        "host": "localhost",
        "port": 4455,
        "password": "",
    },
    "sound": {
        # Só vale para um passo de som salvo sem volume próprio; a tela de
        # reações sempre grava o dela.
        "player_volume": 100,
    },
    # O que aparece no console da aba Conexão (as categorias vêm do logger).
    "log": {
        "chat": True,
        "presentes": True,
        "reacoes": True,
        "voz": True,
        "sistema": True,
        "erros": True,
    },
}


def _deep_merge(base, override):
    result = copy.deepcopy(base)
    if not isinstance(override, dict):
        return override
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


# Chaves que existiram em versões anteriores e hoje não são lidas por ninguém.
# Ficar no arquivo só confunde na hora de conferir o que está valendo.
OBSOLETAS = (
    ("printer", "wkhtmltopdf"),      # a impressão não passa mais por PDF
    ("printer", "pdftoprinter"),
    ("printer", "work_dir"),         # os temporários vão para dados/temp
    ("printer", "images_dir"),       # nunca foi lida
    ("printer", "image_size"),       # o avatar agora acompanha a largura do papel
    ("tts", "volume"),               # o volume é só o do tocador
    ("sound", "tts_volume"),         # nunca foi lida
    ("live", "log_chat"),            # quem manda são os filtros do log
    ("live", "watchdog_timeout"),    # ajuste interno, não é decisão de usuário
    ("live", "watchdog_poll"),
    ("live", "reconnect_delay"),     # virou o mesmo "verificar a cada"
)


def _migrar_impressao(config):
    """Leva a impressora e o texto do cartão para dentro da ação de imprimir.

    Antes a impressora era uma configuração global e o cartão tinha texto fixo.
    Agora as duas coisas moram no passo, onde dá para ver a prévia. Quem já
    usava uma impressora específica precisa dela copiada para lá — cair na
    padrão do Windows mandaria o cupom para a impressora errada.
    """
    global_name = (config.get("printer", {}) or {}).get("printer_name", "")
    for reacao in config.get("reactions", []) or []:
        for passo in reacao.get("actions", []) or []:
            if not isinstance(passo, dict) or passo.get("type") != "print_thanks":
                continue
            if global_name and not passo.get("printer_name"):
                passo["printer_name"] = global_name
            # O antigo "texto_gift" trocava só o nome do presente; hoje o
            # rodapé inteiro é editável e {gift_pt} faz esse papel.
            gift = (passo.pop("texto_gift", "") or "").strip()
            passo.setdefault("texto_topo", "Obrigado, {nickname}!!")
            passo.setdefault("texto_rodape",
                             f"por enviar {{count}} x {gift}!" if gift
                             else "por enviar {count} x {gift_pt}!")
            passo.setdefault("espelhar", True)
            # Rodapé salvo por uma versão que ainda não tinha o espaço final:
            # devolve as duas linhas e o hífen do cartão original.
            if not passo["texto_rodape"].rstrip().endswith("-") \
                    and "\n" not in passo["texto_rodape"]:
                passo["texto_rodape"] = passo["texto_rodape"].rstrip() + "\n\n-"
    config.get("printer", {}).pop("printer_name", None)
    return config


def _limpar(config):
    """Tira as chaves obsoletas e recalcula as derivadas."""
    for secao, chave in OBSOLETAS:
        if isinstance(config.get(secao), dict):
            config[secao].pop(chave, None)
    config.setdefault("tts", {})["temp_dir"] = caminhos.temp_dir()
    _migrar_impressao(config)
    return config


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
                saved = json.load(fh)
            return _limpar(_deep_merge(DEFAULT_CONFIG, saved))
        except (OSError, json.JSONDecodeError):
            pass
    return _limpar(copy.deepcopy(DEFAULT_CONFIG))


def save_config(config):
    # Os caminhos derivados saem antes de gravar: assim o config.json pode ser
    # copiado junto com o programa para outra máquina sem levar os caminhos
    # desta. Eles voltam sozinhos no load_config.
    saida = copy.deepcopy(config)
    for secao, chave in DERIVADOS:
        if isinstance(saida.get(secao), dict):
            saida[secao].pop(chave, None)
    tmp = CONFIG_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(saida, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_FILE)


def exportar(config, destino):
    """Grava as configurações num arquivo à escolha.

    Sai o mesmo conteúdo que vai para o config.json — sem os caminhos que o
    programa calcula sozinho — para o arquivo poder ser levado a outra máquina
    (ou para dentro do executável portátil) sem carregar as pastas desta.
    """
    saida = copy.deepcopy(config)
    for secao, chave in DERIVADOS:
        if isinstance(saida.get(secao), dict):
            saida[secao].pop(chave, None)
    with open(destino, "w", encoding="utf-8") as fh:
        json.dump(saida, fh, ensure_ascii=False, indent=2)
    return destino


def importar(config, origem):
    """Lê um arquivo exportado e passa a valer, por cima do que estava.

    O conteúdo é escrito *dentro* do dicionário que já circula pelo programa,
    em vez de trocar o objeto: as abas guardam referências a ele, e trocar
    deixaria cada uma olhando para uma configuração diferente.

    Levanta ValueError quando o arquivo não é uma configuração do Dinfinity.
    """
    with open(origem, "r", encoding="utf-8") as fh:
        lido = json.load(fh)
    if not isinstance(lido, dict):
        raise ValueError("O arquivo não tem o formato de uma configuração.")
    conhecidas = set(DEFAULT_CONFIG) & set(lido)
    if not conhecidas:
        raise ValueError("O arquivo não parece ser uma configuração do Dinfinity.")
    novo = _limpar(_deep_merge(DEFAULT_CONFIG, lido))
    config.clear()
    config.update(novo)
    save_config(config)
    return sorted(conhecidas)


def ensure_dirs(config):
    pastas = [caminhos.temp_dir(), config["tts"].get("temp_dir")]
    txt = (config.get("printer", {}).get("txt_dir") or "").strip()
    if txt:
        pastas.append(txt)
    for pasta in pastas:
        if not pasta:
            continue
        try:
            os.makedirs(pasta, exist_ok=True)
        except OSError:
            pass
