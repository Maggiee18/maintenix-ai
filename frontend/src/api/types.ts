// Types mirror backend Pydantic schemas (backend/app/schemas).

export type Role = "admin" | "engineer" | "technician" | "viewer";
export type HealthState = "healthy" | "watch" | "at_risk" | "critical" | "unknown";
export type RiskLevel = "low" | "elevated" | "high";
export type WOStatus = "open" | "assigned" | "in_progress" | "completed" | "cancelled";
export type Priority = "low" | "medium" | "high" | "critical";

export interface Page<T> { items: T[]; total: number; page: number; page_size: number }

export interface User {
  id: number; email: string; full_name: string; role: Role; is_active: boolean;
  last_login_at: string | null; created_at: string;
}
export interface UserBrief { id: number; full_name: string; role: Role }
export interface TokenOut { access_token: string; token_type: "bearer"; expires_at: string; user: User }

export interface SensorDefinition {
  id: number; name: string; unit: string; description: string;
  valid_min: number; valid_max: number; normal_min: number; normal_max: number; required: boolean;
}
export interface EquipmentType {
  id: number; key: string; display_name: string; description: string; rul_supported: boolean;
  sampling_interval_seconds: number; failure_horizon_hours: number; data_note: string; sensors: SensorDefinition[];
}

export interface LatestPredictionBrief {
  id: number; as_of: string; status: string; failure_probability: number | null; risk_level: RiskLevel | null;
  is_anomaly: boolean | null; rul_hours: number | null; rul_status: string; rul_unit: string;
}

export interface Equipment {
  id: number; code: string; name: string; equipment_type: string; equipment_type_name: string; location: string;
  manufacturer: string; model_number: string; serial_number: string; install_date: string | null;
  status: "operational" | "under_maintenance" | "offline" | "decommissioned";
  criticality: "low" | "medium" | "high"; data_source: "simulated" | "imported" | "api"; health_state: HealthState;
  last_maintenance_at: string | null; latest_prediction: LatestPredictionBrief | null; open_alerts: number;
  created_at: string; updated_at: string;
}
export interface EquipmentDetail extends Equipment {
  type_info: EquipmentType;
  latest_reading: { recorded_at: string; operating_mode: string; operating_hours: number | null; values: Record<string, number> } | null;
  reading_count: number;
}

export interface FeatureContribution { feature: string; sensor: string; value: number; contribution: number; direction: string }
export interface Explanation {
  method: string; output_space: string; base_value: number; top_features: FeatureContribution[];
  sensor_contributions: { sensor: string; contribution: number }[]; limitations: string;
}
export interface SensorDeviation {
  sensor: string; value: number; baseline_mean: number; lower_limit: number; upper_limit: number; z_score: number; outside_limits: boolean;
}
export interface Prediction {
  id: number; equipment_id: number; equipment_code: string | null; as_of: string; created_at: string; status: string;
  readings_used: number; failure_probability: number | null; failure_threshold: number | null; risk_level: RiskLevel | null;
  anomaly_score: number | null; anomaly_threshold: number | null; is_anomaly: boolean | null; rul_hours: number | null;
  rul_cap_hours: number | null; rul_typical_error_hours: number | null; rul_status: string; rul_unit: string;
  failure_model_id: number | null; anomaly_model_id: number | null; rul_model_id: number | null; triggered_by: string;
  recommendation: string | null;
}
export interface PredictionDetail extends Prediction { explanation: Explanation | null; sensor_deviations: SensorDeviation[] | null }

export interface AnomalyEvent {
  id: number; equipment_id: number; equipment_code: string; prediction_id: number; detected_at: string;
  score: number; threshold: number; sensors: SensorDeviation[];
}

export interface Alert {
  id: number; equipment_id: number; equipment_code: string; equipment_name: string; kind: "failure_risk" | "anomaly";
  severity: "warning" | "critical"; status: "open" | "acknowledged" | "resolved"; title: string; message: string;
  prediction_id: number | null; first_seen_at: string; last_seen_at: string; occurrence_count: number;
  acknowledged_at: string | null; resolved_at: string | null; work_order_id: number | null;
}

export interface ModelVersion {
  id: number; equipment_type: string; task: "failure" | "anomaly" | "rul"; name: string; version: string; algorithm: string;
  dataset_id: string; feature_version: string; feature_count: number; status: "staging" | "production" | "archived";
  trained_at: string; registered_at: string; promoted_at: string | null;
}
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Json = any;
export interface ModelVersionDetail extends ModelVersion {
  feature_names: string[]; params: Record<string, Json>; metrics: Record<string, Json>;
  dataset_info: Record<string, Json>; artifact_sha256: string;
}

export interface WorkOrderEvent { id: number; from_status: string | null; to_status: string; actor: string | null; note: string | null; created_at: string }
export interface MaintenanceRecord {
  id: number; work_order_id: number; work_order_code: string; equipment_id: number; equipment_code: string;
  performed_by: string | null; completed_at: string; action_taken: string; summary: string; parts_replaced: string;
  downtime_hours: number; restores_health: boolean;
}
export interface WorkOrder {
  id: number; code: string; equipment_id: number; equipment_code: string; equipment_name: string; alert_id: number | null;
  prediction_id: number | null; title: string; description: string; priority: Priority; status: WOStatus;
  assigned_to: UserBrief | null; created_by: UserBrief | null; due_date: string | null; overdue: boolean;
  created_at: string; updated_at: string; started_at: string | null; completed_at: string | null;
  cancelled_at: string | null; cancel_reason: string | null; allowed_transitions: string[];
}
export interface WorkOrderDetail extends WorkOrder { events: WorkOrderEvent[]; record: MaintenanceRecord | null }

export interface IngestIssue { row: number | null; column: string | null; code: string; message: string }
export interface IngestReport {
  total_rows: number; accepted_rows: number; rejected_rows: number; duplicate_rows: number; already_stored: number;
  sampling: Record<string, number | null>; errors: IngestIssue[]; warnings: IngestIssue[]; truncated: boolean;
  equipment_ids: number[]; predictions: Record<string, unknown>[];
}

export interface Series { equipment_id: number; bucket: string; sensors: string[]; points: { t: string; values: Record<string, number | null> }[] }

export interface DashboardSummary {
  total_equipment: number; operational: number; under_maintenance: number; requiring_attention: number; high_risk: number;
  open_work_orders: number; active_alerts: number; simulated_equipment: number; last_prediction_at: string | null;
  recent_alerts: Alert[]; definitions: Record<string, string>;
}
export interface HealthDistribution { overall: Record<HealthState, number>; by_type: Record<string, Record<HealthState, number>> }
export interface PredictionTrend { day: string; mean_failure_probability: number | null; elevated: number; high: number; anomalies: number; predictions: number }
export interface SensorTrends {
  equipment_type: string; sensor: string; unit?: string; normal_min?: number; normal_max?: number; equipment?: string[];
  points: Record<string, number | string>[];
}
export interface Backlog {
  by_status: Record<string, number>; by_priority: Record<Priority, number>; overdue: number;
  completed_last_30_days: number; mean_hours_to_complete_last_30_days: number | null;
}
export interface Threshold {
  equipment_type: string; equipment_type_name: string; risk_warning: number; risk_critical: number;
  anomaly_alerts_enabled: boolean; anomaly_score_override: number | null; cooldown_minutes: number;
  model_threshold: number | null; updated_at: string | null;
}
export interface AuditEvent {
  id: number; created_at: string; action: string; entity_type: string; entity_id: string | null;
  actor: string | null; details: Record<string, unknown>; ip_address: string | null;
}
