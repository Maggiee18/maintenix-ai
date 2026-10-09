import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { errorMessage } from "../api/client";
import {
  useAlerts, useAnomalies, useEquipment, useHealthHistory, useMaintenanceRecords, usePrediction, useRunPrediction, useSeries,
  useUpdateEquipmentStatus, useWorkOrders,
} from "../api/hooks";
import type { EquipmentDetail } from "../api/types";
import { TimeChart, tokenColor } from "../components/charts";
import { AlertList, CreateWorkOrderModal, PredictionPanel } from "../components/domain";
import {
  Badge, Card, Empty, ErrorState, HealthBadge, Loading, Modal, Notice, PageHeader, PriorityBadge, QueryState, SourceBadge, Tabs, WOStatusBadge,
} from "../components/ui";
import { useAuth } from "../lib/auth";
import { dateOnly, dateTime, label, num } from "../lib/format";

type Tab = "overview" | "sensors" | "history" | "alerts" | "maintenance";

export default function EquipmentDetailPage() {
  const id = Number(useParams().id);
  const eq = useEquipment(id);
  const [tab, setTab] = useState<Tab>("overview");
  if (eq.isLoading) return <Loading rows={6} />;
  if (eq.error || !eq.data) return <ErrorState error={eq.error} onRetry={() => eq.refetch()} />;
  const e = eq.data;
  return (
    <div>
      <div className="mb-1 text-xs text-subtle"><Link to="/equipment" className="hover:underline">Equipment</Link> / {e.code}</div>
      <PageHeader title={`${e.code} · ${e.name}`}
        subtitle={<span className="flex flex-wrap items-center gap-2">{e.equipment_type_name} · {e.location || "no location"} <HealthBadge state={e.health_state} /> <SourceBadge source={e.data_source} />
          <Badge tone={e.status === "operational" ? "ok" : "warn"}>{label(e.status)}</Badge></span>}
        actions={<Actions e={e} />} />
      {e.data_source === "simulated" && <div className="mb-4"><Notice>Readings for this equipment are <strong>simulated</strong> by the built-in generator. They do not come from a physical machine.</Notice></div>}
      <Tabs<Tab> value={tab} onChange={setTab} tabs={[
        { id: "overview", label: "Overview" }, { id: "sensors", label: "Sensor trends" }, { id: "history", label: "Health history" },
        { id: "alerts", label: `Alerts & anomalies${e.open_alerts ? ` (${e.open_alerts})` : ""}` }, { id: "maintenance", label: "Maintenance" },
      ]} />
      {tab === "overview" && <Overview e={e} />}
      {tab === "sensors" && <SensorTrends e={e} />}
      {tab === "history" && <History e={e} />}
      {tab === "alerts" && <AlertsTab e={e} />}
      {tab === "maintenance" && <MaintenanceTab e={e} />}
    </div>
  );
}

function Actions({ e }: { e: EquipmentDetail }) {
  const { can } = useAuth();
  const run = useRunPrediction();
  const status = useUpdateEquipmentStatus();
  const [wo, setWo] = useState(false);
  const [changing, setChanging] = useState(false);
  const [next, setNext] = useState(e.status);
  const [reason, setReason] = useState("");
  if (!can("admin", "engineer")) return null;
  return (
    <>
      <button className="btn-secondary" disabled={run.isPending || e.reading_count === 0} onClick={() => run.mutate(e.id)}
        title={e.reading_count === 0 ? "No readings yet" : "Run the production models on the latest readings"}>
        {run.isPending ? "Running…" : "Run prediction"}</button>
      <button className="btn-secondary" onClick={() => setChanging(true)} disabled={e.status === "decommissioned"}>Change status</button>
      <button className="btn-primary" onClick={() => setWo(true)} disabled={e.status === "decommissioned"}>Create work order</button>
      {run.error && <span className="w-full text-right text-xs text-danger">{errorMessage(run.error)}</span>}
      {wo && <CreateWorkOrderModal open onClose={() => setWo(false)} equipmentId={e.id} equipmentLabel={e.code} predictionId={e.latest_prediction?.id} />}
      <Modal open={changing} title="Change equipment status" onClose={() => setChanging(false)}
        footer={<><button className="btn-secondary" onClick={() => setChanging(false)}>Cancel</button>
          <button className="btn-primary" disabled={status.isPending || next === e.status}
            onClick={async () => { try { await status.mutateAsync({ id: e.id, status: next, reason }); setChanging(false); } catch { /* shown below */ } }}>Save</button></>}>
        <div className="space-y-3">
          <select aria-label="New status" className="input" value={next} onChange={(ev) => setNext(ev.target.value as typeof next)}>
            {["operational", "under_maintenance", "offline", "decommissioned"].map((s) => <option key={s} value={s}>{label(s)}</option>)}
          </select>
          <textarea aria-label="Reason" className="input" placeholder="Reason (recorded in the audit log)" value={reason} onChange={(ev) => setReason(ev.target.value)} />
          {next === "decommissioned" && <Notice tone="warn">Decommissioning is permanent. Readings will no longer be accepted.</Notice>}
          {status.error && <p className="text-sm text-danger">{errorMessage(status.error)}</p>}
        </div>
      </Modal>
    </>
  );
}

function Overview({ e }: { e: EquipmentDetail }) {
  const pred = usePrediction(e.latest_prediction?.id);
  const sensors = e.type_info.sensors;
  return (
    <div className="grid gap-4 xl:grid-cols-3">
      <Card title="Current assessment" className="xl:col-span-2">
        {!e.latest_prediction ? <Empty title="No prediction yet">Ingest at least 48 hourly readings, then run a prediction.</Empty> :
          <QueryState q={pred}>{(p) => <PredictionPanel p={p} />}</QueryState>}
      </Card>
      <div className="space-y-4">
        <Card title="Latest reading">
          {!e.latest_reading ? <Empty title="No readings" /> : (
            <>
              <table className="w-full"><tbody className="divide-y divide-border">
                {sensors.map((s) => {
                  const v = e.latest_reading!.values[s.name];
                  const out = v !== undefined && (v < s.normal_min || v > s.normal_max);
                  return (
                    <tr key={s.name}>
                      <td className="py-1.5 text-sm">{label(s.name)}<div className="text-2xs text-subtle">{s.description}</div></td>
                      <td className={`py-1.5 text-right text-sm tabular-nums ${out ? "font-semibold text-warn" : ""}`}>{num(v, 2)} <span className="text-2xs text-subtle">{s.unit}</span></td>
                      <td className="py-1.5 pl-2 text-right text-2xs text-subtle">normal {s.normal_min}–{s.normal_max}</td>
                    </tr>
                  );
                })}
              </tbody></table>
              <p className="mt-2 text-2xs text-subtle">{dateTime(e.latest_reading.recorded_at)} · mode {label(e.latest_reading.operating_mode)} · {num(e.latest_reading.operating_hours, 0)} operating h · {e.reading_count} readings stored</p>
            </>
          )}
        </Card>
        <Card title="Details">
          <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-sm">
            {[["Manufacturer", e.manufacturer], ["Model", e.model_number], ["Serial", e.serial_number], ["Installed", dateOnly(e.install_date)],
              ["Criticality", label(e.criticality)], ["Last maintenance", dateTime(e.last_maintenance_at)],
              ["Failure horizon", `${e.type_info.failure_horizon_hours} h`], ["RUL supported", e.type_info.rul_supported ? "Yes" : "No"]].map(([k, v]) => (
              <div key={k}><dt className="text-2xs text-subtle">{k}</dt><dd>{v || "—"}</dd></div>
            ))}
          </dl>
          <p className="mt-3 text-2xs text-subtle">{e.type_info.data_note}</p>
        </Card>
      </div>
    </div>
  );
}

function SensorTrends({ e }: { e: EquipmentDetail }) {
  const [days, setDays] = useState(7);
  const [bucket, setBucket] = useState<"hour" | "day" | "raw">("hour");
  const series = useSeries(e.id, { days, bucket });
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <select aria-label="Range" className="input !w-auto" value={days} onChange={(ev) => setDays(Number(ev.target.value))}>
          {[1, 3, 7, 14, 30].map((d) => <option key={d} value={d}>Last {d} day{d > 1 ? "s" : ""} of data</option>)}
        </select>
        <select aria-label="Aggregation" className="input !w-auto" value={bucket} onChange={(ev) => setBucket(ev.target.value as typeof bucket)}>
          <option value="raw">Raw readings</option><option value="hour">Hourly mean</option><option value="day">Daily mean</option>
        </select>
      </div>
      <QueryState q={series} rows={6} empty={(d) => (d.points.length === 0 ? <Empty title="No readings in this range" /> : false)}>
        {(d) => (
          <div className="grid gap-4 lg:grid-cols-2">
            {e.type_info.sensors.map((s) => (
              <Card key={s.name} title={`${label(s.name)} (${s.unit})`}>
                <TimeChart height={200} data={d.points.map((p) => ({ t: p.t, v: p.values[s.name] }))} lines={[{ key: "v", label: label(s.name) }]}
                  band={{ y1: s.normal_min, y2: s.normal_max, label: "normal band" }} />
              </Card>
            ))}
          </div>
        )}
      </QueryState>
    </div>
  );
}

function History({ e }: { e: EquipmentDetail }) {
  const h = useHealthHistory(e.id);
  return (
    <QueryState q={h} rows={6} empty={(d) => (d.points.length === 0 ? <Empty title="No prediction history yet" /> : false)}>
      {(d) => (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card title="Failure probability over time" className="lg:col-span-2">
            <TimeChart data={d.points.map((p) => ({ t: p.as_of, p: p.failure_probability }))} lines={[{ key: "p", label: "Failure probability" }]}
              valueFormat={(v) => `${(v * 100).toFixed(0)}%`} yDomain={[0, 1]} />
          </Card>
          <Card title="Anomaly score">
            <TimeChart data={d.points.map((p) => ({ t: p.as_of, s: p.anomaly_score }))} lines={[{ key: "s", label: "Anomaly score", color: tokenColor("watch") }]} height={200} />
          </Card>
          <Card title={`Estimated RUL (${e.equipment_type === "turbofan_engine" ? "flight cycles" : "hours"})`}>
            {e.type_info.rul_supported
              ? <TimeChart data={d.points.map((p) => ({ t: p.as_of, r: p.rul_hours }))} lines={[{ key: "r", label: e.equipment_type === "turbofan_engine" ? "RUL (cycles)" : "RUL (h)", color: tokenColor("series-3") }]} height={200} valueFormat={(v) => v.toFixed(0)} />
              : <Empty title="RUL unavailable">This equipment type has no run-to-failure training data, so remaining useful life is not estimated.</Empty>}
          </Card>
          <Card title="Maintenance events" className="lg:col-span-2" bodyClass="p-0">
            {d.maintenance.length === 0 ? <Empty title="No maintenance recorded" /> : (
              <ul className="divide-y divide-border">{d.maintenance.map((m) => (
                <li key={m.work_order_id} className="px-4 py-2 text-sm"><span className="font-medium">{label(m.action_taken)}</span> · {dateTime(m.completed_at)}
                  {m.restores_health && <Badge tone="ok">Health restored</Badge>}<div className="text-xs text-subtle">{m.summary}</div></li>))}</ul>
            )}
          </Card>
        </div>
      )}
    </QueryState>
  );
}

function AlertsTab({ e }: { e: EquipmentDetail }) {
  const alerts = useAlerts({ equipment_id: e.id, page_size: 50 });
  const anomalies = useAnomalies({ equipment_id: e.id, page_size: 20 });
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="Alerts" bodyClass="p-0">
        <QueryState q={alerts} empty={(d) => (d.total === 0 ? <Empty title="No alerts" /> : false)}>{(d) => <AlertList alerts={d.items} compact />}</QueryState>
      </Card>
      <Card title="Anomaly events" bodyClass="p-0">
        <QueryState q={anomalies} empty={(d) => (d.total === 0 ? <Empty title="No anomalies detected" /> : false)}>
          {(d) => (
            <ul className="divide-y divide-border">{d.items.map((a) => (
              <li key={a.id} className="px-4 py-2 text-sm">
                <div className="flex justify-between"><span>{dateTime(a.detected_at)}</span><span className="tabular-nums text-subtle">score {num(a.score, 3)} / {num(a.threshold, 3)}</span></div>
                <div className="text-xs text-subtle">{a.sensors.filter((s) => s.outside_limits).map((s) => `${s.sensor} z=${num(s.z_score, 1)}`).join(", ") || "multivariate deviation (no single sensor outside limits)"}</div>
              </li>))}</ul>
          )}
        </QueryState>
      </Card>
    </div>
  );
}

function MaintenanceTab({ e }: { e: EquipmentDetail }) {
  const wos = useWorkOrders({ equipment_id: e.id, page_size: 50 });
  const recs = useMaintenanceRecords(e.id);
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="Work orders" bodyClass="p-0">
        <QueryState q={wos} empty={(d) => (d.total === 0 ? <Empty title="No work orders" /> : false)}>
          {(d) => (
            <ul className="divide-y divide-border">{d.items.map((w) => (
              <li key={w.id} className="flex items-center justify-between gap-2 px-4 py-2 text-sm">
                <div><Link className="font-medium text-primary hover:underline" to={`/work-orders?open=${w.id}`}>{w.code}</Link> {w.title}
                  <div className="text-2xs text-subtle">{w.assigned_to?.full_name ?? "Unassigned"} · due {dateOnly(w.due_date)}</div></div>
                <div className="flex gap-1"><PriorityBadge priority={w.priority} /><WOStatusBadge status={w.status} /></div>
              </li>))}</ul>
          )}
        </QueryState>
      </Card>
      <Card title="Maintenance records" bodyClass="p-0">
        <QueryState q={recs} empty={(d) => (d.total === 0 ? <Empty title="No completed maintenance" /> : false)}>
          {(d) => (
            <ul className="divide-y divide-border">{d.items.map((r) => (
              <li key={r.id} className="px-4 py-2 text-sm">
                <div className="flex justify-between"><span className="font-medium">{label(r.action_taken)} · {r.work_order_code}</span><span className="text-xs text-subtle">{dateTime(r.completed_at)}</span></div>
                <div className="text-xs">{r.summary}</div>
                <div className="text-2xs text-subtle">{r.performed_by} · downtime {r.downtime_hours} h{r.parts_replaced && ` · parts: ${r.parts_replaced}`}</div>
              </li>))}</ul>
          )}
        </QueryState>
      </Card>
    </div>
  );
}
