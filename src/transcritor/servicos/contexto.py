"""Montagem dos serviços da aplicação (um único lugar onde as dependências são ligadas)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..config import Configuracoes
from .configuracao import ServicoConfiguracao
from .diagnostico import ServicoDiagnostico
from .eventos import Barramento
from .midia import ServicoEnvios
from .repositorio import Repositorio
from .tarefas import FabricaProcesso, GerenciadorTarefas
from .transcricoes import ServicoTranscricoes

log = logging.getLogger("transcritor.servicos")


@dataclass
class Servicos:
    config: Configuracoes
    modo: str
    repositorio: Repositorio
    barramento: Barramento
    tarefas: GerenciadorTarefas
    transcricoes: ServicoTranscricoes
    diagnostico: ServicoDiagnostico
    configuracao: ServicoConfiguracao
    envios: ServicoEnvios
    iniciado_em: datetime = field(default_factory=lambda: datetime.now().astimezone())
    verificar_ao_iniciar: bool = True
    _iniciado: bool = False

    def iniciar(self) -> None:
        if self._iniciado:
            return
        self._iniciado = True
        self.tarefas.iniciar()
        log.info("Serviços iniciados (modo %s)", self.modo)
        if self.verificar_ao_iniciar:
            try:
                self.diagnostico.verificar()
            except Exception:
                log.exception("Não foi possível iniciar a verificação do ambiente")

    def encerrar(self) -> None:
        if not self._iniciado:
            return
        self._iniciado = False
        log.info("Encerrando serviços...")
        self.barramento.encerrar()
        self.tarefas.encerrar()
        log.info("Serviços encerrados")

    def envio_em_uso(self, arquivo: Path) -> bool:
        alvo = os.path.normcase(str(arquivo.resolve()))
        return any(os.path.normcase(str(Path(t.parametros.get("arquivo", "")).resolve())) == alvo
                   for t in self.tarefas.ativas("transcricao") if t.parametros.get("arquivo"))


def criar_servicos(config: Configuracoes, modo: str = "servidor", fabrica_processo: FabricaProcesso | None = None,
                   verificar_ao_iniciar: bool = True) -> Servicos:
    config.garantir_pastas()
    repositorio = Repositorio(config.arquivo_banco)
    barramento = Barramento()
    tarefas = GerenciadorTarefas(config, repositorio, barramento, fabrica_processo)
    return Servicos(
        config=config, modo=modo, repositorio=repositorio, barramento=barramento, tarefas=tarefas,
        transcricoes=ServicoTranscricoes(config, repositorio, tarefas, barramento),
        diagnostico=ServicoDiagnostico(tarefas, barramento), configuracao=ServicoConfiguracao(config),
        envios=ServicoEnvios(config), verificar_ao_iniciar=verificar_ao_iniciar)
