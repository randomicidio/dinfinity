# -*- coding: utf-8 -*-
"""Aba Conexão: usuário, botão único Conectar/Desconectar, conexão automática,
tempo de verificação e console de log."""
import tkinter as tk

import customtkinter as ctk

from core import logger
from core.config import save_config


class LiveTab(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self._build()
        self.app.add_status_listener(self._on_status)

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        header = ctk.CTkLabel(self, text="Conexão com a Live",
                              font=ctk.CTkFont("Segoe UI", 22, "bold"))
        header.grid(row=0, column=0, sticky="w", padx=16, pady=(14, 4))
        ctk.CTkLabel(self, text="O monitor fica em standby, detecta quando a live abre, conecta sozinho "
                                "e volta ao standby quando ela termina.",
                     font=ctk.CTkFont("Segoe UI", 12), text_color=("#7a7a7a", "#9a9a9a")
                     ).grid(row=1, column=0, sticky="w", padx=16, pady=(0, 10))

        settings = ctk.CTkFrame(self)
        settings.grid(row=2, column=0, sticky="we", padx=16, pady=(0, 10))
        settings.grid_columnconfigure(0, weight=1)

        # Linha 1: o usuário e o botão que o aplica, lado a lado.
        linha_user = ctk.CTkFrame(settings, fg_color="transparent")
        linha_user.grid(row=0, column=0, sticky="w", padx=14, pady=(12, 6))
        ctk.CTkLabel(linha_user, text="Usuário da live (@)", font=ctk.CTkFont("Segoe UI", 13)
                     ).pack(side="left", padx=(0, 8))
        self.username_var = ctk.StringVar(value=self.app.config["live"].get("username", ""))
        entrada_user = ctk.CTkEntry(linha_user, textvariable=self.username_var, width=220)
        entrada_user.pack(side="left", padx=(0, 6))
        ctk.CTkButton(linha_user, text="Aplicar", width=90, command=self.apply_username
                      ).pack(side="left")
        entrada_user.bind("<Return>", lambda _e: self.apply_username())

        # Linha 2: primeiro a decisão (conectar sozinho?), depois o detalhe dela
        # (de quanto em quanto tempo). Um número só — "verificar de novo" e
        # "tentar de novo depois de um erro" eram a mesma pergunta com dois
        # campos, e cada um valia num momento diferente sem isso ficar claro.
        linha_auto = ctk.CTkFrame(settings, fg_color="transparent")
        linha_auto.grid(row=1, column=0, sticky="w", padx=14, pady=(0, 6))
        self.auto_var = ctk.BooleanVar(value=bool(self.app.config["live"].get("auto_connect", False)))
        ctk.CTkCheckBox(linha_auto, text="Conectar automaticamente ao abrir o programa",
                        variable=self.auto_var, command=self.apply_auto_connect,
                        font=ctk.CTkFont("Segoe UI", 13)
                        ).pack(side="left", padx=(0, 18))
        ctk.CTkLabel(linha_auto, text="Verificar a cada", font=ctk.CTkFont("Segoe UI", 13)
                     ).pack(side="left", padx=(0, 6))
        self.verify_var = ctk.StringVar(value=str(self.app.config["live"].get("verify_poll", 5)))
        entrada_verify = ctk.CTkEntry(linha_auto, textvariable=self.verify_var, width=70)
        entrada_verify.pack(side="left", padx=(0, 6))
        ctk.CTkLabel(linha_auto, text="segundos", font=ctk.CTkFont("Segoe UI", 13),
                     text_color=("#7a7a7a", "#9a9a9a")).pack(side="left")

        # Gravar ao sair do campo: digitar e trocar de aba perdia o valor.
        entrada_verify.bind("<FocusOut>", lambda _e: self.apply_verify())
        entrada_verify.bind("<Return>", lambda _e: self.apply_verify())

        self.toggle_btn = ctk.CTkButton(settings, text="Conectar", width=150,
                                        command=self.toggle_monitor,
                                        fg_color="#4caf50", hover_color="#3d8b40")
        self.toggle_btn.grid(row=2, column=0, sticky="w", padx=14, pady=(4, 12))

        self.state_label = ctk.CTkLabel(self, text="Parado", font=ctk.CTkFont("Segoe UI", 14, "bold"),
                                        text_color=("#8a8f98"))
        self.state_label.grid(row=3, column=0, sticky="nw", padx=16, pady=(0, 6))

        log_wrap = ctk.CTkFrame(self)
        log_wrap.grid(row=4, column=0, sticky="nsew", padx=16, pady=(0, 16))
        log_wrap.grid_columnconfigure(0, weight=1)
        log_wrap.grid_rowconfigure(0, weight=1)

        bg = "#111111" if self.app.config["app"].get("appearance") == "dark" else "#ffffff"
        self.log_text = tk.Text(
            log_wrap, state="disabled", wrap="word", bg=bg,
            fg="#d0d0d0" if bg == "#111111" else "#222222",
            insertbackground="white", relief="flat", padx=10, pady=8,
            font=("Consolas", 10),
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scroll = ctk.CTkScrollbar(log_wrap, command=self.log_text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scroll.set)
        self.app.register_log_widget(self.log_text)

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=5, column=0, sticky="we", padx=16, pady=(0, 12))
        ctk.CTkButton(bottom, text="Limpar log", width=110, command=self.clear_log
                      ).pack(side="right")

        ctk.CTkLabel(bottom, text="Mostrar:", font=ctk.CTkFont("Segoe UI", 12),
                     text_color=("#7a7a7a", "#9a9a9a")).pack(side="left", padx=(0, 8))
        filtros = self.app.config.setdefault("log", {})
        self.filtro_vars = {}
        for chave, (rotulo, _niveis) in logger.CATEGORIAS.items():
            var = ctk.BooleanVar(value=bool(filtros.get(chave, True)))
            self.filtro_vars[chave] = var
            ctk.CTkCheckBox(bottom, text=rotulo, variable=var, width=20,
                            checkbox_width=18, checkbox_height=18,
                            font=ctk.CTkFont("Segoe UI", 12),
                            command=lambda c=chave: self.apply_filtro(c)
                            ).pack(side="left", padx=(0, 12))

    # ---------------- ações ----------------
    def apply_username(self):
        username = self.username_var.get().strip().lstrip("@")
        if not username:
            logger.log("warning", "Informe o usuário da live.")
            return
        self.app.config["live"]["username"] = username
        logger.log("system", f"Usuário definido: @{username}")
        if self.app.engine.monitoring:
            self.app.engine.stop_monitoring()
            self.app.engine.start_monitoring()

    def apply_auto_connect(self):
        self.app.config["live"]["auto_connect"] = bool(self.auto_var.get())
        save_config(self.app.config)
        logger.log("system", "Conexão automática "
                   + ("ativada." if self.auto_var.get() else "desativada."))

    def _aplicar_tempo(self, var, chave, rotulo, minimo=1, maximo=600):
        """Valida, corrige o que aparece na tela e grava. Devolve o valor."""
        atual = int(self.app.config["live"].get(chave, minimo))
        try:
            valor = int(var.get().strip())
        except ValueError:
            var.set(str(atual))
            logger.log("warning", f"{rotulo}: valor inválido, mantido em {atual}s.")
            return atual
        valor = max(minimo, min(maximo, valor))
        var.set(str(valor))
        if valor != atual:
            self.app.config["live"][chave] = valor
            save_config(self.app.config)
            logger.log("system", f"{rotulo}: {valor}s.")
        return valor

    def apply_verify(self):
        return self._aplicar_tempo(self.verify_var, "verify_poll", "Verificar a cada")

    def toggle_monitor(self):
        if self.app.engine.monitoring:
            self.app.engine.stop_monitoring()
        else:
            self.apply_username()
            self.apply_verify()
            self.app.engine.start_monitoring()

    def apply_filtro(self, chave):
        self.app.config.setdefault("log", {})[chave] = bool(self.filtro_vars[chave].get())
        self.app.aplicar_filtros_log()
        save_config(self.app.config)

    def clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        logger.clear()

    def _on_status(self, state, text):
        colors = {
            "off": "#8a8f98", "standby": "#f4c542",
            "connecting": "#f4a742", "connected": "#4caf50", "error": "#ff6b6b",
        }
        labels = {"off": "Parado", "standby": "Standby", "connecting": "Conectando...",
                  "connected": "Conectado", "error": "Erro"}
        self.state_label.configure(text=f"{labels.get(state, 'Parado')} — {text}",
                                   text_color=colors.get(state, "#8a8f98"))
        if state == "off":
            self.toggle_btn.configure(text="Conectar", fg_color="#4caf50", hover_color="#3d8b40")
        else:
            self.toggle_btn.configure(text="Desconectar", fg_color="#c0392b", hover_color="#922b21")

    def refresh_if_needed(self):
        pass
