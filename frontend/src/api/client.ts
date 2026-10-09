/**
 * Thin fetch wrapper. All requests go to the same-origin /api/v1 prefix
 * (proxied by Vite in development and by nginx in the container).
 *
 * The bearer token is kept in sessionStorage: it survives a reload but not a
 * closed tab, and the server can revoke it (logout). See docs/security.md for
 * the trade-offs versus httpOnly cookies.
 */

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api/v1";
const TOKEN_KEY = "mx-token";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: unknown, public requestId?: string) {
    super(message);
  }
}

let unauthorizedHandler: (() => void) | null = null;
export function onUnauthorized(fn: () => void) { unauthorizedHandler = fn; }

export function getToken(): string | null {
  try { return sessionStorage.getItem(TOKEN_KEY); } catch { return null; }
}
export function setToken(token: string | null) {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch { /* storage unavailable: token lives only in memory for this page */ }
}

type Query = Record<string, string | number | boolean | null | undefined | (string | number)[]>;

export function buildUrl(path: string, query?: Query): string {
  const params = new URLSearchParams();
  Object.entries(query ?? {}).forEach(([k, v]) => {
    if (v === undefined || v === null || v === "") return;
    if (Array.isArray(v)) v.forEach((x) => params.append(k, String(x)));
    else params.set(k, String(v));
  });
  const qs = params.toString();
  return `${BASE}${path}${qs ? `?${qs}` : ""}`;
}

async function request<T>(method: string, path: string, opts: { query?: Query; body?: unknown; form?: FormData; raw?: boolean } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(buildUrl(path, opts.query), { method, headers, body });
  } catch {
    throw new ApiError(0, "network_error", "Cannot reach the server. Check your connection.");
  }
  if (res.status === 401 && path !== "/auth/login") unauthorizedHandler?.();
  if (!res.ok) {
    let payload: { error?: { code: string; message: string; details?: unknown; request_id?: string } } = {};
    try { payload = await res.json(); } catch { /* not JSON */ }
    const e = payload.error;
    throw new ApiError(res.status, e?.code ?? "http_error", e?.message ?? `Request failed (${res.status})`, e?.details, e?.request_id);
  }
  if (opts.raw) return res as unknown as T;
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string, query?: Query) => request<T>("GET", path, { query }),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, { body }),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, { body }),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, { body }),
  upload: <T>(path: string, form: FormData) => request<T>("POST", path, { form }),
  download: async (path: string, query?: Query) => {
    const res = await request<Response>("GET", path, { query, raw: true });
    const blob = await res.blob();
    const name = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "")?.[1] ?? "export.csv";
    const url = URL.createObjectURL(blob);
    const a = Object.assign(document.createElement("a"), { href: url, download: name });
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    return name;
  },
};

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    const details = e.details as { errors?: { message: string }[] } | { msg: string; loc: string[] }[] | undefined;
    if (Array.isArray(details) && details.length) return `${e.message}: ${details.map((d) => `${d.loc.slice(1).join(".")} ${d.msg}`).join("; ")}`;
    if (details && !Array.isArray(details) && details.errors?.length) return `${e.message}: ${details.errors[0].message}`;
    return e.message;
  }
  return e instanceof Error ? e.message : "Something went wrong";
}
