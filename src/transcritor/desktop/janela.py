"""A janela do aplicativo (pywebview com o WebView2 do Windows) e o ciclo de vida do serviço local.

Sequência:
  1. a janela abre na hora com a página de abertura;
  2. o serviço (API + interface) sobe numa thread, numa porta livre de 127.0.0.1;
  3. quando a API responde, a janela carrega a interface (ou mostra o erro, com "Tentar de novo");
  4. ao fechar, se houver transcrição em andamento, a pessoa confirma; o serviço então encerra as
     tarefas (que ficam "interrompidas", para retomar depois), fecha as conexões e libera a porta.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import traceback
import urllib.parse
import webbrowser

from ..api.servidor import ServidorLocal
from ..config import NOME_APLICATIVO, Configuracoes, pasta_web
from . import paginas
from .instancia import Instancia

log = logging.getLogger("transcritor.desktop")

TIPOS_MIDIA = ("Vídeos e áudios (*.mp4;*.mkv;*.mov;*.avi;*.wmv;*.webm;*.m4v;*.mpg;*.mpeg;*.ts;*.mts;*.flv;*.3gp;"
               "*.mp3;*.wav;*.m4a;*.aac;*.ogg;*.oga;*.opus;*.flac;*.wma;*.amr;*.aif;*.aiff)", "Todos os arquivos (*.*)")
TIPOS_ARQUIVO = {"json": ("Transcrições do Transcritor (*.json)", "Todos os arquivos (*.*)"),
                 "txt": ("Textos (*.txt)", "Todos os arquivos (*.*)")}


class Ponte:
    """Funções da janela disponíveis para a interface (window.pywebview.api).

    Só recursos da área de trabalho (seletores de arquivo, abrir o navegador): toda regra de
    negócio passa pela API REST.
    """

    def __init__(self, app: "Aplicativo") -> None:
        self._app = app

    def _dialogo(self, tipo, **kw):
        janela = self._app.janela
        return janela.create_file_dialog(tipo, **kw) if janela else None

    def escolher_midias(self) -> list[str]:
        import webview

        return list(self._dialogo(webview.FileDialog.OPEN, allow_multiple=True, file_types=TIPOS_MIDIA) or [])

    def escolher_pasta(self) -> str | None:
        import webview

        r = self._dialogo(webview.FileDialog.FOLDER)
        return r[0] if r else None

    def escolher_arquivo(self, tipo: str = "json") -> str | None:
        import webview

        r = self._dialogo(webview.FileDialog.OPEN, file_types=TIPOS_ARQUIVO.get(tipo, ("Todos os arquivos (*.*)",)))
        return r[0] if r else None

    def abrir_no_navegador(self, url: str) -> bool:
        if not str(url).startswith(("http://", "https://")):
            return False
        return webbrowser.open(url)

    def tentar_novamente(self) -> None:
        threading.Thread(target=self._app.reiniciar, name="reiniciar", daemon=True).start()

    def abrir_registros(self) -> None:
        pasta = self._app.config.pasta_logs
        pasta.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(pasta))  # type: ignore[attr-defined]

    def fechar(self) -> None:
        self._app.fechar()


def _perguntar_sim_nao(janela, titulo: str, mensagem: str) -> bool:
    """Confirmação nativa com "Sim" e "Não" (o "Não" é o botão padrão)."""
    if sys.platform == "win32":
        import ctypes

        try:
            hwnd = int(janela.native.Handle.ToInt64())
        except Exception:
            hwnd = 0
        MB_YESNO, MB_ICONWARNING, MB_DEFBUTTON2, IDYES = 0x4, 0x30, 0x100, 6
        return ctypes.windll.user32.MessageBoxW(hwnd, mensagem, titulo, MB_YESNO | MB_ICONWARNING | MB_DEFBUTTON2) == IDYES
    return janela.create_confirmation_dialog(titulo, mensagem)


class Aplicativo:
    def __init__(self, config: Configuracoes, instancia: Instancia, arquivos: list[str], preparar: bool = False):
        self.config = config
        self.instancia = instancia
        self.arquivos = arquivos
        self.preparar = preparar
        self.servidor: ServidorLocal | None = None
        self.janela = None
        self._encerrando = False
        self._lock = threading.Lock()
        self._soltar_registrado = False
        self._hwnd_cache: int | None = None

    # -- serviço -----------------------------------------------------------------------------

    def _subir_servico(self) -> None:
        with self._lock:
            try:
                if self.servidor is not None:
                    self.servidor.parar()
                self.servidor = ServidorLocal(self.config, modo="desktop", ao_encerrar_pedido=self.fechar)
                self.servidor.iniciar()
                self.servidor.aguardar_pronto(90)
            except Exception as e:
                log.exception("Falha ao iniciar o serviço")
                detalhe = "".join(traceback.format_exception_only(type(e), e)).strip()
                if self.janela is not None:
                    self.janela.load_html(paginas.erro("Não foi possível iniciar", "O serviço do Transcritor não iniciou.",
                                                       detalhe, str(self.config.pasta_logs)))
                return
        servicos = self.servidor.servicos
        assert servicos is not None
        self.instancia.registrar(self.servidor.url)
        servicos.barramento.ouvir(self._ao_evento)
        destino = "/"
        if self.preparar:
            self.preparar = False
            try:
                tarefa, _ = servicos.diagnostico.baixar_modelos()
                destino = f"/#/atividades/{tarefa.id}"
            except Exception:
                log.exception("Não foi possível iniciar o download dos modelos")
        if self.arquivos:
            destino = "/#/nova?arquivos=" + urllib.parse.quote(json.dumps(self.arquivos))
            self.arquivos = []
        log.info("Interface pronta em %s", self.servidor.url)
        self._soltar_registrado = False
        if self.janela is not None:
            self.janela.load_url(self.servidor.url + destino)

    def reiniciar(self) -> None:
        if self.janela is not None:
            self.janela.load_html(paginas.abertura("Iniciando o Transcritor de novo..."))
        self._subir_servico()

    def _ao_evento(self, evento: dict) -> None:
        # Ouvintes rodam na thread de quem publica (uma requisição da API): nada aqui pode esperar a janela.
        if evento.get("tipo") == "ativacao":
            threading.Thread(target=self._trazer_para_frente, name="trazer-para-frente", daemon=True).start()

    def _hwnd(self) -> int | None:
        """Identificador da janela principal deste processo (Windows)."""
        if self._hwnd_cache or sys.platform != "win32":
            return self._hwnd_cache
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        pid = os.getpid()
        achadas: list[int] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def ver(hwnd, _):
            dono = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(dono))
            if dono.value == pid and user32.IsWindowVisible(hwnd):
                buf = ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(hwnd, buf, 256)
                if buf.value.startswith(NOME_APLICATIVO):
                    achadas.append(hwnd)
            return True

        user32.EnumWindows(ver, 0)
        self._hwnd_cache = achadas[0] if achadas else None
        return self._hwnd_cache

    def _trazer_para_frente(self) -> None:
        """Restaura e ativa a janela. No Windows, só com chamadas Win32 (ctypes libera o GIL):
        alterar propriedades do formulário (TopMost) fora da thread da interface trava o pythonnet."""
        if sys.platform == "win32":
            import ctypes

            hwnd = self._hwnd()
            if not hwnd:
                return
            user32 = ctypes.windll.user32
            if user32.IsIconic(hwnd):
                user32.ShowWindowAsync(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
            return
        try:
            if self.janela is not None:
                self.janela.restore()
        except Exception:
            log.debug("Não foi possível trazer a janela para a frente", exc_info=True)

    # -- janela ------------------------------------------------------------------------------

    def _ao_carregar(self) -> None:
        """Na interface (não nas páginas de abertura e erro), recebe os arquivos soltos na janela."""
        if self._soltar_registrado or self.servidor is None or self.janela is None:
            return
        url = self.janela.get_current_url() or ""
        if not url.startswith(self.servidor.url):
            return
        from webview.dom import DOMEventHandler

        def soltar(evento: dict) -> None:
            arquivos = [f.get("pywebviewFullPath") for f in (evento.get("dataTransfer") or {}).get("files", [])]
            arquivos = [a for a in arquivos if a]
            if arquivos and self.servidor and self.servidor.servicos:
                self.servidor.servicos.barramento.publicar("ativacao", {"arquivos": arquivos, "origem": "soltar"})

        try:
            self.janela.dom.document.events.drop += DOMEventHandler(soltar, prevent_default=True)
            self._soltar_registrado = True
        except Exception:
            log.warning("Arrastar e soltar indisponível nesta janela", exc_info=True)

    def _ao_fechar(self) -> bool:
        if self._encerrando:
            return True
        servicos = self.servidor.servicos if self.servidor else None
        ativas = servicos.tarefas.ativas("transcricao") if servicos else []
        if ativas:
            em_andamento = [t for t in ativas if t.estado == "em_andamento"]
            nomes = ", ".join(t.titulo for t in ativas[:3]) + ("..." if len(ativas) > 3 else "")
            mensagem = (f"{'Há uma transcrição' if len(ativas) == 1 else f'Há {len(ativas)} transcrições'} "
                        f"{'em andamento' if em_andamento else 'na fila'} ({nomes}).\n\n"
                        "Se fechar agora, o processamento é interrompido. As etapas já concluídas ficam guardadas e, "
                        "ao abrir o Transcritor de novo, você pode retomar de onde parou.\n\nFechar o Transcritor mesmo assim?")
            if not _perguntar_sim_nao(self.janela, f"Fechar o {NOME_APLICATIVO}?", mensagem):
                return False
        self._encerrando = True
        return True

    def fechar(self) -> None:
        """Fecha a janela por pedido da interface ou da API (POST /sistema/encerrar)."""
        self._encerrando = True
        if self.janela is not None:
            threading.Thread(target=self.janela.destroy, name="fechar-janela", daemon=True).start()

    def executar(self) -> None:
        import webview

        icone = pasta_web() / "icone.ico"
        fundo = "#111315" if _tema_escuro() else "#F5F5F1"
        self.janela = webview.create_window(
            NOME_APLICATIVO, html=paginas.abertura(), js_api=Ponte(self), width=1220, height=820, min_size=(720, 560),
            background_color=fundo, text_select=True)
        self.janela.events.closing += self._ao_fechar
        self.janela.events.loaded += self._ao_carregar
        self.config.pasta_webview.mkdir(parents=True, exist_ok=True)
        webview.start(self._subir_servico, gui="edgechromium", private_mode=False, storage_path=str(self.config.pasta_webview),
                      icon=str(icone) if icone.is_file() else None, debug=bool(os.environ.get("TRANSCRITOR_DEPURAR")))

    def encerrar(self) -> None:
        if self.servidor is not None:
            self.servidor.parar()
            self.servidor = None


def _tema_escuro() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as chave:
            return winreg.QueryValueEx(chave, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def modo_navegador(config: Configuracoes, instancia: Instancia, arquivos: list[str]) -> None:
    """Alternativa quando a janela (WebView2) não está disponível: a interface abre no navegador padrão
    e uma janela pequena controla o serviço."""
    encerrar = threading.Event()
    servidor = ServidorLocal(config, modo="desktop", ao_encerrar_pedido=encerrar.set)
    servidor.iniciar()
    servidor.aguardar_pronto(90)
    instancia.registrar(servidor.url)
    destino = servidor.url + ("/#/nova?arquivos=" + urllib.parse.quote(json.dumps(arquivos)) if arquivos else "/")
    webbrowser.open(destino)
    try:
        import tkinter as tk

        raiz = tk.Tk()
        raiz.title(NOME_APLICATIVO)
        raiz.geometry("420x170")
        tk.Label(raiz, text="O Transcritor está aberto no navegador.", font=("Segoe UI", 12, "bold")).pack(pady=(22, 6))
        tk.Label(raiz, text="Mantenha esta janela aberta enquanto usar o programa.", font=("Segoe UI", 10)).pack()
        botoes = tk.Frame(raiz)
        botoes.pack(pady=18)
        tk.Button(botoes, text="Abrir de novo", command=lambda: webbrowser.open(servidor.url), width=14).pack(side="left", padx=6)
        tk.Button(botoes, text="Encerrar", command=raiz.destroy, width=14).pack(side="left", padx=6)

        def vigiar() -> None:
            if encerrar.is_set():
                raiz.destroy()
            else:
                raiz.after(500, vigiar)

        raiz.after(500, vigiar)
        raiz.mainloop()
    except Exception:
        log.warning("Janela de controle indisponível; o serviço segue até ser encerrado pela API", exc_info=True)
        encerrar.wait()
    finally:
        servidor.parar()

