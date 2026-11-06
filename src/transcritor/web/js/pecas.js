// Peças compartilhadas entre telas: cartões de tarefa e itens de transcrição.
import { api } from "./api.js";
import { html } from "./biblioteca.js";
import { Barra, Botao, Etiqueta, executar, notificar } from "./componentes.js";
import { duracao, plural, quando, restante } from "./formato.js";
import { Icone, iconeDoArquivo } from "./icones.js";
import { guardarTarefa, ir } from "./loja.js";

export const NOMES_TIPO = { transcricao: "Transcrição", verificacao: "Verificação do ambiente", download_modelos: "Download dos modelos" };

export function situacaoTarefa(t) {
  const p = t.progresso || {};
  switch (t.estado) {
    case "na_fila":
      return t.posicao_fila > 1 ? `Na fila (posição ${t.posicao_fila})` : "Na fila: começa em seguida";
    case "em_andamento": {
      const etapa = p.etapas && p.etapa_atual ? p.etapas[p.etapa_atual - 1] : null;
      if (!etapa) return "Preparando...";
      return p.total_etapas > 1 ? `Etapa ${etapa.numero} de ${p.total_etapas}: ${etapa.titulo}` : etapa.titulo;
    }
    case "concluida":
      return `Concluída ${quando(t.concluida_em)}`;
    case "falhou":
      return t.erro ? t.erro.mensagem : "Falhou";
    case "cancelada":
      return "Cancelada";
    case "interrompida":
      return "Interrompida quando o Transcritor foi fechado";
    default:
      return t.estado;
  }
}

export const ETIQUETA_ESTADO = {
  na_fila: ["", "Na fila"], em_andamento: ["acento", "Em andamento"], concluida: ["sucesso", "Concluída"],
  falhou: ["erro", "Falhou"], cancelada: ["", "Cancelada"], interrompida: ["atencao", "Interrompida"],
};

export function EtiquetaEstado({ estado }) {
  const [tipo, texto] = ETIQUETA_ESTADO[estado] || ["", estado];
  return html`<${Etiqueta} tipo=${tipo}>${texto}</${Etiqueta}>`;
}

export async function cancelarTarefa(t) {
  const nova = await executar(() => api.cancelar(t.id), "Não foi possível cancelar");
  if (nova) guardarTarefa(nova);
}

export async function repetirTarefa(t, abrir = true) {
  const nova = await executar(() => api.repetir(t.id), "Não foi possível retomar");
  if (nova) {
    guardarTarefa(nova);
    notificar({ tipo: "info", titulo: t.estado === "concluida" ? "Tarefa iniciada de novo" : "Tarefa retomada",
      mensagem: t.tipo === "transcricao" ? "As etapas já concluídas serão reaproveitadas." : undefined });
    if (abrir) ir(`/atividades/${nova.id}`);
  }
}

export function CartaoTarefa({ tarefa: t, compacto }) {
  const p = t.progresso || {};
  const andamento = t.estado === "em_andamento";
  const etapaAtual = p.etapas && p.etapa_atual ? p.etapas[p.etapa_atual - 1] : null;
  const indeterminada = andamento && (p.fracao_etapa === null || p.fracao_etapa === undefined);
  const eta = restante(p.restante_estimado_s);
  return html`<article class="cartao tarefa-cartao" aria-label=${`${NOMES_TIPO[t.tipo]}: ${t.titulo}`}>
    <div class="tarefa-topo">
      <span class="arquivo-icone"><${Icone} nome=${t.tipo === "transcricao" ? iconeDoArquivo(t.titulo) : "ajustes"} /></span>
      <div class="corpo">
        <a class="nome" href=${`#/atividades/${t.id}`}>${t.titulo}</a>
        <span class="estado">${situacaoTarefa(t)}</span>
      </div>
      ${t.pode_cancelar && html`<${Botao} tamanho="pequeno" variante="fantasma" icone="fechar" onClick=${() => cancelarTarefa(t)}
        rotulo=${`Cancelar ${t.titulo}`}>Cancelar</${Botao}>`}
    </div>
    ${t.estado !== "na_fila" && html`<${Barra} valor=${p.percentual} indeterminada=${indeterminada && p.percentual < 1}
      rotulo=${`Progresso de ${t.titulo}`} />`}
    ${!compacto && andamento && html`<div class="numeros">
      <span><strong>${Math.round(p.percentual || 0)}%</strong>${etapaAtual && p.mensagem && p.mensagem !== etapaAtual.detalhe ? ` · ${p.mensagem}` : ""}</span>
      <span>${eta ? `${eta} restantes` : indeterminada ? "calculando o tempo restante..." : ""}</span>
    </div>`}
  </article>`;
}

export function ItemTranscricao({ t }) {
  const detalhes = [quando(t.atualizado_em), t.duracao_s ? duracao(t.duracao_s) : null,
    t.participantes.length ? plural(t.participantes.length, "participante", "participantes") : null].filter(Boolean);
  return html`<a class=${"item-lista" + (t.disponivel ? "" : " indisponivel")} href=${`#/transcricoes/${t.id}`}>
    <span class="arquivo-icone"><${Icone} nome=${iconeDoArquivo(t.nome)} /></span>
    <span class="corpo">
      <span class="nome">${t.nome}</span>
      <span class="detalhes">${detalhes.map((d) => html`<span>${d}</span>`)}</span>
    </span>
    <span class="lado">
      ${!t.disponivel ? html`<${Etiqueta} tipo="erro" icone="alerta">Arquivos não encontrados</${Etiqueta}>`
        : t.pontos_conferencia > 0 ? html`<${Etiqueta} tipo="atencao" titulo="Pontos para ouvir de novo e conferir">
            ${plural(t.pontos_conferencia, "ponto", "pontos")} para conferir</${Etiqueta}>`
        : html`<${Etiqueta} tipo="sucesso" icone="ok">Sem pontos de dúvida</${Etiqueta}>`}
    </span>
    <${Icone} nome="direita" />
  </a>`;
}
