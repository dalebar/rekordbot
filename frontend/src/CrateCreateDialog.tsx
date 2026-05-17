import { useCallback, useState } from "react";
import {
  connectCrateProgress,
  createCrate,
  type CrateAssignmentComplete,
  type CrateAssignmentProgress,
} from "./api/client";

interface CrateCreateDialogProps {
  onClose: () => void;
  onCreated: () => void;
}

export default function CrateCreateDialog({ onClose, onCreated }: CrateCreateDialogProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [creating, setCreating] = useState(false);
  const [progress, setProgress] = useState<CrateAssignmentProgress | null>(null);
  const [result, setResult] = useState<CrateAssignmentComplete | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleCreate = useCallback(async () => {
    if (!name.trim() || !description.trim()) return;

    setCreating(true);
    setError(null);

    try {
      const response = await createCrate({
        name: name.trim(),
        description: description.trim(),
        auto_refresh: autoRefresh,
      });

      // Connect to progress SSE
      connectCrateProgress(
        response.id,
        (event) => setProgress(event),
        (data) => {
          setResult(data);
          setCreating(false);
          onCreated();
        },
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create crate");
      setCreating(false);
    }
  }, [name, description, autoRefresh, onCreated]);

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/50">
      <div className="w-full max-w-lg bg-gray-900 border border-gray-700 rounded-lg shadow-xl">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-700">
          <h3 className="text-lg font-semibold">New Crate</h3>
          <button
            className="text-gray-500 hover:text-gray-300"
            onClick={onClose}
            disabled={creating}
          >
            &times;
          </button>
        </div>

        <div className="px-6 py-4 space-y-4">
          {/* Name */}
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1">Name</label>
            <input
              type="text"
              className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-sm text-gray-100 focus:outline-none focus:border-purple-500"
              placeholder="Deep & Dubby"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={creating}
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1">Description</label>
            <textarea
              className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-sm text-gray-100 focus:outline-none focus:border-purple-500 h-24 resize-none"
              placeholder="Deep minimal house, 118-124 BPM, hypnotic and warm. Dubby vibes, suitable for late-night sets..."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              disabled={creating}
            />
          </div>

          {/* Auto-refresh */}
          <label className="flex items-center gap-2 text-sm text-gray-400 cursor-pointer">
            <input
              type="checkbox"
              className="rounded bg-gray-800 border-gray-700"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              disabled={creating}
            />
            Auto-refresh on new imports
          </label>

          {/* Progress */}
          {creating && progress && (
            <div className="bg-gray-800 rounded p-3">
              <div className="flex justify-between text-xs text-gray-400 mb-1">
                <span>
                  Batch {progress.batch_number} / {progress.total_batches}
                </span>
                <span>
                  {progress.tracks_processed} / {progress.tracks_total} tracks
                </span>
              </div>
              <div className="w-full bg-gray-700 rounded-full h-1.5">
                <div
                  className="bg-purple-500 h-1.5 rounded-full transition-all"
                  style={{
                    width: `${(progress.batch_number / progress.total_batches) * 100}%`,
                  }}
                />
              </div>
            </div>
          )}

          {/* Result */}
          {result && (
            <div className="bg-gray-800 rounded p-3 text-sm">
              <span className="text-emerald-400">
                {result.matched} tracks matched out of {result.total_tracks}
              </span>
              {result.errors.length > 0 && (
                <p className="text-amber-400 mt-1">
                  {result.errors.length} error(s) during assignment
                </p>
              )}
            </div>
          )}

          {/* Error */}
          {error && <p className="text-sm text-red-400">{error}</p>}
        </div>

        <div className="flex justify-end gap-3 px-6 py-4 border-t border-gray-700">
          <button
            className="px-4 py-2 text-sm text-gray-400 hover:text-gray-200"
            onClick={onClose}
            disabled={creating}
          >
            {result ? "Close" : "Cancel"}
          </button>
          {!result && (
            <button
              className="px-4 py-2 text-sm bg-purple-600 hover:bg-purple-500 text-white rounded disabled:opacity-50"
              onClick={handleCreate}
              disabled={creating || !name.trim() || !description.trim()}
            >
              {creating ? "Creating..." : "Create Crate"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
