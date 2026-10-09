export const pct = (v: number | null | undefined, digits = 0) =>
  v === null || v === undefined ? "—" : `${(v * 100).toFixed(digits)}%`;

export const num = (v: number | null | undefined, digits = 1) =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : v.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: 0 });

export const dateTime = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString(undefined, { year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—";

export const dateOnly = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "2-digit" }) : "—";

export const shortTime = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { month: "short", day: "2-digit", hour: "2-digit" });

export function relative(iso: string | null | undefined): string {
  if (!iso) return "—";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (Math.abs(s) < 60) return "just now";
  const units: [number, string][] = [[86400, "d"], [3600, "h"], [60, "min"]];
  for (const [size, label] of units) if (Math.abs(s) >= size) return `${Math.round(s / size)} ${label} ago`;
  return "just now";
}

export const label = (s: string | null | undefined) =>
  s ? s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()) : "—";

export function rulText(rul: number | null, status: string, cap?: number | null): string {
  if (status === "unavailable") return "RUL unavailable";
  if (status === "no_model") return "No RUL model";
  if (status === "insufficient_data") return "Insufficient data";
  if (rul === null) return "—";
  return cap && rul >= cap - 0.5 ? `≥ ${Math.round(cap)} h` : `${Math.round(rul)} h`;
}

/** Probability for display. Calibrated scores can reach exactly 0 or 1; never show certainty. */
export function prob(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  if (v > 0.99) return ">99%";
  if (v < 0.01) return "<1%";
  return `${Math.round(v * 100)}%`;
}
