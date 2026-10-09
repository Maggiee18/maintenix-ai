import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type {
  Alert, AnomalyEvent, AuditEvent, Backlog, DashboardSummary, Equipment, EquipmentDetail, EquipmentType, HealthDistribution,
  IngestReport, ModelVersion, ModelVersionDetail, Page, Prediction, PredictionDetail, PredictionTrend, SensorTrends, Series,
  Threshold, User, UserBrief, WorkOrder, WorkOrderDetail, MaintenanceRecord,
} from "./types";

type Q = Record<string, string | number | boolean | undefined | null | (string | number)[]>;

// ------------------------------------------------------------------ queries
export const useEquipmentTypes = () =>
  useQuery({ queryKey: ["equipment-types"], queryFn: () => api.get<EquipmentType[]>("/equipment-types"), staleTime: 300_000 });

export const useEquipmentList = (q: Q) =>
  useQuery({ queryKey: ["equipment", q], queryFn: () => api.get<Page<Equipment>>("/equipment", q), placeholderData: keepPreviousData });

export const useEquipment = (id: number | undefined) =>
  useQuery({ queryKey: ["equipment", id], queryFn: () => api.get<EquipmentDetail>(`/equipment/${id}`), enabled: !!id });

export const useHealthHistory = (id: number) =>
  useQuery({ queryKey: ["health-history", id], queryFn: () => api.get<{ points: { as_of: string; failure_probability: number | null; anomaly_score: number | null; rul_hours: number | null; risk_level: string | null; is_anomaly: boolean | null }[]; maintenance: { completed_at: string; action_taken: string; summary: string; restores_health: boolean; work_order_id: number }[] }>(`/equipment/${id}/health-history`, { limit: 500 }) });

export const useSeries = (id: number | undefined, q: Q) =>
  useQuery({ queryKey: ["series", id, q], queryFn: () => api.get<Series>(`/sensors/equipment/${id}/series`, q), enabled: !!id, placeholderData: keepPreviousData });

export const usePredictions = (q: Q) =>
  useQuery({ queryKey: ["predictions", q], queryFn: () => api.get<Page<Prediction>>("/predictions", q), placeholderData: keepPreviousData });

export const usePrediction = (id: number | null | undefined) =>
  useQuery({ queryKey: ["prediction", id], queryFn: () => api.get<PredictionDetail>(`/predictions/${id}`), enabled: !!id });

export const useAnomalies = (q: Q) =>
  useQuery({ queryKey: ["anomalies", q], queryFn: () => api.get<Page<AnomalyEvent>>("/anomalies", q), placeholderData: keepPreviousData });

export const useAlerts = (q: Q) =>
  useQuery({ queryKey: ["alerts", q], queryFn: () => api.get<Page<Alert>>("/alerts", q), placeholderData: keepPreviousData });

export const useModels = () => useQuery({ queryKey: ["models"], queryFn: () => api.get<ModelVersion[]>("/models") });
export const useModel = (id: number | null) =>
  useQuery({ queryKey: ["model", id], queryFn: () => api.get<ModelVersionDetail>(`/models/${id}`), enabled: !!id });

export const useWorkOrders = (q: Q) =>
  useQuery({ queryKey: ["work-orders", q], queryFn: () => api.get<Page<WorkOrder>>("/work-orders", q), placeholderData: keepPreviousData });
export const useWorkOrder = (id: number | null) =>
  useQuery({ queryKey: ["work-order", id], queryFn: () => api.get<WorkOrderDetail>(`/work-orders/${id}`), enabled: !!id });
export const useMaintenanceRecords = (equipmentId: number) =>
  useQuery({ queryKey: ["maintenance-records", equipmentId], queryFn: () => api.get<Page<MaintenanceRecord>>("/maintenance/records", { equipment_id: equipmentId, page_size: 50 }) });
export const useAssignableUsers = () =>
  useQuery({ queryKey: ["assignable"], queryFn: () => api.get<UserBrief[]>("/users/assignable"), staleTime: 60_000 });

export const useSummary = () => useQuery({ queryKey: ["dash", "summary"], queryFn: () => api.get<DashboardSummary>("/dashboard/summary"), refetchInterval: 60_000 });
export const useHealthDistribution = () => useQuery({ queryKey: ["dash", "health"], queryFn: () => api.get<HealthDistribution>("/dashboard/health-distribution") });
export const useHighRisk = () => useQuery({ queryKey: ["dash", "high-risk"], queryFn: () => api.get<Equipment[]>("/dashboard/high-risk", { limit: 8 }) });
export const usePredictionTrends = (days: number) =>
  useQuery({ queryKey: ["dash", "trends", days], queryFn: () => api.get<PredictionTrend[]>("/dashboard/prediction-trends", { days }) });
export const useSensorTrends = (q: Q) =>
  useQuery({ queryKey: ["dash", "sensor-trends", q], queryFn: () => api.get<SensorTrends>("/dashboard/sensor-trends", q), placeholderData: keepPreviousData });
export const useBacklog = () => useQuery({ queryKey: ["dash", "backlog"], queryFn: () => api.get<Backlog>("/dashboard/maintenance-backlog") });

export const useUsers = () => useQuery({ queryKey: ["users"], queryFn: () => api.get<Page<User>>("/admin/users", { page_size: 200 }) });
export const useThresholds = () => useQuery({ queryKey: ["thresholds"], queryFn: () => api.get<Threshold[]>("/admin/thresholds") });
export const useAudit = (q: Q) =>
  useQuery({ queryKey: ["audit", q], queryFn: () => api.get<Page<AuditEvent>>("/admin/audit-events", q), placeholderData: keepPreviousData });

// ------------------------------------------------------------------ mutations
/** Mutation that invalidates the listed query prefixes on success. */
export function useApiMutation<TVars, TOut>(fn: (v: TVars) => Promise<TOut>, invalidate: string[]) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => Promise.all(invalidate.map((k) => qc.invalidateQueries({ queryKey: [k] }))),
  });
}

const ALL_OPS = ["equipment", "predictions", "prediction", "alerts", "dash", "work-orders", "work-order", "anomalies", "health-history", "series", "maintenance-records"];

export const useRunPrediction = () => useApiMutation((id: number) => api.post<PredictionDetail>(`/predictions/equipment/${id}/run`), ALL_OPS);
export const useRunFleet = () => useApiMutation(() => api.post<Record<string, number>>("/predictions/run-fleet"), ALL_OPS);
export const useCreateWorkOrder = () => useApiMutation((b: Record<string, unknown>) => api.post<WorkOrderDetail>("/work-orders", b), ALL_OPS);
export const useWorkOrderAction = () =>
  useApiMutation(({ id, action, body }: { id: number; action: "assign" | "transition" | "complete"; body: Record<string, unknown> }) =>
    api.post<WorkOrderDetail>(`/work-orders/${id}/${action}`, body), ALL_OPS);
export const useAlertAction = () =>
  useApiMutation(({ id, action, note }: { id: number; action: "acknowledge" | "resolve"; note?: string }) =>
    api.post<Alert>(`/alerts/${id}/${action}`, { note: note ?? "" }), ALL_OPS);
export const useCreateEquipment = () => useApiMutation((b: Record<string, unknown>) => api.post<Equipment>("/equipment", b), ["equipment", "dash"]);
export const useUpdateEquipmentStatus = () =>
  useApiMutation(({ id, status, reason }: { id: number; status: string; reason: string }) => api.post<Equipment>(`/equipment/${id}/status`, { status, reason }), ["equipment", "dash"]);
export const useUploadCsv = () =>
  useApiMutation((form: FormData) => api.upload<IngestReport>("/sensors/readings/upload", form), ALL_OPS);
export const usePromoteModel = () => useApiMutation((id: number) => api.post<ModelVersion>(`/models/${id}/promote`), ["models", "model"]);
export const useCreateUser = () => useApiMutation((b: Record<string, unknown>) => api.post<User>("/admin/users", b), ["users", "assignable"]);
export const useUpdateUser = () =>
  useApiMutation(({ id, ...b }: { id: number } & Record<string, unknown>) => api.patch<User>(`/admin/users/${id}`, b), ["users", "assignable", "audit"]);
export const useUpdateThreshold = () =>
  useApiMutation(({ key, ...b }: { key: string } & Record<string, unknown>) => api.put<Threshold>(`/admin/thresholds/${key}`, b), ["thresholds", "audit"]);
