import { useCallback, useEffect, useState } from "react";
import {
  connectAnalysisProgress,
  connectAiTagProgress,
  postAnalyse,
  postAnalyseCancel,
  postAiTag,
  postAiTagCancel,
  postValidateApiKey,
  postWriteTags,
  type AiTagCompleteEvent,
  type AiTagProgressEvent,
  type AnalysisProgressEvent,
} from "./api/client";

export type FilterMode =
  | "all"
  | "unanalysed"
  | "low_confidence"
  | "conflicts"
  | "ai_tagged"
  | "not_ai_tagged";

interface AnalysisControlsProps {
  selectedTrackIds: number[];
  onRefresh: () => void;
  filter: FilterMode;
  onFilterChange: (filter: FilterMode) => void;
}

export default function AnalysisControls({
  selectedTrackIds,
  onRefresh,
  filter,
  onFilterChange,
}: AnalysisControlsProps) {
  const [analysing, setAnalysing] = useState(false);
  const [progress, setProgress] = useState({ completed: 0, total: 0, failed: 0 });
  const [writing, setWriting] = useState(false);
  const [aiTagging, setAiTagging] = useState(false);
  const [aiProgress, setAiProgress] = useState({ tagged: 0, total: 0, failed: 0 });
  const [aiComplete, setAiComplete] = useState<AiTagCompleteEvent | null>(null);
  const [hasApiKey, setHasApiKey] = useState(true);

  const handleAnalyse = useCallback(async () => {
    try {
      const body =
        selectedTrackIds.length > 0
          ? { track_ids: selectedTrackIds, options: { skip_if_analysed: false } }
          : {};
      const response = await postAnalyse(body);
      if (response.total_tracks === 0) return;

      setAnalysing(true);
      setProgress({ completed: 0, total: response.total_tracks, failed: 0 });

      connectAnalysisProgress(
        (event: AnalysisProgressEvent) => {
          setProgress(event.batch_progress);
        },
        () => {
          setAnalysing(false);
          onRefresh();
        },
      );
    } catch {
      // Error handled by API client
    }
  }, [selectedTrackIds, onRefresh]);

  const handleCancel = useCallback(async () => {
    try {
      await postAnalyseCancel();
    } catch {
      // Ignore
    }
  }, []);

  // Check if API key is configured on mount
  useEffect(() => {
    postValidateApiKey()
      .then((result) => setHasApiKey(result.valid))
      .catch(() => setHasApiKey(false));
  }, []);

  const handleAiTag = useCallback(async () => {
    try {
      setAiComplete(null);
      const body =
        selectedTrackIds.length > 0
          ? { track_ids: selectedTrackIds, options: { skip_if_tagged: false } }
          : {};
      const response = await postAiTag(body);
      if (response.total_tracks === 0) return;

      setAiTagging(true);
      setAiProgress({ tagged: 0, total: response.total_tracks, failed: 0 });

      connectAiTagProgress(
        (event: AiTagProgressEvent) => {
          setAiProgress({
            tagged: event.tracks_tagged,
            total: event.tracks_total,
            failed: event.tracks_failed,
          });
        },
        (data: AiTagCompleteEvent) => {
          setAiTagging(false);
          setAiComplete(data);
          onRefresh();
        },
      );
    } catch {
      // Error handled by API client
    }
  }, [selectedTrackIds, onRefresh]);

  const handleAiTagCancel = useCallback(async () => {
    try {
      await postAiTagCancel();
    } catch {
      // Ignore
    }
  }, []);

  const handleWriteTags = useCallback(async () => {
    if (selectedTrackIds.length === 0) return;
    setWriting(true);
    try {
      await postWriteTags({ track_ids: selectedTrackIds });
      onRefresh();
    } catch {
      // Error handled by API client
    } finally {
      setWriting(false);
    }
  }, [selectedTrackIds, onRefresh]);

  const progressPct = progress.total > 0 ? (progress.completed / progress.total) * 100 : 0;
  const aiProgressPct = aiProgress.total > 0 ? (aiProgress.tagged / aiProgress.total) * 100 : 0;

  const filterLabels: Record<FilterMode, string> = {
    all: "All",
    unanalysed: "Unanalysed",
    low_confidence: "Low Conf.",
    conflicts: "Conflicts",
    ai_tagged: "AI Tagged",
    not_ai_tagged: "Not AI Tagged",
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-3">
        {/* Analyse button */}
        <button
          onClick={handleAnalyse}
          disabled={analysing}
          className="rounded bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-500 disabled:opacity-50"
        >
          {analysing
            ? "Analysing..."
            : selectedTrackIds.length > 0
              ? `Analyse Selected (${selectedTrackIds.length})`
              : "Analyse All Unanalysed"}
        </button>

        {/* Cancel analysis */}
        {analysing && (
          <button
            onClick={handleCancel}
            className="rounded border border-gray-700 px-3 py-1.5 text-xs text-gray-400 hover:text-gray-200"
          >
            Cancel
          </button>
        )}

        {/* AI Tag button */}
        <button
          onClick={handleAiTag}
          disabled={aiTagging || !hasApiKey}
          title={!hasApiKey ? "No Anthropic API key configured" : undefined}
          className="rounded bg-purple-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-purple-500 disabled:opacity-50"
        >
          {aiTagging
            ? "AI Tagging..."
            : selectedTrackIds.length > 0
              ? `AI Tag Selected (${selectedTrackIds.length})`
              : "AI Tag All Untagged"}
        </button>

        {/* Cancel AI tagging */}
        {aiTagging && (
          <button
            onClick={handleAiTagCancel}
            className="rounded border border-gray-700 px-3 py-1.5 text-xs text-gray-400 hover:text-gray-200"
          >
            Cancel
          </button>
        )}

        {/* Write Tags button */}
        <button
          onClick={handleWriteTags}
          disabled={writing || selectedTrackIds.length === 0}
          className="rounded border border-gray-700 px-3 py-1.5 text-xs text-gray-400 hover:text-gray-200 disabled:opacity-50"
        >
          {writing ? "Writing..." : `Write Tags (${selectedTrackIds.length})`}
        </button>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Filter buttons */}
        <div className="flex flex-wrap items-center gap-1 text-xs">
          {(
            [
              "all",
              "unanalysed",
              "low_confidence",
              "conflicts",
              "ai_tagged",
              "not_ai_tagged",
            ] as const
          ).map((f) => (
            <button
              key={f}
              onClick={() => onFilterChange(f)}
              className={`rounded px-2 py-1 ${
                filter === f ? "bg-gray-700 text-gray-100" : "text-gray-500 hover:text-gray-300"
              }`}
            >
              {filterLabels[f]}
            </button>
          ))}
        </div>
      </div>

      {/* Analysis progress bar */}
      {analysing && (
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-gray-800">
          <div
            className="h-full rounded-full bg-blue-500 transition-all duration-300"
            style={{ width: `${progressPct}%` }}
          />
        </div>
      )}

      {/* AI tagging progress bar */}
      {aiTagging && (
        <div className="flex items-center gap-2">
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-gray-800">
            <div
              className="h-full rounded-full bg-purple-500 transition-all duration-300"
              style={{ width: `${aiProgressPct}%` }}
            />
          </div>
          <span className="text-xs text-gray-500">
            {aiProgress.tagged}/{aiProgress.total}
            {aiProgress.failed > 0 && ` (${aiProgress.failed} failed)`}
          </span>
        </div>
      )}

      {/* AI tag completion summary */}
      {aiComplete && (
        <div className="flex items-center gap-3 text-xs text-gray-500">
          <span>
            AI tagged: {aiComplete.succeeded}/{aiComplete.total_tracks}
            {aiComplete.failed > 0 && `, ${aiComplete.failed} failed`}
          </span>
          <span>
            Tokens: {aiComplete.token_usage.input_tokens.toLocaleString()} in /{" "}
            {aiComplete.token_usage.output_tokens.toLocaleString()} out
          </span>
          <span>Cost: ${aiComplete.token_usage.estimated_cost_usd.toFixed(4)}</span>
          <button
            onClick={() => setAiComplete(null)}
            className="text-gray-600 hover:text-gray-400"
          >
            Dismiss
          </button>
        </div>
      )}
    </div>
  );
}
