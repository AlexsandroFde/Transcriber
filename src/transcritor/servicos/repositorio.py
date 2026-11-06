"""Persistência local (SQLite) do histórico de tarefas e de transcrições.

O banco fica em `<pasta de dados>/transcritor.db`. Ele guarda apenas o índice: os resultados
continuam sendo os arquivos da pasta de cada transcrição (o .json é a fonte de verdade).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

VERSAO_ESQUEMA = 1

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS tarefas (
    id TEXT PRIMARY KEY,
    tipo TEXT NOT NULL,
    estado TEXT NOT NULL,
    titulo TEXT NOT NULL,
    criada_em TEXT NOT NULL,
    iniciada_em TEXT,
    concluida_em TEXT,
    parametros TEXT NOT NULL,
    progresso TEXT,
    resultado TEXT,
    erro TEXT,
    origem_id TEXT,
    arquivo_log TEXT
);
CREATE INDEX IF NOT EXISTS tarefas_criada ON tarefas(criada_em);
CREATE TABLE IF NOT EXISTS transcricoes (
    id TEXT PRIMARY KEY,
    caminho_json TEXT NOT NULL UNIQUE,
    resumo TEXT NOT NULL,
    registrado_em TEXT NOT NULL,
    atualizado_em TEXT NOT NULL,
    mtime_json REAL,
    tarefa_id TEXT
);
"""

_JSON_TAREFA = ("parametros", "progresso", "resultado", "erro")


class Repositorio:
    def __init__(self, arquivo: Path):
        self.arquivo = Path(arquivo)
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conexao() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(_ESQUEMA)
            c.execute(f"PRAGMA user_version={VERSAO_ESQUEMA}")

    @contextmanager
    def _conexao(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            con = sqlite3.connect(self.arquivo, timeout=15)
            con.row_factory = sqlite3.Row
            try:
                yield con
                con.commit()
            finally:
                con.close()

    # -- tarefas -----------------------------------------------------------

    def salvar_tarefa(self, registro: dict[str, Any]) -> None:
        linha = dict(registro)
        for k in _JSON_TAREFA:
            linha[k] = json.dumps(linha.get(k), ensure_ascii=False, default=str) if linha.get(k) is not None else None
        colunas = ("id", "tipo", "estado", "titulo", "criada_em", "iniciada_em", "concluida_em", "parametros",
                   "progresso", "resultado", "erro", "origem_id", "arquivo_log")
        valores = [linha.get(c) for c in colunas]
        with self._conexao() as c:
            c.execute(f"INSERT OR REPLACE INTO tarefas ({', '.join(colunas)}) VALUES ({', '.join('?' * len(colunas))})",
                      valores)

    def listar_tarefas(self) -> list[dict[str, Any]]:
        with self._conexao() as c:
            linhas = c.execute("SELECT * FROM tarefas ORDER BY criada_em").fetchall()
        saida = []
        for l in linhas:
            d = dict(l)
            for k in _JSON_TAREFA:
                d[k] = json.loads(d[k]) if d.get(k) else None
            saida.append(d)
        return saida

    def remover_tarefa(self, tarefa_id: str) -> None:
        with self._conexao() as c:
            c.execute("DELETE FROM tarefas WHERE id = ?", (tarefa_id,))

    def podar_tarefas(self, manter: int) -> None:
        """Mantém só as `manter` tarefas mais recentes que já terminaram."""
        with self._conexao() as c:
            c.execute(
                "DELETE FROM tarefas WHERE estado NOT IN ('na_fila', 'em_andamento') AND id NOT IN ("
                "SELECT id FROM tarefas ORDER BY criada_em DESC LIMIT ?)", (manter,))

    # -- transcrições ------------------------------------------------------

    def salvar_transcricao(self, id_: str, caminho_json: str, resumo: dict[str, Any], registrado_em: str,
                           atualizado_em: str, mtime_json: float | None, tarefa_id: str | None) -> None:
        with self._conexao() as c:
            c.execute(
                "INSERT INTO transcricoes (id, caminho_json, resumo, registrado_em, atualizado_em, mtime_json, tarefa_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET caminho_json=excluded.caminho_json, "
                "resumo=excluded.resumo, atualizado_em=excluded.atualizado_em, mtime_json=excluded.mtime_json, "
                "tarefa_id=COALESCE(excluded.tarefa_id, transcricoes.tarefa_id)",
                (id_, caminho_json, json.dumps(resumo, ensure_ascii=False), registrado_em, atualizado_em, mtime_json,
                 tarefa_id))

    def _transcricao(self, linha: sqlite3.Row | None) -> dict[str, Any] | None:
        if linha is None:
            return None
        d = dict(linha)
        d["resumo"] = json.loads(d["resumo"])
        return d

    def obter_transcricao(self, id_: str) -> dict[str, Any] | None:
        with self._conexao() as c:
            return self._transcricao(c.execute("SELECT * FROM transcricoes WHERE id = ?", (id_,)).fetchone())

    def listar_transcricoes(self) -> list[dict[str, Any]]:
        with self._conexao() as c:
            linhas = c.execute("SELECT * FROM transcricoes ORDER BY atualizado_em DESC").fetchall()
        return [self._transcricao(l) for l in linhas]  # type: ignore[misc]

    def remover_transcricao(self, id_: str) -> bool:
        with self._conexao() as c:
            return c.execute("DELETE FROM transcricoes WHERE id = ?", (id_,)).rowcount > 0
