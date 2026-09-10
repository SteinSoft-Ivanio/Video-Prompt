"""Monta o prompt.md a partir do que midia.py e transcricao.py produziram.

Funcao pura de texto: nao le disco, nao decodifica nada, nao chama modelo. Isso
deixa o formato - a parte que decide a qualidade da resposta - testavel de graca
e facil de ajustar sem reprocessar um video de dez minutos.

Duas decisoes valem explicacao:

1. Os caminhos das imagens sao ABSOLUTOS. Quem le o arquivo e o Claude Code, e
   ele pode estar aberto em qualquer pasta; caminho relativo so funcionaria por
   sorte.
2. Fala e quadro usam o MESMO marcador de tempo (mm:ss). E o unico jeito de o
   leitor cruzar "aqui da erro" com a imagem que mostra o erro.
"""

from __future__ import annotations

from pathlib import Path

from midia import Quadro, formatar_tempo
from transcricao import Transcricao

MODOS = ("bug", "sistema")

_CABECALHO = {
    "bug": (
        "Um cliente gravou a tela mostrando um problema e narrando o que acontece. "
        "Transforme esta gravação em uma demanda de correção acionável."
    ),
    "sistema": (
        "Um cliente gravou a tela navegando pelo sistema antigo dele e explicando "
        "como ele funciona. Levante o funcionamento desse sistema a partir da "
        "gravação, no nível de detalhe necessário para reconstruí-lo."
    ),
}

_TAREFA = {
    "bug": """1. **O problema, em uma frase.** O que o cliente diz que está errado.
2. **Passos para reproduzir.** Numerados, na ordem em que aparecem no vídeo, citando o quadro de cada passo.
3. **Evidência na tela.** Transcreva *literalmente* qualquer mensagem de erro, código, valor ou nome de campo visível, dizendo em que quadro está.
4. **Onde investigar.** Hipóteses do que pode causar isso, ancoradas no que se vê — não em suposição genérica.
5. **O que ficou no escuro.** O que o vídeo não mostra e precisa ser perguntado ao cliente antes de mexer no código.""",
    "sistema": """1. **O que o sistema faz**, em uma frase.
2. **Telas identificadas.** Uma seção por tela: nome (o que aparece no título/menu), para que serve, campos visíveis com seus rótulos, botões e ações disponíveis. Cite o quadro de cada tela.
3. **Fluxo.** Em que ordem as telas se conectam e o que dispara cada transição.
4. **Regras de negócio.** O que a narração afirma sobre cálculos, validações, obrigatoriedade, permissões — separando o que foi *dito* do que foi *visto*.
5. **Dados.** Entidades e campos que o sistema parece manipular, inferidos das telas.
6. **Lacunas.** Telas mencionadas mas não mostradas, campos ilegíveis, regras citadas pela metade. Liste como perguntas ao cliente.""",
}

_REGRAS = """- **As imagens são a fonte da verdade sobre a tela; a narração é a fonte sobre a intenção.** Quando as duas divergirem, diga qual você seguiu e por quê.
- **Não preencha lacuna com suposição.** Se um campo está ilegível ou uma tela não aparece, escreva que não dá para saber. Um "não sei" é útil; um palpite apresentado como fato custa caro.
- Os quadros foram escolhidos por *mudança de tela*, então há saltos entre eles. O que acontece no intervalo não está registrado."""


def montar(
    modo: str,
    video: Path,
    duracao_segundos: float,
    quadros: list[Quadro],
    transcricao: Transcricao | None,
    observacao: str | None = None,
) -> str:
    if modo not in MODOS:
        raise ValueError(f"Modo desconhecido: {modo!r}. Use um de {MODOS}.")

    video = Path(video)
    partes: list[str] = []

    partes.append(f"# Gravação do cliente — {video.name}")
    partes.append(_CABECALHO[modo])

    partes.append("## O material")
    inventario = [
        f"- **Arquivo:** `{video.resolve()}`",
        f"- **Duração:** {formatar_tempo(duracao_segundos)}",
        f"- **Quadros:** {len(quadros)} imagens, escolhidas nos momentos em que a tela mudou",
    ]
    if transcricao is None:
        inventario.append(
            "- **Narração:** o vídeo está sem trilha de áudio. Trabalhe só com as imagens."
        )
    else:
        inventario.append(
            f"- **Narração:** transcrita abaixo, em {transcricao.idioma}, com marcador de tempo"
        )
    partes.append("\n".join(inventario))

    partes.append(
        "**Antes de responder, abra cada imagem listada em “Quadros”.** Elas são "
        "metade da informação; a transcrição sozinha não mostra a tela."
    )

    if observacao:
        partes.append(f"## Contexto que eu já sei\n\n{observacao.strip()}")

    if transcricao is not None and transcricao.segmentos:
        partes.append(f"## Narração\n\n```\n{transcricao.cronometrada()}\n```")

    partes.append(_tabela_de_quadros(quadros))
    partes.append(f"## Como tratar as duas fontes\n\n{_REGRAS}")
    partes.append(f"## Sua tarefa\n\n{_TAREFA[modo]}")

    return "\n\n".join(partes) + "\n"


def _tabela_de_quadros(quadros: list[Quadro]) -> str:
    if not quadros:
        return "## Quadros\n\nNenhum quadro pôde ser extraído deste vídeo."

    linhas = ["## Quadros", "", "| Momento | Imagem |", "| --- | --- |"]
    linhas += [
        f"| {formatar_tempo(q.segundo)} | `{q.caminho.resolve()}` |" for q in quadros
    ]
    return "\n".join(linhas)


def linha_de_envio(destino: Path) -> str:
    """A frase unica que se cola numa sessao do Claude Code.

    Uma linha so, de proposito: o REPL do Claude Code trata cada quebra de linha
    como Enter, entao um prompt multi-linha colado chegaria pela metade. Mandar o
    caminho e deixar que ele leia o arquivo resolve isso e ainda carrega as
    imagens junto.
    """
    return (
        f"Leia o arquivo {Path(destino).resolve()} por completo, "
        "abra todas as imagens que ele lista e execute a tarefa descrita nele."
    )
