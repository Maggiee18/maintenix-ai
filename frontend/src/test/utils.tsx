import type { ReactElement } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";
import { AuthProvider } from "../lib/auth";
import type { User } from "../api/types";

export const engineer: User = { id: 2, email: "eng@example.com", full_name: "Eng User", role: "engineer", is_active: true, last_login_at: null, created_at: "2026-01-01T00:00:00Z" };

type Handler = (url: URL, init: RequestInit | undefined) => unknown | Promise<unknown>;
export interface Call { method: string; path: string; body: unknown }

/** Route fetch calls to handlers keyed by "METHOD /path" (path without /api/v1). Returns the call log. */
export function mockApi(routes: Record<string, Handler | unknown>, user: User | null = engineer): Call[] {
  const calls: Call[] = [];
  if (user) sessionStorage.setItem("mx-token", "test-token");
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const path = url.pathname.replace("/api/v1", "");
    const method = (init?.method ?? "GET").toUpperCase();
    calls.push({ method, path, body: typeof init?.body === "string" ? JSON.parse(init.body) : init?.body });
    const key = `${method} ${path}`;
    if (key === "GET /auth/me" && user && !(key in routes)) return json(user);
    if (!(key in routes)) return json({ error: { code: "not_found", message: `no mock for ${key}` } }, 404);
    const h = routes[key];
    const out = typeof h === "function" ? await (h as Handler)(url, init) : h;
    return out instanceof Response ? out : json(out);
  });
  return calls;
}

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

export function renderApp(ui: ReactElement, { route = "/", path = "/" }: { route?: string; path?: string } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[route]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AuthProvider>
          <Routes><Route path={path} element={ui} /><Route path="*" element={<div>other page</div>} /></Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
