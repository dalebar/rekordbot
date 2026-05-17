import { useCallback, useState } from "react";
import {
  importRekordboxXml,
  cancelImport,
  connectImportProgress,
  type ImportSummary,
} from "./api/client";

interface ImportControlsProps {
  onRefresh: () => void;
  onConflicts: (count: number) => void;
}

export default function ImportControls({ onRefresh, onConflicts }: ImportControlsProps) {
  const [importing, setImporting] = useState(false);
  const [progress, setProgress] = useState<{ processed: number; total: number } | null>(null);
  const [summary, setSummary] = useState<ImportSummary | null>(null);
  const [showSkipped, setShowSkipped] = useState(false);

  const handleImport = useCallback(async () => {
    // Use Tauri file dialog if available, else prompt
    let filePath: string | null = null;

    try {
      // Try Tauri dialog
      const { open } = await import("@tauri-apps/plugin-dialog");
      const result = await open({
        filters: [{ name: "XML Files", extensions: ["xml"] }],
        multiple: false,
      });
      if (result) {
        filePath = result;
      }
    } catch {
      // Tauri not available — use prompt fallback for dev
      filePath = window.prompt("Enter path to Rekordbox XML file:");
    }

    if (!filePath) return;

    setImporting(true);
    setProgress(null);
    setSummary(null);
    setShowSkipped(false);

    try {
      await importRekordboxXml(filePath);

      // Connect to SSE progress
      connectImportProgress(
        (p) => setProgress({ processed: p.processed, total: p.total }),
        (s) => {
          setSummary(s);
          setImporting(false);
          setProgress(null);
          onRefresh();
          if (s.tracks_conflict > 0) {
            onConflicts(s.tracks_conflict);
          }
        },
        () => {
          setImporting(false);
          setProgress(null);
        },
      );
    } catch {
      setImporting(false);
    }
  }, [onRefresh, onConflicts]);

  const handleCancel = useCallback(async () => {
    try {
      await cancelImport();
    } catch {
      // handled by API client
    }
  }, []);

  const pct =
    progress && progress.total > 0 ? Math.round((progress.processed / progress.total) * 100) : 0;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-3">
        {/* Import button */}
        <button
          onClick={handleImport}
          disabled={importing}
          className="rounded bg-teal-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-teal-500 disabled:opacity-50"
        >
          {importing ? "Importing..." : "Import XML"}
        </button>

        {/* Cancel button */}
        {importing && (
          <button
            onClick={handleCancel}
            className="rounded border border-gray-700 px-3 py-1.5 text-xs text-gray-400 hover:text-gray-200"
          >
            Cancel
          </button>
        )}

        {/* Progress */}
        {importing && progress && (
          <div className="flex items-center gap-2">
            <div className="h-1.5 w-32 rounded bg-gray-800">
              <div
                className="h-full rounded bg-teal-500 transition-all"
                style={{ width: `${pct}%` }}
              />
            </div>
            <span className="text-xs text-gray-500">
              {progress.processed}/{progress.total}
            </span>
          </div>
        )}

        {/* Summary */}
        {summary && (
          <span className="text-xs text-gray-500">
            Imported {summary.tracks_imported} tracks, {summary.tracks_matched} matched
            {summary.tracks_conflict > 0 && <>, {summary.tracks_conflict} conflicts</>}
            {summary.tracks_skipped > 0 && (
              <>
                {" · "}
                <button
                  onClick={() => setShowSkipped(!showSkipped)}
                  className="text-amber-500 hover:text-amber-400"
                >
                  {summary.tracks_skipped} skipped
                </button>
              </>
            )}
            {summary.playlists_imported > 0 && <>, {summary.playlists_imported} playlists</>}
          </span>
        )}

        {summary && (
          <button
            onClick={() => setSummary(null)}
            className="text-xs text-gray-600 hover:text-gray-400"
          >
            Dismiss
          </button>
        )}
      </div>

      {/* Skipped reasons */}
      {showSkipped && summary && summary.skipped_reasons.length > 0 && (
        <div className="max-h-24 overflow-y-auto rounded border border-gray-800 bg-gray-900 p-2 text-xs text-gray-500">
          {summary.skipped_reasons.map((r, i) => (
            <div key={i}>{r}</div>
          ))}
        </div>
      )}
    </div>
  );
}
