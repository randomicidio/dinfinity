# -*- coding: utf-8 -*-
"""Aba Jogo Perfil: o quebra-cabeça de revelar imagens, embutido no Dinfinity.
O servidor local continua servindo o frame para o OBS."""
import customtkinter as ctk

from core.config import save_config
from puzzle.puzzle import PuzzleWidget


class GameTab(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.widget = PuzzleWidget(
            self,
            app.config["puzzle"],
            on_change=lambda: save_config(app.config),
        )
        self.widget.pack(fill="both", expand=True, padx=10, pady=10)

    def refresh_if_needed(self):
        pass
