"""Processo trabalhador: executa uma tarefa pesada e informa o andamento ao servidor.

Uso interno (`python -m transcritor.trabalhador`), iniciado por `servicos.execucao`.

Protocolo:
  * entrada padrão, uma linha: {"tipo": "transcricao" | "verificacao" | "download_modelos",
    "parametros": {...}, "pid_servidor": 1234}; se o processo do servidor terminar, o
    trabalhador sai imediatamente;
  * saída padrão: um evento JSON por linha:
      {"evento": "etapa", "numero": 3, "total": 6, "texto": "...", "situacao": "executando"}
      {"evento": "progresso", "fracao": 0.42}
      {"evento": "log", "nivel": "INFO", "mensagem": "..."}
      {"evento": "resultado", "dados": {...}}
      {"evento": "erro", "codigo": "...", "mensagem": "...", "dica": "...", "detalhe": "..."}
  * qualquer outra saída (bibliotecas nativas, avisos) vai para a saída de erro, que o
    servidor grava no registro da tarefa.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("transcritor")


class Emissor:
    def __init__(self, canal) -> None:
        self._canal = canal
        self._lock = threading.Lock()

    def emitir(self, evento: dict[str, Any]) -> None:
        linha = json.dumps(evento, ensure_ascii=False, default=str)
        with self._lock:
            try:
                self._canal.write(linha + "\n")
                self._canal.flush()
            except (BrokenPipeError, OSError, ValueError):
                os._exit(3)  # o servidor não está mais lendo


class ManipuladorEventos(logging.Handler):
    """Envia as mensagens do processamento ao servidor. Faz o papel do "console" do `configurar_log`."""

    def __init__(self, emissor: Emissor) -> None:
        super().__init__()
        self.emissor = emissor
        self._transcritor_console = True
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(record, "etapa_transcritor", False):
            return  # já enviada como evento "etapa"
        try:
            mensagem = self.format(record).strip("\n")
        except Exception:
            return
        if mensagem.strip():
            self.emissor.emitir({"evento": "log", "nivel": record.levelname, "mensagem": mensagem})


class _Barra:
    def __init__(self, emissor: Emissor) -> None:
        self.emissor = emissor
        self._ultimo = -1.0
        self._t = 0.0

    def __call__(self, fracao: float) -> None:
        f = max(0.0, min(1.0, float(fracao)))
        agora = time.monotonic()
        if f - self._ultimo >= 0.005 or agora - self._t >= 1.0 or (f >= 1.0 > self._ultimo):
            self._ultimo, self._t = f, agora
            self.emissor.emitir({"evento": "progresso", "fracao": round(f, 4)})

    def fim(self) -> None:
        pass


class RelatorEventos:
    """`Relator` do pipeline que transforma etapas e barras de progresso em eventos."""

    def __init__(self, emissor: Emissor) -> None:
        self.emissor = emissor

    def etapa(self, numero: int, total: int, texto: str, situacao: str = "executando") -> None:
        self.emissor.emitir({"evento": "etapa", "numero": numero, "total": total, "texto": texto,
                             "situacao": situacao})
        # Também no registro da transcrição (<nome>.log), como na linha de comando.
        log.info("[%d/%d] %s", numero, total, texto, extra={"etapa_transcritor": True})

    def barra(self, rotulo: str) -> _Barra:
        return _Barra(self.emissor)


def _abrir_canal():
    """Reserva a saída padrão para o protocolo; o que for escrito nela depois vai para stderr."""
    fd = os.dup(1)
    os.dup2(2, 1)
    return os.fdopen(fd, "w", encoding="utf-8", buffering=1, newline="\n")


def _soltar_entrada() -> None:
    """Troca a entrada padrão por NUL (nada mais será lido dela)."""
    try:
        nulo = os.open(os.devnull, os.O_RDONLY)
        os.dup2(nulo, 0)
        os.close(nulo)
    except OSError:
        pass


def _vigiar_servidor(pid: int | None) -> None:
    """Sai imediatamente se o processo do servidor terminar (evita trabalhadores órfãos)."""
    if not pid:
        return
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        handle = k32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            os._exit(3)  # o servidor já não existe

        def vigiar() -> None:
            k32.WaitForSingleObject(handle, 0xFFFFFFFF)
            os._exit(3)
    else:
        def vigiar() -> None:
            while True:
                time.sleep(2)
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    os._exit(3)
                except PermissionError:
                    pass

    threading.Thread(target=vigiar, name="vigia-servidor", daemon=True).start()


def _transcrever(parametros: dict, emissor: Emissor) -> dict:
    from .processamento.documento import arquivo_relatorio
    from .processamento.pipeline import processar
    from .servicos.contratos import ParametrosTranscricao, ResultadoTarefaTranscricao
    from .servicos.transcricoes import construir_opcoes

    params = ParametrosTranscricao.model_validate(parametros)
    op = construir_opcoes(params)
    caminho_json = processar(Path(params.arquivo), op, RelatorEventos(emissor))
    pasta, base = caminho_json.parent, caminho_json.stem
    candidatos = [pasta / f"{base}.{f}" for f in dict.fromkeys([*op.formatos, "json"])]
    candidatos += [arquivo_relatorio(pasta, base), pasta / f"{base}.log"]
    return ResultadoTarefaTranscricao(caminho_json=str(caminho_json), pasta=str(pasta),
                                      arquivos=[str(c) for c in candidatos if c.is_file()]).model_dump(mode="json")


def _verificar(parametros: dict, emissor: Emissor) -> dict:
    from .servicos.diagnostico import verificar

    emissor.emitir({"evento": "etapa", "numero": 1, "total": 1, "texto": "Verificando placa de vídeo, ffmpeg, "
                    "modelos e token", "situacao": "executando"})
    return verificar(parametros.get("modelo") or "large-v3").model_dump(mode="json")


def _baixar(parametros: dict, emissor: Emissor) -> dict:
    from .servicos.diagnostico import baixar_modelos

    def etapa(numero: int, texto: str, situacao: str) -> None:
        emissor.emitir({"evento": "etapa", "numero": numero, "total": 3, "texto": texto, "situacao": situacao})
        log.info(texto, extra={"etapa_transcritor": True})

    return baixar_modelos(parametros.get("modelo") or "large-v3", etapa).model_dump(mode="json")


EXECUTORES = {"transcricao": _transcrever, "verificacao": _verificar, "download_modelos": _baixar}


def main() -> None:
    canal = _abrir_canal()
    emissor = Emissor(canal)
    try:
        comando = json.loads(sys.stdin.buffer.readline().decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        emissor.emitir({"evento": "erro", "codigo": "comando_invalido", "mensagem": f"Comando inválido: {e}"})
        os._exit(2)
    _soltar_entrada()
    _vigiar_servidor(comando.get("pid_servidor"))

    from .ambiente import configurar_log, preparar
    from .erros import descrever_excecao

    preparar()
    parametros = comando.get("parametros") or {}
    raiz = logging.getLogger("transcritor")
    raiz.addHandler(ManipuladorEventos(emissor))
    configurar_log(detalhado=bool(parametros.get("detalhado")))

    codigo = 0
    try:
        executor = EXECUTORES.get(comando.get("tipo"))
        if executor is None:
            raise ValueError(f"Tipo de tarefa desconhecido: {comando.get('tipo')}")
        emissor.emitir({"evento": "resultado", "dados": executor(parametros, emissor)})
    except BaseException as e:  # noqa: BLE001 - tudo vira um erro descrito para o servidor
        d = descrever_excecao(e)
        emissor.emitir({"evento": "erro", **d.para_dict()})
        codigo = 1
    finally:
        for h in logging.getLogger("transcritor").handlers:
            try:
                h.flush()
            except Exception:
                pass
    # os._exit: não espera threads de bibliotecas (a memória da GPU é liberada com o processo).
    os._exit(codigo)


if __name__ == "__main__":
    main()
