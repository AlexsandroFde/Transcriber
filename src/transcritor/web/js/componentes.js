// Componentes de interface reutilizáveis, com acessibilidade (rótulos, foco, regiões vivas).
import { html, useEffect, useRef, useState } from "./biblioteca.js";
import { Icone } from "./icones.js";

let sequencia = 0;
export const novoId = (prefixo = "c") => `${prefixo}-${++sequencia}`;

export function Botao({ variante = "", tamanho = "", icone, carregando = false, children, classe = "", rotulo, ...resto }) {
  const so = !children && icone;
  const cls = ["botao", variante, tamanho, so ? "icone-so" : "", classe].filter(Boolean).join(" ");
  return html`<button type="button" ...${resto} class=${cls} disabled=${resto.disabled || carregando}
    aria-busy=${carregando ? "true" : undefined} aria-label=${rotulo} title=${so ? rotulo : resto.title}>
    ${carregando ? html`<span class="giro" aria-hidden="true"></span>` : icone ? html`<${Icone} nome=${icone} />` : null}
    ${children}
  </button>`;
}

export function Campo({ rotulo, ajuda, erro, opcional, id, children, classe = "" }) {
  return html`<div class=${"campo " + classe}>
    ${rotulo && html`<label for=${id}>${rotulo}${opcional ? html` <span class="opcional">(opcional)</span>` : null}</label>`}
    ${children}
    ${erro ? html`<p class="erro-campo" id=${id + "-erro"} role="alert"><${Icone} nome="alerta" />${erro}</p>`
      : ajuda ? html`<p class="ajuda" id=${id + "-ajuda"}>${ajuda}</p>` : null}
  </div>`;
}

export const descritoPor = (id, erro, ajuda) => (erro ? id + "-erro" : ajuda ? id + "-ajuda" : undefined);

export function Interruptor({ marcado, aoMudar, titulo, descricao, desabilitado, classe = "", dica }) {
  const [id] = useState(() => novoId("int"));
  return html`<label class=${["interruptor", classe].filter(Boolean).join(" ")} for=${id} title=${dica}>
    <span class="corpo"><span class="titulo">${titulo}</span>${descricao && html`<span class="descricao">${descricao}</span>`}</span>
    <input id=${id} type="checkbox" role="switch" checked=${marcado} disabled=${desabilitado}
      onChange=${(e) => aoMudar(e.currentTarget.checked)} />
  </label>`;
}

export function Selecao({ id, valor, aoMudar, opcoes, desabilitado, descrita }) {
  return html`<select id=${id} class="selecao" value=${valor} disabled=${desabilitado} aria-describedby=${descrita}
    onChange=${(e) => aoMudar(e.currentTarget.value)}>
    ${opcoes.map((o) => html`<option value=${o.valor} selected=${o.valor === valor}>${o.rotulo}</option>`)}
  </select>`;
}

const ICONE_AVISO = { info: "info", atencao: "alerta", erro: "erro", sucesso: "sucesso" };

export function Aviso({ tipo = "info", titulo, children, acoes, papel }) {
  return html`<div class=${"aviso " + tipo} role=${papel || (tipo === "erro" ? "alert" : "status")}>
    <${Icone} nome=${ICONE_AVISO[tipo]} />
    <div class="corpo">
      ${titulo && html`<strong>${titulo}</strong>`}
      ${children}
      ${acoes && html`<div class="acoes">${acoes}</div>`}
    </div>
  </div>`;
}

// Mostra um erro da API (ErroApi) com a explicação e a dica de solução.
export function PainelErro({ erro, titulo, acoes }) {
  if (!erro) return null;
  return html`<${Aviso} tipo="erro" titulo=${titulo || erro.mensagem} acoes=${acoes}>
    ${titulo && html`<p>${erro.mensagem}</p>`}
    ${erro.dica && html`<p class="dica"><b>Como resolver:</b> ${erro.dica}</p>`}
  </${Aviso}>`;
}

export function Etiqueta({ tipo = "", icone, children, titulo }) {
  return html`<span class=${"etiqueta " + tipo} title=${titulo}>${icone && html`<${Icone} nome=${icone} />`}${children}</span>`;
}

export function Barra({ valor, indeterminada, estado = "", rotulo = "Progresso", grossa }) {
  const pct = Math.max(0, Math.min(100, valor || 0));
  return html`<div class=${["barra", indeterminada ? "indeterminada" : "", estado, grossa ? "grossa" : ""].join(" ")}
    role="progressbar" aria-label=${rotulo} aria-valuemin="0" aria-valuemax="100"
    aria-valuenow=${indeterminada ? undefined : Math.round(pct)}><span style=${`width:${pct}%`}></span></div>`;
}

export function Vazio({ icone = "info", titulo, children, acoes }) {
  return html`<div class="vazio">
    <span class="circulo"><${Icone} nome=${icone} /></span>
    <strong>${titulo}</strong>
    ${children && html`<p>${children}</p>`}
    ${acoes && html`<div class="acoes">${acoes}</div>`}
  </div>`;
}

export function Esqueleto({ linhas = 3 }) {
  return html`<div class="cartao" aria-busy="true" aria-label="Carregando">
    ${Array.from({ length: linhas }, (_, i) => html`<div class="item-lista" key=${i}>
      <div class="corpo"><div class="esqueleto" style="width:45%"></div><div class="esqueleto" style="width:70%;height:11px"></div></div>
    </div>`)}
  </div>`;
}

export function Carregando({ texto = "Carregando..." }) {
  return html`<div class="carregando-tela" role="status"><span class="giro" aria-hidden="true"></span>${texto}</div>`;
}

export function CorFalante({ indice }) {
  return html`<span class="cor-falante" style=${`--cor: var(--p${(indice % 8) + 1})`} aria-hidden="true"></span>`;
}

// -- diálogo modal (elemento <dialog> nativo: foco preso e Esc fecham corretamente) -------------

export function Dialogo({ aberto, titulo, aoFechar, children, acoes, rotuloId }) {
  const ref = useRef(null);
  const [id] = useState(() => rotuloId || novoId("dlg"));
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (aberto && !d.open) d.showModal();
    if (!aberto && d.open) d.close();
  }, [aberto]);
  return html`<dialog class="dialogo" ref=${ref} aria-labelledby=${id}
      onClose=${() => aberto && aoFechar && aoFechar()} onCancel=${(e) => { e.preventDefault(); aoFechar && aoFechar(); }}>
    <div class="dialogo-corpo"><h2 id=${id}>${titulo}</h2>${children}</div>
    ${acoes && html`<div class="dialogo-acoes">${acoes}</div>`}
  </dialog>`;
}

// -- confirmação e pedido de texto, acionáveis de qualquer tela --------------------------------

let pedido = null;
const ouvintesPedido = new Set();
const avisarPedido = () => ouvintesPedido.forEach((f) => f());

export function confirmar({ titulo, mensagem, confirmar: rotuloOk = "Confirmar", cancelar = "Cancelar", perigo = false }) {
  return new Promise((resolver) => {
    pedido = { tipo: "confirmar", titulo, mensagem, rotuloOk, cancelar, perigo, resolver };
    avisarPedido();
  });
}

export function pedirCaminho({ titulo, rotulo, exemplo }) {
  return new Promise((resolver) => {
    pedido = { tipo: "texto", titulo, rotulo, exemplo, resolver };
    avisarPedido();
  });
}

export function HospedeDialogos() {
  const [, forcar] = useState(0);
  const [texto, setTexto] = useState("");
  useEffect(() => {
    const f = () => { setTexto(""); forcar((x) => x + 1); };
    ouvintesPedido.add(f);
    return () => ouvintesPedido.delete(f);
  }, []);
  const atual = pedido;
  const responder = (valor) => {
    if (!pedido) return;
    const r = pedido.resolver;
    pedido = null;
    forcar((x) => x + 1);
    r(valor);
  };
  if (!atual) return html`<${Dialogo} aberto=${false} titulo="" />`;
  if (atual.tipo === "confirmar") {
    return html`<${Dialogo} aberto=${true} titulo=${atual.titulo} aoFechar=${() => responder(false)}
      acoes=${html`<${Botao} onClick=${() => responder(false)}>${atual.cancelar}</${Botao}>
        <${Botao} variante=${atual.perigo ? "perigo" : "primario"} onClick=${() => responder(true)} autofocus>${atual.rotuloOk}</${Botao}>`}>
      ${atual.mensagem && html`<p>${atual.mensagem}</p>`}
    </${Dialogo}>`;
  }
  const id = "dlg-caminho";
  return html`<${Dialogo} aberto=${true} titulo=${atual.titulo} aoFechar=${() => responder(null)}
    acoes=${html`<${Botao} onClick=${() => responder(null)}>Cancelar</${Botao}>
      <${Botao} variante="primario" disabled=${!texto.trim()} onClick=${() => responder(texto.trim().replace(/^"|"$/g, ""))}>Usar este caminho</${Botao}>`}>
    <${Campo} id=${id} rotulo=${atual.rotulo} ajuda=${`Exemplo: ${atual.exemplo}`}>
      <input id=${id} class="entrada" value=${texto} onInput=${(e) => setTexto(e.currentTarget.value)} autofocus
        aria-describedby=${id + "-ajuda"} onKeyDown=${(e) => e.key === "Enter" && texto.trim() && responder(texto.trim())} />
    </${Campo}>
  </${Dialogo}>`;
}

// -- notificações ---------------------------------------------------------------------------

let notificacoes = [];
const ouvintesNotificacao = new Set();
const avisarNotificacoes = () => ouvintesNotificacao.forEach((f) => f());

export function notificar({ tipo = "sucesso", titulo, mensagem, acao, duracao = 6000 }) {
  const id = ++sequencia;
  notificacoes = [...notificacoes.slice(-3), { id, tipo, titulo, mensagem, acao }];
  avisarNotificacoes();
  if (duracao) setTimeout(() => fecharNotificacao(id), duracao);
  return id;
}

export function fecharNotificacao(id) {
  notificacoes = notificacoes.filter((n) => n.id !== id);
  avisarNotificacoes();
}

export function AreaNotificacoes() {
  const [, forcar] = useState(0);
  useEffect(() => {
    const f = () => forcar((x) => x + 1);
    ouvintesNotificacao.add(f);
    return () => ouvintesNotificacao.delete(f);
  }, []);
  return html`<div class="notificacoes" role="region" aria-live="polite" aria-label="Notificações">
    ${notificacoes.map((n) => html`<div class=${"notificacao " + n.tipo} key=${n.id}>
      <${Icone} nome=${ICONE_AVISO[n.tipo] || "info"} />
      <div class="corpo">
        <strong>${n.titulo}</strong>
        ${n.mensagem && html`<p>${n.mensagem}</p>`}
        ${n.acao && html`<div class="acoes"><${Botao} tamanho="pequeno" onClick=${() => { fecharNotificacao(n.id); n.acao.executar(); }}>${n.acao.rotulo}</${Botao}></div>`}
      </div>
      <${Botao} variante="fantasma" tamanho="pequeno" icone="fechar" rotulo="Fechar notificação" onClick=${() => fecharNotificacao(n.id)} />
    </div>`)}
  </div>`;
}

// Mostra o erro de uma ação numa notificação (para ações rápidas sem formulário).
export function notificarErro(erro, titulo) {
  notificar({ tipo: "erro", titulo: titulo || erro.mensagem || "Não foi possível concluir a ação.",
    mensagem: titulo ? erro.mensagem : erro.dica, duracao: 9000 });
}

// Executa uma ação da API mostrando erro, se houver. Devolve o resultado ou undefined.
export async function executar(acao, tituloErro) {
  try {
    return await acao();
  } catch (e) {
    notificarErro(e, tituloErro);
    return undefined;
  }
}

export function useAtraso(valor, ms = 250) {
  const [atrasado, setAtrasado] = useState(valor);
  useEffect(() => {
    const t = setTimeout(() => setAtrasado(valor), ms);
    return () => clearTimeout(t);
  }, [valor, ms]);
  return atrasado;
}

export function useTitulo(titulo) {
  useEffect(() => {
    document.title = titulo ? `${titulo} · Transcritor` : "Transcritor";
  }, [titulo]);
}
