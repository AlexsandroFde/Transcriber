// Formatação para exibição (datas, durações, tamanhos). Nenhuma regra de negócio.

const numero = new Intl.NumberFormat("pt-BR");
const decimal = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });

export function duracao(segundos) {
  if (segundos === null || segundos === undefined || isNaN(segundos)) return "";
  const total = Math.round(Math.max(0, segundos));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h) return `${h} h ${String(m).padStart(2, "0")} min`;
  if (m) return `${m} min ${String(s).padStart(2, "0")} s`;
  return `${s} s`;
}

export function restante(segundos) {
  if (segundos === null || segundos === undefined) return null;
  if (segundos < 45) return "menos de 1 minuto";
  const min = Math.round(segundos / 60);
  if (min < 60) return `cerca de ${min} min`;
  const h = Math.floor(min / 60);
  return `cerca de ${h} h ${String(min % 60).padStart(2, "0")} min`;
}

export function hms(segundos) {
  const t = Math.max(0, Math.floor(segundos || 0));
  const h = String(Math.floor(t / 3600)).padStart(2, "0");
  const m = String(Math.floor((t % 3600) / 60)).padStart(2, "0");
  const s = String(t % 60).padStart(2, "0");
  return `${h}:${m}:${s}`;
}

export function dataHora(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return String(iso);
  return d.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function quando(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return String(iso);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return "agora há pouco";
  if (diff < 3600) return `há ${Math.floor(diff / 60)} min`;
  const hoje = new Date();
  const ontem = new Date(Date.now() - 86400000);
  const hora = d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === hoje.toDateString()) return `hoje, ${hora}`;
  if (d.toDateString() === ontem.toDateString()) return `ontem, ${hora}`;
  return dataHora(iso);
}

export function bytes(n) {
  if (n === null || n === undefined) return "";
  const unidades = ["bytes", "KB", "MB", "GB", "TB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < unidades.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${i === 0 ? numero.format(v) : decimal.format(v)} ${unidades[i]}`;
}

export const inteiro = (n) => numero.format(n || 0);
export const pct = (fracao) => `${Math.round((fracao || 0) * 100)}%`;
export const plural = (n, um, varios) => `${inteiro(n)} ${n === 1 ? um : varios}`;

export function nomeArquivo(caminho) {
  return String(caminho || "").split(/[\\/]/).pop();
}

export function pastaDe(caminho) {
  const partes = String(caminho || "").split(/[\\/]/);
  partes.pop();
  return partes.join(caminho.includes("\\") ? "\\" : "/");
}
