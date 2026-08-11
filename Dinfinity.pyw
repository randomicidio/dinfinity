# -*- coding: utf-8 -*-
"""Dinfinity - sua suíte de interação com o TikTok Live.

Reúne em um único programa:
  - Monitor de live (TikTokLive) com reações/ações ativáveis (impressão de
    agradecimento, triggers para Streamer.bot, TTS, log de chat);
  - Texto para Fala com teste de voz;
  - Chat automático (mensagens periódicas no chat flutuante do Live Studio);
  - Jogo de revelar imagens com servidor local para o OBS.

O programa abre sem pedir Administrador. Só o Chat Automático precisa disso
(para controlar o mouse do TikTok LIVE Studio) e pede na hora de ligar — ver
core/admin.py. Quem escolheu a abertura automática como Administrador passa
por `_redirecionar_para_tarefa` aqui embaixo.
"""
import ctypes
import sys
from pathlib import Path


def _elevar_no_arranque():
    """Sobe como Administrador agora, se for o caso. True = esta cópia sai.

    Aqui é o único lugar em que elevar não custa nada: nada foi aberto ainda,
    então não há live conectada para cair, gravação para interromper nem log
    para perder. Dois caminhos, nesta ordem:

      1. a Tarefa Agendada, que eleva sem o Windows perguntar nada;
      2. a preferência "pedir ao abrir", que mostra o UAC de sempre.
    """
    from core import admin

    if admin.ARG_VIA_TAREFA in sys.argv or admin.e_admin():
        return False                      # já veio pela tarefa, ou já é admin
    if admin.tarefa_valida():
        return admin.abrir_pela_tarefa()

    from core.config import load_config
    try:
        pedir = bool(load_config()["app"].get("abrir_como_admin", False))
    except Exception:                     # noqa: BLE001 — config quebrado não trava o programa
        pedir = False
    if not pedir:
        return False
    # Recusar o UAC não pode impedir de usar o resto: o programa segue sem
    # privilégio, e só o Chat Automático fica indisponível.
    return admin.relancar_como_admin()


def main():
    try:
        if not ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

    from core import instancia
    # Segunda checagem, agora reservando a vaga: cobre o caso de duas aberturas
    # quase simultâneas, que passariam as duas pela conferência lá de baixo.
    if not instancia.marcar():
        instancia.focar()
        return

    # Identidade própria na barra de tarefas do Windows. Precisa vir antes de
    # a janela nascer: depois disso ela já foi registrada sob a identidade do
    # interpretador, e o ícone escolhido não aparece no botão da barra.
    from core import icone
    icone.registrar_no_windows()

    import customtkinter as ctk  # noqa: F401 (aplicar tema no App)
    from gui.app import App

    app = App()
    app.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from core import instancia as _instancia
    if _instancia.outra_ja_aberta():
        _instancia.focar()
        sys.exit(0)
    # Antes de qualquer janela: se a abertura como Administrador está ligada,
    # quem aparece para o usuário é a cópia elevada, não esta.
    if _elevar_no_arranque():
        sys.exit(0)
    main()
