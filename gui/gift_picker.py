# -*- coding: utf-8 -*-
"""Seletor visual de presentes do TikTok.

Mostra a grade com a figura, o nome e o valor em diamantes de cada presente do
painel do Brasil, com busca por nome. É aberto pelo gatilho "Presente
específico".

Três decisões que fazem a janela abrir rápido, com 568 presentes:

  - a lista que já está pronta aparece na hora; a busca no TikTok (quando o
    cache está vencido) acontece atrás e só reescreve o que mudou;
  - as células são criadas uma vez e **reaproveitadas**. Filtrar não destrói
    nem recria nada — só troca o texto e a figura de cada célula e esconde as
    que sobraram;
  - as figuras ficam num cache de módulo, então reabrir o seletor na mesma
    sessão não relê nada do disco.
"""
import queue
import threading
import tkinter as tk

import customtkinter as ctk
from PIL import Image, ImageTk

from core import gifts_catalog, logger

TAM_ICONE = 30
COLUNAS = 6
# Baixar 568 figuras uma a uma demoraria; mais que isto só disputa a rede com
# a live que está acontecendo.
THREADS = 6
# Células criadas por vez ao encher a grade: o suficiente para não travar a
# janela entre um bloco e outro.
BLOCO = 60

# id do presente -> ImageTk.PhotoImage. Fica no módulo de propósito: sobrevive
# ao fechar da janela, então a segunda abertura já nasce com as figuras.
_fotos = {}


class GiftPicker(ctk.CTkToplevel):
    """Janela modal que devolve o presente escolhido por `on_pick`."""

    def __init__(self, master, atual="", on_pick=None, username=""):
        super().__init__(master)
        # `on_pick` recebe o presente inteiro: o nome é o que a pessoa lê, mas
        # é o id que o gatilho usa para casar com o evento da live.
        self.on_pick = on_pick or (lambda _gift: None)
        self.username = username
        self._escolhido = atual
        self._celulas = []
        self._por_celula = {}       # célula -> id do presente que ela mostra
        self._entrega = queue.Queue()
        self._parar = threading.Event()
        self._buscando = False
        self._filtro_id = None
        self._enchendo = False

        self.title("Escolher presente")
        self.geometry("640x600")
        self.transient(master.winfo_toplevel())
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._fechar)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        topo = ctk.CTkFrame(self, fg_color="transparent")
        topo.grid(row=0, column=0, sticky="we", padx=14, pady=(14, 6))
        topo.grid_columnconfigure(0, weight=1)

        self.busca_var = ctk.StringVar()
        self.busca_var.trace_add("write", lambda *_: self._agendar_filtro())
        ctk.CTkEntry(topo, textvariable=self.busca_var,
                     placeholder_text="Procurar presente pelo nome...").grid(
            row=0, column=0, sticky="we", padx=(0, 8))
        self.btn_atualizar = ctk.CTkButton(topo, text="Atualizar lista", width=130,
                                           command=self._atualizar_catalogo)
        self.btn_atualizar.grid(row=0, column=1)

        self.grade = ctk.CTkScrollableFrame(self)
        self.grade.grid(row=1, column=0, sticky="nsew", padx=14, pady=6)
        for c in range(COLUNAS):
            self.grade.grid_columnconfigure(c, weight=1)

        rodape = ctk.CTkFrame(self, fg_color="transparent")
        rodape.grid(row=2, column=0, sticky="we", padx=14, pady=(4, 14))
        rodape.grid_columnconfigure(0, weight=1)
        self.info = ctk.CTkLabel(rodape, text="", anchor="w",
                                 font=ctk.CTkFont("Segoe UI", 11),
                                 text_color=("#7a7a7a", "#9a9a9a"))
        self.info.grid(row=0, column=0, sticky="w")
        ctk.CTkButton(rodape, text="Cancelar", width=100, fg_color="#555555",
                      hover_color="#3d3d3d", command=self._fechar).grid(row=0, column=1, padx=4)

        escuro = ctk.get_appearance_mode().lower() == "dark"
        self._cor_fundo = "#2b2b2b" if escuro else "#ebebeb"
        self._cor_sel = "#3a2b4d" if escuro else "#d9c7ee"
        self._cor_texto = "#dce4ee" if escuro else "#1f1f1f"

        self._aplicar(self._presentes())
        self.after(60, self._drenar_figuras)
        # Gerar a lista é o momento de conferir se ela ainda vale.
        if gifts_catalog.vencido():
            self._atualizar_catalogo(automatico=True)

    # ------------------------------------------------------------ catálogo
    def _atualizar_catalogo(self, automatico=False):
        if self._buscando:
            return
        self._buscando = True
        self.btn_atualizar.configure(state="disabled", text="Atualizando...")
        self.info.configure(text="Buscando a lista de presentes no TikTok "
                                 "(a lista atual continua valendo)...")

        def trabalhar():
            itens = gifts_catalog.fetch_gifts_async(self.username)
            try:
                self.after(0, lambda: self._catalogo_chegou(itens, automatico))
            except (tk.TclError, RuntimeError):
                pass                     # janela fechada durante a busca

        threading.Thread(target=trabalhar, daemon=True, name="gift-catalog").start()

    def _catalogo_chegou(self, itens, automatico):
        self._buscando = False
        try:
            self.btn_atualizar.configure(state="normal", text="Atualizar lista")
        except tk.TclError:
            return
        if itens:
            # Reescreve as células que existem em vez de refazer a grade.
            self._aplicar(self._presentes())
        elif not automatico:
            self.info.configure(text="Não consegui atualizar agora — a lista em "
                                     "cache continua valendo.")

    # --------------------------------------------------------------- grade
    def _agendar_filtro(self):
        """Filtrar a cada tecla é barato agora, mas 200 ms evita o tranco."""
        if self._filtro_id is not None:
            self.after_cancel(self._filtro_id)
        self._filtro_id = self.after(200, lambda: self._aplicar(self._presentes()))

    def _presentes(self):
        busca = self.busca_var.get().strip().lower()
        itens = gifts_catalog.catalog()
        if busca:
            itens = [g for g in itens if busca in (g.get("name") or "").lower()]
        return sorted(itens, key=lambda g: (g.get("diamonds", 0), g.get("name", "")))

    def _nova_celula(self):
        """Uma célula = um Label só, com a figura em cima do texto.

        Quatro widgets por presente (moldura, figura, nome, valor) davam 2.200
        widgets e quase quatro segundos para abrir. Com `compound` o mesmo
        visual sai em um widget por presente.
        """
        cel = tk.Label(self.grade, bg=self._cor_fundo, fg=self._cor_texto,
                       compound="top", font=("Segoe UI", 8),
                       wraplength=88, justify="center", cursor="hand2",
                       highlightthickness=1, highlightbackground=self._cor_fundo,
                       bd=0, padx=3, pady=5)
        cel.bind("<Button-1>", lambda _e, c=cel: self._clicou(c))
        return cel

    def _aplicar(self, itens):
        """Encaixa a lista nas células existentes, criando só o que faltar."""
        self._filtro_id = None
        self._itens = itens
        self.info.configure(text=f"{len(itens)} presente(s). Clique para escolher.")
        if not itens:
            for cel in self._celulas:
                cel.grid_remove()
            return
        self._encher(0)

    def _encher(self, inicio):
        """Preenche a grade em blocos, devolvendo o controle entre um e outro."""
        itens = self._itens
        fim = min(len(itens), inicio + BLOCO)
        for i in range(inicio, fim):
            if i >= len(self._celulas):
                self._celulas.append(self._nova_celula())
            self._pintar(self._celulas[i], itens[i])
            self._celulas[i].grid(row=i // COLUNAS, column=i % COLUNAS,
                                  sticky="nsew", padx=4, pady=4)
        if fim < len(itens):
            # after(1) e não after_idle: a tarefa ociosa rodaria antes de o Tk
            # desenhar, e a janela só apareceria com a grade inteira pronta —
            # exatamente o que se quer evitar.
            self._enchendo = True
            self.after(1, lambda: self._encher(fim))
            return
        self._enchendo = False
        for cel in self._celulas[len(itens):]:
            cel.grid_remove()

    def _pintar(self, cel, gift):
        """Escreve um presente numa célula que já existe."""
        ident = str(gift.get("id") or gift.get("name") or "")
        nome = gift.get("name", "")
        selecionado = nome.strip().lower() == (self._escolhido or "").strip().lower()
        cor = self._cor_sel if selecionado else self._cor_fundo
        self._por_celula[cel] = ident
        cel.gift = gift
        cel.configure(text=f"{nome}\n{gift.get('diamonds', 0)} 💎", bg=cor,
                      highlightbackground="#c792ea" if selecionado else cor,
                      image=_fotos.get(ident, ""))
        if ident not in _fotos:
            self._pedir_figura(gift, cel)

    # ------------------------------------------------------------- figuras
    def _pedir_figura(self, gift, cel):
        if not hasattr(self, "_pendentes"):
            self._pendentes, self._trava = [], threading.Lock()
            self._ligar_baixadores()
        with self._trava:
            self._pendentes.append((gift, cel))

    def _ligar_baixadores(self):
        def trabalhador():
            while not self._parar.is_set():
                with self._trava:
                    item = self._pendentes.pop() if self._pendentes else None
                if item is None:
                    if self._parar.wait(0.15):
                        return
                    continue
                gift, cel = item
                caminho = gifts_catalog.icone(gift)
                if not caminho or self._parar.is_set():
                    continue
                try:
                    # O PIL roda fora da thread da interface; só o PhotoImage
                    # (que é objeto do Tk) precisa nascer lá.
                    imagem = Image.open(caminho).convert("RGBA")
                    imagem.thumbnail((TAM_ICONE, TAM_ICONE))
                    self._entrega.put((str(gift.get("id") or gift.get("name")), imagem, cel))
                except Exception:  # noqa: BLE001
                    continue

        for _ in range(THREADS):
            threading.Thread(target=trabalhador, daemon=True, name="gift-icons").start()

    def _drenar_figuras(self):
        """Converte em lotes: uma volta do Tk por figura seria um engasgo só."""
        try:
            for _ in range(24):
                ident, imagem, cel = self._entrega.get_nowait()
                if ident not in _fotos:
                    _fotos[ident] = ImageTk.PhotoImage(imagem)
                # A célula pode ter sido reaproveitada por outro presente
                # enquanto a figura baixava.
                if self._por_celula.get(cel) == ident:
                    try:
                        cel.configure(image=_fotos[ident])
                    except tk.TclError:
                        pass
        except queue.Empty:
            pass
        if not self._parar.is_set():
            self.after(60, self._drenar_figuras)

    # -------------------------------------------------------------- saída
    def _clicou(self, cel):
        gift = getattr(cel, "gift", None)
        if gift:
            self._escolher(gift)

    def _escolher(self, gift):
        self._escolhido = gift.get("name", "")
        try:
            self.on_pick(gift)
        except Exception as exc:  # noqa: BLE001
            logger.log("error", f"[GIFTS] {exc}")
        self._fechar()

    def _fechar(self):
        self._parar.set()
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
