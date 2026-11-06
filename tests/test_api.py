"""Testes da API REST (com o trabalhador falso: sem modelos de IA)."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from conftest import aguardar
from sintetico import dados_sinteticos


def _erro(r, status: int, codigo: str | None = None) -> dict:
    assert r.status_code == status, r.text
    corpo = r.json()["erro"]
    assert corpo["status"] == status and corpo["mensagem"]
    if codigo:
        assert corpo["codigo"] == codigo, corpo
    return corpo


def _transcrever(cliente, wav: Path, **opcoes) -> dict:
    r = cliente.post("/api/v1/transcricoes", json={"arquivos": [str(wav)], **opcoes})
    assert r.status_code == 202, r.text
    tarefa = r.json()["tarefas"][0]
    assert r.headers["location"] == f"/api/v1/tarefas/{tarefa['id']}"
    return tarefa


# -- sistema e documentação -----------------------------------------------------------------


def test_saude_sistema_e_catalogo(cliente):
    saude = cliente.get("/api/v1/saude").json()
    assert saude["status"] == "ok" and saude["aplicacao"] == "transcritor" and saude["versao"] == "2.0.0"
    info = cliente.get("/api/v1/sistema").json()
    assert info["documentacao"] == "/docs" and info["pastas"]["dados"]
    cat = cliente.get("/api/v1/opcoes").json()
    assert cat["padroes"]["modelo"] == "large-v3" and cat["padroes"]["estilo"] == "literal"
    assert "hf_token" not in cat["padroes"]
    assert {o["valor"] for o in cat["diarizacao"]} == {"auto", "pyannote", "livre", "sherpa", "nenhuma"}
    assert [o["valor"] for o in cat["formatos"]][0] == "docx"


def test_openapi_documenta_todas_as_rotas(cliente):
    spec = cliente.get("/api/v1/openapi.json").json()
    assert spec["openapi"].startswith("3.1")
    nomes_tags = {t["name"] for t in spec["tags"]}
    for caminho, operacoes in spec["paths"].items():
        for metodo, op in operacoes.items():
            assert op.get("summary"), f"{metodo} {caminho} sem resumo"
            assert op.get("tags") and set(op["tags"]) <= nomes_tags, f"{metodo} {caminho} sem categoria"
    pedido = spec["paths"]["/api/v1/transcricoes"]["post"]
    assert {"202", "409", "422"} <= set(pedido["responses"])
    assert pedido["requestBody"]["content"]["application/json"]["examples"]
    assert "RespostaErro" in spec["components"]["schemas"]


def test_docs_offline(cliente):
    html = cliente.get("/docs").text
    assert "/vendor/swagger-ui/swagger-ui-bundle.js" in html and "/api/v1/openapi.json" in html
    assert "cdn." not in html
    assert cliente.get("/vendor/swagger-ui/swagger-ui-bundle.js").status_code == 200
    assert cliente.get("/").status_code == 200


def test_rota_inexistente_no_formato_padrao(cliente):
    _erro(cliente.get("/api/v1/nao-existe"), 404, "rota_nao_encontrada")
    _erro(cliente.put("/api/v1/saude"), 405, "metodo_nao_permitido")


# -- validação ----------------------------------------------------------------------------


def test_validacao_em_portugues_com_campos(cliente, wav):
    e = _erro(cliente.post("/api/v1/transcricoes", json={}), 422, "dados_invalidos")
    assert e["campos"] == [{"campo": "arquivos", "mensagem": "Campo obrigatório."}]
    e = _erro(cliente.post("/api/v1/transcricoes", json={"arquivos": [str(wav)], "min_participantes": 4,
                                                         "max_participantes": 2}), 422)
    assert e["campos"][0]["campo"] == "max_participantes" and "mínimo" in e["campos"][0]["mensagem"]
    e = _erro(cliente.post("/api/v1/transcricoes", json={"arquivos": [str(wav)], "faixa_audio": "segunda"}), 422)
    assert "todas" in e["campos"][0]["mensagem"]
    e = _erro(cliente.post("/api/v1/transcricoes", json={"arquivos": [str(wav)], "participantes": 0}), 422)
    assert e["campos"][0]["mensagem"] == "Deve ser maior ou igual a 1."
    e = _erro(cliente.post("/api/v1/transcricoes", json={"arquivos": [str(wav)], "formato": ["md"]}), 422)
    assert e["campos"][0]["mensagem"] == "Campo não reconhecido."
    e = _erro(cliente.post("/api/v1/transcricoes", json={"arquivos": [str(wav)], "diarizacao": "magica"}), 422)
    assert "auto" in e["campos"][0]["mensagem"]


def test_arquivo_inexistente_pasta_e_faixa(cliente, wav, tmp_path):
    e = _erro(cliente.post("/api/v1/transcricoes", json={"arquivos": [str(tmp_path / "nada.mp4")]}), 422,
              "arquivo_nao_encontrado")
    assert e["campos"][0]["campo"] == "arquivos[0]" and e["dica"]
    _erro(cliente.post("/api/v1/transcricoes", json={"arquivos": [str(tmp_path)]}), 422, "caminho_e_pasta")
    _erro(cliente.post("/api/v1/transcricoes", json={"arquivos": [str(wav)], "faixa_audio": "3"}), 422,
          "faixa_inexistente")
    texto = tmp_path / "nao_e_midia.mp4"
    texto.write_text("isto não é um vídeo", encoding="utf-8")
    _erro(cliente.post("/api/v1/transcricoes", json={"arquivos": [str(texto)]}), 422, "midia_invalida")
    _erro(cliente.post("/api/v1/transcricoes", json={"arquivos": [str(wav)],
                                                     "glossario_arquivo": str(tmp_path / "g.txt")}), 422,
          "glossario_nao_encontrado")


# -- fluxo completo -----------------------------------------------------------------------


def test_fluxo_completo_transcricao(cliente, wav, tmp_path):
    tarefa = _transcrever(cliente, wav, participantes=3, glossario=["SIGEP"], hf_token="hf_segredo_123",
                          glossario_texto="Mariana; Roberto # pessoas")
    assert tarefa["estado"] in ("na_fila", "em_andamento") and tarefa["pode_cancelar"]
    assert "hf_token" not in tarefa["parametros"] and "hf_segredo_123" not in json.dumps(tarefa)
    final = aguardar(cliente, tarefa["id"])
    assert final["estado"] == "concluida", final
    assert final["progresso"]["percentual"] == 100.0
    assert [e["estado"] for e in final["progresso"]["etapas"]] == ["concluida"] * 6
    tid = final["resultado"]["transcricao_id"]
    assert final["resultado"]["tipo"] == "transcricao" and Path(final["resultado"]["caminho_json"]).is_file()

    lista = cliente.get("/api/v1/transcricoes").json()
    assert lista["total"] == 1 and lista["itens"][0]["id"] == tid and lista["itens"][0]["disponivel"]
    assert cliente.get("/api/v1/transcricoes", params={"busca": "outra"}).json()["total"] == 0

    det = cliente.get(f"/api/v1/transcricoes/{tid}").json()
    assert det["nome"] == "reuniao.wav" and det["origem_disponivel"] and det["tem_video"] is False
    assert det["indicadores"]["incertas"] == 1 and det["indicadores"]["inaudiveis"] == 1
    tipos = {a["tipo"]: a for a in det["arquivos"]}
    assert tipos["docx"]["existe"] and tipos["relatorio"]["existe"]

    conteudo = cliente.get(f"/api/v1/transcricoes/{tid}/conteudo").json()
    assert conteudo["blocos"][0]["falante"] == "Participante 1"
    assert any(t["tipo"] == "incerto" for b in conteudo["blocos"] for t in b["trechos"])
    assert any(t["tipo"] == "marcador" and t["texto"] == "[inaudível]" for b in conteudo["blocos"] for t in b["trechos"])

    rel = cliente.get(f"/api/v1/transcricoes/{tid}/relatorio").json()
    assert {p["tipo"] for p in rel["pontos"]} == {"incerto", "inaudivel", "descartado"}
    assert any(s["nome"] == "Mariana" and s["autoidentificacoes"] == 1 for s in rel["sugestoes"])
    assert any(c["categoria"] == "Datas e prazos" for c in rel["mencoes"])

    docx = cliente.get(f"/api/v1/transcricoes/{tid}/arquivos/docx")
    assert docx.status_code == 200 and docx.content[:2] == b"PK"
    assert "attachment" in docx.headers["content-disposition"]
    md = cliente.get(f"/api/v1/transcricoes/{tid}/arquivos/md", params={"baixar": False})
    assert "inline" in md.headers["content-disposition"] and "Participante 1" in md.text
    midia = cliente.get(f"/api/v1/transcricoes/{tid}/midia", headers={"range": "bytes=0-99"})
    assert midia.status_code == 206 and len(midia.content) == 100


def test_nomes_unir_e_exportar(cliente, wav, tmp_path):
    tid = aguardar(cliente, _transcrever(cliente, wav)["id"])["resultado"]["transcricao_id"]
    partes = cliente.get(f"/api/v1/transcricoes/{tid}/participantes").json()["itens"]
    assert [p["rotulo"] for p in partes] == ["Participante 1", "Participante 2", "Participante 3"]
    p1 = partes[0]
    assert p1["sugestoes"][0]["nome"] == "Mariana" and p1["exemplos"] and p1["tempo_fala_s"] > 0

    # A união aparece antes do nome do alvo: a ordem não deve importar.
    r = cliente.patch(f"/api/v1/transcricoes/{tid}/participantes", json={"atribuicoes": [
        {"participante": "Participante 3", "nome": "participante 1"},
        {"participante": "s0", "nome": "Mariana"}]})
    assert r.status_code == 200, r.text
    corpo = r.json()
    nomes = {p["rotulo"]: p["exibicao"] for p in corpo["participantes"]}
    assert nomes == {"Participante 1": "Mariana", "Participante 2": "Participante 2", "Participante 3": "Mariana"}
    assert any(a["tipo"] == "docx" and a["existe"] for a in corpo["arquivos"])
    md = Path(cliente.get(f"/api/v1/transcricoes/{tid}").json()["pasta"]) / "reuniao.md"
    assert "**[00:00:00] Mariana:**" in md.read_text(encoding="utf-8")
    partes = cliente.get(f"/api/v1/transcricoes/{tid}/participantes").json()["itens"]
    assert partes[0]["unido_com"] == ["Participante 3"]

    _erro(cliente.patch(f"/api/v1/transcricoes/{tid}/participantes",
                        json={"atribuicoes": [{"participante": "Participante 9", "nome": "X"}]}), 404,
          "participante_nao_encontrado")
    _erro(cliente.patch(f"/api/v1/transcricoes/{tid}/participantes", json={}), 422)
    limpo = cliente.patch(f"/api/v1/transcricoes/{tid}/participantes", json={"limpar": True}).json()
    assert all(p["nome"] is None for p in limpo["participantes"])

    destino = tmp_path / "entregas"
    exp = cliente.post(f"/api/v1/transcricoes/{tid}/exportacoes",
                       json={"formatos": ["srt"], "pasta_destino": str(destino)}).json()
    tipos = sorted(a["tipo"] for a in exp["arquivos"])
    assert tipos == ["json", "relatorio", "srt"] and (destino / "reuniao.srt").is_file()
    assert cliente.post(f"/api/v1/transcricoes/{tid}/exportacoes").status_code == 200


def test_importar_e_remover_do_historico(cliente, tmp_path):
    from transcritor.processamento.documento import gerar_saidas

    pasta = tmp_path / "antiga_transcricao"
    pasta.mkdir()
    gerar_saidas(dados_sinteticos(tmp_path / "antiga.mp4"), pasta, ["json"])
    caminho = str(pasta / "antiga.json")
    r = cliente.post("/api/v1/transcricoes/importacoes", json={"caminho": caminho})
    assert r.status_code == 201 and r.json()["origem_disponivel"] is False
    tid = r.json()["id"]
    assert cliente.post("/api/v1/transcricoes/importacoes", json={"caminho": caminho}).status_code == 200
    _erro(cliente.get(f"/api/v1/transcricoes/{tid}/midia"), 404, "midia_indisponivel")
    _erro(cliente.get(f"/api/v1/transcricoes/{tid}/arquivos/docx"), 404, "arquivo_nao_gerado")
    invalido = tmp_path / "outro.json"
    invalido.write_text('{"a": 1}', encoding="utf-8")
    _erro(cliente.post("/api/v1/transcricoes/importacoes", json={"caminho": str(invalido)}), 422, "json_invalido")
    assert cliente.delete(f"/api/v1/transcricoes/{tid}").status_code == 204
    _erro(cliente.get(f"/api/v1/transcricoes/{tid}"), 404, "transcricao_nao_encontrada")
    assert Path(caminho).is_file()  # os arquivos continuam no disco


# -- tarefas ------------------------------------------------------------------------------


def test_falha_descrita_e_retomada(cliente, wav):
    final = aguardar(cliente, _transcrever(cliente, wav, contexto="falhar")["id"])
    assert final["estado"] == "falhou" and final["erro"]["codigo"] == "memoria_gpu" and final["erro"]["dica"]
    etapas = [e["estado"] for e in final["progresso"]["etapas"]]
    assert etapas[:3] == ["concluida", "concluida", "falhou"] and etapas[3:] == ["pendente"] * 3
    registro = cliente.get(f"/api/v1/tarefas/{final['id']}/registro").json()
    assert any("saida de biblioteca 1" in l for l in registro["linhas"])
    assert any("Traceback (falso)" in l for l in registro["linhas"])
    mais = cliente.get(f"/api/v1/tarefas/{final['id']}/registro", params={"desde": registro["proxima"]}).json()
    assert mais["linhas"] == []

    r = cliente.post(f"/api/v1/tarefas/{final['id']}/repetir")
    assert r.status_code == 202 and r.json()["origem_id"] == final["id"]
    assert aguardar(cliente, r.json()["id"])["estado"] == "falhou"


def test_trabalhador_que_trava(cliente, wav):
    final = aguardar(cliente, _transcrever(cliente, wav, contexto="travar")["id"])
    assert final["estado"] == "falhou" and final["erro"]["codigo"] == "trabalhador_encerrado"


def test_cancelar_fila_e_conflitos(cliente, wav, tmp_path):
    outro = tmp_path / "gravacoes" / "outra.wav"
    outro.write_bytes(wav.read_bytes())
    primeira = _transcrever(cliente, wav, contexto="lento")
    segunda = _transcrever(cliente, outro, contexto="lento")
    _erro(cliente.post("/api/v1/transcricoes", json={"arquivos": [str(wav)]}), 409, "transcricao_em_andamento")
    aguardar(cliente, primeira["id"], estados=("em_andamento",))
    fila = cliente.get(f"/api/v1/tarefas/{segunda['id']}").json()
    assert fila["estado"] == "na_fila" and fila["posicao_fila"] == 1

    cancelada = cliente.post(f"/api/v1/tarefas/{segunda['id']}/cancelar").json()
    assert cancelada["estado"] == "cancelada"
    r = cliente.post(f"/api/v1/tarefas/{primeira['id']}/cancelar")
    assert r.status_code == 200
    final = aguardar(cliente, primeira["id"])
    assert final["estado"] == "cancelada"
    _erro(cliente.post(f"/api/v1/tarefas/{primeira['id']}/cancelar"), 409, "tarefa_encerrada")

    lista = cliente.get("/api/v1/tarefas", params={"estado": ["cancelada"]}).json()
    assert lista["total"] == 2
    assert cliente.delete(f"/api/v1/tarefas/{segunda['id']}").status_code == 204
    _erro(cliente.get(f"/api/v1/tarefas/{segunda['id']}"), 404, "tarefa_nao_encontrada")


def test_tarefas_interrompidas_ao_reabrir(cfg):
    from transcritor.servicos.contexto import criar_servicos

    s1 = criar_servicos(cfg, modo="teste", verificar_ao_iniciar=False)
    s1.repositorio.salvar_tarefa({
        "id": "abcdef123456", "tipo": "transcricao", "estado": "em_andamento", "titulo": "x.mp4",
        "criada_em": "2026-11-05T10:00:00-03:00", "parametros": {"arquivo": "x.mp4"},
        "progresso": {"percentual": 40, "total_etapas": 6, "etapas": [
            {"numero": 1, "chave": "extracao", "titulo": "Extração do áudio", "estado": "em_andamento"}]}})
    s2 = criar_servicos(cfg, modo="teste", verificar_ao_iniciar=False)
    s2.iniciar()
    try:
        t = s2.tarefas.obter("abcdef123456")
        assert t.estado == "interrompida" and t.pode_repetir and t.erro.codigo == "interrompida"
        assert t.progresso.etapas[0].estado == "interrompida"
    finally:
        s2.encerrar()


def test_verificacao_e_download(cliente):
    r = cliente.post("/api/v1/ambiente/verificacoes")
    assert r.status_code == 202
    assert aguardar(cliente, r.json()["id"])["estado"] == "concluida"
    amb = cliente.get("/api/v1/ambiente").json()
    assert amb["situacao"] == "verificado" and amb["relatorio"]["pronto"] and amb["relatorio"]["avisos"]
    r = cliente.post("/api/v1/ambiente/modelos/downloads", json={"modelo": "large-v3"})
    final = aguardar(cliente, r.json()["id"])
    assert [e["estado"] for e in final["progresso"]["etapas"]] == ["concluida", "concluida", "ignorada"]
    amb = cliente.get("/api/v1/ambiente").json()
    assert amb["relatorio"]["modelos"][0]["baixado"] is True and amb["relatorio"]["avisos"] == []


# -- configuração e mídia -------------------------------------------------------------------


def test_token_nunca_e_devolvido(cliente, cfg):
    assert cliente.get("/api/v1/configuracao/token-hf").json()["configurado"] is False
    r = cliente.put("/api/v1/configuracao/token-hf", json={"token": "  hf_abcdefghijklmnop1234  "})
    assert r.status_code == 200 and "hf_abcdefghijklmnop1234" not in r.text
    estado = r.json()
    assert estado["configurado"] and estado["origem"] == "arquivo" and estado["final"] == "1234"
    assert cfg.arquivo_token.read_text(encoding="utf-8").strip() == "hf_abcdefghijklmnop1234"
    _erro(cliente.put("/api/v1/configuracao/token-hf", json={"token": "hf ab cdefgh"}), 422)
    assert cliente.delete("/api/v1/configuracao/token-hf").json()["configurado"] is False
    assert not cfg.arquivo_token.exists()


def test_token_de_variavel_nao_pode_ser_removido(cliente, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_daVariavelDeAmbiente")
    estado = cliente.get("/api/v1/configuracao/token-hf").json()
    assert estado["origem"] == "variavel_ambiente" and estado["variavel"] == "HF_TOKEN"
    _erro(cliente.delete("/api/v1/configuracao/token-hf"), 409, "token_externo")


def test_glossario_padrao(cliente, tmp_path):
    g = cliente.get("/api/v1/configuracao/glossario").json()
    assert g["existe"] is False and g["termos"] == []
    g = cliente.put("/api/v1/configuracao/glossario", json={"texto": "# pessoas\nMariana; Roberto\nSIGEP"}).json()
    assert g["existe"] and g["termos"] == ["Mariana", "Roberto", "SIGEP"]
    r = cliente.post("/api/v1/configuracao/glossario/interpretar", json={"texto": "A;B # c"}).json()
    assert r["termos"] == ["A", "B"]
    arq = tmp_path / "g.txt"
    arq.write_text("LGPD\n", encoding="utf-8")
    assert cliente.post("/api/v1/configuracao/glossario/interpretar", json={"caminho": str(arq)}).json()["termos"] == ["LGPD"]
    _erro(cliente.post("/api/v1/configuracao/glossario/interpretar", json={}), 422)
    _erro(cliente.post("/api/v1/configuracao/glossario/interpretar", json={"caminho": str(tmp_path / "x.txt")}), 404)


def test_informacoes_da_midia_e_envios(cliente, wav):
    info = cliente.get("/api/v1/midia/informacoes", params={"caminho": str(wav)}).json()
    assert info["duracao_s"] and info["tem_video"] is False and info["faixas_audio"][0]["indice"] == 0
    assert info["pasta_saida_padrao"].endswith("reuniao_transcricao")
    _erro(cliente.get("/api/v1/midia/informacoes", params={"caminho": str(wav) + ".x"}), 404)

    r = cliente.post("/api/v1/midia/envios", files={"arquivo": ("../../perigoso nome.wav", wav.read_bytes(), "audio/wav")})
    assert r.status_code == 201, r.text
    envio = r.json()
    assert envio["nome"] == "perigoso nome.wav" and Path(envio["caminho"]).is_file()
    assert cliente.get("/api/v1/midia/envios").json()["total"] == 1
    tarefa = _transcrever(cliente, Path(envio["caminho"]), contexto="lento")
    _erro(cliente.delete(f"/api/v1/midia/envios/{envio['id']}"), 409, "envio_em_uso")
    aguardar(cliente, tarefa["id"])
    assert cliente.delete(f"/api/v1/midia/envios/{envio['id']}").status_code == 204
    assert not Path(envio["caminho"]).exists()
    assert (Path(envio["caminho"]).parent / "perigoso nome_transcricao").is_dir()  # resultados preservados


def test_abrir_recusa_tipos_perigosos(cliente, tmp_path):
    exe = tmp_path / "programa.exe"
    exe.write_bytes(b"MZ")
    _erro(cliente.post("/api/v1/sistema/abrir", json={"caminho": str(exe)}), 422, "tipo_nao_permitido")
    _erro(cliente.post("/api/v1/sistema/abrir", json={"caminho": str(tmp_path / "nada")}), 404)
    _erro(cliente.post("/api/v1/sistema/encerrar"), 409, "encerramento_indisponivel")


# -- segurança e eventos --------------------------------------------------------------------


def test_protecao_contra_sites_e_dns_rebinding(cliente):
    _erro(cliente.get("/api/v1/saude", headers={"host": "atacante.com"}), 400, "host_nao_permitido")
    _erro(cliente.post("/api/v1/configuracao/glossario/interpretar", json={"texto": "a"},
                       headers={"origin": "https://atacante.com"}), 403, "origem_nao_permitida")
    _erro(cliente.get("/api/v1/transcricoes", headers={"sec-fetch-site": "cross-site", "sec-fetch-mode": "cors"}),
          403, "origem_nao_permitida")
    # A própria interface e a navegação direta continuam funcionando.
    assert cliente.post("/api/v1/configuracao/glossario/interpretar", json={"texto": "a"},
                        headers={"origin": "http://127.0.0.1:8765"}).status_code == 200
    assert cliente.get("/docs", headers={"sec-fetch-site": "cross-site", "sec-fetch-mode": "navigate"}).status_code == 200
    assert cliente.get("/api/v1/saude", headers={"host": "localhost:8765"}).status_code == 200


def test_eventos_sse(cliente, servicos, wav):
    recebidos: list[str] = []

    def publicar_e_fechar():
        time.sleep(0.3)
        servicos.barramento.publicar("transcricao", {"id": "x", "acao": "registrada"})
        time.sleep(0.3)
        servicos.barramento.encerrar()

    threading.Thread(target=publicar_e_fechar, daemon=True).start()
    with cliente.stream("GET", "/api/v1/eventos") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        for linha in r.iter_lines():
            recebidos.append(linha)
    assert "event: conectado" in recebidos and "event: transcricao" in recebidos
    dados = json.loads(next(l for l in recebidos if l.startswith("data:") and "registrada" in l)[5:])
    assert dados["tipo"] == "transcricao" and dados["dados"]["acao"] == "registrada"
