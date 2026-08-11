# Dinfinity

Sua própria suíte de interação com o TikTok Live, reunindo em um único programa
profissional (sem console aberto) o que antes estava espalhado em vários
scripts: monitor de live, reações/ações, texto para fala, chat automático, o
jogo de revelar imagens e o gravador/editor de replays.

O programa é **autossuficiente**: as ferramentas de que precisa viajam junto,
em `bin/` e `rd/mpvlib/`. Não é preciso instalar VLC, wkhtmltopdf, PDFtoPrinter
nem ffmpeg na máquina.

## Seções (abas)

| Aba | O que faz |
|-----|-----------|
| **Conexão** | Usuário da live, de quanto em quanto tempo conferir se ela abriu, liga/desliga o monitor e mostra o console de log. |
| **Reações** | As reações da live com liga/desliga. Cada uma é um gatilho + uma lista de ações. |
| **Texto para Fala** | Ativa/desativa o TTS, escolhe voz, velocidade, volume e a saída de áudio; testa a voz ali mesmo. |
| **Chat Automático** | Envia mensagens periódicas para o chat flutuante do TikTok LIVE Studio. A lista é editada no lugar, reordenada arrastando pelo ⠿ e cada mensagem liga/desliga sem precisar apagar. Dá para enviar na ordem da lista ou em ordem aleatória. |
| **Jogo Perfil** | O quebra-cabeça de revelar imagens. As pastas de imagens são escolhidas aqui. Serve o frame para o OBS em `http://127.0.0.1:8765`. |
| **Gravador** | Grava a live e edita o replay. |
| **Configurações** | Só o que é do programa inteiro: conexão com o OBS e aparência. |

O que é de uma seção mora na seção. A impressora fica na ação de imprimir, as
pastas do jogo na aba do jogo, a voz na aba de TTS. Ajuste interno (o vigia da
conexão, as pastas temporárias) não aparece: o programa cuida sozinho.

## Como rodar

1. Tenha o Python 3 (3.10+) instalado com as dependências:

   ```bash
   pip install -r requirements.txt
   ```

2. Baixe as ferramentas embutidas (ffmpeg, ffprobe e a libmpv). Elas não estão
   no repositório porque passam do limite de 100 MB por arquivo do GitHub:

   ```bash
   python ferramentas.py
   ```

3. Abra `Iniciar Dinfinity.bat` (ou dê dois cliques em `Dinfinity.pyw`).
4. Em **Conexão**, confira o usuário (@) e clique em **Conectar**.

Já tem uma configuração de outra máquina? Leve o arquivo exportado e use
**Configurações → Backup das configurações → Importar**.

## Administrador

O programa abre **sem pedir Administrador**. Só o Chat Automático precisa
disso — o Windows não deixa um processo comum mandar cliques para a janela do
TikTok LIVE Studio. Quem não usa essa aba nunca vê o UAC.

O Windows não eleva um processo que já está rodando: para ganhar o privilégio,
o programa **fecha e abre de novo**. No meio de uma sessão isso derruba a live,
encerra a gravação e limpa o log. Por isso, ao clicar em **Iniciar** no Chat
Automático, aparecem três saídas — todas reabrem agora, mas as duas primeiras
fazem a elevação **no arranque** das próximas vezes, antes de qualquer coisa
subir, e aí nada mais é interrompido:

- **Sempre (sem perguntar)** — cria uma Tarefa Agendada do Windows marcada para
  rodar com privilégios mais altos. Você confirma o UAC uma única vez; daí em
  diante o programa abre elevado sozinho.
- **Perguntar ao abrir** — o UAC aparece na abertura, antes de a live conectar.
- **Só desta vez** — não muda nada para as próximas.

A primeira dá privilégio de Administrador, sem perguntar, ao programa que
estiver naquele caminho — então quem puder trocar os arquivos da pasta herda o
mesmo privilégio. As duas se desfazem em **Configurações → Abertura como
Administrador** (o bloco só aparece depois de ligada). Se a pasta do programa
for movida, o Dinfinity percebe que a tarefa aponta para o lugar errado e volta
a pedir do jeito normal.

## Ícone

O ícone é desenhado pelo próprio programa (`core/icone.py`), então nasce nítido
em qualquer tamanho e muda de cor conforme o estado — as mesmas cores da
bolinha na barra lateral:

| Estado | Cor |
|--------|-----|
| Parado | roxo — a cor da marca |
| Standby | amarelo |
| Conectando | laranja |
| Ao vivo | verde |
| **Gravando** | vermelho, com o ponto cheio |
| Erro | vermelho claro |

Parado é o roxo porque é o estado em que o programa abre e passa a maior parte
do tempo: é ele que dá a cara do Dinfinity na barra de tarefas.

Gravando tem prioridade sobre o estado da live. O ponto mais cheio existe
porque só a cor não separa "gravando" de "erro" a 16 px, que é o tamanho da
barra de tarefas.

Os `.ico` de cada estado são gerados em `dados/icones/` na primeira vez que
fazem falta, com a cor no nome do arquivo — mudar a paleta gera arquivos novos
sozinho. O `assets/dinfinity.ico` é o ícone do executável, gerado por
`core.icone.salvar_ico()`.

## Onde ficam as coisas

| Pasta | O que é |
|-------|---------|
| `config.json` | As configurações, na raiz. Gerado na primeira execução. |
| `dados/` | O que o programa produz: temporários do TTS, miniaturas, preferências da edição. |
| `bin/` | ffmpeg e ffprobe, usados pelo gravador e pelo editor. |
| `rd/mpvlib/` | A libmpv, usada pelo som, pela voz e pela prévia do editor. |

O `config.json` não guarda caminhos calculados pelo programa, então pode ser
copiado junto para outra máquina sem quebrar.

## Reações / Ações

Cada reação é um **gatilho** (o que faz disparar) mais uma **lista de ações**
(o que acontece, na ordem). Tudo é montado pela aba **Reações**.

```json
{
  "id": "exemplo_1",
  "name": "Grou de Papel — Avestruz + som",
  "enabled": true,
  "trigger": { "tipo": "presente", "gift": "paper crane", "cooldown": 7 },
  "actions": [
    { "type": "obs_source_show", "scene": "[C] Gifts", "source": "[G] Avestruz" },
    { "type": "delay", "seconds_ms": 1000 },
    { "type": "sound_play", "file": "C:/sons/passaro.mp3", "volume": 80 }
  ]
}
```

Ações disponíveis: aguardar, escrever no log, enviar ação WebSocket
(Streamer.bot), tocar som, parar sons, falar com o TTS, trocar de cena no OBS,
mostrar/esconder/alternar fonte, ligar/desligar filtro, mutar, mudar volume e
imprimir o cartão de agradecimento.

Nos textos valem os curingas `{nickname}`, `{username}`, `{gift}`, `{gift_pt}`,
`{count}`, `{diamonds}`, `{message}` e `{likes}`.

### Cartão de agradecimento

A ação **Imprimir cartão de agradecimento** tem tela própria, com a prévia do
cupom montada ao vivo enquanto você digita. Dá para editar o texto de cima e o
de baixo, escolher se sai espelhado, escolher a impressora (o padrão é a
impressora padrão do Windows), imprimir um teste e reimprimir o último cartão
caso ele saia borrado.

O cartão é desenhado pelo próprio programa e vai direto para a fila de
impressão do Windows.

## Ferramentas

- **Som e voz**: `edge-tts` (Microsoft, gratuito) para gerar a voz e a
  **libmpv** embutida para tocar. A saída de áudio é escolhível — dá para
  mandar a voz por um cabo virtual sem passar pelo alto-falante.
- **Gravador e editor**: `ffmpeg` e `ffprobe` embutidos em `bin/`.
- **Impressão**: Pillow desenha e o Windows imprime.
- O TikTok LIVE Studio precisa estar aberto para o Chat Automático enviar
  mensagens; o envio é uma automação não oficial — use com moderação.

## Observação

O monitor usa a biblioteca [TikTokLive](https://github.com/isaackogan/TikTokLive),
que não é uma API oficial do TikTok. Use por sua conta e risco e respeite as
regras da plataforma.

## Licença

**AGPL-3.0** (veja o arquivo [LICENSE](LICENSE)).

A escolha não foi livre: o Dinfinity importa a
[TikTokLive](https://github.com/isaackogan/TikTokLive), que é AGPL-3.0, e uma
obra que a usa precisa ser distribuída sob a mesma licença. Na prática, quem
distribuir o programa — modificado ou não — precisa disponibilizar o código
junto.

### O que vem junto

| Componente | Licença | Como é usado |
|------------|---------|--------------|
| [TikTokLive](https://github.com/isaackogan/TikTokLive) | AGPL-3.0 | monitor da live |
| [edge-tts](https://github.com/rany2/edge-tts) | LGPL-3.0 | geração da voz |
| [python-mpv](https://github.com/jaseg/python-mpv) | GPL-2.0+ / LGPL-2.1+ | ponte para a libmpv |
| [libmpv](https://mpv.io/) | GPL-2.0+ | som, voz e prévia do editor |
| [ffmpeg](https://ffmpeg.org/) (build GPL) | GPL-2.0+ | gravação e exportação |
| [customtkinter](https://github.com/TomSchimansky/CustomTkinter) | CC0-1.0 | interface |
| [Pillow](https://python-pillow.org/) | MIT-CMU | cartão de impressão e ícone |
| [websockets](https://github.com/python-websockets/websockets) | BSD-3-Clause | OBS e Streamer.bot |
| [uiautomation](https://github.com/yinkaisheng/Python-UIAutomation-for-Windows) | Apache-2.0 | Chat Automático |
| [pywin32](https://github.com/mhammond/pywin32) | PSF | impressão |
| [TikTok Sans](rd/assets/fonts/OFL.txt) | SIL OFL 1.1 | fonte do editor |

O ffmpeg e a libmpv não estão no repositório (`ferramentas.py` os baixa), mas
**entram no executável compilado** — quem distribuir o `.exe` está
redistribuindo esses binários GPL e precisa oferecer o código-fonte deles
também, o que os projetos originais já fazem publicamente.
