// Small typed client for the IOI 3.0 backend (/api/v3). The UI never talks to external services itself.

const TOKEN_KEY = "ioi_api_token";

export function getToken(): string {
  try { return localStorage.getItem(TOKEN_KEY) ?? ""; } catch { return ""; }
}
export function setToken(t: string) {
  try { localStorage.setItem(TOKEN_KEY, t); } catch { /* storage unavailable */ }
}

// One-time device setup: https://host/#token=XYZ stores the token and removes it from the address bar.
(function bootstrapTokenFromFragment() {
  try {
    const m = window.location.hash.match(/(?:^#|&)token=([A-Za-z0-9_-]{16,200})/);
    if (m) {
      setToken(m[1]);
      window.history.replaceState(null, "", window.location.pathname + window.location.search);
    }
  } catch { /* ignore */ }
})();

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

type Query = Record<string, string | number | boolean | null | undefined>;

function qs(q?: Query) {
  if (!q) return "";
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

async function request<T>(method: string, path: string, opts: { query?: Query; body?: unknown; form?: FormData } = {}): Promise<T> {
  const headers: Record<string, string> = { "X-IOI-Actor": "owner" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(opts.body); }
  let res: Response;
  try {
    res = await fetch(`/api/v3${path}${qs(opts.query)}`, { method, headers, body });
  } catch {
    throw new ApiError(0, "Can't reach the IOI server. Is it running? (Start it with ./start.sh)");
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let data: unknown;
  try { data = text ? JSON.parse(text) : undefined; } catch { data = undefined; }
  if (!res.ok) {
    const detail = (data as { detail?: unknown } | undefined)?.detail;
    const msg = typeof detail === "string" ? detail
      : Array.isArray(detail) ? detail.map((d: { msg: string; loc?: string[] }) => `${d.loc?.slice(-1)[0] ?? ""}: ${d.msg}`).join("; ")
      : res.status === 401 ? "Please sign in" : `Something went wrong (${res.status})`;
    throw new ApiError(res.status, msg);
  }
  return data as T;
}

export const api = {
  get: <T,>(path: string, query?: Query) => request<T>("GET", path, { query }),
  post: <T,>(path: string, body?: unknown) => request<T>("POST", path, { body }),
  put: <T,>(path: string, body?: unknown) => request<T>("PUT", path, { body }),
  patch: <T,>(path: string, body?: unknown) => request<T>("PATCH", path, { body }),
  del: <T,>(path: string) => request<T>("DELETE", path),
  upload: <T,>(path: string, form: FormData) => request<T>("POST", path, { form }),
  url: (path: string) => `/api/v3${path}`,
  /** Download a file the signed-in way (a plain link would not carry the token). */
  download: async (path: string, filename: string) => {
    const token = getToken();
    const res = await fetch(`/api/v3${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
    if (!res.ok) throw new ApiError(res.status, `Download failed (${res.status})`);
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url; a.download = filename; a.click();
    URL.revokeObjectURL(url);
  },
};
