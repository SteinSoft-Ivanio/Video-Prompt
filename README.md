# Video -> Prompt

Transforma um vídeo local — a gravação de tela que o cliente mandou — em um
`prompt.md` que o Claude Code consegue ler por inteiro: a narração transcrita
com marcador de tempo, mais os quadros dos momentos em que a tela mudou.

O problema que ele resolve: uma gravação de cinco minutos carrega duas
informações que não cabem numa mensagem de texto — o que a pessoa **diz** e o
que aparece na **tela**. Transcrever só o áudio perde a mensagem de erro; mandar
o vídeo inteiro não é possível. Este comando separa as duas e as reagrupa num
único arquivo, alinhadas pelo mesmo relógio.

## Uso

Clique duas vezes em **`Video Prompt.bat`** (ou arraste o vídeo em cima dele).
Cole o caminho, escolha o modo, espere.

```
  [1/3] áudio ...... 03:12 extraídos, transcrevendo...
        7 trechos em 1.4s (cuda)
  [2/3] quadros .... 11 quadros de mudança de tela
  [3/3] prompt ..... 392 palavras

  Pronto: C:\Users\você\AppData\Local\videoprompt\erro-cliente-143207\prompt.md

  [E] enviar ao Claude Code   [C] copiar   [P] abrir pasta   [A] abrir prompt.md   [Q] sair
```

`[E]` injeta numa sessão do Claude Code que já esteja aberta; `[C]` copia a
mesma linha para você colar onde quiser. A linha é sempre a mesma frase curta —
*leia este arquivo e execute a tarefa* — porque o REPL do Claude Code trata cada
quebra de linha como Enter, e um prompt de 400 palavras colado chegaria pela
metade.

### Os dois modos

| Modo | Quando | O que o prompt pede |
| --- | --- | --- |
| **bug** (padrão) | O cliente está mostrando um problema | Passos para reproduzir, evidência literal na tela, onde investigar, o que ficou no escuro |
| **sistema** | O cliente está mostrando o sistema antigo dele | Telas, campos, fluxo, regras de negócio, lacunas a perguntar |

### Pela linha de comando

```
python app\videoprompt.py "C:\videos\erro.mp4" --modo sistema --frames 24
```

| Argumento | Para quê |
| --- | --- |
| `--modo bug\|sistema` | qual instrução vai no topo do prompt |
| `--frames N` | teto de quadros (padrão 16) |
| `--saida DIR` | pasta de saída |
| `--obs "..."` | contexto seu, entra no prompt |
| `--glossario "Acme, Brasflória"` | nomes próprios que o Whisper costuma errar |
| `--sem-menu` | gera e sai, sem o menu interativo |

## Como funciona

```
video.mp4
   ├─ áudio  -> WAV 16 kHz mono -> faster-whisper -> segmentos COM tempo
   └─ vídeo  -> amostra 2x/s -> compara em 64x36 cinza -> os quadros que mudaram
                                          ↓
                                     prompt.md
```

Três decisões que valem explicação:

**Extrair o áudio antes de transcrever.** Uma gravação de tela de 500 MB vira um
WAV de poucos MB, então o tamanho do `.mp4` deixa de importar e a transcrição
começa mais cedo.

**Escolher quadro por mudança de tela, não por intervalo fixo.** Amostragem fixa
geraria dezenas de fotos idênticas de uma tela parada e ainda assim perderia o
modal que abriu entre duas amostras. Aqui cada quadro amostrado é comparado com
o anterior em miniatura; sobrevivem os que mudaram acima do limiar e estão a
pelo menos 2s do anterior. Se nada mudou — narração sobre tela imóvel — um piso
de 4 quadros espalhados entra como contexto mínimo.

**Fala e imagem compartilham o marcador.** `[01:24]` na narração e
`0003_01m24s.jpg` na pasta são o mesmo instante. É o que permite ao leitor
cruzar *"aqui dá erro"* com a imagem que mostra o erro — e é por isso que os
dois derivam da mesma função de formatação, e não um de truncamento e outro de
arredondamento.

### Módulos

| Arquivo | Responsabilidade |
| --- | --- |
| `app/midia.py` | decodifica o vídeo: WAV + escolha e gravação dos quadros |
| `app/transcricao.py` | carrega o Whisper e devolve segmentos com tempo |
| `app/prompt.py` | monta o `prompt.md` — texto puro, sem I/O |
| `app/envio.py` | área de transferência e ponte com as sessões do Claude Code |
| `app/videoprompt.py` | orquestra e fala com o usuário |

Só `videoprompt.py` imprime ou pergunta algo. É o que permite testar os outros
sem simular um terminal.

## Instalação

Nada, se o **Whatsapp-Transcritor** estiver na pasta ao lado
(`C:\Desenvolvimento\Interno\`): o `.bat` acha o `.venv` de lá, que já tem o
faster-whisper, o PyAV e as DLLs de CUDA — cerca de 3 GB que não precisam ser
instalados duas vezes.

Ambiente próprio, se preferir isolar:

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Ou aponte para qualquer outro interpretador com a variável `VP_PYTHON`.

A primeira execução baixa o modelo `large-v3-turbo` (~1,6 GB) para o cache do
Hugging Face — que é compartilhado com o Whatsapp-Transcritor, então se você já
usa aquele, o download não acontece de novo.

| Variável | Para quê |
| --- | --- |
| `VP_PYTHON` | interpretador a usar |
| `VP_MODEL` | modelo do Whisper (padrão `large-v3-turbo`) |
| `VP_LANGUAGE` | idioma da transcrição (padrão `pt`) |
| `VP_TRANSCRITOR` | onde está o `server/` do Whatsapp-Transcritor, para o `[E]` |

Sem GPU o programa não quebra: cai para CPU e fica mais lento.

## Testes

```
.venv\Scripts\python.exe -m pytest          # rápido, sem GPU
.venv\Scripts\python.exe -m pytest -m slow  # carrega o modelo de verdade
```

Os testes geram os vídeos na hora, em vez de versionar amostras: mantém o repo
leve e deixa cada teste declarar exatamente em que segundo a tela muda — que é
justamente o que precisa ser medido.

## Limites conhecidos

- Windows apenas (`clip.exe`, `os.startfile`, as DLLs de CUDA via pip).
- Vídeo mudo funciona: o prompt sai só com as imagens e diz isso explicitamente,
  em vez de fingir uma narração vazia.
- Os quadros saem da mudança de tela, então **há saltos entre eles**. O que
  acontece no intervalo não fica registrado — o próprio prompt avisa disso ao
  leitor.
- Transcrição de áudio ruim é transcrição ruim. O `--glossario` ajuda com nomes
  próprios, mas não conserta microfone de celular no meio do barulho.
