# -*- coding: utf-8 -*-
"""Aba Gravador, portada fielmente do Replay Downloader.

A conta (username) e o tempo de verificação vêm da aba Conexão; aqui não há
campo de usuário nem de polling. Também não há escolha de qualidade: a variante
`origin` é o próprio vídeo da live sem recompressão, então é sempre ela.

A verificação de "estou ao vivo?" é feita pelo MonitorEngine (aba Conexão); o
RecorderHost assina os eventos de live dele e grava conforme o config, mesmo
sem esta aba aberta. O gravador tem o mesmo comportamento do original: REC
vermelho com hover, faixa de estado colorida, registro com cartões, prévia ao
vivo opcional e resgate de gravações interrompidas.

A sub-aba "Editar" abre o editor de vídeo (motor copiado para rd/), carregado
preguiçosamente na primeira vez que a aba é aberta.
"""
import os
import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk

from core import logger
from core.recorder_host import RD_DIR, ensure_rd_in_path, wait_for_rd_import

# Cada estado tem sua cor de faixa (tema claro e escuro).
NEUTRO = {"fg": "#374151", "bg": "#f3f4f6", "dot": "#9ca3af", "border": "#d1d5db", "prefix": ""}
PALETTE = {
    "parado": NEUTRO,
    "offline": NEUTRO,
    "info": NEUTRO,
    "aguardando": {
        "fg": "#92400e", "bg": "#fef3c7", "dot": "#f59e0b",
        "border": "#fcd34d", "prefix": "Aguardando - ",
    },
    "aovivo": {
        "fg": "#065f46", "bg": "#d1fae5", "dot": "#10b981",
        "border": "#6ee7b7", "prefix": "Ao vivo - ",
    },
    "gravando": {
        "fg": "#b91c1c", "bg": "#fee2e2", "dot": "#dc2626",
        "border": "#f87171", "prefix": "● GRAVANDO - ",
    },
    "finalizando": {
        "fg": "#1e40af", "bg": "#dbeafe", "dot": "#3b82f6",
        "border": "#93c5fd", "prefix": "Finalizando - ",
    },
    "concluido": {
        "fg": "#166534", "bg": "#dcfce7", "dot": "#22c55e",
        "border": "#86efac", "prefix": "",
    },
    "erro": {
        "fg": "#b91c1c", "bg": "#fee2e2", "dot": "#dc2626",
        "border": "#f87171", "prefix": "Erro - ",
    },
}
NEUTRO_ESCURO = {"fg": "#dce4ee", "bg": "#232323", "dot": "#9ca3af", "border": "#3a3a3a", "prefix": ""}
PALETA_ESCURA = {
    "parado": NEUTRO_ESCURO,
    "offline": NEUTRO_ESCURO,
    "info": NEUTRO_ESCURO,
    "aguardando": {
        "fg": "#fcd34d", "bg": "#33291a", "dot": "#f59e0b", "border": "#7c5a1e", "prefix": "Aguardando - ",
    },
    "aovivo": {
        "fg": "#6ee7b7", "bg": "#123026", "dot": "#10b981", "border": "#1f6e53", "prefix": "Ao vivo - ",
    },
    "gravando": {
        "fg": "#fca5a5", "bg": "#331419", "dot": "#dc2626", "border": "#7f2733", "prefix": "● GRAVANDO - ",
    },
    "finalizando": {
        "fg": "#93c5fd", "bg": "#152338", "dot": "#3b82f6", "border": "#1e3a8a", "prefix": "Finalizando - ",
    },
    "concluido": {
        "fg": "#86efac", "bg": "#10281c", "dot": "#22c55e", "border": "#166534", "prefix": "",
    },
    "erro": {
        "fg": "#fca5a5", "bg": "#331419", "dot": "#dc2626", "border": "#7f2733", "prefix": "Erro - ",
    },
}

CARD_BG = "#f8fafc"
CARD_BORDER = "#cbd5e1"
CARD_BG_ESCURO = "#232323"
CARD_BORDER_ESCURO = "#3a3a3a"
CARD_FG_ESCURO = "#e5e7eb"
CARD_MUTED_ESCURO = "#9ca3af"


def formata_tamanho(num_bytes: int) -> str:
    mb = num_bytes / (1024 * 1024)
    if mb >= 1024:
        return f"{mb / 1024:.2f} GB"
    if mb >= 100:
        return f"{mb:.0f} MB"
    return f"{mb:.1f} MB"


def formata_duracao(segundos: int) -> str:
    horas, resto = divmod(int(segundos), 3600)
    minutos, seg = divmod(resto, 60)
    if horas:
        return f"{horas}:{minutos:02d}:{seg:02d}"
    return f"{minutos:02d}:{seg:02d}"


def open_path(path: str) -> None:
    if os.path.exists(path):
        try:
            os.startfile(path)  # noqa: S606
        except OSError:
            pass


def reveal_in_explorer(path: str) -> None:
    if os.path.exists(path):
        try:
            os.system(f'explorer /select,"{os.path.normpath(path)}"')  # noqa: S605
        except OSError:
            pass


class RecorderTab(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.host = app.recorder_host
        # Os módulos do motor (recorder, editor...) se importam por nome simples
        # a partir de rd/. Sem isto, tudo que esta aba importa direto — checagem
        # do ffmpeg, aviso de espaço em disco, resgate de gravações — falharia
        # calado na abertura, antes de o editor colocar rd/ no path.
        ensure_rd_in_path()

        self._escuro = self.app.config["app"].get("appearance", "dark") == "dark"
        self._tabuleiro = PALETA_ESCURA if self._escuro else PALETTE

        self.editor = None
        self._editor_mod = None
        self._editor_loading = False
        self._editor_load_error = None

        self._state_key = "parado"
        self._blink_on = False
        self._disarming = False
        self._espaco_avisado = False
        self._ultimo_espaco = 0.0
        self._thumbs: list[tk.PhotoImage] = []

        self._preview_url = ""
        self._preview_carregada = ""
        self.preview_player = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.abas = ttk.Notebook(self, takefocus=False)
        self.abas.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.abas.bind("<<NotebookTabChanged>>", self._aba_mudou, add="+")
        self.abas.bind("<Button-1>", lambda _e: self.after_idle(self._aba_mudou), add="+")

        self._build_gravador_tab()
        self._build_editor_tab()

        self.bind("<Configure>", self._janela_redimensionada, add="+")
        self.after(180, self._ajustar_preview)
        self._sync_buttons()
        self._check_dependencies()
        self.after(120, self._drain)
        self.after(550, self._pulse)
        # Depois do _drain, como no original: o "Pronto." das dependências já
        # está no registro quando o REC automático anuncia que se armou.
        self.after(400, self._auto_armar)
        self._procurar_interrompidas()

        self.app.add_status_listener(self._live_mudou)
        self.app.add_close_hook(self._on_close_recorder)

    def _janela(self):
        try:
            return self.winfo_toplevel()
        except tk.TclError:
            return self

    # ------------------------------------------------------------ Gravador

    def _build_gravador_tab(self):
        main = ttk.Frame(self.abas, padding=18)
        self.abas.add(main, text="Gravar")
        main.columnconfigure(1, weight=1)
        main.columnconfigure(2, weight=1, minsize=150)
        main.rowconfigure(6, weight=1)
        rotulo = {"font": ("Segoe UI", 10)}

        # --- pasta ---------------------------------------------------------
        ttk.Label(main, text="Salvar em", **rotulo).grid(row=0, column=0, sticky="w", pady=8)
        pasta = ttk.Frame(main)
        pasta.grid(row=0, column=1, sticky="ew", pady=8)
        pasta.columnconfigure(0, weight=1)
        self.outdir_var = tk.StringVar(
            value=self.app.config["recorder"].get("outdir", os.path.join(RD_DIR, "..", "Gravacoes")))
        ttk.Entry(pasta, textvariable=self.outdir_var).grid(
            row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(pasta, text="Escolher...", command=self._pick_dir).grid(row=0, column=1)
        ttk.Button(pasta, text="Abrir pasta", command=self._open_outdir).grid(
            row=0, column=2, padx=(8, 0))

        # --- opcoes --------------------------------------------------------
        opcoes = ttk.Frame(main)
        opcoes.grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self.keep_var = tk.BooleanVar(
            value=bool(self.app.config["recorder"].get("keep_waiting", True)))
        ttk.Checkbutton(
            opcoes,
            text="Continuar aguardando as próximas lives depois que uma terminar",
            variable=self.keep_var,
            command=self._persist_recorder,
        ).pack(anchor="w")

        self.auto_rec_var = tk.BooleanVar(
            value=bool(self.app.config["recorder"].get("auto_rec", False)))
        ttk.Checkbutton(
            opcoes,
            text="Armar o REC sozinho ao abrir o programa (não preciso clicar em nada)",
            variable=self.auto_rec_var,
            command=self._auto_rec_mudou,
        ).pack(anchor="w", pady=(4, 0))

        self.presentes_var = tk.BooleanVar(
            value=bool(self.app.config["recorder"].get("registrar_presentes", True)))
        ttk.Checkbutton(
            opcoes,
            text="Registrar presentes e chat (gera o pacote para inserir as animações depois)",
            variable=self.presentes_var,
            command=self._presentes_mudou,
        ).pack(anchor="w", pady=(4, 0))

        ttk.Separator(main, orient="horizontal").grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=16)

        # --- botoes REC ----------------------------------------------------
        botoes = ttk.Frame(main)
        botoes.grid(row=3, column=0, columnspan=2, sticky="ew")
        # tk.Button e nao ttk: o tema nativo do ttk ignora as cores de fundo, e
        # sem cor nao ha cara de REC.
        self.start_btn = tk.Button(
            botoes,
            command=self._toggle,
            font=("Segoe UI", 12, "bold"),
            fg="white",
            disabledforeground="#fecaca",
            activeforeground="white",
            bd=3,
            padx=22,
            pady=10,
            cursor="hand2",
        )
        self.start_btn.pack(side="left")
        self.start_btn.bind("<Enter>", lambda _e: self._hover_rec(True))
        self.start_btn.bind("<Leave>", lambda _e: self._hover_rec(False))
        self.stop_btn = tk.Button(
            botoes,
            text="■  Parar e salvar",
            command=self._stop,
            font=("Segoe UI", 10),
            bg=("#3a3a3a" if self._escuro else "#e5e7eb"),
            fg=("#e5e7eb" if self._escuro else "#374151"),
            disabledforeground="#6b7280",
            activebackground=("#4a4a4a" if self._escuro else "#d1d5db"),
            activeforeground=("#ffffff" if self._escuro else "#1f2937"),
            bd=2,
            padx=16,
            pady=10,
            cursor="hand2",
        )
        self.stop_btn.pack(side="left", padx=12)

        # --- faixa de estado ----------------------------------------------
        self.status_var = tk.StringVar(value="Parado")
        self.detail_var = tk.StringVar(value="")

        self.banner = tk.Frame(main, highlightthickness=1, bd=0)
        self.banner.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(16, 4))
        inner = tk.Frame(self.banner, bd=0)
        inner.pack(fill="x", padx=12, pady=10)
        self._banner_parts = [self.banner, inner]

        self.dot = tk.Canvas(inner, width=16, height=16, highlightthickness=0, bd=0)
        self.dot_item = self.dot.create_oval(3, 3, 14, 14, outline="")
        self.dot.pack(side="left")
        self.status_label = tk.Label(
            inner, textvariable=self.status_var, font=("Segoe UI", 12, "bold"), bd=0)
        self.status_label.pack(side="left", padx=(9, 0))
        self.detail_label = tk.Label(
            inner, textvariable=self.detail_var, font=("Consolas", 10), bd=0)
        self.detail_label.pack(side="right")

        # --- prévia ao vivo ------------------------------------------------
        self.preview_box = ttk.LabelFrame(main, text=" Prévia ao vivo ", padding=7)
        self.preview_box.grid(row=0, column=2, rowspan=7, sticky="nsew", padx=(18, 0))
        self.preview_box.columnconfigure(0, weight=1)
        # A reserva continua em 9:16, mas acompanha o espaço disponível.
        self.preview_tela = tk.Frame(self.preview_box, bg="#0b0b0b", width=250, height=444)
        self.preview_tela.grid(row=0, column=0, sticky="n")
        self.preview_tela.grid_propagate(False)
        lado_preview = ttk.Frame(self.preview_box)
        lado_preview.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(lado_preview, text="A prévia não altera o arquivo salvo.",
                  wraplength=250).pack(anchor="w")
        self.preview_audio_var = tk.BooleanVar(
            value=bool(self.app.config["recorder"].get("preview_audio", False)))
        self.preview_var = tk.BooleanVar(
            value=bool(self.app.config["recorder"].get("preview_live", True)))
        ttk.Checkbutton(lado_preview, text="Exibir prévia ao vivo", variable=self.preview_var,
                        command=self._preview_mudou).pack(anchor="w", pady=(8, 2))
        ttk.Checkbutton(lado_preview, text="Ouvir áudio", variable=self.preview_audio_var,
                        command=self._preview_audio_mudou).pack(anchor="w", pady=(10, 2))
        volume_linha = ttk.Frame(lado_preview)
        volume_linha.pack(anchor="w", fill="x")
        ttk.Label(volume_linha, text="Volume").pack(side="left")
        self.preview_volume_var = tk.DoubleVar(
            value=float(self.app.config["recorder"].get("preview_volume", 50)))
        ttk.Scale(volume_linha, from_=0, to=100, orient="horizontal", length=150,
                  variable=self.preview_volume_var,
                  command=lambda _v: self._preview_audio_mudou()).pack(side="left", padx=8)
        self.preview_info_var = tk.StringVar(value="Aguardando uma gravação")
        ttk.Label(lado_preview, textvariable=self.preview_info_var,
                  foreground=("#94a3b8" if self._escuro else "#64748b")
                  ).pack(anchor="w", pady=(10, 0))

        # --- registro ------------------------------------------------------
        registro = ttk.LabelFrame(main, text=" Registro ", padding=6)
        registro.grid(row=6, column=0, columnspan=2, sticky="nsew", pady=(12, 0))
        registro.rowconfigure(0, weight=1)
        registro.columnconfigure(0, weight=1)
        self.log = tk.Text(
            registro, height=10, wrap="word", state="disabled",
            font=("Consolas", 9), bd=0, relief="flat",
            bg=("#0f0f0f" if self._escuro else "#ffffff"),
            fg=("#d4d4d4" if self._escuro else "#18181b"),
            insertbackground=("#e5e5e5" if self._escuro else "#18181b"),
            padx=6, pady=4, cursor="arrow",
        )
        scroll = ttk.Scrollbar(registro, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

        self._apply_state("parado", "Parado")

    def _build_editor_tab(self):
        placeholder = ttk.Frame(self.abas, padding=18)
        self.abas.add(placeholder, text="Editar")
        self.editor_placeholder = placeholder
        ttk.Label(placeholder, text="Abrindo o editor...").pack(expand=True)

    # ------------------------------------------------------------- editor

    def _aba_mudou(self, _evt=None) -> None:
        """Na aba do editor o teclado é do playhead, não da navegação."""
        try:
            if self.abas.select() == str(self.editor) and self.editor is not None:
                self.after_idle(self.editor.assumir_foco)
        except tk.TclError:
            pass

    def refresh_if_needed(self):
        if self.editor is None and not self._editor_loading and not self._editor_load_error:
            self._editor_loading = True
            threading.Thread(target=self._load_editor, daemon=True).start()
            self.after(120, self._check_editor)

    def _load_editor(self):
        try:
            self._editor_mod = wait_for_rd_import("editor")
        except Exception as exc:  # noqa: BLE001
            self._editor_load_error = exc
            logger.log("error", f"[EDITOR] Falha ao carregar: {exc}")

    def _check_editor(self):
        if not self._editor_loading:
            return
        if self._editor_load_error is not None:
            self._editor_loading = False
            self._editor_placeholder_error(str(self._editor_load_error))
            return
        if self._editor_mod is None:
            self.after(120, self._check_editor)
            return
        self._editor_loading = False
        self._make_editor()

    def _editor_placeholder_error(self, message):
        for w in self.editor_placeholder.winfo_children():
            w.destroy()
        ttk.Label(self.editor_placeholder,
                  text=f"Não foi possível abrir o editor.\n{message}",
                  foreground="#ff6b6b").pack(expand=True)

    def _make_editor(self):
        self.abas.forget(self.editor_placeholder)
        try:
            self.editor = self._editor_mod.Editor(
                self.abas,
                lambda k, v="": self.host.events.put((k, v)),
                escuro=self._escuro,
            )
            self.abas.add(self.editor, text="Editar")
            logger.log("success", "Editor aberto dentro do Dinfinity.")
        except Exception as exc:  # noqa: BLE001
            self._editor_placeholder_error(str(exc))
            logger.log("error", f"[EDITOR] Falha ao abrir: {exc}")

    # ------------------------------------------------------------ acoes

    def _pick_dir(self):
        d = filedialog.askdirectory(initialdir=self.outdir_var.get() or None)
        if d:
            self.outdir_var.set(d)
            self._persist_recorder()

    def _open_outdir(self):
        d = self.outdir_var.get()
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            return
        open_path(d)

    def _garantir_monitor(self) -> None:
        """Liga o monitor da aba Conexão, que é quem enxerga a live.

        O gravador não consulta o TikTok por conta própria: ele reage aos
        eventos do MonitorEngine. Com o monitor parado, o REC ficaria armado
        para sempre sem nunca gravar nada.
        """
        if not self.app.engine.monitoring:
            self.app.engine.start_monitoring()
            self._log("Monitor da live ligado junto (é ele quem avisa o gravador).")

    def _auto_rec_mudou(self):
        valor = bool(self.auto_rec_var.get())
        self.app.config["recorder"]["auto_rec"] = valor
        if valor:
            self._garantir_monitor()
        self.host.set_auto_rec(valor)
        self._persist_recorder()
        logger.log("system", "REC automático "
                   + ("armado ao abrir o programa." if valor else "desligado."))
        self._sync_buttons()

    def _presentes_mudou(self):
        self.app.config["recorder"]["registrar_presentes"] = bool(self.presentes_var.get())
        self._persist_recorder()

    def _persist_recorder(self):
        rec = self.app.config["recorder"]
        rec["outdir"] = self.outdir_var.get().strip()
        rec["keep_waiting"] = bool(self.keep_var.get())
        rec["auto_rec"] = bool(self.auto_rec_var.get())
        rec["registrar_presentes"] = bool(self.presentes_var.get())
        rec["preview_live"] = bool(self.preview_var.get())
        rec["preview_audio"] = bool(self.preview_audio_var.get())
        rec["preview_volume"] = float(self.preview_volume_var.get())
        try:
            from core.config import save_config
            save_config(self.app.config)
        except Exception:  # noqa: BLE001
            pass

    def _check_dependencies(self) -> None:
        def checar() -> None:
            try:
                import recorder as rec_mod
            except ImportError:
                return
            try:
                if not rec_mod.find_ffmpeg():
                    self.host.events.put(("log", "AVISO: ffmpeg não encontrado no PATH - "
                                                "a gravação não vai funcionar."))
                else:
                    self.host.events.put(("log", "ffmpeg: disponível."))
                if rec_mod.tem_encoder_aac():
                    self.host.events.put(("log", "Conversão de áudio AAC: disponível."))
                if rec_mod.gift_log.DISPONIVEL:
                    self.host.events.put(("log", "Registro de presentes e chat: disponível."))
                else:
                    self.host.events.put(("log", "AVISO: registro de presentes indisponível "
                                                "(falta a biblioteca TikTokLive) - a gravação "
                                                "funciona normalmente."))
            except Exception:  # noqa: BLE001
                pass
            try:
                import compositor
                if compositor.sem_ffprobe():
                    self.host.events.put(("log", "AVISO: ffprobe não encontrado - o editor "
                                                "não consegue ler a duração nem a resolução "
                                                "dos vídeos."))
            except Exception:  # noqa: BLE001
                pass
            try:
                import editor as ed_mod
                if ed_mod._acha_libmpv():
                    self.host.events.put(("log", "Prévia do editor: disponível."))
                else:
                    self.host.events.put(("log", "AVISO: prévia do editor indisponível "
                                                "(libmpv ausente) - a exportação funciona mesmo assim."))
            except Exception:  # noqa: BLE001
                pass
            self.host.events.put(("log", "Pronto."))
        threading.Thread(target=checar, daemon=True).start()

    def _toggle(self) -> None:
        """O botão REC liga e desliga: armar quando solto, desarmar quando armado."""
        if self.host.pending:
            self._disarm()
        else:
            self._start()

    def _start(self) -> None:
        user = self.app.config["live"].get("username", "").strip().lstrip("@")
        if not user:
            messagebox.showinfo("Falta o usuário", "Defina o seu @ do TikTok na aba Conexão.")
            return
        outdir = self.outdir_var.get().strip() or os.path.join(RD_DIR, "..", "Gravacoes")
        try:
            os.makedirs(outdir, exist_ok=True)
        except OSError as e:
            messagebox.showerror("Pasta inválida", f"Não consegui usar essa pasta:\n{e}")
            return

        self._avisar_espaco(outdir)

        self._persist_recorder()
        self._apply_state("aguardando", "Verificando...")
        self._espaco_avisado = False
        self._garantir_monitor()
        self.host.arm_manual()
        self._sync_buttons()

    def _auto_armar(self) -> None:
        """Arma o REC assim que o programa abre, se a opção estiver marcada.

        No original o `_start` automático subia o motor de vigília sozinho.
        Aqui quem enxerga a live é o monitor da aba Conexão, então é ele que
        precisa estar de pé — senão a opção não fazia absolutamente nada.
        """
        if not self.auto_rec_var.get() or self.host.recording:
            return
        self._log("REC automático ligado: armando sozinho ao abrir.")
        self._garantir_monitor()
        self._apply_state("aguardando", "Verificando...")
        self._sync_buttons()

    def _live_mudou(self, state: str, _texto: str) -> None:
        """Mostra na faixa o que o monitor da aba Conexão está vendo.

        Substitui o "Verificar agora" do original: a consulta é uma só, feita
        lá, mas o gravador continua dizendo se a live está no ar. Só vale com o
        gravador ocioso — armado ou gravando, quem manda na faixa é o motor.
        """
        if (self.host.pending or self.host.recording or self.host.active
                or self._disarming):
            return
        # "Gravação salva" fica na tela até o próximo armar: o fim da live
        # chega logo depois e apagaria o aviso na cara do usuário.
        if self._state_key == "concluido":
            return
        if state == "connected":
            self._apply_state("aovivo", "Ao vivo agora")
        elif state in ("standby", "connecting"):
            self._apply_state("offline", "Offline")
        else:
            self._apply_state("parado", "Parado")

    def _disarm(self) -> None:
        """Cancela a espera sem gravar nada (só vale antes da live começar)."""
        self._log("Gravação desarmada.")
        self._disarming = True
        self.host.disarm_manual()
        self._apply_state("info", "Desarmando...")
        threading.Thread(target=self.host.stop, daemon=True).start()
        # No original o motor estava sempre rodando enquanto armado, então o
        # "finished" dele soltava o botão. Aqui, armado sem live no ar, não há
        # motor nenhum para parar — sem isto o botão ficava preso em
        # "Desarmando..." para sempre.
        if not self.host.active:
            self._disarming = False
            self._apply_state("parado", "Parado")

    def _stop(self) -> None:
        self._log("Parando... o arquivo está sendo fechado.")
        self.stop_btn.configure(state="disabled")
        if self.host.recording:
            self._apply_state("finalizando", "Fechando o arquivo...")
        threading.Thread(target=self.host.stop, daemon=True).start()

    def _avisar_espaco(self, outdir: str) -> None:
        """Diz quanto cabe no disco antes de armar, direto no registro."""
        try:
            import recorder as rec_mod
        except ImportError:
            return
        try:
            livre = rec_mod.espaco_livre(outdir)
            if livre < 0:
                return
            horas = rec_mod.horas_que_cabem(livre)
            if livre < rec_mod.ESPACO_CRITICO:
                self._log(f"ATENÇÃO: só restam {formata_tamanho(livre)} em disco "
                          f"(~{horas * 60:.0f} min de live). A gravação vai parar "
                          f"quando acabar.")
            elif livre < rec_mod.ESPACO_CONFORTAVEL:
                self._log(f"Aviso: {formata_tamanho(livre)} livres na pasta de saída "
                          f"— cabem cerca de {horas:.1f}h de live.")
        except Exception:  # noqa: BLE001
            pass

    def _conferir_espaco_gravando(self) -> None:
        """Vigia o disco durante a gravação, avisando uma vez só por sessão."""
        if self._espaco_avisado:
            return
        try:
            import recorder as rec_mod
        except ImportError:
            return
        try:
            livre = rec_mod.espaco_livre(self.outdir_var.get().strip())
            if livre < 0 or livre >= rec_mod.ESPACO_CRITICO:
                return
            self._espaco_avisado = True
            minutos = rec_mod.horas_que_cabem(livre) * 60
            self._log(f"ATENÇÃO: o disco está acabando ({formata_tamanho(livre)}, "
                      f"~{minutos:.0f} min). Libere espaço ou pare e salve agora — "
                      f"o que já foi gravado está seguro.")
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------- estado visual

    def _sync_buttons(self) -> None:
        """Deixa o botão com cara de REC: solto, armado ou gravando."""
        if not hasattr(self, "start_btn"):
            return
        if self.host.recording:
            self._disarming = False
            self.start_btn.configure(
                text="●  GRAVANDO",
                bg="#991b1b", activebackground="#7f1d1d",
                relief="sunken", state="disabled", cursor="",
            )
            self.stop_btn.configure(state="normal", cursor="hand2")
        elif self._disarming:
            self.start_btn.configure(
                text="Desarmando...",
                bg="#7f1d1d", relief="sunken", state="disabled", cursor="",
            )
            self.stop_btn.configure(state="disabled", cursor="")
        elif self.host.pending:
            self.start_btn.configure(
                text="●  REC armado  (clique para desarmar)",
                bg="#7f1d1d", activebackground="#991b1b",
                relief="sunken", state="normal", cursor="hand2",
            )
            self.stop_btn.configure(state="disabled", cursor="")
        else:
            self._disarming = False
            self.start_btn.configure(
                text="●  Iniciar Gravação",
                bg="#dc2626", activebackground="#b91c1c",
                relief="raised", state="normal", cursor="hand2",
            )
            self.stop_btn.configure(state="disabled", cursor="")

    def _hover_rec(self, dentro: bool) -> None:
        """Clareia o botão sob o cursor, só quando ele aceita clique."""
        if str(self.start_btn.cget("state")) != "normal":
            return
        if self.host.pending:
            self.start_btn.configure(bg="#991b1b" if dentro else "#7f1d1d")
        else:
            self.start_btn.configure(bg="#ef4444" if dentro else "#dc2626")

    def _apply_state(self, key: str, text: str) -> None:
        """Pinta a faixa inteira com as cores do estado informado."""
        pal = self._tabuleiro.get(key, NEUTRO_ESCURO if self._escuro else NEUTRO)
        self._state_key = key
        self.status_var.set(text)

        for w in self._banner_parts:
            w.configure(bg=pal["bg"])
        self.banner.configure(highlightbackground=pal["border"], highlightcolor=pal["border"])
        self.dot.configure(bg=pal["bg"])
        self.dot.itemconfigure(self.dot_item, fill=pal["dot"])
        self.status_label.configure(bg=pal["bg"], fg=pal["fg"])
        self.detail_label.configure(bg=pal["bg"], fg=pal["fg"])

        # O prefixo do estado vai para o título da janela, como no original:
        # é assim que dá para ver "GRAVANDO" pela barra de tarefas, com o
        # Dinfinity minimizado.
        try:
            self.winfo_toplevel().title(pal["prefix"] + "Dinfinity")
        except tk.TclError:
            pass

        if key != "gravando":
            self.detail_var.set("")
        self._sync_buttons()

    def _pulse(self) -> None:
        """Pisca a bolinha durante a gravação e atualiza tempo/tamanho."""
        pal = self._tabuleiro.get(self._state_key, NEUTRO)
        if self._state_key == "gravando":
            self._blink_on = not self._blink_on
            self.dot.itemconfigure(
                self.dot_item, fill=pal["dot"] if self._blink_on else pal["bg"])
            self._update_detail()
            agora = time.monotonic()
            if agora - self._ultimo_espaco > 60:
                self._ultimo_espaco = agora
                self._conferir_espaco_gravando()
        elif self._blink_on:
            self._blink_on = False
            self.dot.itemconfigure(self.dot_item, fill=pal["dot"])
        self.after(550, self._pulse)

    def _update_detail(self) -> None:
        started = self.host.session_started
        if not started or not self.host.recording:
            self.detail_var.set("")
            return
        tempo = formata_duracao((datetime.now() - started).total_seconds())
        self.detail_var.set(f"{tempo}     {formata_tamanho(self.host.session_size())}")

    def _janela_redimensionada(self, _event=None) -> None:
        """Agrupa muitos eventos de resize numa única atualização do player."""
        if getattr(self, "_resize_preview_id", None):
            self.after_cancel(self._resize_preview_id)
        self._resize_preview_id = self.after(80, self._ajustar_preview)

    def _ajustar_preview(self) -> None:
        self._resize_preview_id = None
        if not hasattr(self, "preview_box") or self.preview_box.winfo_width() < 20:
            return
        margem = 20
        largura_disponivel = max(130, self.preview_box.winfo_width() - margem)
        altura_disponivel = max(180, self.preview_box.winfo_height() - 150)
        largura = min(largura_disponivel, round(altura_disponivel * 9 / 16))
        largura = max(130, largura)
        altura = round(largura * 16 / 9)
        if (abs(self.preview_tela.winfo_width() - largura) > 2 or
                abs(self.preview_tela.winfo_height() - altura) > 2):
            self.preview_tela.configure(width=largura, height=altura)

    # --------------------------------------------------------- prévia live

    def _preview_mudou(self) -> None:
        """Liga/desliga a reprodução extra sem tocar no espaço reservado."""
        if self.preview_var.get():
            self.preview_box.update_idletasks()
            if self.preview_player is None:
                if self._editor_load_error is not None:
                    self.preview_info_var.set("Prévia indisponível neste computador")
                    self.preview_var.set(False)
                    self._persist_recorder()
                    return
                if self._editor_mod is None:
                    # O editor (que carrega a libmpv) ainda está abrindo.
                    self.preview_info_var.set("Abrindo o player...")
                    self.refresh_if_needed()
                    self.after(200, self._preview_mudou)
                    return
                self.preview_player = self._editor_mod.Player(self.preview_tela)
                if not self.preview_player.disponivel:
                    self._log(f"Prévia ao vivo: {self.preview_player.erro}")
                    self.preview_info_var.set("Prévia indisponível neste computador")
                    self.preview_player = None
                    self.preview_var.set(False)
                    return
            self._preview_audio_mudou()
            if self._preview_url:
                self._preview_stream(self._preview_url)
            else:
                self.preview_info_var.set("Aguardando uma gravação")
        else:
            if self.preview_player is not None:
                self.preview_player.parar()
            self._preview_carregada = ""
            self.preview_info_var.set("Prévia desligada")
        self._persist_recorder()

    def _preview_audio_mudou(self) -> None:
        if self.preview_player is not None:
            self.preview_player.audio(bool(self.preview_audio_var.get()),
                                      self.preview_volume_var.get())
        self._persist_recorder()

    def _preview_stream(self, url: str) -> None:
        self._preview_url = url
        if not url:
            if self.preview_player is not None:
                self.preview_player.parar()
            self._preview_carregada = ""
            if self.preview_var.get():
                self.preview_info_var.set("Aguardando uma gravação")
            return
        if not self.preview_var.get():
            return
        if self.preview_player is None:
            self._preview_mudou()
        if self.preview_player is None or url == self._preview_carregada:
            return
        self.preview_info_var.set("Ao vivo — áudio desligado" if not self.preview_audio_var.get()
                                  else "Ao vivo — áudio ligado")
        self.preview_player.carregar(url)
        self.preview_player.audio(bool(self.preview_audio_var.get()),
                                  self.preview_volume_var.get())
        self.preview_player.tocar(True)
        self._preview_carregada = url

    # ---------------------------------------------------------------- fila

    def _drain(self) -> None:
        try:
            while True:
                kind, value = self.host.events.get_nowait()
                if kind == "log":
                    self._log(str(value))
                elif kind == "status":
                    if isinstance(value, tuple):
                        self._apply_state(value[0], value[1])
                    else:
                        self._apply_state("info", str(value))
                elif kind == "error":
                    self._log(f"ERRO: {value}")
                    self._apply_state("erro", str(value)[:70])
                elif kind == "preview":
                    self._preview_stream(str(value))
                elif kind == "done":
                    if getattr(value, "final_path", ""):
                        self._apply_state("concluido", "Gravação salva")
                        self._log_card(value)
                elif kind == "interrompidas":
                    # As partes da sessão que acabou de começar não são
                    # "interrompidas": a varredura roda em thread na abertura e
                    # o REC automático pode gravar por cima dela.
                    ativas = set(self.host.partes_ativas)
                    for item in value:
                        if ativas.intersection(item.partes):
                            continue
                        self._card_resgate(item)
                elif kind == "resgatou":
                    if getattr(value, "final_path", ""):
                        self._apply_state("concluido", "Gravação resgatada")
                        self._log_card(value)
                    self._sync_buttons()
                elif kind == "progresso":
                    if self.editor is not None:
                        try:
                            fracao, texto = value
                            self.editor.andou(float(fracao), str(texto))
                        except (TypeError, ValueError, tk.TclError):
                            pass
                elif kind == "exportou":
                    if self.editor is not None:
                        try:
                            self.editor.exportou(str(value or ""))
                        except tk.TclError:
                            pass
                    if value:
                        self._log(f"Vídeo exportado: {os.path.basename(str(value))}")
                        self._apply_state("concluido", "Vídeo exportado")
                    else:
                        self._log("A exportação não terminou. Veja o registro.")
                elif kind == "finished":
                    self._sync_buttons()
        except queue.Empty:
            pass
        self.after(120, self._drain)

    # ------------------------------------------------------------- registro

    def _log(self, msg: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", f"[{datetime.now():%H:%M:%S}] {msg}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _log_card(self, result) -> None:
        """Insere no registro um cartão com miniatura e atalhos do arquivo."""
        caminho = result.final_path
        if self._escuro:
            card_bg, card_border = CARD_BG_ESCURO, CARD_BORDER_ESCURO
            card_fg, card_muted = CARD_FG_ESCURO, CARD_MUTED_ESCURO
        else:
            card_bg, card_border = CARD_BG, CARD_BORDER
            card_fg, card_muted = "#0f172a", "#64748b"
        card = tk.Frame(self.log, bg=card_bg, highlightthickness=1,
                        highlightbackground=card_border, bd=0)

        if getattr(result, "thumb_path", "") and os.path.exists(result.thumb_path):
            try:
                img = tk.PhotoImage(file=result.thumb_path)
                self._thumbs.append(img)
                tk.Label(card, image=img, bg=card_bg, bd=0).pack(side="left", padx=10, pady=10)
            except tk.TclError:
                pass  # miniatura ilegível: o cartão vale sem ela

        info = tk.Frame(card, bg=card_bg)
        info.pack(side="left", fill="both", expand=True, padx=(2, 10), pady=10)

        tk.Label(
            info, text=os.path.basename(caminho), bg=card_bg, fg=card_fg,
            font=("Segoe UI", 9, "bold"), anchor="w", justify="left", wraplength=330,
        ).pack(anchor="w")

        detalhes = formata_tamanho(getattr(result, "bytes_written", 0))
        if getattr(result, "duration_seconds", 0):
            detalhes += f"   ·   {formata_duracao(result.duration_seconds)}"
        tk.Label(info, text=detalhes, bg=card_bg, fg=card_muted,
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 6))

        acoes = tk.Frame(info, bg=card_bg)
        acoes.pack(anchor="w")
        btn_style = {
            "font": ("Segoe UI", 9),
            "bg": ("#3a3a3a" if self._escuro else "#e2e8f0"),
            "fg": (card_fg if self._escuro else "#0f172a"),
            "bd": 1, "padx": 10, "pady": 3, "cursor": "hand2",
            "activebackground": ("#4a4a4a" if self._escuro else "#cbd5e1"),
        }
        tk.Button(
            acoes, text="▶  Abrir vídeo", command=lambda p=caminho: open_path(p),
            **btn_style,
        ).pack(side="left")
        tk.Button(
            acoes, text="Ver na pasta", command=lambda p=caminho: reveal_in_explorer(p),
            **btn_style,
        ).pack(side="left", padx=8)
        tk.Button(
            acoes, text="✂  Abrir no editor",
            command=lambda p=caminho: self._abrir_no_editor(p),
            font=("Segoe UI", 9),
            bg=("#0e3d27" if self._escuro else "#dcfce7"),
            fg=("#86efac" if self._escuro else "#14532d"),
            bd=1, padx=10, pady=3, cursor="hand2",
        ).pack(side="left")

        self.log.configure(state="normal")
        self.log.insert("end", "\n")
        self.log.window_create("end", window=card)
        self.log.insert("end", "\n\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _abrir_no_editor(self, caminho: str) -> None:
        """Manda a gravação recém-terminada direto para a aba de edição."""
        if self.editor is not None:
            self.abas.select(self.editor)
            try:
                self.editor.abrir(caminho)
            except Exception as exc:  # noqa: BLE001
                logger.log("error", f"[EDITOR] Não abriu o vídeo: {exc}")

    # ---------------------------------------------------------------- resgate

    def _procurar_interrompidas(self) -> None:
        """Varre a pasta de saída atrás de gravações que ficaram pela metade."""
        pasta = self.outdir_var.get().strip()

        def varrer() -> None:
            try:
                import recorder as rec_mod
                achadas = rec_mod.procurar_interrompidas(pasta)
            except Exception as e:  # noqa: BLE001
                self.host.events.put(("log", f"Não consegui procurar gravações "
                                             f"interrompidas: {e}"))
                return
            if achadas:
                self.host.events.put(("interrompidas", achadas))

        threading.Thread(target=varrer, daemon=True).start()

    def _card_resgate(self, item) -> None:
        """Cartão discreto: se a pessoa ignorar, ele volta na próxima abertura."""
        card = tk.Frame(self.log, bg="#fef9c3", highlightthickness=1,
                        highlightbackground="#fde047", bd=0)
        info = tk.Frame(card, bg="#fef9c3")
        info.pack(side="left", fill="both", expand=True, padx=12, pady=10)

        tk.Label(info, text="Gravação interrompida", bg="#fef9c3", fg="#713f12",
                 font=("Segoe UI", 9, "bold"), anchor="w").pack(anchor="w")
        tk.Label(info, text=item.base, bg="#fef9c3", fg="#0f172a",
                 font=("Segoe UI", 9), anchor="w", justify="left",
                 wraplength=330).pack(anchor="w", pady=(2, 0))

        partes: list[str] = []
        if item.quando:
            partes.append(f"{item.quando:%d/%m às %H:%M}")
        if item.bytes_total:
            partes.append(formata_tamanho(item.bytes_total))
        if len(item.partes) > 1:
            partes.append(f"{len(item.partes)} partes")
        if item.jsonl:
            partes.append("presentes e chat")
        tk.Label(info, text="   ·   ".join(partes), bg="#fef9c3", fg="#854d0e",
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 6))

        botao = tk.Button(
            info, text="Recuperar", font=("Segoe UI", 9), bg="#facc15",
            fg="#422006", bd=1, padx=12, pady=3, cursor="hand2",
        )
        botao.configure(command=lambda: self._resgatar(item, botao))
        botao.pack(anchor="w")

        self.log.configure(state="normal")
        self.log.insert("end", "\n")
        self.log.window_create("end", window=card)
        self.log.insert("end", "\n\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _resgatar(self, item, botao: tk.Button) -> None:
        if self.host.recording:
            messagebox.showinfo(
                "Gravação em andamento",
                "Há uma live sendo gravada agora. O resgate disputaria disco e "
                "processador com ela - tente de novo quando terminar.")
            return
        botao.configure(state="disabled", text="Recuperando...")

        def trabalhar() -> None:
            emit = lambda k, v="": self.host.events.put((k, v))  # noqa: E731
            try:
                import recorder as rec_mod
                resultado = rec_mod.recuperar(item, emit)
            except Exception as e:  # noqa: BLE001
                self.host.events.put(("log", f"O resgate falhou: {e}"))
                self.host.events.put(("resgatou", type("R", (), {"final_path": ""})()))
                return
            self.host.events.put(("resgatou", resultado))

        threading.Thread(target=trabalhar, daemon=True).start()

    # ---------------------------------------------------------------- saída

    def _on_close_recorder(self):
        # Devolver False segura o fechamento do Dinfinity inteiro: fechar no
        # meio de uma live encerra a gravação, e isso o original perguntava.
        if self.host.recording:
            if not messagebox.askyesno(
                    "Gravação em andamento",
                    "Uma live está sendo gravada agora.\n\n"
                    "Fechar agora encerra a gravação e salva o que já foi "
                    "baixado. Continuar?"):
                return False
        self._persist_recorder()
        self.host.shutdown()
        if self.preview_player is not None:
            try:
                self.preview_player.encerrar()
            except Exception:  # noqa: BLE001
                pass
            self.preview_player = None
        if self.editor is not None:
            try:
                self.editor.encerrar()
            except Exception:  # noqa: BLE001
                pass
