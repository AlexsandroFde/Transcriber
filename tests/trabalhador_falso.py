"""Processo trabalhador falso: fala o mesmo protocolo do verdadeiro, sem modelos de IA.

O campo `contexto` dos parâmetros controla o comportamento:
  "falhar": emite um erro descrito na etapa 3; "travar": termina sem avisar na etapa 2;
  "lento": cada etapa demora 0,4 s (para testar cancelamento e fila).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def emitir(evento: dict) -> None:
    sys.stdout.write(json.dumps(evento, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> None:
    comando = json.loads(sys.stdin.readline())
    p = comando.get("parametros") or {}
    tipo = comando.get("tipo")
    if tipo == "transcricao":
        contexto = p.get("contexto") or ""
        for n in range(1, 7):
            emitir({"evento": "etapa", "numero": n, "total": 6, "texto": f"Etapa {n}", "situacao": "executando"})
            emitir({"evento": "progresso", "fracao": 0.5})
            emitir({"evento": "log", "nivel": "INFO", "mensagem": f"mensagem da etapa {n}"})
            print(f"saida de biblioteca {n}", file=sys.stderr, flush=True)
            if contexto == "lento":
                time.sleep(0.4)
            if contexto == "falhar" and n == 3:
                emitir({"evento": "erro", "codigo": "memoria_gpu", "mensagem": "Faltou memória na placa de vídeo.",
                        "dica": "Escolha a precisão int8_float16.", "detalhe": "Traceback (falso)\nRuntimeError"})
                sys.exit(1)
            if contexto == "travar" and n == 2:
                os._exit(7)
        from sintetico import dados_sinteticos

        from transcritor.processamento.documento import gerar_saidas
        from transcritor.processamento.pipeline import pasta_de_saida

        arq = Path(p["arquivo"])
        pasta = pasta_de_saida(arq, Path(p["pasta_saida"]) if p.get("pasta_saida") else None)
        pasta.mkdir(parents=True, exist_ok=True)
        dados = dados_sinteticos(arq)
        dados["processamento"]["contexto"] = contexto or None
        arquivos = gerar_saidas(dados, pasta, p.get("formatos") or ["md", "txt", "docx", "srt", "vtt", "json"])
        emitir({"evento": "resultado", "dados": {"tipo": "transcricao", "caminho_json": str(pasta / f"{arq.stem}.json"),
                                                 "pasta": str(pasta), "arquivos": [str(a) for a in arquivos]}})
    elif tipo == "verificacao":
        emitir({"evento": "etapa", "numero": 1, "total": 1, "texto": "Verificando", "situacao": "executando"})
        emitir({"evento": "resultado", "dados": {
            "tipo": "verificacao", "versao": "2.0.0", "python": "3.12", "plataforma": "teste",
            "ffmpeg": {"disponivel": True, "caminho": "ffmpeg"},
            "gpu": {"disponivel": False, "descricao": "nenhuma (CPU)", "mensagem": "indisponível"},
            "token_hf": {"configurado": False, "acesso_modelo": "sem_token"},
            "modelos": [{"id": "reconhecimento", "nome": "Whisper large-v3", "descricao": "x", "baixado": False}],
            "pronto": True, "avisos": ["Os modelos de IA (cerca de 3 GB) ainda não foram baixados: isso acontece na "
                                       "primeira transcrição."], "verificado_em": "2026-11-05T10:00:00-03:00"}})
    elif tipo == "download_modelos":
        for n in (1, 2):
            emitir({"evento": "etapa", "numero": n, "total": 3, "texto": f"Modelo {n}", "situacao": "executando"})
        emitir({"evento": "etapa", "numero": 3, "total": 3, "texto": "Sem token", "situacao": "ignorada"})
        emitir({"evento": "resultado", "dados": {"tipo": "download_modelos", "mensagens": ["ok"], "modelos": [
            {"id": "reconhecimento", "nome": "Whisper large-v3", "descricao": "x", "baixado": True}]}})
    else:
        sys.exit(2)


if __name__ == "__main__":
    main()
