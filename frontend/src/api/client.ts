/**
 * Typed API client for communicating with the rekordbot backend.
 */

/** Standard error response from the backend. */
export interface ApiError {
  error: string;
  detail: string;
}

/** Health check response. */
export interface HealthResponse {
  status: string;
  version: string;
}

/** Base URL for the backend API. */
const BASE_URL = import.meta.env.DEV
  ? "http://127.0.0.1:8420"
  : "http://127.0.0.1:8420";

/**
 * Typed fetch wrapper that handles error responses.
 * Throws an ApiError-shaped object on non-2xx responses.
 */
async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });

  if (!response.ok) {
    const errorBody: ApiError = await response.json().catch(() => ({
      error: "unknown",
      detail: `HTTP ${response.status}`,
    }));
    throw errorBody;
  }

  return response.json() as Promise<T>;
}

/** Check backend health. */
export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/health");
}

/** Request graceful backend shutdown. */
export function postShutdown(): Promise<{ status: string }> {
  return request<{ status: string }>("/shutdown", { method: "POST" });
}
