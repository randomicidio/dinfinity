# -*- coding: utf-8 -*-
"""Impressão do cartão de agradecimento.

O cartão é desenhado com Pillow e enviado direto para a impressora do Windows.
Antes isto passava por wkhtmltopdf (HTML -> PDF) e PDFtoPrinter (PDF -> fila de
impressão): dois programas externos que precisavam estar instalados e
configurados à mão. Desenhar e imprimir aqui deixa o Dinfinity independente e
tira quatro campos da tela de configuração.

Os textos de cima e de baixo são livres e aceitam os mesmos curingas das outras
ações ({nickname}, {gift_pt}, {count}...). Quem edita vê a prévia montada na
hora, na própria tela da reação.
"""
import io
import os
import threading

from PIL import Image, ImageDraw, ImageFont

from core import caminhos, logger

# A impressora tem um DC por vez, e a fila de agradecimentos pode disparar
# vários gifts em sequência. Um por vez, na ordem.
_lock_impressao = threading.Lock()

# O texto do cartão de sempre, agora como ponto de partida editável. As duas
# linhas vazias e o hífen no fim vêm do modelo original (`<br><br>-` no HTML):
# são o respiro entre o texto e o corte do papel.
TOPO_PADRAO = "Obrigado, {nickname}!!"
RODAPE_PADRAO = "por enviar {count} x {gift_pt}!\n\n-"

# Os curingas que fazem sentido num cartão, para a ajuda da tela de edição.
CURINGAS = [
    ("{nickname}", "nome que aparece no perfil"),
    ("{username}", "@ da pessoa"),
    ("{gift_pt}", "nome do presente em português"),
    ("{gift}", "nome do presente como o TikTok manda"),
    ("{count}", "quantas vezes o presente veio"),
    ("{diamonds}", "valor em diamantes"),
]

# O último cartão impresso, para o botão "Reimprimir última". Fica só na
# memória: é para resolver o cupom que saiu borrado agora, não histórico.
_ultima = None
_lock_ultima = threading.Lock()

# Proporções do cartão, em fração da largura imprimível. Foram tiradas de um
# PDF de verdade impresso pela versão antiga (wkhtmltopdf, página de 80 mm =
# 302 px CSS): título de 32 px, rodapé de 24 px e avatar de 300 px, tudo em
# Times New Roman **negrito** — é o negrito que dá o traço grosso e escuro na
# bobina térmica. Por serem proporções, valem em qualquer resolução: a de 203
# dpi e a de 300 dpi saem iguais.
_MARGEM = 0.025          # a margem do corpo da página (8 px em 302)
_AVATAR = 0.993
_FONTE_TITULO = 0.106
_FONTE_TEXTO = 0.079
_ESPACO_TITULO = 0.071   # margem de baixo do <h1> (0.67em de 32 px)
_ESPACO_RODAPE = 0.066   # margem de cima do <h2> (0.83em de 24 px)
_ENTRELINHA = 1.2        # o mesmo respiro entre linhas que o navegador usava


def _carregar_fonte(tamanho):
    """Times New Roman Negrito, a mesma que o cartão sempre usou.

    O negrito não é enfeite: numa impressora térmica ele é o que separa um
    texto legível de longe de um cinza fininho. As outras da lista são só a
    rede de segurança para uma máquina sem a Times.
    """
    pasta = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    tentativas = [os.path.join(pasta, nome) for nome in
                  ("timesbd.ttf", "arialbd.ttf", "segoeuib.ttf", "calibrib.ttf")]
    embutida = caminhos.fonte()
    if embutida:
        tentativas.append(embutida)
    for arquivo in tentativas:
        try:
            return ImageFont.truetype(arquivo, tamanho)
        except (OSError, ValueError):
            continue
    return ImageFont.load_default()


# Faixas de emoji e símbolos que a Times New Roman não tem. Nick de TikTok vive
# cheio deles, e sem uma fonte de reserva cada um vira um quadradinho vazio no
# cupom — era assim que o cartão antigo saía.
_FAIXAS_EMOJI = (
    (0x1F000, 0x1FAFF),   # emoji em geral
    (0x2600, 0x27BF),     # símbolos diversos e dingbats
    (0x2B00, 0x2BFF),     # setas e formas (a estrela ⭐ mora aqui)
    (0x2190, 0x21FF),     # setas
    (0x2460, 0x24FF),     # números em círculo
)

# Marcas invisíveis que só dizem "desenhe o anterior como emoji". Sem uma
# camada de shaping, a Pillow as trata como glifo de verdade e abre um buraco
# largo no meio do nome — some com elas antes de medir qualquer coisa.
_INVISIVEIS = ("️", "︎", "‍", "​")
# A Segoe UI Emoji desenha um pouco maior que a Times no mesmo corpo; encolher
# um tico deixa o emoji da altura das letras em vez de saltando da linha.
_ESCALA_EMOJI = 0.88


def _e_emoji(ch):
    return any(ini <= ord(ch) <= fim for ini, fim in _FAIXAS_EMOJI)


def _limpar_invisiveis(texto):
    for marca in _INVISIVEIS:
        texto = texto.replace(marca, "")
    return texto


def _fonte_emoji(tamanho):
    """Segoe UI Emoji, a reserva para o que a Times não tem."""
    caminho = os.path.join(os.environ.get("WINDIR", r"C:\Windows"),
                           "Fonts", "seguiemj.ttf")
    try:
        return ImageFont.truetype(caminho, max(1, int(tamanho * _ESCALA_EMOJI)))
    except (OSError, ValueError):
        return None


class Escritor:
    """Escreve uma linha misturando a fonte do texto com a dos emojis.

    A Pillow desenha com uma fonte só por chamada, então o texto é partido em
    trechos e cada um vai com a sua. Todos são alinhados pela mesma linha de
    base — sem isso o emoji flutuaria acima das letras, porque as duas fontes
    têm alturas diferentes.
    """

    def __init__(self, draw, fonte):
        self.draw = draw
        self.fonte = fonte
        self.emoji = _fonte_emoji(fonte.size)
        self.ascendente = fonte.getmetrics()[0]

    def _trechos(self, texto):
        """Parte o texto em (pedaço, é_emoji), juntando caracteres vizinhos."""
        texto = _limpar_invisiveis(str(texto))
        if self.emoji is None:
            # Sem a fonte de reserva, o emoji sairia como caixinha vazia:
            # melhor tirar e deixar o nome limpo.
            yield "".join(c for c in texto if not _e_emoji(c)), False
            return
        atual, tipo = "", None
        for ch in texto:
            marca = _e_emoji(ch)
            if tipo is None or marca == tipo:
                atual, tipo = atual + ch, marca
            else:
                yield atual, tipo
                atual, tipo = ch, marca
        if atual:
            yield atual, tipo

    def _fonte_de(self, e_emoji):
        return self.emoji if e_emoji else self.fonte

    def largura(self, texto):
        return sum(self.draw.textlength(t, font=self._fonte_de(m))
                   for t, m in self._trechos(texto) if t)

    def escrever(self, x, y, texto):
        """Desenha a partir do canto superior esquerdo (x, y)."""
        base = y + self.ascendente
        for trecho, marca in self._trechos(texto):
            if not trecho:
                continue
            fonte = self._fonte_de(marca)
            # `embedded_color` é o que traz o emoji colorido em vez do contorno.
            self.draw.text((x, base), trecho, font=fonte, fill="black",
                           anchor="ls", embedded_color=marca)
            x += self.draw.textlength(trecho, font=fonte)


def _partir_palavra(escritor, palavra, largura):
    """Corta no meio uma palavra que sozinha não cabe na linha.

    Nick de TikTok costuma ser um bloco só, com underscore no lugar do espaço
    (`um_nick_bem_comprido_assim`). Sem este corte ele sai sangrando pelos dois
    lados da bobina — e isso só aparece ao vivo, com o gift já na tela.
    """
    pedacos, atual = [], ""
    for letra in palavra:
        if atual and escritor.largura(atual + letra) > largura:
            pedacos.append(atual)
            atual = letra
        else:
            atual += letra
    if atual:
        pedacos.append(atual)
    return pedacos or [palavra]


def _quebrar_paragrafo(escritor, texto, largura):
    """Quebra um parágrafo em linhas que cabem na largura, medindo de verdade.

    A medida é feita nas fontes reais porque nick tem emoji e acento: contar
    caractere erra feio.
    """
    linhas, atual = [], ""
    for palavra in str(texto).split():
        if escritor.largura(palavra) > largura:
            if atual:
                linhas.append(atual)
                atual = ""
            pedacos = _partir_palavra(escritor, palavra, largura)
            linhas.extend(pedacos[:-1])
            atual = pedacos[-1]
            continue
        teste = f"{atual} {palavra}".strip()
        if escritor.largura(teste) <= largura or not atual:
            atual = teste
        else:
            linhas.append(atual)
            atual = palavra
    if atual:
        linhas.append(atual)
    return linhas


def _quebrar(escritor, texto, largura):
    """As linhas do texto, respeitando as quebras que a pessoa digitou.

    Uma linha vazia vira espaço em branco no cartão — é assim que se controla o
    respiro antes do corte do papel, sem precisar de um campo separado para
    isso. O rodapé padrão já vem com duas, como no cartão de sempre.
    """
    linhas = []
    for paragrafo in str(texto).split("\n"):
        if not paragrafo.strip():
            linhas.append("")
        else:
            linhas.extend(_quebrar_paragrafo(escritor, paragrafo, largura))
    return linhas or [""]


def montar_cartao(largura_px, texto_topo, texto_rodape, image_bytes, espelhar=True):
    """Desenha o cartão e devolve a imagem pronta para imprimir.

    Os textos chegam com os curingas já trocados: quem monta o cartão não
    precisa saber de onde veio o presente.
    """
    largura_px = max(200, int(largura_px))
    margem = int(largura_px * _MARGEM)
    util = largura_px - 2 * margem

    avatar_px = max(48, min(int(largura_px * _AVATAR), util))

    fonte_titulo = _carregar_fonte(max(12, int(largura_px * _FONTE_TITULO)))
    fonte_texto = _carregar_fonte(max(10, int(largura_px * _FONTE_TEXTO)))

    # Régua descartável só para medir antes de saber a altura final.
    regua = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    medir_titulo = Escritor(regua, fonte_titulo)
    medir_rodape = Escritor(regua, fonte_texto)
    titulo = _quebrar(medir_titulo, texto_topo, util) if str(texto_topo).strip() else []
    rodape = _quebrar(medir_rodape, texto_rodape, util) if str(texto_rodape).strip() else []

    alt_titulo = int(fonte_titulo.size * _ENTRELINHA)
    alt_texto = int(fonte_texto.size * _ENTRELINHA)
    depois_titulo = int(largura_px * _ESPACO_TITULO) if titulo else 0
    antes_rodape = int(largura_px * _ESPACO_RODAPE) if rodape else 0
    altura = (margem + len(titulo) * alt_titulo + depois_titulo + avatar_px
              + antes_rodape + len(rodape) * alt_texto + margem)

    cartao = Image.new("RGB", (largura_px, altura), "white")
    draw = ImageDraw.Draw(cartao)

    escreve_titulo = Escritor(draw, fonte_titulo)
    escreve_rodape = Escritor(draw, fonte_texto)

    y = margem
    for linha in titulo:
        escreve_titulo.escrever((largura_px - escreve_titulo.largura(linha)) / 2, y, linha)
        y += alt_titulo

    y += depois_titulo
    if image_bytes:
        try:
            avatar = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        except Exception:  # noqa: BLE001 — avatar corrompido não pode matar o job
            avatar = Image.new("RGB", (avatar_px, avatar_px), "white")
    else:
        avatar = Image.new("RGB", (avatar_px, avatar_px), "white")
    avatar = avatar.resize((avatar_px, avatar_px), Image.LANCZOS)
    cartao.paste(avatar, ((largura_px - avatar_px) // 2, y))
    y += avatar_px + antes_rodape

    for linha in rodape:
        escreve_rodape.escrever((largura_px - escreve_rodape.largura(linha)) / 2, y, linha)
        y += alt_texto

    # Espelhar o cartão pronto dá o mesmo resultado de espelhar cada elemento
    # separadamente, como fazia o HTML — com uma operação só.
    return cartao.transpose(Image.FLIP_LEFT_RIGHT) if espelhar else cartao


def listar_impressoras():
    """Impressoras instaladas. A primeira é a padrão do Windows."""
    try:
        import win32print
    except ImportError:
        return []
    try:
        padrao = win32print.GetDefaultPrinter()
    except Exception:  # noqa: BLE001 — máquina sem nenhuma impressora
        padrao = ""
    nomes = []
    sinalizadores = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    try:
        for info in win32print.EnumPrinters(sinalizadores, None, 1):
            nome = info[2]
            if nome and nome not in nomes:
                nomes.append(nome)
    except Exception as exc:  # noqa: BLE001
        logger.log("error", f"[IMPRESSAO] Não consegui listar as impressoras: {exc}")
    if padrao in nomes:
        nomes.remove(padrao)
        nomes.insert(0, padrao)
    return nomes


def _imprimir_imagem(imagem, printer_name, titulo_job):
    """Manda a imagem para a fila da impressora, ajustada à área imprimível."""
    import win32con
    import win32print
    import win32ui
    from PIL import ImageWin

    nome = printer_name or win32print.GetDefaultPrinter()
    dc = win32ui.CreateDC()
    dc.CreatePrinterDC(nome)
    try:
        largura = dc.GetDeviceCaps(win32con.HORZRES)
        altura_max = dc.GetDeviceCaps(win32con.VERTRES)
        # A bobina é contínua: a altura do "papel" é só o que o driver declara
        # por página. Encolher para caber evita o cartão sair cortado ao meio.
        escala = min(largura / imagem.width, 1.0)
        alvo_w = max(1, int(imagem.width * escala))
        alvo_h = max(1, int(imagem.height * escala))
        if altura_max > 0 and alvo_h > altura_max:
            escala = altura_max / imagem.height
            alvo_w = max(1, int(imagem.width * escala))
            alvo_h = max(1, int(imagem.height * escala))

        dc.StartDoc(titulo_job)
        dc.StartPage()
        deslocamento = max(0, (largura - alvo_w) // 2)
        ImageWin.Dib(imagem).draw(
            dc.GetHandleOutput(),
            (deslocamento, 0, deslocamento + alvo_w, alvo_h),
        )
        dc.EndPage()
        dc.EndDoc()
        return nome
    finally:
        try:
            dc.DeleteDC()
        except Exception:  # noqa: BLE001
            pass


_larguras = {}


def largura_imprimivel(printer_name=""):
    """Largura útil da impressora, em pixels. 576 é a bobina de 80 mm a 203 dpi.

    Em cache porque a prévia redesenha a cada tecla digitada, e abrir um DC da
    impressora a cada vez faz a digitação engasgar.
    """
    if printer_name in _larguras:
        return _larguras[printer_name]
    largura = 576
    try:
        import win32con
        import win32print
        import win32ui

        dc = win32ui.CreateDC()
        dc.CreatePrinterDC(printer_name or win32print.GetDefaultPrinter())
        try:
            largura = dc.GetDeviceCaps(win32con.HORZRES) or 576
        finally:
            dc.DeleteDC()
    except Exception:  # noqa: BLE001 — sem impressora, a bobina padrão serve
        largura = 576
    _larguras[printer_name] = largura
    return largura


def _escrever_txts(cfg_printer, nickname, gift_pt, count):
    """Espelha os dados em .txt, para quem lê isso numa fonte de texto do OBS.

    Opcional: sem pasta configurada, não escreve nada.
    """
    base = (cfg_printer.get("txt_dir") or "").strip()
    if not base:
        return
    try:
        os.makedirs(base, exist_ok=True)
        for arquivo, conteudo in (("Nickname.txt", nickname),
                                  ("GiftName.txt", gift_pt),
                                  ("RepeatCount.txt", str(count))):
            with open(os.path.join(base, arquivo), "w", encoding="utf-8") as fh:
                fh.write(conteudo)
    except OSError as exc:
        logger.log("error", f"Erro ao escrever txts: {exc}")


def _silhueta(tamanho):
    """Um avatar genérico desenhado na hora: cabeça, ombros e um fundo em
    degradê.

    Um quadrado de cor chapada não diz nada sobre como a foto vai sair na
    bobina. Com tons claros e escuros dá para julgar o contraste do meio-tom
    antes de gastar papel.
    """
    img = Image.new("RGB", (tamanho, tamanho), "#ffffff")
    d = ImageDraw.Draw(img)
    for y in range(tamanho):          # degradê de cima para baixo
        t = y / max(1, tamanho - 1)
        d.line([(0, y), (tamanho, y)],
               fill=(int(226 - 96 * t), int(214 - 96 * t), int(240 - 88 * t)))
    cabeca = tamanho * 0.30
    centro = tamanho / 2
    d.ellipse([centro - cabeca / 2, tamanho * 0.16,
               centro + cabeca / 2, tamanho * 0.16 + cabeca],
              fill="#f6f2fb")
    ombros = tamanho * 0.74
    d.ellipse([centro - ombros / 2, tamanho * 0.56,
               centro + ombros / 2, tamanho * 1.34], fill="#f6f2fb")
    return img


def avatar_exemplo(tamanho=300):
    """A foto que a prévia usa quando não há uma de verdade à mão."""
    buf = io.BytesIO()
    _silhueta(tamanho).save(buf, "JPEG", quality=92)
    return buf.getvalue()


def dados_da_ultima():
    """(curingas, foto) do último cartão impresso, ou None.

    A prévia prefere isto: conferir o layout com o nome e a foto de quem
    mandou o presente de verdade mostra muito mais do que um exemplo genérico.
    """
    with _lock_ultima:
        if not _ultima:
            return None
        return dict(_ultima.get("extras") or {}), _ultima["image_bytes"]


def previa(texto_topo, texto_rodape, image_bytes=None, printer_name="", espelhar=True):
    """O cartão como imagem, sem imprimir — para conferir o layout na tela."""
    if image_bytes is None:
        ultima = dados_da_ultima()
        image_bytes = ultima[1] if ultima and ultima[1] else avatar_exemplo()
    return montar_cartao(largura_imprimivel(printer_name), texto_topo, texto_rodape,
                         image_bytes, espelhar)


def imprimir(texto_topo, texto_rodape, image_bytes, printer_name="", espelhar=True,
             txt_cfg=None, dados_txt=None, guardar=True, extras=None):
    """Monta e imprime o cartão. Bloqueante -> rodar em thread.

    `guardar` deixa este cartão pronto para o botão "Reimprimir última"; o
    próprio reimprimir passa False para não se guardar de novo.
    """
    global _ultima
    nome_impressora = (printer_name or "").strip()
    with _lock_impressao:
        try:
            largura = largura_imprimivel(nome_impressora)
            cartao = montar_cartao(largura, texto_topo, texto_rodape, image_bytes, espelhar)
            titulo = (str(texto_topo).strip() or "cartão")[:40]
            usada = _imprimir_imagem(cartao, nome_impressora, f"Dinfinity - {titulo}")
            if txt_cfg is not None and dados_txt:
                _escrever_txts(txt_cfg, *dados_txt)
            if guardar:
                with _lock_ultima:
                    _ultima = {
                        "topo": texto_topo, "rodape": texto_rodape,
                        "image_bytes": image_bytes, "printer_name": nome_impressora,
                        "espelhar": espelhar, "extras": dict(extras or {}),
                    }
            logger.log("success", f"[IMPRESSO] {titulo} ({usada})")
            return True
        except ImportError:
            logger.log("error", "[IMPRESSAO] Falta o pywin32 (pip install pywin32).")
        except Exception as exc:  # noqa: BLE001
            logger.log("error", f"[IMPRESSAO] Falha ao imprimir: {exc}")
        return False


def tem_ultima():
    with _lock_ultima:
        return _ultima is not None


def reimprimir_ultima():
    """Manda de novo o último cartão — para quando o cupom sai borrado ou preso."""
    with _lock_ultima:
        ultima = dict(_ultima) if _ultima else None
    if not ultima:
        logger.log("warning", "[IMPRESSAO] Nada impresso ainda nesta sessão.")
        return False
    logger.log("info", "[IMPRESSAO] Reimprimindo o último cartão...")
    return imprimir(ultima["topo"], ultima["rodape"], ultima["image_bytes"],
                    ultima["printer_name"], ultima["espelhar"], guardar=False)


def test_print(texto_topo=None, texto_rodape=None, printer_name="", espelhar=True):
    """Imprime um cartão de exemplo com os textos que estão na tela."""
    return imprimir(texto_topo if texto_topo is not None else "Obrigado, Fulano!!",
                    texto_rodape if texto_rodape is not None else "por enviar 3 x Rosa!",
                    avatar_exemplo(), printer_name, espelhar)
