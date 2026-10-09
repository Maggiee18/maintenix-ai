import { useMemo, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { errorMessage } from "../api/client";
import { useModel, useModels, usePromoteModel } from "../api/hooks";
import type { ModelVersion, ModelVersionDetail } from "../api/types";
import { BarsChart, legendText, series } from "../components/charts";
import { Badge, Card, Empty, Notice, PageHeader, QueryState, Stat } from "../components/ui";
import { useAuth } from "../lib/auth";
import { dateTime, label, num, pct } from "../lib/format";

const TASK_LABEL = { failure: "Failure risk", anomaly: "Anomaly detection", rul: "Remaining useful life" } as const;

export default function ModelsPage() {
  const models = useModels();
  const [selected, setSelected] = useState<number | null>(null);
  const grouped = useMemo(() => {
    const g: Record<string, ModelVersion[]> = {};
    (models.data ?? []).forEach((m) => { (g[m.equipment_type] ??= []).push(m); });
    return g;
  }, [models.data]);
  const current = selected ?? models.data?.find((m) => m.status === "production" && m.task === "failure")?.id ?? null;

  return (
    <div>
      <PageHeader title="Model performance" subtitle="Versioned models per equipment type, evaluated on held-out units the model never saw in training" />
      <div className="grid gap-4 xl:grid-cols-4">
        <Card title="Registry" bodyClass="p-0">
          <QueryState q={models} empty={(d) => (d.length === 0 ? <Empty title="No models registered">Run the training command, then sync models.</Empty> : false)}>
            {() => (
              <div className="divide-y divide-border">
                {Object.entries(grouped).map(([type, list]) => (
                  <div key={type} className="py-2">
                    <div className="px-4 pb-1 text-2xs font-semibold uppercase tracking-wide text-subtle">{label(type)}</div>
                    {list.map((m) => (
                      <button key={m.id} onClick={() => setSelected(m.id)} aria-pressed={current === m.id}
                        className={`flex w-full items-center justify-between gap-2 px-4 py-1.5 text-left text-sm ${current === m.id ? "bg-primary/10" : "hover:bg-muted"}`}>
                        <span>{TASK_LABEL[m.task]}<span className="block text-2xs text-subtle">{m.algorithm} · {m.version}</span></span>
                        <Badge tone={m.status === "production" ? "ok" : m.status === "staging" ? "watch" : "neutral"}>{m.status}</Badge>
                      </button>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </QueryState>
        </Card>
        <div className="xl:col-span-3">{current ? <ModelDetail id={current} /> : <Card><Empty title="Select a model" /></Card>}</div>
      </div>
    </div>
  );
}

function ModelDetail({ id }: { id: number }) {
  const m = useModel(id);
  const { can } = useAuth();
  const promote = usePromoteModel();
  return (
    <QueryState q={m} rows={8}>
      {(d) => (
        <div className="space-y-4">
          <Card title={`${label(d.equipment_type)} · ${TASK_LABEL[d.task]}`}
            actions={can("admin") && d.status !== "production" && <button className="btn-primary !py-1 text-xs" disabled={promote.isPending} onClick={() => promote.mutate(d.id)}>Promote to production</button>}>
            {promote.error && <div className="mb-3"><Notice tone="danger">{errorMessage(promote.error)}</Notice></div>}
            <dl className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
              {[["Version", d.version], ["Algorithm", d.algorithm], ["Status", d.status], ["Trained", dateTime(d.trained_at)],
                ["Target", String(d.dataset_info.target ?? "—")], ["Split", String(d.dataset_info.split_strategy ?? "—")],
                ["Units train/val/test", d.dataset_info.split ? `${d.dataset_info.split.train} / ${d.dataset_info.split.validation} / ${d.dataset_info.split.test}` : "—"],
                ["Features", `${d.feature_count} (schema v${d.feature_version})`]].map(([k, v]) => (
                <div key={k}><dt className="text-2xs text-subtle">{k}</dt><dd className="break-words">{v}</dd></div>))}
            </dl>
            <p className="mt-3 break-all text-2xs text-subtle">Dataset: {d.dataset_id} · {d.dataset_info.dataset?.source === "simulated" ? "SIMULATED data from maintenix_ml.simulator" : d.dataset_info.dataset?.source} · seed {d.dataset_info.seed} · artifact sha256 {d.artifact_sha256.slice(0, 16)}…</p>
          </Card>
          {d.task === "failure" && <FailureMetrics d={d} />}
          {d.task === "anomaly" && <AnomalyMetrics d={d} />}
          {d.task === "rul" && <RulMetrics d={d} />}
        </div>
      )}
    </QueryState>
  );
}

function FailureMetrics({ d }: { d: ModelVersionDetail }) {
  const t = d.metrics.test;
  const cm = t.confusion_matrix;
  const ev = t.event_level ?? {};
  const comparison = Object.entries(d.metrics.comparison ?? {}).map(([name, v]: [string, any]) => ({ // eslint-disable-line @typescript-eslint/no-explicit-any
    name: label(name), "Validation PR-AUC": v.validation_pr_auc, "Test PR-AUC": v.test?.pr_auc, "Test recall": v.test?.recall, "Test precision": v.test?.precision,
  }));
  return (
    <>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
        <Stat label="Precision" value={pct(t.precision, 1)} /><Stat label="Recall" value={pct(t.recall, 1)} />
        <Stat label="F1" value={num(t.f1, 3)} /><Stat label="PR-AUC" value={num(t.pr_auc, 3)} hint={`positive rate ${pct(t.positive_rate, 1)}`} />
        <Stat label="ROC-AUC" value={num(t.roc_auc, 3)} /><Stat label="Brier score" value={num(t.brier, 4)} hint="lower is better" />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={`Confusion matrix (test, threshold ${num(t.threshold, 3)})`}>
          <div className="grid grid-cols-[auto_1fr_1fr] gap-1 text-center text-sm" role="table" aria-label="Confusion matrix">
            <div /><div className="text-2xs text-subtle">Predicted no failure</div><div className="text-2xs text-subtle">Predicted failure</div>
            <div className="self-center pr-2 text-right text-2xs text-subtle">Actual no failure</div>
            <div className="rounded bg-ok/10 p-3"><div className="text-lg font-semibold">{cm.tn}</div><div className="text-2xs text-subtle">true negatives</div></div>
            <div className="rounded bg-warn/10 p-3"><div className="text-lg font-semibold">{cm.fp}</div><div className="text-2xs text-subtle">false alarms</div></div>
            <div className="self-center pr-2 text-right text-2xs text-subtle">Actual failure</div>
            <div className="rounded bg-danger/10 p-3"><div className="text-lg font-semibold">{cm.fn}</div><div className="text-2xs text-subtle">missed</div></div>
            <div className="rounded bg-ok/10 p-3"><div className="text-lg font-semibold">{cm.tp}</div><div className="text-2xs text-subtle">caught</div></div>
          </div>
          <p className="mt-3 text-xs text-subtle">Missed failures mean unplanned downtime; false alarms cost an unnecessary inspection. The threshold maximises F2 on validation data, which weights recall twice as heavily as precision.</p>
        </Card>
        <Card title="Operational view (test units)">
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <div><dt className="text-2xs text-subtle">Failure events in test units</dt><dd className="text-lg font-semibold">{ev.failure_events ?? "—"}</dd></div>
            <div><dt className="text-2xs text-subtle">Warned in advance</dt><dd className="text-lg font-semibold">{ev.events_warned ?? "—"} ({pct(ev.event_recall)})</dd></div>
            <div><dt className="text-2xs text-subtle">Median first-warning lead time</dt><dd className="text-lg font-semibold">{num(ev.median_lead_time_hours, 0)} h</dd></div>
            <div><dt className="text-2xs text-subtle">False alarms per 1000 healthy hours</dt><dd className="text-lg font-semibold">{num(ev.false_alarms_per_1000_healthy_hours, 1)}</dd></div>
          </dl>
          <p className="mt-3 text-xs text-subtle">Readings are counted individually above; this view counts failure events and asks whether at least one warning came before each.</p>
        </Card>
        <Card title="Model comparison: PR-AUC (selection metric)">
          <BarsChart data={comparison} xKey="name" bars={[{ key: "Validation PR-AUC", label: "Validation" }, { key: "Test PR-AUC", label: "Test" }]} valueFormat={(v) => v.toFixed(2)} domain={[0, 1]} />
          <p className="mt-2 text-xs text-subtle">Selected: <strong>{label(d.metrics.selected_algorithm)}</strong>, by highest validation PR-AUC. Test scores are shown for transparency only and were not used to choose.</p>
        </Card>
        <Card title="Calibration (test)">
          <Calibration bins={t.calibration ?? []} />
        </Card>
      </div>
    </>
  );
}

function Calibration({ bins }: { bins: { mean_predicted: number; observed_rate: number; count: number }[] }) {
  if (!bins.length) return <Empty title="No calibration data" />;
  const data = bins.map((b) => ({ x: b.mean_predicted, observed: b.observed_rate, ideal: b.mean_predicted, n: b.count }));
  return (
    <div style={{ height: 220 }} role="img" aria-label="Reliability diagram">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 18, left: 0 }}>
          <CartesianGrid stroke="rgb(var(--border))" strokeOpacity={0.6} />
          <XAxis dataKey="x" type="number" domain={[0, 1]} tickFormatter={(v) => `${Math.round(v * 100)}%`} stroke="rgb(var(--subtle))" fontSize={11}
            label={{ value: "mean predicted probability", position: "insideBottom", offset: -2, fontSize: 10, fill: "rgb(var(--subtle))" }} />
          <YAxis domain={[0, 1]} tickFormatter={(v) => `${Math.round(v * 100)}%`} stroke="rgb(var(--subtle))" fontSize={11} width={44} />
          <Tooltip formatter={(v: number, n: string) => [`${(v * 100).toFixed(1)}%`, n]} labelFormatter={(v) => `predicted ≈ ${(Number(v) * 100).toFixed(0)}%`}
            contentStyle={{ background: "rgb(var(--surface))", border: "1px solid rgb(var(--border))", fontSize: 12 }} />
          <Legend verticalAlign="top" wrapperStyle={{ fontSize: 12, paddingBottom: 4 }} formatter={legendText} />
          <Line dataKey="ideal" name="Perfect calibration" stroke="rgb(var(--subtle))" strokeDasharray="4 3" dot={false} isAnimationActive={false} />
          <Line dataKey="observed" name="Observed failure rate" stroke={series(0)} strokeWidth={2} dot={{ r: 4 }} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function AnomalyMetrics({ d }: { d: ModelVersionDetail }) {
  const t = d.metrics.test;
  return (
    <>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Injected spikes detected" value={pct(t.injected_spike_detection_rate, 1)} hint={`${t.injected_spikes} spikes in test units`} />
        <Stat label="Flag rate, healthy operation" value={pct(t.flag_rate_healthy, 2)} hint="false-alarm proxy" />
        <Stat label="Flag rate, pre-failure window" value={pct(t.flag_rate_pre_failure_window, 1)} />
        <Stat label="Score threshold" value={num(t.threshold, 3)} />
      </div>
      <Card title="How the threshold and evaluation work">
        <ul className="list-disc space-y-1 pl-5 text-sm">
          <li>{t.threshold_rule}. Admins can override it per equipment type.</li>
          <li>Decision rule: {String(d.params.decision ?? "score ≥ threshold")}; control limits at ±{d.params.control_limit_sigma}σ per sensor and operating mode.</li>
          <li>Spike detection: Isolation Forest alone {pct(t.injected_spike_detection_rate_isolation_forest_only, 1)}, control limits alone {pct(t.injected_spike_detection_rate_control_limits_only, 1)}.</li>
          <li>Spikes are known only because the data is simulated. On real equipment there is no such ground truth; review flagged events.</li>
        </ul>
      </Card>
    </>
  );
}

function RulMetrics({ d }: { d: ModelVersionDetail }) {
  const t = d.metrics.test;
  const comparison = Object.entries(d.metrics.comparison ?? {}).map(([name, v]: [string, any]) => ({ // eslint-disable-line @typescript-eslint/no-explicit-any
    name: label(name), "Validation RMSE": v.validation?.rmse, "Test RMSE (near failure)": v.test?.within_cap?.rmse,
  }));
  return (
    <>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="MAE, last cap hours" value={`${num(t.within_cap?.mae, 1)} h`} hint={`RUL ≤ ${d.metrics.cap_hours} h, where it matters`} />
        <Stat label="RMSE, last cap hours" value={`${num(t.within_cap?.rmse, 1)} h`} />
        <Stat label="MAE, all readings" value={`${num(t.overall?.mae, 1)} h`} hint="target clipped at cap" />
        <Stat label="Bias (pred − true)" value={`${num(t.within_cap?.bias, 1)} h`} hint={t.within_cap?.bias > 0 ? "tends to over-estimate" : "tends to under-estimate"} />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Model comparison: RMSE in hours (lower is better)">
          <BarsChart data={comparison} xKey="name" bars={[{ key: "Validation RMSE", label: "Validation (all)" }, { key: "Test RMSE (near failure)", label: "Test (near failure)" }]} valueFormat={(v) => v.toFixed(0)} domain={[0, "auto"]} />
        </Card>
        <Card title="Limitations">
          <ul className="list-disc space-y-1 pl-5 text-sm">
            <li>Target is hours to failure clipped at {d.metrics.cap_hours} h. A prediction at the cap means "at least {d.metrics.cap_hours} h".</li>
            <li>Over-estimating RUL is the risky direction; bias near failure is {num(t.within_cap?.bias, 1)} h.</li>
            <li>Learned from simulated run-to-failure trajectories with one failure mode; real assets have several.</li>
            <li>RUL is only offered for equipment types with run-to-failure data. Others show "RUL unavailable".</li>
          </ul>
        </Card>
      </div>
    </>
  );
}
