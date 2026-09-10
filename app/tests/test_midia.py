"""Testes da extracao de audio e de quadros."""

from __future__ import annotations

from pathlib import Path

import pytest

import midia


def test_audio_vira_wav_16k_mono(video_com_cenas: Path, tmp_path: Path) -> None:
    destino = tmp_path / "audio.wav"
    info = midia.extrair_audio_wav(video_com_cenas, destino)

    assert destino.exists() and destino.stat().st_size > 0
    assert info.taxa == 16000
    assert info.canais == 1
    # 12s de video; o encoder corta alguns blocos no fim, entao aceitamos folga.
    assert 10.5 <= info.segundos <= 12.5


def test_video_mudo_nao_gera_wav(video_mudo: Path, tmp_path: Path) -> None:
    with pytest.raises(midia.SemAudio):
        midia.extrair_audio_wav(video_mudo, tmp_path / "audio.wav")


def test_quadros_caem_nas_trocas_de_tela(video_com_cenas: Path, tmp_path: Path) -> None:
    quadros = midia.extrair_quadros(video_com_cenas, tmp_path / "frames", maximo=8)

    assert quadros, "nenhum quadro extraido"
    tempos = [q.segundo for q in quadros]
    assert tempos == sorted(tempos), "os quadros devem sair em ordem cronologica"

    # A tela troca em 4s e em 8s; cada troca precisa ter um quadro por perto.
    for troca in (4.0, 8.0):
        assert any(abs(t - troca) <= 1.0 for t in tempos), f"nada perto de {troca}s: {tempos}"

    for quadro in quadros:
        assert quadro.caminho.exists()
        assert quadro.caminho.read_bytes()[:3] == b"\xff\xd8\xff", "nao e JPEG"


def test_respeita_o_teto_de_quadros(video_com_cenas: Path, tmp_path: Path) -> None:
    quadros = midia.extrair_quadros(video_com_cenas, tmp_path / "frames", maximo=2)
    assert len(quadros) <= 2


def test_tela_parada_ainda_rende_um_minimo(video_parado: Path, tmp_path: Path) -> None:
    """Sem mudanca nenhuma, o piso garante cobertura ao longo do video."""
    quadros = midia.extrair_quadros(video_parado, tmp_path / "frames", maximo=8, minimo=3)

    assert len(quadros) >= 3
    tempos = [q.segundo for q in quadros]
    assert max(tempos) - min(tempos) >= 2.0, f"quadros amontoados: {tempos}"


def test_nome_do_arquivo_carrega_o_tempo(video_com_cenas: Path, tmp_path: Path) -> None:
    quadros = midia.extrair_quadros(video_com_cenas, tmp_path / "frames", maximo=4)
    primeiro = quadros[0]
    # O nome precisa amarrar o quadro ao mesmo eixo de tempo da transcricao.
    assert primeiro.caminho.name.startswith("0001_")
    assert primeiro.caminho.suffix == ".jpg"


# --- regras puras: sem decodificar video, com os numeros que quebram na pratica ---


def test_nome_do_quadro_usa_o_mesmo_arredondamento_do_marcador() -> None:
    """Truncar no nome e arredondar no marcador desalinha fala e imagem.

    74,6s vira '01:15' na tabela do prompt. Se o arquivo se chamasse '01m14s',
    quem le o prompt nao conseguiria casar um com o outro.
    """
    assert midia.nome_do_quadro(2, 74.6) == "0002_01m15s.jpg"
    assert midia.nome_do_quadro(1, 17.5) == "0001_00m18s.jpg"
    assert midia.nome_do_quadro(10, 0.0) == "0010_00m00s.jpg"

    for segundo in (0.0, 9.4, 17.5, 74.6, 125.49):
        nome = midia.nome_do_quadro(1, segundo)
        assert nome.endswith(midia.formatar_tempo(segundo).replace(":", "m") + "s.jpg")


def test_piso_nao_encosta_num_quadro_ja_escolhido() -> None:
    """O quadro de reserva a 17,4s morre: ja ha um escolhido a 17,0s."""
    candidatos = [(0.0, 1.0, b"a"), (9.0, 0.5, b"b"), (17.0, 0.4, b"c")]
    reserva = [(0.0, b"r0"), (8.7, b"r1"), (17.4, b"r2"), (26.1, b"r3")]

    escolhidos = midia.selecionar(candidatos, reserva, maximo=16, minimo=4, intervalo=2.0)

    tempos = [c[0] for c in escolhidos]
    assert 17.4 not in tempos, f"quadro de piso colou no vizinho: {tempos}"
    assert 26.1 in tempos, "o piso longe de todos deveria entrar"
    for anterior, seguinte in zip(tempos, tempos[1:]):
        assert seguinte - anterior >= 2.0


def test_piso_so_entra_quando_falta_quadro() -> None:
    candidatos = [(t, 0.5, b"x") for t in (0.0, 5.0, 10.0, 15.0, 20.0)]
    escolhidos = midia.selecionar(candidatos, [(2.0, b"r")], maximo=16, minimo=4, intervalo=2.0)

    assert len(escolhidos) == 5
    assert 2.0 not in [c[0] for c in escolhidos]


def test_teto_vence_o_piso() -> None:
    """Pedir maximo=2 e minimo=4 nao pode devolver 4 quadros."""
    escolhidos = midia.selecionar(
        [(0.0, 1.0, b"a")], [(10.0, b"r"), (20.0, b"r"), (30.0, b"r")],
        maximo=2, minimo=4, intervalo=2.0,
    )
    assert len(escolhidos) == 2


def test_selecionar_devolve_em_ordem_cronologica() -> None:
    candidatos = [(30.0, 0.2, b"c"), (0.0, 1.0, b"a"), (15.0, 0.9, b"b")]
    tempos = [c[0] for c in midia.selecionar(candidatos, [], maximo=16, minimo=1, intervalo=2.0)]
    assert tempos == [0.0, 15.0, 30.0]
