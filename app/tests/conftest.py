"""Videos sinteticos para os testes.

Gerar o video na hora, em vez de versionar um .mp4 de amostra, mantem o repo
leve e deixa cada teste dizer exatamente onde a cena muda - o que e justamente
o que precisamos medir.
"""

from __future__ import annotations

import math
import sys
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

LARGURA, ALTURA, FPS = 320, 180, 10


def _tela(cor: tuple[int, int, int]) -> np.ndarray:
    quadro = np.zeros((ALTURA, LARGURA, 3), dtype=np.uint8)
    quadro[:, :] = cor
    return quadro


def _escrever(caminho: Path, cortes: dict[int, tuple[int, int, int]], segundos: int, com_audio: bool) -> Path:
    import av

    saida = av.open(str(caminho), "w")
    video = saida.add_stream("mpeg4", rate=FPS)
    video.width, video.height, video.pix_fmt = LARGURA, ALTURA, "yuv420p"

    audio = None
    if com_audio:
        audio = saida.add_stream("aac", rate=44100)
        audio.layout = "mono"

    cor = (0, 0, 0)
    for indice in range(segundos * FPS):
        segundo = indice // FPS
        if indice % FPS == 0 and segundo in cortes:
            cor = cortes[segundo]
        quadro = av.VideoFrame.from_ndarray(_tela(cor), format="rgb24")
        quadro.pts = indice
        quadro.time_base = Fraction(1, FPS)
        for pacote in video.encode(quadro):
            saida.mux(pacote)
    for pacote in video.encode():
        saida.mux(pacote)

    if audio is not None:
        total = 44100 * segundos
        bloco = 1024
        amostras = np.arange(total, dtype=np.float32)
        onda = (0.3 * np.sin(2 * math.pi * 440 * amostras / 44100) * 32767).astype(np.int16)
        pts = 0
        for inicio in range(0, total - bloco, bloco):
            pedaco = onda[inicio : inicio + bloco].reshape(1, -1)
            frame = av.AudioFrame.from_ndarray(pedaco, format="s16", layout="mono")
            frame.sample_rate = 44100
            frame.pts = pts
            frame.time_base = Fraction(1, 44100)
            pts += bloco
            for pacote in audio.encode(frame):
                saida.mux(pacote)
        for pacote in audio.encode():
            saida.mux(pacote)

    saida.close()
    return caminho


@pytest.fixture
def video_com_cenas(tmp_path: Path) -> Path:
    """12s de video: a tela troca de cor em 0s, 4s e 8s. Com trilha de audio."""
    cortes = {0: (10, 10, 10), 4: (220, 220, 220), 8: (30, 120, 200)}
    return _escrever(tmp_path / "cenas.mp4", cortes, segundos=12, com_audio=True)


@pytest.fixture
def video_parado(tmp_path: Path) -> Path:
    """8s de tela imovel - nenhuma mudanca de cena para detectar."""
    return _escrever(tmp_path / "parado.mp4", {0: (80, 80, 80)}, segundos=8, com_audio=True)


@pytest.fixture
def video_mudo(tmp_path: Path) -> Path:
    """6s de video sem trilha de audio nenhuma."""
    cortes = {0: (10, 10, 10), 3: (240, 240, 240)}
    return _escrever(tmp_path / "mudo.mp4", cortes, segundos=6, com_audio=False)
