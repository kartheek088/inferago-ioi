import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "./api";

/** Load data; optional polling (ms) while `poll` is truthy. Keeps old data visible while reloading. */
export function useQuery<T>(fn: () => Promise<T>, deps: unknown[] = [], poll?: number | false) {
  const [data, setData] = useState<T | undefined>();
  const [error, setError] = useState<ApiError | undefined>();
  const [loading, setLoading] = useState(true);
  const seq = useRef(0);
  const load = useCallback(() => {
    const id = ++seq.current;
    setLoading(true);
    return fn()
      .then((d) => { if (id === seq.current) { setData(d); setError(undefined); } })
      .catch((e: unknown) => { if (id === seq.current) setError(e instanceof ApiError ? e : new ApiError(0, String(e))); })
      .finally(() => { if (id === seq.current) setLoading(false); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!poll) return;
    const t = setInterval(() => { load(); }, poll);
    return () => clearInterval(t);
  }, [poll, load]);
  return { data, error, loading, reload: load, setData };
}

/** Run an action with busy state and a user-facing message. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | undefined>();
  const run = async <T,>(fn: () => Promise<T>, ok?: string): Promise<T | undefined> => {
    setBusy(true);
    setMsg(undefined);
    try {
      const r = await fn();
      if (ok) setMsg({ kind: "ok", text: ok });
      return r;
    } catch (e) {
      setMsg({ kind: "err", text: e instanceof ApiError ? e.message : String(e) });
      return undefined;
    } finally {
      setBusy(false);
    }
  };
  return { busy, msg, run, setMsg };
}
