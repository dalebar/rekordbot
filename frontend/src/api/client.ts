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
const BASE_URL = import.meta.env.DEV ? "http://127.0.0.1:8420" : "http://127.0.0.1:8420";

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

// --- Phase 2: Tagging & Analysis API ---

/** Track as returned by the enhanced API. */
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

  // Metadata
  title: string | null;
  artist: string | null;
  album: string | null;
  album_artist: string | null;
  genre: string | null;
  year: number | null;
  track_number: number | null;
  comment: string | null;
  label: string | null;
  bpm: number | null;
  key: number | null;
  key_display: string | null;
  rating: number;

  // Analysis
  analysis_status: string;
  bpm_confidence: number | null;
  key_confidence: number | null;
  source_bpm: number | null;
  source_key: number | null;
  has_bpm_conflict: boolean;
  has_key_conflict: boolean;

  // AI tagging
  subgenre: string | null;
  mood: string | null;
  energy: number | null;
  ai_confidence: string | null;
  ai_reasoning: string | null;
  source_genre: string | null;
  ai_status: string;
}

/** Track list response with pagination. */
export interface TrackListResponse {
  tracks: Track[];
  total: number;
  limit: number;
  offset: number;
}

/** List all tracks with pagination. */
export function getTracks(limit = 50, offset = 0): Promise<TrackListResponse> {
  return request<TrackListResponse>(`/api/tracks?limit=${limit}&offset=${offset}`);
}

/** Analysis request body. */
export interface AnalyseRequest {
  track_ids?: number[];
  options?: {
    bpm_range_min?: number;
    bpm_range_max?: number;
    skip_if_analysed?: boolean;
  };
}

/** Analysis response. */
export interface AnalyseResponse {
  batch_id: string;
  total_tracks: number;
  message: string;
}

/** Start analysing tracks. */
export function postAnalyse(body: AnalyseRequest): Promise<AnalyseResponse> {
  return request<AnalyseResponse>("/api/tracks/analyse", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** Cancel current analysis batch. */
export function postAnalyseCancel(): Promise<{ status: string; message: string }> {
  return request<{ status: string; message: string }>("/api/tracks/analyse/cancel", {
    method: "POST",
  });
}

/** Write tags request body. */
export interface WriteTagsRequest {
  track_ids: number[];
}

/** Write tags response. */
export interface WriteTagsResponse {
  total: number;
  succeeded: number;
  failed: number;
}

/** Write tags to files for selected tracks. */
export function postWriteTags(body: WriteTagsRequest): Promise<WriteTagsResponse> {
  return request<WriteTagsResponse>("/api/tracks/write-tags", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** Partial track update body. */
export interface TrackUpdate {
  title?: string;
  artist?: string;
  album?: string;
  genre?: string;
  year?: number;
  track_number?: number;
  comment?: string;
  label?: string;
  bpm?: number;
  key?: number;
  rating?: number;
  subgenre?: string;
  mood?: string;
  energy?: number;
}

/** Update a single track's metadata. */
export function updateTrack(trackId: number, update: TrackUpdate): Promise<Track> {
  return request<Track>(`/api/tracks/${trackId}`, {
    method: "PUT",
    body: JSON.stringify(update),
  });
}

/** Revert a field to its source value. */
export function revertField(trackId: number, field: "bpm" | "key" | "genre"): Promise<Track> {
  return request<Track>(`/api/tracks/${trackId}/revert/${field}`, {
    method: "PUT",
  });
}

/** Multiply BPM by a factor (2 or 0.5). */
export function bpmMultiply(trackId: number, factor: 2 | 0.5): Promise<Track> {
  return request<Track>(`/api/tracks/${trackId}/bpm-multiply`, {
    method: "PUT",
    body: JSON.stringify({ factor }),
  });
}

/** SSE analysis progress event data. */
export interface AnalysisProgressEvent {
  track_id: number;
  status: "queued" | "processing" | "complete" | "failed";
  message: string;
  error?: string;
  batch_progress: {
    completed: number;
    total: number;
    failed: number;
  };
}

/** Connect to analysis SSE progress stream. Returns an EventSource. */
export function connectAnalysisProgress(
  onEvent: (event: AnalysisProgressEvent) => void,
  onBatchComplete?: (data: { total: number; succeeded: number; failed: number }) => void,
): EventSource {
  const es = new EventSource(`${BASE_URL}/api/tracks/analyse/progress`);

  const eventTypes = [
    "analysis_queued",
    "analysis_processing",
    "analysis_complete",
    "analysis_failed",
  ];
  for (const eventType of eventTypes) {
    es.addEventListener(eventType, (e) => {
      const data = JSON.parse(e.data) as AnalysisProgressEvent;
      onEvent(data);
    });
  }

  es.addEventListener("analysis_batch_complete", (e) => {
    const data = JSON.parse(e.data);
    onBatchComplete?.(data);
    es.close();
  });

  es.addEventListener("error", () => {
    es.close();
  });

  return es;
}

// --- Phase 3: AI Tagging API ---

/** AI tag request body. */
export interface AiTagRequest {
  track_ids?: number[];
  options?: {
    skip_if_tagged?: boolean;
    model?: string;
  };
}

/** AI tag response. */
export interface AiTagResponse {
  batch_id: string;
  total_tracks: number;
  total_batches: number;
  message: string;
}

/** AI tag status response. */
export interface AiTagStatus {
  status: string;
  token_usage?: {
    total_input_tokens: number;
    total_output_tokens: number;
    total_requests: number;
    estimated_cost_usd: number;
  };
}

/** AI tag progress event data. */
export interface AiTagProgressEvent {
  batch_number: number;
  total_batches: number;
  tracks_tagged: number;
  tracks_total: number;
  tracks_failed: number;
  token_usage: {
    input_tokens: number;
    output_tokens: number;
    estimated_cost_usd: number;
  };
}

/** AI tag complete event data. */
export interface AiTagCompleteEvent {
  total_tracks: number;
  succeeded: number;
  failed: number;
  total_batches: number;
  token_usage: {
    input_tokens: number;
    output_tokens: number;
    estimated_cost_usd: number;
  };
}

/** Validate key response. */
export interface ValidateKeyResponse {
  valid: boolean;
  model?: string;
  error?: string;
}

/** Start AI tagging tracks. */
export function postAiTag(body: AiTagRequest): Promise<AiTagResponse> {
  return request<AiTagResponse>("/api/tracks/ai-tag", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** Cancel current AI tagging batch. */
export function postAiTagCancel(): Promise<{ status: string; message: string }> {
  return request<{ status: string; message: string }>("/api/tracks/ai-tag/cancel", {
    method: "POST",
  });
}

/** Get AI tagging status. */
export function getAiTagStatus(): Promise<AiTagStatus> {
  return request<AiTagStatus>("/api/tracks/ai-tag/status");
}

/** Validate the configured API key. */
export function postValidateApiKey(): Promise<ValidateKeyResponse> {
  return request<ValidateKeyResponse>("/api/tracks/ai-tag/validate-key", {
    method: "POST",
  });
}

/** Connect to AI tag SSE progress stream. Returns an EventSource. */
export function connectAiTagProgress(
  onEvent: (event: AiTagProgressEvent) => void,
  onComplete?: (data: AiTagCompleteEvent) => void,
): EventSource {
  const es = new EventSource(`${BASE_URL}/api/tracks/ai-tag/progress`);

  es.addEventListener("ai_tag_batch_progress", (e) => {
    const data = JSON.parse(e.data) as AiTagProgressEvent;
    onEvent(data);
  });

  es.addEventListener("ai_tag_complete", (e) => {
    const data = JSON.parse(e.data) as AiTagCompleteEvent;
    onComplete?.(data);
    es.close();
  });

  es.addEventListener("error", () => {
    es.close();
  });

  return es;
}
