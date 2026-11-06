"""Execução de tarefas em um processo trabalhador separado.

Por que um processo e não uma thread:
  * cancelar uma transcrição exige interromper código nativo (ffmpeg, CUDA, CTranslate2),
    o que só é possível encerrando o processo; o cache por etapa torna isso seguro;
  * a memória da placa de vídeo é devolvida por completo ao fim de cada tarefa;
  * uma falha nativa (driver, falta de memória) não derruba a API nem a janela.

Garantia de encerramento: no Windows, cada trabalhador entra em um Job Object com
"encerrar ao fechar"; se o processo do servidor terminar por qualquer motivo, o sistema
encerra o trabalhador e os processos filhos dele (ffmpeg). Em todas as plataformas, o
trabalhador também observa o processo do servidor (pelo PID) e sai sozinho se ele desaparecer.

Protocolo: o servidor escreve o comando (JSON) numa única linha da entrada padrão e a fecha;
o trabalhador responde com eventos JSON, um por linha, na saída padrão (ver `trabalhador.py`).
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import threading
from collections.abc import Callable, Sequence
from pathlib import Path

log = logging.getLogger("transcritor.execucao")


class _JobObject:
    """Windows: Job Object que encerra todos os processos associados quando é fechado."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._k32 = k32
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class EXTENDED(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO_COUNTERS),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        self.handle = k32.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW falhou")
        info = EXTENDED()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            erro = ctypes.get_last_error()
            k32.CloseHandle(self.handle)
            raise OSError(erro, "SetInformationJobObject falhou")

    def atribuir(self, pid: int) -> None:
        PROCESS_SET_QUOTA, PROCESS_TERMINATE = 0x0100, 0x0001
        h = self._k32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
        if not h:
            raise OSError(self._ctypes.get_last_error(), "OpenProcess falhou")
        try:
            if not self._k32.AssignProcessToJobObject(self.handle, h):
                raise OSError(self._ctypes.get_last_error(), "AssignProcessToJobObject falhou")
        finally:
            self._k32.CloseHandle(h)

    def terminar(self, codigo: int = 1) -> None:
        if self.handle:
            self._k32.TerminateJobObject(self.handle, codigo)

    def fechar(self) -> None:
        if self.handle:
            self._k32.CloseHandle(self.handle)
            self.handle = None


def interpretador() -> tuple[str, dict[str, str]]:
    """(executável, variáveis de ambiente extras) para iniciar o trabalhador.

    * Sempre a versão com console (python.exe, com a janela oculta), para que os processos
      filhos (ffmpeg) herdem o console invisível em vez de abrir janelas.
    * No Windows, o python.exe de um ambiente virtual é um lançador que cria um segundo
      processo. Iniciamos direto o interpretador real com `__PYVENV_LAUNCHER__` (o mesmo
      mecanismo que o lançador usa), para que o Job Object alcance o processo que trabalha.
    """
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").exists():
        exe = exe.with_name("python.exe")
    extras: dict[str, str] = {}
    base = getattr(sys, "_base_executable", None)
    if sys.platform == "win32" and base and sys.prefix != sys.base_prefix:
        real = Path(base).with_name("python.exe")
        if real.is_file() and real.resolve() != exe.resolve():
            extras["__PYVENV_LAUNCHER__"] = str(exe)
            exe = real
    return str(exe), extras


def comando_padrao() -> list[str]:
    return [interpretador()[0], "-X", "utf8", "-m", "transcritor.trabalhador"]


class ProcessoTrabalhador:
    def __init__(self, comando: dict, *, ao_evento: Callable[[dict], None], ao_texto: Callable[[str], None],
                 executavel: Sequence[str] | None = None):
        self.comando = {**comando, "pid_servidor": os.getpid()}
        self.ao_evento = ao_evento
        self.ao_texto = ao_texto
        self.executavel = list(executavel) if executavel else comando_padrao()
        self._env_extra = {} if executavel else interpretador()[1]
        self._proc: subprocess.Popen | None = None
        self._job: _JobObject | None = None
        self._leitores: list[threading.Thread] = []
        self._encerrado = threading.Event()

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc else None

    def iniciar(self) -> None:
        env = dict(os.environ)
        env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"})
        env.update(self._env_extra)
        kwargs: dict = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True
        self._proc = subprocess.Popen(self.executavel, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, env=env, **kwargs)
        if sys.platform == "win32":
            try:
                self._job = _JobObject()
                self._job.atribuir(self._proc.pid)
            except OSError as e:  # pragma: no cover - depende do sistema
                log.warning("Não foi possível associar o trabalhador a um Job Object: %s", e)
                self._job = None
        self._leitores = [threading.Thread(target=self._ler_eventos, name=f"trabalhador-{self._proc.pid}-saida",
                                           daemon=True),
                          threading.Thread(target=self._ler_erros, name=f"trabalhador-{self._proc.pid}-erros",
                                           daemon=True)]
        for t in self._leitores:
            t.start()
        assert self._proc.stdin is not None
        try:
            self._proc.stdin.write((json.dumps(self.comando, ensure_ascii=False) + "\n").encode("utf-8"))
            self._proc.stdin.flush()
            # Fechada logo em seguida: uma leitura pendente num pipe bloqueia, no Windows, a carga de
            # bibliotecas que consultam a entrada padrão. O trabalhador vigia o servidor pelo PID.
            self._proc.stdin.close()
        except OSError:
            pass  # o processo já terminou; o código de saída dirá o motivo

    def _ler_eventos(self) -> None:
        assert self._proc and self._proc.stdout
        for bruto in self._proc.stdout:
            linha = bruto.decode("utf-8", errors="replace").rstrip("\r\n")
            if not linha:
                continue
            try:
                evento = json.loads(linha)
            except json.JSONDecodeError:
                self.ao_texto(linha)
                continue
            if isinstance(evento, dict) and "evento" in evento:
                try:
                    self.ao_evento(evento)
                except Exception:
                    log.exception("Falha ao tratar evento do trabalhador")
            else:
                self.ao_texto(linha)

    def _ler_erros(self) -> None:
        assert self._proc and self._proc.stderr
        for bruto in self._proc.stderr:
            linha = bruto.decode("utf-8", errors="replace").rstrip("\r\n")
            if linha.strip():
                self.ao_texto(linha)

    def aguardar(self) -> int:
        assert self._proc is not None
        codigo = self._proc.wait()
        for t in self._leitores:
            t.join(timeout=10)
        self._liberar()
        return codigo

    def encerrar(self) -> None:
        """Encerra o trabalhador e seus processos filhos imediatamente."""
        if self._proc is None or self._proc.poll() is not None:
            return
        self._encerrado.set()
        if self._job is not None:
            self._job.terminar(1)
        elif sys.platform == "win32":
            self._proc.kill()
        else:
            try:
                os.killpg(self._proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    @property
    def encerrado_pelo_servidor(self) -> bool:
        return self._encerrado.is_set()

    def _liberar(self) -> None:
        if self._proc and self._proc.stdin:
            try:
                self._proc.stdin.close()
            except OSError:
                pass
        if self._job is not None:
            self._job.fechar()
            self._job = None
