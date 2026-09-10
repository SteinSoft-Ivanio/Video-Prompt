"""Testes do pipeline inteiro.

O caso rapido usa um video MUDO de proposito: sem trilha de audio o orquestrador
pula a transcricao, entao o teste exercita todo o resto (extracao, escolha de
quadros, montagem, escrita) sem carregar 1,6 GB de modelo nem ocupar a GPU.

O caso com audio existe, mas fica atras do marcador `slow`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import videoprompt


def test_video_mudo_gera_prompt_completo(video_mudo: Path, tmp_path: Path) -> None:
    destino = videoprompt.processar(video_mudo, "bug", tmp_path / "saida")

    assert destino.name == "prompt.md"
    texto = destino.read_text(encoding="utf-8")

    assert "sem trilha de áudio" in texto.lower()
    assert "## Narração" not in texto
    assert (tmp_path / "saida" / "frames").is_dir()

    # Todo caminho de imagem citado no prompt precisa existir de fato.
    for quadro in (tmp_path / "saida" / "frames").glob("*.jpg"):
        assert str(quadro.resolve()) in texto

    assert not (tmp_path / "saida" / "audio.wav").exists(), "video mudo nao deve deixar wav"


def test_modo_sistema_muda_a_tarefa(video_mudo: Path, tmp_path: Path) -> None:
    destino = videoprompt.processar(video_mudo, "sistema", tmp_path / "saida")
    assert "campos visíveis" in destino.read_text(encoding="utf-8").lower()


def test_observacao_chega_ao_arquivo(video_mudo: Path, tmp_path: Path) -> None:
    destino = videoprompt.processar(
        video_mudo, "bug", tmp_path / "saida", observacao="Cliente: Acme, ambiente de homologação."
    )
    assert "Cliente: Acme, ambiente de homologação." in destino.read_text(encoding="utf-8")


def test_arquivo_inexistente_para_o_programa(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        videoprompt._validar(str(tmp_path / "nao-existe.mp4"))


def test_caminho_colado_com_aspas_funciona(video_mudo: Path) -> None:
    """Ctrl+V do Explorer traz aspas; elas nao podem virar parte do caminho."""
    assert videoprompt._validar(f'"{video_mudo}"') == video_mudo.resolve()


def test_pasta_de_saida_nao_fica_em_temp(tmp_path: Path) -> None:
    pasta = videoprompt._saida_padrao(Path("C:/videos/erro do cliente.mp4"))
    assert "videoprompt" in pasta.parts
    assert pasta.name.startswith("erro-do-cliente-")


@pytest.mark.slow
def test_pipeline_com_audio_de_verdade(video_com_cenas: Path, tmp_path: Path) -> None:
    """Carrega o Whisper e transcreve. Rode com: pytest -m slow"""
    destino = videoprompt.processar(video_com_cenas, "bug", tmp_path / "saida")
    texto = destino.read_text(encoding="utf-8")

    assert (tmp_path / "saida" / "audio.wav").exists()
    assert "## Quadros" in texto
