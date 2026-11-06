from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pytest

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

URL = "http://127.0.0.1:8765"


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    """Configuração isolada em uma pasta temporária, com o trabalhador falso."""
    from transcritor import config

    for var in ("TRANSCRITOR_HF_TOKEN", "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    import huggingface_hub

    monkeypatch.setattr(huggingface_hub, "get_token", lambda: None)
    c = config.carregar().com(
        pasta_config=tmp_path / "config", pasta_dados=tmp_path / "dados", pasta_modelos=tmp_path / "modelos",
        arquivo_glossario=tmp_path / "config" / "glossario.txt", porta=0,
        comando_trabalhador=(sys.executable, str(AQUI / "trabalhador_falso.py")))
    anterior = config._ATUAL
    config.definir(c)
    yield c
    config._ATUAL = anterior


@pytest.fixture
def servicos(cfg):
    from transcritor.servicos.contexto import criar_servicos

    return criar_servicos(cfg, modo="teste", verificar_ao_iniciar=False)


@pytest.fixture
def cliente(servicos):
    from fastapi.testclient import TestClient

    from transcritor.api.app import criar_app

    with TestClient(criar_app(servicos), base_url=URL) as c:
        yield c


@pytest.fixture
def wav(tmp_path) -> Path:
    import soundfile as sf

    pasta = tmp_path / "gravacoes"
    pasta.mkdir()
    arq = pasta / "reuniao.wav"
    t = np.arange(16000 * 2) / 16000
    sf.write(str(arq), (0.1 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), 16000)
    return arq


def aguardar(cliente, tarefa_id: str, estados=("concluida", "falhou", "cancelada", "interrompida"),
             limite: float = 30.0) -> dict:
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        t = cliente.get(f"/api/v1/tarefas/{tarefa_id}").json()
        if t["estado"] in estados:
            return t
        time.sleep(0.05)
    raise AssertionError(f"A tarefa {tarefa_id} não chegou a {estados}: {t['estado']}")
