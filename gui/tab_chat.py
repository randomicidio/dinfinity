# -*- coding: utf-8 -*-
"""Aba Chat Automático: envia mensagens periodicamente para o chat flutuante do
TikTok LIVE Studio (automação de mouse/teclado via win32). Requer rodar como
Administrador — a elevação é pedida na hora de ligar, ver core/admin.py."""
import ctypes
from ctypes import wintypes
import random
import threading
import time
import tkinter as tk

import customtkinter as ctk

from core import logger
from core.chat_sender import (
    VK_F8,
    ChatSender,
    is_tiktok_live_window,
    uia_chat_info,
    window_rect,
)
from core.config import save_config

user32 = ctypes.windll.user32


class ChatTab(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.sender = ChatSender()
        self.sender.request_uia = self.request_uia

        chat_cfg = app.config["chat"]
        self.sender.input_offset = chat_cfg.get("input_offset")
        self.sender.send_offset = chat_cfg.get("send_offset")

        self.running = False
        self.stop_event = threading.Event()
        self.worker = None
        self.active_interval = None
        self.active_messages = []
        self.config_phase = None
        self.main_thread = threading.current_thread()
        self.uia_event = threading.Event()
        self.uia_pending = None
        self.uia_result = None
        self.last_status = None
        self.last_sent = None

        self.interval = ctk.StringVar(value=str(chat_cfg.get("interval_minutes", 60)))
        self.status = ctk.StringVar(value="Parado")
        self.mensagens = self._carregar_mensagens(chat_cfg.get("messages", []))
        self._proxima = 0     # de onde continuar no modo "na ordem da lista"

        self._build()
        # Ligado na janela, e não em cada widget: no Tk o caminho do toplevel
        # entra na cadeia de bindtags de todo descendente, então um clique em
        # qualquer canto passa por aqui. (`bind_all` seria o reflexo natural,
        # mas o customtkinter o proíbe.) O `add="+"` preserva quem já ouvia.
        tk.Misc.bind(self.winfo_toplevel(), "<Button-1>", self._clique_fora, add="+")
        self.after(100, self._poll)

    @staticmethod
    def _carregar_mensagens(salvas):
        """Aceita o formato antigo (só o texto) e o novo (texto + liga/desliga).

        Antes a lista era de strings; desativar uma mensagem só era possível
        apagando. Quem já tinha mensagens salvas chega aqui com todas ligadas.
        """
        saida = []
        for item in salvas or []:
            if isinstance(item, dict):
                saida.append({"texto": str(item.get("texto", "")),
                              "ativa": bool(item.get("ativa", True))})
            elif isinstance(item, str) and item.strip():
                saida.append({"texto": item, "ativa": True})
        return saida

    # ---------------- UI ----------------
    def _build(self):
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text="Chat Automático",
                     font=ctk.CTkFont("Segoe UI", 22, "bold")
                     ).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 4))
        ctk.CTkLabel(self, text="Envia uma mensagem aleatória da lista a cada intervalo, "
                                "diretamente no chat flutuante do TikTok LIVE Studio.",
                     font=ctk.CTkFont("Segoe UI", 12), text_color=("#7a7a7a", "#9a9a9a")
                     ).grid(row=1, column=0, sticky="w", padx=16, pady=(0, 12))

        body = ctk.CTkFrame(self)
        body.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 16))
        self.grid_rowconfigure(2, weight=1)
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(1, weight=1)

        cabecalho = ctk.CTkFrame(body, fg_color="transparent")
        cabecalho.grid(row=0, column=0, sticky="we", padx=12, pady=(12, 4))
        ctk.CTkLabel(cabecalho, text="Mensagens",
                     font=ctk.CTkFont("Segoe UI", 13, "bold")).pack(side="left")
        ctk.CTkLabel(cabecalho, text="  escreva na linha de baixo para criar · arraste pelo ⠿ "
                                     "para reordenar · desmarque para guardar sem enviar",
                     font=ctk.CTkFont("Segoe UI", 11), text_color=("#7a7a7a", "#9a9a9a")
                     ).pack(side="left")
        ctk.CTkButton(cabecalho, text="+  Adicionar", width=110, command=self.add_message
                      ).pack(side="right")

        self.lista = ctk.CTkScrollableFrame(body, height=240)
        self.lista.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 8))
        self.lista.grid_columnconfigure(0, weight=1)
        self.linhas = []
        self.fantasma = None
        self._arraste = None
        self._desenhar_lista()

        opcoes = ctk.CTkFrame(body, fg_color="transparent")
        opcoes.grid(row=2, column=0, sticky="we", padx=12, pady=(4, 6))
        ctk.CTkLabel(opcoes, text="Enviar", font=ctk.CTkFont("Segoe UI", 13)
                     ).pack(side="left", padx=(0, 8))
        self.ordem_var = ctk.StringVar(
            value=self.app.config["chat"].get("ordem", "aleatoria"))
        for valor, rotulo in (("sequencia", "na ordem da lista"), ("aleatoria", "aleatório")):
            ctk.CTkRadioButton(opcoes, text=rotulo, value=valor, variable=self.ordem_var,
                               command=self.save_settings, radiobutton_width=18,
                               radiobutton_height=18, font=ctk.CTkFont("Segoe UI", 13)
                               ).pack(side="left", padx=(0, 14))

        ctk.CTkLabel(opcoes, text="   a cada", font=ctk.CTkFont("Segoe UI", 13)
                     ).pack(side="left", padx=(8, 6))
        entrada_intervalo = ctk.CTkEntry(opcoes, textvariable=self.interval, width=70)
        entrada_intervalo.pack(side="left", padx=(0, 6))
        entrada_intervalo.bind("<FocusOut>", lambda _e: self.save_settings())
        ctk.CTkLabel(opcoes, text="minutos (mínimo recomendado: 10)",
                     font=ctk.CTkFont("Segoe UI", 12), text_color=("#7a7a7a", "#9a9a9a")
                     ).pack(side="left")

        rodape = ctk.CTkFrame(body, fg_color="transparent")
        rodape.grid(row=3, column=0, sticky="we", padx=12, pady=(6, 12))
        self.start_button = ctk.CTkButton(rodape, text="Iniciar", width=130,
                                          command=self.alternar,
                                          fg_color="#4caf50", hover_color="#3d8b40")
        self.start_button.pack(side="left", padx=(0, 10))
        self.status_label = ctk.CTkLabel(rodape, textvariable=self.status,
                                         font=ctk.CTkFont("Segoe UI", 12),
                                         text_color=("#7a7a7a", "#9a9a9a"))
        self.status_label.pack(side="left")

        # A calibração é a saída de emergência: o envio tenta achar o campo
        # sozinho pela árvore de acessibilidade do Live Studio, e só quando isso
        # falha é que as posições marcadas à mão entram. Por isso ela fica
        # discreta aqui embaixo, e não como um botão do mesmo peso dos outros.
        self.offset_info = ctk.CTkLabel(
            body, text="", font=ctk.CTkFont("Segoe UI", 11),
            text_color=("#7a7a7a", "#9a9a9a"), anchor="w", justify="left")
        self.offset_info.grid(row=4, column=0, sticky="w", padx=12, pady=(0, 4))
        self.botao_calibrar = ctk.CTkButton(
            body, text="Marcar as posições à mão (F8)", width=230, height=26,
            fg_color="transparent", border_width=1, text_color=("#5a5a5a", "#9a9a9a"),
            border_color=("#c0c0c0", "#4a4a4a"), hover_color=("#e8e8e8", "#2a2a2a"),
            font=ctk.CTkFont("Segoe UI", 11), command=self.configure)
        self.botao_calibrar.grid(row=5, column=0, sticky="w", padx=12, pady=(0, 12))
        self._update_offset_info()

    # ---------------- lista de mensagens ----------------
    def _desenhar_lista(self, focar=None):
        """Redesenha as linhas. `focar` põe o cursor no fim da linha indicada."""
        for linha in self.linhas:
            linha["quadro"].destroy()
        if getattr(self, "fantasma", None) is not None:
            self.fantasma["quadro"].destroy()
        self.linhas = []
        for indice, item in enumerate(self.mensagens):
            self.linhas.append(self._linha_mensagem(indice, item))
        self.fantasma = self._linha_fantasma(len(self.mensagens))
        if focar is not None and 0 <= focar < len(self.linhas):
            campo = self.linhas[focar]["texto"]
            campo.focus_set()
            campo.icursor("end")

    def _linha_mensagem(self, indice, item):
        quadro = ctk.CTkFrame(self.lista, fg_color=("#ededed", "#2a2a2a"))
        quadro.grid(row=indice, column=0, sticky="we", pady=2)
        quadro.grid_columnconfigure(2, weight=1)

        pegador = ctk.CTkLabel(quadro, text="⠿", width=24, cursor="fleur",
                               text_color=("#8a8a8a", "#7a7a7a"),
                               font=ctk.CTkFont("Segoe UI", 15))
        pegador.grid(row=0, column=0, padx=(6, 2), pady=4)
        pegador.bind("<Button-1>", lambda e, i=indice: self._arraste_inicio(i))
        pegador.bind("<B1-Motion>", self._arraste_move)
        pegador.bind("<ButtonRelease-1>", lambda e: self._arraste_fim())

        ativa = ctk.BooleanVar(value=bool(item.get("ativa", True)))
        ctk.CTkCheckBox(quadro, text="", variable=ativa, width=24,
                        checkbox_width=18, checkbox_height=18,
                        command=self.save_settings).grid(row=0, column=1, padx=(0, 6))

        texto = ctk.CTkEntry(quadro, border_width=0, fg_color="transparent",
                             font=ctk.CTkFont("Segoe UI", 13))
        texto.insert(0, item.get("texto", ""))
        texto.grid(row=0, column=2, sticky="we", pady=2)
        texto.bind("<FocusOut>", lambda _e: self.save_settings())
        texto.bind("<Return>", lambda _e: self._confirmar_edicao())

        ctk.CTkButton(quadro, text="✕", width=28, height=26, fg_color="transparent",
                      text_color=("#a05050", "#c07070"), hover_color=("#e0c0c0", "#4a2a2a"),
                      command=lambda i=indice: self.remove_message(i)
                      ).grid(row=0, column=3, padx=(4, 6))

        return {"quadro": quadro, "texto": texto, "ativa": ativa}

    def _linha_fantasma(self, indice):
        """A linha vazia do fim: escrever nela já cria a mensagem.

        Vale também como estado inicial — com a lista vazia, é ela que convida
        a digitar, sem precisar caçar um botão antes.
        """
        quadro = ctk.CTkFrame(self.lista, fg_color="transparent")
        quadro.grid(row=indice, column=0, sticky="we", pady=2)
        quadro.grid_columnconfigure(2, weight=1)

        ctk.CTkLabel(quadro, text="+", width=24, text_color=("#9a9a9a", "#6a6a6a"),
                     font=ctk.CTkFont("Segoe UI", 15)).grid(row=0, column=0, padx=(6, 2), pady=4)
        ctk.CTkLabel(quadro, text="", width=24).grid(row=0, column=1, padx=(0, 6))

        texto = ctk.CTkEntry(quadro, border_width=0, fg_color="transparent",
                             font=ctk.CTkFont("Segoe UI", 13),
                             placeholder_text="Escrever nova mensagem...")
        texto.grid(row=0, column=2, sticky="we", pady=2)
        texto.bind("<KeyRelease>", self._fantasma_digitou)
        return {"quadro": quadro, "texto": texto, "ativa": None}

    def _fantasma_digitou(self, evento=None):
        """Primeira tecla na linha fantasma: ela vira uma mensagem de verdade.

        A troca é adiada para o próximo respiro do Tk porque este mesmo widget
        é destruído no redesenho — mexer nele no meio do próprio evento é
        pedir erro.
        """
        conteudo = self.fantasma["texto"].get()
        if not conteudo.strip():
            return
        self._coletar()
        self.mensagens.append({"texto": conteudo, "ativa": True})
        novo = len(self.mensagens) - 1
        self.after_idle(lambda: self._promover(novo))

    def _promover(self, indice):
        self._desenhar_lista(focar=indice)
        self.save_settings()

    def _confirmar_edicao(self):
        """Grava e devolve o foco: o campo para de piscar e sai do caminho."""
        self.save_settings()
        self.lista.focus_set()

    def _campos_de_texto(self):
        """Os widgets Tk de verdade por trás dos campos — o CTkEntry embrulha um.

        É com eles que o `focus_get` e o alvo do clique se comparam; comparar
        com o CTkEntry nunca casaria.
        """
        caixas = [linha["texto"] for linha in self.linhas]
        if self.fantasma is not None:
            caixas.append(self.fantasma["texto"])
        return [c._entry for c in caixas if c is not None]

    def _clique_fora(self, evento):
        """Clicar em qualquer outro lugar também fecha a edição.

        No Tk, clicar num quadro ou numa etiqueta não tira o foco de um campo
        de texto — ele continuaria piscando enquanto a pessoa já foi mexer em
        outra coisa. O laço é global de propósito (o clique pode cair em
        qualquer canto da janela), mas só faz alguma coisa quando um campo
        desta aba está mesmo em edição.
        """
        try:
            campos = self._campos_de_texto()
            if not campos or self.focus_get() not in campos:
                return
            if evento.widget in campos:
                return                    # foi para outro campo da lista
        except Exception:  # noqa: BLE001 — clique durante um redesenho
            return
        self._confirmar_edicao()

    def _coletar(self):
        """Lê o que está na tela de volta para a lista em memória."""
        for item, linha in zip(self.mensagens, self.linhas):
            item["texto"] = linha["texto"].get()
            item["ativa"] = bool(linha["ativa"].get())

    # ---------------- arrastar para reordenar ----------------
    def _arraste_inicio(self, indice):
        self._coletar()
        self._arraste = indice

    def _arraste_move(self, evento):
        """Troca a linha de lugar assim que o ponteiro passa por outra.

        A posição vem da altura da própria linha, e não de um valor fixo: o
        tamanho muda com o tema e com a escala da tela.
        """
        if self._arraste is None or not self.linhas:
            return
        origem = self.linhas[self._arraste]["quadro"]
        altura = max(1, origem.winfo_height() + 4)
        y = origem.winfo_rooty() + evento.y - self.lista.winfo_rooty()
        destino = max(0, min(len(self.mensagens) - 1, int(y // altura)))
        if destino != self._arraste:
            self.mensagens.insert(destino, self.mensagens.pop(self._arraste))
            self._arraste = destino
            self._desenhar_lista()

    def _arraste_fim(self):
        if self._arraste is not None:
            self._arraste = None
            self.save_settings()

    # ---------------- mensagens / config ----------------
    def save_settings(self):
        self._coletar()
        chat_cfg = self.app.config["chat"]
        try:
            chat_cfg["interval_minutes"] = self.get_interval()
        except ValueError:
            pass          # intervalo inválido não pode impedir de salvar o resto
        chat_cfg["messages"] = [dict(m) for m in self.mensagens]
        chat_cfg["ordem"] = self.ordem_var.get()
        chat_cfg["input_offset"] = self.sender.input_offset
        chat_cfg["send_offset"] = self.sender.send_offset
        save_config(self.app.config)

    def get_interval(self):
        try:
            minutes = int(self.interval.get())
            if minutes < 1:
                raise ValueError
            return minutes
        except ValueError:
            raise ValueError("Informe um intervalo inteiro de pelo menos 1 minuto.")

    def add_message(self):
        """O botão só leva o cursor para a linha vazia do fim.

        Quem digita lá já cria a mensagem sozinho, então criar uma linha vazia
        aqui deixaria uma sobrando toda vez que alguém clicasse sem escrever.
        """
        if self.fantasma is not None:
            self.fantasma["texto"].focus_set()

    def remove_message(self, indice):
        self._coletar()
        if 0 <= indice < len(self.mensagens):
            del self.mensagens[indice]
            self._desenhar_lista()
            self.save_settings()

    def _info(self, text):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Chat Automático")
        dialog.geometry("520x300")
        dialog.transient(self.winfo_toplevel())
        ctk.CTkLabel(dialog, text=text, wraplength=480, justify="left",
                     font=ctk.CTkFont("Segoe UI", 12)).pack(padx=20, pady=20)
        ctk.CTkButton(dialog, text="OK", width=90, command=dialog.destroy).pack(pady=8)

    # ---------------- configuração por F8 ----------------
    def configure(self):
        self.config_phase = "field"
        self.status.set("Passo 1 de 2: aponte o mouse para o CAMPO DE TEXTO do chat e pressione F8.")
        self.after(50, self.wait_for_f8)

    def wait_for_f8(self):
        if self.config_phase is None:
            return
        if user32.GetAsyncKeyState(VK_F8) & 1:
            point = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(point))
            child = user32.WindowFromPoint(point)
            hwnd = user32.GetAncestor(child, 2)  # GA_ROOT
            if hwnd and is_tiktok_live_window(hwnd):
                rect = window_rect(hwnd)
                offset = (point.x - rect.left, rect.bottom - point.y)
                if offset[0] >= 0 and offset[1] >= 0:
                    self.sender.chat_hwnd = hwnd
                    if self.config_phase == "field":
                        self.sender.input_offset = offset
                        self.config_phase = "send"
                        self.status.set("Passo 2 de 2: aponte para a SETINHA DE ENVIAR e pressione F8.")
                    else:
                        self.sender.send_offset = offset
                        self.config_phase = None
                        self.save_settings()
                        self.status.set("Configurado. Use “Testar clique” para verificar a posição.")
                        self._update_offset_info()
                    self.after(50, self.wait_for_f8)
                    return
            self.config_phase = None
            self.status.set("Não consegui registrar. Aponte para a janela do Live Studio e use “Configurar” de novo.")
            return
        self.after(50, self.wait_for_f8)

    def _update_offset_info(self):
        chat_cfg = self.app.config["chat"]
        if chat_cfg.get("input_offset"):
            self.offset_info.configure(
                text="O envio procura o campo sozinho na janela do Live Studio. "
                     f"Há posições marcadas à mão como reserva: campo "
                     f"{chat_cfg.get('input_offset')} · enviar {chat_cfg.get('send_offset')}.")
        else:
            self.offset_info.configure(
                text="O envio procura o campo sozinho na janela do Live Studio. "
                     "Só marque as posições à mão se ele reclamar que não achou.")

    # ---------------- UIA via thread principal ----------------
    def request_uia(self, hwnd, timeout=4.0):
        if threading.current_thread() is self.main_thread:
            try:
                return uia_chat_info(hwnd)
            except Exception:
                return None
        self.uia_event.clear()
        self.uia_result = None
        self.uia_pending = hwnd
        done = self.uia_event.wait(timeout)
        return self.uia_result if done else None

    def _poll(self):
        try:
            if self.last_status is not None:
                self.status.set(self.last_status)
                self.last_status = None
            if self.uia_pending is not None:
                hwnd = self.uia_pending
                self.uia_pending = None
                try:
                    self.uia_result = uia_chat_info(hwnd)
                except Exception as error:
                    logger.log("error", f"UIA: {error}")
                    self.uia_result = None
                self.uia_event.set()
        finally:
            self.after(100, self._poll)

    # ---------------- administrador ----------------
    def _garantir_admin(self, o_que="ligar o Chat Automático"):
        """Confere o privilégio e, se faltar, oferece reabrir elevado.

        Só esta aba precisa: o Windows não deixa um processo comum mandar
        cliques e teclas para a janela do TikTok LIVE Studio. Devolve True se
        já dá para seguir.
        """
        from core.admin import (ARG_CHAT, ARG_INSTALAR, e_admin, pedir_abertura_no_chat,
                                relancar_como_admin, tarefa_valida)

        if e_admin():
            return True

        # A tarefa já existe (o programa foi aberto por fora dela, por um
        # atalho antigo): não há o que perguntar, é só reabrir por ela.
        if tarefa_valida():
            from core.admin import abrir_pela_tarefa
            pedir_abertura_no_chat()
            if abrir_pela_tarefa():
                self.app.on_close()
                return False

        escolha = self._perguntar_elevacao(o_que)
        if escolha is None:
            self._info("O Chat Automático só funciona com o programa como Administrador.")
            return False
        if escolha == "ao_abrir":
            # Da próxima vez o UAC vem antes de tudo subir (ver
            # Dinfinity._elevar_no_arranque) e nada é interrompido.
            self.app.config["app"]["abrir_como_admin"] = True
            save_config(self.app.config)
        extra = f"{ARG_INSTALAR} {ARG_CHAT}" if escolha == "sempre" else ARG_CHAT
        if relancar_como_admin(extra):
            # A cópia elevada já está subindo; esta sai pela porta de sempre,
            # salvando o config e soltando as travas.
            self.app.on_close()
        else:
            self._info("O Windows recusou a elevação. O programa continua aberto.")
        return False

    def _perguntar_elevacao(self, o_que):
        """As três saídas. Devolve "sempre", "ao_abrir", "agora" ou None.

        Todas passam por reabrir o programa agora — o Windows não eleva um
        processo já em pé. A diferença é o que acontece das próximas vezes: as
        duas primeiras fazem a elevação no arranque, antes de a live conectar e
        o gravador subir, e aí nada mais é interrompido.
        """
        gravando = getattr(self.app, "recorder_host", None) is not None \
            and self.app.recorder_host.recording

        janela = ctk.CTkToplevel(self)
        janela.title("Abrir como Administrador")
        janela.geometry("600x430")
        janela.transient(self.winfo_toplevel())
        janela.grab_set()
        janela.resizable(False, False)

        resposta = {"valor": None}

        ctk.CTkLabel(janela, text="O Chat Automático precisa de Administrador",
                     font=ctk.CTkFont("Segoe UI", 16, "bold")
                     ).pack(anchor="w", padx=20, pady=(20, 6))
        ctk.CTkLabel(
            janela,
            text=(f"Para {o_que}, o Windows exige que o Dinfinity rode como "
                  "Administrador — é o que permite controlar a janela do TikTok "
                  "LIVE Studio. As outras abas funcionam sem isso."),
            font=ctk.CTkFont("Segoe UI", 12), text_color=("#5a5a5a", "#a5a5a5"),
            wraplength=555, justify="left", anchor="w").pack(anchor="w", padx=20)

        aviso = ("⚠  O programa precisa fechar e abrir de novo. A live desconecta, "
                 "o log se perde e uma gravação em andamento é encerrada.")
        if gravando:
            aviso = ("⚠  HÁ UMA GRAVAÇÃO EM ANDAMENTO. Reabrir agora encerra a "
                     "sessão de gravação. Considere parar a gravação antes, ou "
                     "escolher uma das opções de cima e reabrir mais tarde.")
        ctk.CTkLabel(janela, text=aviso, font=ctk.CTkFont("Segoe UI", 12, "bold"),
                     text_color=("#b04a00", "#f4a742"), wraplength=555,
                     justify="left", anchor="w").pack(anchor="w", padx=20, pady=(12, 4))

        ctk.CTkLabel(
            janela,
            text=("Das próximas vezes:\n"
                  "•  Sempre — cria uma tarefa no Windows e o programa já abre elevado, "
                  "sem perguntar nada. Em troca, quem puder trocar os arquivos desta "
                  "pasta ganha o mesmo privilégio.\n"
                  "•  Perguntar ao abrir — o UAC aparece na abertura, antes de a live "
                  "conectar. Nada é interrompido.\n"
                  "•  Só desta vez — não muda nada; da próxima vez você passa por aqui "
                  "de novo.\n\n"
                  "As duas primeiras podem ser desfeitas em Configurações."),
            font=ctk.CTkFont("Segoe UI", 11), text_color=("#7a7a7a", "#8a8a8a"),
            wraplength=555, justify="left", anchor="w").pack(anchor="w", padx=20, pady=(8, 0))

        def responder(valor):
            resposta["valor"] = valor
            janela.destroy()

        botoes = ctk.CTkFrame(janela, fg_color="transparent")
        botoes.pack(side="bottom", fill="x", padx=20, pady=16)
        ctk.CTkButton(botoes, text="Sempre (sem perguntar)", width=190,
                      command=lambda: responder("sempre"),
                      fg_color="#4caf50", hover_color="#3d8b40").pack(side="left")
        ctk.CTkButton(botoes, text="Perguntar ao abrir", width=150,
                      command=lambda: responder("ao_abrir")).pack(side="left", padx=8)
        ctk.CTkButton(botoes, text="Só desta vez", width=110, fg_color="#555555",
                      hover_color="#444444", command=lambda: responder("agora")
                      ).pack(side="left")
        ctk.CTkButton(botoes, text="Cancelar", width=100, fg_color="transparent",
                      border_width=1, text_color=("#5a5a5a", "#9a9a9a"),
                      command=lambda: responder(None)).pack(side="right")

        janela.protocol("WM_DELETE_WINDOW", lambda: responder(None))
        janela.wait_window()
        return resposta["valor"]

    # ---------------- start / stop ----------------
    def alternar(self):
        """O botão é um só e faz o que falta: ligar ou desligar."""
        if self.running:
            self.stop()
        else:
            self.start()

    def _atualizar_botao(self):
        if self.running:
            self.start_button.configure(text="Parar", fg_color="#c0392b",
                                        hover_color="#922b21")
        else:
            self.start_button.configure(text="Iniciar", fg_color="#4caf50",
                                        hover_color="#3d8b40")

    def start(self):
        if not self._garantir_admin():
            return
        try:
            interval = self.get_interval()
        except ValueError as error:
            self._info(str(error))
            return
        self._coletar()
        ativas = [m["texto"] for m in self.mensagens
                  if m.get("ativa") and m.get("texto", "").strip()]
        if not ativas:
            self._info("Nenhuma mensagem ativa. Adicione uma, ou marque alguma das "
                       "que estão desmarcadas.")
            return
        if self.running:
            return
        self.save_settings()
        self.active_interval = interval
        self.active_messages = ativas
        self._proxima = 0
        self.running = True
        self.stop_event.clear()
        self._atualizar_botao()
        self.status.set(f"Ativo — primeira mensagem em {interval} minuto(s).")
        self.worker = threading.Thread(target=self.send_loop, daemon=True)
        self.worker.start()
        logger.log("system", f"Chat automático iniciado ({len(ativas)} mensagem(ns), "
                             f"intervalo {interval} min).")

    def stop(self):
        self.running = False
        self.stop_event.set()
        self._atualizar_botao()
        self.status.set("Parado")
        logger.log("system", "Chat automático parado.")

    def _proxima_mensagem(self):
        """A próxima a enviar, conforme o modo escolhido.

        No aleatório, sortear entre as que não são a última evita a repetição
        logo em seguida — que é o que mais chama atenção de quem assiste.
        """
        if len(self.active_messages) == 1:
            return self.active_messages[0]
        if self.ordem_var.get() == "sequencia":
            mensagem = self.active_messages[self._proxima % len(self.active_messages)]
            self._proxima += 1
            return mensagem
        candidatas = [m for m in self.active_messages if m != self.last_sent] \
            or self.active_messages
        return random.choice(candidatas)

    def send_loop(self):
        while not self.stop_event.wait(self.active_interval * 60):
            message = self._proxima_mensagem()
            try:
                self.sender.send_once(message)
                self.last_sent = message
                self.last_status = f"Enviada às {time.strftime('%H:%M')}."
                logger.log("success", f"[CHAT] Enviada: {message}")
            except RuntimeError as error:
                self.last_status = str(error)
                logger.log("warning", f"[CHAT] {error}")
            except Exception as error:
                self.last_status = f"Erro ao enviar: {error}"
                logger.log("error", f"[CHAT] {error}")

    def _bring_to_front(self, hwnd):
        from core.chat_sender import bring_to_foreground
        bring_to_foreground(hwnd)

    def refresh_if_needed(self):
        self._update_offset_info()
