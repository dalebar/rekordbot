import { useCallback, useState } from "react";
import { exportRekordboxXml, type ExportResult } from "./api/client";

interface ExportControlsProps {
  trackCount: number;
  onRefresh: () => void;
}

export default function ExportControls({ trackCount, onRefresh }: ExportControlsProps) {
  const [exporting, setExporting] = useState(false);
  const [result, setResult] = useState<ExportResult | null>(null);
  const [showWarnings, setShowWarnings] = useState(false);

  const handleExport = useCallback(async () => {
    setExporting(true);
    setResult(null);
    setShowWarnings(false);
    try {
      const res = await exportRekordboxXml();
      setResult(res);
      onRefresh();
    } catch {
      // Error handled by API client
    } finally {
      setExporting(false);
    }
  }, [onRefresh]);

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-3">
        {/* Export button */}
        <button
          onClick={handleExport}
          disabled={exporting || trackCount === 0}
          className="rounded bg-amber-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-500 disabled:opacity-50"
        >
          {exporting ? "Exporting..." : "Export XML"}
        </button>

        {/* Result summary */}
        {result && (
          <span className="text-xs text-gray-500">
            Exported {result.tracks_exported} tracks, {result.playlists_created} playlists
            {result.tracks_skipped > 0 && (
              <>
                {" · "}
                <button
                  onClick={() => setShowWarnings(!showWarnings)}
                  className="text-amber-500 hover:text-amber-400"
                >
                  {result.tracks_skipped} skipped
                </button>
              </>
            )}
          </span>
        )}

        {result && (
          <button
            onClick={() => setResult(null)}
            className="text-xs text-gray-600 hover:text-gray-400"
          >
            Dismiss
          </button>
        )}
      </div>

      {/* Warnings detail */}
      {showWarnings && result && result.warnings.length > 0 && (
        <div className="max-h-24 overflow-y-auto rounded border border-gray-800 bg-gray-900 p-2 text-xs text-gray-500">
          {result.warnings.map((w, i) => (
            <div key={i}>{w}</div>
          ))}
        </div>
      )}
    </div>
  );
}
