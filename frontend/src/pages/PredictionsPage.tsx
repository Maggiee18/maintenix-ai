import { useState } from "react";
import { Link } from "react-router-dom";
import { errorMessage } from "../api/client";
import { useAlerts, usePrediction, usePredictions, useRunFleet } from "../api/hooks";
import { AlertList, PredictionPanel } from "../components/domain";
import { Badge, Card, Empty, Modal, Notice, PageHeader, Pagination, ProbabilityBar, QueryState, RiskBadge } from "../components/ui";
import { useAuth } from "../lib/auth";
import { dateTime, label, rulText } from "../lib/format";

export default function PredictionsPage() {
  const { can } = useAuth();
  const [page, setPage] = useState(1);
  const [risk, setRisk] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const preds = usePredictions({ page, page_size: 25, risk_level: risk || undefined });
  const alerts = useAlerts({ status: "active", kind: "failure_risk", page_size: 20 });
  const fleet = useRunFleet();
  const detail = usePrediction(open);

  return (
    <div>
      <PageHeader title="Failure prediction" subtitle="Probability of failure within each equipment type's horizon, from the production classifier"
        actions={can("admin", "engineer") && <button className="btn-primary" disabled={fleet.isPending} onClick={() => fleet.mutate(undefined)}>{fleet.isPending ? "Running…" : "Run predictions for fleet"}</button>} />
      {fleet.data && <div className="mb-4"><Notice tone="ok">Evaluated {fleet.data.equipment_evaluated} equipment, created {fleet.data.predictions_created} predictions, {fleet.data.alerts_raised_or_updated} alerts raised or updated.</Notice></div>}
      {fleet.error && <div className="mb-4"><Notice tone="danger">{errorMessage(fleet.error)}</Notice></div>}
      <div className="grid gap-4 xl:grid-cols-3">
        <Card title="Prediction history" className="xl:col-span-2" bodyClass="p-0"
          actions={<select aria-label="Risk level" className="input !w-auto !py-1 text-xs" value={risk} onChange={(e) => { setRisk(e.target.value); setPage(1); }}>
            <option value="">All risk levels</option><option value="high">High</option><option value="elevated">Elevated</option><option value="low">Low</option></select>}>
          <QueryState q={preds} rows={8} empty={(d) => (d.total === 0 ? <Empty title="No predictions" /> : false)}>
            {(d) => (
              <>
                <div className="overflow-x-auto"><table className="w-full">
                  <thead className="border-b border-border"><tr><th className="th">As of</th><th className="th">Equipment</th><th className="th">Failure risk</th><th className="th">Level</th><th className="th">Anomaly</th><th className="th">RUL</th><th className="th">Trigger</th><th className="th" /></tr></thead>
                  <tbody className="divide-y divide-border">{d.items.map((p) => (
                    <tr key={p.id} className="hover:bg-muted/50">
                      <td className="td text-xs">{dateTime(p.as_of)}</td>
                      <td className="td"><Link to={`/equipment/${p.equipment_id}`} className="text-primary hover:underline">{p.equipment_code}</Link></td>
                      <td className="td"><ProbabilityBar value={p.failure_probability} level={p.risk_level} /></td>
                      <td className="td">{p.status === "ok" ? <RiskBadge level={p.risk_level} /> : <Badge>{label(p.status)}</Badge>}</td>
                      <td className="td">{p.is_anomaly ? <Badge tone="watch">Yes</Badge> : <span className="text-xs text-subtle">No</span>}</td>
                      <td className="td text-xs">{rulText(p.rul_hours, p.rul_status, p.rul_cap_hours, p.rul_unit)}</td>
                      <td className="td text-xs text-subtle">{p.triggered_by}</td>
                      <td className="td"><button className="btn-ghost !py-0.5 text-xs" onClick={() => setOpen(p.id)}>Explain</button></td>
                    </tr>))}</tbody>
                </table></div>
                <Pagination page={d.page} pageSize={d.page_size} total={d.total} onPage={setPage} />
              </>
            )}
          </QueryState>
        </Card>
        <Card title="Active failure-risk alerts" bodyClass="p-0">
          <QueryState q={alerts} empty={(d) => (d.total === 0 ? <Empty title="No active risk alerts" /> : false)}>{(d) => <AlertList alerts={d.items} />}</QueryState>
        </Card>
      </div>
      <Modal open={open !== null} wide title={`Prediction #${open ?? ""}${detail.data?.equipment_code ? ` · ${detail.data.equipment_code}` : ""}`} onClose={() => setOpen(null)}>
        <QueryState q={detail}>{(p) => <PredictionPanel p={p} />}</QueryState>
      </Modal>
    </div>
  );
}
