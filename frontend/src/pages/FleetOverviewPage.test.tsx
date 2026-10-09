import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import FleetOverviewPage from "./FleetOverviewPage";
import { json, mockApi, renderApp } from "../test/utils";

const summary = {
  total_equipment: 12, operational: 11, under_maintenance: 1, requiring_attention: 5, high_risk: 3, open_work_orders: 2,
  active_alerts: 7, simulated_equipment: 12, last_prediction_at: new Date().toISOString(), recent_alerts: [], definitions: {},
};

describe("FleetOverviewPage", () => {
  it("renders KPIs from the API and flags simulated data", async () => {
    mockApi({
      "GET /dashboard/summary": summary,
      "GET /dashboard/health-distribution": { overall: { healthy: 7, watch: 1, at_risk: 1, critical: 3, unknown: 0 }, by_type: { Pump: { healthy: 2, watch: 0, at_risk: 1, critical: 1, unknown: 0 } } },
      "GET /dashboard/high-risk": [],
      "GET /dashboard/prediction-trends": [],
      "GET /dashboard/maintenance-backlog": { by_status: { open: 1, assigned: 1, in_progress: 0 }, by_priority: { critical: 0, high: 1, medium: 1, low: 0 }, overdue: 0, completed_last_30_days: 4, mean_hours_to_complete_last_30_days: 5.2 },
      "GET /equipment-types": [],
      "GET /dashboard/sensor-trends": { equipment_type: "centrifugal_pump", sensor: "vibration", points: [] },
    });
    renderApp(<FleetOverviewPage />);
    expect(await screen.findByText("Requiring attention")).toBeInTheDocument();
    expect(screen.getByText("12 of 12")).toBeInTheDocument();
    expect(screen.getByText(/simulated/i, { selector: "strong" })).toBeInTheDocument();
    expect(await screen.findByText("No equipment at risk")).toBeInTheDocument();
    expect(screen.getByText("No active alerts")).toBeInTheDocument();
  });

  it("shows an error state when the API fails", async () => {
    mockApi({ "GET /dashboard/summary": () => json({ error: { code: "internal_error", message: "An unexpected error occurred" } }, 500) });
    renderApp(<FleetOverviewPage />);
    expect((await screen.findAllByRole("alert"))[0]).toHaveTextContent("An unexpected error occurred");
  });
});
