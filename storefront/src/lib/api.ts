/**
 * Server-side Django client. Used by Server Components and Route Handlers ONLY
 * (it reads process.env.API_URL, which is not exposed to the browser). Centralises
 * the base URL, the /api/v1 prefix, the X-Country header, the Bearer header, JSON
 * encode/decode, and the error shape so no other file re-implements any of it.
 */
const DEFAULT_COUNTRY = "NG";

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
  /** Market code forwarded as X-Country (defaults to NG). */
  country?: string;
  /** JWT access token → Authorization: Bearer. Omit for anonymous calls. */
  token?: string;
  /** Guest cart id → X-Cart-Id (cart calls only). */
  cartId?: string;
  /** Next.js fetch cache options, e.g. { next: { revalidate: 3600 } }. */
  next?: NextFetchRequestConfig;
  cache?: RequestCache;
  headers?: Record<string, string>;
}

function baseUrl(): string {
  return process.env.API_URL ?? "http://localhost:8000";
}

export async function apiFetch<T = unknown>(
  path: string,
  opts: ApiFetchOptions = {},
): Promise<T> {
  const headers = new Headers(opts.headers);
  headers.set("Accept", "application/json");
  headers.set("X-Country", opts.country ?? DEFAULT_COUNTRY);
  if (opts.token) headers.set("Authorization", `Bearer ${opts.token}`);
  if (opts.cartId) headers.set("X-Cart-Id", opts.cartId);

  const init: RequestInit = { method: opts.method ?? "GET", headers };
  if (opts.body !== undefined) {
    headers.set("Content-Type", "application/json");
    init.body = JSON.stringify(opts.body);
  }
  if (opts.next) (init as { next?: NextFetchRequestConfig }).next = opts.next;
  if (opts.cache) init.cache = opts.cache;

  const res = await fetch(`${baseUrl()}/api/v1${path}`, init);

  // Read from a clone so the original body stream is left undisturbed. Harmless
  // in production (a fresh Response is read once), and it lets tests that reuse a
  // single mocked Response across calls read the body more than once.
  const text = await res.clone().text();
  const data = text ? safeJson(text) : null;
  if (!res.ok) throw new ApiError(res.status, data);
  return data as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}
