# -*- coding: utf-8 -*-
"""Serviço de gravação em segundo plano.

Une o MonitorEngine (fonte única de verdade sobre a live) ao motor de
gravação do RD, copiado para dentro do Dinfinity em rd/. O App cria o host
no início; ele assina os eventos de live do monitor e grava conforme o
config, mesmo que a aba Gravador nunca seja aberta e seguindo pela troca de
seções.
"""
import os
import queue
import sys
import threading
import time

from core import logger

RD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rd")


class RecorderHost:
    def __init__(self, app):
        self.app = app
        self.events = queue.Queue()   # (kind, value) vindos do motor
        self._recorder = None
        self._lock = threading.Lock()
        self._loading = False
        self._load_error = None
        self._start_pending = False

        self._manual_armed = False
        # Com keep_waiting=False, o REC automático grava uma única live por
        # "armo": depois de uma sessão salva ele não liga de novo por conta
        # própria (como o RD fazia ao passar wait_for_live ao armar).
        self._sessao_fechada_no_armo = False

        engine = app.engine
        engine.on_live_started(self._on_live_started)
        engine.on_live_ended(self._on_live_ended)

    # ------------------------------------------------------------ carregamento

    @property
    def auto_record(self):
        return bool(self.app.config["recorder"].get("auto_rec", False))

    @property
    def keep_waiting(self):
        return bool(self.app.config["recorder"].get("keep_waiting", True))

    def ensure_loaded(self):
        """Carrega o motor de gravação em thread, uma única vez."""
        with self._lock:
            if self._recorder is not None or self._loading or self._load_error:
                return
            self._loading = True
        threading.Thread(target=self._load, daemon=True, name="recorder-load").start()

    def _load(self):
        try:
            if RD_DIR not in sys.path:
                sys.path.insert(0, RD_DIR)
            import recorder as rd_recorder  # noqa: N813
            self._recorder = rd_recorder.Recorder(self._emit)
            self._recorder.registrar_presentes = self.auto_record_presentes()
        except Exception as exc:  # noqa: BLE001
            self._load_error = exc
            logger.log("error", f"[GRAVADOR] Não foi possível carregar o motor de gravação: {exc}")
        finally:
            with self._lock:
                self._loading = False
            if self._start_pending:
                self._start_pending = False
                self._do_start()

    def auto_record_presentes(self) -> bool:
        return bool(self.app.config["recorder"].get("registrar_presentes", True))

    @property
    def loaded(self) -> bool:
        return self._recorder is not None

    @property
    def load_error(self):
        return self._load_error

    # ------------------------------------------------------------ estado

    @property
    def recording(self) -> bool:
        return self._recorder is not None and self._recorder.recording

    @property
    def active(self) -> bool:
        return self._recorder is not None and self._recorder.active

    @property
    def armed(self) -> bool:
        return self.auto_record or self._manual_armed

    @property
    def pending(self) -> bool:
        """Verdadeiro se a próxima live detectada será gravada.

        Difere de `armed` quando o usuário desarmou: o desarme bloqueia a
        vigília até um novo armar, mesmo com o REC automático ligado.
        """
        return self.armed and not self._sessao_fechada_no_armo

    @property
    def manual_armed(self) -> bool:
        return self._manual_armed

    @property
    def partes_ativas(self) -> list:
        """Partes .ts que a sessão atual está escrevendo agora."""
        if self._recorder is None:
            return []
        try:
            return list(self._recorder.partes_ativas)
        except Exception:  # noqa: BLE001
            return []

    @property
    def session_started(self):
        return self._recorder.session_started if self._recorder is not None else None

    def session_size(self) -> int:
        if self._recorder is not None:
            try:
                return int(self._recorder.session_size())
            except Exception:  # noqa: BLE001
                pass
        return 0

    # ------------------------------------------------------------- eventos

    def _on_live_started(self):
        """Chamado pelo monitor quando uma live é detectada (thread do loop)."""
        # A prévia ao vivo segue a URL da transmissão mesmo sem REC armado,
        # como o "Verificar agora" fazia no original.
        self._resolve_preview()
        if not self.pending:
            return
        self.ensure_loaded()
        if self._recorder is None:
            self._start_pending = True
            return
        self._do_start()

    def _on_live_ended(self):
        """O próprio motor detecta o fim da live e finaliza/salva sozinho."""
        self.events.put(("preview", ""))

    def _resolve_preview(self):
        """Descobre a URL da live em segundo plano e alimenta a prévia."""
        def trabalhar():
            try:
                if self._recorder is not None and self._recorder.recording:
                    return
                tiktok_api = import_rd("tiktok_api")
                username = self.app.config["live"].get("username", "")
                cookie = self.app.config["recorder"].get("cookie", "")
                info = tiktok_api.resolve(username, tiktok_api.make_session(cookie))
                if info.is_live:
                    opcao = info.pick("origin")
                    if opcao:
                        self.events.put(("preview", opcao.best_url))
                        return
                self.events.put(("preview", ""))
            except Exception as exc:  # noqa: BLE001
                logger.log("error", f"[PRÉVIA] Não deu para resolver a live: {exc}")
                self.events.put(("preview", ""))

        threading.Thread(target=trabalhar, daemon=True, name="preview-resolve").start()

    # ------------------------------------------------------------ controles

    def arm_manual(self):
        """Arma a gravação manual (REC). Grava na próxima live ou já, se no ar."""
        self._manual_armed = True
        self._sessao_fechada_no_armo = False
        self.events.put(("status", ("aguardando", "Verificando...")))
        if self.app.engine.live_active:
            self._on_live_started()

    def disarm_manual(self):
        self._manual_armed = False
        # Desarmar vale até um novo armar: impede que o REC automático pegue a
        # próxima live por conta própria (como o original, onde parar o thread
        # encerrava a vigília até um novo clique no botão).
        self._sessao_fechada_no_armo = True

    def set_auto_rec(self, valor: bool):
        """Aplica a opção "Armar o REC sozinho ao abrir o programa"."""
        if valor:
            # Ligar rearma a vigília (limpa o bloqueio de um desarme antigo),
            # como o original fazia ao armar na abertura.
            self._sessao_fechada_no_armo = False
            self.events.put(("status", ("aguardando", "Verificando...")))
            if self.app.engine.live_active:
                self._on_live_started()
        elif not self._manual_armed:
            self._sessao_fechada_no_armo = True

    def start_now(self):
        """Grava imediatamente, se a live estiver no ar (independente do config)."""
        self.ensure_loaded()
        if self._recorder is None:
            self._start_pending = True
            return
        self._do_start()

    def stop(self):
        if self._recorder is not None:
            self._recorder.stop()

    def shutdown(self):
        self._manual_armed = False
        if self._recorder is not None:
            try:
                self._recorder.stop()
            except Exception:  # noqa: BLE001
                pass

    def _do_start(self):
        try:
            rec = self.app.config["recorder"]
            live = self.app.config["live"]
            username = live.get("username", "")
            outdir = rec.get("outdir", os.path.join(RD_DIR, "..", "Gravacoes"))
            cookie = rec.get("cookie", "")
            self._recorder.registrar_presentes = self.auto_record_presentes()
            self._recorder.start(
                username, outdir, "origin", cookie,
                poll_seconds=int(live.get("verify_poll", 5)),
                wait_for_live=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.log("error", f"[GRAVADOR] Falha ao iniciar a gravação: {exc}")

    # -------------------------------------------------------------- emit

    def _emit(self, kind, value=""):
        """Ponte entre o motor (threads de trabalho) e a GUI/logger."""
        if kind == "log":
            logger.log("info", str(value))
        elif kind == "error":
            logger.log("error", str(value))
        elif kind == "info":
            logger.log("info", str(value))
        elif kind == "status":
            try:
                _, texto = value
                logger.log("info", str(texto))
            except (TypeError, ValueError):
                logger.log("info", str(value))
        elif kind == "done":
            caminho = getattr(value, "final_path", "") or ""
            logger.log("success", f"Gravação salva: {os.path.basename(caminho)}"
                       if caminho else "Gravação salva.")
            # Com keep_waiting=False o REC automático grava uma única live por
            # armo: depois de salvar, ele não liga de novo sozinho até que o
            # usuário arme outra vez.
            if not self.keep_waiting:
                self._sessao_fechada_no_armo = True
                self._manual_armed = False
        self.events.put((kind, value))


# Conveniência para que outras partes (ex.: resgate) possam reutilizar o caminho.
RD_PATH = RD_DIR


def ensure_rd_in_path() -> None:
    if RD_DIR not in sys.path:
        sys.path.insert(0, RD_DIR)


def import_rd(nome: str):
    """Importa um módulo do motor copiado (rd/), adicionando-o ao path se preciso.

    `recorder` importa `resources`, `tiktok_api` etc. por nome simples, então
    todos precisam resolver a partir de rd/ no sys.path.
    """
    ensure_rd_in_path()
    return __import__(nome)


def wait_for_rd_import(nome: str, timeout: float = 15.0):
    """Tenta importar `nome` de rd/ com tolerância ao carregamento em andamento.

    O host carrega o `recorder` (pesado, ~3s) em thread na abertura; quando a
    aba pede o `editor`, ele importa `compositor` que por sua vez puxa o
    `recorder` — por isso espera-se o host terminar antes de importar por aqui.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            return import_rd(nome)
        except ImportError as exc:
            # Pode ser dependência ainda não carregada; se for o caso, espera.
            if nome in exc.name or "rd" in str(exc):
                time.sleep(0.15)
                continue
            raise
    raise ImportError(f"Não foi possível carregar {nome} de rd/")
