/**
 * Thin fetch wrapper. Centralizes base URL, JSON parsing, error handling,
 * and query-string building so feature code never touches `fetch` directly.
 */

const API_BASE = (import.meta.env.VITE_API_BASE ?? '').replace(/\/$/, '');

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = 'ApiError';
  }
}

type QueryValue = string | number | boolean | null | undefined;

function buildQuery(params?: Record<string, QueryValue>): string {
  if (!params) return '';
  const usp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== null && v !== undefined && v !== '') usp.append(k, String(v));
  }
  const s = usp.toString();
  return s ? `?${s}` : '';
}

async function request<T>(
  path: string,
  opts: { method?: string; params?: Record<string, QueryValue>; body?: unknown } = {},
): Promise<T> {
  const url = `${API_BASE}${path}${buildQuery(opts.params)}`;
  const init: RequestInit = { method: opts.method ?? 'GET', headers: {} };
  if (opts.body !== undefined) {
    init.headers = { 'Content-Type': 'application/json' };
    init.body = JSON.stringify(opts.body);
  }
  const res = await fetch(url, init);
  if (!res.ok) {
    throw new ApiError(res.status, `Request failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

export const http = {
  get: <T>(path: string, params?: Record<string, QueryValue>) => request<T>(path, { params }),
  post: <T>(path: string, body: unknown) => request<T>(path, { method: 'POST', body }),
};

export { API_BASE };
