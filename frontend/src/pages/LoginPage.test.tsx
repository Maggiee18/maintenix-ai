import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import LoginPage from "./LoginPage";
import { engineer, json, mockApi, renderApp } from "../test/utils";

describe("LoginPage", () => {
  it("validates the form before calling the API", async () => {
    const calls = mockApi({}, null);
    renderApp(<LoginPage />, { route: "/login", path: "/login" });
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(screen.getByRole("alert")).toHaveTextContent(/valid email/i);
    expect(calls.filter((c) => c.path === "/auth/login")).toHaveLength(0);
  });

  it("shows the server error for bad credentials", async () => {
    mockApi({ "POST /auth/login": () => json({ error: { code: "unauthorized", message: "Invalid email or password" } }, 401) }, null);
    renderApp(<LoginPage />, { route: "/login", path: "/login" });
    await userEvent.type(screen.getByLabelText(/email/i), "a@b.com");
    await userEvent.type(screen.getByLabelText(/password/i), "wrong");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password");
  });

  it("logs in and navigates away", async () => {
    const calls = mockApi({ "POST /auth/login": { access_token: "t", token_type: "bearer", expires_at: "2030-01-01T00:00:00Z", user: engineer } }, null);
    renderApp(<LoginPage />, { route: "/login", path: "/login" });
    await userEvent.type(screen.getByLabelText(/email/i), "eng@example.com");
    await userEvent.type(screen.getByLabelText(/password/i), "Secret-pass-1");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => expect(screen.getByText("other page")).toBeInTheDocument());
    expect(calls.find((c) => c.path === "/auth/login")?.body).toEqual({ email: "eng@example.com", password: "Secret-pass-1" });
    expect(sessionStorage.getItem("mx-token")).toBe("t");
  });
});
