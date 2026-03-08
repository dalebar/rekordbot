import { useCallback, useState } from "react";
import {
  connectAnalysisProgress,
  postAnalyse,
  postAnalyseCancel,
  postWriteTags,
  type AnalysisProgressEvent,
} from "./api/client";

export type FilterMode = "all" | "unanalysed" | "low_confidence" | "conflicts";

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

        {/* Cancel button */}
        {analysing && (
          <button
            onClick={handleCancel}
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
        <div className="flex items-center gap-1 text-xs">
          {(["all", "unanalysed", "low_confidence", "conflicts"] as const).map((f) => (
            <button
              key={f}
              onClick={() => onFilterChange(f)}
              className={`rounded px-2 py-1 ${
                filter === f ? "bg-gray-700 text-gray-100" : "text-gray-500 hover:text-gray-300"
              }`}
            >
              {f === "all"
                ? "All"
                : f === "unanalysed"
                  ? "Unanalysed"
                  : f === "low_confidence"
                    ? "Low Conf."
                    : "Conflicts"}
            </button>
          ))}
        </div>
      </div>

      {/* Progress bar */}
      {analysing && (
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-gray-800">
          <div
            className="h-full rounded-full bg-blue-500 transition-all duration-300"
            style={{ width: `${progressPct}%` }}
          />
        </div>
      )}
    </div>
  );
}
