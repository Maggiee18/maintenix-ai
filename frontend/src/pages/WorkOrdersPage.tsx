import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { errorMessage } from "../api/client";
import { useAssignableUsers, useEquipmentList, useWorkOrder, useWorkOrderAction, useWorkOrders } from "../api/hooks";
import type { WorkOrderDetail } from "../api/types";
import { CreateWorkOrderModal } from "../components/domain";
import { Badge, Empty, Field, Modal, Notice, PageHeader, Pagination, PriorityBadge, QueryState, WOStatusBadge } from "../components/ui";
import { useAuth } from "../lib/auth";
import { dateOnly, dateTime, label } from "../lib/format";

const STATUS_FILTERS = [
  { id: "active", label: "Active", statuses: ["open", "assigned", "in_progress"] },
  { id: "open", label: "Open", statuses: ["open"] }, { id: "assigned", label: "Assigned", statuses: ["assigned"] },
  { id: "in_progress", label: "In progress", statuses: ["in_progress"] }, { id: "completed", label: "Completed", statuses: ["completed"] },
  { id: "cancelled", label: "Cancelled", statuses: ["cancelled"] }, { id: "all", label: "All", statuses: [] },
];

export default function WorkOrdersPage() {
  const { can, user } = useAuth();
  const [params, setParams] = useSearchParams();
  const [filter, setFilter] = useState("active");
  const [mine, setMine] = useState(user?.role === "technician");
  const [search, setSearch] = useState("");
  const [priority, setPriority] = useState("");
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const openId = params.get("open") ? Number(params.get("open")) : null;
  const list = useWorkOrders({
    page, page_size: 20, search: search || undefined, priority: priority || undefined, assigned_to_me: mine || undefined,
    status: STATUS_FILTERS.find((f) => f.id === filter)?.statuses, sort: filter === "active" ? "priority" : "created",
  });
  const setOpen = (id: number | null) => { const p = new URLSearchParams(params); if (id) p.set("open", String(id)); else p.delete("open"); setParams(p); };

  return (
    <div>
      <PageHeader title="Maintenance work orders" subtitle="Plan, assign and record maintenance"
        actions={can("admin", "engineer") && <button className="btn-primary" onClick={() => setCreating(true)}>New work order</button>} />
      <div className="card">
        <div className="flex flex-wrap items-center gap-2 border-b border-border p-3">
          <div role="group" aria-label="Status filter" className="flex flex-wrap gap-1">
            {STATUS_FILTERS.map((f) => (
              <button key={f.id} onClick={() => { setFilter(f.id); setPage(1); }} aria-pressed={filter === f.id}
                className={`rounded-full px-2.5 py-1 text-xs font-medium ${filter === f.id ? "bg-primary text-primary-fg" : "bg-muted text-subtle hover:text-fg"}`}>{f.label}</button>
            ))}
          </div>
          <input aria-label="Search work orders" placeholder="Search code, title, equipment" className="input max-w-xs" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} />
          <select aria-label="Priority" className="input !w-auto" value={priority} onChange={(e) => { setPriority(e.target.value); setPage(1); }}>
            <option value="">Any priority</option>{["critical", "high", "medium", "low"].map((p) => <option key={p} value={p}>{label(p)}</option>)}
          </select>
          <label className="flex items-center gap-1.5 text-sm"><input type="checkbox" checked={mine} onChange={(e) => { setMine(e.target.checked); setPage(1); }} /> Assigned to me</label>
        </div>
        <QueryState q={list} rows={6} empty={(d) => (d.total === 0 ? <Empty title="No work orders match">Change the filters, or create a work order from an alert.</Empty> : false)}>
          {(d) => (
            <>
              <div className="overflow-x-auto"><table className="w-full">
                <thead className="border-b border-border"><tr><th className="th">Code</th><th className="th">Title</th><th className="th">Equipment</th><th className="th">Priority</th><th className="th">Status</th><th className="th">Assignee</th><th className="th">Due</th><th className="th">Created</th></tr></thead>
                <tbody className="divide-y divide-border">{d.items.map((w) => (
                  <tr key={w.id} className="cursor-pointer hover:bg-muted/50" onClick={() => setOpen(w.id)}>
                    <td className="td"><button className="font-medium text-primary hover:underline" onClick={(e) => { e.stopPropagation(); setOpen(w.id); }}>{w.code}</button></td>
                    <td className="td max-w-xs truncate">{w.title}</td>
                    <td className="td text-xs">{w.equipment_code}</td>
                    <td className="td"><PriorityBadge priority={w.priority} /></td>
                    <td className="td"><WOStatusBadge status={w.status} /></td>
                    <td className="td text-xs">{w.assigned_to?.full_name ?? <span className="text-subtle">Unassigned</span>}</td>
                    <td className="td text-xs">{w.overdue ? <Badge tone="danger">Overdue {dateOnly(w.due_date)}</Badge> : dateOnly(w.due_date)}</td>
                    <td className="td text-xs text-subtle">{dateOnly(w.created_at)}</td>
                  </tr>))}</tbody>
              </table></div>
              <Pagination page={d.page} pageSize={d.page_size} total={d.total} onPage={setPage} />
            </>
          )}
        </QueryState>
      </div>
      {creating && <NewWorkOrder onClose={() => setCreating(false)} />}
      {openId && <WorkOrderModal id={openId} onClose={() => setOpen(null)} />}
    </div>
  );
}

function NewWorkOrder({ onClose }: { onClose: () => void }) {
  const eq = useEquipmentList({ page_size: 200, sort: "code" });
  const [eqId, setEqId] = useState<number | null>(null);
  if (eqId) {
    const e = eq.data?.items.find((x) => x.id === eqId);
    return <CreateWorkOrderModal open onClose={onClose} equipmentId={eqId} equipmentLabel={e?.code ?? ""} predictionId={e?.latest_prediction?.id} />;
  }
  return (
    <Modal open title="New work order: choose equipment" onClose={onClose}>
      <QueryState q={eq}>
        {(d) => (
          <select aria-label="Equipment" className="input" defaultValue="" onChange={(e) => setEqId(Number(e.target.value))}>
            <option value="" disabled>Select equipment…</option>
            {d.items.filter((x) => x.status !== "decommissioned").map((x) => <option key={x.id} value={x.id}>{x.code} · {x.name} ({label(x.health_state)})</option>)}
          </select>
        )}
      </QueryState>
    </Modal>
  );
}

function WorkOrderModal({ id, onClose }: { id: number; onClose: () => void }) {
  const wo = useWorkOrder(id);
  return (
    <Modal open wide title={wo.data ? `${wo.data.code} · ${wo.data.title}` : "Work order"} onClose={onClose}>
      <QueryState q={wo}>{(w) => <WorkOrderBody w={w} />}</QueryState>
    </Modal>
  );
}

function WorkOrderBody({ w }: { w: WorkOrderDetail }) {
  const action = useWorkOrderAction();
  const users = useAssignableUsers();
  const [assignee, setAssignee] = useState(String(w.assigned_to?.id ?? ""));
  const [mode, setMode] = useState<"none" | "complete" | "cancel">("none");
  const [cancelReason, setCancelReason] = useState("");
  const [done, setDone] = useState({ action_taken: "inspection", summary: "", parts_replaced: "", downtime_hours: "0", restores_health: false });
  const [formErr, setFormErr] = useState<string | null>(null);
  const can = (a: string) => w.allowed_transitions.includes(a);
  const run = async (a: "assign" | "transition" | "complete", body: Record<string, unknown>) => {
    setFormErr(null);
    try { await action.mutateAsync({ id: w.id, action: a, body }); setMode("none"); } catch (e) { setFormErr(errorMessage(e)); }
  };
  async function complete(e: FormEvent) {
    e.preventDefault();
    if (done.summary.trim().length < 5) return setFormErr("Describe the work performed (at least 5 characters).");
    const hours = Number(done.downtime_hours);
    if (Number.isNaN(hours) || hours < 0) return setFormErr("Downtime must be a non-negative number.");
    await run("complete", { ...done, downtime_hours: hours });
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <WOStatusBadge status={w.status} /><PriorityBadge priority={w.priority} />
        {w.overdue && <Badge tone="danger">Overdue</Badge>}
        <span className="text-sm">Equipment <Link className="text-primary hover:underline" to={`/equipment/${w.equipment_id}`}>{w.equipment_code}</Link></span>
        {w.alert_id && <span className="text-xs text-subtle">from alert #{w.alert_id}</span>}
      </div>
      {w.description && <p className="whitespace-pre-wrap text-sm">{w.description}</p>}
      <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
        <div><dt className="text-2xs text-subtle">Assignee</dt><dd>{w.assigned_to?.full_name ?? "Unassigned"}</dd></div>
        <div><dt className="text-2xs text-subtle">Due</dt><dd>{dateOnly(w.due_date)}</dd></div>
        <div><dt className="text-2xs text-subtle">Created by</dt><dd>{w.created_by?.full_name ?? "—"}</dd></div>
        <div><dt className="text-2xs text-subtle">Started</dt><dd>{dateTime(w.started_at)}</dd></div>
      </dl>

      {w.allowed_transitions.length > 0 && (
        <div className="flex flex-wrap items-end gap-2 rounded-md border border-border p-3">
          {can("assign") && (
            <>
              <Field label={w.status === "assigned" ? "Reassign to" : "Assign to"}>
                <select className="input !w-56" value={assignee} onChange={(e) => setAssignee(e.target.value)}>
                  <option value="">Choose…</option>{users.data?.map((u) => <option key={u.id} value={u.id}>{u.full_name} ({u.role})</option>)}
                </select>
              </Field>
              <button className="btn-primary" disabled={!assignee || action.isPending} onClick={() => run("assign", { assignee_id: Number(assignee) })}>Assign</button>
            </>
          )}
          {can("start") && <button className="btn-primary" disabled={action.isPending} onClick={() => run("transition", { to_status: "in_progress" })}>Start work</button>}
          {can("unassign") && <button className="btn-secondary" disabled={action.isPending} onClick={() => run("transition", { to_status: "open" })}>Unassign</button>}
          {can("complete") && <button className="btn-primary" onClick={() => setMode("complete")}>Record completion</button>}
          {can("cancel") && <button className="btn-ghost text-danger" onClick={() => setMode("cancel")}>Cancel work order</button>}
        </div>
      )}

      {mode === "complete" && (
        <form onSubmit={complete} className="grid gap-3 rounded-md border border-border p-3 sm:grid-cols-2" noValidate>
          <Field label="Action taken"><select className="input" value={done.action_taken} onChange={(e) => setDone({ ...done, action_taken: e.target.value })}>
            {["inspection", "repair", "replacement", "adjustment", "lubrication", "calibration", "other"].map((a) => <option key={a} value={a}>{label(a)}</option>)}</select></Field>
          <Field label="Downtime (hours)"><input className="input" inputMode="decimal" value={done.downtime_hours} onChange={(e) => setDone({ ...done, downtime_hours: e.target.value })} /></Field>
          <div className="sm:col-span-2"><Field label="Work performed"><textarea className="input min-h-20" value={done.summary} onChange={(e) => setDone({ ...done, summary: e.target.value })} /></Field></div>
          <Field label="Parts replaced"><input className="input" value={done.parts_replaced} onChange={(e) => setDone({ ...done, parts_replaced: e.target.value })} /></Field>
          <label className="flex items-center gap-2 self-end text-sm"><input type="checkbox" checked={done.restores_health} onChange={(e) => setDone({ ...done, restores_health: e.target.checked })} />
            Restores equipment health (resolves active alerts)</label>
          <div className="flex gap-2 sm:col-span-2"><button className="btn-primary" disabled={action.isPending}>Complete work order</button><button type="button" className="btn-secondary" onClick={() => setMode("none")}>Back</button></div>
        </form>
      )}
      {mode === "cancel" && (
        <div className="space-y-2 rounded-md border border-danger/30 p-3">
          <Field label="Cancellation reason (required)"><textarea className="input" value={cancelReason} onChange={(e) => setCancelReason(e.target.value)} /></Field>
          <div className="flex gap-2"><button className="btn-danger" disabled={!cancelReason.trim() || action.isPending} onClick={() => run("transition", { to_status: "cancelled", note: cancelReason })}>Cancel work order</button>
            <button className="btn-secondary" onClick={() => setMode("none")}>Back</button></div>
        </div>
      )}
      {formErr && <p role="alert" className="text-sm text-danger">{formErr}</p>}

      {w.record && (
        <Notice tone="ok"><strong>{label(w.record.action_taken)}</strong> by {w.record.performed_by} on {dateTime(w.record.completed_at)}: {w.record.summary}
          {w.record.parts_replaced && ` Parts: ${w.record.parts_replaced}.`} Downtime {w.record.downtime_hours} h.</Notice>
      )}
      {w.cancel_reason && <Notice tone="warn">Cancelled: {w.cancel_reason}</Notice>}

      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-subtle">History</h3>
        <ol className="space-y-1.5 border-l border-border pl-4">
          {w.events.map((e) => (
            <li key={e.id} className="relative text-sm"><span className="absolute -left-[21px] top-1.5 h-2 w-2 rounded-full bg-primary" />
              <span className="font-medium">{e.from_status ? `${label(e.from_status)} → ${label(e.to_status)}` : "Created"}</span>
              <span className="text-xs text-subtle"> · {e.actor ?? "system"} · {dateTime(e.created_at)}</span>
              {e.note && <div className="text-xs text-subtle">{e.note}</div>}</li>
          ))}
        </ol>
      </div>
    </div>
  );
}
