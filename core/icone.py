# -*- coding: utf-8 -*-
"""O ícone do Dinfinity, desenhado na hora e tingido pelo estado.

É desenhado em vez de vir de um arquivo por dois motivos: nasce nítido em
qualquer tamanho (a barra de tarefas pede um, a janela pede outro) e a cor sai
de um parâmetro, o que permite o mesmo ícone contar em que pé está a gravação
— parado, armado esperando a live, ou gravando.

A forma é um anel com um ponto no meio, o símbolo universal de gravação. O
fundo escuro nunca muda: só o anel e o ponto trocam de cor, para a mudança ser
percebida sem o ícone virar outro.
"""
import os
import threading

from PIL import Image, ImageDraw

from core import logger

# O ícone conta o que o **gravador** está fazendo, e não o que o monitor da
# live está fazendo. São coisas diferentes: o monitor fica em standby o tempo
# todo esperando a live abrir, e pintar isso de amarelo daria alarme falso de
# "prestes a gravar" mesmo com o REC desarmado.
#
# Parado é o roxo da marca, e não um cinza: é o estado em que o programa passa
# a maior parte do tempo e o que aparece ao abrir, então é ele que dá a cara do
# Dinfinity na barra de tarefas.
CORES = {
    "parado":     "#c792ea",   # o gravador não vai gravar nada
    "aguardando": "#f4c542",   # armado: a próxima live será gravada
    "gravando":   "#d92b18",   # o vermelho do REC, gravando agora
    "erro":       "#ff6b6b",   # a conexão com a live falhou
}
FUNDO = "#141821"

# Só a cor não separa "gravando" de "erro" a 16 px — os dois são vermelhos. O
# ponto do REC vem mais cheio, encostando no anel, como um botão de gravação de
# verdade. A forma continua a mesma, então não parece outro ícone.
_PONTO = {"gravando": 0.255}
_PONTO_PADRAO = 0.30

_ESTADO_PADRAO = "parado"

_cache = {}
_lock = threading.Lock()


def _misturar(cor, com, quanto):
    """Aproxima `cor` de `com` na proporção pedida (0 a 1)."""
    a = tuple(int(cor[i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(com[i:i + 2], 16) for i in (1, 3, 5))
    return tuple(int(x + (y - x) * quanto) for x, y in zip(a, b))


def desenhar(tamanho=256, estado=_ESTADO_PADRAO):
    """O ícone como imagem RGBA, no tamanho e no estado pedidos."""
    cor = CORES.get(estado, CORES[_ESTADO_PADRAO])
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


def arquivo_ico(estado=_ESTADO_PADRAO):
    """Um .ico do estado, gravado em `dados/icones/`. Devolve o caminho.

    Existe porque o Windows precisa de um arquivo de verdade: o `iconbitmap`
    não aceita imagem em memória. Gerado uma vez por estado e reaproveitado.

    A cor entra no nome do arquivo de propósito: mudar a paleta passa a gerar
    um arquivo novo sozinho, em vez de deixar quem já rodou o programa preso ao
    desenho antigo — o cache só sabe olhar se o arquivo existe.
    """
    from core import caminhos

    with _lock:
        if estado in _icos and os.path.isfile(_icos[estado]):
            return _icos[estado]
        pasta = os.path.join(caminhos.dados_dir(), "icones")
        os.makedirs(pasta, exist_ok=True)
        cor = CORES.get(estado, CORES[_ESTADO_PADRAO]).lstrip("#")
        caminho = os.path.join(pasta, f"dinfinity-{estado}-{cor}.ico")
        if not os.path.isfile(caminho):
            salvar_ico(caminho, estado=estado)
            _limpar_antigos(pasta, estado, os.path.basename(caminho))
        _icos[estado] = caminho
        return caminho


def _limpar_antigos(pasta, estado, manter):
    """Apaga os .ico deste estado que sobraram de uma paleta anterior."""
    try:
        for nome in os.listdir(pasta):
            if nome.startswith(f"dinfinity-{estado}") and nome != manter:
                os.remove(os.path.join(pasta, nome))
    except OSError:
        pass


def aplicar(janela, estado=_ESTADO_PADRAO):
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


def salvar_ico(destino, tamanhos=(16, 24, 32, 48, 64, 128, 256), estado=_ESTADO_PADRAO):
    """Grava um .ico. O padrão é o estado parado, que é a cara do programa."""
    base = desenhar(max(tamanhos), estado)
    base.save(destino, format="ICO",
              sizes=[(t, t) for t in sorted(tamanhos)])
    return destino
