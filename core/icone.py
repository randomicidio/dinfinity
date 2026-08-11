# -*- coding: utf-8 -*-
"""O ícone do Dinfinity, desenhado na hora e tingido pelo estado.

É desenhado em vez de vir de um arquivo por dois motivos: nasce nítido em
qualquer tamanho (a barra de tarefas pede um, a janela pede outro) e a cor sai
de um parâmetro, o que permite o mesmo ícone contar o que o programa está
fazendo — parado, em standby, ao vivo ou gravando.

A forma é um anel com um ponto no meio, o símbolo universal de gravação. O
fundo escuro nunca muda: só o anel e o ponto trocam de cor, para a mudança ser
percebida sem o ícone virar outro.
"""
import os
import threading

from PIL import Image, ImageDraw

from core import logger

# As cores acompanham as da bolinha de estado da barra lateral (gui/app.STATES),
# para o ícone e a janela nunca contarem histórias diferentes.
CORES = {
    "off":        "#8a8f98",   # parado
    "standby":    "#f4c542",   # esperando a live abrir
    "connecting": "#f4a742",   # conectando
    "connected":  "#c792ea",   # ao vivo — o roxo da marca
    "error":      "#ff6b6b",   # deu ruim
    "gravando":   "#d92b18",   # o vermelho do REC, quando está gravando
}
FUNDO = "#141821"

# Só a cor não separa "gravando" de "erro" a 16 px — os dois são vermelhos. O
# ponto do REC vem mais cheio, encostando no anel, como um botão de gravação de
# verdade. A forma continua a mesma, então não parece outro ícone.
_PONTO = {"gravando": 0.255}
_PONTO_PADRAO = 0.30

_cache = {}
_lock = threading.Lock()


def _misturar(cor, com, quanto):
    """Aproxima `cor` de `com` na proporção pedida (0 a 1)."""
    a = tuple(int(cor[i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(com[i:i + 2], 16) for i in (1, 3, 5))
    return tuple(int(x + (y - x) * quanto) for x, y in zip(a, b))


def desenhar(tamanho=256, estado="off"):
    """O ícone como imagem RGBA, no tamanho e no estado pedidos."""
    cor = CORES.get(estado, CORES["off"])
    # Desenhado grande e reduzido no fim: é o que dá a borda lisa, já que o
    # Pillow não suavia as formas por conta própria.
    escala = 4
    lado = tamanho * escala
    img = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    raio = int(lado * 0.22)
    d.rounded_rectangle([0, 0, lado - 1, lado - 1], radius=raio, fill=FUNDO)

    # O anel usa uma versão lavada da cor, e o ponto a cor cheia: o contraste
    # entre os dois é o que mantém a forma reconhecível mesmo a 16 px.
    anel = _misturar(cor, "#ffffff", 0.45)
    margem = lado * 0.17
    grossura = int(lado * 0.075)
    d.ellipse([margem, margem, lado - margem, lado - margem],
              outline=anel, width=grossura)

    ponto = lado * _PONTO.get(estado, _PONTO_PADRAO)
    d.ellipse([ponto, ponto, lado - ponto, lado - ponto], fill=cor)

    return img.resize((tamanho, tamanho), Image.LANCZOS)


def para_tk(tamanho, estado):
    """O ícone como PhotoImage do Tk, guardado em cache por tamanho e estado.

    O cache não é economia à toa: sem uma referência viva, o Tk recolhe a
    imagem e a janela fica com o ícone em branco.
    """
    from PIL import ImageTk

    chave = (tamanho, estado)
    with _lock:
        if chave not in _cache:
            _cache[chave] = ImageTk.PhotoImage(desenhar(tamanho, estado))
        return _cache[chave]


_icos = {}


def arquivo_ico(estado="off"):
    """Um .ico do estado, gravado em `dados/icones/`. Devolve o caminho.

    Existe porque o Windows precisa de um arquivo de verdade: o `iconbitmap`
    não aceita imagem em memória. Gerado uma vez por estado e reaproveitado.
    """
    from core import caminhos

    with _lock:
        if estado in _icos and os.path.isfile(_icos[estado]):
            return _icos[estado]
        pasta = os.path.join(caminhos.dados_dir(), "icones")
        os.makedirs(pasta, exist_ok=True)
        caminho = os.path.join(pasta, f"dinfinity-{estado}.ico")
        if not os.path.isfile(caminho):
            salvar_ico(caminho, estado=estado)
        _icos[estado] = caminho
        return caminho


def aplicar(janela, estado="off"):
    """Põe o ícone na janela e na barra de tarefas, no estado pedido.

    O `iconbitmap` não é redundância: o customtkinter põe o ícone dele por
    cima da janela a menos que este método já tenha sido chamado — é ele que
    decide, olhando um sinalizador próprio. Sem esta chamada, o programa abre
    com o ícone da biblioteca em vez do nosso.
    """
    ok = False
    try:
        janela.iconbitmap(arquivo_ico(estado))
        ok = True
    except Exception as exc:  # noqa: BLE001
        logger.log("warning", f"[ÍCONE] Não consegui aplicar o .ico: {exc}")
    try:
        # Dois tamanhos: o Windows pega o maior para a barra de tarefas e o
        # menor para o canto da janela.
        janela.iconphoto(True, para_tk(48, estado), para_tk(16, estado))
        ok = True
    except Exception as exc:  # noqa: BLE001 — sem ícone o programa abre igual
        logger.log("warning", f"[ÍCONE] Não consegui aplicar o ícone: {exc}")
    return ok


def registrar_no_windows(app_id="Dinfinity.TikTokLiveSuite"):
    """Dá ao processo uma identidade própria na barra de tarefas do Windows.

    Sem isto o Windows agrupa a janela sob o ícone do python.exe, e o ícone
    escolhido aqui não aparece no botão da barra.
    """
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
        return True
    except Exception:  # noqa: BLE001
        return False


def salvar_ico(destino, tamanhos=(16, 24, 32, 48, 64, 128, 256), estado="connected"):
    """Grava o .ico usado ao empacotar o programa com o PyInstaller."""
    base = desenhar(max(tamanhos), estado)
    base.save(destino, format="ICO",
              sizes=[(t, t) for t in sorted(tamanhos)])
    return destino
