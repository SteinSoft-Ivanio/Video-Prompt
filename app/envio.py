"""Entrega a linha de comando pronta: area de transferencia ou sessao do Claude.

O envio direto reaproveita `sessions.py` e `dispatch.py` do Whatsapp-Transcritor,
que ja resolvem a parte chata (descobrir sessoes abertas, focar a janela, colar).
E uma dependencia OPCIONAL e por caminho: se o projeto vizinho nao estiver ali,
o menu perde a opcao de enviar e continua funcionando com o copiar - que resolve
o mesmo problema com um Ctrl+V a mais.
"""

from __future__ import annotations

import base64
import os
import subprocess
import sys
from pathlib import Path


def _pasta_do_transcritor() -> Path:
    """Onde procurar sessions.py/dispatch.py. VP_TRANSCRITOR sobrepoe o padrao."""
    manual = os.getenv("VP_TRANSCRITOR")
    if manual:
        return Path(manual)
    return Path(__file__).resolve().parents[2] / "Whatsapp-Transcritor" / "server"


def _carregar_ponte():
    """Importa sessions+dispatch do projeto vizinho, ou devolve None."""
    pasta = _pasta_do_transcritor()
    if not (pasta / "dispatch.py").is_file():
        return None
    caminho = str(pasta)
    if caminho not in sys.path:
        sys.path.append(caminho)
    try:
        import dispatch  # noqa: PLC0415
        import sessions  # noqa: PLC0415
    except Exception:  # noqa: BLE001 - vizinho quebrado nao pode derrubar este comando
        return None
    return sessions, dispatch


def alvos() -> list[dict]:
    """Sessoes do Claude Code abertas agora. Lista vazia = nenhuma, ou sem ponte."""
    ponte = _carregar_ponte()
    if ponte is None:
        return []
    sessions, _ = ponte
    try:
        return sessions.list_targets()
    except Exception:  # noqa: BLE001
        return []


def enviar(alvo_id: str, texto: str) -> dict:
    ponte = _carregar_ponte()
    if ponte is None:
        return {"ok": False, "error": "Envio indisponível: não achei o Whatsapp-Transcritor."}
    _, dispatch = ponte
    try:
        return dispatch.send_to_target(alvo_id, texto)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def copiar(texto: str) -> bool:
    """Poe o texto na area de transferencia, sem sujeira e sem acento trocado.

    O caminho obvio - `clip.exe` - nao serve, e as tres tentativas falham de
    jeitos diferentes: em UTF-8 ou UTF-16 sem BOM ele decodifica pela codepage do
    console e os acentos chegam trocados; com o BOM ele decodifica certo, mas
    deixa o proprio BOM como primeiro caractere do texto colado.

    Entao vai por Set-Clipboard, com o texto em base64 no argumento. O base64
    resolve dois problemas de uma vez: nao ha byte que a codepage possa
    interpretar mal, e nao ha aspas nem barra invertida de caminho do Windows
    para escapar na linha de comando.
    """
    codificado = base64.b64encode(texto.encode("utf-8")).decode("ascii")
    comando = (
        "Set-Clipboard -Value ([Text.Encoding]::UTF8.GetString("
        f"[Convert]::FromBase64String('{codificado}')))"
    )
    try:
        concluido = subprocess.run(  # noqa: S603 - executavel fixo, argumento em base64
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", comando],
            capture_output=True,
            timeout=15,
        )
        return concluido.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def abrir(caminho: Path) -> None:
    """Abre a pasta ou o arquivo no Explorer / aplicativo padrao."""
    try:
        os.startfile(str(Path(caminho).resolve()))  # noqa: S606 - Windows-only, caminho nosso
    except Exception:  # noqa: BLE001
        pass
