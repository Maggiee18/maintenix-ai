/**
 * Chart wrappers on Recharts. Conventions (see docs): one y-axis per chart, 2px lines,
 * categorical colours in fixed slot order following the entity (never its rank),
 * recessive grid, a legend whenever there are 2+ series, hover tooltips everywhere.
 * Colours are CSS custom properties so light/dark themes swap automatically.
 */
import type { ReactNode } from "react";
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { shortTime } from "../lib/format";

export const series = (i: number) => `rgb(var(--series-${(i % 8) + 1}))`;
export const tokenColor = (name: string) => `rgb(var(--${name}))`;

const axis = { stroke: "rgb(var(--subtle))", fontSize: 11, tickLine: false, axisLine: { stroke: "rgb(var(--border))" } };
const tooltipStyle = {
  contentStyle: { background: "rgb(var(--surface))", border: "1px solid rgb(var(--border))", borderRadius: 6, fontSize: 12, color: "rgb(var(--fg))" },
  labelStyle: { color: "rgb(var(--subtle))", marginBottom: 4 },
};

/** Legend labels use the text colour; the swatch carries the series colour. */
export const legendText = (value: string) => <span style={{ color: "rgb(var(--subtle))" }}>{value}</span>;

export interface LineSpec { key: string; label: string; color?: string; dashed?: boolean }

export function TimeChart({ data, xKey = "t", lines, height = 260, yLabel, yDomain, band, refLines, valueFormat, empty }: {
  data: Record<string, unknown>[]; xKey?: string; lines: LineSpec[]; height?: number; yLabel?: string;
  yDomain?: [number | "auto", number | "auto"]; band?: { y1: number; y2: number; label: string };
  refLines?: { y: number; label: string; color: string }[]; valueFormat?: (v: number) => string; empty?: ReactNode;
}) {
  if (!data.length) return <>{empty ?? <div className="py-10 text-center text-sm text-subtle">No data in this range</div>}</>;
  const fmt = valueFormat ?? ((v: number) => (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2)));
  return (
    <div style={{ height }} role="img" aria-label={`Time series chart: ${lines.map((l) => l.label).join(", ")}`}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="rgb(var(--border))" strokeDasharray="0" vertical={false} strokeOpacity={0.6} />
          <XAxis dataKey={xKey} {...axis} tickFormatter={(v) => shortTime(String(v))} minTickGap={40} />
          <YAxis {...axis} width={52} domain={yDomain ?? ["auto", "auto"]} tickFormatter={(v) => fmt(Number(v))}
            label={yLabel ? { value: yLabel, angle: -90, position: "insideLeft", fill: "rgb(var(--subtle))", fontSize: 11, dx: 4 } : undefined} />
          {band && <ReferenceArea y1={band.y1} y2={band.y2} fill="rgb(var(--ok))" fillOpacity={0.07} stroke="none" ifOverflow="extendDomain"
            label={{ value: band.label, position: "insideTopLeft", fill: "rgb(var(--subtle))", fontSize: 10 }} />}
          {refLines?.map((r) => <ReferenceLine key={r.label} y={r.y} stroke={r.color} strokeDasharray="4 3"
            label={{ value: r.label, position: "insideTopRight", fill: "rgb(var(--subtle))", fontSize: 10 }} />)}
          <Tooltip {...tooltipStyle} labelFormatter={(v) => new Date(String(v)).toLocaleString()}
            formatter={(v: number, name: string) => [typeof v === "number" ? fmt(v) : String(v), name]} />
          {lines.length > 1 && <Legend iconType="plainline" wrapperStyle={{ fontSize: 12 }} formatter={legendText} />}
          {lines.map((l, i) => (
            <Line key={l.key} type="linear" dataKey={l.key} name={l.label} stroke={l.color ?? series(i)} strokeWidth={2}
              strokeDasharray={l.dashed ? "5 4" : undefined} dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: "rgb(var(--surface))" }}
              connectNulls isAnimationActive={false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function BarsChart({ data, xKey, bars, height = 220, stacked, horizontal, valueFormat, domain }: {
  data: Record<string, unknown>[]; xKey: string; bars: LineSpec[]; height?: number; stacked?: boolean; horizontal?: boolean;
  valueFormat?: (v: number) => string; domain?: [number, number | "auto"];
}) {
  const fmt = valueFormat ?? ((v: number) => String(Math.round(v * 1000) / 1000));
  return (
    <div style={{ height }} role="img" aria-label={`Bar chart: ${bars.map((b) => b.label).join(", ")}`}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout={horizontal ? "vertical" : "horizontal"} margin={{ top: 8, right: 12, bottom: 0, left: 0 }} barCategoryGap="25%">
          <CartesianGrid stroke="rgb(var(--border))" vertical={!!horizontal} horizontal={!horizontal} strokeOpacity={0.6} />
          {horizontal ? (
            <>
              <XAxis type="number" {...axis} tickFormatter={(v) => fmt(Number(v))} />
              <YAxis type="category" dataKey={xKey} {...axis} width={130} />
            </>
          ) : (
            <>
              <XAxis dataKey={xKey} {...axis} />
              <YAxis {...axis} width={44} tickFormatter={(v) => fmt(Number(v))} allowDecimals={!!domain} domain={domain ?? [0, "auto"]} />
            </>
          )}
          <Tooltip {...tooltipStyle} cursor={{ fill: "rgb(var(--muted))", fillOpacity: 0.6 }} formatter={(v: number, n: string) => [fmt(v), n]} />
          {bars.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} iconType="square" formatter={legendText} />}
          {bars.map((b, i) => (
            <Bar key={b.key} dataKey={b.key} name={b.label} fill={b.color ?? series(i)} stackId={stacked ? "s" : undefined}
              stroke="rgb(var(--surface))" strokeWidth={stacked ? 1 : 0} radius={stacked ? 0 : horizontal ? [0, 3, 3, 0] : [3, 3, 0, 0]}
              maxBarSize={36} isAnimationActive={false} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Horizontal diverging bars for signed contributions (risk up = danger tone, down = ok tone). */
export function ContributionBars({ items }: { items: { name: string; value: number }[] }) {
  const max = Math.max(...items.map((i) => Math.abs(i.value)), 1e-9);
  return (
    <ul className="space-y-1.5" aria-label="Feature contributions">
      {items.map((it) => (
        <li key={it.name} className="grid grid-cols-[minmax(0,11rem)_1fr_4.5rem] items-center gap-2 text-xs" title={`${it.name}: ${it.value.toFixed(3)}`}>
          <span className="truncate font-mono text-subtle">{it.name}</span>
          <span className="relative h-3">
            <span className="absolute inset-y-0 left-1/2 w-px bg-border" />
            <span className={`absolute inset-y-0 rounded-sm ${it.value >= 0 ? "left-1/2 bg-danger/80" : "right-1/2 bg-ok/80"}`}
              style={{ width: `${(Math.abs(it.value) / max) * 50}%` }} />
          </span>
          <span className="text-right tabular-nums text-fg">{it.value >= 0 ? "+" : ""}{it.value.toFixed(2)}</span>
        </li>
      ))}
    </ul>
  );
}
