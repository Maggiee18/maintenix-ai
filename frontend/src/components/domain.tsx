import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { errorMessage } from "../api/client";
import { useAlertAction, useAssignableUsers, useCreateWorkOrder } from "../api/hooks";
import type { Alert, PredictionDetail } from "../api/types";
import { useAuth } from "../lib/auth";
import { dateTime, label, num, pct, prob, rulText } from "../lib/format";
import { ContributionBars } from "./charts";
import { Badge, Field, Modal, Notice, RiskBadge } from "./ui";

/** Full explanation of one prediction: risk, anomaly, RUL, drivers and limitations. */
export function PredictionPanel({ p }: { p: PredictionDetail }) {
  if (p.status !== "ok") {
    return <Notice tone="warn">{p.status === "no_model" ? "No production model is registered for this equipment type yet." : `Not enough readings (${p.readings_used}) to compute features. At least 48 consecutive readings are needed.`}</Notice>;
  }
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-md border border-border p-3">
          <div className="text-2xs font-medium text-subtle">Failure probability (next horizon)</div>
          <div className="mt-1 flex items-baseline gap-2"><span className="text-2xl font-semibold tabular-nums">{prob(p.failure_probability)}</span><RiskBadge level={p.risk_level} /></div>
          <div className="text-2xs text-subtle">Alert threshold {pct(p.failure_threshold)} · calibrated on validation data</div>
        </div>
        <div className="rounded-md border border-border p-3">
          <div className="text-2xs font-medium text-subtle">Anomaly score</div>
          <div className="mt-1 flex items-baseline gap-2"><span className="text-2xl font-semibold tabular-nums">{num(p.anomaly_score, 3)}</span>
            {p.is_anomaly ? <Badge tone="watch">Anomalous</Badge> : <Badge tone="ok">Normal</Badge>}</div>
          <div className="text-2xs text-subtle">Threshold {num(p.anomaly_threshold, 3)}. An anomaly is not a confirmed failure.</div>
        </div>
        <div className="rounded-md border border-border p-3">
          <div className="text-2xs font-medium text-subtle">Remaining useful life</div>
          <div className="mt-1 text-2xl font-semibold tabular-nums">{rulText(p.rul_hours, p.rul_status, p.rul_cap_hours, p.rul_unit)}</div>
          <div className="text-2xs text-subtle">{p.rul_status === "ok" ? `Typical error ±${num(p.rul_typical_error_hours, 0)} ${p.rul_unit} on held-out units` : p.rul_status === "unavailable" ? "No run-to-failure data for this type" : "—"}</div>
        </div>
      </div>
      {p.recommendation && <Notice tone={p.risk_level === "high" ? "danger" : p.risk_level === "elevated" ? "warn" : "watch"}><strong>Advisory:</strong> {p.recommendation}</Notice>}
      {p.explanation && (
        <div className="grid gap-4 lg:grid-cols-2">
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-subtle">Contribution by sensor</h3>
            <ContributionBars items={p.explanation.sensor_contributions.map((s) => ({ name: s.sensor, value: s.contribution }))} />
          </div>
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-subtle">Top features</h3>
            <ContributionBars items={p.explanation.top_features.map((f) => ({ name: f.feature, value: f.contribution }))} />
          </div>
          <p className="text-2xs text-subtle lg:col-span-2">
            Method: {p.explanation.method.replace("_", " ")} ({p.explanation.output_space}). Positive values push risk up, negative values push it down. {p.explanation.limitations}
          </p>
        </div>
      )}
      {p.sensor_deviations && p.sensor_deviations.length > 0 && (
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-subtle">Latest reading vs healthy baseline (same operating mode)</h3>
          <div className="overflow-x-auto"><table className="w-full">
            <thead><tr><th className="th">Sensor</th><th className="th">Value</th><th className="th">Baseline</th><th className="th">Control limits</th><th className="th">z-score</th></tr></thead>
            <tbody className="divide-y divide-border">
              {p.sensor_deviations.map((d) => (
                <tr key={d.sensor}>
                  <td className="td">{label(d.sensor)}</td><td className="td tabular-nums">{num(d.value, 2)}</td>
                  <td className="td tabular-nums text-subtle">{num(d.baseline_mean, 2)}</td>
                  <td className="td tabular-nums text-subtle">{num(d.lower_limit, 2)} – {num(d.upper_limit, 2)}</td>
                  <td className="td">{d.outside_limits ? <Badge tone="warn">{num(d.z_score, 1)}</Badge> : <span className="tabular-nums">{num(d.z_score, 1)}</span>}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        </div>
      )}
      <p className="text-2xs text-subtle">Computed {dateTime(p.created_at)} from {p.readings_used} readings up to {dateTime(p.as_of)} · trigger: {p.triggered_by}</p>
    </div>
  );
}

export function CreateWorkOrderModal({ open, onClose, equipmentId, equipmentLabel, alertId, predictionId, defaultTitle, defaultPriority }: {
  open: boolean; onClose: () => void; equipmentId: number; equipmentLabel: string; alertId?: number; predictionId?: number;
  defaultTitle?: string; defaultPriority?: string;
}) {
  const users = useAssignableUsers();
  const create = useCreateWorkOrder();
  const [title, setTitle] = useState(defaultTitle ?? "");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState(defaultPriority ?? "medium");
  const [due, setDue] = useState("");
  const [assignee, setAssignee] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (title.trim().length < 3) return setError("Title must have at least 3 characters.");
    setError(null);
    try {
      await create.mutateAsync({ equipment_id: equipmentId, title, description, priority, due_date: due || null,
        alert_id: alertId ?? null, prediction_id: predictionId ?? null, assigned_to_id: assignee ? Number(assignee) : null });
      onClose();
    } catch (err) { setError(errorMessage(err)); }
  }
  return (
    <Modal open={open} title={`New work order · ${equipmentLabel}`} onClose={onClose}
      footer={<><button className="btn-secondary" onClick={onClose}>Cancel</button><button className="btn-primary" form="wo-create" disabled={create.isPending}>Create work order</button></>}>
      <form id="wo-create" onSubmit={submit} className="space-y-3" noValidate>
        {alertId && <Notice>Linked to alert #{alertId}. Creating the work order acknowledges the alert.</Notice>}
        <Field label="Title"><input className="input" value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
        <Field label="Description"><textarea className="input min-h-20" value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
        <div className="grid grid-cols-3 gap-3">
          <Field label="Priority"><select className="input" value={priority} onChange={(e) => setPriority(e.target.value)}>
            {["low", "medium", "high", "critical"].map((p) => <option key={p} value={p}>{label(p)}</option>)}</select></Field>
          <Field label="Due date"><input type="date" className="input" value={due} min={new Date().toISOString().slice(0, 10)} onChange={(e) => setDue(e.target.value)} /></Field>
          <Field label="Assign to"><select className="input" value={assignee} onChange={(e) => setAssignee(e.target.value)}>
            <option value="">Unassigned</option>{users.data?.map((u) => <option key={u.id} value={u.id}>{u.full_name} ({u.role})</option>)}</select></Field>
        </div>
        {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      </form>
    </Modal>
  );
}

export function AlertList({ alerts, compact }: { alerts: Alert[]; compact?: boolean }) {
  const { can } = useAuth();
  const act = useAlertAction();
  const [creating, setCreating] = useState<Alert | null>(null);
  return (
    <>
      <ul className="divide-y divide-border">
        {alerts.map((a) => (
          <li key={a.id} className="flex flex-wrap items-start justify-between gap-2 px-4 py-3">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={a.severity === "critical" ? "danger" : "warn"}>{label(a.severity)}</Badge>
                <span className="text-sm font-medium">{a.title}</span>
                {!compact && <Link className="text-sm text-primary hover:underline" to={`/equipment/${a.equipment_id}`}>{a.equipment_code}</Link>}
                <Badge tone={a.status === "open" ? "primary" : a.status === "acknowledged" ? "watch" : "neutral"}>{label(a.status)}</Badge>
              </div>
              <p className="mt-0.5 text-xs text-subtle">{a.message}</p>
              <p className="text-2xs text-subtle">First {dateTime(a.first_seen_at)} · last {dateTime(a.last_seen_at)} · {a.occurrence_count} occurrence{a.occurrence_count > 1 ? "s" : ""}
                {a.work_order_id && <> · <Link className="text-primary hover:underline" to={`/work-orders?open=${a.work_order_id}`}>work order</Link></>}</p>
            </div>
            {can("admin", "engineer") && a.status !== "resolved" && (
              <div className="flex gap-1.5">
                {!a.work_order_id && <button className="btn-primary !py-1 text-xs" onClick={() => setCreating(a)}>Create work order</button>}
                {a.status === "open" && <button className="btn-secondary !py-1 text-xs" disabled={act.isPending} onClick={() => act.mutate({ id: a.id, action: "acknowledge" })}>Acknowledge</button>}
                <button className="btn-ghost !py-1 text-xs" disabled={act.isPending} onClick={() => act.mutate({ id: a.id, action: "resolve", note: "Reviewed, no action required" })}>Resolve</button>
              </div>
            )}
          </li>
        ))}
      </ul>
      {creating && <CreateWorkOrderModal open onClose={() => setCreating(null)} equipmentId={creating.equipment_id} equipmentLabel={creating.equipment_code}
        alertId={creating.id} predictionId={creating.prediction_id ?? undefined} defaultTitle={`${creating.title}: inspect ${creating.equipment_code}`}
        defaultPriority={creating.severity === "critical" ? "high" : "medium"} />}
    </>
  );
}
