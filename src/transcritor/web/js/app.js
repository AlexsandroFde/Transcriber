// Casca do aplicativo: navegação, rotas, eventos em tempo real e arrastar e soltar.
import { api, conectarEventos } from "./api.js";
import { html, render, useEffect, useRef, useState } from "./biblioteca.js";
import { AreaNotificacoes, HospedeDialogos, Vazio, executar, fecharNotificacao, notificar, notificarErro } from "./componentes.js";
import { aguardarDesktop, ehDesktop, enviarArquivos } from "./desktop.js";
import { Icone } from "./icones.js";
import { adicionarSelecao, ativa, atualizar, esquecerTarefa, guardarTarefa, guardarTarefas, ir, obter, preferencia,
  publicarLog, useLoja, useRota } from "./loja.js";
import { TelaAtividades, TelaTarefa } from "./telas/atividades.js";
import { TelaConfiguracoes, aplicarTema } from "./telas/configuracoes.js";
import { TelaInicio } from "./telas/inicio.js";
import { TelaNova } from "./telas/nova.js";
import { TelaTranscricao } from "./telas/transcricao.js";
import { TelaTranscricoes, recarregarTranscricoes } from "./telas/transcricoes.js";

// -- dados iniciais e eventos ---------------------------------------------------------------------

function carregarTudo() {
  // Cada parte aparece assim que chega (a tela não espera a consulta mais lenta).
  const ignorar = () => {};
  api.opcoes().then((opcoes) => atualizar({ opcoes })).catch(ignorar);
  api.sistema().then((sistema) => atualizar({ sistema })).catch(ignorar);
  api.ambiente().then((ambiente) => atualizar({ ambiente })).catch(ignorar);
  api.tarefas({ limite: 300 }).then((r) => guardarTarefas(r.itens)).catch(ignorar);
  api.transcricoes().then((r) => atualizar({ transcricoes: r.itens })).catch(ignorar);
}

function lerArquivosDaRota(rota) {
  // O inicializador abre a janela com os arquivos recebidos (vídeo arrastado sobre o atalho): #/nova?arquivos=[...]
  const bruto = rota.params.get("arquivos");
  if (rota.partes[0] !== "nova" || !bruto) return;
  try {
    const arquivos = JSON.parse(bruto);
    if (Array.isArray(arquivos)) adicionarSelecao(arquivos.filter((a) => typeof a === "string"));
  } catch (e) { /* parâmetro inválido: ignorado */ }
  history.replaceState(null, "", "#/nova");
}

function aoMudarTarefa(t) {
  const antes = obter().tarefas.get(t.id);
  guardarTarefa(t);
  if (!antes || !ativa(antes) || ativa(t)) return;
  if (t.tipo === "transcricao" && t.estado === "concluida" && t.resultado) {
    notificar({ titulo: "Transcrição concluída", mensagem: t.titulo, duracao: 10000,
      acao: t.resultado.transcricao_id ? { rotulo: "Abrir", executar: () => ir(`/transcricoes/${t.resultado.transcricao_id}`) } : null });
    if (preferencia("abrirPasta", false)) executar(() => api.abrir(t.resultado.pasta));
  } else if (t.estado === "falhou") {
    notificar({ tipo: "erro", titulo: `Não foi possível concluir: ${t.titulo}`, mensagem: t.erro ? t.erro.mensagem : undefined,
      duracao: 12000, acao: { rotulo: "Ver detalhes", executar: () => ir(`/atividades/${t.id}`) } });
  } else if (t.tipo === "download_modelos" && t.estado === "concluida") {
    notificar({ titulo: "Modelos prontos", mensagem: "A próxima transcrição não precisa esperar o download." });
  }
}

let recarregarLista = null;
function iniciarEventos() {
  let aviso = null;
  conectarEventos({
    conectado: () => {
      clearTimeout(aviso);
      atualizar({ conexao: "ok" });
      carregarTudo();
    },
    erro: () => {
      clearTimeout(aviso);
      aviso = setTimeout(() => atualizar({ conexao: "perdida" }), 2000);
    },
    tarefa: (ev) => aoMudarTarefa(ev.dados),
    tarefa_removida: (ev) => esquecerTarefa(ev.dados.id),
    log: (ev) => publicarLog(ev.dados),
    transcricao: (ev) => {
      const versoes = { ...(obter().versoes || {}) };
      versoes[ev.dados.id] = (versoes[ev.dados.id] || 0) + 1;
      atualizar({ versoes });
      clearTimeout(recarregarLista);
      recarregarLista = setTimeout(recarregarTranscricoes, 300);
    },
    ambiente: () => api.ambiente().then((a) => atualizar({ ambiente: a })).catch(() => {}),
    ativacao: (ev) => {
      const arquivos = (ev.dados && ev.dados.arquivos) || [];
      if (arquivos.length) {
        adicionarSelecao(arquivos);
        ir("/nova");
      }
    },
  });
}

// -- partes da casca ----------------------------------------------------------------------------

function SituacaoAmbiente() {
  const ambiente = useLoja((e) => e.ambiente);
  const rel = ambiente && ambiente.relatorio;
  const verificando = !ambiente || ambiente.situacao === "verificando" || ambiente.situacao === "nao_verificado";
  let ponto = "";
  let titulo = "Verificando o ambiente";
  let texto = "placa de vídeo, modelos e ffmpeg";
  if (rel) {
    if (!rel.pronto) [ponto, titulo, texto] = ["erro", "Ambiente com problema", "veja os detalhes"];
    else if (rel.gpu.disponivel) [ponto, titulo, texto] = ["ok", "Pronto para transcrever", rel.gpu.descricao.replace(/^NVIDIA (GeForce )?/, "")];
    else [ponto, titulo, texto] = ["aviso", "Pronto, sem placa de vídeo", "a transcrição será mais lenta"];
  }
  return html`<a class="situacao" href="#/configuracoes/ambiente" title=${`${titulo}: ${texto}`}>
    <span class=${`ponto ${ponto} ${verificando ? "pulsando" : ""}`} aria-hidden="true"></span>
    <span class="texto"><strong>${titulo}</strong>${texto}</span>
    <span class="visualmente-oculto">${titulo}: ${texto}</span>
  </a>`;
}

function Lateral({ secao }) {
  const tarefas = useLoja((e) => e.tarefas);
  const ativas = [...tarefas.values()].filter((t) => t.tipo === "transcricao" && ativa(t)).length;
  const itens = [
    ["inicio", "#/", "enviar", "Transcrever"],
    ["transcricoes", "#/transcricoes", "texto", "Transcrições"],
    ["atividades", "#/atividades", "atividade", "Atividades"],
    ["configuracoes", "#/configuracoes", "ajustes", "Configurações"],
  ];
  const atual = !secao || secao === "nova" ? "inicio" : secao;
  return html`<aside class="lateral">
    <a class="marca" href="#/" aria-label="Transcritor: início"><span class="marca-icone"><${Icone} nome="marca" /></span><span>Transcritor</span></a>
    <nav class="nav" aria-label="Navegação principal">
      ${itens.map(([id, href, icone, rotulo]) => html`<a href=${href} aria-current=${atual === id ? "page" : undefined} title=${rotulo}>
        <${Icone} nome=${icone} /><span class="rotulo">${rotulo}</span>
        ${id === "atividades" && ativas > 0 && html`<span class="contador" aria-label=${`${ativas} em andamento`}>${ativas}</span>`}
      </a>`)}
    </nav>
    <div class="lateral-rodape"><${SituacaoAmbiente} /></div>
  </aside>`;
}

function FaixaConexao() {
  const conexao = useLoja((e) => e.conexao);
  const [demorando, setDemorando] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setDemorando(true), 4000);
    return () => clearTimeout(t);
  }, []);
  if (conexao === "ok" || (conexao === "conectando" && !demorando)) return null;
  return html`<div class="faixa-conexao" role="status"><span class="giro" aria-hidden="true"></span>
    ${conexao === "perdida" ? "Reconectando ao serviço do Transcritor..." : "Conectando ao serviço do Transcritor..."}</div>`;
}

function useArrastar() {
  const [arrastando, setArrastando] = useState(false);
  useEffect(() => {
    let contador = 0;
    const temArquivos = (e) => Array.from((e.dataTransfer && e.dataTransfer.types) || []).includes("Files");
    const entrar = (e) => { if (!temArquivos(e)) return; e.preventDefault(); contador += 1; setArrastando(true); };
    const sobre = (e) => { if (!temArquivos(e)) return; e.preventDefault(); e.dataTransfer.dropEffect = "copy"; };
    const sair = (e) => { if (!temArquivos(e)) return; contador = Math.max(0, contador - 1); if (!contador) setArrastando(false); };
    const soltar = async (e) => {
      if (!temArquivos(e)) return;
      e.preventDefault();
      contador = 0;
      setArrastando(false);
      // Na janela do aplicativo, os caminhos completos chegam pelo evento "ativacao" (sem copiar o arquivo).
      if (ehDesktop()) return;
      const arquivos = Array.from(e.dataTransfer.files || []);
      if (!arquivos.length) return;
      const id = notificar({ tipo: "info", titulo: `Enviando ${arquivos.length > 1 ? `${arquivos.length} arquivos` : arquivos[0].name}...`, duracao: 0 });
      try {
        adicionarSelecao(await enviarArquivos(arquivos));
        ir("/nova");
      } catch (erro) {
        notificarErro(erro, "Não foi possível enviar o arquivo");
      } finally {
        fecharNotificacao(id);
      }
    };
    window.addEventListener("dragenter", entrar);
    window.addEventListener("dragover", sobre);
    window.addEventListener("dragleave", sair);
    window.addEventListener("drop", soltar);
    return () => {
      window.removeEventListener("dragenter", entrar);
      window.removeEventListener("dragover", sobre);
      window.removeEventListener("dragleave", sair);
      window.removeEventListener("drop", soltar);
    };
  }, []);
  return arrastando;
}

function Conteudo({ rota }) {
  const [p0, p1, p2] = rota.partes;
  switch (p0) {
    case undefined:
      return html`<${TelaInicio} />`;
    case "nova":
      return html`<${TelaNova} />`;
    case "atividades":
      return p1 ? html`<${TelaTarefa} key=${p1} id=${p1} />` : html`<${TelaAtividades} />`;
    case "transcricoes":
      return p1 ? html`<${TelaTranscricao} key=${p1} id=${p1} aba=${p2} />` : html`<${TelaTranscricoes} />`;
    case "configuracoes":
      return html`<${TelaConfiguracoes} secao=${p1} />`;
    default:
      return html`<div class="conteudo"><div class="cartao"><${Vazio} icone="busca" titulo="Página não encontrada"
        acoes=${html`<a class="botao primario" href="#/">Ir para o início</a>`} /></div></div>`;
  }
}

function App() {
  const rota = useRota();
  const arrastando = useArrastar();
  const principal = useRef(null);
  const chave = rota.partes.slice(0, 2).join("/");
  const primeira = useRef(true);

  useEffect(() => lerArquivosDaRota(rota), [rota.params.get("arquivos")]);

  useEffect(() => {
    if (primeira.current) { primeira.current = false; return; }
    window.scrollTo(0, 0);
    if (principal.current) principal.current.focus({ preventScroll: true });
  }, [chave]);

  return html`<a class="pular-conteudo" href="#conteudo" onClick=${(e) => { e.preventDefault(); principal.current && principal.current.focus(); }}>Ir para o conteúdo</a>
    <div class="app">
      <${Lateral} secao=${rota.partes[0]} />
      <main class="principal" id="conteudo" tabindex="-1" ref=${principal}><${Conteudo} rota=${rota} /></main>
    </div>
    ${arrastando && html`<div class="sobreposicao-soltar" aria-hidden="true"><div><${Icone} nome="enviar" />Solte para transcrever</div></div>`}
    <${FaixaConexao} />
    <${AreaNotificacoes} />
    <${HospedeDialogos} />`;
}

// -- início ---------------------------------------------------------------------------------------

function iniciar() {
  const tema = preferencia("tema", "sistema");
  aplicarTema(tema);
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (preferencia("tema", "sistema") === "sistema") aplicarTema("sistema");
  });
  aguardarDesktop().then((d) => atualizar({ desktop: d }));
  render(html`<${App} />`, document.getElementById("app"));
  carregarTudo();
  iniciarEventos();
}

iniciar();
