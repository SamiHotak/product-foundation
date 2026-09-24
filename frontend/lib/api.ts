/**
 * Minimal API helper. Phase 1B replaces the hand-written types below with a
 * client generated from the FastAPI OpenAPI schema.
 *
 * All calls go to the same origin (`/api/...`); Next.js forwards them to FastAPI.
 */

export type ApiErrorBody = {
  error: { code: string; message: string; request_id: string | null; details?: unknown };
};

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly requestId: string | null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function isApiErrorBody(value: unknown): value is ApiErrorBody {
  return (
    typeof value === "object" &&
    value !== null &&
    "error" in value &&
    typeof (value as ApiErrorBody).error?.message === "string"
  );
}

/**
 * Fetch JSON from the API. Throws ApiError for non-2xx responses, unless the
 * status is listed in `acceptStatuses` (e.g. readiness returns a useful body with 503).
 */
export async function apiGet<T>(
  path: string,
  init?: RequestInit & { acceptStatuses?: number[] },
): Promise<T> {
  const { acceptStatuses = [], ...rest } = init ?? {};
  let res: Response;
  try {
    res = await fetch(`/api${path}`, { ...rest, headers: { Accept: "application/json" } });
  } catch {
    throw new ApiError(0, "network_error", "Can't reach the server. Check your connection.", null);
  }
  const body: unknown = await res.json().catch(() => null);
  if (res.ok || acceptStatuses.includes(res.status)) return body as T;
  if (isApiErrorBody(body)) {
    throw new ApiError(res.status, body.error.code, body.error.message, body.error.request_id);
  }
  throw new ApiError(res.status, "http_error", `The server answered with ${res.status}.`, null);
}

// --- Types (hand-written for now; generated in phase 1B) ---

export type DependencyCheck = {
  name: string;
  status: "ok" | "error";
  latency_ms: number | null;
  error: string | null;
};

export type ReadinessResponse = {
  status: "ok" | "error";
  version: string;
  environment: string;
  checks: DependencyCheck[];
};
