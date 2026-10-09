import { useState } from "react";
import { api, errorMessage } from "../api/client";
import { useEquipmentTypes } from "../api/hooks";
import { Card, Field, Notice, PageHeader } from "../components/ui";
import { label } from "../lib/format";

function Download({ path, query, children }: { path: string; query: Record<string, string | undefined>; children: string }) {
  const [state, setState] = useState<{ busy: boolean; msg?: string; err?: string }>({ busy: false });
  return (
    <div>
      <button className="btn-primary" disabled={state.busy} onClick={async () => {
        setState({ busy: true });
        try { const name = await api.download(path, query); setState({ busy: false, msg: `Downloaded ${name}` }); }
        catch (e) { setState({ busy: false, err: errorMessage(e) }); }
      }}>{state.busy ? "Preparing…" : children}</button>
      {state.msg && <p className="mt-1 text-xs text-ok">{state.msg}</p>}
      {state.err && <p role="alert" className="mt-1 text-xs text-danger">{state.err}</p>}
    </div>
  );
}

export default function ReportsPage() {
  const types = useEquipmentTypes();
  const [eqType, setEqType] = useState("");
  const [eqStatus, setEqStatus] = useState("");
  const [risk, setRisk] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [woStatus, setWoStatus] = useState("");
  const iso = (d: string, endOfDay = false) => (d ? new Date(`${d}T${endOfDay ? "23:59:59" : "00:00:00"}Z`).toISOString() : undefined);

  return (
    <div>
      <PageHeader title="Reports" subtitle="CSV exports generated from the database at download time" />
      <div className="mb-4"><Notice>Exports are audited. Text cells that a spreadsheet could execute as a formula are prefixed with an apostrophe.</Notice></div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Equipment and health">
          <div className="space-y-3">
            <Field label="Equipment type"><select className="input" value={eqType} onChange={(e) => setEqType(e.target.value)}>
              <option value="">All</option>{types.data?.map((t) => <option key={t.key} value={t.key}>{t.display_name}</option>)}</select></Field>
            <Field label="Status"><select className="input" value={eqStatus} onChange={(e) => setEqStatus(e.target.value)}>
              <option value="">All</option>{["operational", "under_maintenance", "offline", "decommissioned"].map((s) => <option key={s} value={s}>{label(s)}</option>)}</select></Field>
            <Download path="/reports/equipment.csv" query={{ equipment_type: eqType || undefined, status: eqStatus || undefined }}>Export equipment CSV</Download>
          </div>
        </Card>
        <Card title="Predictions">
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <Field label="From (UTC)"><input type="date" className="input" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
              <Field label="To (UTC)"><input type="date" className="input" value={end} onChange={(e) => setEnd(e.target.value)} /></Field>
            </div>
            <Field label="Risk level"><select className="input" value={risk} onChange={(e) => setRisk(e.target.value)}>
              <option value="">All</option><option value="high">High</option><option value="elevated">Elevated</option><option value="low">Low</option></select></Field>
            <Download path="/reports/predictions.csv" query={{ start: iso(start), end: iso(end, true), risk_level: risk || undefined }}>Export predictions CSV</Download>
          </div>
        </Card>
        <Card title="Maintenance history">
          <div className="space-y-3">
            <Field label="Work-order status"><select className="input" value={woStatus} onChange={(e) => setWoStatus(e.target.value)}>
              <option value="">All</option>{["open", "assigned", "in_progress", "completed", "cancelled"].map((s) => <option key={s} value={s}>{label(s)}</option>)}</select></Field>
            <Download path="/reports/maintenance.csv" query={{ status: woStatus || undefined }}>Export maintenance CSV</Download>
          </div>
        </Card>
      </div>
    </div>
  );
}
