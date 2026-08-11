# -*- coding: utf-8 -*-
"""Aba Configurações: só o que é do programa inteiro e o usuário decide.

O que é de uma seção só mora na seção: a impressora fica na ação de imprimir
(aba Reações), as pastas do jogo na aba Jogo Perfil, a voz na aba Texto para
Fala e os tempos da live na aba Conexão. O que é ajuste interno — o vigia da
conexão, as pastas temporárias — não aparece: o programa cuida sozinho.
"""
import customtkinter as ctk

from core import logger
from core.config import save_config


class SettingsTab(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self._build()

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(self, text="Configurações",
                     font=ctk.CTkFont("Segoe UI", 22, "bold")
                     ).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 8))

        scroller = ctk.CTkScrollableFrame(self)
        scroller.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 8))
        scroller.grid_columnconfigure(0, weight=1)

        self._bloco_obs(scroller, 0)
        self._bloco_aparencia(scroller, 1)
        self._bloco_backup(scroller, 2)
        self._bloco_admin(scroller, 3)

        save_row = ctk.CTkFrame(scroller, fg_color="transparent")
        save_row.grid(row=4, column=0, sticky="we", pady=10)
        ctk.CTkButton(save_row, text="Salvar configurações", width=200, command=self.save,
                      fg_color="#4caf50", hover_color="#3d8b40").pack(side="right", padx=6)

    # ---------------- OBS ----------------
    def _bloco_obs(self, parent, row):
        bloco = ctk.CTkFrame(parent)
        bloco.grid(row=row, column=0, sticky="we", pady=8)
        bloco.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(bloco, text="Conexão com o OBS",
                     font=ctk.CTkFont("Segoe UI", 15, "bold")
                     ).grid(row=0, column=0, columnspan=2, sticky="w", padx=18, pady=(14, 4))
        ctk.CTkLabel(bloco, text="As reações que trocam de cena ou mostram uma fonte precisam disto. "
                                 "O botão abaixo lê a configuração do próprio OBS.",
                     font=ctk.CTkFont("Segoe UI", 12), text_color=("#7a7a7a", "#9a9a9a"),
                     wraplength=560, justify="left", anchor="w"
                     ).grid(row=1, column=0, columnspan=2, sticky="w", padx=18, pady=(0, 8))

        self.obs_info = ctk.CTkLabel(bloco, text="", anchor="w", justify="left",
                                     font=ctk.CTkFont("Segoe UI", 12),
                                     text_color=("#7a7a7a", "#9a9a9a"), wraplength=560)
        self.obs_info.grid(row=2, column=0, columnspan=2, sticky="w", padx=18, pady=(2, 8))

        botoes = ctk.CTkFrame(bloco, fg_color="transparent")
        botoes.grid(row=3, column=0, columnspan=2, sticky="w", padx=18, pady=(0, 10))
        ctk.CTkButton(botoes, text="Detectar do OBS", width=150,
                      command=self.detectar_obs).pack(side="left", padx=(0, 6))
        ctk.CTkButton(botoes, text="Testar conexão", width=140,
                      command=self.testar_obs).pack(side="left")

        # Endereço, porta e senha são o plano B: a detecção resolve quase
        # sempre, e deixar os três campos à mostra faz parecer que tem que
        # preencher alguma coisa.
        self.manual_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(bloco, text="Preencher manualmente", variable=self.manual_var,
                        command=self._alternar_manual, font=ctk.CTkFont("Segoe UI", 12)
                        ).grid(row=4, column=0, columnspan=2, sticky="w", padx=18, pady=(0, 8))

        self.manual = ctk.CTkFrame(bloco, fg_color="transparent")
        self.manual.grid(row=5, column=0, columnspan=2, sticky="we", padx=4, pady=(0, 10))
        self.manual.grid_columnconfigure(1, weight=1)
        self.entries = {}
        campos = [("host", "Endereço"), ("port", "Porta"), ("password", "Senha")]
        for i, (chave, rotulo) in enumerate(campos):
            ctk.CTkLabel(self.manual, text=rotulo, font=ctk.CTkFont("Segoe UI", 13), anchor="w"
                         ).grid(row=i, column=0, sticky="w", padx=(14, 12), pady=5)
            var = ctk.StringVar(value=str(self.app.config["obs"].get(chave, "")))
            ctk.CTkEntry(self.manual, textvariable=var,
                         show="•" if chave == "password" else "",
                         width=260 if chave != "port" else 120
                         ).grid(row=i, column=1, sticky="w", padx=(0, 18), pady=5)
            self.entries[f"obs.{chave}"] = var
        self.manual.grid_remove()

        self._mostrar_obs_detectado()

    def _alternar_manual(self):
        if self.manual_var.get():
            self.manual.grid()
        else:
            self.manual.grid_remove()

    # ---------------- aparência ----------------
    def _bloco_aparencia(self, parent, row):
        bloco = ctk.CTkFrame(parent)
        bloco.grid(row=row, column=0, sticky="we", pady=8)
        bloco.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(bloco, text="Aparência",
                     font=ctk.CTkFont("Segoe UI", 15, "bold")
                     ).grid(row=0, column=0, columnspan=2, sticky="w", padx=18, pady=(14, 8))

        ctk.CTkLabel(bloco, text="Tema", font=ctk.CTkFont("Segoe UI", 13)
                     ).grid(row=1, column=0, sticky="w", padx=(18, 12), pady=8)
        self.appearance_var = ctk.StringVar(value=self.app.config["app"].get("appearance", "dark"))
        ctk.CTkOptionMenu(bloco, values=["dark", "light", "system"],
                          variable=self.appearance_var, width=140
                          ).grid(row=1, column=1, sticky="w", padx=(0, 18), pady=8)

        ctk.CTkLabel(bloco, text="Cor de destaque", font=ctk.CTkFont("Segoe UI", 13)
                     ).grid(row=2, column=0, sticky="w", padx=(18, 12), pady=8)
        self.theme_var = ctk.StringVar(value=self.app.config["app"].get("color_theme", "blue"))
        ctk.CTkOptionMenu(bloco, values=["blue", "green", "dark-blue"],
                          variable=self.theme_var, width=140
                          ).grid(row=2, column=1, sticky="w", padx=(0, 18), pady=8)

        ctk.CTkLabel(bloco, text="Tema e cor são aplicados ao reiniciar o programa.",
                     font=ctk.CTkFont("Segoe UI", 11), text_color=("#7a7a7a", "#9a9a9a")
                     ).grid(row=3, column=0, columnspan=2, sticky="w", padx=18, pady=(4, 16))

    # ---------------- exportar / importar ----------------
    def _bloco_backup(self, parent, row):
        bloco = ctk.CTkFrame(parent)
        bloco.grid(row=row, column=0, sticky="we", pady=8)
        bloco.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(bloco, text="Backup das configurações",
                     font=ctk.CTkFont("Segoe UI", 15, "bold")
                     ).grid(row=0, column=0, sticky="w", padx=18, pady=(14, 4))
        ctk.CTkLabel(
            bloco,
            text=("Leva tudo junto: reações, mensagens do chat, voz, OBS, pastas do "
                  "Jogo Perfil e aparência. Serve para passar a sua configuração "
                  "para outro computador ou para uma instalação nova."),
            font=ctk.CTkFont("Segoe UI", 12), text_color=("#7a7a7a", "#9a9a9a"),
            wraplength=560, justify="left", anchor="w"
            ).grid(row=1, column=0, sticky="w", padx=18, pady=(0, 8))

        botoes = ctk.CTkFrame(bloco, fg_color="transparent")
        botoes.grid(row=2, column=0, sticky="w", padx=18, pady=(0, 6))
        ctk.CTkButton(botoes, text="Exportar...", width=140, command=self.exportar
                      ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(botoes, text="Importar...", width=140, command=self.importar
                      ).pack(side="left")

        self.backup_info = ctk.CTkLabel(
            bloco, text="", font=ctk.CTkFont("Segoe UI", 11),
            text_color=("#7a7a7a", "#9a9a9a"), wraplength=560,
            justify="left", anchor="w")
        self.backup_info.grid(row=3, column=0, sticky="w", padx=18, pady=(0, 14))

    def exportar(self):
        from tkinter import filedialog

        from core.config import exportar as exportar_config

        # O que estiver digitado nesta aba entra no arquivo junto.
        self.save()
        destino = filedialog.asksaveasfilename(
            parent=self.winfo_toplevel(), title="Exportar configurações",
            defaultextension=".json", initialfile="dinfinity-config.json",
            filetypes=[("Configuração do Dinfinity", "*.json"), ("Todos", "*.*")])
        if not destino:
            return
        try:
            exportar_config(self.app.config, destino)
        except OSError as exc:
            self.backup_info.configure(text=f"Não consegui salvar: {exc}")
            return
        self.backup_info.configure(text=f"Exportado para {destino}")
        logger.log("success", f"Configurações exportadas para {destino}")

    def importar(self):
        import json
        from tkinter import filedialog, messagebox

        from core.config import importar as importar_config

        origem = filedialog.askopenfilename(
            parent=self.winfo_toplevel(), title="Importar configurações",
            filetypes=[("Configuração do Dinfinity", "*.json"), ("Todos", "*.*")])
        if not origem:
            return
        # Importar substitui tudo, inclusive as reações: melhor perguntar do que
        # alguém descobrir depois que perdeu o que tinha montado.
        if not messagebox.askyesno(
                "Importar configurações",
                "Isto substitui TODAS as configurações atuais — reações, mensagens "
                "do chat, voz, OBS e aparência.\n\nExporte as suas antes, se quiser "
                "poder voltar.\n\nImportar mesmo assim?",
                parent=self.winfo_toplevel()):
            return
        try:
            secoes = importar_config(self.app.config, origem)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            self.backup_info.configure(text=f"Não consegui importar: {exc}")
            logger.log("error", f"Falha ao importar configurações: {exc}")
            return
        self.backup_info.configure(
            text=f"Importado de {origem} ({len(secoes)} seção(ões)). "
                 "Feche e abra o programa para tudo passar a valer.")
        logger.log("success", "Configurações importadas. Reabra o programa para "
                              "aplicar tudo.")
        messagebox.showinfo(
            "Importado",
            "Configurações importadas.\n\nFeche e abra o Dinfinity para que todas "
            "as abas mostrem os valores novos.",
            parent=self.winfo_toplevel())

    # ---------------- administrador ----------------
    def _bloco_admin(self, parent, row):
        """Só aparece depois de ligada: é aqui que se desfaz a escolha.

        Quem nunca usou o Chat Automático não precisa nem saber que isto
        existe — daí o bloco ficar escondido enquanto nada estiver ligado.
        """
        from core.admin import tarefa_existe

        self.tem_tarefa = tarefa_existe()
        self.pede_ao_abrir = bool(self.app.config["app"].get("abrir_como_admin", False))
        if not self.tem_tarefa and not self.pede_ao_abrir:
            return

        bloco = ctk.CTkFrame(parent)
        bloco.grid(row=row, column=0, sticky="we", pady=8)
        bloco.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(bloco, text="Abertura como Administrador",
                     font=ctk.CTkFont("Segoe UI", 15, "bold")
                     ).grid(row=0, column=0, sticky="w", padx=18, pady=(14, 4))
        self.admin_info = ctk.CTkLabel(
            bloco, text="", font=ctk.CTkFont("Segoe UI", 12),
            text_color=("#7a7a7a", "#9a9a9a"), wraplength=560, justify="left", anchor="w")
        self.admin_info.grid(row=1, column=0, sticky="w", padx=18, pady=(0, 8))
        self.admin_botao = ctk.CTkButton(bloco, text="Desligar", width=230,
                                         command=self.desligar_admin,
                                         fg_color="#c0392b", hover_color="#922b21")
        self.admin_botao.grid(row=2, column=0, sticky="w", padx=18, pady=(0, 14))
        self._mostrar_estado_admin()

    def _mostrar_estado_admin(self):
        if self.tem_tarefa:
            texto = ("Ligada, sem perguntar. Uma tarefa do Windows abre o Dinfinity "
                     "já com privilégios de Administrador — é o que o Chat Automático "
                     "precisa. Desligue se não usa mais essa aba.")
        else:
            texto = ("Ligada. O Windows pede a confirmação do UAC ao abrir o programa, "
                     "antes de a live conectar, então nada é interrompido. Desligue se "
                     "não usa mais o Chat Automático.")
        self.admin_info.configure(text=texto)

    def desligar_admin(self):
        from core.admin import e_admin, remover_tarefa

        if self.tem_tarefa:
            if not e_admin():
                self.admin_info.configure(
                    text="Para remover a tarefa, o Dinfinity precisa estar rodando como "
                         "Administrador — que é justamente como ele abre agora. Abra o "
                         "programa normalmente e tente de novo.")
                return
            if not remover_tarefa():
                self.admin_info.configure(text="Não consegui remover a tarefa do Windows.")
                return
            self.tem_tarefa = False
        self.app.config["app"]["abrir_como_admin"] = False
        save_config(self.app.config)
        self.admin_info.configure(
            text="Desligada. Na próxima vez o Dinfinity abre sem privilégio, e só "
                 "pergunta se você ligar o Chat Automático.")
        self.admin_botao.configure(state="disabled", text="Desligada")

    # ---------------- OBS: ações ----------------
    def _mostrar_obs_detectado(self):
        achado = getattr(self.app, "_obs_detectado", None)
        if not achado:
            self.obs_info.configure(
                text="Não achei a configuração do obs-websocket. Abra o OBS e clique em "
                     "Detectar, ou preencha à mão (no OBS: Ferramentas → "
                     "Configurações do WebSocket).")
            return
        estado = "ligado" if achado["habilitado"] else "DESLIGADO no OBS"
        senha = "com senha" if achado["exige_senha"] else "sem senha"
        conectado = self.app.engine.actions.obs.connected
        self.obs_info.configure(
            text=f"Detectado no OBS: porta {achado['port']}, {senha}, servidor {estado}.  "
                 f"{'Conectado agora.' if conectado else 'Ainda não conectado.'}")

    def detectar_obs(self):
        from core.obs_config import aplicar
        mudou, achado = aplicar(self.app.config)
        self.app._obs_detectado = achado
        if achado:
            for chave in ("host", "port", "password"):
                self.entries[f"obs.{chave}"].set(str(self.app.config["obs"].get(chave, "")))
            logger.log("system", f"[OBS] Configuração lida de {achado['arquivo']}"
                                 + (" (config atualizado)." if mudou else "."))
        else:
            logger.log("warning", "[OBS] Não achei a configuração do obs-websocket.")
        self._mostrar_obs_detectado()

    def testar_obs(self):
        self.save()
        logger.log("info", "[OBS] Testando a conexão...")

        def contar(cenas, erro):
            # Roda na thread do monitor: só o logger, que é próprio para isso.
            # A faixa de estado se atualiza sozinha ao voltar para esta aba.
            if erro is not None:
                logger.log("error", f"[OBS] Não conectou: {erro}")
            else:
                logger.log("success", f"[OBS] Conectado! {len(cenas)} cena(s) encontradas.")

        self.app.engine.actions.configure(self.app.config.get("obs", {}),
                                          self.app.config.get("sound", {}))
        self.app.engine.obs_consultar(lambda obs: obs.listar_cenas(), contar)

    # ---------------- salvar ----------------
    def save(self):
        for chave, var in self.entries.items():
            _secao, campo = chave.split(".", 1)
            bruto = var.get().strip()
            if campo == "port":
                try:
                    self.app.config["obs"][campo] = int(bruto)
                except ValueError:
                    continue
            else:
                self.app.config["obs"][campo] = bruto
        self.app.config["app"]["appearance"] = self.appearance_var.get()
        self.app.config["app"]["color_theme"] = self.theme_var.get()
        self.app.engine.actions.configure(self.app.config.get("obs", {}),
                                          self.app.config.get("sound", {}))
        save_config(self.app.config)
        logger.log("success", "Configurações salvas.")

    def refresh_if_needed(self):
        self._mostrar_obs_detectado()
