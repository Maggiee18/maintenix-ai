import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { errorMessage } from "../api/client";
import { useCreateEquipment, useEquipmentList, useEquipmentTypes } from "../api/hooks";
import { Badge, Empty, Field, HealthBadge, Modal, PageHeader, Pagination, ProbabilityBar, QueryState, SourceBadge } from "../components/ui";
import { useAuth } from "../lib/auth";
import { label, relative, rulText } from "../lib/format";

export default function EquipmentListPage() {
  const [params, setParams] = useSearchParams();
  const { can } = useAuth();
  const [creating, setCreating] = useState(false);
  const page = Number(params.get("page") ?? 1);
  const q = {
    page, page_size: 20, search: params.get("search") ?? undefined, equipment_type: params.get("type") ?? undefined,
    status: params.get("status") ?? undefined, health: params.get("health") ?? undefined, sort: params.get("sort") ?? "code",
  };
  const list = useEquipmentList(q);
  const types = useEquipmentTypes();
  const set = (k: string, v: string) => { const p = new URLSearchParams(params); if (v) p.set(k, v); else p.delete(k); if (k !== "page") p.delete("page"); setParams(p); };

  return (
    <div>
      <PageHeader title="Equipment inventory" subtitle="Registered equipment with the latest model assessment"
        actions={can("admin", "engineer") && <button className="btn-primary" onClick={() => setCreating(true)}>Register equipment</button>} />
      <div className="card">
        <div className="flex flex-wrap gap-2 border-b border-border p-3">
          <input aria-label="Search equipment" placeholder="Search code, name or location" className="input max-w-xs" defaultValue={q.search}
            onKeyDown={(e) => e.key === "Enter" && set("search", (e.target as HTMLInputElement).value)} onBlur={(e) => set("search", e.target.value)} />
          <select aria-label="Type" className="input !w-auto" value={q.equipment_type ?? ""} onChange={(e) => set("type", e.target.value)}>
            <option value="">All types</option>
            {types.data?.map((t) => <option key={t.key} value={t.key}>{t.display_name}</option>)}
          </select>
          <select aria-label="Health" className="input !w-auto" value={q.health ?? ""} onChange={(e) => set("health", e.target.value)}>
            <option value="">Any health</option>
            {["healthy", "watch", "at_risk", "critical", "unknown"].map((h) => <option key={h} value={h}>{label(h)}</option>)}
          </select>
          <select aria-label="Status" className="input !w-auto" value={q.status ?? ""} onChange={(e) => set("status", e.target.value)}>
            <option value="">Any status</option>
            {["operational", "under_maintenance", "offline", "decommissioned"].map((h) => <option key={h} value={h}>{label(h)}</option>)}
          </select>
          <select aria-label="Sort" className="input !w-auto" value={q.sort} onChange={(e) => set("sort", e.target.value)}>
            <option value="code">Sort: code</option><option value="name">Sort: name</option><option value="risk">Sort: highest risk</option><option value="updated">Sort: recently updated</option>
          </select>
        </div>
        <QueryState q={list} rows={6} empty={(d) => (d.total === 0 ? <Empty title="No equipment matches">Adjust the filters or register new equipment.</Empty> : false)}>
          {(d) => (
            <>
              <div className="overflow-x-auto"><table className="w-full">
                <thead className="border-b border-border"><tr>
                  <th className="th">Code</th><th className="th">Type</th><th className="th">Location</th><th className="th">Status</th>
                  <th className="th">Health</th><th className="th">Failure risk</th><th className="th">RUL</th><th className="th">Data</th><th className="th">Assessed</th>
                </tr></thead>
                <tbody className="divide-y divide-border">
                  {d.items.map((e) => (
                    <tr key={e.id} className="hover:bg-muted/50">
                      <td className="td"><Link to={`/equipment/${e.id}`} className="font-medium text-primary hover:underline">{e.code}</Link><div className="text-2xs text-subtle">{e.name}</div></td>
                      <td className="td text-xs">{e.equipment_type_name}</td>
                      <td className="td text-xs text-subtle">{e.location || "—"}</td>
                      <td className="td"><Badge tone={e.status === "operational" ? "ok" : e.status === "under_maintenance" ? "warn" : "neutral"}>{label(e.status)}</Badge></td>
                      <td className="td"><HealthBadge state={e.health_state} />{e.open_alerts > 0 && <span className="ml-1 text-2xs text-warn">{e.open_alerts} alert{e.open_alerts > 1 ? "s" : ""}</span>}</td>
                      <td className="td"><ProbabilityBar value={e.latest_prediction?.failure_probability ?? null} level={e.latest_prediction?.risk_level} /></td>
                      <td className="td text-xs">{e.latest_prediction ? rulText(e.latest_prediction.rul_hours, e.latest_prediction.rul_status, null, e.latest_prediction.rul_unit) : "—"}</td>
                      <td className="td"><SourceBadge source={e.data_source} /></td>
                      <td className="td text-xs text-subtle">{relative(e.latest_prediction?.as_of)}</td>
                    </tr>
                  ))}
                </tbody>
              </table></div>
              <Pagination page={d.page} pageSize={d.page_size} total={d.total} onPage={(p) => set("page", String(p))} />
            </>
          )}
        </QueryState>
      </div>
      <CreateEquipmentModal open={creating} onClose={() => setCreating(false)} />
    </div>
  );
}

function CreateEquipmentModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const types = useEquipmentTypes();
  const create = useCreateEquipment();
  const [form, setForm] = useState({ code: "", name: "", equipment_type: "centrifugal_pump", location: "", manufacturer: "", serial_number: "", criticality: "medium" });
  const [err, setErr] = useState<Record<string, string>>({});
  const upd = (k: string) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    const v: Record<string, string> = {};
    if (!/^[A-Za-z0-9][A-Za-z0-9_-]{1,31}$/.test(form.code)) v.code = "2–32 letters, digits, - or _";
    if (form.name.trim().length < 2) v.name = "Name is required";
    setErr(v);
    if (Object.keys(v).length) return;
    try {
      await create.mutateAsync(form);
      setForm({ ...form, code: "", name: "" });
      onClose();
    } catch (e2) {
      setErr({ form: errorMessage(e2) });
    }
  }
  const selected = types.data?.find((t) => t.key === form.equipment_type);
  return (
    <Modal open={open} title="Register equipment" onClose={onClose}
      footer={<><button className="btn-secondary" onClick={onClose}>Cancel</button><button className="btn-primary" form="create-eq" disabled={create.isPending}>Register</button></>}>
      <form id="create-eq" onSubmit={submit} className="grid grid-cols-2 gap-3" noValidate>
        <Field label="Code" error={err.code}><input className="input" value={form.code} onChange={upd("code")} placeholder="PMP-201" /></Field>
        <Field label="Name" error={err.name}><input className="input" value={form.name} onChange={upd("name")} /></Field>
        <Field label="Equipment type" hint={selected?.rul_supported ? "RUL estimation supported" : "RUL not available for this type"}>
          <select className="input" value={form.equipment_type} onChange={upd("equipment_type")}>
            {types.data?.map((t) => <option key={t.key} value={t.key}>{t.display_name}</option>)}
          </select>
        </Field>
        <Field label="Criticality"><select className="input" value={form.criticality} onChange={upd("criticality")}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option></select></Field>
        <Field label="Location"><input className="input" value={form.location} onChange={upd("location")} /></Field>
        <Field label="Manufacturer"><input className="input" value={form.manufacturer} onChange={upd("manufacturer")} /></Field>
        <Field label="Serial number"><input className="input" value={form.serial_number} onChange={upd("serial_number")} /></Field>
        {selected && <p className="col-span-2 text-xs text-subtle">Sensors: {selected.sensors.map((s) => `${s.name} (${s.unit})`).join(", ")}</p>}
        {err.form && <p role="alert" className="col-span-2 text-sm text-danger">{err.form}</p>}
      </form>
    </Modal>
  );
}
