import { useState, type FormEvent } from "react";
import { errorMessage } from "../api/client";
import { useAudit, useCreateUser, useThresholds, useUpdateThreshold, useUpdateUser, useUsers } from "../api/hooks";
import type { Role, Threshold } from "../api/types";
import { Badge, Card, Empty, Field, Modal, PageHeader, Pagination, QueryState, Tabs } from "../components/ui";
import { useAuth } from "../lib/auth";
import { dateTime, num, pct, relative } from "../lib/format";

type Tab = "users" | "thresholds" | "audit";
const ROLES: Role[] = ["admin", "engineer", "technician", "viewer"];

export default function AdminPage() {
  const [tab, setTab] = useState<Tab>("users");
  return (
    <div>
      <PageHeader title="Administration" subtitle="Users and roles, alert thresholds, and the audit log" />
      <Tabs<Tab> value={tab} onChange={setTab} tabs={[{ id: "users", label: "Users" }, { id: "thresholds", label: "Alert thresholds" }, { id: "audit", label: "Audit log" }]} />
      {tab === "users" && <Users />}
      {tab === "thresholds" && <Thresholds />}
      {tab === "audit" && <Audit />}
    </div>
  );
}

function Users() {
  const users = useUsers();
  const update = useUpdateUser();
  const { user: me } = useAuth();
  const [creating, setCreating] = useState(false);
  return (
    <Card title="Users" bodyClass="p-0" actions={<button className="btn-primary !py-1 text-xs" onClick={() => setCreating(true)}>Add user</button>}>
      {update.error && <p className="px-4 pt-3 text-sm text-danger">{errorMessage(update.error)}</p>}
      <QueryState q={users}>
        {(d) => (
          <div className="overflow-x-auto"><table className="w-full">
            <thead className="border-b border-border"><tr><th className="th">Name</th><th className="th">Email</th><th className="th">Role</th><th className="th">Status</th><th className="th">Last login</th><th className="th" /></tr></thead>
            <tbody className="divide-y divide-border">{d.items.map((u) => (
              <tr key={u.id}>
                <td className="td font-medium">{u.full_name}</td><td className="td text-xs">{u.email}</td>
                <td className="td"><select aria-label={`Role for ${u.email}`} className="input !w-auto !py-0.5 text-xs" value={u.role} disabled={u.id === me?.id || update.isPending}
                  onChange={(e) => update.mutate({ id: u.id, role: e.target.value })}>{ROLES.map((r) => <option key={r} value={r}>{r}</option>)}</select></td>
                <td className="td">{u.is_active ? <Badge tone="ok">Active</Badge> : <Badge>Inactive</Badge>}</td>
                <td className="td text-xs text-subtle">{relative(u.last_login_at)}</td>
                <td className="td text-right">{u.id !== me?.id && <button className="btn-ghost !py-0.5 text-xs" disabled={update.isPending}
                  onClick={() => update.mutate({ id: u.id, is_active: !u.is_active })}>{u.is_active ? "Deactivate" : "Reactivate"}</button>}</td>
              </tr>))}</tbody>
          </table></div>
        )}
      </QueryState>
      {creating && <CreateUser onClose={() => setCreating(false)} />}
    </Card>
  );
}

function CreateUser({ onClose }: { onClose: () => void }) {
  const create = useCreateUser();
  const [f, setF] = useState({ email: "", full_name: "", role: "technician", password: "" });
  const [err, setErr] = useState<string | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (f.password.length < 10 || !/\d/.test(f.password) || f.password.toLowerCase() === f.password) return setErr("Password needs 10+ characters, mixed case and a digit.");
    try { await create.mutateAsync(f); onClose(); } catch (e2) { setErr(errorMessage(e2)); }
  }
  return (
    <Modal open title="Add user" onClose={onClose}
      footer={<><button className="btn-secondary" onClick={onClose}>Cancel</button><button className="btn-primary" form="new-user" disabled={create.isPending}>Create</button></>}>
      <form id="new-user" onSubmit={submit} className="space-y-3" noValidate>
        <Field label="Full name"><input className="input" value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} /></Field>
        <Field label="Email"><input className="input" type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
        <Field label="Role"><select className="input" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>{ROLES.map((r) => <option key={r}>{r}</option>)}</select></Field>
        <Field label="Initial password" hint="Share it securely; the user cannot change it yet (admin reset only)."><input className="input" type="password" autoComplete="new-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></Field>
        {err && <p role="alert" className="text-sm text-danger">{err}</p>}
      </form>
    </Modal>
  );
}

function Thresholds() {
  const th = useThresholds();
  return (
    <div className="space-y-4">
      <p className="text-sm text-subtle">Risk thresholds turn calibrated probabilities into alert levels. The default warning level is the model's validation-chosen threshold (maximum F2). Raising it reduces false alarms but misses more failures.</p>
      <QueryState q={th} empty={(d) => (d.length === 0 ? <Empty title="No thresholds" /> : false)}>
        {(rows) => <div className="grid gap-4 lg:grid-cols-2">{rows.map((t) => <ThresholdCard key={t.equipment_type} t={t} />)}</div>}
      </QueryState>
    </div>
  );
}

function ThresholdCard({ t }: { t: Threshold }) {
  const upd = useUpdateThreshold();
  const [f, setF] = useState({ risk_warning: String(t.risk_warning), risk_critical: String(t.risk_critical), cooldown_minutes: String(t.cooldown_minutes),
    anomaly_alerts_enabled: t.anomaly_alerts_enabled, anomaly_score_override: t.anomaly_score_override === null ? "" : String(t.anomaly_score_override) });
  const [msg, setMsg] = useState<string | null>(null);
  async function save(e: FormEvent) {
    e.preventDefault();
    setMsg(null);
    const w = Number(f.risk_warning), c = Number(f.risk_critical);
    if (!(w > 0 && w < c && c <= 1)) return setMsg("Need 0 < warning < critical ≤ 1.");
    try {
      await upd.mutateAsync({ key: t.equipment_type, risk_warning: w, risk_critical: c, cooldown_minutes: Number(f.cooldown_minutes),
        anomaly_alerts_enabled: f.anomaly_alerts_enabled, anomaly_score_override: f.anomaly_score_override === "" ? null : Number(f.anomaly_score_override) });
      setMsg("Saved");
    } catch (e2) { setMsg(errorMessage(e2)); }
  }
  return (
    <Card title={t.equipment_type_name}>
      <form onSubmit={save} className="grid grid-cols-2 gap-3" noValidate>
        <Field label="Warning (elevated) at" hint={t.model_threshold !== null ? `Model threshold ${pct(t.model_threshold, 1)}` : "No production model"}>
          <input className="input" inputMode="decimal" value={f.risk_warning} onChange={(e) => setF({ ...f, risk_warning: e.target.value })} /></Field>
        <Field label="Critical (high) at"><input className="input" inputMode="decimal" value={f.risk_critical} onChange={(e) => setF({ ...f, risk_critical: e.target.value })} /></Field>
        <Field label="Alert cooldown (minutes)" hint="Suppress repeat alerts of the same severity after resolution"><input className="input" inputMode="numeric" value={f.cooldown_minutes} onChange={(e) => setF({ ...f, cooldown_minutes: e.target.value })} /></Field>
        <Field label="Anomaly score override" hint="Blank = use the model's threshold"><input className="input" inputMode="decimal" value={f.anomaly_score_override} onChange={(e) => setF({ ...f, anomaly_score_override: e.target.value })} /></Field>
        <label className="col-span-2 flex items-center gap-2 text-sm"><input type="checkbox" checked={f.anomaly_alerts_enabled} onChange={(e) => setF({ ...f, anomaly_alerts_enabled: e.target.checked })} /> Raise alerts for anomalies</label>
        <div className="col-span-2 flex items-center gap-3"><button className="btn-primary" disabled={upd.isPending}>Save</button>
          {msg && <span className={`text-sm ${msg === "Saved" ? "text-ok" : "text-danger"}`}>{msg}</span>}
          <span className="ml-auto text-2xs text-subtle">Updated {dateTime(t.updated_at)}</span></div>
      </form>
    </Card>
  );
}

function Audit() {
  const [page, setPage] = useState(1);
  const [action, setAction] = useState("");
  const audit = useAudit({ page, page_size: 50, action: action || undefined });
  return (
    <Card title="Audit log" bodyClass="p-0" actions={<input aria-label="Filter by action" className="input !w-48 !py-1 text-xs" placeholder="action prefix, e.g. work_order" value={action} onChange={(e) => { setAction(e.target.value); setPage(1); }} />}>
      <QueryState q={audit} rows={8} empty={(d) => (d.total === 0 ? <Empty title="No events" /> : false)}>
        {(d) => (
          <>
            <div className="overflow-x-auto"><table className="w-full">
              <thead className="border-b border-border"><tr><th className="th">Time</th><th className="th">Actor</th><th className="th">Action</th><th className="th">Entity</th><th className="th">Details</th><th className="th">IP</th></tr></thead>
              <tbody className="divide-y divide-border">{d.items.map((a) => (
                <tr key={a.id}>
                  <td className="td whitespace-nowrap text-xs">{dateTime(a.created_at)}</td><td className="td text-xs">{a.actor ?? "system"}</td>
                  <td className="td"><code className="text-xs">{a.action}</code></td><td className="td text-xs">{a.entity_type} {a.entity_id}</td>
                  <td className="td max-w-md truncate font-mono text-2xs text-subtle" title={JSON.stringify(a.details)}>{JSON.stringify(a.details)}</td>
                  <td className="td text-xs text-subtle">{a.ip_address ?? "—"}</td>
                </tr>))}</tbody>
            </table></div>
            <Pagination page={d.page} pageSize={d.page_size} total={d.total} onPage={setPage} />
          </>
        )}
      </QueryState>
      <p className="px-4 py-2 text-2xs text-subtle">Passwords and tokens are never written to the audit log. {num(d0(audit.data?.total))} events.</p>
    </Card>
  );
}
const d0 = (n: number | undefined) => n ?? 0;
