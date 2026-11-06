// Estado compartilhado da interface (o que veio da API) e roteamento por hash.
import { useEffect, useState } from "./biblioteca.js";

const estado = {
  conexao: "conectando", // conectando | ok | perdida
  saude: null,
  sistema: null,
  opcoes: null,
  ambiente: null,
  tarefas: new Map(), // id -> tarefa
  transcricoes: null, // null enquanto carrega
  selecao: [], // caminhos escolhidos para a próxima transcrição
  desktop: false,
};

const ouvintes = new Set();
const ouvintesLog = new Set();

export function obter() {
  return estado;
}

export function atualizar(mudancas) {
  Object.assign(estado, mudancas);
  for (const f of ouvintes) f();
}

export function guardarTarefa(tarefa) {
  const mapa = new Map(estado.tarefas);
  mapa.set(tarefa.id, tarefa);
  atualizar({ tarefas: mapa });
}

export function guardarTarefas(lista) {
  atualizar({ tarefas: new Map(lista.map((t) => [t.id, t])) });
}

export function esquecerTarefa(id) {
  const mapa = new Map(estado.tarefas);
  mapa.delete(id);
  atualizar({ tarefas: mapa });
}

export function adicionarSelecao(caminhos) {
  const atuais = new Set(estado.selecao.map((c) => c.toLowerCase()));
  const novos = caminhos.filter((c) => c && !atuais.has(c.toLowerCase()));
  atualizar({ selecao: [...estado.selecao, ...novos] });
}

export function useLoja(seletor) {
  const [, forcar] = useState(0);
  useEffect(() => {
    const f = () => forcar((x) => x + 1);
    ouvintes.add(f);
    return () => ouvintes.delete(f);
  }, []);
  return seletor(estado);
}

// Linhas novas do registro técnico das tarefas (evento "log").
export function publicarLog(dados) {
  for (const f of ouvintesLog) f(dados);
}

export function ouvirLog(funcao) {
  ouvintesLog.add(funcao);
  return () => ouvintesLog.delete(funcao);
}

export const ATIVOS = new Set(["na_fila", "em_andamento"]);
export const ativa = (t) => ATIVOS.has(t.estado);

// -- rotas -------------------------------------------------------------------------

function analisar(hash) {
  const [caminho, consulta] = (hash.replace(/^#/, "") || "/").split("?");
  return { partes: caminho.split("/").filter(Boolean), params: new URLSearchParams(consulta || "") };
}

export function useRota() {
  const [hash, setHash] = useState(location.hash);
  useEffect(() => {
    const f = () => setHash(location.hash);
    window.addEventListener("hashchange", f);
    return () => window.removeEventListener("hashchange", f);
  }, []);
  return analisar(hash);
}

export function ir(caminho) {
  const destino = "#" + caminho;
  if (location.hash === destino) return;
  location.hash = destino;
}

// -- preferências locais (só desta interface, neste computador) ----------------------

export function preferencia(nome, padrao) {
  try {
    const v = localStorage.getItem("transcritor." + nome);
    return v === null ? padrao : JSON.parse(v);
  } catch (e) {
    return padrao;
  }
}

export function salvarPreferencia(nome, valor) {
  try {
    localStorage.setItem("transcritor." + nome, JSON.stringify(valor));
  } catch (e) { /* armazenamento indisponível: a preferência vale só nesta sessão */ }
}
