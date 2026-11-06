"""Interface de linha de comando.

A forma recomendada de usar o Transcritor é o aplicativo (atalho "Transcritor" ou
`transcritor app`). A linha de comando continua disponível, com as mesmas regras, para
automação e para quem prefere o terminal.

Exemplos:
    transcritor reuniao.mp4
    transcritor transcrever reuniao.mp4 -n 4 -c "Reunião do conselho sobre o orçamento 2027" -g glossario.txt
    transcritor nomear reuniao_transcricao/reuniao.json "Participante 1=Ana Souza" "Participante 2=Carlos"
    transcritor exportar reuniao_transcricao/reuniao.json -f docx,srt
    transcritor verificar
    transcritor configurar-token hf_xxxxxxxx
    transcritor servidor               # só a API REST (documentação em http://127.0.0.1:8765/docs)
    transcritor app                    # abre o aplicativo
"""

from __future__ import annotations

import argparse
import glob
import logging
import sys
from pathlib import Path
from typing import get_args

from . import __version__
from .ambiente import configurar_log, preparar
from .erros import ErroTranscritor

log = logging.getLogger("transcritor")

COMANDOS = {"transcrever", "nomear", "exportar", "verificar", "configurar-token", "servidor", "app"}


def _formatos(valor: str) -> list[str]:
    from .processamento.exportar import FORMATOS

    itens = [v.strip().lower().lstrip(".") for v in valor.split(",") if v.strip()]
    invalidos = [v for v in itens if v not in FORMATOS]
    if invalidos:
        raise argparse.ArgumentTypeError(f"formato(s) inválido(s): {', '.join(invalidos)}. Use: {', '.join(FORMATOS)}")
    return itens


def _parser() -> argparse.ArgumentParser:
    from .servicos import contratos as c

    padrao = c.OpcoesTranscricao()
    p = argparse.ArgumentParser(
        prog="transcritor",
        description="Transcrição fiel de reuniões gravadas (português brasileiro), com identificação de "
                    "participantes, marcação temporal e exportação em MD, TXT, DOCX, SRT, VTT e JSON.",
    )
    p.add_argument("--version", action="version", version=f"transcritor {__version__}")
    sub = p.add_subparsers(dest="comando")

    t = sub.add_parser("transcrever", help="transcreve um ou mais vídeos/áudios")
    t.add_argument("entradas", nargs="+", help="arquivos de vídeo ou áudio")
    t.add_argument("-s", "--saida", help="pasta de saída (padrão: <pasta do vídeo>/<nome>_transcricao)")
    t.add_argument("-n", "--participantes", type=int, help="número exato de participantes, se conhecido")
    t.add_argument("--min-participantes", type=int, help="número mínimo de participantes")
    t.add_argument("--max-participantes", type=int, help="número máximo de participantes")
    t.add_argument("-c", "--contexto", help="frase descrevendo a reunião (assunto, organização, projeto)")
    t.add_argument("-g", "--glossario", help="arquivo .txt com nomes, siglas e termos técnicos (um por linha)")
    t.add_argument("-m", "--modelo", default=padrao.modelo, help=f"modelo Whisper (padrão: {padrao.modelo})")
    t.add_argument("--modelo-revisao", help="modelo diferente para o segundo passo (ex.: large-v2)")
    t.add_argument("--dispositivo", choices=get_args(c.Dispositivo), default=padrao.dispositivo)
    t.add_argument("--precisao", choices=get_args(c.Precisao), default=padrao.precisao,
                   help="tipo numérico do modelo (padrão: float16 na GPU, int8 na CPU)")
    t.add_argument("--pre-processamento", choices=get_args(c.PreProcessamento), default=padrao.pre_processamento,
                   help="tratamento do áudio (padrão: auto, que só reduz ruído quando necessário)")
    t.add_argument("--faixa-audio", default=padrao.faixa_audio, help="índice da faixa de áudio ou 'todas' para mixar")
    t.add_argument("--diarizacao", choices=get_args(c.Diarizacao), default=padrao.diarizacao,
                   help="identificação de participantes (padrão: pyannote community-1 com token; sem token, "
                        "o pipeline pyannote 3.1 livre)")
    t.add_argument("--hf-token", help="token do Hugging Face (alternativa a configurar-token)")
    t.add_argument("--sem-revisao", action="store_true", help="pula o segundo passo de revisão (mais rápido)")
    t.add_argument("--estilo", choices=get_args(c.Estilo), default=padrao.estilo,
                   help="literal (padrão) preserva hesitações e repetições; padrao deixa o modelo decidir")
    t.add_argument("-f", "--formatos", type=_formatos, default=None,
                   help="formatos de saída separados por vírgula (padrão: md,txt,docx,srt,vtt,json)")
    t.add_argument("--beam", type=int, default=padrao.beam, help=f"largura do feixe no primeiro passo (padrão: {padrao.beam})")
    t.add_argument("--limiar-incerteza", type=float, default=None,
                   help="sem maioria entre as decodificações, palavras abaixo desta probabilidade são marcadas "
                        "como incertas (padrão: 0.85)")
    t.add_argument("--refazer", action="store_true", help="ignora resultados anteriores e processa tudo de novo")
    t.add_argument("--manter-audio", action="store_true", help="mantém os WAV intermediários em .trabalho")
    t.add_argument("-v", "--detalhado", action="store_true", help="mensagens detalhadas")

    n = sub.add_parser("nomear", help="associa nomes aos participantes e regenera os arquivos")
    n.add_argument("json", help="arquivo .json gerado pela transcrição")
    n.add_argument("mapeamentos", nargs="*", help='pares "Participante 1=Nome". Use o mesmo nome para unir dois rótulos')
    n.add_argument("-a", "--arquivo", help="arquivo .txt com um mapeamento por linha")
    n.add_argument("-i", "--interativo", action="store_true",
                   help="pergunta o nome de cada participante, mostrando exemplos de fala e nomes mencionados")
    n.add_argument("--limpar", action="store_true", help="remove todos os nomes atribuídos")
    n.add_argument("-f", "--formatos", type=_formatos, default=None)

    e = sub.add_parser("exportar", help="regenera os arquivos de saída a partir do .json")
    e.add_argument("json")
    e.add_argument("-f", "--formatos", type=_formatos, default=None)
    e.add_argument("-s", "--saida", help="pasta de destino (padrão: a pasta do .json)")

    v = sub.add_parser("verificar", help="verifica GPU, ffmpeg, modelos e token")
    v.add_argument("--baixar-modelos", action="store_true", help="baixa os modelos agora (evita espera depois)")
    v.add_argument("-m", "--modelo", default=padrao.modelo)

    tk = sub.add_parser("configurar-token", help="salva o token do Hugging Face para a diarização pyannote")
    tk.add_argument("token")

    s = sub.add_parser("servidor", help="inicia só a API REST, sem janela (para integrações)")
    s.add_argument("--host", help="endereço (padrão: 127.0.0.1, só este computador)")
    s.add_argument("--porta", type=int, help="porta (padrão: 8765)")
    s.add_argument("--sem-verificacao", action="store_true", help="não verifica o ambiente ao iniciar")

    sub.add_parser("app", help="abre o aplicativo (janela)")
    return p


def _opcoes_da_linha(a: argparse.Namespace):
    from pydantic import ValidationError

    from .servicos.contratos import OpcoesTranscricao

    valores = dict(
        pasta_saida=a.saida, participantes=a.participantes, min_participantes=a.min_participantes,
        max_participantes=a.max_participantes, contexto=a.contexto, glossario_arquivo=a.glossario, modelo=a.modelo,
        modelo_revisao=a.modelo_revisao, dispositivo=a.dispositivo, precisao=a.precisao,
        pre_processamento=a.pre_processamento, faixa_audio=a.faixa_audio, diarizacao=a.diarizacao,
        hf_token=a.hf_token, revisao=not a.sem_revisao, estilo=a.estilo, beam=a.beam,
        limiar_incerteza=a.limiar_incerteza, refazer=a.refazer, manter_audio=a.manter_audio, detalhado=a.detalhado)
    if a.formatos:
        valores["formatos"] = a.formatos
    try:
        return OpcoesTranscricao(**valores)
    except ValidationError as e:
        nomes = {"pasta_saida": "--saida", "glossario_arquivo": "--glossario", "pre_processamento": "--pre-processamento",
                 "faixa_audio": "--faixa-audio", "limiar_incerteza": "--limiar-incerteza"}
        for erro in e.errors():
            campo = str(erro["loc"][0]) if erro.get("loc") else ""
            opcao = nomes.get(campo, f"--{campo.replace('_', '-')}" if campo else "")
            log.error("Opção inválida%s: %s", f" {opcao}" if opcao else "", erro["msg"].removeprefix("Value error, "))
        raise SystemExit(2)


def _cmd_transcrever(a: argparse.Namespace) -> int:
    from .processamento.pipeline import processar
    from .servicos import glossario
    from .servicos.transcricoes import construir_opcoes

    params = _opcoes_da_linha(a)
    if params.glossario_arquivo:
        glossario.ler_arquivo(params.glossario_arquivo)  # erro claro antes de começar
    op = construir_opcoes(params)
    entradas: list[str] = []
    for e in a.entradas:
        # O cmd do Windows não expande curingas (*.mp4); expandimos aqui.
        achados = sorted(glob.glob(e)) if any(c in e for c in "*?[") else [e]
        if not achados:
            log.error("Nenhum arquivo corresponde a: %s", e)
        entradas.extend(achados)
    falhas = 0
    for entrada in entradas:
        try:
            processar(Path(entrada), op)
        except KeyboardInterrupt:
            log.error("\nInterrompido. Os resultados parciais ficam em .trabalho e serão reaproveitados.")
            return 130
        except Exception as e:
            falhas += 1
            log.exception("Erro ao processar %s: %s", entrada, e)
    return 1 if falhas else 0


def _perguntar_nomes(dados: dict) -> list[tuple[str, str]]:
    """Mostra cada participante com exemplos de fala e nomes mencionados; pergunta o nome."""
    from .processamento import tempo
    from .servicos.participantes import resumir

    pares = []
    print("\nPara cada participante, digite o nome (Enter mantém como está).")
    print("Para unir dois rótulos da mesma pessoa, digite o rótulo da outra (ex.: Participante 1).")
    for p in resumir(dados):
        print(f"\n{p.rotulo} ({tempo.duracao_legivel(p.tempo_fala_s)} de fala)")
        for ex in p.exemplos:
            print(f"   [{tempo.hms(ex.inicio_s)}] {ex.texto[:110]}{'...' if len(ex.texto) > 110 else ''}")
        if p.sugestoes:
            print("   Nomes mencionados na fala (confirme antes de usar): "
                  + ", ".join(f"{s.nome} ({s.ocorrencias}x)" for s in p.sugestoes))
        try:
            resposta = input(f"   Nome [{p.nome or p.rotulo}]: ").strip()
        except EOFError:
            resposta = ""
        if resposta:
            pares.append((p.rotulo, resposta))
    return pares


def _cmd_nomear(a: argparse.Namespace) -> int:
    from .processamento.documento import carregar_transcricao, gerar_saidas
    from .processamento.exportar import FORMATOS
    from .servicos.participantes import aplicar, ler_mapeamentos

    caminho = Path(a.json)
    dados = carregar_transcricao(caminho)
    pares = ler_mapeamentos(a.mapeamentos, a.arquivo)
    if a.limpar:
        aplicar(dados, [], limpar=True)
    if a.interativo:
        pares += _perguntar_nomes(dados)
    aplicar(dados, pares)
    arquivos = gerar_saidas(dados, caminho.parent, a.formatos or list(FORMATOS))
    log.info("Arquivos atualizados:")
    for arq in arquivos:
        log.info("    %s", arq)
    return 0


def _cmd_exportar(a: argparse.Namespace) -> int:
    from .processamento.documento import carregar_transcricao, gerar_saidas
    from .processamento.exportar import FORMATOS

    caminho = Path(a.json)
    dados = carregar_transcricao(caminho)
    pasta = Path(a.saida) if a.saida else caminho.parent
    for arq in gerar_saidas(dados, pasta, a.formatos or list(FORMATOS)):
        log.info("    %s", arq)
    return 0


def _cmd_verificar(a: argparse.Namespace) -> int:
    from .processamento.diarizacao import PAGINA_MODELO
    from .servicos.diagnostico import baixar_modelos, verificar

    r = verificar(a.modelo)
    log.info("transcritor %s | Python %s", r.versao, r.python)
    if r.ffmpeg.disponivel:
        log.info("ffmpeg: %s", r.ffmpeg.caminho)
    else:
        log.error("ffmpeg: %s", r.ffmpeg.mensagem)
    log.info("GPU (CUDA): %s", r.gpu.descricao if r.gpu.disponivel else r.gpu.mensagem)
    tk = r.token_hf
    if tk.configurado:
        log.info("Token do Hugging Face: configurado")
        (log.info if tk.acesso_modelo == "ok" else log.error)("%s", tk.mensagem)
    else:
        log.info("Token do Hugging Face: não configurado (opcional). A diarização usará o pipeline\n"
                 "  pyannote 3.1 com componentes de acesso livre. Para usar o modelo mais recente\n"
                 "  (community-1): crie uma conta em huggingface.co, aceite os termos em\n"
                 "  %s, gere um token de leitura e salve-o no aplicativo\n"
                 "  (Configurações) ou rode: transcritor configurar-token SEU_TOKEN", PAGINA_MODELO)
    situacao = {True: "baixado", False: "não baixado", None: "não verificado"}
    log.info("Modelos: %s", "; ".join(f"{m.nome} ({situacao[m.baixado]})" for m in r.modelos))
    if a.baixar_modelos:
        baixar_modelos(a.modelo)
    return 0 if r.ffmpeg.disponivel and tk.acesso_modelo not in ("negado", "erro") else 1


def _cmd_token(a: argparse.Namespace) -> int:
    from .ambiente import salvar_token

    destino = salvar_token(a.token)
    log.info("Token salvo em %s", destino)
    log.info("Rode 'transcritor verificar' para testar o acesso ao modelo de diarização.")
    return 0


def _cmd_servidor(a: argparse.Namespace) -> int:
    from . import config
    from .ambiente import configurar_log_aplicativo
    from .api.servidor import executar

    cfg = config.obter()
    if a.host:
        cfg = cfg.com(host=a.host)
    if a.porta is not None:
        cfg = cfg.com(porta=a.porta)
    config.definir(cfg)
    configurar_log_aplicativo(cfg)
    return executar(cfg, verificar_ao_iniciar=not a.sem_verificacao)


def _cmd_app(_a: argparse.Namespace) -> int:
    from .desktop import main as abrir

    return abrir([])


def main(argv: list[str] | None = None) -> None:
    preparar()
    configurar_log()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] not in COMANDOS and not argv[0].startswith("-"):
        argv.insert(0, "transcrever")
    parser = _parser()
    a = parser.parse_args(argv)
    if not a.comando:
        parser.print_help()
        sys.exit(0)
    acoes = {"transcrever": _cmd_transcrever, "nomear": _cmd_nomear, "exportar": _cmd_exportar,
             "verificar": _cmd_verificar, "configurar-token": _cmd_token, "servidor": _cmd_servidor,
             "app": _cmd_app}
    try:
        codigo = acoes[a.comando](a)
    except ErroTranscritor as e:
        log.error("%s", e.mensagem)
        if e.dica:
            log.error("  %s", e.dica)
        codigo = 1
    sys.exit(codigo)
