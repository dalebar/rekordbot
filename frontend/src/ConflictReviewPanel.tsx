import { useCallback, useEffect, useState } from "react";
import {
  getImportConflicts,
  resolveConflict,
  resolveAllConflicts,
  type ImportConflict,
} from "./api/client";

interface ConflictReviewPanelProps {
  onClose: () => void;
  onRefresh: () => void;
}

export default function ConflictReviewPanel({ onClose, onRefresh }: ConflictReviewPanelProps) {
  const [conflicts, setConflicts] = useState<ImportConflict[]>([]);
  const [expandedTrack, setExpandedTrack] = useState<number | null>(null);
  const [resolutions, setResolutions] = useState<Record<number, Record<string, string>>>({});
  const [resolving, setResolving] = useState(false);

  const loadConflicts = useCallback(async () => {
    try {
      const data = await getImportConflicts();
      setConflicts(data);
    } catch {
      // handled by API client
    }
  }, []);

  useEffect(() => {
    loadConflicts();
  }, [loadConflicts]);

  const handleFieldChoice = useCallback(
    (trackId: number, field: string, choice: string) => {
      setResolutions((prev) => ({
        ...prev,
        [trackId]: {
          ...(prev[trackId] || {}),
          [field]: choice,
        },
      }));
    },
    [],
  );

  const handleResolveTrack = useCallback(
    async (trackId: number) => {
      const trackResolutions = resolutions[trackId];
      if (!trackResolutions) return;

      setResolving(true);
      try {
        await resolveConflict(trackId, trackResolutions);
        await loadConflicts();
        onRefresh();
      } catch {
        // handled by API client
      } finally {
        setResolving(false);
      }
    },
    [resolutions, loadConflicts, onRefresh],
  );

  const handleBulkResolve = useCallback(
    async (strategy: string) => {
      setResolving(true);
      try {
        await resolveAllConflicts(strategy);
        await loadConflicts();
        onRefresh();
      } catch {
        // handled by API client
      } finally {
        setResolving(false);
      }
    },
    [loadConflicts, onRefresh],
  );

  if (conflicts.length === 0) {
    return (
      <div className="flex flex-col items-center gap-4 p-8 text-gray-500">
        <p className="text-sm">No conflicts to review.</p>
        <button
          onClick={onClose}
          className="rounded bg-gray-800 px-4 py-2 text-xs text-gray-300 hover:bg-gray-700"
        >
          Close
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden p-4">
      {/* Header */}
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-medium text-gray-300">
          Import Conflicts ({conflicts.length} tracks)
        </h2>
        <div className="flex items-center gap-2">
          <button
            onClick={() => handleBulkResolve("rekordbox")}
            disabled={resolving}
            className="rounded bg-teal-700 px-3 py-1 text-xs text-white hover:bg-teal-600 disabled:opacity-50"
          >
            Accept All Rekordbox
          </button>
          <button
            onClick={() => handleBulkResolve("rekordbot")}
            disabled={resolving}
            className="rounded bg-gray-700 px-3 py-1 text-xs text-gray-300 hover:bg-gray-600 disabled:opacity-50"
          >
            Keep All rekordbot
          </button>
          <button
            onClick={onClose}
            className="rounded border border-gray-700 px-3 py-1 text-xs text-gray-400 hover:text-gray-200"
          >
            Close
          </button>
        </div>
      </div>

      {/* Conflict list */}
      <div className="flex-1 overflow-y-auto">
        {conflicts.map((conflict) => (
          <div
            key={conflict.track_id}
            className="mb-2 rounded border border-gray-800 bg-gray-900"
          >
            {/* Track header */}
            <button
              onClick={() =>
                setExpandedTrack(
                  expandedTrack === conflict.track_id ? null : conflict.track_id,
                )
              }
              className="flex w-full items-center justify-between p-3 text-left text-xs hover:bg-gray-800"
            >
              <div>
                <span className="font-medium text-gray-200">
                  {conflict.title || "Untitled"}
                </span>
                {conflict.artist && (
                  <span className="ml-2 text-gray-500">— {conflict.artist}</span>
                )}
              </div>
              <span className="text-gray-600">
                {conflict.conflicts.length} conflict
                {conflict.conflicts.length !== 1 ? "s" : ""}
              </span>
            </button>

            {/* Expanded detail */}
            {expandedTrack === conflict.track_id && (
              <div className="border-t border-gray-800 p-3">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-gray-600">
                      <th className="pb-2 text-left font-normal">Field</th>
                      <th className="pb-2 text-left font-normal">Rekordbox</th>
                      <th className="pb-2 text-left font-normal">rekordbot</th>
                      <th className="pb-2 text-left font-normal">Use</th>
                    </tr>
                  </thead>
                  <tbody>
                    {conflict.conflicts.map((f) => {
                      const choice =
                        resolutions[conflict.track_id]?.[f.field] || f.recommended;
                      return (
                        <tr key={f.field} className="border-t border-gray-800">
                          <td className="py-2 text-gray-400">{f.field}</td>
                          <td
                            className={`py-2 ${choice === "rekordbox" ? "font-medium text-teal-400" : "text-gray-500"}`}
                          >
                            {String(f.rekordbox_value ?? "—")}
                          </td>
                          <td
                            className={`py-2 ${choice === "rekordbot" ? "font-medium text-blue-400" : "text-gray-500"}`}
                          >
                            {String(f.rekordbot_value ?? "—")}
                          </td>
                          <td className="py-2">
                            <div className="flex gap-1">
                              <button
                                onClick={() =>
                                  handleFieldChoice(
                                    conflict.track_id,
                                    f.field,
                                    "rekordbox",
                                  )
                                }
                                className={`rounded px-2 py-0.5 ${
                                  choice === "rekordbox"
                                    ? "bg-teal-700 text-white"
                                    : "bg-gray-800 text-gray-500 hover:text-gray-300"
                                }`}
                              >
                                RB
                              </button>
                              <button
                                onClick={() =>
                                  handleFieldChoice(
                                    conflict.track_id,
                                    f.field,
                                    "rekordbot",
                                  )
                                }
                                className={`rounded px-2 py-0.5 ${
                                  choice === "rekordbot"
                                    ? "bg-blue-700 text-white"
                                    : "bg-gray-800 text-gray-500 hover:text-gray-300"
                                }`}
                              >
                                rbot
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>

                <div className="mt-3 flex justify-end">
                  <button
                    onClick={() => handleResolveTrack(conflict.track_id)}
                    disabled={resolving || !resolutions[conflict.track_id]}
                    className="rounded bg-teal-600 px-3 py-1 text-xs text-white hover:bg-teal-500 disabled:opacity-50"
                  >
                    Apply
                  </button>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
