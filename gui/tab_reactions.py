# -*- coding: utf-8 -*-
"""Aba Reações: cada reação é um gatilho + uma sequência de ações.

A janela de edição tem duas seções, como o Streamer.bot:

  1. Gatilho — o que liga a reação (presente, valor em diamantes, comando no
     chat, curtida, seguidor...) e quem tem permissão de ativar.
  2. Ações — a lista ordenada do que acontece, montada passo a passo
     (delay, tocar som, filtro do OBS, falar no TTS, imprimir...).

Os formulários dos dois lados são gerados a partir dos catálogos em
`core/triggers.py` e `core/actions.py`, então acrescentar um gatilho ou uma
ação nova não exige mexer nesta tela.
"""
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog

import customtkinter as ctk

from core import logger, triggers
from core.actions import STEP_TYPES, resumo_passo
from core.config import save_config
from gui.gift_picker import GiftPicker

MUTED = ("#7a7a7a", "#9a9a9a")
ROXO = ("#c792ea", "#c792ea")


class ReactionsTab(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        # Respostas de threads de fundo (OBS, saídas de áudio): elas empilham
        # aqui e a GUI consome na thread dela, que é a única que pode desenhar.
        self._fila_respostas = queue.Queue()
        self._build()
        self.after(80, self._drenar_respostas)

    def _drenar_respostas(self):
        try:
            while True:
                aplicar, lista, erro = self._fila_respostas.get_nowait()
                try:
                    aplicar(lista, erro)
                except tk.TclError:
                    pass          # o menu já não existe mais
        except queue.Empty:
            pass
        self.after(80, self._drenar_respostas)

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="we", padx=16, pady=(14, 8))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(header, text="Reações e Ações",
                     font=ctk.CTkFont("Segoe UI", 22, "bold")).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(header,
                     text="Cada reação tem um gatilho (o que ativa) e uma sequência de "
                          "ações (o que acontece).",
                     font=ctk.CTkFont("Segoe UI", 12), text_color=MUTED
                     ).grid(row=1, column=0, sticky="w", pady=(2, 6))

        ctk.CTkButton(header, text="Adicionar reação", width=160,
                      command=self.add_reaction).grid(row=0, column=1, rowspan=2, sticky="e")

        self.list_frame = ctk.CTkScrollableFrame(self)
        self.list_frame.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))
        self.list_frame.grid_columnconfigure(0, weight=1)

        self._render_cards()

    # ------------------------------------------------------------- cartões
    def _render_cards(self):
        for widget in self.list_frame.winfo_children():
            widget.destroy()

        definitions = self.app.config.get("reactions", [])
        if not definitions:
            ctk.CTkLabel(self.list_frame,
                         text="Nenhuma reação configurada. Clique em “Adicionar reação”.",
                         text_color=MUTED).pack(pady=20)
            return

        for cfg in definitions:
            self._make_card(cfg).pack(fill="x", padx=4, pady=5)

    def _make_card(self, cfg):
        """Cartão de duas linhas, com moldura e faixa lateral.

        Antes eram três linhas soltas na mesma cor do fundo: a lista virava um
        bloco só, sem dizer onde uma reação acaba e a outra começa.
        """
        ativo = bool(cfg.get("enabled", True))
        card = ctk.CTkFrame(self.list_frame, corner_radius=8, border_width=1,
                            border_color=("#d4d4d4", "#3a3a3a"),
                            fg_color=("#fafafa", "#232323"))
        card.grid_columnconfigure(2, weight=1)

        # A faixa colorida dá o contorno de cada item de relance e ainda mostra
        # se a reação está ligada.
        # height=1: o CTkFrame nasce com 200px de altura e, esticado pelo
        # sticky="ns", era ele que inchava o cartão inteiro.
        faixa = ctk.CTkFrame(card, width=4, height=1, corner_radius=2,
                             fg_color=ROXO if ativo else ("#c8c8c8", "#3d3d3d"))
        faixa.grid(row=0, column=0, rowspan=2, sticky="ns", padx=(6, 0), pady=7)

        enabled_var = ctk.BooleanVar(value=ativo)
        ctk.CTkSwitch(card, text="", variable=enabled_var, width=42,
                      command=lambda c=cfg, v=enabled_var, f=faixa:
                      self._on_toggle(c, v.get(), f)
                      ).grid(row=0, column=1, rowspan=2, padx=(10, 8), pady=8)

        ctk.CTkLabel(card, text=cfg.get("name", cfg.get("id", "?")),
                     font=ctk.CTkFont("Segoe UI", 13, "bold"), anchor="w"
                     ).grid(row=0, column=2, sticky="w", padx=(2, 8), pady=(7, 0))

        resumo = ctk.CTkFrame(card, fg_color="transparent")
        resumo.grid(row=1, column=2, sticky="we", padx=(2, 8), pady=(0, 7))
        ctk.CTkLabel(resumo, text=triggers.resumo(cfg.get("trigger")),
                     font=ctk.CTkFont("Segoe UI", 11), text_color=ROXO, anchor="w"
                     ).pack(side="left")
        ctk.CTkLabel(resumo, text="   →   " + self._resumo_acoes(cfg),
                     font=ctk.CTkFont("Segoe UI", 11), text_color=MUTED, anchor="w"
                     ).pack(side="left")

        botoes = ctk.CTkFrame(card, fg_color="transparent")
        botoes.grid(row=0, column=3, rowspan=2, padx=(8, 10), pady=6, sticky="e")
        ctk.CTkButton(botoes, text="▶", width=34, height=28,
                      fg_color="#2f7d4f", hover_color="#256540",
                      command=lambda c=cfg: self.testar_reacao(c)).pack(side="left", padx=3)
        ctk.CTkButton(botoes, text="Editar", width=70, height=28,
                      command=lambda c=cfg: self.edit_reaction(c)).pack(side="left", padx=3)
        ctk.CTkButton(botoes, text="Remover", width=76, height=28,
                      fg_color="#c0392b", hover_color="#922b21",
                      command=lambda c=cfg: self.remove_reaction(c)).pack(side="left", padx=3)
        return card

    def _resumo_acoes(self, cfg):
        acoes = cfg.get("actions") or []
        if not acoes:
            return "sem ações — clique em Editar"
        nomes = [STEP_TYPES.get(p.get("type"), {}).get("label", p.get("type", "?"))
                 for p in acoes[:3]]
        texto = " → ".join(nomes)
        if len(acoes) > 3:
            texto += f" → +{len(acoes) - 3}"
        return texto

    def testar_reacao(self, cfg):
        """Roda a sequência agora, sem esperar o gatilho de verdade."""
        acoes = cfg.get("actions") or []
        if not acoes:
            logger.log("warning", f"[TESTE] “{cfg.get('name')}” não tem nenhuma ação.")
            return
        # O presente do gatilho entra nos campos de substituição, para o teste
        # sair com o mesmo texto que sairia na live.
        gatilho = cfg.get("trigger") or {}
        self.app.engine.testar_acoes(
            acoes, {"gift": gatilho.get("gift") or "Presente de teste"})

    def _on_toggle(self, cfg, value, faixa=None):
        cfg["enabled"] = value
        if faixa is not None:
            faixa.configure(fg_color=ROXO if value else ("#c8c8c8", "#3d3d3d"))
        self._save_and_apply()
        self.app.engine.reactions.set_enabled(cfg.get("id"), value)

    def _save_and_apply(self):
        save_config(self.app.config)
        self.app.engine.reload_reactions()

    def add_reaction(self):
        self._dialog(reaction=None)

    def edit_reaction(self, cfg):
        self._dialog(reaction=cfg)

    def remove_reaction(self, cfg):
        definitions = self.app.config.get("reactions", [])
        self.app.config["reactions"] = [r for r in definitions if r.get("id") != cfg.get("id")]
        self._save_and_apply()
        self._render_cards()
        logger.log("system", f"Reação removida: {cfg.get('name')}")

    # ---------------------------------------------------------- campos OBS
    OBS_KINDS = ("obs_cena", "obs_fonte", "obs_fonte_da_cena", "obs_filtro", "obs_entrada")

    def _campo_obs(self, linha, field, valor, registro):
        """Menu preenchido com o que existe no OBS aberto.

        É um ComboBox e não um menu fechado de propósito: com o OBS desligado
        (ou para uma cena que ainda vai ser criada) continua dando para digitar
        o nome à mão, como era antes.
        """
        var = ctk.StringVar(value=str(valor or ""))
        caixa = ctk.CTkFrame(linha, fg_color="transparent")
        caixa.grid(row=0, column=1, sticky="we")
        caixa.grid_columnconfigure(0, weight=1)
        combo = ctk.CTkComboBox(caixa, variable=var, values=[])
        combo.grid(row=0, column=0, sticky="we", padx=(0, 6))
        aviso = ctk.CTkLabel(caixa, text="", width=150, anchor="w", text_color=MUTED,
                             font=ctk.CTkFont("Segoe UI", 10))
        aviso.grid(row=0, column=2, padx=(6, 0))

        def aplicar(lista, erro):
            try:
                if erro is not None:
                    aviso.configure(text="OBS não conectado — digite o nome")
                    return
                combo.configure(values=lista)
                aviso.configure(text="" if lista else "nada encontrado")
            except tk.TclError:
                pass          # a janela foi fechada durante a consulta

        def recarregar(*_):
            consulta = self._consulta_obs(field["kind"], registro)
            if consulta is None:
                aplicar([], None)
                return
            aviso.configure(text="lendo do OBS...")
            # A resposta chega na thread do loop do monitor; o Tk só pode ser
            # tocado na dele, então ela entra numa fila que a GUI drena.
            self.app.engine.obs_consultar(
                consulta,
                lambda lista, erro: self._fila_respostas.put((aplicar, lista, erro)))

        ctk.CTkButton(caixa, text="↻", width=32, command=recarregar).grid(row=0, column=1)
        registro[field["key"]] = {"kind": field["kind"], "var": var,
                                  "recarregar": recarregar}
        return var.get

    def _consulta_obs(self, kind, registro):
        """Qual pergunta fazer ao OBS para preencher este menu."""
        if kind == "obs_cena":
            return lambda obs: obs.listar_cenas()
        if kind == "obs_fonte":
            return lambda obs: obs.listar_fontes()
        if kind == "obs_entrada":
            return lambda obs: obs.listar_entradas()
        if kind == "obs_fonte_da_cena":
            cena = registro.get("scene", {}).get("var")
            nome = cena.get().strip() if cena else ""
            if not nome:
                return None      # sem cena escolhida não há o que listar
            return lambda obs: obs.listar_fontes_da_cena(nome)
        if kind == "obs_filtro":
            fonte = registro.get("source", {}).get("var")
            nome = fonte.get().strip() if fonte else ""
            if not nome:
                return None
            return lambda obs: obs.listar_filtros(nome)
        return None

    def _ligar_dependencias(self, registro):
        """Escolher a cena recarrega as fontes; escolher a fonte, os filtros."""
        pares = (("scene", "source"), ("source", "filter"))
        for pai, filho in pares:
            if pai not in registro or filho not in registro:
                continue
            if registro[filho]["kind"] not in ("obs_fonte_da_cena", "obs_filtro"):
                continue
            registro[pai]["var"].trace_add(
                "write", lambda *_a, f=filho: registro[f]["recarregar"]())
        for campo in registro.values():
            campo["recarregar"]()

    # ------------------------------------------------------ campos genéricos
    def _campo(self, parent, field, valor, registro=None):
        """Monta o widget de um campo e devolve uma função que lê o valor.

        Os tipos saem dos catálogos: text, number, bool, escolha, arquivo e
        gift (que abre o seletor visual de presentes).
        """
        linha = ctk.CTkFrame(parent, fg_color="transparent")
        linha.pack(fill="x", padx=2, pady=4)
        linha.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(linha, text=field.get("label", field["key"]), width=250, anchor="w"
                     ).grid(row=0, column=0, padx=(4, 8), sticky="w")

        kind = field.get("kind", "text")

        if kind in self.OBS_KINDS and registro is not None:
            return self._campo_obs(linha, field, valor, registro)

        if kind == "bool":
            var = ctk.BooleanVar(value=bool(valor))
            ctk.CTkSwitch(linha, text="", variable=var).grid(row=0, column=1, sticky="w")
            return var.get

        if kind == "texto_longo":
            # Caixa de várias linhas: no cartão, uma linha vazia é espaço em
            # branco de verdade, então dá para ver o cupom tomando forma
            # enquanto se digita.
            caixa = ctk.CTkTextbox(linha, height=22 * int(field.get("linhas", 3)),
                                   wrap="word", font=ctk.CTkFont("Segoe UI", 13))
            caixa.grid(row=0, column=1, sticky="we")
            caixa.insert("1.0", str(valor or ""))
            return lambda: caixa.get("1.0", "end-1c")

        if kind == "impressora":
            # A primeira opção é a padrão do Windows, guardada como texto
            # vazio: assim quem não tem impressora dedicada não mexe em nada, e
            # o cartão acompanha a padrão se ela mudar depois.
            from core.printer import listar_impressoras
            PADRAO_WIN = "Impressora padrão do Windows"
            instaladas = listar_impressoras()
            opcoes = [PADRAO_WIN] + instaladas
            atual = str(valor or "")
            if atual and atual not in instaladas:
                # A impressora salva foi desligada ou removida: continua na
                # lista, marcada, em vez de sumir sem avisar.
                opcoes.append(f"{atual}  (não encontrada)")
                mostrar = opcoes[-1]
            else:
                mostrar = atual or PADRAO_WIN
            var = ctk.StringVar(value=mostrar)
            ctk.CTkOptionMenu(linha, values=opcoes, variable=var, width=300,
                              command=field.get("ao_mudar")
                              ).grid(row=0, column=1, sticky="w")

            def ler():
                escolhido = var.get()
                if escolhido == PADRAO_WIN:
                    return ""
                return escolhido.replace("  (não encontrada)", "")
            return ler

        if kind == "escolha":
            rotulos = field.get("rotulos") or {}
            opcoes = list(field.get("opcoes") or [])
            mostrar = [rotulos.get(o, o) for o in opcoes]
            atual = rotulos.get(valor, valor) if valor in opcoes else (mostrar[0] if mostrar else "")
            var = ctk.StringVar(value=atual)
            ctk.CTkOptionMenu(linha, values=mostrar, variable=var,
                              command=field.get("ao_mudar")).grid(row=0, column=1, sticky="w")

            def ler():
                escolhido = var.get()
                for bruto, rotulo in zip(opcoes, mostrar):
                    if rotulo == escolhido:
                        return bruto
                return escolhido
            return ler

        if kind == "gift":
            var = ctk.StringVar(value=str(valor or "") or "(nenhum presente escolhido)")
            escolha = {"gift": str(valor or ""), "gift_id": field.get("gift_id", "")}
            caixa = ctk.CTkFrame(linha, fg_color="transparent")
            caixa.grid(row=0, column=1, sticky="we")
            caixa.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(caixa, textvariable=var, anchor="w",
                         fg_color=("#f2f2f2", "#262626"), corner_radius=6, height=30
                         ).grid(row=0, column=0, sticky="we", padx=(0, 6))

            def escolhido(gift):
                escolha["gift"] = gift.get("name", "")
                escolha["gift_id"] = str(gift.get("id") or "")
                var.set(f"{escolha['gift']}  ·  {gift.get('diamonds', 0)} diamantes")

            def escolher():
                GiftPicker(self, atual=escolha["gift"], on_pick=escolhido,
                           username=self.app.config["live"].get("username", ""))

            ctk.CTkButton(caixa, text="Escolher presente...", width=160,
                          command=escolher).grid(row=0, column=1)
            # Devolve os dois campos de uma vez: quem colhe mescla no gatilho.
            return lambda: dict(escolha)

        if kind == "volume":
            minimo = int(field.get("minimo", 0))
            maximo = int(field.get("maximo", 120))
            try:
                inicial = int(float(valor))
            except (TypeError, ValueError):
                inicial = int(field.get("default", 100))
            inicial = max(minimo, min(maximo, inicial))
            caixa = ctk.CTkFrame(linha, fg_color="transparent")
            caixa.grid(row=0, column=1, sticky="we")
            caixa.grid_columnconfigure(0, weight=1)
            var = ctk.IntVar(value=inicial)
            numero = ctk.CTkLabel(caixa, text=f"{inicial}%", width=52,
                                  font=ctk.CTkFont("Consolas", 12))
            ctk.CTkSlider(caixa, from_=minimo, to=maximo, number_of_steps=maximo - minimo,
                          variable=var,
                          command=lambda v: numero.configure(text=f"{int(float(v))}%")
                          ).grid(row=0, column=0, sticky="we", padx=(0, 8))
            numero.grid(row=0, column=1)
            return var.get

        if kind == "audio_device":
            # A lista vem do VLC e custa uns 200 ms na primeira vez; o menu
            # nasce com o que já está escolhido e se completa em seguida.
            atual_id = str(valor or "")
            atual_nome = field.get("device_nome") or ("Padrão do Windows" if not atual_id
                                                      else "(carregando...)")
            escolha = {"device": atual_id, "device_nome": atual_nome}
            var = ctk.StringVar(value=atual_nome)
            menu = ctk.CTkOptionMenu(linha, values=[atual_nome], variable=var)
            menu.grid(row=0, column=1, sticky="we", padx=(4, 4))

            def preencher(dispositivos):
                nomes = [d["nome"] for d in dispositivos]
                por_nome = {d["nome"]: d["id"] for d in dispositivos}

                def selecionou(nome):
                    escolha["device"] = por_nome.get(nome, "")
                    escolha["device_nome"] = nome

                try:
                    menu.configure(values=nomes, command=selecionou)
                    for d in dispositivos:
                        if d["id"] == escolha["device"]:
                            var.set(d["nome"])
                            escolha["device_nome"] = d["nome"]
                            break
                    else:
                        # A saída salva sumiu (fone desconectado, por exemplo).
                        if escolha["device"]:
                            var.set("(saída não encontrada — usando o padrão)")
                except tk.TclError:
                    pass

            def carregar():
                from core.sound import listar_dispositivos
                dispositivos = listar_dispositivos()
                self._fila_respostas.put((lambda lista, _e: preencher(lista), dispositivos, None))

            threading.Thread(target=carregar, daemon=True, name="audio-devices").start()
            return lambda: dict(escolha)

        if kind == "arquivo":
            var = ctk.StringVar(value=str(valor or ""))
            caixa = ctk.CTkFrame(linha, fg_color="transparent")
            caixa.grid(row=0, column=1, sticky="we")
            caixa.grid_columnconfigure(0, weight=1)
            ctk.CTkEntry(caixa, textvariable=var).grid(row=0, column=0, sticky="we", padx=(0, 6))

            def procurar():
                caminho = filedialog.askopenfilename(
                    parent=self.winfo_toplevel(),
                    filetypes=[("Sons", "*.mp3 *.wav *.ogg *.m4a *.flac"), ("Todos", "*.*")])
                if caminho:
                    var.set(caminho)

            ctk.CTkButton(caixa, text="Procurar...", width=110,
                          command=procurar).grid(row=0, column=1)
            return var.get

        var = ctk.StringVar(value="" if valor is None else str(valor))
        ctk.CTkEntry(linha, textvariable=var).grid(row=0, column=1, sticky="we", padx=(4, 4))
        if kind == "number":
            def ler_numero():
                bruto = var.get().strip().replace(",", ".")
                try:
                    return float(bruto) if "." in bruto else int(bruto)
                except ValueError:
                    return field.get("default", 0)
            return ler_numero
        return lambda: var.get().strip()

    # ------------------------------------------------- janela da reação
    def _dialog(self, reaction):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Editar reação" if reaction else "Nova reação")
        dialog.geometry("760x760")
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()
        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(0, weight=1)

        corpo = ctk.CTkScrollableFrame(dialog)
        corpo.grid(row=0, column=0, sticky="nsew", padx=14, pady=(14, 6))
        corpo.grid_columnconfigure(0, weight=1)

        trigger_atual = dict((reaction or {}).get("trigger") or {})
        acoes = [dict(p) for p in ((reaction or {}).get("actions") or [])]

        # ---- nome
        ctk.CTkLabel(corpo, text="Nome da reação", anchor="w",
                     font=ctk.CTkFont("Segoe UI", 13, "bold")).pack(fill="x", pady=(0, 4))
        nome_var = ctk.StringVar(value=(reaction or {}).get("name", ""))
        ctk.CTkEntry(corpo, textvariable=nome_var,
                     placeholder_text="Ex.: Rosa toca miado").pack(fill="x", pady=(0, 12))

        # ---- seção 1: gatilho
        caixa_gatilho = self._secao(corpo, "1.  Gatilho", "O que ativa esta reação.")

        ordem = list(triggers.TIPOS.keys())
        rotulos = [triggers.TIPOS[t]["label"] for t in ordem]
        tipo_atual = trigger_atual.get("tipo") or ordem[0]
        tipo_var = ctk.StringVar(value=triggers.TIPOS.get(tipo_atual, {}).get("label", rotulos[0]))

        topo_gatilho = ctk.CTkFrame(caixa_gatilho, fg_color="transparent")
        topo_gatilho.pack(fill="x", padx=2, pady=(2, 2))
        topo_gatilho.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(topo_gatilho, text="Tipo de gatilho", width=250, anchor="w"
                     ).grid(row=0, column=0, padx=(4, 8), sticky="w")
        ctk.CTkOptionMenu(topo_gatilho, values=rotulos, variable=tipo_var,
                          command=lambda _v: montar_gatilho()).grid(row=0, column=1, sticky="w")

        desc = ctk.CTkLabel(caixa_gatilho, text="", font=ctk.CTkFont("Segoe UI", 11),
                            text_color=MUTED, anchor="w", justify="left", wraplength=680)
        desc.pack(fill="x", padx=6, pady=(2, 4))

        campos_gatilho = ctk.CTkFrame(caixa_gatilho, fg_color="transparent")
        campos_gatilho.pack(fill="x", padx=2, pady=(0, 2))
        leitores = {}

        def tipo_escolhido():
            for bruto, rotulo in zip(ordem, rotulos):
                if rotulo == tipo_var.get():
                    return bruto
            return ordem[0]

        def montar_gatilho(*_):
            # Guarda o que já foi digitado: trocar de tipo (ou de "quem pode
            # ativar") não pode apagar o resto do formulário.
            trigger_atual.update(colher_gatilho())
            for w in campos_gatilho.winfo_children():
                w.destroy()
            leitores.clear()

            tipo = tipo_escolhido()
            info = triggers.TIPOS[tipo]
            desc.configure(text=info["descricao"])

            campos = list(info["fields"])
            if info["evento"] == "gift":
                campos += triggers.CAMPOS_PRESENTE
            for campo in triggers.CAMPOS_COMUNS:
                # top_n e nível só aparecem quando a permissão escolhida usa.
                quem = trigger_atual.get("quem", "todos")
                if campo["key"] == "top_n" and quem != "top_n":
                    continue
                if campo["key"] == "nivel_min" and quem != "clube_fas":
                    continue
                campo = dict(campo)
                if campo["key"] == "quem":
                    # after_idle porque remontar aqui destrói o próprio menu
                    # que está chamando de volta.
                    campo["ao_mudar"] = lambda _v: self.after_idle(montar_gatilho)
                campos.append(campo)

            for campo in campos:
                valor = trigger_atual.get(campo["key"], campo.get("default"))
                if campo.get("kind") == "gift":
                    campo = dict(campo, gift_id=trigger_atual.get("gift_id", ""))
                leitores[campo["key"]] = self._campo(campos_gatilho, campo, valor)

        def colher_gatilho():
            colhido = {"tipo": tipo_escolhido()}
            for chave, ler in leitores.items():
                valor = ler()
                # O campo de presente devolve nome e id juntos.
                if isinstance(valor, dict):
                    colhido.update(valor)
                else:
                    colhido[chave] = valor
            return colhido

        montar_gatilho()

        # ---- seção 2: ações
        caixa_acoes = self._secao(
            corpo, "2.  Ações",
            "O que acontece, de cima para baixo. Duplo clique edita; arraste para "
            "mudar a ordem.")
        self._lista_acoes(caixa_acoes, acoes)

        # ---- rodapé
        rodape = ctk.CTkFrame(dialog, fg_color="transparent")
        rodape.grid(row=1, column=0, sticky="we", padx=14, pady=(0, 14))

        def salvar():
            gatilho = colher_gatilho()
            nome = nome_var.get().strip() or triggers.TIPOS[gatilho["tipo"]]["label"]
            definitions = self.app.config.get("reactions", [])
            novo = {
                "id": (reaction or {}).get("id") or f"reacao_{int(time.time() * 1000)}",
                "name": nome,
                "enabled": bool((reaction or {}).get("enabled", True)),
                "trigger": gatilho,
                "actions": [dict(p) for p in acoes],
            }
            if reaction is not None:
                idx = next((i for i, r in enumerate(definitions)
                            if r.get("id") == reaction.get("id")), None)
                if idx is not None:
                    definitions[idx] = novo
                else:
                    definitions.append(novo)
            else:
                definitions.append(novo)
            self.app.config["reactions"] = definitions
            self._save_and_apply()
            self._render_cards()
            logger.log("system", f"Reação salva: {nome}")
            dialog.destroy()

        ctk.CTkButton(rodape, text="Salvar", width=120, command=salvar,
                      fg_color="#4caf50", hover_color="#3d8b40").pack(side="right", padx=4)
        ctk.CTkButton(rodape, text="Cancelar", width=120, fg_color="#555555",
                      hover_color="#3d3d3d", command=dialog.destroy).pack(side="right", padx=4)
        # Testar sem fechar: montar a sequência e conferir o efeito é ida e
        # volta, e salvar a cada tentativa só atrapalharia.
        ctk.CTkButton(rodape, text="▶  Testar ações", width=140,
                      fg_color="#2f7d4f", hover_color="#256540",
                      command=lambda: self.app.engine.testar_acoes(
                          acoes, {"gift": colher_gatilho().get("gift")
                                  or "Presente de teste"})).pack(side="left", padx=4)

    def _secao(self, parent, titulo, subtitulo, aberto=True):
        """Bloco que abre e fecha. Devolve o corpo, onde o conteúdo entra.

        Fechar o gatilho enquanto se mexe nas ações (e vice-versa) é o que
        mantém a janela navegável sem rolar o tempo todo.
        """
        caixa = ctk.CTkFrame(parent)
        caixa.pack(fill="x", pady=(0, 10))
        corpo = ctk.CTkFrame(caixa, fg_color="transparent")
        estado = {"aberto": bool(aberto)}

        cabeca = ctk.CTkButton(
            caixa, anchor="w", height=38, corner_radius=8, fg_color="transparent",
            hover_color=("#d8d8d8", "#2a2a2a"), text_color=ROXO,
            font=ctk.CTkFont("Segoe UI", 15, "bold"))
        cabeca.pack(fill="x", padx=6, pady=(6, 0))
        legenda = ctk.CTkLabel(caixa, text=subtitulo, anchor="w", text_color=MUTED,
                               justify="left", wraplength=680,
                               font=ctk.CTkFont("Segoe UI", 11))

        def desenhar():
            cabeca.configure(text=("▼  " if estado["aberto"] else "▶  ") + titulo)
            if estado["aberto"]:
                legenda.pack(fill="x", padx=16, pady=(0, 4))
                corpo.pack(fill="both", expand=True, padx=12, pady=(0, 10))
            else:
                legenda.pack_forget()
                corpo.pack_forget()

        def alternar():
            estado["aberto"] = not estado["aberto"]
            desenhar()

        cabeca.configure(command=alternar)
        desenhar()
        return corpo

    def _lista_acoes(self, parent, acoes):
        """A sequência como lista de verdade: seleção, duplo clique e arraste.

        Devolve a função que redesenha a lista, para quem mexe em `acoes` de
        fora (a janela de um passo) pedir a atualização.
        """
        escuro = ctk.get_appearance_mode().lower() == "dark"
        lista = tk.Listbox(
            parent, height=8, activestyle="none", relief="flat", bd=0,
            highlightthickness=1, font=("Segoe UI", 10),
            bg="#1e1e1e" if escuro else "#ffffff",
            fg="#dce4ee" if escuro else "#1f1f1f",
            highlightbackground="#3a3a3a" if escuro else "#cccccc",
            selectbackground="#3a2b4d" if escuro else "#d9c7ee",
            selectforeground="#ffffff" if escuro else "#1f1f1f")
        lista.pack(fill="both", expand=True, pady=(2, 6))

        arrasto = {"de": None}

        def redesenhar(selecionar=None):
            lista.delete(0, "end")
            for i, passo in enumerate(acoes):
                lista.insert("end", f"  {i + 1}.   {resumo_passo(passo)}")
            if not acoes:
                lista.insert("end", "  (nenhuma ação ainda — clique em “Adicionar ação”)")
            elif selecionar is not None and 0 <= selecionar < len(acoes):
                lista.selection_set(selecionar)
                lista.see(selecionar)

        def selecionado():
            escolha = lista.curselection()
            if not escolha or not acoes:
                return None
            return escolha[0] if escolha[0] < len(acoes) else None

        def editar(_evt=None):
            i = selecionado()
            if i is not None:
                self._step_dialog(acoes, i, lambda: redesenhar(i))

        def remover():
            i = selecionado()
            if i is not None:
                acoes.pop(i)
                redesenhar(min(i, len(acoes) - 1))

        def duplicar():
            i = selecionado()
            if i is not None:
                acoes.insert(i + 1, dict(acoes[i]))
                redesenhar(i + 1)

        def mover(delta):
            i = selecionado()
            if i is None:
                return
            novo = i + delta
            if 0 <= novo < len(acoes):
                acoes[i], acoes[novo] = acoes[novo], acoes[i]
                redesenhar(novo)

        def arrastar_inicio(evento):
            arrasto["de"] = lista.nearest(evento.y) if acoes else None

        def arrastar(evento):
            origem = arrasto["de"]
            if origem is None or not acoes:
                return
            destino = lista.nearest(evento.y)
            if destino < 0 or destino >= len(acoes) or destino == origem:
                return
            acoes[origem], acoes[destino] = acoes[destino], acoes[origem]
            arrasto["de"] = destino
            redesenhar(destino)

        lista.bind("<Double-Button-1>", editar)
        lista.bind("<Button-1>", arrastar_inicio, add="+")
        lista.bind("<B1-Motion>", arrastar)
        lista.bind("<ButtonRelease-1>", lambda _e: arrasto.update(de=None))
        lista.bind("<Delete>", lambda _e: remover())
        lista.bind("<Return>", editar)

        botoes = ctk.CTkFrame(parent, fg_color="transparent")
        botoes.pack(fill="x")
        ctk.CTkButton(botoes, text="+  Adicionar ação", width=150,
                      command=lambda: self._step_dialog(
                          acoes, None, lambda: redesenhar(len(acoes) - 1))
                      ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(botoes, text="Editar", width=80, command=editar).pack(side="left", padx=3)
        ctk.CTkButton(botoes, text="Duplicar", width=90, command=duplicar).pack(side="left", padx=3)
        ctk.CTkButton(botoes, text="↑", width=36, command=lambda: mover(-1)).pack(side="left", padx=3)
        ctk.CTkButton(botoes, text="↓", width=36, command=lambda: mover(1)).pack(side="left", padx=3)
        ctk.CTkButton(botoes, text="Remover", width=90, fg_color="#c0392b",
                      hover_color="#922b21", command=remover).pack(side="left", padx=3)

        redesenhar()
        return redesenhar

    # ------------------------------------------------------- teste de som
    def _player(self):
        """Player só para os testes, separado do que roda durante a live."""
        if getattr(self, "_player_teste", None) is None:
            from core.sound import SoundPlayer
            self._player_teste = SoundPlayer(100)
        return self._player_teste

    def _linha_teste(self, parent, leitores):
        """Ouvir o som ali mesmo, no volume que está configurado."""
        linha = ctk.CTkFrame(parent, fg_color="transparent")
        linha.pack(fill="x", padx=2, pady=(10, 2))
        ctk.CTkLabel(linha, text="", width=250).pack(side="left", padx=(4, 8))

        estado = ctk.CTkLabel(linha, text="", text_color=MUTED,
                              font=ctk.CTkFont("Segoe UI", 11))

        def testar():
            arquivo = (leitores.get("file", lambda: "")() or "").strip()
            if not arquivo:
                estado.configure(text="Escolha um arquivo primeiro.")
                return
            volume = leitores.get("volume", lambda: 100)()
            escolhido = leitores.get("device", lambda: {})()
            device = escolhido.get("device") if isinstance(escolhido, dict) else None
            saida = escolhido.get("device_nome") if isinstance(escolhido, dict) else ""
            estado.configure(text=f"Tocando a {int(volume)}%"
                                  + (f" em {saida}..." if device else "..."))
            # Em thread: abrir o arquivo segura a interface por um instante, e
            # o botão precisa continuar respondendo ao Parar.
            threading.Thread(
                target=lambda: self._player().play(arquivo, int(volume), False,
                                                   device or None),
                daemon=True).start()

        def parar():
            self._player().stop_all()
            estado.configure(text="Parado.")

        ctk.CTkButton(linha, text="▶  Testar som", width=120, command=testar,
                      fg_color="#4caf50", hover_color="#3d8b40").pack(side="left")
        ctk.CTkButton(linha, text="■  Parar", width=90, command=parar,
                      fg_color="#c0392b", hover_color="#922b21").pack(side="left", padx=6)
        estado.pack(side="left", padx=6)

    # ------------------------------------------------- editor da impressão
    def _editor_impressao(self, parent, leitores):
        """Prévia do cartão montada ao vivo, curingas à mão e os dois testes.

        Ver o cupom antes de gastar papel é o ponto: o texto é livre, e sem a
        prévia só dá para conferir imprimindo.
        """
        from core import printer

        bloco = ctk.CTkFrame(parent)
        bloco.pack(fill="x", pady=(12, 4))
        bloco.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(bloco, text="Prévia da impressão",
                     font=ctk.CTkFont("Segoe UI", 14, "bold"), anchor="w"
                     ).grid(row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(12, 2))

        ajuda = "  ·  ".join(f"{curinga} = {oque}" for curinga, oque in printer.CURINGAS)
        ctk.CTkLabel(bloco, text=ajuda, text_color=MUTED, anchor="w", justify="left",
                     wraplength=560, font=ctk.CTkFont("Segoe UI", 10)
                     ).grid(row=1, column=0, columnspan=2, sticky="w", padx=14, pady=(0, 8))

        alvo = ctk.CTkLabel(bloco, text="", width=230, height=300)
        alvo.grid(row=2, column=0, columnspan=2, padx=14, pady=(0, 6))

        estado = ctk.CTkLabel(bloco, text="", text_color=MUTED, anchor="w",
                              font=ctk.CTkFont("Segoe UI", 11))
        estado.grid(row=3, column=0, columnspan=2, sticky="w", padx=14, pady=(0, 4))

        # Os valores de exemplo são só da prévia: na live entram os do evento.
        # Se já houve uma impressão nesta sessão, a prévia usa o nome, o
        # presente e a foto de verdade daquela — muito mais fiel do que um
        # exemplo inventado.
        exemplo = {"nickname": "Ana ⭐ Souza", "username": "ana_souza",
                   "gift_pt": "Rosa", "gift": "rose", "count": 3, "diamonds": 5,
                   "message": "", "likes": 0}
        foto = None
        ultima = printer.dados_da_ultima()
        if ultima:
            reais, foto = ultima
            exemplo.update({k: v for k, v in reais.items() if v not in ("", None)})

        def valores():
            return (str(leitores.get("texto_topo", lambda: "")() or ""),
                    str(leitores.get("texto_rodape", lambda: "")() or ""),
                    bool(leitores.get("espelhar", lambda: True)()),
                    str(leitores.get("printer_name", lambda: "")() or ""))

        def desenhar(topo, rodape, espelhar, impressora):
            from core.actions import substituir
            try:
                cartao = printer.previa(substituir(topo, exemplo),
                                        substituir(rodape, exemplo),
                                        foto, impressora, espelhar)
            except Exception as exc:  # noqa: BLE001 — prévia nunca derruba a janela
                alvo.configure(image=None, text=f"Não consegui montar a prévia: {exc}")
                return
            largura = 230
            altura = max(1, int(cartao.height * largura / cartao.width))
            imagem = ctk.CTkImage(light_image=cartao, dark_image=cartao,
                                  size=(largura, altura))
            # A referência precisa sobreviver: sem ela o Tk recolhe a imagem
            # e o quadro fica em branco.
            alvo._cartao = imagem
            alvo.configure(image=imagem, text="", height=altura)
            estado.configure(text=f"Sai com {cartao.width} px de largura"
                                  + (" · espelhado" if espelhar else " · sem espelhar")
                                  + f" · {impressora or 'impressora padrão do Windows'}")

        ultimo = {"valores": None}

        def acompanhar():
            if not bloco.winfo_exists():
                return
            atual = valores()
            if atual != ultimo["valores"]:
                ultimo["valores"] = atual
                desenhar(*atual)
            # Sondar é mais simples do que amarrar um evento em cada tipo de
            # widget (entrada, interruptor, menu) — e 300 ms não pesa.
            bloco.after(300, acompanhar)

        botoes = ctk.CTkFrame(bloco, fg_color="transparent")
        botoes.grid(row=4, column=0, columnspan=2, sticky="w", padx=14, pady=(4, 12))

        def imprimir_teste():
            topo, rodape, espelhar, impressora = valores()
            from core.actions import substituir
            estado.configure(text="Enviando o cartão de teste...")
            threading.Thread(
                target=printer.imprimir,
                args=(substituir(topo, exemplo), substituir(rodape, exemplo),
                      foto or printer.avatar_exemplo(), impressora, espelhar),
                daemon=True).start()

        def reimprimir():
            if not printer.tem_ultima():
                estado.configure(text="Nada foi impresso ainda nesta sessão.")
                return
            estado.configure(text="Reimprimindo o último cartão...")
            threading.Thread(target=printer.reimprimir_ultima, daemon=True).start()

        ctk.CTkButton(botoes, text="🖨  Imprimir teste", width=150, command=imprimir_teste,
                      fg_color="#4caf50", hover_color="#3d8b40").pack(side="left")
        ctk.CTkButton(botoes, text="↻  Reimprimir última", width=170, command=reimprimir
                      ).pack(side="left", padx=8)

        acompanhar()

    # --------------------------------------------------- janela de um passo
    def _step_dialog(self, acoes, indice, ao_salvar):
        editando = indice is not None and 0 <= indice < len(acoes)
        existente = dict(acoes[indice]) if editando else {}

        win = ctk.CTkToplevel(self)
        win.title("Editar ação" if editando else "Adicionar ação")
        win.geometry("640x520")
        win.transient(self.winfo_toplevel())
        win.grab_set()
        win.grid_columnconfigure(0, weight=1)
        win.grid_rowconfigure(1, weight=1)

        topo = ctk.CTkFrame(win, fg_color="transparent")
        topo.grid(row=0, column=0, sticky="we", padx=16, pady=(16, 4))
        topo.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(topo, text="Tipo de ação", width=140, anchor="w"
                     ).grid(row=0, column=0, sticky="w")

        # Agrupadas por área, para a lista não virar um paredão de opções.
        ordem, rotulos = [], []
        for grupo in ("Geral", "Som e voz", "OBS Studio", "TikTok"):
            for chave, info in STEP_TYPES.items():
                if info.get("grupo") == grupo:
                    ordem.append(chave)
                    rotulos.append(f"{grupo}  ·  {info['label']}")

        atual = existente.get("type") or ordem[0]
        tipo_var = ctk.StringVar(value=rotulos[ordem.index(atual)] if atual in ordem else rotulos[0])
        ctk.CTkOptionMenu(topo, values=rotulos, variable=tipo_var,
                          command=lambda _v: montar()).grid(row=0, column=1, sticky="we")

        campos = ctk.CTkScrollableFrame(win)
        campos.grid(row=1, column=0, sticky="nsew", padx=16, pady=8)
        leitores = {}

        def tipo_escolhido():
            for bruto, rotulo in zip(ordem, rotulos):
                if rotulo == tipo_var.get():
                    return bruto
            return ordem[0]

        def montar(*_):
            for w in campos.winfo_children():
                w.destroy()
            leitores.clear()
            tipo = tipo_escolhido()
            info = STEP_TYPES[tipo]
            if not info["fields"]:
                ctk.CTkLabel(campos, text="Esta ação não tem nada para configurar.",
                             text_color=MUTED).pack(pady=16)
                return
            registro = {}
            for campo in info["fields"]:
                valor = existente.get(campo["key"], campo.get("default"))
                if campo.get("kind") == "audio_device":
                    campo = dict(campo, device_nome=existente.get("device_nome", ""))
                leitores[campo["key"]] = self._campo(campos, campo, valor, registro)
            if registro:
                self._ligar_dependencias(registro)
            if info.get("testavel"):
                self._linha_teste(campos, leitores)
            if info.get("editor") == "impressao":
                # O editor da impressão já traz a lista de curingas do cartão.
                self._editor_impressao(campos, leitores)
                win.geometry("700x760")
                return
            ctk.CTkLabel(campos, text="Use {nickname}, {username}, {gift}, {count}, "
                                      "{diamonds}, {message} ou {likes} nos textos.",
                         text_color=MUTED, anchor="w", justify="left", wraplength=560,
                         font=ctk.CTkFont("Segoe UI", 10)).pack(fill="x", pady=(10, 0))

        montar()

        rodape = ctk.CTkFrame(win, fg_color="transparent")
        rodape.grid(row=2, column=0, sticky="we", padx=16, pady=(0, 16))

        def fechar():
            # Um teste de som não pode continuar tocando depois que a janela
            # que o começou some da tela.
            if getattr(self, "_player_teste", None) is not None:
                self._player_teste.stop_all()
            win.destroy()

        def salvar():
            passo = {"type": tipo_escolhido()}
            for chave, ler in leitores.items():
                valor = ler()
                # A saída de áudio devolve id e nome de uma vez (como o presente).
                if isinstance(valor, dict):
                    passo.update(valor)
                else:
                    passo[chave] = valor
            if editando:
                acoes[indice] = passo
            else:
                acoes.append(passo)
            ao_salvar()
            fechar()

        win.protocol("WM_DELETE_WINDOW", fechar)
        ctk.CTkButton(rodape, text="Salvar ação", width=120, command=salvar
                      ).pack(side="right", padx=4)
        ctk.CTkButton(rodape, text="Cancelar", width=120, fg_color="#555555",
                      hover_color="#3d3d3d", command=fechar).pack(side="right", padx=4)

    def refresh_if_needed(self):
        pass
