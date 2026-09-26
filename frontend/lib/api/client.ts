/**
 * Typed API client. Paths, parameters, bodies and responses all come from
 * `schema.d.ts`, which is generated from the FastAPI OpenAPI schema:
 *
 *   make api-client      (run it after changing any backend route or schema)
 *
 * Every call goes to the same origin (`/api/...`); Next.js forwards it to FastAPI.
 */
import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

export type ErrorResponse = components["schemas"]["ErrorResponse"];

export const api = createClient<paths>({ baseUrl: "" });

/** An API error with the fields from the standard error envelope. */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly requestId: string | null,
    public readonly details: unknown = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function isErrorResponse(value: unknown): value is ErrorResponse {
  if (typeof value !== "object" || value === null || !("error" in value)) return false;
  const inner = (value as { error: unknown }).error;
  return (
    typeof inner === "object" &&
    inner !== null &&
    typeof (inner as { message?: unknown }).message === "string"
  );
}

/** Turn any failed response body into an ApiError with a message people can read. */
export function toApiError(status: number, body: unknown): ApiError {
  if (isErrorResponse(body)) {
    return new ApiError(
      status,
      body.error.code,
      body.error.message,
      body.error.request_id,
      body.error.details ?? null,
    );
  }
  return new ApiError(status, "http_error", `The server answered with ${status}.`, null);
}

export const NETWORK_ERROR_MESSAGE = "Can't reach the server. Check your connection.";

type ClientResult = { data?: unknown; error?: unknown; response: Response };

/**
 * Await a client call and return its data, or throw an ApiError.
 *
 *   const job = await unwrap(api.GET("/api/jobs/{job_id}", { params: { path: { job_id } } }));
 *
 * "204 No Content" (e.g. DELETE) is a success without a body: it resolves to undefined.
 */
export async function unwrap<T extends ClientResult>(
  request: Promise<T>,
): Promise<NonNullable<T["data"]>> {
  let result: T;
  try {
    result = await request;
  } catch {
    throw new ApiError(0, "network_error", NETWORK_ERROR_MESSAGE, null);
  }
  if (result.response.ok && result.data !== undefined) {
    return result.data as NonNullable<T["data"]>;
  }
  if (result.response.status === 204) {
    // The generated type for a 204 response has no data; nothing to return.
    return undefined as unknown as NonNullable<T["data"]>;
  }
  throw toApiError(result.response.status, result.error);
}

/** Field errors from a 422 response: { email: "value is not a valid email address", ... }. */
export function fieldErrors(err: unknown): Record<string, string> {
  if (!(err instanceof ApiError) || err.code !== "validation_error") return {};
  const out: Record<string, string> = {};
  const details = err.details;
  if (Array.isArray(details)) {
    for (const d of details as { field?: string; message?: string }[]) {
      const name = d.field?.split(".").pop();
      if (name && d.message && !out[name]) out[name] = d.message;
    }
  }
  return out;
}

/** A short, user-facing message for any thrown value. */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  return "Something went wrong. Try again.";
}
