"""Glossário: nomes de pessoas, siglas e termos técnicos que orientam o reconhecimento.

Formato do arquivo (o mesmo desde a versão 1.0): um termo por linha, vários termos na
mesma linha separados por `;`, e o que vier depois de `#` é ignorado (comentário).
"""

from __future__ import annotations

from pathlib import Path

from ..erros import EntradaInvalida, NaoEncontrado


def interpretar(texto: str) -> list[str]:
    termos: list[str] = []
    for linha in texto.splitlines():
        linha = linha.split("#", 1)[0].strip()
        if linha:
            termos.extend(t.strip() for t in linha.split(";") if t.strip())
    return termos


def ler_texto(caminho: str | Path) -> str:
    arq = Path(caminho).expanduser()
    if not arq.is_file():
        raise NaoEncontrado(f"Arquivo de glossário não encontrado: {arq}",
                            dica="Confira o caminho do arquivo .txt do glossário.",
                            codigo="glossario_nao_encontrado")
    try:
        return arq.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as e:
        raise EntradaInvalida(f"O glossário {arq.name} não está em UTF-8.",
                              dica="Salve o arquivo como texto UTF-8 (no Bloco de Notas: Salvar como > Codificação UTF-8).",
                              codigo="glossario_codificacao") from e


def ler_arquivo(caminho: str | Path | None) -> list[str]:
    """Termos de um arquivo de glossário (lista vazia sem caminho)."""
    if not caminho:
        return []
    return interpretar(ler_texto(caminho))


def combinar(termos: list[str] | None = None, texto: str | None = None, arquivo: str | Path | None = None) -> list[str]:
    """Junta as três formas de informar o glossário, nesta ordem, sem reordenar nem remover repetições
    (a montagem das hotwords já ignora repetições; manter a lista igual preserva o cache)."""
    saida = [t.strip() for t in (termos or []) if t and t.strip()]
    if texto:
        saida += interpretar(texto)
    saida += ler_arquivo(arquivo)
    return saida
