import { useEffect, useRef, type ReactNode } from "react";
import { errorMessage } from "../api/client";
import type { HealthState, Priority, RiskLevel, WOStatus } from "../api/types";
import { label, prob } from "../lib/format";

const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");
export { cx };

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-subtle">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Card({ title, actions, children, className, bodyClass }: {
  title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; bodyClass?: string;
}) {
  return (
    <section className={cx("card", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-2 border-b border-border px-4 py-2.5">
          <h2 className="text-sm font-semibold">{title}</h2>
          {actions}
        </header>
      )}
      <div className={cx("p-4", bodyClass)}>{children}</div>
    </section>
  );
}

export function Stat({ label: l, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: "ok" | "warn" | "danger" | "watch" }) {
  const toneCls = tone ? { ok: "text-ok", warn: "text-warn", danger: "text-danger", watch: "text-watch" }[tone] : "";
  return (
    <div className="card px-4 py-3">
      <div className="text-xs font-medium text-subtle">{l}</div>
      <div className={cx("mt-1 text-2xl font-semibold tabular-nums", toneCls)}>{value}</div>
      {hint && <div className="mt-0.5 text-2xs text-subtle">{hint}</div>}
    </div>
  );
}

type Tone = "ok" | "watch" | "warn" | "danger" | "unknown" | "primary" | "neutral";
const toneClass: Record<Tone, string> = {
  ok: "bg-ok/10 text-ok ring-ok/25", watch: "bg-watch/10 text-watch ring-watch/25", warn: "bg-warn/10 text-warn ring-warn/30",
  danger: "bg-danger/10 text-danger ring-danger/25", unknown: "bg-unknown/10 text-unknown ring-unknown/25",
  primary: "bg-primary/10 text-primary ring-primary/25", neutral: "bg-muted text-subtle ring-border",
};

export function Badge({ tone = "neutral", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={cx("inline-flex items-center gap-1 whitespace-nowrap rounded px-1.5 py-0.5 text-2xs font-semibold ring-1 ring-inset", toneClass[tone])}>
      {children}
    </span>
  );
}

const HEALTH: Record<HealthState, [Tone, string]> = {
  healthy: ["ok", "Healthy"], watch: ["watch", "Watch"], at_risk: ["warn", "At risk"], critical: ["danger", "Critical"], unknown: ["unknown", "Unknown"],
};
export const HealthBadge = ({ state }: { state: HealthState }) => <Badge tone={HEALTH[state][0]}>{HEALTH[state][1]}</Badge>;

export const RiskBadge = ({ level }: { level: RiskLevel | null }) =>
  level ? <Badge tone={level === "high" ? "danger" : level === "elevated" ? "warn" : "ok"}>{label(level)} risk</Badge> : <Badge>n/a</Badge>;

const WO: Record<WOStatus, Tone> = { open: "primary", assigned: "watch", in_progress: "warn", completed: "ok", cancelled: "neutral" };
export const WOStatusBadge = ({ status }: { status: WOStatus }) => <Badge tone={WO[status]}>{label(status)}</Badge>;

const PRI: Record<Priority, Tone> = { critical: "danger", high: "warn", medium: "watch", low: "neutral" };
export const PriorityBadge = ({ priority }: { priority: Priority }) => <Badge tone={PRI[priority]}>{label(priority)}</Badge>;

export function SourceBadge({ source }: { source: string }) {
  if (source === "simulated") return <Badge tone="watch" title="Synthetic data from the built-in simulator, not a real machine">Simulated</Badge>;
  if (source === "imported") return <Badge title="Imported historical data">Imported</Badge>;
  return <Badge title="Received through the API">Live API</Badge>;
}

export function Spinner({ className }: { className?: string }) {
  return <span role="status" aria-label="Loading" className={cx("inline-block h-4 w-4 animate-spin rounded-full border-2 border-primary/30 border-t-primary", className)} />;
}

export function Loading({ rows = 3 }: { rows?: number }) {
  return (
    <div aria-busy="true" aria-label="Loading" className="space-y-2">
      {Array.from({ length: rows }).map((_, i) => <div key={i} className="h-4 animate-pulse rounded bg-muted" style={{ width: `${90 - i * 12}%` }} />)}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-start justify-between gap-3 rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-sm text-danger">
      <span>{errorMessage(error)}</span>
      {onRetry && <button className="btn-ghost !py-0.5 text-danger" onClick={onRetry}>Retry</button>}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-4 py-10 text-center">
      <div className="mb-2 h-9 w-9 rounded-full border-2 border-dashed border-border" />
      <div className="text-sm font-medium">{title}</div>
      {children && <div className="mt-1 max-w-md text-sm text-subtle">{children}</div>}
    </div>
  );
}

/** Wraps a query result into loading / error / empty / content states. */
export function QueryState<T>({ q, empty, children, rows }: {
  q: { data?: T; isLoading: boolean; error: unknown; refetch: () => unknown };
  empty?: (d: T) => ReactNode | false; children: (d: T) => ReactNode; rows?: number;
}) {
  if (q.isLoading) return <Loading rows={rows} />;
  if (q.error) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  if (q.data === undefined) return null;
  const e = empty?.(q.data);
  if (e) return <>{e}</>;
  return <>{children(q.data)}</>;
}

export function Pagination({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="flex items-center justify-between gap-2 border-t border-border px-3 py-2 text-xs text-subtle">
      <span>{total === 0 ? "No results" : `${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, total)} of ${total}`}</span>
      <div className="flex items-center gap-1">
        <button className="btn-secondary !px-2 !py-0.5" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</button>
        <span className="px-1">Page {page} / {pages}</span>
        <button className="btn-secondary !px-2 !py-0.5" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</button>
      </div>
    </div>
  );
}

export function Modal({ open, title, onClose, children, footer, wide }: {
  open: boolean; title: string; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    ref.current?.querySelector<HTMLElement>("input, select, textarea, button")?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4 pt-[8vh]" onMouseDown={onClose}>
      <div ref={ref} role="dialog" aria-modal="true" aria-label={title}
        className={cx("card w-full shadow-xl", wide ? "max-w-3xl" : "max-w-lg")} onMouseDown={(e) => e.stopPropagation()}>
        <header className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 className="text-base font-semibold">{title}</h2>
          <button aria-label="Close" className="btn-ghost !px-2" onClick={onClose}>✕</button>
        </header>
        <div className="max-h-[70vh] overflow-y-auto p-4">{children}</div>
        {footer && <footer className="flex justify-end gap-2 border-t border-border px-4 py-3">{footer}</footer>}
      </div>
    </div>
  );
}

export function Field({ label: l, children, error, hint }: { label: string; children: ReactNode; error?: string; hint?: string }) {
  return (
    <label className="block">
      <span className="label">{l}</span>
      {children}
      {hint && !error && <span className="mt-1 block text-2xs text-subtle">{hint}</span>}
      {error && <span className="mt-1 block text-xs text-danger">{error}</span>}
    </label>
  );
}

export function Notice({ tone = "watch", children }: { tone?: "watch" | "warn" | "ok" | "danger"; children: ReactNode }) {
  const cls = { watch: "border-watch/30 bg-watch/5", warn: "border-warn/30 bg-warn/5", ok: "border-ok/30 bg-ok/5", danger: "border-danger/30 bg-danger/5" }[tone];
  return <div className={cx("rounded-md border px-3 py-2 text-sm", cls)}>{children}</div>;
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: string }[]; value: T; onChange: (t: T) => void }) {
  return (
    <div role="tablist" className="mb-4 flex gap-1 overflow-x-auto border-b border-border">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id} onClick={() => onChange(t.id)}
          className={cx("-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium",
            value === t.id ? "border-primary text-fg" : "border-transparent text-subtle hover:text-fg")}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

/** Bar coloured by the server-computed risk level (thresholds are per equipment type). */
export function ProbabilityBar({ value, level }: { value: number | null; level?: RiskLevel | null }) {
  if (value === null) return <span className="text-subtle">—</span>;
  const tone = level === "high" ? "bg-danger" : level === "elevated" ? "bg-warn" : "bg-ok";
  return (
    <div className="flex items-center gap-2" title={`${(value * 100).toFixed(1)}%`}>
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-muted"><div className={cx("h-full", tone)} style={{ width: `${Math.max(2, value * 100)}%` }} /></div>
      <span className="tabular-nums text-xs">{prob(value)}</span>
    </div>
  );
}
