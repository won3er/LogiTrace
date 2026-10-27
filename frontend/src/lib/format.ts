const nf = (d: number) => new Intl.NumberFormat("pt-BR", { maximumFractionDigits: d, minimumFractionDigits: 0 });

export function fmt(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return nf(digits).format(v);
}

export function fmtCompact(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return new Intl.NumberFormat("pt-BR", { notation: "compact", maximumFractionDigits: 1 }).format(v);
}

export function fmtPct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined) return "—";
  return `${nf(digits).format(v * 100)}%`;
}

export function fmtBRL(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined) return "—";
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: digits }).format(v);
}

export function fmtSigned(v: number | null | undefined, digits = 1, unit = ""): string {
  if (v === null || v === undefined) return "—";
  const s = nf(digits).format(v);
  return `${v > 0 ? "+" : ""}${s}${unit ? ` ${unit}` : ""}`;
}

export function fmtDate(s: string | null | undefined): string {
  if (!s) return "—";
  return new Date(s).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

export function hours(h: number | null | undefined): string {
  if (h === null || h === undefined) return "—";
  const hh = Math.floor(h);
  const mm = Math.round((h - hh) * 60);
  return `${hh} h ${String(mm).padStart(2, "0")} min`;
}
