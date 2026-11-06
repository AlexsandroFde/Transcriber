"""Contratos de dados da aplicação (entrada e saída), validados com Pydantic.

Os mesmos modelos são usados pela API (corpo das requisições e das respostas, e a
documentação OpenAPI), pela linha de comando (validação dos parâmetros) e pelo processo
trabalhador (parâmetros recebidos do servidor). Os valores padrão vêm das próprias
estruturas do processamento (`Opcoes`, `OpcoesRevisao`), para não existirem duas fontes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Union, get_args

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationInfo, field_validator, model_validator

from ..processamento.exportar import FORMATOS
from ..processamento.pipeline import Opcoes

_PADRAO = Opcoes()

Formato = Literal["md", "txt", "docx", "srt", "vtt", "json"]
Dispositivo = Literal["auto", "cuda", "cpu"]
Precisao = Literal["auto", "float16", "int8_float16", "int8", "float32", "bfloat16"]
PreProcessamento = Literal["auto", "leve", "forte", "nenhum"]
Diarizacao = Literal["auto", "pyannote", "livre", "sherpa", "nenhuma"]
Estilo = Literal["literal", "padrao"]

assert set(get_args(Formato)) == set(FORMATOS), "Formato deve listar os mesmos formatos do exportador"

TEXTO_CURTO = 300


class Modelo(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _vazio_para_none(valor: Any) -> Any:
    if isinstance(valor, str):
        valor = valor.strip()
        return valor or None
    return valor


# ---------------------------------------------------------------------------
# Transcrição: parâmetros
# ---------------------------------------------------------------------------


class OpcoesTranscricao(Modelo):
    """Todas as opções do processamento (equivalem às opções do comando `transcritor transcrever`)."""

    pasta_saida: str | None = Field(
        None, max_length=1000,
        description="Pasta onde será criada a subpasta `<nome do arquivo>` com os resultados. Sem valor, os "
                    "resultados ficam ao lado da gravação, em `<pasta do arquivo>/<nome>_transcricao`.",
        examples=["C:\\Transcricoes"])
    participantes: int | None = Field(
        None, ge=1, le=99,
        description="Número exato de participantes, quando conhecido. Ajuda a separar vozes parecidas. Quando "
                    "informado, `min_participantes` e `max_participantes` são ignorados.", examples=[4])
    min_participantes: int | None = Field(None, ge=1, le=99, description="Número mínimo de participantes.")
    max_participantes: int | None = Field(None, ge=1, le=99, description="Número máximo de participantes.")
    contexto: str | None = Field(
        None, max_length=2000,
        description="Assunto da reunião (organização, projeto, tema). Orienta o reconhecimento do vocabulário; "
                    "não entra no texto da transcrição.",
        examples=["Reunião do conselho sobre o orçamento 2027"])
    glossario: list[Annotated[str, Field(max_length=TEXTO_CURTO)]] = Field(
        default_factory=list, max_length=2000,
        description="Termos literais: nomes de pessoas, organizações, siglas e termos técnicos citados.",
        examples=[["Instituto Iracema", "SIGEP", "LGPD"]])
    glossario_texto: str | None = Field(
        None, max_length=200_000,
        description="Glossário no formato de arquivo: um termo por linha, vários separados por `;`, e o texto "
                    "após `#` é ignorado. Somado a `glossario` e `glossario_arquivo`.",
        examples=["# Pessoas\nMariana; Roberto\nSIGEP"])
    glossario_arquivo: str | None = Field(
        None, max_length=1000,
        description="Caminho de um arquivo .txt de glossário no computador onde a API está rodando.")
    modelo: str = Field(
        _PADRAO.modelo, min_length=1, max_length=TEXTO_CURTO, pattern=r"^[^\r\n\t]+$",
        description="Modelo Whisper: `large-v3` (padrão, o mais preciso), `large-v3-turbo` (mais rápido), outro "
                    "nome aceito pelo faster-whisper ou o caminho de um modelo local.")
    modelo_revisao: str | None = Field(
        None, max_length=TEXTO_CURTO, pattern=r"^[^\r\n\t]+$",
        description="Modelo diferente para o segundo passo (por exemplo, `large-v2`). Sem valor, usa `modelo`.")
    dispositivo: Dispositivo = Field(
        _PADRAO.dispositivo, description="`auto` usa a placa de vídeo NVIDIA quando disponível.")
    precisao: Precisao = Field(
        _PADRAO.precisao, description="Tipo numérico do modelo. `auto`: float16 na placa de vídeo, int8 no processador.")
    pre_processamento: PreProcessamento = Field(
        _PADRAO.preprocessamento,
        description="Tratamento do áudio. `auto` só reduz ruído e equaliza o volume quando as medições indicam.")
    faixa_audio: str = Field(
        _PADRAO.faixa, pattern=r"^(\d{1,3}|todas)$",
        description="Índice da faixa de áudio (0 é a primeira) ou `todas` para mixar todas as faixas "
                    "(vídeos do OBS, por exemplo).", examples=["0", "todas"])
    diarizacao: Diarizacao = Field(
        _PADRAO.diarizacao,
        description="Identificação dos participantes. `auto`: pyannote community-1 com token do Hugging Face; "
                    "sem token, o pipeline pyannote 3.1 de acesso livre.")
    hf_token: SecretStr | None = Field(
        None, max_length=400,
        description="Token do Hugging Face só para esta transcrição (alternativa ao token salvo em Configurações). "
                    "Não é armazenado nem devolvido pela API.")
    revisao: bool = Field(
        _PADRAO.revisao,
        description="Segundo passo: cada trecho duvidoso é decodificado mais duas vezes e as três versões são "
                    "comparadas palavra a palavra. Desligar deixa o processamento mais rápido e menos preciso.")
    estilo: Estilo = Field(
        "literal" if _PADRAO.literal else "padrao",
        description="`literal` preserva hesitações e repetições; `padrao` deixa o modelo decidir.")
    formatos: list[Formato] = Field(
        default_factory=lambda: list(FORMATOS), min_length=1,
        description="Formatos de saída. O JSON e o relatório de conferência são sempre gerados: o JSON é a fonte "
                    "para renomear participantes e gerar os arquivos de novo.")
    beam: int = Field(_PADRAO.beam, ge=1, le=50, description="Largura do feixe no primeiro passo.")
    limiar_incerteza: float | None = Field(
        None, gt=0, lt=1,
        description="Sem maioria entre as decodificações, palavras abaixo desta probabilidade são marcadas como "
                    f"incertas. Sem valor: {_PADRAO.opcoes_revisao.limiar_sem_maioria}.")
    refazer: bool = Field(False, description="Ignora resultados de etapas anteriores e processa tudo de novo.")
    manter_audio: bool = Field(False, description="Mantém os arquivos WAV intermediários na pasta `.trabalho`.")
    detalhado: bool = Field(False, description="Registro técnico (log) detalhado.")

    _normalizar = field_validator("pasta_saida", "contexto", "glossario_arquivo", "modelo_revisao",
                                  "glossario_texto", mode="before")(_vazio_para_none)

    @field_validator("modelo", mode="before")
    @classmethod
    def _modelo(cls, valor: Any) -> Any:
        return valor.strip() if isinstance(valor, str) else valor

    @field_validator("formatos")
    @classmethod
    def _sem_repeticao(cls, valor: list[str]) -> list[str]:
        return list(dict.fromkeys(valor))

    @field_validator("max_participantes")
    @classmethod
    def _limites(cls, maximo: int | None, info: ValidationInfo) -> int | None:
        minimo = info.data.get("min_participantes")
        if maximo and minimo and minimo > maximo:
            raise ValueError("O número máximo de participantes não pode ser menor que o mínimo.")
        return maximo

    def para_trabalhador(self) -> dict[str, Any]:
        """Dicionário com o token em texto puro (só para o processo trabalhador, nunca persistido)."""
        dados = self.model_dump(mode="json", exclude={"hf_token"})
        if self.hf_token is not None:
            dados["hf_token"] = self.hf_token.get_secret_value()
        return dados

    def para_armazenar(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"hf_token"})


class PedidoTranscricao(OpcoesTranscricao):
    arquivos: list[Annotated[str, Field(min_length=1, max_length=1000)]] = Field(
        ..., min_length=1, max_length=200,
        description="Caminhos dos vídeos ou áudios no computador onde a API está rodando (ou o `caminho` devolvido "
                    "por `POST /api/v1/midia/envios`). Cada arquivo vira uma tarefa na fila.",
        examples=[["C:\\Users\\ana\\Videos\\reuniao.mp4"]])

    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [
        {"arquivos": ["C:\\Users\\ana\\Videos\\reuniao.mp4"]},
        {"arquivos": ["C:\\Users\\ana\\Videos\\conselho.mp4"], "participantes": 5,
         "contexto": "Reunião do conselho sobre o orçamento 2027", "glossario": ["SIGEP", "Instituto Iracema"],
         "formatos": ["docx", "srt"]},
    ]})


class ParametrosTranscricao(OpcoesTranscricao):
    """Parâmetros de uma tarefa de transcrição (um arquivo)."""

    arquivo: str = Field(..., min_length=1, max_length=1000, description="Vídeo ou áudio a transcrever.")


class PedidoModelo(Modelo):
    modelo: str = Field(_PADRAO.modelo, min_length=1, max_length=TEXTO_CURTO, pattern=r"^[^\r\n\t]+$",
                        description="Modelo Whisper a verificar ou baixar.")


# ---------------------------------------------------------------------------
# Tarefas
# ---------------------------------------------------------------------------

TipoTarefa = Literal["transcricao", "verificacao", "download_modelos"]
EstadoTarefa = Literal["na_fila", "em_andamento", "concluida", "falhou", "cancelada", "interrompida"]
EstadoEtapa = Literal["pendente", "em_andamento", "concluida", "reaproveitada", "ignorada", "falhou", "interrompida"]
ESTADOS_ATIVOS: tuple[str, ...] = ("na_fila", "em_andamento")
ESTADOS_FINAIS: tuple[str, ...] = ("concluida", "falhou", "cancelada", "interrompida")


class EtapaTarefa(Modelo):
    numero: int = Field(..., description="Posição da etapa (1 em diante).")
    chave: str = Field(..., description="Identificador estável da etapa.", examples=["diarizacao"])
    titulo: str = Field(..., examples=["Identificação dos participantes"])
    estado: EstadoEtapa
    detalhe: str | None = Field(None, description="Última mensagem da etapa.",
                                examples=["Identificando os participantes (diarização)"])
    duracao_s: float | None = Field(None, description="Duração em segundos, quando concluída.")


class ProgressoTarefa(Modelo):
    percentual: float = Field(..., ge=0, le=100, description="Progresso geral ponderado pela duração típica das etapas.")
    etapa_atual: int | None = Field(None, description="Número da etapa em andamento.")
    total_etapas: int
    fracao_etapa: float | None = Field(
        None, ge=0, le=1, description="Progresso dentro da etapa atual. `null` quando não é possível medir "
                                      "(por exemplo, durante o carregamento ou o download de um modelo).")
    mensagem: str | None = Field(None, description="Última mensagem do processamento, para exibir ao usuário.")
    decorrido_s: float | None = None
    restante_estimado_s: float | None = Field(
        None, description="Estimativa de tempo restante. `null` enquanto não há dados suficientes.")
    etapas: list[EtapaTarefa] = Field(default_factory=list)


class ErroTarefa(Modelo):
    codigo: str = Field(..., description="Código estável do erro.", examples=["memoria_gpu"])
    mensagem: str = Field(..., examples=["Faltou memória na placa de vídeo."])
    dica: str | None = Field(None, description="Como resolver, quando possível.")


class ResultadoTarefaTranscricao(Modelo):
    tipo: Literal["transcricao"] = "transcricao"
    transcricao_id: str | None = Field(None, description="Identificador para `GET /api/v1/transcricoes/{id}`.")
    caminho_json: str
    pasta: str
    arquivos: list[str] = Field(default_factory=list)


class EstadoModelo(Modelo):
    id: str = Field(..., examples=["reconhecimento"])
    nome: str = Field(..., examples=["Whisper large-v3"])
    descricao: str
    baixado: bool | None = Field(None, description="`null` quando não foi possível verificar.")
    obrigatorio: bool = True


class EstadoFfmpeg(Modelo):
    disponivel: bool
    caminho: str | None = None
    mensagem: str | None = None


class EstadoGpu(Modelo):
    disponivel: bool
    descricao: str = Field(..., examples=["NVIDIA GeForce RTX 4060 (8.0 GB)"])
    mensagem: str | None = None


AcessoModelo = Literal["ok", "negado", "erro", "nao_verificado", "sem_token"]


class EstadoTokenAmbiente(Modelo):
    configurado: bool
    origem: str | None = Field(None, examples=["arquivo"])
    acesso_modelo: AcessoModelo = Field(..., description="Acesso ao modelo pyannote community-1.")
    mensagem: str | None = None


class RelatorioAmbiente(Modelo):
    tipo: Literal["verificacao"] = "verificacao"
    versao: str
    python: str
    plataforma: str
    ffmpeg: EstadoFfmpeg
    gpu: EstadoGpu
    token_hf: EstadoTokenAmbiente
    modelos: list[EstadoModelo] = Field(default_factory=list)
    pronto: bool = Field(..., description="O essencial para transcrever está disponível (ffmpeg).")
    avisos: list[str] = Field(default_factory=list)
    verificado_em: datetime


class ResultadoDownload(Modelo):
    tipo: Literal["download_modelos"] = "download_modelos"
    modelos: list[EstadoModelo] = Field(default_factory=list)
    mensagens: list[str] = Field(default_factory=list)


ResultadoTarefa = Annotated[Union[ResultadoTarefaTranscricao, RelatorioAmbiente, ResultadoDownload],
                            Field(discriminator="tipo")]


class Tarefa(Modelo):
    id: str = Field(..., examples=["3f9c2a1b7d4e"])
    tipo: TipoTarefa
    estado: EstadoTarefa
    titulo: str = Field(..., examples=["reuniao.mp4"])
    criada_em: datetime
    iniciada_em: datetime | None = None
    concluida_em: datetime | None = None
    progresso: ProgressoTarefa
    parametros: dict[str, Any] = Field(default_factory=dict,
                                       description="Parâmetros da tarefa (o token do Hugging Face nunca aparece).")
    resultado: ResultadoTarefa | None = None
    erro: ErroTarefa | None = None
    origem_id: str | None = Field(None, description="Tarefa repetida, quando esta foi criada por `repetir`.")
    posicao_fila: int | None = Field(None, description="Posição na fila (1 é a próxima), quando está na fila.")
    pode_cancelar: bool
    pode_repetir: bool


class ListaTarefas(Modelo):
    itens: list[Tarefa]
    total: int


class TarefasCriadas(Modelo):
    tarefas: list[Tarefa]


class RegistroTarefa(Modelo):
    tarefa_id: str
    linhas: list[str]
    proxima: int = Field(..., description="Use como `desde` na próxima consulta para receber só as linhas novas.")
    caminho: str


# ---------------------------------------------------------------------------
# Transcrições (histórico e conteúdo)
# ---------------------------------------------------------------------------

TipoArquivo = Literal["md", "txt", "docx", "srt", "vtt", "json", "relatorio", "log"]


class ArquivoGerado(Modelo):
    tipo: TipoArquivo
    nome: str
    caminho: str
    existe: bool
    tamanho_bytes: int | None = None
    modificado_em: datetime | None = None
    url: str = Field(..., description="Download pela API.")


class ParticipanteBasico(Modelo):
    chave: str = Field(..., description="Identificador interno do falante.", examples=["SPEAKER_02"])
    rotulo: str = Field(..., examples=["Participante 1"])
    nome: str | None = Field(None, examples=["Mariana"])
    exibicao: str = Field(..., description="Nome exibido nos arquivos (o nome ou, sem ele, o rótulo).")


class IndicadoresQualidade(Modelo):
    palavras: int
    incertas: int
    percentual_incertas: float
    inaudiveis: int
    simultaneas: int
    janelas_revisadas: int
    janelas_alteradas: int
    recuperadas: int
    alucinacoes: int
    pontos_conferencia: int = Field(..., description="Total de pontos listados para conferência no relatório.")


class TranscricaoResumo(Modelo):
    id: str = Field(..., examples=["9a1e3c5b7f20d4e6"])
    nome: str = Field(..., description="Nome do arquivo de origem.", examples=["reuniao.mp4"])
    arquivo_origem: str
    origem_disponivel: bool = Field(..., description="A gravação original ainda está no mesmo lugar.")
    pasta: str
    caminho_json: str
    disponivel: bool = Field(..., description="O arquivo .json da transcrição ainda existe.")
    duracao_s: float | None = None
    gerado_em: str | None = Field(None, description="Data do processamento, como gravada no JSON.",
                                  examples=["04/11/2026 20:07"])
    registrado_em: datetime
    atualizado_em: datetime
    participantes: list[str] = Field(default_factory=list, description="Nomes exibidos, sem repetição.")
    pontos_conferencia: int = 0
    tarefa_id: str | None = None


class ProcessamentoInfo(Modelo):
    descricao_asr: str | None = None
    descricao_diarizacao: str | None = None
    dispositivo: str | None = None
    modelo: str | None = None
    modelo_revisao: str | None = None
    contexto: str | None = None
    glossario: list[str] = Field(default_factory=list)
    tempo_total_s: float | None = None
    tempos_etapas_s: dict[str, float] = Field(default_factory=dict)
    versao_programa: str | None = None


class TranscricaoDetalhe(TranscricaoResumo):
    tem_video: bool
    processamento: ProcessamentoInfo
    falantes: list[ParticipanteBasico]
    indicadores: IndicadoresQualidade
    observacoes: list[str] = Field(default_factory=list)
    arquivos: list[ArquivoGerado] = Field(default_factory=list)


class ListaTranscricoes(Modelo):
    itens: list[TranscricaoResumo]
    total: int


class PedidoImportacao(Modelo):
    caminho: str = Field(..., min_length=1, max_length=1000,
                         description="Arquivo .json gerado pelo Transcritor (pela interface, pelo .bat antigo ou "
                                     "pela linha de comando).",
                         examples=["C:\\Users\\ana\\Videos\\reuniao_transcricao\\reuniao.json"])


TipoTrecho = Literal["texto", "incerto", "marcador"]


class TrechoTexto(Modelo):
    tipo: TipoTrecho = Field(..., description="`incerto`: melhor hipótese sem confirmação; `marcador`: "
                                               "[inaudível] ou [falas simultâneas: ...].")
    texto: str


class BlocoTranscricao(Modelo):
    inicio_s: float
    fim_s: float
    falante: str = Field(..., description="Nome exibido.")
    sobreposto_a: list[str] = Field(default_factory=list,
                                    description="Quem ainda falava quando este trecho começou.")
    trechos: list[TrechoTexto]
    texto: str = Field(..., description="Texto corrido com as marcações, como nos arquivos .md e .txt.")


class ConteudoTranscricao(Modelo):
    id: str
    participantes: list[str]
    blocos: list[BlocoTranscricao]


TipoPonto = Literal["incerto", "inaudivel", "descartado"]


class PontoConferencia(Modelo):
    inicio_s: float
    participante: str
    tipo: TipoPonto
    rotulo_tipo: str = Field(..., examples=["trecho incerto"])
    trecho: str


class ParticipanteConferencia(Modelo):
    nome: str
    primeira_fala_s: float
    tempo_fala_s: float = Field(..., description="Inclui pausas curtas (até 1 s) entre palavras da mesma pessoa.")
    parcela: float = Field(..., ge=0, le=1)
    palavras: int


class SugestaoNome(Modelo):
    participante: str
    nome: str
    autoidentificacoes: int
    indicios_indiretos: int
    evidencias: str = Field(..., examples=["1 autoidentificação, 1 indício indireto"])
    exemplo_inicio_s: float
    exemplo: str


class Mencao(Modelo):
    inicio_s: float
    participante: str
    texto: str


class CategoriaMencoes(Modelo):
    categoria: str = Field(..., examples=["Valores monetários"])
    itens: list[Mencao]


class AudioConferencia(Modelo):
    canais: str | None = None
    nivel_fala_db: float | None = None
    nivel_ruido_db: float | None = None
    snr_db: float | None = None
    tratamento: str | None = None
    observacoes: list[str] = Field(default_factory=list)


class RelatorioConferencia(Modelo):
    id: str
    arquivo: str
    duracao_s: float
    gerado_em: str
    processamento: ProcessamentoInfo
    audio: AudioConferencia
    observacoes: list[str]
    participantes: list[ParticipanteConferencia]
    indicadores: IndicadoresQualidade
    pontos: list[PontoConferencia]
    sugestoes: list[SugestaoNome]
    mencoes: list[CategoriaMencoes]


# ---------------------------------------------------------------------------
# Participantes (nomes)
# ---------------------------------------------------------------------------


class ExemploFala(Modelo):
    inicio_s: float
    texto: str


class SugestaoParticipante(Modelo):
    nome: str
    ocorrencias: int


class ParticipanteDetalhe(ParticipanteBasico):
    tempo_fala_s: float = Field(..., description="Soma da duração das palavras atribuídas.")
    palavras: int
    exemplos: list[ExemploFala] = Field(default_factory=list, description="Frases com pelo menos 4 palavras.")
    sugestoes: list[SugestaoParticipante] = Field(
        default_factory=list, description="Nomes mencionados na fala que apontam para esta pessoa. Exigem "
                                          "confirmação: nenhum é aplicado automaticamente.")
    unido_com: list[str] = Field(default_factory=list,
                                 description="Rótulos de outros participantes exibidos com o mesmo nome.")


class ListaParticipantes(Modelo):
    transcricao_id: str
    itens: list[ParticipanteDetalhe]


class AtribuicaoNome(Modelo):
    participante: str = Field(..., min_length=1, max_length=TEXTO_CURTO,
                              description="Rótulo (`Participante 1`) ou chave (`SPEAKER_00`), sem diferenciar "
                                          "maiúsculas.", examples=["Participante 1"])
    nome: str = Field(..., max_length=TEXTO_CURTO,
                      description="Nome a exibir. Vazio remove o nome. O rótulo de outro participante une os dois "
                                  "(a mesma pessoa detectada com dois rótulos).", examples=["Ana Souza"])

    @field_validator("participante", "nome", mode="before")
    @classmethod
    def _aparar(cls, valor: Any) -> Any:
        return valor.strip() if isinstance(valor, str) else valor


class PedidoNomes(Modelo):
    atribuicoes: list[AtribuicaoNome] = Field(default_factory=list, max_length=200)
    limpar: bool = Field(False, description="Remove todos os nomes antes de aplicar as atribuições.")
    arquivo_mapeamentos: str | None = Field(
        None, max_length=1000,
        description="Arquivo .txt com um mapeamento `Participante 1=Nome` por linha (linhas com `#` no início são "
                    "ignoradas), no computador onde a API está rodando.")
    formatos: list[Formato] | None = Field(None, description="Formatos a gerar de novo. Sem valor: todos.")

    _normalizar = field_validator("arquivo_mapeamentos", mode="before")(_vazio_para_none)

    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [
        {"atribuicoes": [{"participante": "Participante 1", "nome": "Mariana"},
                         {"participante": "Participante 2", "nome": "Roberto"}]},
        {"atribuicoes": [{"participante": "Participante 5", "nome": "Participante 4"}]},
        {"limpar": True},
    ]})

    @model_validator(mode="after")
    def _algo_a_fazer(self) -> "PedidoNomes":
        if not (self.atribuicoes or self.limpar or self.arquivo_mapeamentos):
            raise ValueError("Informe ao menos uma atribuição, um arquivo de mapeamentos ou limpar=true.")
        return self


class AlteracaoNome(Modelo):
    participante: str
    anterior: str | None
    novo: str | None


class ResultadoNomes(Modelo):
    transcricao_id: str
    alteracoes: list[AlteracaoNome]
    participantes: list[ParticipanteBasico]
    arquivos: list[ArquivoGerado]


class PedidoExportacao(Modelo):
    formatos: list[Formato] = Field(default_factory=lambda: list(FORMATOS), min_length=1)
    pasta_destino: str | None = Field(None, max_length=1000,
                                      description="Pasta de destino. Sem valor: a pasta da transcrição.")

    _normalizar = field_validator("pasta_destino", mode="before")(_vazio_para_none)


class ResultadoExportacao(Modelo):
    pasta: str
    arquivos: list[ArquivoGerado]


# ---------------------------------------------------------------------------
# Ambiente e configuração
# ---------------------------------------------------------------------------

SituacaoAmbiente = Literal["nao_verificado", "verificando", "verificado"]


class EstadoAmbiente(Modelo):
    situacao: SituacaoAmbiente
    relatorio: RelatorioAmbiente | None = None
    tarefa_id: str | None = Field(None, description="Verificação em andamento, quando houver.")


OrigemToken = Literal["arquivo", "variavel_ambiente", "login_huggingface"]


class EstadoToken(Modelo):
    configurado: bool
    origem: OrigemToken | None = None
    variavel: str | None = Field(None, description="Nome da variável de ambiente, quando o token vem dela.")
    final: str | None = Field(None, description="Últimos 4 caracteres, para conferência.", examples=["a1b2"])
    arquivo: str = Field(..., description="Onde o Transcritor guarda o token.")
    pode_remover: bool
    pagina_modelo: str
    pagina_tokens: str
    pagina_cadastro: str


class PedidoToken(Modelo):
    token: SecretStr = Field(..., min_length=8, max_length=400, description="Token de leitura do Hugging Face.",
                             examples=["hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"])

    @field_validator("token", mode="before")
    @classmethod
    def _aparar(cls, valor: Any) -> Any:
        return valor.strip() if isinstance(valor, str) else valor

    @field_validator("token")
    @classmethod
    def _sem_espacos(cls, valor: SecretStr) -> SecretStr:
        if any(c.isspace() for c in valor.get_secret_value()):
            raise ValueError("O token não pode conter espaços ou quebras de linha.")
        return valor


class Glossario(Modelo):
    caminho: str
    existe: bool
    texto: str
    termos: list[str]


class PedidoGlossario(Modelo):
    texto: str = Field(..., max_length=200_000, examples=["Instituto Iracema\nMariana; Roberto\nSIGEP"])


class PedidoInterpretarGlossario(Modelo):
    texto: str | None = Field(None, max_length=200_000)
    caminho: str | None = Field(None, max_length=1000, description="Arquivo .txt a ler.")

    @model_validator(mode="after")
    def _um_dos_dois(self) -> "PedidoInterpretarGlossario":
        if (self.texto is None) == (self.caminho is None):
            raise ValueError("Informe `texto` ou `caminho` (apenas um dos dois).")
        return self


class GlossarioInterpretado(Modelo):
    termos: list[str]
    texto: str


# ---------------------------------------------------------------------------
# Mídia, sistema e catálogo
# ---------------------------------------------------------------------------


class FaixaAudio(Modelo):
    indice: int = Field(..., description="Valor para `faixa_audio`.")
    canais: int
    taxa_hz: int
    codec: str | None = None
    idioma: str | None = None
    titulo: str | None = None


class InfoMidia(Modelo):
    caminho: str
    nome: str
    tamanho_bytes: int
    duracao_s: float | None
    tem_video: bool
    faixas_audio: list[FaixaAudio]
    pasta_saida_padrao: str = Field(..., description="Onde os resultados ficam quando `pasta_saida` não é informada.")


class ArquivoEnviado(Modelo):
    id: str
    nome: str
    caminho: str = Field(..., description="Use em `arquivos` ao criar a transcrição.")
    tamanho_bytes: int
    enviado_em: datetime


class ListaEnvios(Modelo):
    itens: list[ArquivoEnviado]
    total: int


ModoExecucao = Literal["desktop", "servidor", "teste"]


class Saude(Modelo):
    status: Literal["ok"] = "ok"
    aplicacao: Literal["transcritor"] = "transcritor"
    versao: str
    modo: ModoExecucao
    iniciado_em: datetime
    tarefas_ativas: int


class PastasSistema(Modelo):
    config: str
    dados: str
    modelos: str
    logs: str
    envios: str


class InfoSistema(Modelo):
    versao: str
    python: str
    plataforma: str
    modo: ModoExecucao
    documentacao: str = Field(..., description="Caminho da documentação interativa.", examples=["/docs"])
    openapi: str
    pastas: PastasSistema
    glossario_padrao: str


class PedidoAbrir(Modelo):
    caminho: str = Field(..., min_length=1, max_length=1000)
    revelar: bool = Field(False, description="Mostra o arquivo selecionado no Explorador em vez de abri-lo.")


class PedidoAtivacao(Modelo):
    arquivos: list[Annotated[str, Field(max_length=1000)]] = Field(default_factory=list, max_length=200)


class OpcaoCatalogo(Modelo):
    valor: str
    rotulo: str
    descricao: str
    recomendado: bool = False


class LimiteNumerico(Modelo):
    minimo: float
    maximo: float
    passo: float
    padrao: float | None = None


class CatalogoOpcoes(Modelo):
    padroes: dict[str, Any] = Field(..., description="Valores padrão de `OpcoesTranscricao`.")
    modelos: list[OpcaoCatalogo]
    dispositivos: list[OpcaoCatalogo]
    precisoes: list[OpcaoCatalogo]
    pre_processamento: list[OpcaoCatalogo]
    diarizacao: list[OpcaoCatalogo]
    estilos: list[OpcaoCatalogo]
    formatos: list[OpcaoCatalogo]
    extensoes_midia: list[str]
    limites: dict[str, LimiteNumerico]
