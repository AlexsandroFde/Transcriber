"""Testes dos serviços e da linha de comando (sem modelos de IA)."""

from __future__ import annotations

import errno
from pathlib import Path

import pytest
from sintetico import dados_sinteticos

from transcritor.erros import EntradaInvalida, NaoEncontrado, descrever_excecao
from transcritor.servicos import glossario, participantes
from transcritor.servicos.progresso import ETAPAS_TRANSCRICAO, Acompanhamento


def test_glossario_formato_de_arquivo(tmp_path):
    assert glossario.interpretar("# comentário\nA; B\n\n  C  # resto\n") == ["A", "B", "C"]
    arq = tmp_path / "g.txt"
    arq.write_text("\ufeffSIGEP\nLGPD; API\n", encoding="utf-8")  # com BOM, como o Bloco de Notas salva
    assert glossario.ler_arquivo(arq) == ["SIGEP", "LGPD", "API"]
    assert glossario.combinar(["X", " "], "Y;Z", arq) == ["X", "Y", "Z", "SIGEP", "LGPD", "API"]
    with pytest.raises(NaoEncontrado):
        glossario.ler_arquivo(tmp_path / "nao.txt")
    ruim = tmp_path / "latin.txt"
    ruim.write_bytes("Associação".encode("latin-1"))
    with pytest.raises(EntradaInvalida):
        glossario.ler_arquivo(ruim)


def _dados() -> dict:
    return dados_sinteticos(Path("reuniao.mp4"))


def test_nomes_diretos_unioes_e_limpar():
    dados = _dados()
    alteracoes = participantes.aplicar(dados, [("Participante 2", "Participante 1"), ("participante 1", "Ana")])
    nomes = {i["rotulo"]: i["nome"] for i in dados["falantes"].values()}
    assert nomes == {"Participante 1": "Ana", "Participante 2": "Ana", "Participante 3": None}
    assert {a.participante for a in alteracoes} == {"Participante 1", "Participante 2"}
    participantes.aplicar(dados, [("Participante 1", "")])
    assert dados["falantes"]["S0"]["nome"] is None
    participantes.aplicar(dados, [], limpar=True)
    assert all(i["nome"] is None for i in dados["falantes"].values())
    with pytest.raises(NaoEncontrado):
        participantes.aplicar(dados, [("Participante 7", "X")])


def test_resumo_de_participantes():
    resumo = participantes.resumir(_dados())
    p1 = resumo[0]
    assert p1.rotulo == "Participante 1" and p1.chave == "S0"
    assert [s.nome for s in p1.sugestoes] == ["Mariana"] and p1.sugestoes[0].ocorrencias == 2
    assert all(len(e.texto.split()) >= 4 for e in p1.exemplos)
    assert resumo[2].sugestoes[0].nome == "Roberto"


def test_mapeamentos_de_arquivo(tmp_path):
    arq = tmp_path / "nomes.txt"
    arq.write_text("# comentário\nParticipante 1=Ana\n\nParticipante 2 = Carlos \n", encoding="utf-8")
    assert participantes.ler_mapeamentos(["Participante 3=Bia"], arq) == [
        ("Participante 3", "Bia"), ("Participante 1", "Ana"), ("Participante 2", "Carlos")]
    with pytest.raises(EntradaInvalida):
        participantes.ler_mapeamentos(["sem igual"])


def test_progresso_pondera_e_estima_so_trabalho_executado():
    relogio = [0.0]
    ac = Acompanhamento(ETAPAS_TRANSCRICAO, relogio=lambda: relogio[0])
    ac.iniciar()
    ac.etapa(4, "Transcrição reaproveitada", "reaproveitada")  # 1 a 3 também vieram do cache
    assert [e.estado for e in ac.instantaneo().etapas[:4]] == ["reaproveitada"] * 4
    assert ac.percentual() == pytest.approx(74.0)
    ac.etapa(5, "Revisando")
    assert ac.restante() is None  # sem medida ainda
    relogio[0] = 20.0
    ac.progresso(0.5)
    # 0,10 de peso em 20 s -> restam 0,10 da revisão + 0,06 da montagem = 32 s
    assert ac.restante() == pytest.approx(32.0)
    ac.encerrar("falhou")
    etapas = ac.instantaneo().etapas
    assert etapas[4].estado == "falhou" and etapas[5].estado == "pendente" and ac.restante() is None


def test_erros_tecnicos_viram_mensagens_compreensiveis():
    assert descrever_excecao(RuntimeError("CUDA failed: out of memory")).codigo == "memoria_gpu"
    assert descrever_excecao(RuntimeError("O arquivo não possui faixa de áudio.")).codigo == "sem_audio"
    assert descrever_excecao(RuntimeError("Falha no ffmpeg:\nInvalid data")).codigo == "midia_ilegivel"
    assert descrever_excecao(OSError(errno.ENOSPC, "No space left")).codigo == "disco_cheio"
    assert descrever_excecao(PermissionError(13, "negado", "C:/x.docx")).codigo == "sem_permissao"
    assert descrever_excecao(FileNotFoundError(2, "nao", "C:/v.mp4")).mensagem.endswith("C:/v.mp4")
    d = descrever_excecao(ValueError("algo estranho"))
    assert d.codigo == "erro_inesperado" and d.dica and "ValueError" in d.detalhe


def test_contrato_valida_parametros_da_linha_de_comando():
    from transcritor.cli import _opcoes_da_linha, _parser

    a = _parser().parse_args(["transcrever", "x.mp4", "-n", "4", "-c", "", "--sem-revisao", "-f", "docx,srt"])
    op = _opcoes_da_linha(a)
    assert op.participantes == 4 and op.contexto is None and op.revisao is False and op.formatos == ["docx", "srt"]
    a = _parser().parse_args(["transcrever", "x.mp4", "--min-participantes", "5", "--max-participantes", "2"])
    with pytest.raises(SystemExit):
        _opcoes_da_linha(a)


def test_construir_opcoes_equivale_ao_comportamento_antigo(tmp_path):
    from transcritor.servicos.contratos import OpcoesTranscricao
    from transcritor.servicos.transcricoes import construir_opcoes

    g = tmp_path / "g.txt"
    g.write_text("SIGEP; LGPD\n", encoding="utf-8")
    op = construir_opcoes(OpcoesTranscricao(glossario_arquivo=str(g), limiar_incerteza=0.7, estilo="padrao",
                                            faixa_audio="todas", pasta_saida=str(tmp_path)))
    assert op.glossario == ["SIGEP", "LGPD"] and op.opcoes_revisao.limiar_sem_maioria == 0.7
    assert op.literal is False and op.faixa == "todas" and op.saida == tmp_path
    padrao = construir_opcoes(OpcoesTranscricao())
    assert padrao.opcoes_revisao.limiar_sem_maioria == 0.85
    assert padrao.formatos == ["md", "txt", "docx", "srt", "vtt", "json"]


def test_cli_nomear_e_exportar(tmp_path, cfg):
    from transcritor.cli import main
    from transcritor.processamento.documento import carregar_transcricao, gerar_saidas

    pasta = tmp_path / "t"
    gerar_saidas(dados_sinteticos(tmp_path / "reuniao.mp4"), pasta, ["json"])
    json_ = pasta / "reuniao.json"
    with pytest.raises(SystemExit) as fim:
        main(["nomear", str(json_), "Participante 1=Ana", "Participante 3=Participante 1"])
    assert fim.value.code == 0
    dados = carregar_transcricao(json_)
    assert {i["rotulo"]: i["nome"] for i in dados["falantes"].values()}["Participante 3"] == "Ana"
    assert (pasta / "reuniao.docx").is_file()
    with pytest.raises(SystemExit) as fim:
        main(["nomear", str(json_), "Participante 9=X"])
    assert fim.value.code == 1
    with pytest.raises(SystemExit) as fim:
        main(["exportar", str(json_), "-f", "vtt", "-s", str(tmp_path / "saida")])
    assert fim.value.code == 0 and (tmp_path / "saida" / "reuniao.vtt").is_file()
