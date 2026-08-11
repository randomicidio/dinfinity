# -*- coding: utf-8 -*-
"""Aba Texto para Fala: ativar/desativar TTS, escolher voz, ajustar velocidade/
volume e testar a voz pelo próprio programa."""
import queue
import threading
import tkinter as tk

import customtkinter as ctk

from core import logger
from core.config import save_config
from core.tts import list_voices


class TTSTab(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.voices = []
        self.voice_display = {}
        # As buscas (vozes do edge-tts, saídas do VLC) rodam em thread e
        # devolvem por aqui: chamar after() de fora da thread do Tk é o tipo de
        # coisa que funciona até o dia em que a janela fecha no meio.
        self._respostas = queue.Queue()
        self._build()
        self.after(80, self._drenar)
        self.refresh_voices()

    def _drenar(self):
        try:
            while True:
                funcao, dados = self._respostas.get_nowait()
                try:
                    funcao(dados)
                except tk.TclError:
                    pass
        except queue.Empty:
            pass
        self.after(80, self._drenar)

    def _build(self):
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text="Texto para Fala (TTS)",
                     font=ctk.CTkFont("Segoe UI", 22, "bold")
                     ).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 4))
        ctk.CTkLabel(self, text="As reações do tipo “Ler mensagem em voz alta” usam o TTS. "
                                "Ative ou desative o motor aqui e teste a voz antes da live.",
                     font=ctk.CTkFont("Segoe UI", 12), text_color=("#7a7a7a", "#9a9a9a")
                     ).grid(row=1, column=0, sticky="w", padx=16, pady=(0, 12))

        card = ctk.CTkFrame(self)
        card.grid(row=2, column=0, sticky="we", padx=16, pady=(0, 12))
        card.grid_columnconfigure(1, weight=1)

        self.enabled_var = ctk.BooleanVar(value=bool(self.app.config["tts"].get("enabled", True)))
        ctk.CTkLabel(card, text="TTS ativo", font=ctk.CTkFont("Segoe UI", 14, "bold")
                     ).grid(row=0, column=0, padx=(16, 10), pady=14, sticky="w")
        ctk.CTkSwitch(card, text="", variable=self.enabled_var, command=self._on_enabled
                      ).grid(row=0, column=1, sticky="w", pady=14)

        ctk.CTkLabel(card, text="Voz", anchor="w", font=ctk.CTkFont("Segoe UI", 13)
                     ).grid(row=1, column=0, padx=(16, 10), pady=6, sticky="w")
        voice_row = ctk.CTkFrame(card, fg_color="transparent")
        voice_row.grid(row=1, column=1, sticky="we", pady=6)
        voice_row.grid_columnconfigure(0, weight=1)
        self.voice_var = ctk.StringVar(value=self.app.config["tts"].get("voice", ""))
        self.voice_menu = ctk.CTkOptionMenu(voice_row, values=[], variable=self.voice_var,
                                            command=lambda _v: self._on_voice())
        self.voice_menu.grid(row=0, column=0, sticky="we", padx=(0, 6))
        ctk.CTkButton(voice_row, text="Atualizar vozes", width=130, command=self.refresh_voices
                      ).grid(row=0, column=1)

        ctk.CTkLabel(card, text="Filtro de idioma", font=ctk.CTkFont("Segoe UI", 13)
                     ).grid(row=2, column=0, padx=(16, 10), pady=6, sticky="w")
        self.filter_var = ctk.StringVar(value="pt-BR")
        ctk.CTkOptionMenu(card, values=["pt-BR", "pt-PT", "es", "en", "Todas"],
                          variable=self.filter_var, width=140,
                          command=lambda _v: self.refresh_voices()
                          ).grid(row=2, column=1, sticky="w", pady=6)

        ctk.CTkLabel(card, text="Velocidade", font=ctk.CTkFont("Segoe UI", 13)
                     ).grid(row=3, column=0, padx=(16, 10), pady=6, sticky="w")
        self.rate_var = ctk.StringVar(value=self.app.config["tts"].get("rate", "+0%"))
        rate_row = ctk.CTkFrame(card, fg_color="transparent")
        rate_row.grid(row=3, column=1, sticky="we", pady=6)
        rate_row.grid_columnconfigure(0, weight=1)
        ctk.CTkEntry(rate_row, textvariable=self.rate_var, width=110).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(rate_row, text="Ex.: -20% (lento), +10% (rápido)",
                     font=ctk.CTkFont("Segoe UI", 11), text_color=("#7a7a7a", "#9a9a9a")
                     ).grid(row=0, column=1, padx=(10, 0), sticky="w")

        ctk.CTkLabel(card, text="Volume", font=ctk.CTkFont("Segoe UI", 13)
                     ).grid(row=4, column=0, padx=(16, 10), pady=6, sticky="w")
        vol_row = ctk.CTkFrame(card, fg_color="transparent")
        vol_row.grid(row=4, column=1, sticky="we", pady=6)
        self.player_vol_var = ctk.IntVar(value=int(self.app.config["tts"].get("player_volume", 100)))
        ctk.CTkSlider(vol_row, from_=0, to=120, number_of_steps=120,
                      variable=self.player_vol_var, width=300,
                      command=lambda _v: self._on_player_vol()
                      ).grid(row=0, column=0, sticky="w")
        self.vol_label = ctk.CTkLabel(vol_row, text=f"{self.player_vol_var.get()}%",
                                      width=48, anchor="w",
                                      font=ctk.CTkFont("Segoe UI", 13))
        self.vol_label.grid(row=0, column=1, padx=(10, 0), sticky="w")

        ctk.CTkLabel(card, text="Sair pelo dispositivo", font=ctk.CTkFont("Segoe UI", 13)
                     ).grid(row=5, column=0, padx=(16, 10), pady=(6, 14), sticky="w")
        self._device_id = str(self.app.config["tts"].get("device", "") or "")
        inicial = (self.app.config["tts"].get("device_nome")
                   or ("Padrão do Windows" if not self._device_id else "(carregando...)"))
        self.device_var = ctk.StringVar(value=inicial)
        self.device_menu = ctk.CTkOptionMenu(card, values=[inicial], variable=self.device_var,
                                             width=340, command=self._on_device)
        self.device_menu.grid(row=5, column=1, sticky="w", pady=(6, 14))
        # Listar as saídas sobe uma instância da libmpv; em thread para a aba
        # não travar enquanto isso.
        threading.Thread(target=self._load_devices, daemon=True).start()

        ctk.CTkLabel(self, text="Testar voz", font=ctk.CTkFont("Segoe UI", 16, "bold")
                     ).grid(row=3, column=0, sticky="w", padx=16, pady=(4, 6))

        test_card = ctk.CTkFrame(self)
        test_card.grid(row=4, column=0, sticky="we", padx=16, pady=(0, 12))
        test_card.grid_columnconfigure(0, weight=1)

        self.test_var = ctk.StringVar(value="Olá, galera! Este é o teste de voz do Dinfinity.")
        ctk.CTkEntry(test_card, textvariable=self.test_var).grid(
            row=0, column=0, sticky="we", padx=(14, 8), pady=14)
        ctk.CTkButton(test_card, text="Testar voz", width=130, command=self.test_voice,
                      fg_color="#4caf50", hover_color="#3d8b40"
                      ).grid(row=0, column=1, padx=(0, 14), pady=14)

        self.status_label = ctk.CTkLabel(self, text="", font=ctk.CTkFont("Segoe UI", 12),
                                         text_color=("#7a7a7a", "#9a9a9a"))
        self.status_label.grid(row=5, column=0, sticky="w", padx=16)

    # ---------------- ações ----------------
    def _on_enabled(self):
        self.app.config["tts"]["enabled"] = self.enabled_var.get()
        save_config(self.app.config)
        logger.log("system", f"TTS {'ativado' if self.enabled_var.get() else 'desativado'}.")

    def _on_voice(self):
        # O menu mostra rótulos ("pt-BR-X — Feminino"), mas o config guarda o
        # ShortName real, que é o que o edge-tts aceita.
        self.app.config["tts"]["voice"] = self._shortname(self.voice_var.get())
        save_config(self.app.config)

    def _shortname(self, label):
        mapping = getattr(self, "voice_display", {}) or {}
        return mapping.get(label) or label

    def _on_player_vol(self):
        valor = int(self.player_vol_var.get())
        self.vol_label.configure(text=f"{valor}%")
        self.app.config["tts"]["player_volume"] = valor
        save_config(self.app.config)

    # ---------------- saída de áudio ----------------
    def _load_devices(self):
        from core.audio import listar_dispositivos, migrar_dispositivo
        dispositivos = listar_dispositivos()
        # A saída salva pode estar no formato antigo (VLC). A conversão é feita
        # aqui, com a lista em mãos, para quem já usava um cabo virtual não
        # perder o ajuste ao atualizar o programa.
        novo, mudou = migrar_dispositivo(self._device_id,
                                         self.app.config["tts"].get("device_nome", ""))
        self._respostas.put((self._apply_devices, (dispositivos, novo, mudou)))

    def _apply_devices(self, dados):
        dispositivos, novo, mudou = dados
        nomes = [d["nome"] for d in dispositivos or []]
        self._device_por_nome = {d["nome"]: d["id"] for d in dispositivos or []}
        self.device_menu.configure(values=nomes)

        if mudou:
            from core.audio import PADRAO
            if novo == PADRAO and self._device_id:
                # O aparelho sumiu de vez (fone desconectado, driver removido):
                # volta ao padrão em vez de falhar calado na hora de falar.
                logger.log("warning", "[TTS] A saída de áudio escolhida não existe mais; "
                                      "voltando ao padrão do Windows.")
            self._device_id = novo
            self.app.config["tts"]["device"] = novo
            self.app.config["tts"]["device_nome"] = next(
                (d["nome"] for d in dispositivos if d["id"] == novo), "")
            save_config(self.app.config)

        for d in dispositivos or []:
            if d["id"] == self._device_id:
                self.device_var.set(d["nome"])
                return
        if nomes:
            self.device_var.set(nomes[0])

    def _on_device(self, nome):
        self._device_id = getattr(self, "_device_por_nome", {}).get(nome, "")
        self.app.config["tts"]["device"] = self._device_id
        self.app.config["tts"]["device_nome"] = nome
        save_config(self.app.config)
        logger.log("system", f"[TTS] Voz sairá por: {nome}")

    def test_voice(self):
        text = self.test_var.get().strip()
        if not text:
            text = "Teste de voz do Dinfinity."
        self.app.config["tts"]["voice"] = self._shortname(self.voice_var.get())
        self.app.config["tts"]["rate"] = self.rate_var.get().strip() or "+0%"
        self.app.config["tts"]["player_volume"] = int(self.player_vol_var.get())
        save_config(self.app.config)
        self.status_label.configure(text="Enviando para o TTS... (pode levar alguns segundos)")
        self.app.tts.speak(text)

    def refresh_voices(self):
        filter_ = self.filter_var.get()
        self.status_label.configure(text="Buscando vozes...")
        threading.Thread(target=self._load_voices, args=(filter_,), daemon=True).start()

    def _load_voices(self, filter_):
        raw = list_voices("" if filter_ == "Todas" else filter_)
        self.voices = sorted(raw, key=lambda v: v["ShortName"])
        display = []
        mapping = {}
        for v in self.voices:
            label = f"{v['ShortName']} — {'Feminino' if v['Gender'] == 'Female' else 'Masculino' if v['Gender'] == 'Male' else v['Gender']}"
            display.append(label)
            mapping[label] = v["ShortName"]
        self._respostas.put((lambda par: self._apply_voices(*par), (display, mapping)))

    def _apply_voices(self, display, mapping):
        self.voice_display = mapping
        current = self.app.config["tts"].get("voice", "")
        self.voice_menu.configure(values=display)
        # Suporta config legado que guardou o rótulo ("... — Masculino") em vez
        # do ShortName: converte na hora.
        if current not in mapping.values():
            for label, short in mapping.items():
                if label.startswith(current) or current.startswith(label.split(" —")[0]):
                    current = short
                    break
        if current in mapping.values():
            for label, short in mapping.items():
                if short == current:
                    self.voice_var.set(label)
                    break
        elif display:
            self.voice_var.set(display[0])
        self.status_label.configure(text=f"{len(display)} voz(es) disponíveis.")

    def refresh_if_needed(self):
        pass
