"""Testes da montagem do prompt.md.

Sao testes de texto puro: nenhum video, nenhum modelo. O que importa aqui e o
contrato com quem vai ler o arquivo - caminhos absolutos, tempos alinhados e a
instrucao certa para cada modo.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import prompt
from midia import Quadro
from transcricao import Segmento, Transcricao


@pytest.fixture
def quadros(tmp_path: Path) -> list[Quadro]:
    pasta = tmp_path / "frames"
    pasta.mkdir()
    dados = [(0.0, "0001_00m00s.jpg"), (74.5, "0002_01m14s.jpg")]
    saida = []
    for segundo, nome in dados:
        caminho = pasta / nome
        caminho.write_bytes(b"\xff\xd8\xff")
        saida.append(Quadro(segundo=segundo, caminho=caminho, mudanca=0.4))
    return saida


@pytest.fixture
def fala() -> Transcricao:
    return Transcricao(
        segmentos=(
            Segmento(0.0, 3.2, "Ó, deixa eu te mostrar o problema."),
            Segmento(74.5, 78.0, "Aqui ele estoura esse erro."),
        ),
        idioma="pt",
        segundos=90.0,
        dispositivo="cuda",
        demorou=8.4,
    )


def test_modo_bug_pede_demanda_de_correcao(quadros, fala, tmp_path) -> None:
    texto = prompt.montar("bug", tmp_path / "erro.mp4", 90.0, quadros, fala)

    assert "reproduzir" in texto.lower()
    assert "levantamento" not in texto.lower()


def test_modo_sistema_pede_levantamento(quadros, fala, tmp_path) -> None:
    texto = prompt.montar("sistema", tmp_path / "legado.mp4", 90.0, quadros, fala)

    assert "telas" in texto.lower()
    assert "campos" in texto.lower()
    assert "reproduzir" not in texto.lower()


def test_caminhos_dos_quadros_sao_absolutos(quadros, fala, tmp_path) -> None:
    """O Claude Code abre a imagem pelo caminho; relativo quebraria fora da pasta."""
    texto = prompt.montar("bug", tmp_path / "erro.mp4", 90.0, quadros, fala)

    for quadro in quadros:
        assert str(quadro.caminho.resolve()) in texto


def test_fala_e_quadro_compartilham_o_marcador(quadros, fala, tmp_path) -> None:
    texto = prompt.montar("bug", tmp_path / "erro.mp4", 90.0, quadros, fala)

    # 74.5s aparece como 01:14 tanto na narracao quanto na lista de quadros.
    assert texto.count("01:14") >= 2
    assert "[00:00] Ó, deixa eu te mostrar o problema." in texto


def test_video_mudo_nao_inventa_narracao(quadros, tmp_path) -> None:
    texto = prompt.montar("bug", tmp_path / "mudo.mp4", 90.0, quadros, None)

    assert "sem trilha de áudio" in texto.lower() or "sem narração" in texto.lower()
    assert "## Narração" not in texto


def test_observacao_do_usuario_entra_no_prompt(quadros, fala, tmp_path) -> None:
    texto = prompt.montar(
        "bug", tmp_path / "erro.mp4", 90.0, quadros, fala, observacao="É o cliente Acme."
    )

    assert "É o cliente Acme." in texto


def test_modo_desconhecido_reclama(quadros, fala, tmp_path) -> None:
    with pytest.raises(ValueError):
        prompt.montar("qualquer", tmp_path / "x.mp4", 90.0, quadros, fala)


def test_linha_de_envio_aponta_para_o_arquivo(tmp_path) -> None:
    """A linha colada no Claude Code precisa caber em UMA linha e ter o caminho."""
    destino = tmp_path / "saida" / "prompt.md"
    linha = prompt.linha_de_envio(destino)

    assert "\n" not in linha
    assert str(destino.resolve()) in linha
