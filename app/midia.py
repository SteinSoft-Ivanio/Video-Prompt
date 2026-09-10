"""Le o video e devolve as duas materias-primas do prompt: audio e quadros.

Este modulo nao sabe o que e um prompt nem quem vai transcrever. Recebe um
arquivo e devolve um WAV e uma lista de JPEGs - o que permite testar a parte
cara (decodificacao) com videos sinteticos, sem GPU e sem modelo carregado.

Tudo aqui roda em cima do PyAV, que ja vem junto com o faster-whisper. Nao ha
dependencia nova: nem ffmpeg no PATH, nem Pillow.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

# O Whisper quer 16 kHz mono. Converter aqui, e nao no transcritor, tem um
# efeito colateral util: uma gravacao de tela de 500 MB vira um WAV de poucos
# MB, entao o tamanho do .mp4 deixa de ser um problema.
TAXA_WHISPER = 16000

# Resolucao maxima do JPEG salvo. 1280 mantem legivel o texto de uma tela cheia
# (mensagem de erro, nome de campo) sem inchar o diretorio de saida.
LARGURA_MAXIMA = 1280

# Miniatura usada so para comparar quadros. Pequena de proposito: em 64x36 o
# ruido de compressao some e sobra a mudanca estrutural - abriu um modal,
# trocou de aba, apareceu um erro.
COMPARA_LARGURA, COMPARA_ALTURA = 64, 36

# Fracao media de mudanca (0 a 1) a partir da qual consideramos que a tela
# mudou de verdade. Calibrado em gravacao de tela: o cursor piscando e a rolagem
# de uma linha ficam abaixo; abrir uma janela fica bem acima.
LIMIAR_PADRAO = 0.035

# Quantas vezes por segundo olhamos um quadro. Gravacao de tela nao muda mais
# rapido que isso, e amostrar barato deixa o custo proporcional a duracao.
FPS_AMOSTRA = 2.0

# Teto da lista de candidatos antes da escolha final. Evita que um video longo
# e agitado carregue centenas de JPEGs na memoria.
TETO_CANDIDATOS = 80


class MidiaInvalida(Exception):
    """O arquivo nao abriu, ou nao tem trilha de video."""


class SemAudio(MidiaInvalida):
    """O container abriu, mas nao ha trilha de audio para transcrever."""


@dataclass(frozen=True)
class InfoAudio:
    segundos: float
    taxa: int
    canais: int


@dataclass(frozen=True)
class Quadro:
    segundo: float
    caminho: Path
    mudanca: float

    @property
    def marcador(self) -> str:
        return formatar_tempo(self.segundo)


def formatar_tempo(segundos: float) -> str:
    """Converte 12.4 no marcador 00:12, o mesmo usado na transcricao."""
    total = int(round(segundos))
    return f"{total // 60:02d}:{total % 60:02d}"


def _abrir(video: Path):
    import av

    try:
        return av.open(str(video))
    except Exception as exc:  # noqa: BLE001 - o erro cru do libav nao ajuda ninguem
        raise MidiaInvalida(f"Não consegui abrir o vídeo: {exc}") from exc


def duracao(video: Path) -> float:
    """Duracao em segundos, ou 0.0 se o container nao souber informar."""
    import av

    with _abrir(video) as container:
        if container.duration:
            return container.duration / av.time_base
        fluxos = container.streams.video or container.streams.audio
        if fluxos and fluxos[0].duration and fluxos[0].time_base:
            return float(fluxos[0].duration * fluxos[0].time_base)
    return 0.0


def extrair_audio_wav(video: Path, destino: Path) -> InfoAudio:
    """Escreve a trilha de audio como WAV 16 kHz mono e devolve o que saiu.

    Levanta SemAudio quando o video e mudo. Isso nao e fatal para o programa: um
    video sem narracao ainda rende um prompt so com as imagens - quem decide
    isso e o orquestrador, nao este modulo.
    """
    import av
    from av.audio.resampler import AudioResampler

    destino.parent.mkdir(parents=True, exist_ok=True)

    with _abrir(video) as entrada:
        if not entrada.streams.audio:
            raise SemAudio("Este vídeo não tem trilha de áudio.")
        trilha = entrada.streams.audio[0]
        trilha.thread_type = "AUTO"

        reamostrador = AudioResampler(format="s16", layout="mono", rate=TAXA_WHISPER)
        saida = av.open(str(destino), "w", format="wav")
        canal = saida.add_stream("pcm_s16le", rate=TAXA_WHISPER)
        canal.layout = "mono"

        amostras = 0
        try:
            for quadro in entrada.decode(audio=0):
                for convertido in _resample(reamostrador, quadro):
                    amostras += convertido.samples
                    for pacote in canal.encode(convertido):
                        saida.mux(pacote)
            for convertido in _resample(reamostrador, None):
                amostras += convertido.samples
                for pacote in canal.encode(convertido):
                    saida.mux(pacote)
            for pacote in canal.encode():
                saida.mux(pacote)
        finally:
            saida.close()

    if not amostras:
        raise SemAudio("A trilha de áudio está vazia.")

    return InfoAudio(
        segundos=round(amostras / TAXA_WHISPER, 2), taxa=TAXA_WHISPER, canais=1
    )


def _resample(reamostrador, quadro) -> list:
    """Uniformiza o retorno do resampler entre as versoes do PyAV.

    Versoes novas devolvem uma lista; as antigas, um quadro ou None. Sem isso o
    codigo quebra em uma das duas e o sintoma (audio truncado) e dificil de ler.
    """
    resultado = reamostrador.resample(quadro)
    if resultado is None:
        return []
    if isinstance(resultado, list):
        return resultado
    return [resultado]


def _para_jpeg(quadro, largura_maxima: int = LARGURA_MAXIMA) -> bytes:
    """Codifica um quadro em JPEG na memoria, sem passar por Pillow."""
    import av

    largura, altura = quadro.width, quadro.height
    if largura > largura_maxima:
        altura = max(2, int(altura * largura_maxima / largura) // 2 * 2)
        largura = largura_maxima

    buffer = io.BytesIO()
    saida = av.open(buffer, "w", format="mjpeg")
    canal = saida.add_stream("mjpeg", rate=1)
    canal.width, canal.height, canal.pix_fmt = largura, altura, "yuvj420p"
    try:
        convertido = quadro.reformat(width=largura, height=altura, format="yuvj420p")
        for pacote in canal.encode(convertido):
            saida.mux(pacote)
        for pacote in canal.encode():
            saida.mux(pacote)
    finally:
        saida.close()
    return buffer.getvalue()


def _instante(quadro, indice: int, fallback_fps: float) -> float:
    """Segundo em que o quadro aparece, com plano B quando o pts vem vazio."""
    if quadro.time is not None:
        return float(quadro.time)
    if quadro.pts is not None and quadro.time_base:
        return float(quadro.pts * quadro.time_base)
    return indice / max(fallback_fps, 1.0)


def nome_do_quadro(posicao: int, segundo: float) -> str:
    """0002 + 74.6s -> '0002_01m15s.jpg'.

    Deriva do MESMO formatar_tempo que a transcricao usa, e nao de int(segundo).
    Truncar aqui e arredondar la fazia 74,6s virar '01m14s' no arquivo e '01:15'
    no prompt - e o cruzamento entre fala e imagem, que e a razao de existir do
    formato, deixava de fechar.
    """
    return f"{posicao:04d}_{formatar_tempo(segundo).replace(':', 'm')}s.jpg"


def selecionar(
    candidatos: list[tuple[float, float, bytes]],
    reserva: list[tuple[float, bytes]],
    maximo: int,
    minimo: int,
    intervalo: float,
) -> list[tuple[float, float, bytes]]:
    """Escolhe os quadros finais: as mudancas mais fortes, completadas pelo piso.

    Separada da decodificacao porque e aqui que mora a regra - e regra se testa
    com numeros, nao com um .mp4 de doze segundos.

    O piso so entra onde nao atrapalha: um quadro de reserva a menos de
    `intervalo` de um ja escolhido seria quase a mesma foto, gastando uma vaga
    (e a atencao de quem le) sem acrescentar tela nenhuma.
    """
    escolhidos = sorted(candidatos, key=lambda c: c[1], reverse=True)[:maximo]

    alvo = min(minimo, maximo)
    if len(escolhidos) < alvo:
        for segundo, jpeg in reserva:
            if len(escolhidos) >= alvo:
                break
            if any(abs(segundo - outro[0]) < intervalo for outro in escolhidos):
                continue
            escolhidos.append((segundo, 0.0, jpeg))

    escolhidos.sort(key=lambda c: c[0])
    return escolhidos


def extrair_quadros(
    video: Path,
    pasta: Path,
    maximo: int = 16,
    minimo: int = 4,
    intervalo: float = 2.0,
    limiar: float = LIMIAR_PADRAO,
) -> list[Quadro]:
    """Salva os quadros em que a tela realmente mudou.

    Amostragem fixa geraria dezenas de fotos identicas de uma tela parada e
    ainda assim perderia o modal que abriu entre duas amostras. Aqui cada quadro
    amostrado e comparado com o anterior; sobrevivem os que mudaram acima do
    limiar e estao a pelo menos `intervalo` segundos do candidato anterior.

    Se nada mudou (narracao sobre tela imovel), `minimo` quadros espalhados pelo
    video entram como piso - e melhor um contexto ralo que nenhum.
    """
    pasta.mkdir(parents=True, exist_ok=True)
    total_segundos = duracao(video)

    candidatos: list[tuple[float, float, bytes]] = []  # (segundo, mudanca, jpeg)
    reserva: list[tuple[float, bytes]] = []  # piso uniforme, usado so se faltar

    passo_reserva = (total_segundos / minimo) if (total_segundos and minimo) else 0.0
    proxima_reserva = 0.0
    proxima_amostra = 0.0
    anterior: np.ndarray | None = None
    ultimo_candidato: float | None = None

    with _abrir(video) as container:
        if not container.streams.video:
            raise MidiaInvalida("Este arquivo não tem trilha de vídeo.")
        trilha = container.streams.video[0]
        trilha.thread_type = "AUTO"
        fps = float(trilha.average_rate or 25)

        for indice, quadro in enumerate(container.decode(video=0)):
            segundo = _instante(quadro, indice, fps)
            if segundo + 1e-6 < proxima_amostra:
                continue
            proxima_amostra = segundo + 1.0 / FPS_AMOSTRA

            miniatura = quadro.reformat(
                width=COMPARA_LARGURA, height=COMPARA_ALTURA, format="gray"
            ).to_ndarray()
            atual = miniatura.astype(np.int16)

            if anterior is None:
                mudanca = 1.0  # a tela de abertura sempre interessa
            else:
                mudanca = float(np.abs(atual - anterior).mean()) / 255.0
            anterior = atual

            if passo_reserva and segundo + 1e-6 >= proxima_reserva and len(reserva) < minimo:
                reserva.append((segundo, _para_jpeg(quadro)))
                proxima_reserva += passo_reserva

            longe = ultimo_candidato is None or (segundo - ultimo_candidato) >= intervalo
            if mudanca >= limiar and longe:
                candidatos.append((segundo, mudanca, _para_jpeg(quadro)))
                ultimo_candidato = segundo
                if len(candidatos) > TETO_CANDIDATOS:
                    # Descarta a mudanca mais fraca; as fortes e a de abertura ficam.
                    fraco = min(range(len(candidatos)), key=lambda i: candidatos[i][1])
                    candidatos.pop(fraco)

    escolhidos = selecionar(candidatos, reserva, maximo, minimo, intervalo)

    quadros: list[Quadro] = []
    for posicao, (segundo, mudanca, jpeg) in enumerate(escolhidos, start=1):
        caminho = pasta / nome_do_quadro(posicao, segundo)
        caminho.write_bytes(jpeg)
        quadros.append(
            Quadro(segundo=round(segundo, 2), caminho=caminho, mudanca=round(mudanca, 4))
        )

    log.debug("%d quadros salvos de %d candidatos", len(quadros), len(candidatos))
    return quadros
