"""Configurações centralizadas do Transcritor.

Todos os caminhos, portas e limites usados pela aplicação são definidos aqui. Os valores
padrão funcionam sem nenhuma configuração; quem precisar ajustar algo pode usar variáveis
de ambiente com o prefixo ``TRANSCRITOR_``:

=============================  ===========================================================
Variável                       Efeito
=============================  ===========================================================
TRANSCRITOR_HOST               Endereço em que a API escuta (padrão: 127.0.0.1).
TRANSCRITOR_PORTA              Porta preferida da API (padrão: 8765; 0 escolhe uma livre).
TRANSCRITOR_PASTA_DADOS        Banco de dados, registros (logs) e arquivos enviados.
TRANSCRITOR_PASTA_CONFIG       Token do Hugging Face e glossário padrão.
TRANSCRITOR_PASTA_MODELOS      Modelos de diarização baixados pelo programa.
TRANSCRITOR_GLOSSARIO          Arquivo do glossário padrão.
TRANSCRITOR_NIVEL_LOG          DEBUG, INFO (padrão), WARNING ou ERROR.
TRANSCRITOR_ORIGENS            Origens extras aceitas pela API (separadas por vírgula).
TRANSCRITOR_HOSTS              Nomes de host extras aceitos pela API (separados por vírgula).
=============================  ===========================================================

As variáveis TRANSCRITOR_FFMPEG e TRANSCRITOR_HF_TOKEN continuam valendo (ver ``ambiente``).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

NOME_APLICATIVO = "Transcritor"
ID_APLICATIVO = "transcritor"
PORTA_PADRAO = 8765
PREFIXO_API = "/api/v1"


def _env(nome: str) -> str | None:
    valor = os.environ.get(f"TRANSCRITOR_{nome}")
    return valor.strip() if valor and valor.strip() else None


def _lista_env(nome: str) -> tuple[str, ...]:
    valor = _env(nome)
    return tuple(v.strip() for v in valor.split(",") if v.strip()) if valor else ()


def _pasta_config_padrao() -> Path:
    base = os.environ.get("APPDATA") if sys.platform == "win32" else os.environ.get("XDG_CONFIG_HOME")
    return (Path(base) if base else Path.home() / ".config") / ID_APLICATIVO


def _pasta_dados_padrao() -> Path:
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / ID_APLICATIVO
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / ID_APLICATIVO


def _pasta_modelos_padrao() -> Path:
    # Mesmo local usado desde a versão 1.0 (os modelos já baixados continuam valendo).
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / ID_APLICATIVO / "modelos"
    return Path.home() / ".cache" / ID_APLICATIVO / "modelos"


def pasta_programa() -> Path | None:
    """Pasta do projeto (onde fica o pyproject.toml), quando o programa roda a partir dela."""
    raiz = Path(__file__).resolve().parents[2]
    return raiz if (raiz / "pyproject.toml").is_file() else None


def pasta_web() -> Path:
    """Arquivos estáticos da interface gráfica."""
    return Path(__file__).resolve().parent / "web"


def _glossario_padrao(pasta_config: Path) -> Path:
    """Compatível com o transcrever.bat: `glossario.txt` na pasta do programa, se existir."""
    programa = pasta_programa()
    if programa is not None and (programa / "glossario.txt").is_file():
        return programa / "glossario.txt"
    return pasta_config / "glossario.txt"


@dataclass(frozen=True)
class Configuracoes:
    host: str
    porta: int
    pasta_config: Path
    pasta_dados: Path
    pasta_modelos: Path
    arquivo_glossario: Path
    nivel_log: str = "INFO"
    origens_extras: tuple[str, ...] = ()
    hosts_extras: tuple[str, ...] = ()
    # Histórico de tarefas mantido no banco (as transcrições concluídas não entram neste limite).
    max_tarefas_historico: int = 300
    # Linhas de registro mantidas em memória por tarefa (o arquivo guarda tudo).
    max_linhas_log_memoria: int = 400
    tamanho_maximo_envio: int = 50 * 1024**3
    # Comando do processo trabalhador; substituível em testes.
    comando_trabalhador: tuple[str, ...] = field(default_factory=tuple)

    @property
    def arquivo_token(self) -> Path:
        return self.pasta_config / "hf_token.txt"

    @property
    def arquivo_banco(self) -> Path:
        return self.pasta_dados / "transcritor.db"

    @property
    def pasta_logs(self) -> Path:
        return self.pasta_dados / "logs"

    @property
    def pasta_logs_tarefas(self) -> Path:
        return self.pasta_logs / "tarefas"

    @property
    def pasta_envios(self) -> Path:
        return self.pasta_dados / "envios"

    @property
    def pasta_webview(self) -> Path:
        return self.pasta_dados / "webview"

    @property
    def arquivo_instancia(self) -> Path:
        return self.pasta_dados / "instancia.json"

    def com(self, **mudancas) -> "Configuracoes":
        return replace(self, **mudancas)

    def garantir_pastas(self) -> None:
        for pasta in (self.pasta_config, self.pasta_dados, self.pasta_logs, self.pasta_logs_tarefas, self.pasta_envios):
            pasta.mkdir(parents=True, exist_ok=True)


def carregar() -> Configuracoes:
    """Lê as configurações do ambiente (sem cache: útil em testes)."""
    pasta_config = Path(_env("PASTA_CONFIG")) if _env("PASTA_CONFIG") else _pasta_config_padrao()
    porta_txt = _env("PORTA")
    try:
        porta = int(porta_txt) if porta_txt is not None else PORTA_PADRAO
    except ValueError:
        porta = PORTA_PADRAO
    nivel = (_env("NIVEL_LOG") or "INFO").upper()
    if nivel not in ("DEBUG", "INFO", "WARNING", "ERROR"):
        nivel = "INFO"
    return Configuracoes(
        host=_env("HOST") or "127.0.0.1",
        porta=porta,
        pasta_config=pasta_config,
        pasta_dados=Path(_env("PASTA_DADOS")) if _env("PASTA_DADOS") else _pasta_dados_padrao(),
        pasta_modelos=Path(_env("PASTA_MODELOS")) if _env("PASTA_MODELOS") else _pasta_modelos_padrao(),
        arquivo_glossario=Path(_env("GLOSSARIO")) if _env("GLOSSARIO") else _glossario_padrao(pasta_config),
        nivel_log=nivel,
        origens_extras=_lista_env("ORIGENS"),
        hosts_extras=_lista_env("HOSTS"),
    )


_ATUAL: Configuracoes | None = None


def obter() -> Configuracoes:
    """Configurações do processo (lidas uma vez)."""
    global _ATUAL
    if _ATUAL is None:
        _ATUAL = carregar()
    return _ATUAL


def definir(config: Configuracoes) -> None:
    """Substitui as configurações do processo (inicializador, servidor e testes)."""
    global _ATUAL
    _ATUAL = config
