# -*- coding: utf-8 -*-
"""Elevação a Administrador, pedida só quando faz falta.

Antes o programa se relançava elevado logo ao abrir, e todo mundo levava um
pedido do UAC antes de ver a janela. Só uma coisa precisa disso: o Chat
Automático, que move o mouse e digita na janela do TikTok LIVE Studio — o
Windows não deixa um processo comum mandar cliques para uma janela de nível
mais alto. Monitorar a live, falar, imprimir, gravar e o Jogo Perfil rodam
sem privilégio nenhum.

Então a elevação virou sob demanda, de dois jeitos:

  - **só desta vez**: relança com o pedido do UAC de sempre;
  - **para sempre**: cria uma Tarefa Agendada marcada para rodar com
    privilégios mais altos. O Windows não pede confirmação para iniciar uma
    tarefa dessas, então o programa passa a abrir elevado direto. Criar a
    tarefa exige o UAC uma única vez.

Sobre a segunda: ela dá privilégio de Administrador, sem perguntar, para o
programa *que estiver naquele caminho*. Se alguém trocar o arquivo de lá, herda
o privilégio junto. Por isso ela é opcional, o caminho fica gravado na tarefa e
o programa confere se ainda é o mesmo antes de usar (`tarefa_valida`).
"""
import ctypes
import os
import subprocess
import sys
import tempfile

from core import logger

SW_SHOWNORMAL = 1
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

NOME_TAREFA = "Dinfinity - abrir como Administrador"


def e_admin():
    """Este processo está rodando como Administrador?"""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001 — fora do Windows, segue o baile
        return True


# Passado para a cópia elevada para ela já abrir na aba certa: quem elevou
# estava indo ligar o Chat Automático e não deve ter que procurar de novo.
ARG_CHAT = "--chat"
# Pedido para a cópia elevada criar a Tarefa Agendada (só ela consegue).
ARG_INSTALAR = "--instalar-tarefa"
# Gravado dentro da própria tarefa. Quem nasce por ela não tenta se relançar de
# novo — numa conta sem direito de Administrador a tarefa sobe sem elevar, e
# sem esta marca o programa ficaria se reabrindo para sempre.
ARG_VIA_TAREFA = "--via-tarefa"


def _interpretador():
    """O python sem console, que é como o Dinfinity abre normalmente.

    `sys.executable` aponta para o `python.exe` quando alguém roda de um
    terminal, e usar esse na tarefa faria aparecer um console preto atrás da
    janela toda vez. Também deixa a conferência da tarefa estável: o caminho
    gravado é sempre o mesmo, tenha sido aberta como for.
    """
    atual = sys.executable
    sem_console = os.path.join(os.path.dirname(atual), "pythonw.exe")
    if os.path.basename(atual).lower() == "python.exe" and os.path.isfile(sem_console):
        return sem_console
    return atual


def _comando_de_relancamento(extra=""):
    """(programa, argumentos) para abrir outra cópia deste mesmo Dinfinity."""
    if getattr(sys, "frozen", False):
        return sys.executable, extra
    script = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Dinfinity.pyw")
    return _interpretador(), f'"{script}" {extra}'.strip()


def relancar_como_admin(extra=""):
    """Abre outra instância elevada e devolve True se o UAC foi aceito.

    A vaga da instância única é solta antes de chamar o UAC: a cópia nova
    confere o mutex assim que nasce e encontraria esta aqui ainda ocupando o
    lugar. Se o usuário recusar o pedido, a vaga é retomada e nada muda.
    """
    from core import instancia

    programa, argumentos = _comando_de_relancamento(extra)
    pasta = os.path.dirname(os.path.abspath(programa if getattr(sys, "frozen", False)
                                            else __file__))
    instancia.soltar_vaga()
    try:
        resultado = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", programa, argumentos, pasta, SW_SHOWNORMAL)
    except Exception as exc:  # noqa: BLE001
        logger.log("error", f"[ADMIN] Não consegui relançar: {exc}")
        resultado = 0
    # Acima de 32 = o Windows aceitou abrir. 5 (ACCESS_DENIED) é o "não" do
    # usuário no pedido do UAC.
    if resultado > 32:
        return True
    instancia.marcar()
    logger.log("warning", "[ADMIN] Elevação recusada; o programa segue como está.")
    return False


# ------------------------------------------------------------ tarefa agendada

def _schtasks(*args, capturar=False):
    """Roda o schtasks sem piscar console. Devolve (deu_certo, saída)."""
    try:
        r = subprocess.run(["schtasks", *args], capture_output=True, text=True,
                           timeout=30, creationflags=NO_WINDOW,
                           encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError) as exc:
        logger.log("error", f"[ADMIN] schtasks falhou: {exc}")
        return False, ""
    return r.returncode == 0, (r.stdout or "") if capturar else ""


def _xml_da_tarefa(programa, argumentos, pasta):
    """A tarefa: sem gatilho, só sob demanda, com privilégios mais altos.

    Sem `<Triggers>` ela nunca dispara sozinha — só quando o programa a chama.
    `InteractiveToken` é o que faz a janela aparecer na sessão de quem está
    usando o computador, em vez de rodar invisível.
    """
    usuario = f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}".strip("\\")
    escapar = lambda t: (str(t).replace("&", "&amp;").replace("<", "&lt;")  # noqa: E731
                         .replace(">", "&gt;"))
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Abre o Dinfinity com privilegios de Administrador, sem o pedido do UAC. Criada pelo proprio Dinfinity; pode ser removida por la ou pelo Agendador de Tarefas.</Description>
    <URI>\\{escapar(NOME_TAREFA)}</URI>
  </RegistrationInfo>
  <Principals>
    <Principal id="Author">
      <UserId>{escapar(usuario)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>false</AllowHardTerminate>
    <StartWhenAvailable>false</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>5</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escapar(programa)}</Command>
      <Arguments>{escapar(argumentos)}</Arguments>
      <WorkingDirectory>{escapar(pasta)}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def criar_tarefa():
    """Registra a tarefa. Precisa estar rodando como Administrador."""
    if not e_admin():
        logger.log("error", "[ADMIN] Só dá para criar a tarefa como Administrador.")
        return False
    from core import caminhos

    programa, argumentos = _comando_de_relancamento(ARG_VIA_TAREFA)
    pasta = caminhos.APP_DIR
    # O schtasks espera o XML em UTF-16; em UTF-8 ele recusa o arquivo.
    caminho = os.path.join(tempfile.gettempdir(), "dinfinity_tarefa.xml")
    try:
        with open(caminho, "w", encoding="utf-16") as fh:
            fh.write(_xml_da_tarefa(programa, argumentos, pasta))
        ok, _ = _schtasks("/create", "/tn", NOME_TAREFA, "/xml", caminho, "/f")
    finally:
        try:
            os.remove(caminho)
        except OSError:
            pass
    if ok:
        logger.log("success", "[ADMIN] Pronto: o Dinfinity vai abrir como "
                              "Administrador sem pedir confirmação.")
    else:
        logger.log("error", "[ADMIN] Não consegui criar a tarefa agendada.")
    return ok


def remover_tarefa():
    ok, _ = _schtasks("/delete", "/tn", NOME_TAREFA, "/f")
    if ok:
        logger.log("system", "[ADMIN] Abertura automática como Administrador desligada.")
    return ok


def _entre(texto, etiqueta):
    if f"<{etiqueta}>" not in texto:
        return ""
    return texto.split(f"<{etiqueta}>", 1)[1].split(f"</{etiqueta}>", 1)[0].strip()


def _comando_da_tarefa():
    """(programa, argumentos) que a tarefa registrada aponta, ou ("", "")."""
    ok, saida = _schtasks("/query", "/tn", NOME_TAREFA, "/xml", capturar=True)
    if not ok:
        return "", ""
    return _entre(saida, "Command"), _entre(saida, "Arguments")


def tarefa_existe():
    return bool(_comando_da_tarefa()[0])


def tarefa_valida():
    """A tarefa existe E ainda aponta para esta instalação?

    Mover ou copiar a pasta deixaria a tarefa apontando para o lugar antigo — e
    aí ela abriria o Dinfinity de lá, ou nenhum. Rodando do código-fonte o
    programa é sempre o mesmo python, então os argumentos (onde está o caminho
    do script) também entram na conferência.
    """
    programa, argumentos = _comando_da_tarefa()
    if not programa:
        return False
    esperado_prog, esperado_args = _comando_de_relancamento(ARG_VIA_TAREFA)
    mesmo = lambda a, b: os.path.normcase(a.strip()) == os.path.normcase(b.strip())  # noqa: E731
    return mesmo(programa, esperado_prog) and mesmo(argumentos, esperado_args)


def abrir_pela_tarefa():
    """Inicia a cópia elevada pela tarefa (sem UAC). True se o Windows aceitou."""
    ok, _ = _schtasks("/run", "/tn", NOME_TAREFA)
    return ok


def _bilhete_chat():
    from core import caminhos
    return os.path.join(caminhos.dados_dir(), ".abrir_no_chat")


def pedir_abertura_no_chat():
    """Deixa um bilhete para a próxima cópia abrir na aba Chat.

    O `schtasks /run` não aceita argumentos, então o recado vai por arquivo —
    é o único jeito de a cópia que a tarefa acorda saber de onde ela veio.
    """
    try:
        with open(_bilhete_chat(), "w", encoding="utf-8") as fh:
            fh.write("1")
    except OSError:
        pass


def consumir_abertura_no_chat():
    """Lê e apaga o bilhete. True se a aba Chat era o destino."""
    caminho = _bilhete_chat()
    try:
        if os.path.exists(caminho):
            os.remove(caminho)
            return True
    except OSError:
        pass
    return False
