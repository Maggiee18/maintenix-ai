import { expect, test, type Page } from "@playwright/test";

const ADMIN = { email: process.env.E2E_ADMIN_EMAIL ?? "admin@example.com", password: process.env.E2E_ADMIN_PASSWORD ?? "" };
const DEMO_PASSWORD = process.env.E2E_DEMO_PASSWORD ?? "";

async function login(page: Page, email: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Fleet overview" })).toBeVisible();
}

test.beforeAll(() => {
  if (!ADMIN.password || !DEMO_PASSWORD) throw new Error("Set E2E_ADMIN_PASSWORD and E2E_DEMO_PASSWORD");
});

test("fleet overview shows backend KPIs and the simulated-data notice", async ({ page }) => {
  await login(page, "engineer@example.com", DEMO_PASSWORD);
  await expect(page.getByText(/use simulated sensor data|simulated/i).first()).toBeVisible();
  await expect(page.getByText("Total equipment")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Highest-risk equipment" })).toBeVisible();
});

test("alert -> work order -> assign -> start -> complete resolves the alert", async ({ page }) => {
  await login(page, "engineer@example.com", DEMO_PASSWORD);
  await page.goto("/predictions");
  const alerts = page.locator("section", { has: page.getByRole("heading", { name: "Active failure-risk alerts" }) });
  const alertItem = alerts.locator("li").filter({ has: page.getByRole("button", { name: "Create work order" }) }).first();
  const createBtn = alertItem.getByRole("button", { name: "Create work order" });
  await expect(createBtn).toBeVisible();
  const code = (await alertItem.getByRole("link").first().textContent())!.trim();
  await createBtn.click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Assign to").selectOption({ label: "Priya Raman (engineer)" });
  await dialog.getByRole("button", { name: "Create work order" }).click();
  await expect(dialog).toBeHidden();

  await page.goto("/work-orders");
  await page.getByPlaceholder("Search code, title, equipment").fill(code);
  const row = page.getByRole("row").filter({ hasText: code }).first();
  await row.getByRole("button").first().click();
  const wo = page.getByRole("dialog");
  await wo.getByRole("button", { name: "Start work" }).click();
  await wo.getByRole("button", { name: "Record completion" }).click();
  await wo.getByLabel("Action taken").selectOption("replacement");
  await wo.getByLabel("Work performed").fill("Replaced worn bearing, verified vibration levels");
  await wo.getByLabel(/Restores equipment health/).check();
  await wo.getByRole("button", { name: "Complete work order" }).click();
  await expect(wo.getByText("Completed", { exact: true }).first()).toBeVisible();

  await page.goto("/equipment");
  await page.getByLabel("Search equipment").fill(code);
  await page.getByLabel("Search equipment").press("Enter");
  await page.getByRole("link", { name: code }).click();
  await page.getByRole("tab", { name: /Maintenance/ }).click();
  await expect(page.getByText("Replaced worn bearing, verified vibration levels")).toBeVisible();
});

test("viewer has read-only access and no admin page", async ({ page }) => {
  await login(page, "viewer@example.com", DEMO_PASSWORD);
  await expect(page.getByRole("link", { name: "Administration" })).toHaveCount(0);
  await page.goto("/equipment");
  await expect(page.getByRole("button", { name: "Register equipment" })).toHaveCount(0);
  await page.goto("/admin");
  await expect(page.getByText("You need the administrator role")).toBeVisible();
});

test("admin can review models and the audit log", async ({ page }) => {
  await login(page, ADMIN.email, ADMIN.password);
  await page.goto("/models");
  await expect(page.getByText("Confusion matrix", { exact: false })).toBeVisible();
  await page.goto("/admin");
  await page.getByRole("tab", { name: "Audit log" }).click();
  await expect(page.getByText("auth.login").first()).toBeVisible();
});

test("invalid login shows an error", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("nobody@example.com");
  await page.getByLabel("Password").fill("wrong-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toHaveText(/Invalid email or password/);
});
