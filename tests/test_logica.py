"""Testes da lógica pura (sem modelos de IA)."""

from __future__ import annotations

import numpy as np
import pytest

from transcritor.processamento import tempo
from transcritor.processamento.asr import MapaFala, construir_trechos
from transcritor.processamento.diarizacao import exclusivizar
from transcritor.processamento.exportar import Documento, gerar_legendas, para_markdown, para_srt
from transcritor.processamento.intervalos import sobreposicao, subtrair, unir
from transcritor.processamento.modelos import Marcador, Palavra, SegmentoASR, Turno
from transcritor.processamento.montagem import (OpcoesMontagem, atribuir_falantes, marcadores_simultaneos, montar_blocos,
                                  rotular, suavizar, texto_bloco)
from transcritor.processamento.nomes import agrupar, sugerir
from transcritor.processamento.qualidade import (assinatura_alucinacao, combinar, diagnosticar_segmento, eco_do_prompt,
                                   escolher, marcar_incertas, repeticao_excessiva, termos_da_reuniao)
from transcritor.processamento.revisao import OpcoesRevisao, lacunas, montar_janelas
from transcritor.processamento.texto import capitalizar_inicio, juntar_palavras, tokens


def P(ini, fim, txt, prob=0.9, falante=None):
    return Palavra(ini, fim, txt, prob, falante)


# --- intervalos e tempo ------------------------------------------------------

def test_unir_e_subtrair():
    assert unir([(0, 1), (0.5, 2), (3, 4)]) == [(0, 2), (3, 4)]
    assert unir([(0, 1), (1.2, 2)], tolerancia=0.3) == [(0, 2)]
    assert subtrair([(0, 10)], [(2, 3), (5, 6)]) == [(0, 2), (3, 5), (6, 10)]
    assert subtrair([(0, 2), (4, 6)], [(1, 5)]) == [(0, 1), (5, 6)]
    assert subtrair([(0, 2)], []) == [(0, 2)]
    assert sobreposicao((0, 2), (1, 3)) == 1


def test_tempo():
    assert tempo.hms(135.9) == "00:02:15"
    assert tempo.srt(3661.5) == "01:01:01,500"
    assert tempo.vtt(1.25) == "00:00:01.250"
    assert tempo.duracao_legivel(3725) == "1 h 02 min 05 s"


def test_texto():
    assert juntar_palavras([" Olá,", " tudo", " bem?"]) == "Olá, tudo bem?"
    assert juntar_palavras([" isso", " —", " certo"]) == "isso, certo"
    assert juntar_palavras([" de", " 10–20"]) == "de 10-20"
    assert capitalizar_inicio("sim, pode ser") == "Sim, pode ser"
    assert capitalizar_inicio("...então") == "...Então"
    assert tokens("É, a gente, a gente vai!") == ["é", "a", "gente", "a", "gente", "vai"]


# --- tratamento de canais ----------------------------------------------------

def test_tratar_canais():
    from transcritor.processamento.audio import tratar_canais

    rng = np.random.default_rng(0)
    voz = (0.1 * rng.standard_normal(16000 * 3)).astype(np.float32)
    outra = (0.1 * rng.standard_normal(16000 * 3)).astype(np.float32)
    mono, info = tratar_canais(voz.reshape(-1, 1))
    assert info["decisao"] == "áudio mono" and np.allclose(mono, voz)
    # canal direito mudo: usa só o esquerdo (a média reduziria o nível à metade)
    mono, info = tratar_canais(np.stack([voz, voz * 1e-4], axis=1))
    assert "só o esquerdo" in info["decisao"] and np.allclose(mono, voz)
    # fase invertida: a soma cancelaria a voz
    mono, info = tratar_canais(np.stack([voz, -voz * 0.9], axis=1))
    assert "fase invertida" in info["decisao"] and np.allclose(mono, voz)
    # conteúdos diferentes (ex.: uma pessoa em cada canal): mixagem
    mono, info = tratar_canais(np.stack([voz, outra], axis=1))
    assert info["decisao"] == "mixagem dos dois canais" and np.allclose(mono, (voz + outra) / 2)


# --- mapa de concatenação ----------------------------------------------------

def test_mapa_fala():
    mapa = MapaFala([(10.0, 12.0), (20.0, 25.0)])
    assert mapa.duracao == pytest.approx(7.0)
    assert mapa.para_original(0.5) == pytest.approx(10.5)
    assert mapa.para_original(2.5) == pytest.approx(20.5)
    # palavra atravessando a junção fica do lado com mais conteúdo
    ini, fim = mapa.mapear(1.9, 2.4)
    assert ini == pytest.approx(20.0) and fim == pytest.approx(20.4)
    audio = np.arange(30 * 16000, dtype=np.float32)
    c = mapa.concatenar(audio)
    assert len(c) == 7 * 16000 and c[0] == 10 * 16000


def test_construir_trechos_mantem_pausas_curtas():
    trechos = construir_trechos([(1.0, 2.0), (3.0, 4.0), (10.0, 11.0)], duracao=60)
    assert trechos == [(0.7, 4.3), (9.7, 11.3)]


# --- qualidade ---------------------------------------------------------------

def test_assinaturas():
    assert assinatura_alucinacao("Legendas pela comunidade Amara.org") == "forte"
    assert assinatura_alucinacao("Obrigado por assistir!") == "forte"
    assert assinatura_alucinacao("Obrigado.") == "fraca"
    assert assinatura_alucinacao("Obrigado a todos pela presença.") is None
    assert assinatura_alucinacao("Precisamos definir a integração.") is None


def test_repeticao():
    assert repeticao_excessiva(tokens("não não não")) is None
    assert repeticao_excessiva(tokens("não " * 8)) is not None
    assert repeticao_excessiva(tokens("a gente vai " * 4)) is not None
    assert repeticao_excessiva(tokens("eu acho que eu acho que pode ser")) is None


def test_eco_prompt():
    prompt = "Hum, deixa eu ver... Tá, então, é, a gente, a gente tava pensando, né, em fazer assim."
    assert eco_do_prompt("a gente tava pensando, né, em fazer assim", prompt)
    assert not eco_do_prompt("vamos aprovar o orçamento", prompt)


def test_diagnostico_descarta_alucinacao_sem_fala():
    seg = SegmentoASR(10, 12, " Legendas pela comunidade Amara.org", -0.9, 1.2, 0.7, 0.0,
                      [P(10, 12, " Legendas", 0.3)])
    assert diagnosticar_segmento(seg, fala=[(0, 5)]).descartar
    normal = SegmentoASR(1, 3, " Bom dia a todos.", -0.2, 1.1, 0.01, 0.0,
                         [P(1, 1.5, " Bom"), P(1.5, 2, " dia"), P(2, 2.5, " a"), P(2.5, 3, " todos.")])
    d = diagnosticar_segmento(normal, fala=[(0.5, 3.5)])
    assert not d.descartar and not d.revisar


def test_escolher_nunca_troca_por_hipotese_que_omite_fala():
    fala = [(0, 6)]
    h1 = [P(0.2, 1.0, " vamos", 0.5), P(1.0, 2.0, " revisar", 0.5), P(3, 5.8, " o orçamento", 0.5)]
    h2 = [P(0.2, 1.0, " vamos", 0.95), P(1.0, 2.0, " revisar.", 0.95)]
    assert escolher(h1, h2, fala, (0, 6)).escolhida == "passo1"
    h2b = [P(0.2, 1.0, " vamos", 0.95), P(1.0, 2.0, " revisar", 0.95), P(3, 5.8, " o orçamento", 0.9)]
    assert escolher(h1, h2b, fala, (0, 6)).escolhida == "revisao"


def test_escolher_troca_laco():
    fala = [(0, 4)]
    h1 = [P(0.1 + i * 0.1, 0.2 + i * 0.1, " não", 0.6) for i in range(30)]
    h2 = [P(0.1, 0.5, " não,", 0.8), P(0.5, 0.9, " não.", 0.8), P(1.0, 3.5, " Espera", 0.7)]
    assert escolher(h1, h2, fala, (0, 4)).escolhida == "revisao"


def test_marcar_incertas_por_concordancia():
    h = [P(0, 1, " o", 0.9), P(1, 2, " Sigep", 0.3), P(2, 3, " funciona", 0.5)]
    alt = [P(0, 1, " o", 0.9), P(1, 2, " CJ", 0.2), P(2, 3, " funciona", 0.5)]
    marcar_incertas(h, alt)
    assert [p.incerta for p in h] == [False, True, False]


def test_termos_da_reuniao():
    palavras = [P(0, 1, " O"), P(1, 2, " SIGEP"), P(2, 3, " e"), P(3, 4, " o"), P(4, 5, " SIGEP."),
                P(5, 6, " Falei"), P(6, 7, " com"), P(7, 8, " Iracema"), P(8, 9, " e"), P(9, 10, " Iracema.")]
    termos = termos_da_reuniao(palavras)
    assert "SIGEP" in termos and "Iracema" in termos


# --- votação entre três hipóteses (casos reais da reunião de teste) ------------

def _h(*itens, t0=0.0):
    """Cria hipótese: itens (texto, prob) com 0,4 s por palavra a partir de t0."""
    return [P(t0 + i * 0.4, t0 + i * 0.4 + 0.35, f" {txt}", prob) for i, (txt, prob) in enumerate(itens)]


def _textos(resultado):
    palavras, _incertezas, _descartadas = resultado
    return [(p.texto.strip(), p.incerta) for p in palavras]


def test_combinar_mantem_palavra_confirmada_pela_terceira():
    h1 = _h(("Então,", 0.99), ("do", 0.8), ("total", 0.99), ("de", 0.99))
    h2 = _h(("Então,", 0.99), ("total", 0.99), ("de", 0.99))
    # 3ª hipótese com tempos deslocados: o casamento é por alinhamento, não por tempo
    h3 = _h(("Então,", 0.99), ("do", 0.7), ("total", 0.99), ("de", 0.99), t0=0.3)
    assert _textos(combinar(h1, h2, h3)) == [("Então,", False), ("do", False), ("total", False), ("de", False)]


def test_combinar_nao_apaga_palavra_contestada_sinaliza():
    h1 = _h(("Então,", 0.99), ("do", 0.8), ("total", 0.99))
    h2 = _h(("Então,", 0.99), ("total", 0.99))
    h3 = _h(("Então,", 0.99), ("total", 0.99))
    palavras, incertezas, _ = combinar(h1, h2, h3)
    assert [(p.texto.strip(), p.incerta) for p in palavras] == [("Então,", False), ("do", True), ("total", False)]
    assert incertezas[0].escolhido == "do" and "(nenhuma palavra)" in incertezas[0].alternativas


def test_combinar_palavra_inventada_fica_incerta_com_alternativas():
    h1 = _h(("contrato.", 1.0), ("Tchérrita.", 0.57), ("Juliana,", 0.99))
    h2 = _h(("contrato.", 1.0), ("Certo.", 0.47), ("Juliana,", 0.57))
    h3 = _h(("contrato.", 1.0), ("Tchegada.", 0.62), ("Juliana,", 1.0))
    palavras, incertezas, _ = combinar(h1, h2, h3)
    assert [(p.texto.strip(), p.incerta) for p in palavras] == [("contrato.", False), ("Tchérrita.", True),
                                                                 ("Juliana,", False)]
    assert set(incertezas[0].alternativas) == {"Certo.", "Tchegada."}


def test_combinar_grafia_diferente_mesmos_sons_mantem_primeiro_passo():
    h1 = _h(("Então,", 1.0), ("a", 0.41), ("gente,", 1.0), ("a", 1.0), ("gente", 1.0))
    h2 = _h(("Então,", 1.0), ("agente,", 0.3), ("a", 1.0), ("gente", 1.0))
    h3 = _h(("Então,", 1.0), ("agente,", 0.3), ("a", 1.0), ("gente", 1.0))
    assert _textos(combinar(h1, h2, h3)) == [("Então,", False), ("a", False), ("gente,", False), ("a", False),
                                             ("gente", False)]
    h1b = _h(("cerca", 1.0), ("de", 1.0), ("62%.", 0.9))
    h2b = _h(("cerca", 1.0), ("de", 1.0), ("62", 0.9), ("por", 0.9), ("cento.", 0.9))
    assert _textos(combinar(h1b, h2b, [])) == [("cerca", False), ("de", False), ("62%.", False)]


def test_combinar_descarta_alucinacao_fora_da_fala():
    # "É isso aí?" inventado no ruído depois do fim da reunião (nenhum detector ouviu voz ali)
    h1 = _h(("Obrigada", 0.99), ("a", 0.99), ("todos.", 0.99), ("É", 0.7), ("isso", 0.7), ("aí?", 0.7))
    h2 = _h(("Obrigada", 0.99), ("a", 0.99), ("todos.", 0.99))
    h3 = _h(("Obrigada", 0.99), ("a", 0.99), ("todos.", 0.99))
    fala = [(0.0, 1.3)]
    palavras, _, descartadas = combinar(h1, h2, h3, fala=fala)
    assert [p.texto.strip() for p in palavras] == ["Obrigada", "a", "todos."]
    assert [p.texto.strip() for p in descartadas] == ["É", "isso", "aí?"]
    # com fala detectada no trecho, as palavras ficam (sinalizadas), nunca somem sem aviso
    palavras, _, descartadas = combinar(h1, h2, h3, fala=[(0.0, 3.0)])
    assert [(p.texto.strip(), p.incerta) for p in palavras][-3:] == [("É", True), ("isso", True), ("aí?", True)]
    assert descartadas == []


def test_combinar_descarta_insercao_de_uma_so_decodificacao():
    h1 = _h(("a", 0.9), ("gente", 0.9))
    h2 = _h(("a", 0.9), ("é", 0.5), ("gente", 0.9))
    h3 = _h(("a", 0.9), ("gente", 0.9))
    assert _textos(combinar(h1, h2, h3)) == [("a", False), ("gente", False)]
    # inserção confirmada pela 3ª hipótese entra (o 1º passo omitiu a palavra)
    h3b = _h(("a", 0.9), ("é", 0.6), ("gente", 0.9))
    assert _textos(combinar(h1, h2, h3b)) == [("a", False), ("é", False), ("gente", False)]


def test_combinar_recupera_fala_em_lacuna():
    h2 = _h(("Certo.", 0.9), t0=10.0)
    h3 = _h(("Certo.", 0.8), t0=10.0)
    assert _textos(combinar([], h2, h3, lacunas=[(9.9, 10.5)])) == [("Certo.", False)]
    # sem confirmação da 3ª hipótese: entra sinalizada
    assert _textos(combinar([], _h(("Certo.", 0.7), t0=10.0), [], lacunas=[(9.9, 10.5)])) == [("Certo.", True)]
    # fora de lacuna, inserção isolada é descartada
    assert _textos(combinar([], h2, [])) == []


def test_combinar_maioria_corrige_e_sem_maioria_sinaliza():
    h1 = _h(("o", 0.9), ("CIGEP", 0.6))
    h2 = _h(("o", 0.9), ("SIGEP", 0.7))
    h3 = _h(("o", 0.9), ("SIGEP", 0.8))
    assert _textos(combinar(h1, h2, h3)) == [("o", False), ("SIGEP", False)]
    h3b = _h(("o", 0.9), ("xyz", 0.5))
    assert _textos(combinar(h1, h2, h3b)) == [("o", False), ("SIGEP", True)]


# --- diarização e montagem ---------------------------------------------------

def test_palavras_em_sobreposicao_seguem_a_frase():
    # Juliana interrompe Roberto: "Desculpa interromper, mas isso impacta o orçamento?"
    exclusivos = [Turno(35.67, 41.678, "R"), Turno(41.678, 43.653, "J")]
    turnos = [Turno(35.671, 41.678, "R"), Turno(40.666, 43.653, "J")]
    palavras = [P(40.24, 40.52, " acesso"), P(40.52, 40.82, " de"), P(40.82, 41.32, " homologação."),
                P(41.32, 41.34, " Desculpa"), P(41.34, 41.72, " interromper,"), P(41.88, 42.24, " mas"),
                P(42.24, 42.48, " isso"), P(42.48, 43.04, " impacta"), P(43.04, 43.08, " o"),
                P(43.08, 43.46, " orçamento?")]
    op = OpcoesMontagem()
    infos = atribuir_falantes(palavras, exclusivos, op, turnos)
    suavizar(palavras, infos, op, turnos)
    assert [p.falante for p in palavras] == ["R", "R", "R"] + ["J"] * 7


def test_exclusivizar_mantem_turno_mais_longo():
    turnos = [Turno(0, 10, "A"), Turno(4, 5, "B")]
    exc = exclusivizar(turnos)
    assert [(t.inicio, t.fim, t.falante) for t in exc] == [(0, 10, "A")]
    turnos = [Turno(0, 5, "A"), Turno(4.5, 9, "B")]
    exc = exclusivizar(turnos)
    assert exc[0].falante == "A" and exc[-1].falante == "B"


def _cenario_conversa():
    exclusivos = [Turno(0.0, 3.0, "S0"), Turno(3.0, 4.0, "S1"), Turno(4.0, 8.0, "S0")]
    palavras = [
        P(0.1, 0.5, " Precisamos"), P(0.5, 1.0, " definir"), P(1.0, 1.4, " a"), P(1.4, 2.8, " integração."),
        P(3.1, 3.6, " Sim."),
        P(3.95, 4.3, " E"), P(4.3, 4.8, " o"), P(4.8, 5.5, " prazo?"),
    ]
    return exclusivos, palavras


def test_atribuicao_e_suavizacao():
    exclusivos, palavras = _cenario_conversa()
    op = OpcoesMontagem()
    infos = atribuir_falantes(palavras, exclusivos, op)
    suavizar(palavras, infos, op)
    assert [p.falante for p in palavras] == ["S0"] * 4 + ["S1"] + ["S0"] * 3


def test_suavizacao_corrige_inicio_de_frase_vazado():
    # "Então" começa 0,2 s antes do turno do falante B (imprecisão de tempo)
    exclusivos = [Turno(0, 5.0, "A"), Turno(5.0, 9.0, "B")]
    palavras = [P(1, 2, " Fechado."), P(4.8, 5.2, " Então"), P(5.2, 5.6, " vamos"), P(5.6, 6.0, " seguir"),
                P(6.0, 6.5, " assim.")]
    op = OpcoesMontagem()
    infos = atribuir_falantes(palavras, exclusivos, op)
    suavizar(palavras, infos, op)
    assert [p.falante for p in palavras] == ["A", "B", "B", "B", "B"]


def test_blocos_e_marcadores():
    exclusivos, palavras = _cenario_conversa()
    op = OpcoesMontagem()
    infos = atribuir_falantes(palavras, exclusivos, op)
    suavizar(palavras, infos, op)
    palavras[6].incerta = True  # " o"
    palavras[7].incerta = True  # " prazo?"
    # S2 fala por 1,2 s enquanto S0 está sendo transcrito, sem nenhuma palavra própria.
    turnos = exclusivos + [Turno(4.2, 5.4, "S2")]
    simult = marcadores_simultaneos(palavras, turnos, op)
    assert len(simult) == 1 and simult[0].falante == "S2"
    marcadores = [Marcador(6.5, 8.0, "inaudivel", "S0")] + simult
    rot = rotular(palavras, marcadores, turnos)
    assert rot == {"S0": "Participante 1", "S1": "Participante 2", "S2": "Participante 3"}
    blocos = montar_blocos(palavras, marcadores, turnos, rot, op)
    assert [b.falante for b in blocos] == ["Participante 1", "Participante 2", "Participante 1"]
    assert texto_bloco(blocos[0]) == "Precisamos definir a integração."
    assert texto_bloco(blocos[1]) == "Sim."
    assert texto_bloco(blocos[2]) == ("E [falas simultâneas: Participante 3] [trecho incerto: o prazo]? "
                                      "[inaudível]")


def test_turno_curto_ou_sem_fala_concorrente_nao_vira_marcador():
    palavras = [P(0, 1, " Bom", falante="A"), P(1, 2, " dia.", falante="A")]
    op = OpcoesMontagem()
    assert marcadores_simultaneos(palavras, [Turno(0.5, 1.2, "B")], op) == []  # curto demais
    assert marcadores_simultaneos(palavras, [Turno(3.0, 6.0, "B")], op) == []  # ninguém mais falando


def test_sobreposicao_no_inicio_do_bloco():
    palavras = [P(0, 1, " Eu", falante="A"), P(1, 2.0, " acho", falante="A"), P(2.0, 3.0, " que", falante="A"),
                P(2.5, 3.2, " Não,", falante="B"), P(3.2, 3.8, " espera.", falante="B")]
    turnos = [Turno(0, 3.5, "A"), Turno(2.4, 4.0, "B")]
    blocos = montar_blocos(palavras, [], turnos, {"A": "Participante 1", "B": "Participante 2"}, OpcoesMontagem())
    assert texto_bloco(blocos[1]).startswith("[falas simultâneas com Participante 1] Não, espera.")


def test_sobreposicao_medida_pelo_inicio_do_turno():
    # Interrupção real começou em 40,67 s, mas o reconhecedor pôs a 1ª palavra em 41,32 s.
    palavras = [P(39.0, 40.8, " homologação.", falante="R"), P(41.32, 41.72, " Desculpa", falante="J"),
                P(41.9, 43.4, " interromper.", falante="J"), P(44.0, 45.0, " Não.", falante="R")]
    turnos = [Turno(35.67, 41.68, "R"), Turno(40.67, 43.65, "J"), Turno(43.9, 45.2, "R")]
    rot = {"R": "Participante 1", "J": "Participante 2"}
    blocos = montar_blocos(palavras, [], turnos, rot, OpcoesMontagem())
    assert blocos[1].sobreposto_a == ["Participante 1"]
    assert blocos[2].sobreposto_a == []  # turno normal, sem sobreposição


# --- revisão -----------------------------------------------------------------

def test_lacunas_e_janelas():
    palavras = [P(0.5, 1.0, " um"), P(1.0, 1.5, " dois"), P(6.0, 6.5, " três")]
    fala = [(0.4, 1.6), (3.0, 4.5), (5.9, 6.6)]
    assert lacunas(fala, palavras, 0.5) == [(3.0, 4.5)]
    janelas = montar_janelas([(3.0, 4.5, "lacuna")], palavras, 10.0, OpcoesRevisao())
    assert len(janelas) == 1
    j = janelas[0]
    assert j.inicio <= 3.0 and j.fim >= 4.5
    # limites não cortam palavras
    for p in palavras:
        assert not (p.inicio < j.inicio < p.fim) and not (p.inicio < j.fim < p.fim)


def test_janelas_nao_se_sobrepoem():
    palavras = [P(i * 0.5, i * 0.5 + 0.4, f" p{i}") for i in range(200)]
    alvos = [(5, 6, "a"), (20, 21, "b"), (22, 60, "c")]
    janelas = montar_janelas(alvos, palavras, 100.0, OpcoesRevisao())
    for a, b in zip(janelas, janelas[1:]):
        assert a.fim <= b.inicio + 1e-9
    assert all(j.fim - j.inicio <= OpcoesRevisao().janela_maxima + 1e-6 for j in janelas)


# --- exportação e nomes ------------------------------------------------------

def _documento():
    exclusivos, palavras = _cenario_conversa()
    op = OpcoesMontagem()
    suavizar(palavras, atribuir_falantes(palavras, exclusivos, op), op)
    rot = rotular(palavras, [], exclusivos)
    blocos = montar_blocos(palavras, [], exclusivos, rot, op)
    return Documento("reuniao.mp4", "reuniao.mp4", 8.0, "04/11/2026 10:00", "Whisper", "pyannote",
                     [("Participante 1", "Participante 1"), ("Participante 2", "Participante 2")],
                     blocos, palavras, [], rot)


def test_markdown_no_formato_pedido():
    md = para_markdown(_documento())
    assert "**[00:00:00] Participante 1:** Precisamos definir a integração." in md
    assert "**[00:00:03] Participante 2:** Sim." in md
    assert "—" not in md


def test_srt():
    doc = _documento()
    srt = para_srt(doc)
    blocos = [b for b in srt.strip().split("\n\n")]
    assert blocos[0].startswith("1\n00:00:00,100 --> ")
    assert "Participante 1: Precisamos definir a integração." in blocos[0].replace("\n", " ")
    legendas = gerar_legendas(doc)
    for a, b in zip(legendas, legendas[1:]):
        assert a.fim <= b.inicio


def test_sugestao_de_nomes():
    frases = [(t, t + 1.5, f, tx) for t, f, tx in [
        (0.0, "A", "Bom dia, meu nome é Ana Souza e eu coordeno o projeto."),
        (5.0, "B", "Obrigado, Ana."),
        (7.0, "B", "Carlos, você pode apresentar os números?"),
        (9.0, "C", "Claro, posso sim."),
        (12.0, "A", "Então, você pode começar?"),
        (14.0, "C", "Lembrei de uma coisa sobre o prazo."),
        (16.0, "A", "Bem lembrado, Carlos."),
        (18.0, "A", "Beatriz, como está a parte financeira?"),
        (20.0, "D", "Está dentro do previsto."),
        (22.0, "D", "Quer dizer, quase tudo?"),
        (24.0, "D", "Eduardo, você confirma?"),
        (60.0, "B", "Confirmo."),  # resposta distante demais: não vira indício
    ]]
    ev = sugerir(frases)
    assert not any(e.nome == "Eduardo" for e in ev)
    pares = {(e.falante, e.nome, e.tipo) for e in ev}
    assert ("A", "Ana Souza", "direta") in pares
    assert ("A", "Ana", "indireta") in pares
    assert ("C", "Carlos", "indireta") in pares  # convite ao próximo e reação ao anterior
    assert ("D", "Beatriz", "indireta") in pares
    assert not any(e.nome in ("Então", "Quer") for e in ev)
    grupos = agrupar(ev)
    assert grupos["C"][0][0] == "Carlos" and grupos["C"][0][2] == 2
