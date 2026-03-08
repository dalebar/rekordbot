import { useCallback, useState } from "react";
import { bpmMultiply, revertField, updateTrack, type Track, type TrackUpdate } from "./api/client";

interface TrackDetailPanelProps {
  track: Track;
  onClose: () => void;
  onTrackUpdated: (track: Track) => void;
}

export default function TrackDetailPanel({
  track,
  onClose,
  onTrackUpdated,
}: TrackDetailPanelProps) {
  const [editing, setEditing] = useState<Record<string, string>>({});

  const handleEdit = useCallback((field: string, value: string) => {
    setEditing((prev) => ({ ...prev, [field]: value }));
  }, []);

  const handleSave = useCallback(
    async (field: string) => {
      const value = editing[field];
      if (value === undefined) return;

      const update: TrackUpdate = {};
      if (field === "bpm") {
        update.bpm = parseFloat(value);
      } else if (field === "key") {
        update.key = parseInt(value, 10);
      } else if (field === "year") {
        update.year = parseInt(value, 10);
      } else if (field === "track_number") {
        update.track_number = parseInt(value, 10);
      } else if (field === "rating") {
        update.rating = parseInt(value, 10);
      } else {
        (update as Record<string, string>)[field] = value;
      }

      try {
        const updated = await updateTrack(track.id, update);
        onTrackUpdated(updated);
        setEditing((prev) => {
          const next = { ...prev };
          delete next[field];
          return next;
        });
      } catch {
        // Error handled by API client
      }
    },
    [editing, track.id, onTrackUpdated],
  );

  const handleRevert = useCallback(
    async (field: "bpm" | "key") => {
      try {
        const updated = await revertField(track.id, field);
        onTrackUpdated(updated);
      } catch {
        // No source value
      }
    },
    [track.id, onTrackUpdated],
  );

  const handleBpmMultiply = useCallback(
    async (factor: 2 | 0.5) => {
      try {
        const updated = await bpmMultiply(track.id, factor);
        onTrackUpdated(updated);
      } catch {
        // Error
      }
    },
    [track.id, onTrackUpdated],
  );

  const textFields: { field: string; label: string; value: string | null }[] = [
    { field: "title", label: "Title", value: track.title },
    { field: "artist", label: "Artist", value: track.artist },
    { field: "album", label: "Album", value: track.album },
    { field: "genre", label: "Genre", value: track.genre },
    { field: "label", label: "Label", value: track.label },
    { field: "comment", label: "Comment", value: track.comment },
  ];

  return (
    <div className="flex h-full flex-col border-l border-gray-800 bg-gray-900/50">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-gray-800 px-4 py-3">
        <h3 className="text-sm font-medium text-gray-200">Track Detail</h3>
        <button onClick={onClose} className="text-gray-500 hover:text-gray-300">
          &times;
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4">
        <div className="flex flex-col gap-3">
          {/* Text fields */}
          {textFields.map(({ field, label, value }) => (
            <div key={field} className="flex flex-col gap-1">
              <label className="text-xs text-gray-500">{label}</label>
              <input
                type="text"
                value={editing[field] ?? value ?? ""}
                onChange={(e) => handleEdit(field, e.target.value)}
                onBlur={() => handleSave(field)}
                onKeyDown={(e) => e.key === "Enter" && handleSave(field)}
                className="rounded border border-gray-700 bg-gray-800 px-2 py-1 text-xs text-gray-200"
              />
            </div>
          ))}

          {/* Year and Track Number */}
          <div className="flex gap-3">
            <div className="flex flex-1 flex-col gap-1">
              <label className="text-xs text-gray-500">Year</label>
              <input
                type="number"
                value={editing.year ?? track.year ?? ""}
                onChange={(e) => handleEdit("year", e.target.value)}
                onBlur={() => handleSave("year")}
                className="rounded border border-gray-700 bg-gray-800 px-2 py-1 text-xs text-gray-200"
              />
            </div>
            <div className="flex flex-1 flex-col gap-1">
              <label className="text-xs text-gray-500">Track #</label>
              <input
                type="number"
                value={editing.track_number ?? track.track_number ?? ""}
                onChange={(e) => handleEdit("track_number", e.target.value)}
                onBlur={() => handleSave("track_number")}
                className="rounded border border-gray-700 bg-gray-800 px-2 py-1 text-xs text-gray-200"
              />
            </div>
          </div>

          {/* BPM section */}
          <div className="flex flex-col gap-1">
            <label className="text-xs text-gray-500">
              BPM
              {track.bpm_confidence !== null && (
                <span
                  className={`ml-2 ${track.bpm_confidence < 0.6 ? "text-amber-400" : "text-emerald-400"}`}
                >
                  ({(track.bpm_confidence * 100).toFixed(0)}% conf.)
                </span>
              )}
            </label>
            <div className="flex items-center gap-2">
              <input
                type="number"
                step="0.01"
                value={editing.bpm ?? track.bpm ?? ""}
                onChange={(e) => handleEdit("bpm", e.target.value)}
                onBlur={() => handleSave("bpm")}
                className="flex-1 rounded border border-gray-700 bg-gray-800 px-2 py-1 text-xs text-gray-200"
              />
              <button
                onClick={() => handleBpmMultiply(0.5)}
                className="rounded border border-gray-700 px-1.5 py-0.5 text-xs text-gray-400 hover:text-gray-200"
                title="Halve BPM"
              >
                /2
              </button>
              <button
                onClick={() => handleBpmMultiply(2)}
                className="rounded border border-gray-700 px-1.5 py-0.5 text-xs text-gray-400 hover:text-gray-200"
                title="Double BPM"
              >
                x2
              </button>
              {track.source_bpm !== null && track.has_bpm_conflict && (
                <button
                  onClick={() => handleRevert("bpm")}
                  className="text-xs text-amber-400 hover:text-amber-300"
                  title={`Revert to source: ${track.source_bpm}`}
                >
                  Revert
                </button>
              )}
            </div>
          </div>

          {/* Key section */}
          <div className="flex flex-col gap-1">
            <label className="text-xs text-gray-500">
              Key
              {track.key_confidence !== null && (
                <span
                  className={`ml-2 ${track.key_confidence < 0.6 ? "text-amber-400" : "text-emerald-400"}`}
                >
                  ({(track.key_confidence * 100).toFixed(0)}% conf.)
                </span>
              )}
            </label>
            <div className="flex items-center gap-2">
              <span className="text-sm text-gray-200">{track.key_display ?? "—"}</span>
              {track.source_key !== null && track.has_key_conflict && (
                <button
                  onClick={() => handleRevert("key")}
                  className="text-xs text-amber-400 hover:text-amber-300"
                  title="Revert to source key"
                >
                  Revert
                </button>
              )}
            </div>
          </div>

          {/* File info (read-only) */}
          <div className="mt-4 border-t border-gray-800 pt-3">
            <h4 className="mb-2 text-xs font-medium text-gray-400">File Info</h4>
            <div className="flex flex-col gap-1 text-xs text-gray-500">
              <div>
                Format: {track.output_format?.toUpperCase() ?? "—"} | Duration:{" "}
                {track.duration ? formatDuration(track.duration) : "—"}
              </div>
              <div>
                Source: {track.source_codec ?? track.source_format ?? "—"} |{" "}
                {track.source_bitrate ? `${track.source_bitrate} kbps` : "—"}
              </div>
              <div>Status: {track.analysis_status}</div>
              <div className="mt-1 truncate" title={track.file_path}>
                {track.file_path}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}
