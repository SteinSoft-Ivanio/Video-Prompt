"""Orquestra: recebe o caminho de um video e deixa um prompt.md pronto na mesa.

Este e o unico modulo que fala com o usuario. Os outros tres nao imprimem nada e
nao perguntam nada - e o que permite testa-los sem simular um terminal.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

import envio
import midia
import prompt as montador
import transcricao as fala

EXTENSOES = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".wmv", ".flv", ".mpg", ".mpeg"}


def _saida_padrao(video: Path) -> Path:
    """%LOCALAPPDATA%\\videoprompt\\<video>-<hora>. Persistente e achavel.

    Deliberadamente fora de %TEMP%: a limpeza do Windows apagaria a pasta no meio
    de uma analise, e as imagens sao referenciadas por caminho absoluto dentro do
    prompt.md - some a pasta, o prompt vira papel picado.
    """
    raiz = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    carimbo = dt.datetime.now().strftime("%H%M%S")
    nome = "".join(c if c.isalnum() or c in "-_" else "-" for c in video.stem)[:60]
    return raiz / "videoprompt" / f"{nome or 'video'}-{carimbo}"


def _passo(numero: int, total: int, rotulo: str) -> None:
    print(f"  [{numero}/{total}] {rotulo}", flush=True)


def _detalhe(texto: str) -> None:
    print(f"        {texto}", flush=True)


def _validar(caminho: str) -> Path:
    video = Path(caminho.strip().strip('"')).expanduser()
    if not video.exists():
        raise SystemExit(f"\n  [ERRO] Arquivo não encontrado: {video}\n")
    if not video.is_file():
        raise SystemExit(f"\n  [ERRO] Isso é uma pasta, não um vídeo: {video}\n")
    if video.suffix.lower() not in EXTENSOES:
        _detalhe(f"aviso: extensão {video.suffix or '(nenhuma)'} incomum, tentando mesmo assim")
    return video.resolve()


def processar(
    video: Path,
    modo: str,
    pasta: Path,
    maximo_quadros: int = 16,
    observacao: str | None = None,
    glossario: str | None = None,
) -> Path:
    """Roda o pipeline inteiro e devolve o caminho do prompt.md."""
    pasta.mkdir(parents=True, exist_ok=True)
    total_segundos = midia.duracao(video)

    _passo(1, 3, "áudio")
    wav = pasta / "audio.wav"
    transcrito = None
    try:
        info = midia.extrair_audio_wav(video, wav)
        _detalhe(f"{midia.formatar_tempo(info.segundos)} extraídos, transcrevendo...")
        _detalhe("(a primeira execução carrega o modelo, ~30s)")
        transcrito = fala.transcrever(wav, glossario=glossario)
        _detalhe(
            f"{len(transcrito.segmentos)} trechos em {transcrito.demorou}s "
            f"({transcrito.dispositivo})"
        )
    except midia.SemAudio as exc:
        _detalhe(f"{exc} Seguindo só com as imagens.")
        wav.unlink(missing_ok=True)
    except fala.FalhaNaTranscricao as exc:
        _detalhe(f"falhou: {exc}")
        _detalhe("Seguindo só com as imagens.")

    _passo(2, 3, "quadros")
    quadros = midia.extrair_quadros(video, pasta / "frames", maximo=maximo_quadros)
    _detalhe(f"{len(quadros)} quadros de mudança de tela")

    _passo(3, 3, "prompt")
    texto = montador.montar(modo, video, total_segundos, quadros, transcrito, observacao)
    destino = pasta / "prompt.md"
    destino.write_text(texto, encoding="utf-8")
    _detalhe(f"{len(texto.split())} palavras")

    return destino


def _menu(destino: Path) -> None:
    linha = montador.linha_de_envio(destino)
    while True:
        print()
        print("  [E] enviar ao Claude Code   [C] copiar   [P] abrir pasta   [A] abrir prompt.md   [Q] sair")
        try:
            escolha = input("  > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return

        if escolha in {"q", ""}:
            return
        if escolha == "c":
            print("  copiado." if envio.copiar(linha) else "  não consegui copiar.")
        elif escolha == "p":
            envio.abrir(destino.parent)
        elif escolha == "a":
            envio.abrir(destino)
        elif escolha == "e":
            _enviar(linha)
        else:
            print("  opção inválida.")


def _enviar(linha: str) -> None:
    lista = envio.alvos()
    if not lista:
        print("  Nenhuma sessão do Claude Code encontrada. Use [C] e cole você mesmo.")
        return

    print()
    for indice, alvo in enumerate(lista, start=1):
        nome = alvo.get("name") or alvo.get("folder") or alvo.get("id")
        print(f"    {indice}. {nome}  ({alvo.get('host', '?')})  {alvo.get('folder', '')}")
    try:
        escolhido = input("  sessão > ").strip()
    except (EOFError, KeyboardInterrupt):
        return
    if not escolhido.isdigit() or not (1 <= int(escolhido) <= len(lista)):
        print("  cancelado.")
        return

    resposta = envio.enviar(lista[int(escolhido) - 1].get("id", ""), linha)
    print("  enviado." if resposta.get("ok") else f"  falhou: {resposta.get('error')}")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    analisador = argparse.ArgumentParser(
        prog="videoprompt",
        description="Transforma um vídeo local em um prompt (narração + telas) para o Claude Code.",
    )
    analisador.add_argument("video", nargs="?", help="caminho do arquivo de vídeo")
    analisador.add_argument(
        "--modo", choices=montador.MODOS, default="bug",
        help="bug: problema relatado pelo cliente. sistema: levantamento do sistema antigo.",
    )
    analisador.add_argument("--frames", type=int, default=16, help="teto de quadros (padrão: 16)")
    analisador.add_argument("--saida", help="pasta de saída (padrão: %%LOCALAPPDATA%%\\videoprompt)")
    analisador.add_argument("--obs", help="contexto seu que entra no prompt")
    analisador.add_argument("--glossario", help="nomes próprios para o Whisper não errar a grafia")
    analisador.add_argument("--sem-menu", action="store_true", help="só gera e sai")
    args = analisador.parse_args(argv)

    caminho = args.video
    if not caminho:
        try:
            caminho = input("  Cole o caminho do vídeo: ")
        except (EOFError, KeyboardInterrupt):
            return 1

    video = _validar(caminho)
    pasta = Path(args.saida).expanduser() if args.saida else _saida_padrao(video)

    print()
    print(f"  Vídeo: {video}")
    print(f"  Modo:  {args.modo}")
    print()

    try:
        destino = processar(
            video, args.modo, pasta,
            maximo_quadros=args.frames, observacao=args.obs, glossario=args.glossario,
        )
    except midia.MidiaInvalida as exc:
        print(f"\n  [ERRO] {exc}\n")
        return 1

    print()
    print(f"  Pronto: {destino}")

    if args.sem_menu:
        print(f"\n  {montador.linha_de_envio(destino)}\n")
        return 0

    _menu(destino)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
