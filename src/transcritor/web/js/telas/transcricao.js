import { api } from "../api.js";
import { html, useEffect, useMemo, useRef, useState } from "../biblioteca.js";
import { Aviso, Botao, Campo, Carregando, CorFalante, Etiqueta, Interruptor, PainelErro, Vazio, confirmar, executar,
  notificar, pedirCaminho, useAtraso, useTitulo } from "../componentes.js";
import { escolherPasta } from "../desktop.js";
import { bytes, duracao, hms, inteiro, plural, quando } from "../formato.js";
import { Icone } from "../icones.js";
import { ir, preferencia, salvarPreferencia, useLoja } from "../loja.js";
import { abrirExistente, recarregarTranscricoes } from "./transcricoes.js";

const ABAS = [
  { id: "texto", rotulo: "Texto", icone: "texto" },
  { id: "participantes", rotulo: "Participantes", icone: "pessoas" },
  { id: "conferencia", rotulo: "Conferência", icone: "conferir" },
  { id: "arquivos", rotulo: "Arquivos", icone: "documento" },
];

// Recarrega quando a transcrição muda (nomes salvos, arquivos gerados de novo, outra janela...).
function useVersao(id) {
  return useLoja((e) => (e.versoes || {})[id] || 0);
}

function useCarregar(funcao, deps) {
  const [estado, setEstado] = useState({ dados: null, erro: null });
  useEffect(() => {
    let vivo = true;
    funcao().then((dados) => vivo && setEstado({ dados, erro: null })).catch((erro) => vivo && setEstado({ dados: null, erro }));
    return () => { vivo = false; };
  }, deps);
  return [estado.dados, estado.erro, (dados) => setEstado({ dados, erro: null })];
}

function BotaoTempo({ inicio, tocar }) {
  return html`<button type="button" class="tempo-botao" onClick=${() => tocar && tocar(inicio)} disabled=${!tocar}
    title=${tocar ? "Ouvir a partir deste ponto" : "A gravação original não está disponível"}
    aria-label=${`${tocar ? "Ouvir a partir de" : "Tempo"} ${hms(inicio)}`}>${hms(inicio)}</button>`;
}

// -- busca sem diferenciar acentos e maiúsculas, mantendo as posições do texto original --------------

function normalizarComPosicoes(texto) {
  let saida = "";
  for (const c of texto) {
    const n = c.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
    saida += n.length === 1 ? n : c.toLowerCase().slice(0, 1) || " ";
  }
  return saida;
}

function realcar(texto, termo, contador, ativo) {
  if (!termo) return texto;
  const base = normalizarComPosicoes(texto);
  const partes = [];
  let i = 0;
  let achou = base.indexOf(termo, i);
  while (achou !== -1) {
    if (achou > i) partes.push(texto.slice(i, achou));
    const n = contador.n++;
    partes.push(html`<mark class=${"achado" + (n === ativo ? " ativo" : "")} data-achado=${n}>${texto.slice(achou, achou + termo.length)}</mark>`);
    i = achou + termo.length;
    achou = base.indexOf(termo, i);
  }
  if (i < texto.length) partes.push(texto.slice(i));
  return partes;
}

// -- rolagem automática ---------------------------------------------------------------------------

// Frações da parte da tela que o player fixo não cobre. A cada troca de fala, a página rola até a fala
// nova ficar na ANCORA. Numa fala longa, que não cabe na tela, ela rola de novo quando o trecho que está
// tocando passa do LIMITE.
const ANCORA = 0.22;
const LIMITE = 0.72;
const TECLAS_ROLAGEM = new Set(["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " "]);

// Bloco que está tocando (o último que já começou) e quanto dele já passou, de 0 a 1.
function posicaoNoTexto(blocos, t) {
  if (t === null || !blocos || !blocos.length) return null;
  let indice = -1;
  for (let i = 0; i < blocos.length; i++) {
    if (blocos[i].inicio_s <= t && (indice < 0 || blocos[i].inicio_s >= blocos[indice].inicio_s)) indice = i;
  }
  if (indice < 0) return { indice: 0, fracao: 0 };
  const b = blocos[indice];
  const total = b.fim_s - b.inicio_s;
  return { indice, fracao: total > 0 ? Math.min(1, Math.max(0, (t - b.inicio_s) / total)) : 0 };
}

// Parte da janela em que o texto aparece: abaixo do player fixo (e da barra de navegação, em telas estreitas).
// Só conta o que fica por cima do texto; o que não é fixo sai da tela junto com a rolagem. O que é fixo
// estará grudado no alto depois de rolar, mesmo que agora ainda esteja no lugar original.
function areaLivre() {
  let topo = 0;
  for (const seletor of [".lateral", ".reprodutor"]) {
    const el = document.querySelector(seletor);
    if (!el || getComputedStyle(el).position !== "sticky") continue;
    const altura = el.getBoundingClientRect().height;
    if (altura < window.innerHeight * 0.6) topo = Math.max(topo, altura);
  }
  topo = Math.min(topo, window.innerHeight * 0.6);
  return { topo, altura: window.innerHeight - topo };
}

// Faz a página acompanhar a gravação. Rolar a página durante a reprodução (roda do mouse, teclado,
// barra de rolagem, toque ou busca) suspende o acompanhamento, que volta pelo botão "Voltar ao trecho
// atual" ou ao clicar num horário do texto. Com a gravação pausada, rolar não suspende nada: ao tocar
// de novo, a página volta para a fala atual.
function useRolagemAutomatica({ ligada, blocos, tempoAtual, tocando, lista }) {
  const [seguindo, setSeguindo] = useState(true);
  const propria = useRef(false); // a rolagem em andamento foi pedida por este código
  const espera = useRef(0);
  const forcar = useRef(false);
  const ultimo = useRef(-1); // índice da última fala acompanhada
  const tocandoAgora = useRef(tocando);
  tocandoAgora.current = tocando;

  // A rolagem suave dispara vários eventos "scroll"; a marca vale até 200 ms depois do último deles.
  const prolongar = () => {
    clearTimeout(espera.current);
    espera.current = setTimeout(() => { propria.current = false; }, 200);
  };

  useEffect(() => {
    if (!ligada) return;
    ultimo.current = -1;
    setSeguindo(true);
  }, [ligada]);

  useEffect(() => {
    if (!ligada) return undefined;
    let ignorarAte = 0;
    // Qualquer ação da pessoa encerra a marca: a rolagem que vier depois é dela.
    const daPessoa = () => { propria.current = false; };
    const tecla = (e) => {
      if (!TECLAS_ROLAGEM.has(e.key) || !(e.target instanceof Element)) return;
      if (e.target.closest("input, textarea, select, video, audio, [contenteditable]")) return;
      if (e.key === " " && e.target.closest("button, a, summary, label")) return;
      daPessoa();
    };
    // Botão do meio (rolagem automática do Windows) ou clique na barra de rolagem da página.
    const botao = (e) => { if (e.button === 1 || e.clientX >= document.documentElement.clientWidth) daPessoa(); };
    // Mudar o tamanho da janela reorganiza o texto e o navegador corrige a rolagem sozinho.
    const redimensionou = () => { ignorarAte = performance.now() + 400; };
    const rolou = () => {
      if (propria.current) { prolongar(); return; }
      if (performance.now() >= ignorarAte && tocandoAgora.current) setSeguindo(false);
    };
    const parou = () => { clearTimeout(espera.current); propria.current = false; };
    const passivo = { passive: true };
    const ouvintes = [["wheel", daPessoa, passivo], ["touchstart", daPessoa, passivo], ["keydown", tecla],
      ["mousedown", botao], ["resize", redimensionou], ["scroll", rolou, passivo], ["scrollend", parou]];
    for (const [nome, f, opcoes] of ouvintes) window.addEventListener(nome, f, opcoes);
    return () => {
      for (const [nome, f, opcoes] of ouvintes) window.removeEventListener(nome, f, opcoes);
      clearTimeout(espera.current);
      propria.current = false;
    };
  }, [ligada]);

  useEffect(() => {
    const forcado = forcar.current;
    forcar.current = false;
    if (!ligada || !seguindo || !lista.current || (propria.current && !forcado)) return;
    const pos = posicaoNoTexto(blocos, tempoAtual);
    const el = pos && lista.current.children[pos.indice];
    if (!el) return;
    const trocou = pos.indice !== ultimo.current;
    ultimo.current = pos.indice;
    // Sem o horário de cada frase, a posição da fala dentro de um bloco longo é estimada pelo tempo.
    const r = el.getBoundingClientRect();
    const linha = r.top + pos.fracao * r.height;
    const { topo, altura } = areaLivre();
    if (!forcado && !trocou && linha >= topo + 8 && linha <= topo + altura * LIMITE) return;
    const maximo = document.documentElement.scrollHeight - window.innerHeight;
    const destino = Math.max(0, Math.min(maximo, window.scrollY + linha - (topo + altura * ANCORA)));
    if (Math.abs(destino - window.scrollY) < 2) return;
    propria.current = true;
    prolongar();
    const suave = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    window.scrollTo({ top: destino, behavior: suave ? "smooth" : "auto" });
  }, [ligada, seguindo, tempoAtual, blocos]);

  return {
    seguindo,
    seguir: () => setSeguindo(true),
    retomar: () => { forcar.current = true; setSeguindo(true); },
  };
}

// -- aba Texto ------------------------------------------------------------------------------------

function AbaTexto({ id, versao, tocar, tempoAtual, tocando, rolagem, aoMudarRolagem }) {
  const [conteudo, erro] = useCarregar(() => api.conteudo(id), [id, versao]);
  const [busca, setBusca] = useState("");
  const termo = useAtraso(normalizarComPosicoes(busca.trim()), 150);
  const [ativo, setAtivo] = useState(0);
  const lista = useRef(null);
  const ligada = rolagem && !!tocar;
  const { seguindo, seguir, retomar } = useRolagemAutomatica({
    ligada, blocos: conteudo ? conteudo.blocos : null, tempoAtual, tocando, lista });

  useEffect(() => setAtivo(0), [termo]);
  useEffect(() => {
    if (!termo) return;
    const el = document.querySelector(`mark[data-achado="${ativo}"]`);
    if (el) el.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [ativo, termo, conteudo]);

  if (erro) return html`<${PainelErro} erro=${erro} />`;
  if (!conteudo) return html`<${Carregando} texto="Carregando o texto..." />`;
  if (!conteudo.blocos.length) return html`<div class="cartao"><${Vazio} icone="texto" titulo="Nenhuma fala reconhecida">
    A gravação não tinha fala detectável, ou o áudio estava mudo.</${Vazio}></div>`;

  // Clicar num horário mostra que a pessoa quer acompanhar dali: o acompanhamento volta.
  const tocarAqui = tocar && ((t) => { seguir(); tocar(t); });
  const cores = new Map(conteudo.participantes.map((p, i) => [p, i]));
  const contador = { n: 0 };
  const blocos = conteudo.blocos.map((b, i) => {
    const atual = tempoAtual !== null && tempoAtual >= b.inicio_s && tempoAtual < b.fim_s + 0.5;
    return html`<article class=${"bloco" + (atual ? " atual" : "")} key=${i}>
      <button type="button" class="tempo" onClick=${() => tocarAqui && tocarAqui(b.inicio_s)} disabled=${!tocar}
        title=${tocar ? "Ouvir a partir deste ponto" : undefined} aria-label=${`${tocar ? "Ouvir a partir de" : "Tempo"} ${hms(b.inicio_s)}`}>${hms(b.inicio_s)}</button>
      <div class="falante"><${CorFalante} indice=${cores.get(b.falante) || 0} />${b.falante}
        ${b.sobreposto_a.length > 0 && html`<span class="sobreposto">falas simultâneas com ${b.sobreposto_a.join(", ")}</span>`}</div>
      <p class="fala">${b.trechos.map((t, j) => {
        const sep = j > 0 ? " " : "";
        if (t.tipo === "incerto") {
          return html`${sep}<span class="incerto" title="Trecho incerto: confira na gravação"><span class="visualmente-oculto">trecho incerto: </span>${realcar(t.texto, termo, contador, ativo)}</span>`;
        }
        if (t.tipo === "marcador") return html`${sep}<span class="marcacao">${t.texto}</span>`;
        return html`${sep}${realcar(t.texto, termo, contador, ativo)}`;
      })}</p>
    </article>`;
  });
  const total = contador.n;

  return html`<div>
    <div class="ferramentas-texto">
      <div class="busca">
        <${Icone} nome="busca" />
        <input class="entrada" type="search" placeholder="Buscar no texto" aria-label="Buscar no texto" value=${busca}
          onInput=${(e) => setBusca(e.currentTarget.value)}
          onKeyDown=${(e) => { if (e.key === "Enter" && total) { e.preventDefault(); setAtivo((a) => (e.shiftKey ? (a - 1 + total) % total : (a + 1) % total)); } }} />
      </div>
      ${termo && html`<span class="texto-2 pequeno" role="status">${total ? `${ativo + 1} de ${total}` : "Nada encontrado"}</span>`}
      ${termo && total > 1 && html`<div class="acoes">
        <${Botao} tamanho="pequeno" icone="voltar" rotulo="Anterior" onClick=${() => setAtivo((a) => (a - 1 + total) % total)} />
        <${Botao} tamanho="pequeno" icone="avancar" rotulo="Próximo" onClick=${() => setAtivo((a) => (a + 1) % total)} />
      </div>`}
      ${tocar && html`<${Interruptor} classe="compacto" titulo="Rolagem automática" marcado=${rolagem} aoMudar=${aoMudarRolagem}
        dica="Durante a reprodução, a tela acompanha a fala que está tocando, com o player fixo no alto." />`}
    </div>
    ${ligada && !seguindo && tempoAtual !== null && html`<div class="retomar-rolagem">
      <${Botao} variante="primario" icone="alvo" onClick=${retomar}>Voltar ao trecho atual</${Botao}>
    </div>`}
    <div class="legenda-marcas" aria-label="Legenda">
      <span><span class="incerto">texto</span> trecho incerto: confira na gravação</span>
      <span><span class="marcacao">[inaudível]</span> havia fala, mas não foi possível entender</span>
      <span><span class="marcacao">[falas simultâneas: ...]</span> outra pessoa falou ao mesmo tempo</span>
    </div>
    <div class="cartao cartao-corpo" style="padding-top:6px;padding-bottom:6px"><div class="blocos" ref=${lista}>${blocos}</div></div>
  </div>`;
}

// -- aba Participantes -----------------------------------------------------------------------------

function AbaParticipantes({ id, versao, tocar, aoSalvar }) {
  const [lista, erro, definir] = useCarregar(() => api.participantes(id), [id, versao]);
  const [nomes, setNomes] = useState({});
  const [unioes, setUnioes] = useState({});
  const [salvando, setSalvando] = useState(false);
  const [erroSalvar, setErroSalvar] = useState(null);

  const itens = lista ? lista.itens : [];
  const rotulos = useMemo(() => new Map(itens.map((p) => [p.rotulo.toLowerCase(), p.rotulo])), [lista]);
  useEffect(() => {
    if (!lista) return;
    const n = {};
    const u = {};
    for (const p of itens) {
      const alvo = p.nome && rotulos.get(p.nome.toLowerCase());
      if (alvo && alvo !== p.rotulo) u[p.chave] = alvo;
      else n[p.chave] = p.nome || "";
    }
    setNomes(n);
    setUnioes(u);
  }, [lista]);

  if (erro) return html`<${PainelErro} erro=${erro} />`;
  if (!lista) return html`<${Carregando} texto="Carregando os participantes..." />`;
  if (!itens.length) return html`<div class="cartao"><${Vazio} icone="pessoas" titulo="Sem participantes identificados">
    A identificação de participantes estava desativada ou não encontrou vozes.</${Vazio}></div>`;

  const atribuicoes = [];
  for (const p of itens) {
    const original = p.nome || "";
    const uniao = unioes[p.chave];
    if (uniao) {
      if (rotulos.get(original.toLowerCase()) !== uniao) atribuicoes.push({ participante: p.rotulo, nome: uniao });
    } else if ((nomes[p.chave] || "").trim() !== original) {
      atribuicoes.push({ participante: p.rotulo, nome: (nomes[p.chave] || "").trim() });
    }
  }
  const alterado = atribuicoes.length > 0;
  const algumNome = itens.some((p) => p.nome);

  async function salvar(pedido) {
    setErroSalvar(null);
    setSalvando(true);
    try {
      const r = await api.nomear(id, pedido);
      notificar({ titulo: pedido.limpar ? "Nomes removidos" : "Nomes salvos",
        mensagem: `${plural(r.arquivos.length, "arquivo gerado", "arquivos gerados")} de novo com os nomes atualizados.` });
      definir(await api.participantes(id));
      aoSalvar();
    } catch (e) {
      setErroSalvar(e);
    } finally {
      setSalvando(false);
    }
  }

  async function limpar() {
    const ok = await confirmar({ titulo: "Remover todos os nomes?", mensagem: "Os participantes voltam a aparecer como Participante 1, Participante 2 etc., e os arquivos são gerados de novo.",
      confirmar: "Remover nomes", perigo: true });
    if (ok) salvar({ limpar: true });
  }

  return html`<div class="pilha" style="gap:18px">
    <${Aviso} tipo="info" titulo="O programa nunca atribui nomes sozinho">
      <p>Confira os exemplos de fala e as sugestões (nomes mencionados na própria conversa) e digite o nome de cada pessoa.
        Se a mesma pessoa apareceu com dois rótulos, use "É a mesma pessoa que".</p>
    </${Aviso}>
    <div class="cartao">
      ${itens.map((p, i) => {
        const uniao = unioes[p.chave] || "";
        const idNome = `nome-${p.chave}`;
        return html`<section class="participante" key=${p.chave} aria-labelledby=${`tit-${p.chave}`}>
          <div>
            <div class="cabeca">
              <h3 id=${`tit-${p.chave}`}><${CorFalante} indice=${i} />${p.rotulo}</h3>
              ${p.nome && !uniao && html`<${Etiqueta} tipo="acento">${p.nome}</${Etiqueta}>`}
              <span class="texto-2 pequeno">${duracao(p.tempo_fala_s)} de fala · ${plural(p.palavras, "palavra", "palavras")}</span>
              ${p.unido_com.length > 0 && html`<${Etiqueta} icone="unir" titulo="Exibidos com o mesmo nome">junto com ${p.unido_com.join(", ")}</${Etiqueta}>`}
            </div>
            ${p.exemplos.length ? html`<ul class="exemplos">${p.exemplos.map((ex) => html`<li>
              <${BotaoTempo} inicio=${ex.inicio_s} tocar=${tocar} /><q>${ex.texto}</q></li>`)}</ul>`
              : html`<p class="texto-2 pequeno" style="margin-top:8px">Só falas curtas: ouça a gravação para identificar.</p>`}
          </div>
          <div class="lado">
            <${Campo} id=${idNome} rotulo="Nome">
              <input id=${idNome} class="entrada" value=${uniao ? "" : nomes[p.chave] || ""} disabled=${!!uniao}
                placeholder=${uniao ? `Mesmo nome de ${uniao}` : p.rotulo} maxlength="300"
                onInput=${(e) => setNomes({ ...nomes, [p.chave]: e.currentTarget.value })} />
            </${Campo}>
            ${p.sugestoes.length > 0 && !uniao && html`<div class="pilha" style="gap:6px">
              <span class="ajuda">Mencionados na conversa (confirme antes de usar):</span>
              <div class="sugestoes">${p.sugestoes.map((s) => html`<button type="button" class="chip"
                onClick=${() => setNomes({ ...nomes, [p.chave]: s.nome })} aria-label=${`Usar o nome ${s.nome}`}>
                <${Icone} nome="mais" />${s.nome}${s.ocorrencias > 1 ? ` (${s.ocorrencias}x)` : ""}</button>`)}</div>
            </div>`}
            ${itens.length > 1 && html`<${Campo} id=${`uniao-${p.chave}`} rotulo="É a mesma pessoa que">
              <select id=${`uniao-${p.chave}`} class="selecao" value=${uniao}
                onChange=${(e) => setUnioes({ ...unioes, [p.chave]: e.currentTarget.value })}>
                <option value="">Ninguém (pessoa diferente)</option>
                ${itens.filter((o) => o.chave !== p.chave).map((o) => html`<option value=${o.rotulo} selected=${o.rotulo === uniao}>${o.rotulo}${o.nome ? ` (${o.nome})` : ""}</option>`)}
              </select>
            </${Campo}>`}
          </div>
        </section>`;
      })}
    </div>
    <${PainelErro} erro=${erroSalvar} titulo="Não foi possível salvar os nomes" />
    <div class="rodape-acao">
      <span class="resumo">${alterado ? html`<strong>${plural(atribuicoes.length, "alteração", "alterações")}</strong> ainda não salvas`
        : "Os arquivos (Word, textos e legendas) são gerados de novo ao salvar."}</span>
      <div class="acoes">
        ${algumNome && html`<${Botao} variante="fantasma" icone="lixeira" onClick=${limpar} disabled=${salvando}>Remover todos os nomes</${Botao}>`}
        <${Botao} onClick=${() => definir({ ...lista })} disabled=${!alterado || salvando}>Desfazer</${Botao}>
        <${Botao} variante="primario" icone="ok" carregando=${salvando} disabled=${!alterado} onClick=${() => salvar({ atribuicoes })}>Salvar nomes</${Botao}>
      </div>
    </div>
  </div>`;
}

// -- aba Conferência -------------------------------------------------------------------------------

const TIPOS_PONTO = { incerto: ["atencao", "Trecho incerto"], inaudivel: ["", "Inaudível"], descartado: ["info", "Descartado"] };

function AbaConferencia({ id, versao, tocar }) {
  const [rel, erro] = useCarregar(() => api.relatorio(id), [id, versao]);
  if (erro) return html`<${PainelErro} erro=${erro} />`;
  if (!rel) return html`<${Carregando} texto="Carregando o relatório..." />`;
  const ind = rel.indicadores;
  const proc = rel.processamento;
  return html`<div class="pilha" style="gap:30px">
    <section aria-labelledby="t-indicadores">
      <div class="secao-cabecalho"><h2 id="t-indicadores">Indicadores de qualidade</h2></div>
      <div class="indicadores">
        <div class="indicador"><span class="valor">${inteiro(ind.palavras)}</span><span class="rotulo">palavras transcritas</span></div>
        <div class=${"indicador" + (ind.incertas ? " destaque" : "")}><span class="valor">${inteiro(ind.incertas)}</span>
          <span class="rotulo">palavras incertas (${String(ind.percentual_incertas).replace(".", ",")}%)</span></div>
        <div class=${"indicador" + (ind.inaudiveis ? " destaque" : "")}><span class="valor">${inteiro(ind.inaudiveis)}</span><span class="rotulo">trechos inaudíveis</span></div>
        <div class="indicador"><span class="valor">${inteiro(ind.simultaneas)}</span><span class="rotulo">falas simultâneas não transcritas</span></div>
        <div class="indicador"><span class="valor">${inteiro(ind.janelas_revisadas)}</span><span class="rotulo">trechos revisados no segundo passo</span></div>
        <div class="indicador"><span class="valor">${inteiro(ind.alucinacoes)}</span><span class="rotulo">frases descartadas como invenção do modelo</span></div>
      </div>
    </section>

    <section aria-labelledby="t-pontos">
      <div class="secao-cabecalho"><h2 id="t-pontos">Pontos para conferência</h2>
        <p>${rel.pontos.length ? "Ouça a gravação nestes pontos para confirmar ou corrigir o texto." : ""}</p></div>
      ${rel.pontos.length === 0 ? html`<div class="cartao"><${Vazio} icone="ok" titulo="Nenhum ponto de dúvida registrado" /></div>`
        : html`<div class="cartao tabela-rolagem"><table class="tabela">
          <thead><tr><th scope="col">Tempo</th><th scope="col">Participante</th><th scope="col">Tipo</th><th scope="col">Trecho</th></tr></thead>
          <tbody>${rel.pontos.map((p) => {
            const [tipo, rotulo] = TIPOS_PONTO[p.tipo] || ["", p.rotulo_tipo];
            return html`<tr><td><${BotaoTempo} inicio=${p.inicio_s} tocar=${tocar} /></td><td>${p.participante || "-"}</td>
              <td><${Etiqueta} tipo=${tipo}>${rotulo}</${Etiqueta}></td><td>${p.trecho}</td></tr>`;
          })}</tbody></table></div>`}
    </section>

    <section aria-labelledby="t-sugestoes">
      <div class="secao-cabecalho"><h2 id="t-sugestoes">Sugestões de nomes</h2>
        ${rel.sugestoes.length > 0 && html`<a href=${`#/transcricoes/${id}/participantes`}>Dar nomes aos participantes</a>`}</div>
      ${rel.sugestoes.length === 0 ? html`<div class="cartao"><${Vazio} icone="pessoas" titulo="Nenhum nome mencionado com clareza">
          Autoidentificações ("aqui é a Ana") e menções diretas a alguém pelo nome aparecem aqui.</${Vazio}></div>`
        : html`<div class="cartao tabela-rolagem"><table class="tabela">
          <thead><tr><th scope="col">Participante</th><th scope="col">Nome sugerido</th><th scope="col">Evidências</th><th scope="col">Exemplo</th></tr></thead>
          <tbody>${rel.sugestoes.map((s) => html`<tr><td>${s.participante}</td><td><strong>${s.nome}</strong></td><td>${s.evidencias}</td>
            <td><${BotaoTempo} inicio=${s.exemplo_inicio_s} tocar=${tocar} /> ${s.exemplo}</td></tr>`)}</tbody></table></div>`}
    </section>

    <section aria-labelledby="t-mencoes">
      <div class="secao-cabecalho"><h2 id="t-mencoes">Índice de menções</h2><p>Citações literais com valores, datas, prazos, horários, percentuais e encaminhamentos.</p></div>
      ${rel.mencoes.length === 0 ? html`<div class="cartao"><${Vazio} icone="busca" titulo="Nenhuma menção encontrada" /></div>`
        : html`<div class="cartao mencoes">${rel.mencoes.map((c, i) => html`<details open=${i === 0} key=${c.categoria}>
            <summary><${Icone} nome="direita" />${c.categoria}<${Etiqueta}>${c.itens.length}</${Etiqueta}></summary>
            <ul>${c.itens.map((m) => html`<li><${BotaoTempo} inicio=${m.inicio_s} tocar=${tocar} />
              <span><strong>${m.participante}:</strong> ${m.texto}</span></li>`)}</ul>
          </details>`)}</div>`}
    </section>

    <section aria-labelledby="t-processamento">
      <div class="secao-cabecalho"><h2 id="t-processamento">Processamento</h2></div>
      <div class="cartao cartao-corpo"><dl class="pares">
        <dt>Reconhecimento de fala</dt><dd>${proc.descricao_asr || "-"}</dd>
        <dt>Identificação de participantes</dt><dd>${proc.descricao_diarizacao || "-"}</dd>
        <dt>Dispositivo</dt><dd>${proc.dispositivo || "-"}</dd>
        ${rel.audio.canais && html`<dt>Canais</dt><dd>${rel.audio.canais}</dd>`}
        ${rel.audio.snr_db !== null && html`<dt>Nível de fala e de ruído</dt><dd>${rel.audio.nivel_fala_db} dBFS e ${rel.audio.nivel_ruido_db} dBFS
          (relação sinal-ruído de ${rel.audio.snr_db} dB)</dd>`}
        ${rel.audio.tratamento && html`<dt>Tratamento do áudio</dt><dd>${rel.audio.tratamento}</dd>`}
        ${proc.contexto && html`<dt>Assunto informado</dt><dd>${proc.contexto}</dd>`}
        ${proc.glossario.length > 0 && html`<dt>Glossário</dt><dd>${proc.glossario.join(", ")}</dd>`}
        <dt>Tempo de processamento</dt><dd>${duracao(proc.tempo_total_s || 0)}${Object.keys(proc.tempos_etapas_s).length ? ` (${Object.entries(proc.tempos_etapas_s).map(([k, v]) => `${k} ${duracao(v)}`).join(", ")})` : ""}</dd>
        ${[...rel.audio.observacoes, ...rel.observacoes].map((o) => html`<dt>Observação</dt><dd>${o}</dd>`)}
      </dl></div>
    </section>
  </div>`;
}

// -- aba Arquivos ----------------------------------------------------------------------------------

const ROTULOS_ARQUIVO = { docx: "Word", md: "Markdown", txt: "Texto", srt: "Legendas SRT", vtt: "Legendas WebVTT",
  json: "Dados completos (JSON)", relatorio: "Relatório de conferência", log: "Registro técnico" };

function AbaArquivos({ det, aoGerar }) {
  const catalogo = useLoja((e) => e.opcoes);
  const [formatos, setFormatos] = useState(() => new Set(catalogo ? catalogo.padroes.formatos : ["md", "txt", "docx", "srt", "vtt", "json"]));
  const [destino, setDestino] = useState("mesma");
  const [pasta, setPasta] = useState("");
  const [gerando, setGerando] = useState(false);
  const [erro, setErro] = useState(null);

  async function gerar() {
    setErro(null);
    setGerando(true);
    try {
      const r = await api.exportar(det.id, { formatos: [...formatos], pasta_destino: destino === "outra" ? pasta : null });
      notificar({ titulo: "Arquivos gerados", mensagem: r.pasta, acao: { rotulo: "Abrir pasta", executar: () => executar(() => api.abrir(r.pasta)) } });
      aoGerar();
    } catch (e) {
      setErro(e);
    } finally {
      setGerando(false);
    }
  }

  const existentes = det.arquivos.filter((a) => a.existe);
  return html`<div class="pilha" style="gap:30px">
    <section aria-labelledby="t-arquivos">
      <div class="secao-cabecalho"><h2 id="t-arquivos">Arquivos gerados</h2>
        <${Botao} tamanho="pequeno" icone="pasta" onClick=${() => executar(() => api.abrir(det.pasta), "Não foi possível abrir a pasta")}>Abrir pasta</${Botao}></div>
      <ul class="cartao lista-cartao">
        ${existentes.map((a) => html`<li key=${a.tipo} class="item-lista">
          <span class="arquivo-icone"><${Icone} nome=${a.tipo === "srt" || a.tipo === "vtt" ? "texto" : "documento"} /></span>
          <span class="corpo"><span class="nome">${ROTULOS_ARQUIVO[a.tipo] || a.tipo}</span>
            <span class="detalhes"><span class="mono">${a.nome}</span><span>${bytes(a.tamanho_bytes)}</span><span>${quando(a.modificado_em)}</span></span></span>
          <span class="lado">
            <${Botao} tamanho="pequeno" icone="externo" onClick=${() => executar(() => api.abrir(a.caminho), "Não foi possível abrir o arquivo")}>Abrir</${Botao}>
            <${Botao} tamanho="pequeno" variante="fantasma" icone="pasta" rotulo=${`Mostrar ${a.nome} na pasta`}
              onClick=${() => executar(() => api.abrir(a.caminho, true), "Não foi possível mostrar o arquivo")} />
          </span>
        </li>`)}
      </ul>
    </section>

    <section class="cartao" aria-labelledby="t-gerar">
      <div class="grupo-form">
        <div><h2 id="t-gerar">Gerar os arquivos de novo</h2>
          <p class="ajuda" style="margin-top:4px">A partir do JSON da transcrição: útil para obter um formato que não foi escolhido, ou uma cópia em outra pasta.</p></div>
        <fieldset><legend>Formatos</legend><div class="caixas">
          ${(catalogo ? catalogo.formatos : []).map((f) => {
            const sempre = f.valor === "json";
            return html`<label class="caixa" title=${f.descricao}><input type="checkbox" checked=${sempre || formatos.has(f.valor)} disabled=${sempre}
              onChange=${(e) => { const s = new Set(formatos); e.currentTarget.checked ? s.add(f.valor) : s.delete(f.valor); setFormatos(s); }} />
              <span>${f.rotulo}</span></label>`;
          })}
        </div></fieldset>
        <fieldset><legend>Destino</legend><div class="escolhas em-linha">
          <label class="escolha"><input type="radio" name="destino" checked=${destino === "mesma"} onChange=${() => setDestino("mesma")} />
            <span class="corpo"><span class="titulo">Pasta da transcrição</span><span class="descricao">Substitui os arquivos atuais.</span></span></label>
          <label class="escolha"><input type="radio" name="destino" checked=${destino === "outra"} onChange=${() => setDestino("outra")} />
            <span class="corpo"><span class="titulo">Outra pasta</span>
              ${destino === "outra" ? html`<span class="com-botao" style="margin-top:6px">
                <input class="entrada" aria-label="Pasta de destino" value=${pasta} onInput=${(e) => setPasta(e.currentTarget.value)} />
                <${Botao} icone="pasta" onClick=${async () => { const p = await escolherPasta(pedirCaminho); if (p) setPasta(p); }}>Escolher</${Botao}></span>`
                : html`<span class="descricao">Uma cópia, sem alterar a original.</span>`}</span></label>
        </div></fieldset>
        <${PainelErro} erro=${erro} titulo="Não foi possível gerar os arquivos" />
        <div class="acoes"><${Botao} variante="primario" icone="repetir" carregando=${gerando} disabled=${destino === "outra" && !pasta.trim()}
          onClick=${gerar}>Gerar arquivos</${Botao}></div>
      </div>
    </section>
  </div>`;
}

// -- tela -----------------------------------------------------------------------------------------

// Com "fixar" (rolagem automática na aba Texto), o player fica no alto da tela a partir da primeira
// reprodução, mesmo pausado, para o vídeo continuar à vista enquanto o texto rola.
function Reprodutor({ det, refMidia, aoTempo, tempoAtual, tocando, aoTocar, fixar }) {
  const [falhou, setFalhou] = useState(false);
  const [iniciado, setIniciado] = useState(false);
  const [visivel, setVisivel] = useState(true);
  const caixa = useRef(null);
  const fixo = fixar && iniciado;
  useEffect(() => {
    if (!caixa.current || !window.IntersectionObserver) return undefined;
    const obs = new IntersectionObserver(([e]) => setVisivel(e.isIntersecting), { threshold: 0.2 });
    obs.observe(caixa.current);
    return () => obs.disconnect();
  }, [caixa.current]);
  // A altura do player fixo desconta da área visível, para o foco do teclado e a busca não pararem atrás dele.
  useEffect(() => {
    const el = caixa.current;
    if (!fixo || !el) return undefined;
    const raiz = document.documentElement;
    const medir = () => raiz.style.setProperty("--altura-reprodutor", `${Math.ceil(el.getBoundingClientRect().height)}px`);
    medir();
    const obs = window.ResizeObserver ? new ResizeObserver(medir) : null;
    if (obs) obs.observe(el);
    return () => {
      if (obs) obs.disconnect();
      raiz.style.removeProperty("--altura-reprodutor");
    };
  }, [fixo]);
  if (!det.origem_disponivel) {
    return html`<${Aviso} tipo="info" titulo="A gravação original não está no mesmo lugar">
      <p>Ela estava em <span class="mono">${det.arquivo_origem}</span>. Sem ela, os tempos não tocam o áudio; o texto continua disponível.</p>
    </${Aviso}>`;
  }
  if (falhou) {
    return html`<${Aviso} tipo="atencao" titulo="Este formato não pode ser reproduzido dentro do Transcritor"
      acoes=${html`<${Botao} tamanho="pequeno" icone="externo" onClick=${() => executar(() => api.abrir(det.arquivo_origem))}>Abrir no player do sistema</${Botao}>`}>
      <p>Use os tempos indicados no texto para localizar os trechos no seu player.</p>
    </${Aviso}>`;
  }
  const Tag = det.tem_video ? "video" : "audio";
  const classes = ["reprodutor", det.tem_video ? "com-video" : "", fixo ? "fixo" : ""].filter(Boolean).join(" ");
  return html`<div class=${classes} ref=${caixa}>
    <div class="reprodutor-corpo">
      <${Tag} ref=${refMidia} src=${api.urlMidia(det.id)} controls preload="metadata" aria-label=${`Gravação: ${det.nome}`}
        onError=${() => setFalhou(true)} onTimeUpdate=${(e) => aoTempo(e.currentTarget.currentTime)}
        onPlay=${() => { setIniciado(true); aoTocar(true); }} onPause=${() => aoTocar(false)} onEnded=${() => aoTocar(false)} />
      ${det.tem_video && html`<p class="ajuda">Clique em qualquer horário do texto para ouvir aquele trecho.</p>`}
    </div>
    ${tocando && !visivel && html`<div class="reproducao-flutuante" role="region" aria-label="Reprodução">
      <span class="ao-vivo" aria-hidden="true"></span>
      <span class="mono">${hms(tempoAtual || 0)}</span>
      <${Botao} tamanho="pequeno" onClick=${() => refMidia.current && refMidia.current.pause()}>Pausar</${Botao}>
    </div>`}
  </div>`;
}

export function TelaTranscricao({ id, aba = "texto" }) {
  const versao = useVersao(id);
  const [extra, setExtra] = useState(0);
  const [det, erro] = useCarregar(() => api.transcricao(id), [id, versao, extra]);
  const midia = useRef(null);
  const [tempoAtual, setTempoAtual] = useState(null);
  const [tocando, setTocando] = useState(false);
  const [rolagem, setRolagem] = useState(() => preferencia("rolagemAutomatica", false));
  useTitulo(det ? det.nome : "Transcrição");
  const recarregar = () => setExtra((x) => x + 1);
  const mudarRolagem = (v) => { setRolagem(v); salvarPreferencia("rolagemAutomatica", v); };

  if (erro) {
    return html`<div class="conteudo"><a class="voltar" href="#/transcricoes"><${Icone} nome="voltar" tamanho=${16} /> Transcrições</a>
      <${PainelErro} erro=${erro} acoes=${erro.codigo === "arquivos_indisponiveis" ? html`<div class="acoes">
        <${Botao} onClick=${abrirExistente}>Abrir do novo local</${Botao}>
        <${Botao} variante="perigo" onClick=${() => remover()}>Remover do histórico</${Botao}></div>` : null} /></div>`;
  }
  if (!det) return html`<div class="conteudo"><${Carregando} /></div>`;

  const tocar = det.origem_disponivel ? (t) => {
    const m = midia.current;
    if (!m) return;
    m.currentTime = Math.max(0, t - 0.4);
    m.play().catch(() => {});
  } : null;
  const docx = det.arquivos.find((a) => a.tipo === "docx" && a.existe);
  const pontos = det.indicadores.pontos_conferencia;

  async function remover() {
    const ok = await confirmar({ titulo: "Remover do histórico?",
      mensagem: "A transcrição sai da lista do Transcritor. Os arquivos continuam na pasta e podem ser abertos de novo pelo .json.",
      confirmar: "Remover", perigo: true });
    if (!ok) return;
    const r = await executar(() => api.removerTranscricao(id), "Não foi possível remover");
    if (r !== undefined) { recarregarTranscricoes(); ir("/transcricoes"); }
  }

  const abaAtual = ABAS.some((a) => a.id === aba) ? aba : "texto";
  return html`<div class="conteudo">
    <a class="voltar" href="#/transcricoes"><${Icone} nome="voltar" tamanho=${16} /> Transcrições</a>
    <header class="cabecalho">
      <div class="titulos">
        <h1>${det.nome}</h1>
        <div class="meta">
          ${det.duracao_s ? html`<span><${Icone} nome="relogio" tamanho=${15} />${duracao(det.duracao_s)}</span>` : null}
          <span><${Icone} nome="pessoas" tamanho=${15} />${det.participantes.length ? det.participantes.join(", ") : "Sem identificação de participantes"}</span>
          ${det.gerado_em && html`<span>Processado em ${det.gerado_em}</span>`}
        </div>
      </div>
      <div class="acoes">
        ${docx && html`<${Botao} variante="primario" icone="documento" onClick=${() => executar(() => api.abrir(docx.caminho), "Não foi possível abrir o documento")}>Abrir no Word</${Botao}>`}
        <${Botao} icone="pasta" onClick=${() => executar(() => api.abrir(det.pasta), "Não foi possível abrir a pasta")}>Abrir pasta</${Botao}>
        <${Botao} variante="fantasma" icone="lixeira" rotulo="Remover do histórico" onClick=${remover} />
      </div>
    </header>

    <${Reprodutor} det=${det} refMidia=${midia} aoTempo=${setTempoAtual} tempoAtual=${tempoAtual}
      tocando=${tocando} aoTocar=${setTocando} fixar=${rolagem && abaAtual === "texto"} />

    <nav class="abas" aria-label="Seções da transcrição">
      ${ABAS.map((a) => html`<a href=${`#/transcricoes/${id}/${a.id}`} aria-current=${a.id === abaAtual ? "page" : undefined}>
        <${Icone} nome=${a.icone} />${a.rotulo}
        ${a.id === "conferencia" && pontos > 0 && html`<${Etiqueta} tipo="atencao">${pontos}</${Etiqueta}>`}
        ${a.id === "participantes" && det.falantes.length > 0 && html`<${Etiqueta}>${det.falantes.length}</${Etiqueta}>`}
      </a>`)}
    </nav>

    ${abaAtual === "texto" && html`<${AbaTexto} id=${id} versao=${versao + extra} tocar=${tocar} tempoAtual=${tempoAtual}
      tocando=${tocando} rolagem=${rolagem} aoMudarRolagem=${mudarRolagem} />`}
    ${abaAtual === "participantes" && html`<${AbaParticipantes} id=${id} versao=${versao} tocar=${tocar} aoSalvar=${recarregar} />`}
    ${abaAtual === "conferencia" && html`<${AbaConferencia} id=${id} versao=${versao + extra} tocar=${tocar} />`}
    ${abaAtual === "arquivos" && html`<${AbaArquivos} det=${det} aoGerar=${recarregar} />`}
  </div>`;
}

