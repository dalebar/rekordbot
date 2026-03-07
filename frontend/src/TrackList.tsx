import { useCallback, useEffect, useState } from "react";
import { getTracks, type Track } from "./api/client";

interface TrackListProps {
  refreshTrigger: number;
}

export default function TrackList({ refreshTrigger }: TrackListProps) {
  const [tracks, setTracks] = useState<Track[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  const loadTracks = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getTracks(100, 0);
      setTracks(data.tracks);
      setTotal(data.total);
    } catch {
      // Silently handle — backend may not be ready
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadTracks();
  }, [loadTracks, refreshTrigger]);

  if (loading && tracks.length === 0) {
    return <p className="text-sm text-gray-600">Loading tracks...</p>;
  }

  if (tracks.length === 0) {
    return (
      <p className="text-sm text-gray-600">
        No tracks yet. Drop some audio files above to get started.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-gray-300">
          Library ({total} tracks)
        </h3>
        <button
          onClick={loadTracks}
          className="text-xs text-gray-500 hover:text-gray-300"
        >
          Refresh
        </button>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="border-b border-gray-800 text-gray-500">
              <th className="py-2 pr-4">File</th>
              <th className="py-2 pr-4">Source</th>
              <th className="py-2 pr-4">Output</th>
              <th className="py-2 pr-4">Bitrate</th>
              <th className="py-2 pr-4">Duration</th>
              <th className="py-2 pr-4">Action</th>
              <th className="py-2">Quality</th>
            </tr>
          </thead>
          <tbody>
            {tracks.map((track) => (
              <tr
                key={track.id}
                className="border-b border-gray-800/50 text-gray-400"
              >
                <td className="max-w-48 truncate py-1.5 pr-4" title={track.file_path}>
                  {track.file_path.split("/").pop()}
                </td>
                <td className="py-1.5 pr-4">
                  {track.source_codec ?? track.source_format ?? "—"}
                </td>
                <td className="py-1.5 pr-4 uppercase">
                  {track.output_format ?? "—"}
                </td>
                <td className="py-1.5 pr-4">
                  {track.source_bitrate ? `${track.source_bitrate} kbps` : "—"}
                </td>
                <td className="py-1.5 pr-4">
                  {track.duration ? formatDuration(track.duration) : "—"}
                </td>
                <td className="py-1.5 pr-4">
                  {formatAction(track.conversion_action)}
                </td>
                <td className="py-1.5">
                  {track.quality_warning ? (
                    <span className="text-yellow-400">Low quality</span>
                  ) : (
                    <span className="text-gray-600">OK</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function formatAction(action: string | null): string {
  if (!action) return "—";
  return action.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
