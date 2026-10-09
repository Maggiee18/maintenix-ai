import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useAlerts, useAnomalies } from "../api/hooks";
import { BarsChart } from "../components/charts";
import { AlertList } from "../components/domain";
import { Badge, Card, Empty, Notice, PageHeader, Pagination, QueryState } from "../components/ui";
import { dateTime, label, num } from "../lib/format";

export default function AnomaliesPage() {
  const [page, setPage] = useState(1);
  const events = useAnomalies({ page, page_size: 25 });
  const recent = useAnomalies({ page_size: 500 });
  const alerts = useAlerts({ status: "active", kind: "anomaly", page_size: 20 });
  const bySensor = useMemo(() => {
    const counts: Record<string, number> = {};
    (recent.data?.items ?? []).forEach((a) => a.sensors.filter((s) => s.outside_limits).forEach((s) => { counts[s.sensor] = (counts[s.sensor] ?? 0) + 1; }));
    return Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([sensor, n]) => ({ sensor: label(sensor), n }));
  }, [recent.data]);

  return (
    <div>
      <PageHeader title="Anomaly detection" subtitle="Readings that deviate from each type's healthy baseline (Isolation Forest + per-sensor control limits)" />
      <div className="mb-4"><Notice>An anomaly means the behaviour is unusual compared with healthy baseline data. It can come from wear, a sensor fault, a transient spike or an unusual but safe operating point. It is <strong>not</strong> a confirmed failure; review the evidence before acting.</Notice></div>
      <div className="grid gap-4 xl:grid-cols-3">
        <Card title="Anomaly events" className="xl:col-span-2" bodyClass="p-0">
          <QueryState q={events} rows={8} empty={(d) => (d.total === 0 ? <Empty title="No anomalies detected" /> : false)}>
            {(d) => (
              <>
                <div className="overflow-x-auto"><table className="w-full">
                  <thead className="border-b border-border"><tr><th className="th">Detected</th><th className="th">Equipment</th><th className="th">Score / threshold</th><th className="th">Sensors outside control limits</th></tr></thead>
                  <tbody className="divide-y divide-border">{d.items.map((a) => {
                    const out = a.sensors.filter((s) => s.outside_limits);
                    return (
                      <tr key={a.id}>
                        <td className="td whitespace-nowrap text-xs">{dateTime(a.detected_at)}</td>
                        <td className="td"><Link className="text-primary hover:underline" to={`/equipment/${a.equipment_id}`}>{a.equipment_code}</Link></td>
                        <td className="td text-xs tabular-nums">{num(a.score, 3)} / {num(a.threshold, 3)}</td>
                        <td className="td"><div className="flex flex-wrap gap-1">{out.length ? out.map((s) => <Badge key={s.sensor} tone="watch" title={`value ${num(s.value, 2)}, limits ${num(s.lower_limit, 2)}–${num(s.upper_limit, 2)}`}>{s.sensor} z={num(s.z_score, 1)}</Badge>) : <span className="text-xs text-subtle">Multivariate pattern only</span>}</div></td>
                      </tr>);
                  })}</tbody>
                </table></div>
                <Pagination page={d.page} pageSize={d.page_size} total={d.total} onPage={setPage} />
              </>
            )}
          </QueryState>
        </Card>
        <div className="space-y-4">
          <Card title="Sensors most often outside limits">
            <QueryState q={recent} empty={() => (bySensor.length === 0 ? <Empty title="No single-sensor breaches" /> : false)}>
              {() => <BarsChart data={bySensor} xKey="sensor" horizontal bars={[{ key: "n", label: "Anomaly events" }]} height={Math.max(140, bySensor.length * 34)} />}
            </QueryState>
            <p className="mt-2 text-2xs text-subtle">Across the latest {recent.data?.items.length ?? 0} anomaly events.</p>
          </Card>
          <Card title="Active anomaly alerts" bodyClass="p-0">
            <QueryState q={alerts} empty={(d) => (d.total === 0 ? <Empty title="No active anomaly alerts" /> : false)}>{(d) => <AlertList alerts={d.items} />}</QueryState>
          </Card>
        </div>
      </div>
    </div>
  );
}
