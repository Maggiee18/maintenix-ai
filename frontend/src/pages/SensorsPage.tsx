import { useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, errorMessage } from "../api/client";
import { useEquipmentList, useSeries, useUploadCsv } from "../api/hooks";
import type { IngestReport } from "../api/types";
import { TimeChart } from "../components/charts";
import { Badge, Card, Empty, Notice, PageHeader, QueryState, SourceBadge } from "../components/ui";
import { useAuth } from "../lib/auth";
import { label, num, relative } from "../lib/format";

interface LatestRow { equipment_id: number; equipment_code: string; equipment_type: string; data_source: string; reading: { recorded_at: string; operating_mode: string; values: Record<string, number> } | null }

export default function SensorsPage() {
  const { can } = useAuth();
  const equipment = useEquipmentList({ page_size: 200, sort: "code" });
  const latest = useQuery({ queryKey: ["latest"], queryFn: () => api.get<LatestRow[]>("/sensors/latest"), refetchInterval: 30_000 });
  const [eqId, setEqId] = useState<number | undefined>();
  const selected = equipment.data?.items.find((e) => e.id === eqId) ?? equipment.data?.items[0];
  const [sensor, setSensor] = useState<string>("");
  const [days, setDays] = useState(3);
  const types = useQuery({ queryKey: ["equipment-types"], queryFn: () => api.get<{ key: string; sensors: { name: string; unit: string; normal_min: number; normal_max: number }[] }[]>("/equipment-types") });
  const sensorDefs = types.data?.find((t) => t.key === selected?.equipment_type)?.sensors ?? [];
  const def = sensorDefs.find((s) => s.name === sensor) ?? sensorDefs[0];
  const series = useSeries(selected?.id, { days, bucket: "raw", sensors: def ? [def.name] : undefined });
  const data = useMemo(() => (series.data?.points ?? []).map((p) => ({ t: p.t, v: def ? p.values[def.name] : null })), [series.data, def]);

  return (
    <div>
      <PageHeader title="Sensor monitoring" subtitle="Raw readings as stored, latest values per equipment, and data import" />
      <div className="grid gap-4 xl:grid-cols-3">
        <Card title="Sensor history" className="xl:col-span-2"
          actions={
            <div className="flex flex-wrap gap-2">
              <select aria-label="Equipment" className="input !w-auto !py-1 text-xs" value={selected?.id ?? ""} onChange={(e) => { setEqId(Number(e.target.value)); setSensor(""); }}>
                {equipment.data?.items.map((e) => <option key={e.id} value={e.id}>{e.code} · {e.name}</option>)}
              </select>
              <select aria-label="Sensor" className="input !w-auto !py-1 text-xs" value={def?.name ?? ""} onChange={(e) => setSensor(e.target.value)}>
                {sensorDefs.map((s) => <option key={s.name} value={s.name}>{label(s.name)}</option>)}
              </select>
              <select aria-label="Range" className="input !w-auto !py-1 text-xs" value={days} onChange={(e) => setDays(Number(e.target.value))}>
                {[1, 3, 7, 14].map((d) => <option key={d} value={d}>{d} day{d > 1 ? "s" : ""}</option>)}
              </select>
            </div>
          }>
          {selected && <div className="mb-2 flex items-center gap-2 text-xs text-subtle"><SourceBadge source={selected.data_source} /> Each point is one stored reading (no smoothing).</div>}
          <QueryState q={series} rows={6}>
            {() => <TimeChart data={data} lines={[{ key: "v", label: def ? `${label(def.name)} (${def.unit})` : "value" }]} yLabel={def?.unit} height={300}
              band={def ? { y1: def.normal_min, y2: def.normal_max, label: "normal band" } : undefined} />}
          </QueryState>
        </Card>
        {can("admin", "engineer") ? <CsvUpload /> : <Card title="Import data"><p className="text-sm text-subtle">Engineers and administrators can import CSV readings.</p></Card>}
        <Card title="Latest readings" className="xl:col-span-3" bodyClass="p-0">
          <QueryState q={latest} empty={(d) => (d.length === 0 ? <Empty title="No equipment" /> : false)}>
            {(rows) => (
              <div className="overflow-x-auto"><table className="w-full">
                <thead className="border-b border-border"><tr><th className="th">Equipment</th><th className="th">Received</th><th className="th">Mode</th><th className="th">Values</th><th className="th">Source</th></tr></thead>
                <tbody className="divide-y divide-border">{rows.map((r) => (
                  <tr key={r.equipment_id}>
                    <td className="td"><Link className="font-medium text-primary hover:underline" to={`/equipment/${r.equipment_id}`}>{r.equipment_code}</Link></td>
                    <td className="td text-xs text-subtle">{relative(r.reading?.recorded_at)}</td>
                    <td className="td text-xs">{label(r.reading?.operating_mode)}</td>
                    <td className="td text-xs">{r.reading ? Object.entries(r.reading.values).map(([k, v]) => <span key={k} className="mr-3 whitespace-nowrap"><span className="text-subtle">{k}</span> <span className="tabular-nums">{num(v, 2)}</span></span>) : "No readings"}</td>
                    <td className="td"><SourceBadge source={r.data_source} /></td>
                  </tr>))}</tbody>
              </table></div>
            )}
          </QueryState>
        </Card>
      </div>
    </div>
  );
}

function CsvUpload() {
  const upload = useUploadCsv();
  const file = useRef<HTMLInputElement>(null);
  const [report, setReport] = useState<IngestReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [runInference, setRunInference] = useState(true);
  async function submit() {
    const f = file.current?.files?.[0];
    setError(null);
    setReport(null);
    if (!f) return setError("Choose a CSV file first.");
    if (!f.name.toLowerCase().endsWith(".csv")) return setError("Only .csv files are accepted.");
    if (f.size > 5 * 1024 * 1024) return setError("File is larger than 5 MB.");
    const form = new FormData();
    form.append("file", f);
    form.append("run_inference", String(runInference));
    try { setReport(await upload.mutateAsync(form)); } catch (e) { setError(errorMessage(e)); }
  }
  return (
    <Card title="Import CSV readings">
      <p className="mb-3 text-xs text-subtle">Columns: <code>equipment_code, timestamp, operating_mode, operating_hours</code> and the sensor names of each equipment type. Timestamps without a timezone are treated as UTC. Every row is validated; invalid rows are reported and skipped, duplicates are ignored.</p>
      <input ref={file} type="file" accept=".csv,text/csv" aria-label="CSV file" className="block w-full text-sm file:mr-3 file:rounded-md file:border-0 file:bg-muted file:px-3 file:py-1.5 file:text-sm" />
      <label className="mt-2 flex items-center gap-2 text-sm"><input type="checkbox" checked={runInference} onChange={(e) => setRunInference(e.target.checked)} /> Run predictions after import</label>
      <button className="btn-primary mt-3" onClick={submit} disabled={upload.isPending}>{upload.isPending ? "Uploading…" : "Upload and validate"}</button>
      {error && <p role="alert" className="mt-2 text-sm text-danger">{error}</p>}
      {report && (
        <div className="mt-3 space-y-2 text-sm">
          <Notice tone={report.rejected_rows ? "warn" : "ok"}>
            {report.accepted_rows} stored · {report.rejected_rows} rejected · {report.already_stored} already stored · {report.total_rows} total
          </Notice>
          {report.errors.length > 0 && (
            <ul className="max-h-40 overflow-y-auto text-xs">{report.errors.slice(0, 50).map((e, i) => (
              <li key={i}><Badge tone="danger">{e.code}</Badge> row {e.row === null ? "–" : e.row + 2}{e.column ? ` · ${e.column}` : ""}: {e.message}</li>))}</ul>
          )}
          {report.warnings.map((w, i) => <p key={i} className="text-xs text-warn">{w.message}</p>)}
        </div>
      )}
    </Card>
  );
}
