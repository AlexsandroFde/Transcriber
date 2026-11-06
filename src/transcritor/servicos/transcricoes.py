"""Casos de uso das transcrições: criar (tarefas), histórico, conteúdo, relatório, nomes e exportação.

A transcrição em si roda no processo trabalhador (`trabalhador.py`), que chama
`construir_opcoes` e `processamento.pipeline.processar`. Este serviço valida o pedido antes
de colocá-lo na fila, para que erros simples (arquivo inexistente, faixa de áudio que não
existe) apareçam na hora, e mantém o histórico das transcrições concluídas.
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime
from pathlib import Path

from ..config import Configuracoes
from ..erros import Conflito, EntradaInvalida, ErroCampo, ErroTranscritor, NaoEncontrado
from ..processamento.documento import (
    analisar_relatorio,
    arquivo_relatorio,
    carregar_transcricao,
    gerar_saidas,
    montar_documento,
)
from ..processamento.exportar import FORMATOS
from ..processamento.montagem import texto_bloco
from ..processamento.pipeline import Opcoes, pasta_de_saida
from ..processamento.relatorio import descrever_filtros
from . import glossario as glossario_mod
from . import participantes as participantes_mod
from .catalogo import EXTENSOES_VIDEO
from .contratos import (
    ArquivoGerado,
    AudioConferencia,
    BlocoTranscricao,
    CategoriaMencoes,
    ConteudoTranscricao,
    IndicadoresQualidade,
    ListaParticipantes,
    Mencao,
    OpcoesTranscricao,
    ParametrosTranscricao,
    ParticipanteConferencia,
    PedidoExportacao,
    PedidoNomes,
    PedidoTranscricao,
    PontoConferencia,
    ProcessamentoInfo,
    RelatorioConferencia,
    ResultadoExportacao,
    ResultadoNomes,
    SugestaoNome,
    Tarefa,
    TranscricaoDetalhe,
    TranscricaoResumo,
    TrechoTexto,
)
from .eventos import Barramento
from .midia import informacoes, resolver_arquivo
from .repositorio import Repositorio
from .tarefas import GerenciadorTarefas, TarefaInterna

log = logging.getLogger("transcritor.transcricoes")

_TIPOS_PONTO = {"trecho incerto": "incerto", "inaudível": "inaudivel", "descartado": "descartado"}


def construir_opcoes(params: OpcoesTranscricao) -> Opcoes:
    """Converte os parâmetros validados nas opções do processamento."""
    op = Opcoes(
        saida=Path(params.pasta_saida).expanduser() if params.pasta_saida else None,
        modelo=params.modelo,
        modelo_revisao=params.modelo_revisao,
        dispositivo=params.dispositivo,
        precisao=params.precisao,
        num_participantes=params.participantes,
        min_participantes=params.min_participantes,
        max_participantes=params.max_participantes,
        contexto=params.contexto,
        glossario=glossario_mod.combinar(params.glossario, params.glossario_texto, params.glossario_arquivo),
        preprocessamento=params.pre_processamento,
        faixa=params.faixa_audio,
        diarizacao=params.diarizacao,
        hf_token=params.hf_token.get_secret_value() if params.hf_token else None,
        revisao=params.revisao,
        literal=params.estilo == "literal",
        formatos=list(params.formatos),
        refazer=params.refazer,
        manter_audio=params.manter_audio,
        beam=params.beam,
        detalhado=params.detalhado,
    )
    if params.limiar_incerteza is not None:
        op.opcoes_revisao.limiar_sem_maioria = params.limiar_incerteza
    return op


def id_transcricao(caminho_json: Path) -> str:
    return hashlib.sha1(os.path.normcase(str(Path(caminho_json).resolve())).encode("utf-8")).hexdigest()[:16]


def _agora() -> str:
    return datetime.now().astimezone().isoformat()


def _mtime(caminho: Path) -> float | None:
    try:
        return caminho.stat().st_mtime
    except OSError:
        return None


class ServicoTranscricoes:
    def __init__(self, config: Configuracoes, repositorio: Repositorio, tarefas: GerenciadorTarefas,
                 barramento: Barramento):
        self.config = config
        self.repositorio = repositorio
        self.tarefas = tarefas
        self.barramento = barramento
        tarefas.ao_concluir("transcricao", self._ao_concluir)

    # -- criação ---------------------------------------------------------------

    def _validar_pasta_saida(self, pasta: str | None) -> None:
        if not pasta:
            return
        p = Path(pasta).expanduser()
        if p.exists() and not p.is_dir():
            raise EntradaInvalida(f"A pasta de saída indicada é um arquivo: {p}", codigo="pasta_saida_invalida",
                                  campos=[ErroCampo("pasta_saida", "Indique uma pasta, não um arquivo.")])
        if not p.is_absolute() or not Path(p.anchor).exists():
            raise EntradaInvalida(f"A pasta de saída não está em um disco disponível: {p}",
                                  codigo="pasta_saida_invalida",
                                  campos=[ErroCampo("pasta_saida", "Use um caminho completo, como C:\\Transcricoes.")])

    def _validar_arquivo(self, indice: int, caminho: str, opcoes: OpcoesTranscricao) -> Path:
        campo = f"arquivos[{indice}]"
        try:
            info = informacoes(caminho)
        except ErroTranscritor as e:
            raise EntradaInvalida(e.mensagem, dica=e.dica, codigo=e.codigo,
                                  campos=[ErroCampo(campo, e.mensagem)]) from e
        if not info.faixas_audio:
            msg = f"{info.nome} não possui faixa de áudio."
            raise EntradaInvalida(msg, codigo="sem_audio", dica="Escolha um vídeo ou áudio que tenha som gravado.",
                                  campos=[ErroCampo(campo, msg)])
        if opcoes.faixa_audio != "todas" and int(opcoes.faixa_audio) >= len(info.faixas_audio):
            msg = (f"{info.nome} tem {len(info.faixas_audio)} faixa(s) de áudio; a faixa {opcoes.faixa_audio} "
                   "não existe.")
            raise EntradaInvalida(msg, codigo="faixa_inexistente", campos=[ErroCampo("faixa_audio", msg)],
                                  dica="Escolha uma faixa entre 0 e "
                                       f"{len(info.faixas_audio) - 1} ou a opção de mixar todas.")
        return Path(info.caminho)

    def pastas_em_uso(self) -> dict[str, str]:
        """Pasta de saída (normalizada) -> id da tarefa de transcrição ativa que escreve nela."""
        em_uso: dict[str, str] = {}
        for t in self.tarefas.ativas("transcricao"):
            try:
                p = t.parametros
                pasta = pasta_de_saida(Path(p["arquivo"]), Path(p["pasta_saida"]) if p.get("pasta_saida") else None)
                em_uso[os.path.normcase(str(pasta))] = t.id
            except (KeyError, OSError):
                continue
        return em_uso

    def criar(self, pedido: PedidoTranscricao) -> list[Tarefa]:
        self._validar_pasta_saida(pedido.pasta_saida)
        if pedido.glossario_arquivo:
            try:
                glossario_mod.ler_arquivo(pedido.glossario_arquivo)
            except ErroTranscritor as e:
                raise EntradaInvalida(e.mensagem, dica=e.dica, codigo=e.codigo,
                                      campos=[ErroCampo("glossario_arquivo", e.mensagem)]) from e
        opcoes = OpcoesTranscricao.model_validate(pedido.model_dump(exclude={"arquivos"}))
        arquivos = [self._validar_arquivo(i, c, opcoes) for i, c in enumerate(pedido.arquivos)]
        saida = Path(pedido.pasta_saida).expanduser() if pedido.pasta_saida else None
        em_uso = self.pastas_em_uso()
        destinos: dict[str, int] = {}
        for i, arq in enumerate(arquivos):
            chave = os.path.normcase(str(pasta_de_saida(arq, saida)))
            if chave in em_uso:
                raise Conflito(f"{arq.name} já está na fila ou sendo transcrito.", codigo="transcricao_em_andamento",
                               dica="Acompanhe a tarefa existente em Atividades ou cancele-a antes de começar de novo.",
                               campos=[ErroCampo(f"arquivos[{i}]", "Já há uma tarefa para este arquivo.")])
            if chave in destinos:
                raise EntradaInvalida(f"{arq.name} aparece mais de uma vez (ou dois arquivos têm o mesmo nome e a "
                                      "mesma pasta de saída).", codigo="arquivo_repetido",
                                      campos=[ErroCampo(f"arquivos[{i}]", "Arquivo repetido.")])
            destinos[chave] = i
        criadas = []
        for arq in arquivos:
            params = ParametrosTranscricao(**opcoes.model_dump(), arquivo=str(arq))
            criadas.append(self.tarefas.criar("transcricao", arq.name, params.para_armazenar(),
                                              params.para_trabalhador()))
        return criadas

    def repetir(self, tarefa_id: str) -> Tarefa:
        tipo, parametros = self.tarefas.parametros(tarefa_id)
        if tipo != "transcricao":
            raise ValueError("repetir() do serviço de transcrições só trata transcrições")
        params = ParametrosTranscricao.model_validate(parametros)
        self._validar_pasta_saida(params.pasta_saida)
        arq = self._validar_arquivo(0, params.arquivo, params)
        chave = os.path.normcase(str(pasta_de_saida(arq, Path(params.pasta_saida) if params.pasta_saida else None)))
        if chave in self.pastas_em_uso():
            raise Conflito(f"{arq.name} já está na fila ou sendo transcrito.", codigo="transcricao_em_andamento")
        return self.tarefas.criar("transcricao", arq.name, params.para_armazenar(), params.para_trabalhador(),
                                  origem_id=tarefa_id)

    def _ao_concluir(self, tarefa: TarefaInterna, resultado: dict) -> dict:
        resumo = self.registrar(Path(resultado["caminho_json"]), tarefa.id)
        resultado["transcricao_id"] = resumo.id
        return resultado

    # -- histórico ---------------------------------------------------------------

    def _resumo_de_dados(self, dados: dict) -> dict:
        participantes = list(dict.fromkeys(b.exibicao for b in participantes_mod.basicos(dados)))
        try:
            pontos = len(analisar_relatorio(dados).pontos)
        except Exception:  # relatório é complementar; não impede o registro
            log.exception("Não foi possível analisar o relatório")
            pontos = 0
        arq = dados.get("arquivo", {})
        return {"nome": arq.get("nome", ""), "arquivo_origem": arq.get("caminho", ""),
                "duracao_s": arq.get("duracao"), "gerado_em": dados.get("gerado_em"),
                "participantes": participantes, "pontos_conferencia": pontos}

    def registrar(self, caminho_json: Path, tarefa_id: str | None = None) -> TranscricaoResumo:
        caminho_json = Path(caminho_json).resolve()
        dados = carregar_transcricao(caminho_json)
        id_ = id_transcricao(caminho_json)
        existente = self.repositorio.obter_transcricao(id_)
        agora = _agora()
        self.repositorio.salvar_transcricao(id_, str(caminho_json), self._resumo_de_dados(dados),
                                            existente["registrado_em"] if existente else agora, agora,
                                            _mtime(caminho_json), tarefa_id)
        self.barramento.publicar("transcricao", {"id": id_, "acao": "atualizada" if existente else "registrada"})
        return self._resumo(self.repositorio.obter_transcricao(id_))  # type: ignore[arg-type]

    def importar(self, caminho: str) -> tuple[TranscricaoResumo, bool]:
        arq = resolver_arquivo(caminho)
        if arq.suffix.lower() != ".json":
            raise EntradaInvalida(f"{arq.name} não é um arquivo .json.", codigo="json_invalido",
                                  dica="Escolha o arquivo .json que fica na pasta da transcrição.")
        try:
            carregar_transcricao(arq)
        except (ValueError, UnicodeDecodeError) as e:
            raise EntradaInvalida(f"{arq.name} não é um arquivo de transcrição do Transcritor.", codigo="json_invalido",
                                  dica="Escolha o arquivo .json gerado pelo Transcritor, na pasta da transcrição.") from e
        criada = self.repositorio.obter_transcricao(id_transcricao(arq)) is None
        return self.registrar(arq), criada

    def _resumo(self, registro: dict) -> TranscricaoResumo:
        caminho = Path(registro["caminho_json"])
        r = registro["resumo"]
        return TranscricaoResumo(
            id=registro["id"], nome=r.get("nome") or caminho.stem, arquivo_origem=r.get("arquivo_origem") or "",
            origem_disponivel=bool(r.get("arquivo_origem")) and Path(r["arquivo_origem"]).is_file(),
            pasta=str(caminho.parent), caminho_json=str(caminho), disponivel=caminho.is_file(),
            duracao_s=r.get("duracao_s"), gerado_em=r.get("gerado_em"),
            registrado_em=datetime.fromisoformat(registro["registrado_em"]),
            atualizado_em=datetime.fromisoformat(registro["atualizado_em"]),
            participantes=r.get("participantes") or [], pontos_conferencia=r.get("pontos_conferencia") or 0,
            tarefa_id=registro.get("tarefa_id"))

    def _atualizado(self, registro: dict) -> dict:
        """Relê o JSON se ele mudou desde o registro (nomes alterados pela linha de comando, por exemplo)."""
        caminho = Path(registro["caminho_json"])
        mtime = _mtime(caminho)
        if mtime is not None and registro.get("mtime_json") != mtime:
            try:
                dados = carregar_transcricao(caminho)
            except (OSError, ValueError):
                return registro
            self.repositorio.salvar_transcricao(registro["id"], str(caminho), self._resumo_de_dados(dados),
                                                registro["registrado_em"], _agora(), mtime, None)
            return self.repositorio.obter_transcricao(registro["id"]) or registro
        return registro

    def listar(self, busca: str | None = None) -> list[TranscricaoResumo]:
        itens = [self._resumo(self._atualizado(r)) for r in self.repositorio.listar_transcricoes()]
        if busca and busca.strip():
            alvo = busca.strip().casefold()
            itens = [i for i in itens if alvo in i.nome.casefold() or any(alvo in p.casefold() for p in i.participantes)]
        itens.sort(key=lambda i: i.atualizado_em, reverse=True)
        return itens

    def _registro(self, id_: str) -> dict:
        r = self.repositorio.obter_transcricao(id_)
        if r is None:
            raise NaoEncontrado(f"Transcrição não encontrada: {id_}", codigo="transcricao_nao_encontrada",
                                dica="Ela pode ter sido removida do histórico. Use \"Abrir transcrição\" para "
                                     "incluí-la de novo a partir do arquivo .json.")
        return self._atualizado(r)

    def caminho_json(self, id_: str) -> Path:
        caminho = Path(self._registro(id_)["caminho_json"])
        if not caminho.is_file():
            raise NaoEncontrado(f"O arquivo da transcrição não foi encontrado: {caminho}",
                                codigo="arquivos_indisponiveis",
                                dica="A pasta pode ter sido movida ou apagada. Se ela foi movida, abra o .json no "
                                     "novo local; depois, remova este item do histórico.")
        return caminho

    def _dados(self, id_: str) -> tuple[Path, dict]:
        caminho = self.caminho_json(id_)
        try:
            return caminho, carregar_transcricao(caminho)
        except (ValueError, UnicodeDecodeError) as e:
            raise EntradaInvalida(f"O arquivo {caminho.name} não é mais uma transcrição válida.",
                                  codigo="json_invalido") from e

    def remover(self, id_: str) -> None:
        self._registro(id_)
        self.repositorio.remover_transcricao(id_)
        self.barramento.publicar("transcricao", {"id": id_, "acao": "removida"})

    # -- conteúdo ---------------------------------------------------------------

    def arquivos(self, id_: str, pasta: Path, base: str) -> list[ArquivoGerado]:
        candidatos = [(f, pasta / f"{base}.{f}") for f in FORMATOS]
        candidatos += [("relatorio", arquivo_relatorio(pasta, base)), ("log", pasta / f"{base}.log")]
        return [self._descrever_arquivo(id_, tipo, caminho) for tipo, caminho in candidatos]

    @staticmethod
    def _descrever_arquivo(id_: str, tipo: str, caminho: Path) -> ArquivoGerado:
        try:
            st = caminho.stat()
            existe, tamanho, mod = True, st.st_size, datetime.fromtimestamp(st.st_mtime).astimezone()
        except OSError:
            existe, tamanho, mod = False, None, None
        return ArquivoGerado(tipo=tipo, nome=caminho.name, caminho=str(caminho), existe=existe, tamanho_bytes=tamanho,
                             modificado_em=mod, url=f"/api/v1/transcricoes/{id_}/arquivos/{tipo}")

    @staticmethod
    def _processamento(dados: dict) -> ProcessamentoInfo:
        p = dados.get("processamento", {})
        return ProcessamentoInfo(
            descricao_asr=p.get("descricao_asr"), descricao_diarizacao=p.get("descricao_diarizacao"),
            dispositivo=p.get("dispositivo"), modelo=p.get("modelo"), modelo_revisao=p.get("modelo_revisao"),
            contexto=p.get("contexto"), glossario=list(p.get("glossario") or []), tempo_total_s=p.get("tempo_total_s"),
            tempos_etapas_s=dict(p.get("tempos_etapas_s") or {}), versao_programa=dados.get("versao_programa"))

    @staticmethod
    def _indicadores(rel) -> IndicadoresQualidade:
        i = rel.indicadores
        return IndicadoresQualidade(
            palavras=i.palavras, incertas=i.incertas, percentual_incertas=round(i.percentual_incertas, 1),
            inaudiveis=i.inaudiveis, simultaneas=i.simultaneas, janelas_revisadas=i.janelas_revisadas,
            janelas_alteradas=i.janelas_alteradas, recuperadas=i.recuperadas, alucinacoes=i.alucinacoes,
            pontos_conferencia=len(rel.pontos))

    def obter(self, id_: str) -> TranscricaoDetalhe:
        caminho, dados = self._dados(id_)
        rel = analisar_relatorio(dados)
        resumo = self._resumo(self._registro(id_))
        origem = resumo.arquivo_origem
        return TranscricaoDetalhe(
            **resumo.model_dump(), tem_video=Path(origem).suffix.lower() in EXTENSOES_VIDEO,
            processamento=self._processamento(dados), falantes=participantes_mod.basicos(dados),
            indicadores=self._indicadores(rel), observacoes=list(dados.get("observacoes", [])),
            arquivos=self.arquivos(id_, caminho.parent, dados["arquivo"]["base"]))

    def conteudo(self, id_: str) -> ConteudoTranscricao:
        _caminho, dados = self._dados(id_)
        doc = montar_documento(dados)
        blocos = [BlocoTranscricao(inicio_s=round(b.inicio, 2), fim_s=round(b.fim, 2), falante=b.falante or "",
                                   sobreposto_a=list(b.sobreposto_a),
                                   trechos=[TrechoTexto(tipo=t.tipo, texto=t.texto) for t in b.trechos],
                                   texto=texto_bloco(b)) for b in doc.blocos]
        return ConteudoTranscricao(id=id_, participantes=[nome for _rotulos, nome in doc.participantes], blocos=blocos)

    def relatorio(self, id_: str) -> RelatorioConferencia:
        _caminho, dados = self._dados(id_)
        rel = analisar_relatorio(dados)
        pre = rel.processamento.get("preprocessamento") or {}
        med = pre.get("medicoes", {}) if pre else {}
        audio = AudioConferencia(
            canais=(pre.get("canais") or {}).get("decisao") if pre else None,
            nivel_fala_db=med.get("nivel_fala_db"), nivel_ruido_db=med.get("nivel_ruido_db"), snr_db=med.get("snr_db"),
            tratamento=descrever_filtros(pre.get("filtros_asr") or []) if pre else None,
            observacoes=list(pre.get("observacoes", [])) if pre else [])
        return RelatorioConferencia(
            id=id_, arquivo=rel.arquivo, duracao_s=rel.duracao, gerado_em=rel.gerado_em,
            processamento=self._processamento(dados), audio=audio, observacoes=rel.observacoes,
            participantes=[ParticipanteConferencia(nome=p.nome, primeira_fala_s=round(p.primeira_fala, 2),
                                                   tempo_fala_s=round(p.tempo_fala, 1), parcela=round(p.parcela, 4),
                                                   palavras=p.palavras) for p in rel.participantes],
            indicadores=self._indicadores(rel),
            pontos=[PontoConferencia(inicio_s=round(p.inicio, 2), participante=p.participante,
                                     tipo=_TIPOS_PONTO.get(p.tipo, "incerto"), rotulo_tipo=p.tipo, trecho=p.trecho)
                    for p in rel.pontos],
            sugestoes=[SugestaoNome(participante=s.participante, nome=s.nome, autoidentificacoes=s.diretas,
                                    indicios_indiretos=s.indiretas, evidencias=s.evidencias,
                                    exemplo_inicio_s=round(s.exemplo_inicio, 2), exemplo=s.exemplo)
                       for s in rel.sugestoes],
            mencoes=[CategoriaMencoes(categoria=c, itens=[Mencao(inicio_s=round(m.inicio, 2), participante=m.participante,
                                                                 texto=m.texto) for m in itens])
                     for c, itens in rel.mencoes.items()])

    def arquivo(self, id_: str, tipo: str) -> Path:
        caminho, dados = self._dados(id_)
        for a in self.arquivos(id_, caminho.parent, dados["arquivo"]["base"]):
            if a.tipo == tipo:
                if not a.existe:
                    raise NaoEncontrado(f"O arquivo {a.nome} não foi gerado para esta transcrição.",
                                        codigo="arquivo_nao_gerado",
                                        dica="Gere os arquivos de novo na aba Arquivos, marcando este formato.")
                return Path(a.caminho)
        raise NaoEncontrado(f"Tipo de arquivo desconhecido: {tipo}", codigo="tipo_arquivo_invalido")

    def midia(self, id_: str) -> Path:
        resumo = self._resumo(self._registro(id_))
        if not resumo.origem_disponivel:
            raise NaoEncontrado("A gravação original não está mais no mesmo lugar.", codigo="midia_indisponivel",
                                dica=f"Ela estava em {resumo.arquivo_origem}.")
        return Path(resumo.arquivo_origem)

    # -- participantes e exportação ---------------------------------------------

    def participantes(self, id_: str) -> ListaParticipantes:
        _caminho, dados = self._dados(id_)
        return ListaParticipantes(transcricao_id=id_, itens=participantes_mod.resumir(dados))

    def _garantir_livre(self, pasta: Path) -> None:
        tarefa = self.pastas_em_uso().get(os.path.normcase(str(pasta.resolve())))
        if tarefa:
            raise Conflito("Esta transcrição está sendo processada de novo neste momento.", codigo="transcricao_em_uso",
                           dica="Aguarde o fim da tarefa em andamento para alterar os arquivos.")

    def nomear(self, id_: str, pedido: PedidoNomes) -> ResultadoNomes:
        caminho, dados = self._dados(id_)
        self._garantir_livre(caminho.parent)
        pares = [(a.participante, a.nome) for a in pedido.atribuicoes]
        pares += participantes_mod.ler_mapeamentos([], pedido.arquivo_mapeamentos)
        alteracoes = participantes_mod.aplicar(dados, pares, pedido.limpar)
        gerados = gerar_saidas(dados, caminho.parent, pedido.formatos or list(FORMATOS))
        self.registrar(caminho)
        return ResultadoNomes(transcricao_id=id_, alteracoes=alteracoes, participantes=participantes_mod.basicos(dados),
                              arquivos=[self._arquivo_gerado(id_, caminho.parent, dados, g) for g in gerados])

    def _arquivo_gerado(self, id_: str, pasta: Path, dados: dict, caminho: Path) -> ArquivoGerado:
        base = dados["arquivo"]["base"]
        if caminho.name == arquivo_relatorio(pasta, base).name:
            tipo = "relatorio"
        else:
            tipo = caminho.suffix.lstrip(".").lower()
        return self._descrever_arquivo(id_, tipo, caminho)

    def exportar(self, id_: str, pedido: PedidoExportacao) -> ResultadoExportacao:
        caminho, dados = self._dados(id_)
        pasta = Path(pedido.pasta_destino).expanduser() if pedido.pasta_destino else caminho.parent
        self._validar_pasta_saida(str(pasta))
        if pasta.resolve() == caminho.parent.resolve():
            self._garantir_livre(pasta)
        pasta.mkdir(parents=True, exist_ok=True)
        gerados = gerar_saidas(dados, pasta, list(pedido.formatos))
        if pasta.resolve() == caminho.parent.resolve():
            self.registrar(caminho)
        return ResultadoExportacao(pasta=str(pasta.resolve()),
                                   arquivos=[self._arquivo_gerado(id_, pasta, dados, g) for g in gerados])
