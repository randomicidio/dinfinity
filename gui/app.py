# -*- coding: utf-8 -*-
"""Janela principal do Dinfinity: sidebar de navegação + área de conteúdo com
as abas das seções."""
import sys

import customtkinter as ctk

from core import icone, logger
from core.config import ensure_dirs, load_config, save_config
from core.instancia import liberar as liberar_instancia
from core.monitor import MonitorEngine
from core.obs_config import aplicar as aplicar_obs
from core.reactions import migrar as migrar_reacoes
from core.recorder_host import RecorderHost
from core.theme import apply_ttk_theme
from core.tts import TTSEngine

from gui.tab_live import LiveTab
from gui.tab_reactions import ReactionsTab
from gui.tab_tts import TTSTab
from gui.tab_chat import ChatTab
from gui.tab_game import GameTab
from gui.tab_recorder import RecorderTab
from gui.tab_settings import SettingsTab

NAV = [
    ("Conexão", "Conexão"),
    ("Reações", "Reações"),
    ("Texto para Fala", "TTS"),
    ("Chat Automático", "Chat"),
    ("Jogo Perfil", "Jogo"),
    ("Gravador", "Gravador"),
    ("Configurações", "Config"),
]

STATES = {
    "off": ("#8a8f98", "Parado"),
    "standby": ("#f4c542", "Standby"),
    "connecting": ("#f4a742", "Conectando..."),
    "connected": ("#4caf50", "Conectado"),
    "error": ("#ff6b6b", "Erro"),
}


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.config = load_config()
        # Reações do formato antigo (um "type" fixo por reação) viram
        # gatilho + lista de ações. Idempotente: quem já está no formato novo
        # passa intacto.
        self.config["reactions"] = migrar_reacoes(self.config.get("reactions", []))
        ensure_dirs(self.config)
        # As saídas de áudio mudaram de formato junto com a troca do VLC pela
        # libmpv. A conversão é feita depois da janela abrir (ver _migrar_audio):
        # subir a libmpv aqui atrasaria a abertura do programa.

        ctk.set_appearance_mode(self.config["app"].get("appearance", "dark"))
        ctk.set_default_color_theme(self.config["app"].get("color_theme", "blue"))
        apply_ttk_theme(self.config["app"].get("appearance", "dark"))

        self.title("Dinfinity")
        self.geometry("1280x820")
        self.minsize(1024, 680)

        # Identidade própria na barra de tarefas: sem isso o Windows agrupa a
        # janela sob o ícone do python.exe e o nosso não aparece no botão.
        icone.registrar_no_windows()
        self._estado_icone = None
        self._aplicar_icone()

        # O OBS instalado é quem sabe a porta e a senha do websocket dele; ler
        # isso evita a configuração manual (e a porta 4444 x 4455, que é onde
        # quase todo mundo tropeça).
        mudou, achado = aplicar_obs(self.config)
        self._obs_detectado = achado

        self.tts = TTSEngine(self.config)
        self.engine = MonitorEngine(self.config, self.tts)
        self.engine.start()
        if achado and achado.get("habilitado"):
            self.engine.conectar_obs()
        if mudou:
            try:
                save_config(self.config)
            except Exception:
                pass
        self.recorder_host = RecorderHost(self)

        self._current_state = "off"
        self._log_widget = None
        self._status_listeners = []
        self._close_hooks = []
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self._build_sidebar()
        self._build_content()

        # Reaberto pelo botão do Chat Automático: volta direto para a aba de
        # onde a elevação foi pedida. O caminho do UAC avisa por argumento; o
        # da Tarefa Agendada, por bilhete (o schtasks não passa argumentos).
        from core.admin import ARG_CHAT, consumir_abertura_no_chat
        voltar_pro_chat = ARG_CHAT in sys.argv or consumir_abertura_no_chat()
        self.show_tab("Chat" if voltar_pro_chat else "Conexão")

        self.after(200, self._poll_logs)
        self.after(300, self._poll_status)
        self.after(400, self._migrar_audio)
        self.after(500, self._instalar_tarefa_se_pedido)

        if self.config["live"].get("auto_connect"):
            self.after(600, self._auto_connect)

    def _migrar_audio(self):
        """Converte as saídas de áudio salvas no formato do VLC, em thread."""
        import threading

        from core.audio import migrar_dispositivos_salvos

        def trabalho():
            try:
                if migrar_dispositivos_salvos(self.config):
                    save_config(self.config)
            except Exception as exc:  # noqa: BLE001
                logger.log("error", f"[ÁUDIO] Falha ao converter as saídas salvas: {exc}")

        threading.Thread(target=trabalho, daemon=True, name="migrar-audio").start()

    def _instalar_tarefa_se_pedido(self):
        """Cria a Tarefa Agendada quando esta cópia subiu elevada para isso.

        Só um processo Administrador consegue registrá-la, e é justamente o que
        acabou de nascer: quem pediu ficou na cópia anterior, que já fechou.
        """
        from core.admin import ARG_INSTALAR, criar_tarefa

        if ARG_INSTALAR not in sys.argv:
            return
        if criar_tarefa():
            logger.log("system", "[ADMIN] Da próxima vez o Dinfinity já abre "
                                 "como Administrador, sem perguntar nada.")

    def _auto_connect(self):
        logger.log("system", "Conexão automática: iniciando monitor.")
        self.engine.start_monitoring()

    # ---------------- layout ----------------
    def _build_sidebar(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkFrame(self, width=220, corner_radius=0, fg_color=("#e8e8e8", "#1b1b1b"))
        sidebar.grid(row=0, column=0, sticky="nsw")
        sidebar.grid_propagate(False)

        ctk.CTkLabel(
            sidebar, text="Dinfinity", font=ctk.CTkFont("Segoe UI", 26, "bold"),
            text_color=("#c792ea", "#c792ea"),
        ).pack(pady=(24, 2))
        ctk.CTkLabel(
            sidebar, text="TikTok Live Suite", font=ctk.CTkFont("Segoe UI", 12),
            text_color=("#888888", "#888888"),
        ).pack(pady=(0, 18))

        self.nav_buttons = {}
        for i, (_label, key) in enumerate(NAV):
            btn = ctk.CTkButton(
                sidebar, text=_label, command=lambda k=key: self.show_tab(k),
                anchor="w", height=40, corner_radius=8,
                font=ctk.CTkFont("Segoe UI", 14),
                fg_color="transparent", text_color=("#3b3b3b", "#dcdcdc"),
                hover_color=("#d8d8d8", "#2a2a2a"),
            )
            btn.pack(fill="x", padx=12, pady=3)
            self.nav_buttons[key] = btn

        status_box = ctk.CTkFrame(sidebar, fg_color="transparent")
        status_box.pack(side="bottom", fill="x", padx=14, pady=(8, 14))
        self.status_dot = ctk.CTkLabel(status_box, text="●",
                                       font=ctk.CTkFont("Segoe UI", 14),
                                       text_color=STATES["off"][0])
        self.status_dot.pack(side="left", padx=(0, 6))
        self.status_label = ctk.CTkLabel(
            status_box, text="Parado", font=ctk.CTkFont("Segoe UI", 12),
            anchor="w", justify="left", wraplength=170,
        )
        self.status_label.pack(side="left", fill="x", expand=True)

    def _build_content(self):
        content = ctk.CTkFrame(self, corner_radius=0)
        content.grid(row=0, column=1, sticky="nsew")
        # Sem peso, cada aba fica no tamanho "pedido" dela (e sobra espaço ou
        # falta espaço conforme o conteúdo). Com peso, a aba ocupa a área toda.
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)

        self.tabs = {}
        factories = {
            "Conexão": LiveTab,
            "Reações": ReactionsTab,
            "TTS": TTSTab,
            "Chat": ChatTab,
            "Jogo": GameTab,
            "Gravador": RecorderTab,
            "Config": SettingsTab,
        }
        for key, cls in factories.items():
            frame = cls(content, self)
            frame.grid(row=0, column=0, sticky="nsew")
            frame.grid_remove()
            self.tabs[key] = frame

    def show_tab(self, key):
        for k, frame in self.tabs.items():
            if k == key:
                frame.grid()
                frame.lift()
                frame.refresh_if_needed()
            else:
                frame.grid_remove()
        for _key, btn in self.nav_buttons.items():
            active = (_key == key)
            btn.configure(
                fg_color=("#c8a2e8", "#3a2b4d") if active else "transparent",
                text_color=("#1a1a1a", "#ffffff") if active else ("#3b3b3b", "#dcdcdc"),
            )

    # ---------------- polling ----------------
    def _poll_logs(self):
        items = logger.drain()
        if items and self._log_widget is not None:
            try:
                widget = self._log_widget
                for _ts, level, _msg in items:
                    try:
                        widget.tag_config(level, foreground=logger.LEVEL_COLORS.get(level, "white"))
                    except Exception:
                        pass
                widget.configure(state="normal")
                for timestamp, level, message in items:
                    # Duas etiquetas: o nível pinta a linha, a categoria decide
                    # se ela fica visível (ver aplicar_filtros_log).
                    widget.insert("end", f"[{timestamp}] {message}\n",
                                  (level, logger.categoria(level)))
                widget.see("end")
                widget.configure(state="disabled")
            except Exception:
                pass
        self.after(200, self._poll_logs)

    def register_log_widget(self, widget):
        self._log_widget = widget
        self.aplicar_filtros_log()

    def aplicar_filtros_log(self):
        """Esconde/mostra as categorias desmarcadas, inclusive o que já está
        escrito: o `elide` da etiqueta vale para a linha inteira, então marcar
        de volta traz o histórico junto em vez de só valer dali para frente."""
        if self._log_widget is None:
            return
        filtros = self.config.setdefault("log", {})
        for chave in logger.CATEGORIAS:
            try:
                self._log_widget.tag_config(chave, elide=not filtros.get(chave, True))
            except Exception:
                pass

    def _poll_status(self):
        for state, text in self.engine.drain_status():
            color, label = STATES.get(state, STATES["off"])
            self.status_dot.configure(text_color=color)
            self.status_label.configure(text=f"{label}\n{text}")
            for listener in self._status_listeners:
                try:
                    listener(state, text)
                except Exception:
                    pass
            self._current_state = state
        # Fora do laço: a gravação começa e termina sozinha, sem passar pela
        # fila de status da live.
        self._aplicar_icone()
        self.after(300, self._poll_status)

    def _estado_do_icone(self):
        """Gravar ganha do resto: é o estado em que perder o programa de vista
        custa mais caro.

        Tolera ser chamado cedo: o ícone é posto assim que a janela ganha
        título, antes de o motor e o gravador existirem.
        """
        try:
            if self.recorder_host.recording:
                return "gravando"
        except Exception:  # noqa: BLE001 — o gravador pode nem ter carregado
            pass
        return getattr(self, "_current_state", "off")

    def _aplicar_icone(self):
        estado = self._estado_do_icone()
        if estado == self._estado_icone:
            return
        self._estado_icone = estado
        icone.aplicar(self, estado)

    def add_status_listener(self, fn):
        """Registra quem quer saber do estado da live (aba Conexão, Gravador)."""
        if fn not in self._status_listeners:
            self._status_listeners.append(fn)

    @property
    def live_state(self):
        return self._current_state

    def add_close_hook(self, fn):
        self._close_hooks.append(fn)

    def on_close(self):
        # Um gancho pode devolver False para segurar o fechamento (o gravador
        # pergunta antes de encerrar uma live que está sendo gravada).
        for hook in self._close_hooks:
            try:
                if hook() is False:
                    return
            except Exception:
                pass
        try:
            save_config(self.config)
        except Exception:
            pass
        try:
            self.recorder_host.shutdown()
        except Exception:
            pass
        try:
            self.engine.stop()
        except Exception:
            pass
        try:
            liberar_instancia()
        except Exception:
            pass
        self.destroy()
