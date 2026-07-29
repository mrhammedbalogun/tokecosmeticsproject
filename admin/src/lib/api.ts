/**
 * Server-side Django client for the admin app. Server Components, Server Functions and
 * Route Handlers ONLY — it reads `process.env.API_URL`, which is never exposed to the
 * browser. Centralises the base URL, the `/api/v1` prefix, the Bearer header, JSON
 * encode/decode and the error shape so nothing else re-implements any of them.
 *
 * The storefront's equivalent also carries `X-Country` and `X-Cart-Id`. Both are dropped
 * here rather than ported: the admin has no market and no cart, and a header that is
 * always the same default is a thing a future reader has to reason about for nothing.
 */
export class ApiError extends Error {
  constructor(
    public status: number,
    public data: unknown,
  ) {
    super(`API ${status}`);
    this.name = "ApiError";
  }
}

export interface ApiFetchOptions {
  method?: string;
  body?: unknown;
  /** JWT access token → Authorization: Bearer. Omit for anonymous calls. */
  token?: string;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  cache?: RequestCache;
}

/**
 * `API_URL` is the server-side value; `NEXT_PUBLIC_API_URL` is the same URL published to
 * the browser so the topbar can tell staging from production. Reading the public one as a
 * fallback means a deployment that sets only the public variable still works, rather than
 * silently talking to localhost.
 */
export function apiBaseUrl(): string {
  return process.env.API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
}

/**
 * Everything `apiFetch` does up to and including the fetch, returning the Response
 * UNTOUCHED — not parsed, not cloned, not thrown on. The generic BFF proxy uses it so it
 * can pass a backend status and body straight through without re-deciding either.
 */
export async function apiFetchRaw(
  path: string,
  opts: ApiFetchOptions = {},
): Promise<Response> {
  const headers = new Headers(opts.headers);
  headers.set("Accept", "application/json");
  if (opts.token) headers.set("Authorization", `Bearer ${opts.token}`);

  const init: RequestInit = { method: opts.method ?? "GET", headers };
  if (opts.body !== undefined) {
    headers.set("Content-Type", "application/json");
    init.body = JSON.stringify(opts.body);
  }
  if (opts.signal) init.signal = opts.signal;
  // Admin data is never cached by the framework either — see the no-store discussion in
  // `next.config.ts` and `proxy.ts`. A stale order list is worse than a slow one.
  init.cache = opts.cache ?? "no-store";

  return fetch(`${apiBaseUrl()}/api/v1${path}`, init);
}

export async function apiFetch<T = unknown>(
  path: string,
  opts: ApiFetchOptions = {},
): Promise<T> {
  const res = await apiFetchRaw(path, opts);

  // Read from a clone so the original body stream is left undisturbed. Harmless in
  // production (a fresh Response is read once), and it lets tests reuse a single mocked
  // Response across calls.
  const text = await res.clone().text();
  const data = text ? safeJson(text) : null;
  if (!res.ok) throw new ApiError(res.status, data);
  return data as T;
}

/**
 * Release an unwanted Response body by READING it to completion — never by awaiting
 * `body.cancel()`. Next's patched fetch tees response bodies for its cache layer, and a
 * tee branch's cancel() only settles once BOTH branches are cancelled; Next holds the
 * other, so an awaited cancel() blocks until undici's ~300s connection timeout (measured
 * live as a 5-minute stall in the storefront's invoice route). Reading drains the shared
 * source instead, which releases the connection immediately.
 */
export async function drainBody(res: Response): Promise<void> {
  try {
    await res.arrayBuffer();
  } catch {
    // Best-effort: a body that fails to read is already torn down.
  }
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}
