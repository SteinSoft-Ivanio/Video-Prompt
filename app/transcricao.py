"""Transcreve um WAV e devolve segmentos COM marcador de tempo.

O tempo e o que amarra as duas metades do prompt: sem ele, o Claude recebe um
bloco de fala e um punhado de imagens soltas, e nao tem como saber que o
"olha, aqui da erro" acontece na mesma hora do quadro que mostra o erro.

Roda o faster-whisper no proprio processo. Deliberadamente NAO conversa com o
servidor do Whatsapp-Transcritor: aquele endpoint devolve so o texto colado,
sem os tempos, e depender dele deixaria o comando refem de outra janela aberta.
"""

from __future__ import annotations

import logging
import os
import site
import sys
import sysconfig
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

MODELO_PADRAO = os.getenv("VP_MODEL", "large-v3-turbo")
IDIOMA_PADRAO = os.getenv("VP_LANGUAGE", "pt")

# Ordem deliberada: int8 antes de float16. Placas sem tensor cores (a serie GTX
# 16, por exemplo) nao aceleram float16. Onde int8_float16 nao existir, float16
# vale; e se a GPU nao aparecer, sobra a CPU.
_BACKENDS = (
    ("cuda", "int8_float16"),
    ("cuda", "float16"),
    ("cpu", "int8"),
)

_DLLS_NVIDIA = (
    "nvidia/cublas/bin",
    "nvidia/cudnn/bin",
    "nvidia/cuda_nvrtc/bin",
    "nvidia/cuda_runtime/bin",
)


class FalhaNaTranscricao(Exception):
    """O modelo nao carregou ou o audio nao decodificou."""


@dataclass(frozen=True)
class Segmento:
    inicio: float
    fim: float
    texto: str


@dataclass(frozen=True)
class Transcricao:
    segmentos: tuple[Segmento, ...]
    idioma: str
    segundos: float
    dispositivo: str
    demorou: float

    @property
    def texto(self) -> str:
        return " ".join(s.texto for s in self.segmentos if s.texto).strip()

    def cronometrada(self) -> str:
        """A fala com marcador de minuto, uma linha por segmento."""
        from midia import formatar_tempo

        return "\n".join(
            f"[{formatar_tempo(s.inicio)}] {s.texto}" for s in self.segmentos if s.texto
        )


def _registrar_dlls_nvidia() -> None:
    """Poe as DLLs de CUDA/cuDNN instaladas via pip ao alcance do CTranslate2.

    Copiado do Whatsapp-Transcritor de proposito: e uma correcao especifica de
    Windows que custou depuracao, e importa-la de outro projeto amarraria este
    comando a existencia daquele repositorio.

    O detalhe que engana: `os.add_dll_directory` sozinho NAO resolve. Ele so
    vale para DLLs que o proprio Python carrega; o CTranslate2 pede
    cublas64_12.dll via LoadLibrary, que ignora esses diretorios e consulta o
    PATH. O sintoma e traicoeiro - o modelo carrega em "cuda" sem reclamar e so
    estoura na primeira transcricao. Por isso mexemos nos dois lugares.
    """
    if sys.platform != "win32":
        return

    raizes: list[Path] = []
    try:
        raizes.extend(Path(p) for p in site.getsitepackages())
    except AttributeError:  # ambientes virtuais antigos
        pass
    purelib = sysconfig.get_paths().get("purelib")
    if purelib:
        raizes.append(Path(purelib))

    achadas: list[str] = []
    for raiz in raizes:
        for sub in _DLLS_NVIDIA:
            diretorio = raiz / sub
            if not diretorio.is_dir():
                continue
            caminho = str(diretorio)
            if caminho in achadas:
                continue
            achadas.append(caminho)
            try:
                os.add_dll_directory(caminho)
            except OSError as exc:
                log.warning("Nao consegui registrar %s: %s", caminho, exc)

    if achadas:
        os.environ["PATH"] = os.pathsep.join([*achadas, os.environ.get("PATH", "")])
    else:
        log.warning("Nenhuma DLL NVIDIA encontrada - a transcricao vai cair para CPU.")


def _beam(modelo: str) -> int:
    """O turbo tem 4 camadas de decoder; o large-v3 tem 32.

    Num decoder tao raso, alargar o beam custa proporcionalmente caro e rende
    pouco. No large-v3 vale o contrario.
    """
    return 1 if "turbo" in modelo else 5


def carregar(modelo: str = MODELO_PADRAO):
    """Sobe o modelo, tentando GPU e degradando para CPU. Devolve (modelo, dispositivo)."""
    _registrar_dlls_nvidia()
    from faster_whisper import WhisperModel  # import tardio: puxa o CTranslate2

    ultimo: Exception | None = None
    for dispositivo, precisao in _BACKENDS:
        try:
            carregado = WhisperModel(modelo, device=dispositivo, compute_type=precisao)
        except Exception as exc:  # noqa: BLE001 - queremos degradar, nao quebrar
            ultimo = exc
            log.warning("%s/%s indisponivel (%s).", dispositivo, precisao, exc)
            continue
        return carregado, dispositivo

    raise FalhaNaTranscricao(f"Nenhum backend carregou o modelo {modelo}: {ultimo}")


def transcrever(
    wav: Path,
    idioma: str | None = IDIOMA_PADRAO,
    modelo: str = MODELO_PADRAO,
    glossario: str | None = None,
) -> Transcricao:
    """Transcreve o WAV inteiro e devolve os segmentos com tempo.

    `glossario` vira o initial_prompt do Whisper - util para enviesar a grafia
    de nomes proprios do cliente (marcas, nomes de tela do sistema antigo).
    """
    if not wav.exists() or wav.stat().st_size == 0:
        raise FalhaNaTranscricao("O áudio extraído ficou vazio.")

    carregado, dispositivo = carregar(modelo)
    comeco = time.monotonic()
    try:
        segmentos, info = carregado.transcribe(
            str(wav),
            language=idioma,
            vad_filter=True,  # corta silencio; gravacao de tela tem muito
            beam_size=_beam(modelo),
            initial_prompt=glossario or None,
        )
        lista = tuple(
            Segmento(
                inicio=round(float(s.start), 2),
                fim=round(float(s.end), 2),
                texto=s.text.strip(),
            )
            for s in segmentos
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("Falha ao decodificar o audio")
        raise FalhaNaTranscricao(f"Não consegui transcrever o áudio: {exc}") from exc

    return Transcricao(
        segmentos=lista,
        idioma=getattr(info, "language", idioma or "?"),
        segundos=round(getattr(info, "duration", 0.0), 2),
        dispositivo=dispositivo,
        demorou=round(time.monotonic() - comeco, 2),
    )
