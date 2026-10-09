import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { WorkOrderDetail } from "../api/types";
import WorkOrdersPage from "./WorkOrdersPage";
import { mockApi, renderApp } from "../test/utils";

const base: WorkOrderDetail = {
  id: 7, code: "WO-000007", equipment_id: 3, equipment_code: "PMP-103", equipment_name: "Feed pump", alert_id: null, prediction_id: null,
  title: "Inspect bearing", description: "", priority: "high", status: "in_progress", assigned_to: { id: 2, full_name: "Eng User", role: "engineer" },
  created_by: null, due_date: null, overdue: false, created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z",
  started_at: "2026-10-02T00:00:00Z", completed_at: null, cancelled_at: null, cancel_reason: null, allowed_transitions: ["complete", "cancel"],
  events: [{ id: 1, from_status: null, to_status: "open", actor: "Eng User", note: null, created_at: "2026-10-01T00:00:00Z" }], record: null,
};

describe("WorkOrdersPage", () => {
  it("lists work orders and completes one with validation", async () => {
    const calls = mockApi({
      "GET /work-orders": { items: [base], total: 1, page: 1, page_size: 20 },
      "GET /work-orders/7": base,
      "GET /users/assignable": [],
      "POST /work-orders/7/complete": { ...base, status: "completed", allowed_transitions: [] },
    });
    renderApp(<WorkOrdersPage />, { route: "/work-orders", path: "/work-orders" });
    await userEvent.click(await screen.findByRole("button", { name: "WO-000007" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: /record completion/i }));
    await userEvent.click(within(dialog).getByRole("button", { name: /complete work order/i }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent(/describe the work/i);
    await userEvent.type(within(dialog).getByLabelText(/work performed/i), "Replaced the bearing");
    await userEvent.click(within(dialog).getByLabelText(/restores equipment health/i));
    await userEvent.click(within(dialog).getByRole("button", { name: /complete work order/i }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/work-orders/7/complete")).toBe(true));
    const body = calls.find((c) => c.path === "/work-orders/7/complete")!.body as Record<string, unknown>;
    expect(body).toMatchObject({ action_taken: "inspection", summary: "Replaced the bearing", restores_health: true, downtime_hours: 0 });
  });

  it("requires a reason to cancel", async () => {
    mockApi({ "GET /work-orders": { items: [base], total: 1, page: 1, page_size: 20 }, "GET /work-orders/7": base, "GET /users/assignable": [] });
    renderApp(<WorkOrdersPage />, { route: "/work-orders?open=7", path: "/work-orders" });
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(await within(dialog).findByRole("button", { name: /^cancel work order$/i }));
    const confirm = within(dialog).getAllByRole("button", { name: /^cancel work order$/i }).at(-1)!;
    expect(confirm).toBeDisabled();
  });

  it("shows an empty state", async () => {
    mockApi({ "GET /work-orders": { items: [], total: 0, page: 1, page_size: 20 } });
    renderApp(<WorkOrdersPage />, { route: "/work-orders", path: "/work-orders" });
    expect(await screen.findByText("No work orders match")).toBeInTheDocument();
  });
});
