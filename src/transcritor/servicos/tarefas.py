"""Gerenciamento de tarefas demoradas: fila, execução, progresso, cancelamento e histórico.

Cada tarefa roda em um processo trabalhador (ver `execucao.py`). As tarefas são organizadas
em pistas: transcrições rodam uma de cada vez (disputam a placa de vídeo), enquanto
verificações do ambiente e downloads de modelos rodam em uma pista própria, em paralelo.

Estados: na_fila -> em_andamento -> concluida | falhou | cancelada. Tarefas que estavam na
fila ou em andamento quando o programa foi fechado viram "interrompida" na próxima vez; uma
transcrição interrompida pode ser retomada, e as etapas já concluídas são reaproveitadas.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import Configuracoes
from ..erros import Conflito, Indisponivel, NaoEncontrado
from .contratos import ESTADOS_ATIVOS, ESTADOS_FINAIS, ErroTarefa, ProgressoTarefa, RegistroTarefa, Tarefa
from .eventos import Barramento
from .execucao import ProcessoTrabalhador
from .progresso import ETAPAS_POR_TIPO, Acompanhamento, progresso_inicial
from .repositorio import Repositorio

log = logging.getLogger("transcritor.tarefas")

PISTAS = {"transcricao": "processamento", "verificacao": "manutencao", "download_modelos": "manutencao"}
INTERVALO_PUBLICACAO_S = 0.25
_CAMINHO = re.compile(r"^([A-Za-z]:[\\/]|\\\\|/)\S")

FabricaProcesso = Callable[..., Any]
AoConcluir = Callable[["TarefaInterna", dict], dict]


def _agora() -> datetime:
    return datetime.now().astimezone()


class TarefaInterna:
    """Estado mutável de uma tarefa (protegido pelo lock do gerenciador)."""

    def __init__(self, id_: str, tipo: str, titulo: str, parametros: dict, execucao: dict | None,
                 origem_id: str | None, arquivo_log: Path):
        self.id = id_
        self.tipo = tipo
        self.titulo = titulo
        self.parametros = parametros  # como armazenado (sem segredos)
        self.execucao = execucao  # enviado ao trabalhador (pode conter o token); nunca persistido
        self.origem_id = origem_id
        self.arquivo_log = arquivo_log
        self.estado = "na_fila"
        self.criada_em = _agora()
        self.iniciada_em: datetime | None = None
        self.concluida_em: datetime | None = None
        self.resultado: dict | None = None
        self.erro: dict | None = None
        self.acompanhamento: Acompanhamento | None = None
        self.progresso_salvo: ProgressoTarefa | None = None
        self.processo: ProcessoTrabalhador | None = None
        self.cancelar_pedido = False
        self.interromper_pedido = False
        self.resultado_bruto: dict | None = None
        self.erro_bruto: dict | None = None
        self.ultima_publicacao = 0.0
        self.linhas_log = 0
        # O registro recebe linhas de duas threads (saída e erros do trabalhador). No Windows, o modo de
        # acréscimo não é atômico entre handles diferentes: sem a trava, uma linha pode sobrescrever outra.
        self.trava_log = threading.Lock()

    def progresso(self) -> ProgressoTarefa:
        if self.acompanhamento is not None:
            return self.acompanhamento.instantaneo()
        return self.progresso_salvo or progresso_inicial(self.tipo)

    def para_registro(self) -> dict[str, Any]:
        return {
            "id": self.id, "tipo": self.tipo, "estado": self.estado, "titulo": self.titulo,
            "criada_em": self.criada_em.isoformat(),
            "iniciada_em": self.iniciada_em.isoformat() if self.iniciada_em else None,
            "concluida_em": self.concluida_em.isoformat() if self.concluida_em else None,
            "parametros": self.parametros, "progresso": self.progresso().model_dump(mode="json"),
            "resultado": self.resultado, "erro": self.erro, "origem_id": self.origem_id,
            "arquivo_log": str(self.arquivo_log),
        }

    @classmethod
    def de_registro(cls, r: dict[str, Any]) -> "TarefaInterna":
        t = cls(r["id"], r["tipo"], r["titulo"], r.get("parametros") or {}, None, r.get("origem_id"),
                Path(r.get("arquivo_log") or ""))
        t.estado = r["estado"]
        t.criada_em = datetime.fromisoformat(r["criada_em"])
        t.iniciada_em = datetime.fromisoformat(r["iniciada_em"]) if r.get("iniciada_em") else None
        t.concluida_em = datetime.fromisoformat(r["concluida_em"]) if r.get("concluida_em") else None
        t.resultado = r.get("resultado")
        t.erro = r.get("erro")
        if r.get("progresso"):
            try:
                t.progresso_salvo = ProgressoTarefa.model_validate(r["progresso"])
            except Exception:
                t.progresso_salvo = None
        return t


class _Pista:
    def __init__(self, nome: str):
        self.nome = nome
        self.fila: deque[str] = deque()
        self.condicao = threading.Condition()
        self.thread: threading.Thread | None = None


class GerenciadorTarefas:
    def __init__(self, config: Configuracoes, repositorio: Repositorio, barramento: Barramento,
                 fabrica_processo: FabricaProcesso | None = None):
        self.config = config
        self.repositorio = repositorio
        self.barramento = barramento
        self._fabrica = fabrica_processo or self._fabrica_padrao
        self._tarefas: dict[str, TarefaInterna] = {}
        self._lock = threading.RLock()
        self._pistas = {n: _Pista(n) for n in set(PISTAS.values())}
        self._ao_concluir: dict[str, AoConcluir] = {}
        self._ativo = False

    def _fabrica_padrao(self, comando: dict, ao_evento, ao_texto) -> ProcessoTrabalhador:
        return ProcessoTrabalhador(comando, ao_evento=ao_evento, ao_texto=ao_texto,
                                   executavel=self.config.comando_trabalhador or None)

    def ao_concluir(self, tipo: str, funcao: AoConcluir) -> None:
        """Registra o pós-processamento de um tipo (ex.: incluir a transcrição no histórico)."""
        self._ao_concluir[tipo] = funcao

    # -- ciclo de vida ------------------------------------------------------

    def iniciar(self) -> None:
        self.config.pasta_logs_tarefas.mkdir(parents=True, exist_ok=True)
        with self._lock:
            for r in self.repositorio.listar_tarefas():
                t = TarefaInterna.de_registro(r)
                if t.estado in ESTADOS_ATIVOS:
                    self._marcar_interrompida(t)
                    self.repositorio.salvar_tarefa(t.para_registro())
                self._tarefas[t.id] = t
            self._ativo = True
        for pista in self._pistas.values():
            pista.thread = threading.Thread(target=self._laco, args=(pista,), name=f"pista-{pista.nome}", daemon=True)
            pista.thread.start()

    def _marcar_interrompida(self, t: TarefaInterna) -> None:
        t.estado = "interrompida"
        t.concluida_em = t.concluida_em or _agora()
        t.erro = ErroTarefa(
            codigo="interrompida", mensagem="O Transcritor foi fechado antes do fim desta tarefa.",
            dica="As etapas concluídas foram guardadas. Retome para continuar de onde parou." if t.tipo == "transcricao"
            else "Execute a tarefa de novo.").model_dump()
        if t.acompanhamento is not None:
            t.acompanhamento.encerrar("interrompida")
            t.progresso_salvo = t.acompanhamento.instantaneo()
            t.acompanhamento = None
        elif t.progresso_salvo is not None:
            for e in t.progresso_salvo.etapas:
                if e.estado == "em_andamento":
                    e.estado = "interrompida"
            t.progresso_salvo.etapa_atual = None
            t.progresso_salvo.restante_estimado_s = None

    def encerrar(self, espera_s: float = 10.0) -> None:
        """Interrompe o que estiver rodando (estado "interrompida") e para as pistas."""
        with self._lock:
            if not self._ativo:
                return
            self._ativo = False
            for t in self._tarefas.values():
                if t.estado == "na_fila":
                    self._marcar_interrompida(t)
                    self._salvar(t)
                elif t.estado == "em_andamento":
                    t.interromper_pedido = True
                    if t.processo is not None:
                        t.processo.encerrar()
        for pista in self._pistas.values():
            with pista.condicao:
                pista.fila.clear()
                pista.condicao.notify_all()
        limite = time.monotonic() + espera_s
        for pista in self._pistas.values():
            if pista.thread is not None:
                pista.thread.join(timeout=max(0.1, limite - time.monotonic()))

    # -- consultas -----------------------------------------------------------

    def _instantaneo(self, t: TarefaInterna) -> Tarefa:
        posicao = None
        if t.estado == "na_fila":
            pista = self._pistas[PISTAS[t.tipo]]
            with pista.condicao:
                try:
                    posicao = list(pista.fila).index(t.id) + 1
                except ValueError:
                    posicao = None
        return Tarefa(
            id=t.id, tipo=t.tipo, estado=t.estado, titulo=t.titulo, criada_em=t.criada_em,
            iniciada_em=t.iniciada_em, concluida_em=t.concluida_em, progresso=t.progresso(),
            parametros=t.parametros, resultado=t.resultado, erro=ErroTarefa(**t.erro) if t.erro else None,
            origem_id=t.origem_id, posicao_fila=posicao, pode_cancelar=t.estado in ESTADOS_ATIVOS,
            pode_repetir=t.estado in ESTADOS_FINAIS,
        )

    def _interna(self, tarefa_id: str) -> TarefaInterna:
        t = self._tarefas.get(tarefa_id)
        if t is None:
            raise NaoEncontrado(f"Tarefa não encontrada: {tarefa_id}", codigo="tarefa_nao_encontrada",
                                dica="A tarefa pode ter sido removida do histórico.")
        return t

    def obter(self, tarefa_id: str) -> Tarefa:
        with self._lock:
            return self._instantaneo(self._interna(tarefa_id))

    def parametros(self, tarefa_id: str) -> tuple[str, dict]:
        with self._lock:
            t = self._interna(tarefa_id)
            return t.tipo, dict(t.parametros)

    def listar(self, tipo: str | None = None, estados: list[str] | None = None) -> list[Tarefa]:
        with self._lock:
            ts = [t for t in self._tarefas.values()
                  if (tipo is None or t.tipo == tipo) and (not estados or t.estado in estados)]
            ts.sort(key=lambda t: t.criada_em, reverse=True)
            return [self._instantaneo(t) for t in ts]

    def ativas(self, tipo: str | None = None) -> list[Tarefa]:
        return self.listar(tipo=tipo, estados=list(ESTADOS_ATIVOS))

    def ler_log(self, tarefa_id: str, desde: int = 0) -> RegistroTarefa:
        with self._lock:
            t = self._interna(tarefa_id)
            arquivo = t.arquivo_log
        linhas: list[str] = []
        if arquivo.is_file():
            linhas = arquivo.read_text(encoding="utf-8", errors="replace").splitlines()
        desde = max(0, desde)
        return RegistroTarefa(tarefa_id=tarefa_id, linhas=linhas[desde:], proxima=len(linhas), caminho=str(arquivo))

    # -- comandos -------------------------------------------------------------

    def criar(self, tipo: str, titulo: str, parametros: dict, execucao: dict | None = None,
              origem_id: str | None = None) -> Tarefa:
        if tipo not in PISTAS:
            raise ValueError(f"Tipo de tarefa desconhecido: {tipo}")
        with self._lock:
            if not self._ativo:
                raise Indisponivel("O Transcritor está sendo encerrado e não aceita novas tarefas.",
                                   codigo="encerrando")
            id_ = uuid.uuid4().hex[:12]
            t = TarefaInterna(id_, tipo, titulo, parametros, execucao if execucao is not None else parametros,
                              origem_id, self.config.pasta_logs_tarefas / f"{id_}.log")
            self._tarefas[id_] = t
            self._salvar(t)
            self._podar()
        pista = self._pistas[PISTAS[tipo]]
        with pista.condicao:
            pista.fila.append(id_)
            pista.condicao.notify()
        self._publicar(t, forcar=True)
        log.info("Tarefa %s criada (%s: %s)", id_, tipo, titulo)
        return self.obter(id_)

    def cancelar(self, tarefa_id: str) -> Tarefa:
        with self._lock:
            t = self._interna(tarefa_id)
            if t.estado not in ESTADOS_ATIVOS:
                raise Conflito(f"A tarefa já terminou (estado: {t.estado}).", codigo="tarefa_encerrada",
                               dica="Só é possível cancelar tarefas na fila ou em andamento.")
            t.cancelar_pedido = True
            if t.estado == "na_fila":
                pista = self._pistas[PISTAS[t.tipo]]
                with pista.condicao:
                    if t.id in pista.fila:
                        pista.fila.remove(t.id)
                t.estado = "cancelada"
                t.concluida_em = _agora()
                self._salvar(t)
                self._registrar_linha(t, "Tarefa cancelada antes de começar.")
            elif t.processo is not None:
                self._registrar_linha(t, "Cancelamento pedido. Encerrando o processamento...")
                t.processo.encerrar()
        self._publicar(t, forcar=True)
        return self.obter(tarefa_id)

    def remover(self, tarefa_id: str) -> None:
        with self._lock:
            t = self._interna(tarefa_id)
            if t.estado in ESTADOS_ATIVOS:
                raise Conflito("Não é possível remover uma tarefa na fila ou em andamento.",
                               codigo="tarefa_ativa", dica="Cancele a tarefa antes de removê-la.")
            del self._tarefas[tarefa_id]
            self.repositorio.remover_tarefa(tarefa_id)
            try:
                t.arquivo_log.unlink(missing_ok=True)
            except OSError:
                pass
        self.barramento.publicar("tarefa_removida", {"id": tarefa_id})

    def _podar(self) -> None:
        finais = sorted((t for t in self._tarefas.values() if t.estado in ESTADOS_FINAIS),
                        key=lambda t: t.criada_em, reverse=True)
        for t in finais[self.config.max_tarefas_historico:]:
            self._tarefas.pop(t.id, None)
            try:
                t.arquivo_log.unlink(missing_ok=True)
            except OSError:
                pass
        self.repositorio.podar_tarefas(self.config.max_tarefas_historico)

    # -- execução ------------------------------------------------------------

    def _laco(self, pista: _Pista) -> None:
        while True:
            with pista.condicao:
                while self._ativo and not pista.fila:
                    pista.condicao.wait(timeout=1.0)
                if not self._ativo:
                    return
                tarefa_id = pista.fila.popleft()
            with self._lock:
                t = self._tarefas.get(tarefa_id)
                if t is None or t.estado != "na_fila":
                    continue
            try:
                self._executar(t)
            except Exception:  # pragma: no cover - proteção da pista
                log.exception("Falha inesperada ao executar a tarefa %s", tarefa_id)

    def _executar(self, t: TarefaInterna) -> None:
        with self._lock:
            t.estado = "em_andamento"
            t.iniciada_em = _agora()
            t.acompanhamento = Acompanhamento(ETAPAS_POR_TIPO.get(t.tipo, ()))
            t.acompanhamento.iniciar()
            self._salvar(t)
        self._registrar_linha(t, f"Iniciando: {t.titulo}")
        self._publicar(t, forcar=True)

        comando = {"tipo": t.tipo, "parametros": t.execucao or t.parametros}
        codigo: int | None = None
        try:
            processo = self._fabrica(comando, ao_evento=lambda e: self._ao_evento(t, e),
                                     ao_texto=lambda linha: self._registrar_linha(t, linha))
            with self._lock:
                t.processo = processo
                if t.interromper_pedido or t.cancelar_pedido:
                    raise _Abortar()
            processo.iniciar()
            with self._lock:
                if t.interromper_pedido or t.cancelar_pedido:  # pedido chegou durante o início
                    processo.encerrar()
            codigo = processo.aguardar()
        except _Abortar:
            codigo = None
        except Exception as e:
            log.exception("Não foi possível iniciar o processo trabalhador")
            t.erro_bruto = {"codigo": "trabalhador_indisponivel",
                            "mensagem": f"Não foi possível iniciar o processamento: {e}",
                            "dica": "Reinstale o Transcritor (instalar.bat) e tente de novo."}
        finally:
            t.execucao = None  # descarta o token, se havia

        with self._lock:
            t.processo = None
            if t.interromper_pedido:
                estado = "interrompida"
            elif t.cancelar_pedido:
                estado = "cancelada"
            elif codigo == 0 and t.resultado_bruto is not None:
                estado = "concluida"
            else:
                estado = "falhou"
        resultado = t.resultado_bruto
        if estado == "concluida" and t.tipo in self._ao_concluir:
            try:
                resultado = self._ao_concluir[t.tipo](t, dict(resultado or {}))
            except Exception as e:
                log.exception("Falha no pós-processamento da tarefa %s", t.id)
                estado = "falhou"
                t.erro_bruto = {"codigo": "pos_processamento", "mensagem": str(e),
                                "dica": "Os arquivos podem ter sido gerados mesmo assim; confira a pasta de saída."}
        with self._lock:
            t.concluida_em = _agora()
            if estado == "interrompida":
                self._marcar_interrompida(t)
            else:
                t.estado = estado
                if t.acompanhamento is not None:
                    t.acompanhamento.encerrar(estado)
                    t.progresso_salvo = t.acompanhamento.instantaneo()
                    t.acompanhamento = None
                if estado == "concluida":
                    t.resultado = resultado
                    t.erro = None
                elif estado == "falhou":
                    bruto = t.erro_bruto or {
                        "codigo": "trabalhador_encerrado",
                        "mensagem": f"O processamento terminou inesperadamente (código {codigo}).",
                        "dica": "Veja o registro técnico. Se o problema continuar, escolha o dispositivo CPU em "
                                "Opções avançadas."}
                    t.erro = ErroTarefa(codigo=bruto.get("codigo") or "erro_inesperado",
                                        mensagem=bruto.get("mensagem") or "Erro inesperado.",
                                        dica=bruto.get("dica")).model_dump()
            self._salvar(t)
        mensagens = {"concluida": "Concluída.", "falhou": f"Falhou: {(t.erro or {}).get('mensagem', '')}",
                     "cancelada": "Cancelada.", "interrompida": "Interrompida."}
        self._registrar_linha(t, mensagens.get(t.estado, t.estado))
        log.info("Tarefa %s: %s", t.id, t.estado)
        self._publicar(t, forcar=True)

    def _ao_evento(self, t: TarefaInterna, evento: dict) -> None:
        tipo = evento.get("evento")
        mudou_etapa = False
        with self._lock:
            ac = t.acompanhamento
            if tipo == "etapa" and ac is not None:
                ac.etapa(int(evento.get("numero", 1)), evento.get("texto"), evento.get("situacao", "executando"))
                mudou_etapa = True
            elif tipo == "progresso" and ac is not None:
                ac.progresso(float(evento.get("fracao", 0.0)))
            elif tipo == "log":
                texto = str(evento.get("mensagem", "")).strip()
                # Linhas que são só um caminho (a lista de arquivos gerados) não servem como "mensagem atual".
                if ac is not None and evento.get("nivel") in ("INFO", "WARNING") and texto and not _CAMINHO.match(texto):
                    ac.informar(texto)
            elif tipo == "resultado":
                t.resultado_bruto = evento.get("dados") or {}
            elif tipo == "erro":
                t.erro_bruto = {k: evento.get(k) for k in ("codigo", "mensagem", "dica")}
        if tipo == "etapa":
            self._registrar_linha(t, f"[{evento.get('numero')}/{evento.get('total')}] {evento.get('texto', '')}")
        elif tipo == "log":
            nivel = evento.get("nivel", "INFO")
            prefixo = {"WARNING": "AVISO ", "ERROR": "ERRO ", "DEBUG": "DEPURAÇÃO "}.get(nivel, "")
            self._registrar_linha(t, prefixo + evento.get("mensagem", ""))
        elif tipo == "erro" and evento.get("detalhe"):
            self._registrar_linha(t, "ERRO " + str(evento.get("mensagem")))
            for linha in str(evento["detalhe"]).rstrip().splitlines():
                self._registrar_linha(t, "    " + linha, publicar=False)
        if mudou_etapa:
            with self._lock:
                self._salvar(t)
        self._publicar(t, forcar=mudou_etapa)

    # -- registro e publicação ---------------------------------------------------

    def _registrar_linha(self, t: TarefaInterna, texto: str, publicar: bool = True) -> None:
        linha = f"{datetime.now():%H:%M:%S}  {texto}"
        with t.trava_log:
            try:
                t.arquivo_log.parent.mkdir(parents=True, exist_ok=True)
                with open(t.arquivo_log, "a", encoding="utf-8") as f:
                    f.write(linha + "\n")
            except OSError:
                log.exception("Não foi possível gravar o registro da tarefa %s", t.id)
            numero = t.linhas_log
            t.linhas_log += 1
        if publicar:
            self.barramento.publicar("log", {"tarefa_id": t.id, "numero": numero, "linha": linha})

    def _salvar(self, t: TarefaInterna) -> None:
        try:
            self.repositorio.salvar_tarefa(t.para_registro())
        except Exception:
            log.exception("Não foi possível salvar a tarefa %s", t.id)

    def _publicar(self, t: TarefaInterna, forcar: bool = False) -> None:
        agora = time.monotonic()
        if not forcar and agora - t.ultima_publicacao < INTERVALO_PUBLICACAO_S:
            return
        t.ultima_publicacao = agora
        with self._lock:
            dados = self._instantaneo(t).model_dump(mode="json")
        self.barramento.publicar("tarefa", dados)


class _Abortar(Exception):
    pass
