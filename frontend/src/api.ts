// Thin typed client for the IOI backend. All data shown in the UI comes from these calls.

const TOKEN_KEY = "ioi_api_token";
const ACTOR_KEY = "ioi_actor";

export function getToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}
export function setToken(t: string) {
  try {
    localStorage.setItem(TOKEN_KEY, t);
  } catch {
    /* storage unavailable */
  }
}
export function getActor(): string {
  try {
    return localStorage.getItem(ACTOR_KEY) ?? "owner";
  } catch {
    return "owner";
  }
}
export function setActor(a: string) {
  try {
    localStorage.setItem(ACTOR_KEY, a);
  } catch {
    /* storage unavailable */
  }
}

// One-time device setup: a link like https://host/#token=XYZ stores the token in this browser and
// removes it from the address bar. URL fragments are never sent to the server or written to logs.
(function bootstrapTokenFromFragment() {
  try {
    const m = window.location.hash.match(/(?:^#|&)token=([A-Za-z0-9_-]{16,200})/);
    if (m) {
      setToken(m[1]);
      window.history.replaceState(null, "", window.location.pathname + window.location.search);
    }
  } catch {
    /* ignore */
  }
})();

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;

function qs(q?: Query): string {
  if (!q) return "";
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

async function request<T>(method: string, path: string, opts: { query?: Query; body?: unknown; form?: FormData } = {}): Promise<T> {
  const headers: Record<string, string> = { "X-IOI-Actor": getActor() };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  const res = await fetch(`/api${path}${qs(opts.query)}`, { method, headers, body });
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const data = text ? JSON.parse(text) : undefined;
  if (!res.ok) {
    const detail = data?.detail;
    const msg = typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map((d: { msg: string; loc?: string[] }) => `${d.loc?.slice(-1)[0] ?? ""}: ${d.msg}`).join("; ") : res.statusText;
    throw new ApiError(res.status, msg);
  }
  return data as T;
}

export const api = {
  get: <T>(path: string, query?: Query) => request<T>("GET", path, { query }),
  post: <T>(path: string, body?: unknown, query?: Query) => request<T>("POST", path, { body, query }),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, { body }),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, { body }),
  del: <T>(path: string) => request<T>("DELETE", path),
  upload: <T>(path: string, form: FormData) => request<T>("POST", path, { form }),
};
