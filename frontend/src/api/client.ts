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
 * Global error callback — set by the toast system to auto-show errors.
 * Components don't need to handle API errors individually when this is set.
 */
let onApiError: ((error: ApiError) => void) | null = null;

/** Register a global API error handler (called by ToastProvider). */
export function setApiErrorHandler(handler: (error: ApiError) => void): void {
  onApiError = handler;
}

/** Clear the global API error handler. */
export function clearApiErrorHandler(): void {
  onApiError = null;
}

/**
 * Typed fetch wrapper that handles error responses.
 * Throws an ApiError-shaped object on non-2xx responses.
 * Also calls the global error handler if registered.
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
    onApiError?.(errorBody);
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

  // Organisation
  organisation_status: string;
  proposed_path: string | null;
  previous_output_path: string | null;
  organisation_confidence: number | null;
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

// --- Phase 2b: Organisation API ---

/** Organisation proposal request body. */
export interface OrganiseRequest {
  track_ids?: number[];
  options?: {
    use_claude?: boolean;
    skip_if_organised?: boolean;
    confidence_threshold?: number;
  };
}

/** Organisation proposal response. */
export interface OrganiseResponse {
  batch_id: string;
  total_tracks: number;
  message: string;
}

/** A single track in the proposal. */
export interface ProposalTrack {
  track_id: number;
  title: string | null;
  artist: string | null;
  current_path: string;
  proposed_path: string | null;
  confidence: number | null;
  reasoning: string | null;
  flags: string[] | null;
}

/** Full proposal response. */
export interface ProposalResponse {
  auto_approved: ProposalTrack[];
  needs_review: ProposalTrack[];
  failed: ProposalTrack[];
  summary: {
    total: number;
    auto_approved: number;
    needs_review: number;
    failed: number;
  };
}

/** Approve request body. */
export interface ApproveRequest {
  mode: "auto_approved" | "specific" | "all";
  track_ids?: number[];
}

/** Approve response. */
export interface ApproveResponse {
  total_moved: number;
  failed: number;
  dirs_cleaned: number;
  message: string;
}

/** Resolve request body. */
export interface ResolveRequest {
  action: "accept" | "custom" | "skip";
  custom_path?: string;
  save_preference?: boolean;
  preference_type?: string;
}

/** Preference rule. */
export interface PreferenceRule {
  id: number;
  rule_type: string;
  key: string;
  value: string;
  created_at: string | null;
}

/** Create preference rule request. */
export interface PreferenceRuleCreate {
  rule_type: string;
  key: string;
  value: string;
}

/** Organisation progress event data. */
export interface OrganiseProgressEvent {
  phase: string;
  tracks_processed: number;
  tracks_total: number;
  auto_approved: number;
  needs_review: number;
  failed: number;
}

/** Start organisation proposal. */
export function postOrganisePropose(body: OrganiseRequest): Promise<OrganiseResponse> {
  return request<OrganiseResponse>("/api/organise/propose", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** Cancel current organisation operation. */
export function postOrganiseCancel(): Promise<{ status: string; message: string }> {
  return request<{ status: string; message: string }>("/api/organise/cancel", {
    method: "POST",
  });
}

/** Get current proposal. */
export function getOrganiseProposal(): Promise<ProposalResponse> {
  return request<ProposalResponse>("/api/organise/proposal");
}

/** Approve and execute file moves. */
export function postOrganiseApprove(body: ApproveRequest): Promise<ApproveResponse> {
  return request<ApproveResponse>("/api/organise/approve", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** Resolve an ambiguous track. */
export function postOrganiseResolve(
  trackId: number,
  body: ResolveRequest,
): Promise<{ status: string; track_id: number; action: string; organisation_status: string }> {
  return request("/api/organise/resolve/" + trackId, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** List preference rules. */
export function getPreferences(ruleType?: string): Promise<PreferenceRule[]> {
  const params = ruleType ? `?rule_type=${ruleType}` : "";
  return request<PreferenceRule[]>(`/api/preferences${params}`);
}

/** Create a preference rule. */
export function postPreference(body: PreferenceRuleCreate): Promise<PreferenceRule> {
  return request<PreferenceRule>("/api/preferences", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** Delete a preference rule. */
export function deletePreference(ruleId: number): Promise<{ status: string; rule_id: number }> {
  return request(`/api/preferences/${ruleId}`, { method: "DELETE" });
}

// --- Phase 4: Rekordbox XML Export API ---

/** Export result from the backend. */
export interface ExportResult {
  tracks_exported: number;
  tracks_skipped: number;
  playlists_created: number;
  output_path: string;
  warnings: string[];
}

/** Export status response. */
export interface ExportStatus {
  status: string;
  last_export: {
    timestamp: string;
    tracks_exported: number;
    output_path: string;
  } | null;
}

/** Export request options. */
export interface ExportOptions {
  track_ids?: number[];
  output_path?: string;
}

/** Trigger Rekordbox XML export. */
export function exportRekordboxXml(options?: ExportOptions): Promise<ExportResult> {
  return request<ExportResult>("/api/export/rekordbox", {
    method: "POST",
    body: JSON.stringify(options ? { options } : {}),
  });
}

/** Get export status. */
export function getExportStatus(): Promise<ExportStatus> {
  return request<ExportStatus>("/api/export/rekordbox/status");
}

/** Connect to organisation SSE progress stream. Returns an EventSource. */
export function connectOrganiseProgress(
  onEvent: (event: OrganiseProgressEvent) => void,
  onProposalComplete?: (data: OrganiseProgressEvent) => void,
  onMoveComplete?: (data: {
    phase: string;
    files_moved: number;
    files_total: number;
    files_failed: number;
    dirs_cleaned: number;
  }) => void,
): EventSource {
  const es = new EventSource(`${BASE_URL}/api/organise/progress`);

  es.addEventListener("organise_progress", (e) => {
    const data = JSON.parse(e.data) as OrganiseProgressEvent;
    onEvent(data);
  });

  es.addEventListener("organise_propose_complete", (e) => {
    const data = JSON.parse(e.data) as OrganiseProgressEvent;
    onProposalComplete?.(data);
    es.close();
  });

  es.addEventListener("organise_move_complete", (e) => {
    const data = JSON.parse(e.data);
    onMoveComplete?.(data);
    es.close();
  });

  es.addEventListener("error", () => {
    es.close();
  });

  return es;
}

// --- Phase 5a: Crate Builder API ---

/** Crate summary (list view). */
export interface CrateSummary {
  id: number;
  name: string;
  description: string;
  track_count: number;
  auto_refresh: boolean;
  created_at: string;
  updated_at: string;
}

/** Crate detail (full view). */
export interface CrateDetail {
  id: number;
  name: string;
  description: string;
  parsed_criteria: Record<string, unknown> | null;
  auto_refresh: boolean;
  track_ids: number[];
  track_count: number;
  created_at: string;
  updated_at: string;
}

/** Crate create request. */
export interface CrateCreateRequest {
  name: string;
  description: string;
  auto_refresh?: boolean;
}

/** Crate create response. */
export interface CrateCreateResponse {
  id: number;
  name: string;
  description: string;
  auto_refresh: boolean;
  message: string;
}

/** Crate update request. */
export interface CrateUpdateRequest {
  name?: string;
  description?: string;
  auto_refresh?: boolean;
}

/** Crate update response. */
export interface CrateUpdateResponse {
  id: number;
  name: string;
  description: string;
  auto_refresh: boolean;
  description_changed: boolean;
  message: string;
}

/** Crate assignment progress event. */
export interface CrateAssignmentProgress {
  crate_id: number;
  batch_number: number;
  total_batches: number;
  tracks_processed: number;
  tracks_total: number;
}

/** Crate assignment complete event. */
export interface CrateAssignmentComplete {
  crate_id: number;
  total_tracks: number;
  matched: number;
  total_batches: number;
  errors: string[];
}

/** List all crates. */
export function listCrates(): Promise<CrateSummary[]> {
  return request<CrateSummary[]>("/api/crates");
}

/** Get crate detail. */
export function getCrate(crateId: number): Promise<CrateDetail> {
  return request<CrateDetail>(`/api/crates/${crateId}`);
}

/** Create a new crate. */
export function createCrate(body: CrateCreateRequest): Promise<CrateCreateResponse> {
  return request<CrateCreateResponse>("/api/crates", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** Update a crate. */
export function updateCrate(
  crateId: number,
  body: CrateUpdateRequest,
): Promise<CrateUpdateResponse> {
  return request<CrateUpdateResponse>(`/api/crates/${crateId}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

/** Delete a crate. */
export function deleteCrate(crateId: number): Promise<{ status: string; crate_id: number }> {
  return request(`/api/crates/${crateId}`, { method: "DELETE" });
}

/** Refresh a crate (re-run AI assignment). */
export function refreshCrate(
  crateId: number,
): Promise<{ status: string; message: string }> {
  return request(`/api/crates/${crateId}/refresh`, { method: "POST" });
}

/** Manually add tracks to a crate. */
export function addTracksToCrate(
  crateId: number,
  trackIds: number[],
): Promise<{ status: string; added: number; crate_id: number }> {
  return request(`/api/crates/${crateId}/tracks`, {
    method: "POST",
    body: JSON.stringify({ track_ids: trackIds }),
  });
}

/** Remove tracks from a crate. */
export function removeTracksFromCrate(
  crateId: number,
  trackIds: number[],
): Promise<{ status: string; removed: number; crate_id: number }> {
  return request(`/api/crates/${crateId}/tracks`, {
    method: "DELETE",
    body: JSON.stringify({ track_ids: trackIds }),
  });
}

// --- Phase 5b: Set Planner API ---

/** Set summary (list view). */
export interface SetSummary {
  id: number;
  name: string;
  description: string;
  track_count: number;
  candidate_count: number;
  status: string;
  created_at: string;
  updated_at: string;
}

/** Set track in the detail view. */
export interface SetTrackItem {
  track_id: number;
  position: number;
  is_locked: boolean;
  is_candidate: boolean;
  title: string | null;
  artist: string | null;
  bpm: number | null;
  key: number | null;
  key_display: string | null;
  energy: number | null;
  mood: string | null;
  genre: string | null;
}

/** Set segment. */
export interface SetSegmentItem {
  id: number;
  set_id: number;
  start_position: number;
  end_position: number;
  description: string | null;
}

/** Set detail (full view). */
export interface SetDetail {
  id: number;
  name: string;
  description: string;
  duration_minutes: number | null;
  target_bpm_start: number | null;
  target_bpm_end: number | null;
  energy_arc: string | null;
  source_type: string;
  source_crate_ids: number[] | null;
  harmonic_mixing: boolean;
  status: string;
  tracks: SetTrackItem[];
  candidates: SetTrackItem[];
  segments: SetSegmentItem[];
  created_at: string;
  updated_at: string;
}

/** Set create request. */
export interface SetCreateRequest {
  name: string;
  description: string;
  source_type?: string;
  source_crate_ids?: number[];
  duration_minutes?: number;
  target_bpm_start?: number;
  target_bpm_end?: number;
  energy_arc?: string;
  harmonic_mixing?: boolean;
}

/** Set create response. */
export interface SetCreateResponse {
  id: number;
  name: string;
  description: string;
  status: string;
  message: string;
}

/** Set update request. */
export interface SetUpdateRequest {
  name?: string;
  description?: string;
  duration_minutes?: number;
  target_bpm_start?: number;
  target_bpm_end?: number;
  energy_arc?: string;
  harmonic_mixing?: boolean;
}

/** Shuffle mode type. */
export type ShuffleMode = "replace" | "reorder";

/** Shuffle response. */
export interface ShuffleResponse {
  mode: string;
  tracks_changed: number;
  errors: string[];
  message: string;
}

/** List all sets. */
export function listSets(): Promise<SetSummary[]> {
  return request<SetSummary[]>("/api/sets");
}

/** Get set detail. */
export function getSet(setId: number): Promise<SetDetail> {
  return request<SetDetail>(`/api/sets/${setId}`);
}

/** Create a new set. */
export function createSet(body: SetCreateRequest): Promise<SetCreateResponse> {
  return request<SetCreateResponse>("/api/sets", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** Update a set. */
export function updateSet(
  setId: number,
  body: SetUpdateRequest,
): Promise<{ id: number; name: string; description: string; status: string; message: string }> {
  return request(`/api/sets/${setId}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

/** Delete a set. */
export function deleteSet(setId: number): Promise<{ status: string; set_id: number }> {
  return request(`/api/sets/${setId}`, { method: "DELETE" });
}

/** Lock a track at a position. */
export function lockTrack(
  setId: number,
  position: number,
): Promise<{ status: string; set_id: number; position: number }> {
  return request(`/api/sets/${setId}/lock/${position}`, { method: "POST" });
}

/** Unlock a track at a position. */
export function unlockTrack(
  setId: number,
  position: number,
): Promise<{ status: string; set_id: number; position: number }> {
  return request(`/api/sets/${setId}/unlock/${position}`, { method: "POST" });
}

/** Update a segment description. */
export function updateSegment(
  setId: number,
  segmentId: number,
  description: string | null,
): Promise<{ status: string; segment_id: number; description: string | null }> {
  return request(`/api/sets/${setId}/segments/${segmentId}`, {
    method: "PUT",
    body: JSON.stringify({ description }),
  });
}

/** Shuffle unlocked tracks. */
export function shuffleSet(setId: number, mode: ShuffleMode): Promise<ShuffleResponse> {
  return request<ShuffleResponse>(`/api/sets/${setId}/shuffle`, {
    method: "POST",
    body: JSON.stringify({ mode }),
  });
}

/** Add a track to a set at a position. */
export function addTrackToSet(
  setId: number,
  trackId: number,
  position: number,
): Promise<{ status: string; set_id: number; track_id: number; position: number }> {
  return request(`/api/sets/${setId}/tracks`, {
    method: "POST",
    body: JSON.stringify({ track_id: trackId, position }),
  });
}

/** Remove a track from a set at a position. */
export function removeTrackFromSet(
  setId: number,
  position: number,
): Promise<{ status: string; set_id: number; position: number }> {
  return request(`/api/sets/${setId}/tracks/${position}`, { method: "DELETE" });
}

/** Move a track within a set. */
export function moveTrackInSet(
  setId: number,
  fromPosition: number,
  toPosition: number,
): Promise<{
  status: string;
  set_id: number;
  from_position: number;
  to_position: number;
}> {
  return request(`/api/sets/${setId}/tracks/move`, {
    method: "POST",
    body: JSON.stringify({ from_position: fromPosition, to_position: toPosition }),
  });
}

/** Get candidate pool for a set. */
export function getCandidates(
  setId: number,
): Promise<SetTrackItem[]> {
  return request<SetTrackItem[]>(`/api/sets/${setId}/candidates`);
}

/** Export a set as a Rekordbox playlist. */
export function exportSet(
  setId: number,
): Promise<{
  status: string;
  set_id: number;
  set_name: string;
  tracks_in_set: number;
  output_path: string;
}> {
  return request(`/api/sets/${setId}/export`, { method: "POST" });
}

/** Set planner SSE progress event. */
export interface SetPlannerProgressEvent {
  event: string;
  data: string;
}

/** Connect to set planner SSE progress stream. */
export function connectSetProgress(
  setId: number,
  onEvent: (eventType: string, data: string) => void,
  onComplete?: () => void,
): EventSource {
  const es = new EventSource(`${BASE_URL}/api/sets/${setId}/progress`);

  const eventTypes = [
    "set_planning_started",
    "set_candidate_selection",
    "set_sequencing",
    "set_planning_complete",
    "shuffle_started",
    "shuffle_complete",
  ];
  for (const eventType of eventTypes) {
    es.addEventListener(eventType, (e) => {
      onEvent(eventType, e.data);
      if (eventType.includes("complete")) {
        onComplete?.();
        es.close();
      }
    });
  }

  es.addEventListener("error", () => {
    es.close();
  });

  return es;
}

/** Connect to crate assignment SSE progress stream. */
export function connectCrateProgress(
  crateId: number,
  onProgress: (event: CrateAssignmentProgress) => void,
  onComplete?: (data: CrateAssignmentComplete) => void,
): EventSource {
  const es = new EventSource(`${BASE_URL}/api/crates/${crateId}/progress`);

  es.addEventListener("crate_assignment_progress", (e) => {
    const data = JSON.parse(e.data) as CrateAssignmentProgress;
    onProgress(data);
  });

  es.addEventListener("crate_assignment_complete", (e) => {
    const data = JSON.parse(e.data) as CrateAssignmentComplete;
    onComplete?.(data);
    es.close();
  });

  es.addEventListener("error", () => {
    es.close();
  });

  return es;
}

// --- Phase 6a: Settings API ---

/** Settings response from GET /api/settings. */
export interface SettingsResponse {
  anthropic_api_key: string;
  output_directory: string;
  default_key_notation: string;
  folder_template: string;
  convert_aac_to_mp3: boolean;
  bpm_range_min: number;
  bpm_range_max: number;
  confidence_threshold: number;
  set_track_duration_minutes: number;
  set_max_tracks: number;
}

/** Settings update request. */
export interface SettingsUpdateRequest {
  anthropic_api_key?: string;
  output_directory?: string;
  default_key_notation?: string;
  folder_template?: string;
  convert_aac_to_mp3?: boolean;
  bpm_range_min?: number;
  bpm_range_max?: number;
  confidence_threshold?: number;
  set_track_duration_minutes?: number;
  set_max_tracks?: number;
}

/** Settings status (first-run check). */
export interface SettingsStatusResponse {
  configured: boolean;
  has_api_key: boolean;
  has_output_directory: boolean;
  ffmpeg_available: boolean;
  output_directory_writable: boolean;
}

/** Validate key response. */
export interface SettingsValidateKeyResponse {
  valid: boolean;
  error: string;
}

/** Validate directory response. */
export interface SettingsValidateDirectoryResponse {
  valid: boolean;
  error: string;
}

/** Get current settings (API key masked). */
export function getSettings(): Promise<SettingsResponse> {
  return request<SettingsResponse>("/api/settings");
}

/** Update settings. */
export function updateSettings(body: SettingsUpdateRequest): Promise<SettingsResponse> {
  return request<SettingsResponse>("/api/settings", {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

/** Validate an API key. */
export function validateApiKey(key: string): Promise<SettingsValidateKeyResponse> {
  return request<SettingsValidateKeyResponse>("/api/settings/validate-key", {
    method: "POST",
    body: JSON.stringify({ key }),
  });
}

/** Validate an output directory path. */
export function validateDirectory(path: string): Promise<SettingsValidateDirectoryResponse> {
  return request<SettingsValidateDirectoryResponse>("/api/settings/validate-directory", {
    method: "POST",
    body: JSON.stringify({ path }),
  });
}

/** Get settings status (first-run check). */
export function getSettingsStatus(): Promise<SettingsStatusResponse> {
  return request<SettingsStatusResponse>("/api/settings/status");
}
