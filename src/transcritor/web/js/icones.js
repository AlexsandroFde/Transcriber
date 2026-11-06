// Ícones em traço (grade 24 x 24), desenhados para este aplicativo.
import { html } from "./biblioteca.js";

const T = {
  marca: "M5 10v4M8.5 7v10M12 9.5v5M15 8h5M15 12h5M15 16h3",
  mais: "M12 5v14M5 12h14",
  fechar: "M6 6l12 12M18 6 6 18",
  ok: "M5 12.5l4.5 4.5L19 7.5",
  voltar: "M19 12H5M11 6l-6 6 6 6",
  avancar: "M5 12h14M13 6l6 6-6 6",
  baixo: "M6 9l6 6 6-6",
  direita: "M9 6l6 6-6 6",
  enviar: "M12 15V4M7.5 8.5 12 4l4.5 4.5M5 15v3a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-3",
  arquivo: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5",
  documento: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5M9 13h6M9 17h4",
  video: "M3 7.5A1.5 1.5 0 0 1 4.5 6h10A1.5 1.5 0 0 1 16 7.5v9a1.5 1.5 0 0 1-1.5 1.5h-10A1.5 1.5 0 0 1 3 16.5zM16 10.5l5-3v9l-5-3",
  audio: "M4 10v4M8 7v10M12 4v16M16 8v8M20 11v2",
  pasta: "M3 7.5A1.5 1.5 0 0 1 4.5 6H9l2 2h8.5A1.5 1.5 0 0 1 21 9.5v8a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5z",
  lista: "M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01",
  atividade: "M3 12h4l3-7 4 14 3-7h4",
  ajustes: "M4 7h9M17 7h3M4 17h3M11 17h9M15 5v4M9 15v4",
  alerta: "M12 4 21 19.5H3zM12 10v4.5M12 17.2v.1",
  info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 11v5.5M12 7.8v.1",
  erro: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM9 9l6 6M15 9l-6 6",
  sucesso: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM8 12.5l2.7 2.7L16 9.8",
  relogio: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7.5V12l3 2",
  pessoas: "M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6M16 4.5a3.5 3.5 0 0 1 0 6.8M18 14.3c2 .8 3.5 2.8 3.5 5.7",
  busca: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM16.2 16.2 21 21",
  repetir: "M4 12a8 8 0 0 1 13.7-5.6L20 8.5M20 4v4.5h-4.5M20 12a8 8 0 0 1-13.7 5.6L4 15.5M4 20v-4.5h4.5",
  lixeira: "M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3",
  copiar: "M9 9.5A1.5 1.5 0 0 1 10.5 8h8A1.5 1.5 0 0 1 20 9.5v9a1.5 1.5 0 0 1-1.5 1.5h-8A1.5 1.5 0 0 1 9 18.5zM5 15V5.5A1.5 1.5 0 0 1 6.5 4H15",
  externo: "M14 4h6v6M20 4l-9 9M18 14v4.5a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6H10",
  chave: "M8 19a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM10.9 12.1 20 3M16.5 6.5 19 9M14 9l2 2",
  chip: "M7 8.5A1.5 1.5 0 0 1 8.5 7h7A1.5 1.5 0 0 1 17 8.5v7a1.5 1.5 0 0 1-1.5 1.5h-7A1.5 1.5 0 0 1 7 15.5zM10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4",
  escudo: "M12 3l8 3v6c0 4.6-3.4 8.4-8 9-4.6-.6-8-4.4-8-9V6z",
  livro: "M4 5.5A1.5 1.5 0 0 1 5.5 4H20v13H5.5A1.5 1.5 0 0 0 4 18.5zM4 18.5A1.5 1.5 0 0 0 5.5 20H20",
  lapis: "M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16z",
  unir: "M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1",
  sol: "M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4",
  lua: "M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z",
  monitor: "M3 5.5A1.5 1.5 0 0 1 4.5 4h15A1.5 1.5 0 0 1 21 5.5v10a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 15.5zM8 21h8M12 17v4",
  texto: "M4 6h16M4 10h11M4 14h16M4 18h9",
  conferir: "M9 4h6v3H9zM8 5H6.5A1.5 1.5 0 0 0 5 6.5v13A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5v-13A1.5 1.5 0 0 0 17.5 5H16M9 14l2 2 4-4",
  ouvir: "M4 13a8 8 0 0 1 16 0v4a2 2 0 0 1-2 2h-1v-6h3M4 13v4a2 2 0 0 0 2 2h1v-6H4",
  alvo: "M12 18.5a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13zM12 2v3.5M12 18.5V22M2 12h3.5M18.5 12H22M12 12h.01",
  baixar: "M12 4v11M7.5 10.5 12 15l4.5-4.5M5 19h14",
  parar: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM9.5 9.5h5v5h-5z",
  codigo: "M8 7l-5 5 5 5M16 7l5 5-5 5M13.5 4l-3 16",
  olho: "M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  "olho-fechado": "M3.5 3.5l17 17M10.6 5.6A9.6 9.6 0 0 1 12 5.5c6 0 9.5 6.5 9.5 6.5a16.6 16.6 0 0 1-2.8 3.6M6.5 6.6C3.9 8.4 2.5 12 2.5 12s3.5 6.5 9.5 6.5c1.5 0 2.9-.4 4.1-1M9.9 9.9a3 3 0 0 0 4.2 4.2",
};
const PREENCHIDOS = { tocar: "M8 5.5v13a1 1 0 0 0 1.5.9l10.4-6.5a1 1 0 0 0 0-1.8L9.5 4.6A1 1 0 0 0 8 5.5z" };

export function Icone({ nome, tamanho, classe = "", titulo }) {
  const estilo = tamanho ? `width:${tamanho}px;height:${tamanho}px` : undefined;
  const preenchido = PREENCHIDOS[nome];
  return html`<svg class=${`icone ${preenchido ? "preenchido" : ""} ${classe}`} viewBox="0 0 24 24" style=${estilo}
    aria-hidden=${titulo ? undefined : "true"} role=${titulo ? "img" : undefined} aria-label=${titulo}
    focusable="false"><path d=${preenchido || T[nome] || T.arquivo} /></svg>`;
}

const POR_EXTENSAO = { video: /\.(mp4|mkv|mov|avi|wmv|webm|m4v|mpe?g|ts|mts|flv|3gp)$/i, audio: /\.(mp3|wav|m4a|aac|ogg|oga|opus|flac|wma|amr|aiff?)$/i };

export function iconeDoArquivo(nome) {
  if (POR_EXTENSAO.video.test(nome || "")) return "video";
  if (POR_EXTENSAO.audio.test(nome || "")) return "audio";
  return "arquivo";
}
