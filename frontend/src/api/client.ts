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

// --- Phase 1: Ingestion API ---

/** Ingest request body. */
export interface IngestRequest {
  paths: string[];
  options?: {
    convert_aac_to_mp3?: boolean;
  };
}

/** Ingest response. */
export interface IngestResponse {
  batch_id: string;
  total_files: number;
  message: string;
}

/** Track as returned by the API. */
export interface Track {
  id: number;
  file_path: string;
  source_path: string | null;
  source_format: string | null;
  source_codec: string | null;
  source_bitrate: number | null;
  output_format: string | null;
  duration: number | null;
  quality_warning: boolean;
  conversion_action: string | null;
  imported_at: string | null;
}

/** Track list response with pagination. */
export interface TrackListResponse {
  tracks: Track[];
  total: number;
  limit: number;
  offset: number;
}

/** SSE progress event data. */
export interface FileProgressEvent {
  file_path: string;
  status: "queued" | "processing" | "complete" | "failed" | "skipped";
  action: string;
  message: string;
  error?: string;
  batch_progress: {
    completed: number;
    total: number;
    failed: number;
    duplicates: number;
  };
}

/** Start ingesting files. */
export function postIngest(body: IngestRequest): Promise<IngestResponse> {
  return request<IngestResponse>("/api/ingest", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** Cancel current batch. */
export function postIngestCancel(): Promise<{ status: string; message: string }> {
  return request<{ status: string; message: string }>("/api/ingest/cancel", {
    method: "POST",
  });
}

/** List all tracks with pagination. */
export function getTracks(
  limit = 50,
  offset = 0,
): Promise<TrackListResponse> {
  return request<TrackListResponse>(
    `/api/tracks?limit=${limit}&offset=${offset}`,
  );
}

/** Connect to SSE progress stream. Returns an EventSource. */
export function connectProgress(
  onEvent: (event: FileProgressEvent) => void,
  onBatchComplete?: (data: {
    total: number;
    succeeded: number;
    failed: number;
    duplicates: number;
  }) => void,
): EventSource {
  const es = new EventSource(`${BASE_URL}/api/ingest/progress`);

  es.addEventListener("file_progress", (e) => {
    const data = JSON.parse(e.data) as FileProgressEvent;
    onEvent(data);
  });

  es.addEventListener("batch_complete", (e) => {
    const data = JSON.parse(e.data);
    onBatchComplete?.(data);
    es.close();
  });

  es.addEventListener("error", () => {
    es.close();
  });

  return es;
}
