/**
 * Thin fetch wrapper around the FastAPI backend.
 *
 * - Injects the bearer token from the in-memory/localStorage session.
 * - Unwraps the `{ status, data }` envelope used by the API.
 * - Normalises errors into `ApiError` so UI code has one shape to handle.
 * - De-duplicates identical in-flight GETs (cheap protection against
 *   several widgets polling the same resource at the same time).
 */

const RAW_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";
export const API_BASE = RAW_BASE.replace(/\/$/, "");

export const AUTH_STORAGE_KEY = "rcs.session";

export class ApiError extends Error {
  status: number;
  code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

let accessToken: string | null = null;
let onUnauthorized: (() => void) | null = null;

export function setAccessToken(token: string | null) {
  accessToken = token;
}

export function getAccessToken() {
  return accessToken;
}

export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler;
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
  /** Skip the shared `{ data }` unwrapping (used for envelope-less routes). */
  raw?: boolean;
}

const inflight = new Map<string, Promise<unknown>>();

async function parseError(response: Response): Promise<ApiError> {
  let message = `${response.status} ${response.statusText}`;
  let code: string | undefined;
  try {
    const payload = await response.json();
    const detail = payload?.detail ?? payload?.message ?? payload?.error;
    if (typeof detail === "string") message = detail;
    else if (Array.isArray(detail) && detail[0]?.msg) message = String(detail[0].msg);
    if (typeof payload?.code === "string") code = payload.code;
  } catch {
    /* body was not JSON — keep the status line */
  }
  return new ApiError(message, response.status, code);
}

async function execute<T>(path: string, options: RequestOptions): Promise<T> {
  const { method = "GET", body, signal, raw } = options;

  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;

  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    signal,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (response.status === 401) {
    onUnauthorized?.();
    throw await parseError(response);
  }
  if (!response.ok) throw await parseError(response);
  if (response.status === 204) return undefined as T;

  const payload = await response.json();
  if (!raw && payload && typeof payload === "object" && "data" in payload) {
    return payload.data as T;
  }
  return payload as T;
}

/**
 * Multipart POST (file uploads). FormData sets its own `Content-Type` with the
 * boundary, so it must not be overridden by the JSON header logic above.
 */
async function uploadRequest<T>(path: string, formData: FormData): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;

  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers,
    body: formData,
  });

  if (response.status === 401) {
    onUnauthorized?.();
    throw await parseError(response);
  }
  if (!response.ok) throw await parseError(response);

  const payload = await response.json();
  if (payload && typeof payload === "object" && "data" in payload) {
    return payload.data as T;
  }
  return payload as T;
}

export function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? "GET";
  if (method !== "GET") return execute<T>(path, options);

  const key = `${path}|${accessToken ? "auth" : "anon"}`;
  const existing = inflight.get(key);
  if (existing) return existing as Promise<T>;

  const promise = execute<T>(path, options).finally(() => inflight.delete(key));
  inflight.set(key, promise);
  return promise as Promise<T>;
}

export const api = {
  get: <T>(path: string, signal?: AbortSignal) => apiRequest<T>(path, { signal }),
  post: <T>(path: string, body?: unknown) => apiRequest<T>(path, { method: "POST", body }),
  patch: <T>(path: string, body?: unknown) => apiRequest<T>(path, { method: "PATCH", body }),
  del: <T>(path: string) => apiRequest<T>(path, { method: "DELETE" }),
  raw: <T>(path: string, body?: unknown) =>
    apiRequest<T>(path, { method: body === undefined ? "GET" : "POST", body, raw: true }),
  upload: <T>(path: string, formData: FormData) => uploadRequest<T>(path, formData),
};

/** Authenticated file download (a plain <a href> cannot send the bearer token). */
export async function downloadFile(path: string, fallbackName: string): Promise<void> {
  const headers: Record<string, string> = {};
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  const response = await fetch(`${API_BASE}${path}`, { headers });
  if (response.status === 401) {
    onUnauthorized?.();
    throw await parseError(response);
  }
  if (!response.ok) throw await parseError(response);
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const name = /filename="?([^";]+)"?/.exec(disposition)?.[1] ?? fallbackName;
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
