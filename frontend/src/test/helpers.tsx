import { render } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";
import type { ReactNode } from "react";

/** Route fetch("/api/v3/...") calls to canned JSON responses. */
export function mockApi(routes: Record<string, unknown | ((init?: RequestInit) => unknown)>) {
  const calls: { url: string; method: string; body?: unknown }[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input).replace(/^\/api\/v3/, "");
    const path = url.split("?")[0];
    const method = init?.method ?? "GET";
    calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const key = `${method} ${path}`;
    const hit = routes[key] ?? routes[path];
    if (hit === undefined) return new Response(JSON.stringify({ detail: `no mock for ${key}` }), { status: 404 });
    const body = typeof hit === "function" ? (hit as (i?: RequestInit) => unknown)(init) : hit;
    if (body instanceof Response) return body;
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  });
  return calls;
}

export function renderAt(path: string, routePath: string, el: ReactNode) {
  return render(<MemoryRouter initialEntries={[path]}><Routes><Route path={routePath} element={el} /></Routes></MemoryRouter>);
}
