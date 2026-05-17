import { useCallback, useEffect, useState } from "react";
import {
  connectSetProgress,
  exportSet,
  getSet,
  lockTrack,
  removeTrackFromSet,
  shuffleSet,
  unlockTrack,
  updateSegment,
  type SetDetail,
  type SetSegmentItem,
  type SetTrackItem,
  type ShuffleMode,
} from "./api/client";

interface SetPlannerViewProps {
  setId: number;
  onBack: () => void;
}

/** BPM transition quality indicator. */
function bpmQuality(
  bpmA: number | null,
  bpmB: number | null,
): {
  label: string;
  color: string;
} {
  if (bpmA == null || bpmB == null) return { label: "", color: "" };
  const diff = Math.abs(bpmA - bpmB);
  if (diff <= 2) return { label: "smooth", color: "text-emerald-400" };
  if (diff <= 5) return { label: "acceptable", color: "text-blue-400" };
  if (diff <= 10) return { label: "noticeable", color: "text-amber-400" };
  return { label: "jarring", color: "text-red-400" };
}

/** Key compatibility indicator (simplified — green if same Camelot number group). */
function keyCompat(
  keyA: number | null,
  keyB: number | null,
): {
  label: string;
  color: string;
} {
  if (keyA == null || keyB == null) return { label: "", color: "" };
  // Same key
  if (keyA === keyB) return { label: "same", color: "text-emerald-400" };
  // Adjacent on Camelot wheel (simplified check — ±1 in same mode or relative)
  const modeA = keyA <= 12 ? "minor" : "major";
  const modeB = keyB <= 12 ? "minor" : "major";
  const numA = keyA <= 12 ? keyA : keyA - 12;
  const numB = keyB <= 12 ? keyB : keyB - 12;
  if (modeA === modeB && (Math.abs(numA - numB) === 1 || Math.abs(numA - numB) === 11)) {
    return { label: "adjacent", color: "text-emerald-400" };
  }
  // Relative major/minor
  if (numA === numB && modeA !== modeB) {
    return { label: "relative", color: "text-blue-400" };
  }
  return { label: "neutral", color: "text-gray-500" };
}

export default function SetPlannerView({ setId, onBack }: SetPlannerViewProps) {
  const [detail, setDetail] = useState<SetDetail | null>(null);
  const [shuffling, setShuffling] = useState(false);
  const [progressMessage, setProgressMessage] = useState<string | null>(null);
  const [showCandidates, setShowCandidates] = useState(false);
  const [editingSegmentId, setEditingSegmentId] = useState<number | null>(null);
  const [segmentText, setSegmentText] = useState("");

  const loadDetail = useCallback(() => {
    getSet(setId)
      .then(setDetail)
      .catch(() => {});
  }, [setId]);

  useEffect(() => {
    loadDetail();
  }, [loadDetail]);

  const handleLockToggle = useCallback(
    async (track: SetTrackItem) => {
      if (track.is_locked) {
        await unlockTrack(setId, track.position);
      } else {
        await lockTrack(setId, track.position);
      }
      loadDetail();
    },
    [setId, loadDetail],
  );

  const handleRemoveTrack = useCallback(
    async (position: number) => {
      await removeTrackFromSet(setId, position);
      loadDetail();
    },
    [setId, loadDetail],
  );

  const handleShuffle = useCallback(
    async (mode: ShuffleMode) => {
      setShuffling(true);
      setProgressMessage(`Shuffle (${mode}) started...`);

      await shuffleSet(setId, mode);

      connectSetProgress(
        setId,
        (_eventType, data) => {
          setProgressMessage(data || "Processing...");
        },
        () => {
          setShuffling(false);
          setProgressMessage(null);
          loadDetail();
        },
      );
    },
    [setId, loadDetail],
  );

  const handleExport = useCallback(async () => {
    try {
      const result = await exportSet(setId);
      setProgressMessage(`Exported ${result.tracks_in_set} tracks to ${result.output_path}`);
      setTimeout(() => setProgressMessage(null), 3000);
    } catch {
      setProgressMessage("Export failed");
      setTimeout(() => setProgressMessage(null), 3000);
    }
  }, [setId]);

  const handleSegmentSave = useCallback(
    async (segmentId: number) => {
      await updateSegment(setId, segmentId, segmentText || null);
      setEditingSegmentId(null);
      loadDetail();
    },
    [setId, segmentText, loadDetail],
  );

  const startEditSegment = useCallback((segment: SetSegmentItem) => {
    setEditingSegmentId(segment.id);
    setSegmentText(segment.description || "");
  }, []);

  if (!detail) {
    return <div className="flex items-center justify-center h-full text-gray-500">Loading...</div>;
  }

  // Get tracks in position order (non-candidates)
  const tracks = detail.tracks
    .filter((t) => !t.is_candidate)
    .sort((a, b) => a.position - b.position);

  // Find which segment a position belongs to
  const getSegmentForPosition = (position: number): SetSegmentItem | null => {
    return (
      detail.segments.find((s) => position >= s.start_position && position <= s.end_position) ||
      null
    );
  };

  // Determine segment boundaries for dividers
  const segmentStarts = new Set(detail.segments.map((s) => s.start_position));

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-3 border-b border-gray-800">
        <div className="flex items-center gap-4">
          <button className="text-sm text-gray-500 hover:text-gray-300" onClick={onBack}>
            &larr; Back
          </button>
          <div>
            <h2 className="text-sm font-semibold text-gray-200">{detail.name}</h2>
            <p className="text-xs text-gray-500">{detail.description}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`text-xs px-2 py-0.5 rounded ${
              detail.status === "complete"
                ? "bg-emerald-900/50 text-emerald-400"
                : "bg-blue-900/50 text-blue-400"
            }`}
          >
            {detail.status}
          </span>
          {detail.duration_minutes && (
            <span className="text-xs text-gray-600">{detail.duration_minutes} min</span>
          )}
        </div>
      </div>

      {/* Controls toolbar */}
      <div className="flex items-center gap-3 px-6 py-2 border-b border-gray-800/50 bg-gray-900/50">
        <button
          className="px-3 py-1.5 text-xs bg-blue-600 hover:bg-blue-500 text-white rounded disabled:opacity-50"
          onClick={() => handleShuffle("replace")}
          disabled={shuffling}
        >
          Shuffle: Replace
        </button>
        <button
          className="px-3 py-1.5 text-xs bg-blue-600 hover:bg-blue-500 text-white rounded disabled:opacity-50"
          onClick={() => handleShuffle("reorder")}
          disabled={shuffling}
        >
          Shuffle: Reorder
        </button>
        <div className="flex-1" />
        {progressMessage && <span className="text-xs text-blue-400">{progressMessage}</span>}
        <button
          className="px-3 py-1.5 text-xs text-gray-400 hover:text-gray-200 border border-gray-700 rounded"
          onClick={() => setShowCandidates(!showCandidates)}
        >
          {showCandidates ? "Hide" : "Show"} Candidates ({detail.candidates.length})
        </button>
        <button
          className="px-3 py-1.5 text-xs bg-amber-600 hover:bg-amber-500 text-white rounded"
          onClick={handleExport}
        >
          Export XML
        </button>
      </div>

      {/* Main content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Track sequence */}
        <div className="flex-1 overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-gray-950 text-xs text-gray-500 uppercase">
              <tr>
                <th className="px-3 py-2 text-left w-10">#</th>
                <th className="px-3 py-2 text-center w-10">Lock</th>
                <th className="px-3 py-2 text-left">Title</th>
                <th className="px-3 py-2 text-left">Artist</th>
                <th className="px-3 py-2 text-right w-16">BPM</th>
                <th className="px-3 py-2 text-center w-14">Key</th>
                <th className="px-3 py-2 text-center w-16">Energy</th>
                <th className="px-3 py-2 text-left w-24">Mood</th>
                <th className="px-3 py-2 text-center w-20">BPM Tx</th>
                <th className="px-3 py-2 text-center w-16">Key Tx</th>
                <th className="px-3 py-2 text-center w-10"></th>
              </tr>
            </thead>
            <tbody>
              {tracks.map((track, idx) => {
                const prevTrack = idx > 0 ? tracks[idx - 1] : null;
                const bpmTx = prevTrack
                  ? bpmQuality(prevTrack.bpm, track.bpm)
                  : { label: "", color: "" };
                const keyTx = prevTrack
                  ? keyCompat(prevTrack.key, track.key)
                  : { label: "", color: "" };

                // Check if this position starts a new segment
                const segment = getSegmentForPosition(track.position);
                const isSegmentStart = segmentStarts.has(track.position);

                return (
                  <>
                    {/* Segment divider */}
                    {isSegmentStart && segment && (
                      <tr key={`seg-${segment.id}`} className="bg-gray-900/80">
                        <td colSpan={11} className="px-3 py-1.5">
                          {editingSegmentId === segment.id ? (
                            <div className="flex items-center gap-2">
                              <input
                                type="text"
                                className="flex-1 px-2 py-1 bg-gray-800 border border-gray-700 rounded text-xs text-gray-100 focus:outline-none focus:border-blue-500"
                                value={segmentText}
                                onChange={(e) => setSegmentText(e.target.value)}
                                placeholder="Set description for this section"
                                autoFocus
                                onKeyDown={(e) => {
                                  if (e.key === "Enter") handleSegmentSave(segment.id);
                                  if (e.key === "Escape") setEditingSegmentId(null);
                                }}
                              />
                              <button
                                className="text-xs text-blue-400 hover:text-blue-300"
                                onClick={() => handleSegmentSave(segment.id)}
                              >
                                Save
                              </button>
                            </div>
                          ) : (
                            <button
                              className="text-xs text-gray-500 hover:text-gray-300 italic"
                              onClick={() => startEditSegment(segment)}
                            >
                              {segment.description || "Set description for this section..."}
                            </button>
                          )}
                        </td>
                      </tr>
                    )}
                    {/* Track row */}
                    <tr
                      key={track.track_id}
                      className={`border-b border-gray-800/30 hover:bg-gray-800/30 ${
                        track.is_locked ? "bg-blue-950/20" : ""
                      }`}
                    >
                      <td className="px-3 py-2 text-gray-600">{track.position}</td>
                      <td className="px-3 py-2 text-center">
                        <button
                          className={`text-sm ${
                            track.is_locked
                              ? "text-blue-400 hover:text-blue-300"
                              : "text-gray-700 hover:text-gray-400"
                          }`}
                          onClick={() => handleLockToggle(track)}
                          title={track.is_locked ? "Unlock" : "Lock"}
                        >
                          {track.is_locked ? "\u{1F512}" : "\u{1F513}"}
                        </button>
                      </td>
                      <td className="px-3 py-2 text-gray-200 truncate max-w-[200px]">
                        {track.title || "Untitled"}
                      </td>
                      <td className="px-3 py-2 text-gray-400 truncate max-w-[150px]">
                        {track.artist || "Unknown"}
                      </td>
                      <td className="px-3 py-2 text-right text-gray-300">
                        {track.bpm?.toFixed(1) || "—"}
                      </td>
                      <td className="px-3 py-2 text-center text-gray-300">
                        {track.key_display || "—"}
                      </td>
                      <td className="px-3 py-2 text-center">
                        {track.energy != null ? (
                          <span
                            className={
                              track.energy <= 3
                                ? "text-blue-400"
                                : track.energy <= 6
                                  ? "text-gray-300"
                                  : track.energy <= 8
                                    ? "text-amber-400"
                                    : "text-red-400"
                            }
                          >
                            {track.energy}
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="px-3 py-2 text-gray-500 truncate max-w-[100px]">
                        {track.mood || "—"}
                      </td>
                      <td className={`px-3 py-2 text-center text-xs ${bpmTx.color}`}>
                        {bpmTx.label}
                      </td>
                      <td className={`px-3 py-2 text-center text-xs ${keyTx.color}`}>
                        {keyTx.label}
                      </td>
                      <td className="px-3 py-2 text-center">
                        <button
                          className="text-gray-700 hover:text-red-400 text-xs"
                          onClick={() => handleRemoveTrack(track.position)}
                          title="Remove"
                        >
                          &times;
                        </button>
                      </td>
                    </tr>
                  </>
                );
              })}
              {tracks.length === 0 && (
                <tr>
                  <td colSpan={11} className="px-6 py-8 text-center text-gray-600">
                    {detail.status === "planning"
                      ? "Planning in progress..."
                      : "No tracks in this set yet"}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Candidate pool */}
        {showCandidates && (
          <div className="w-72 border-l border-gray-800 overflow-y-auto bg-gray-950/50">
            <div className="px-3 py-2 border-b border-gray-800 text-xs font-semibold text-gray-500 uppercase">
              Candidates ({detail.candidates.length})
            </div>
            {detail.candidates.map((cand) => (
              <div
                key={cand.track_id}
                className="px-3 py-2 border-b border-gray-800/30 text-xs hover:bg-gray-800/30"
              >
                <div className="text-gray-300 truncate">{cand.title || "Untitled"}</div>
                <div className="text-gray-600 truncate">{cand.artist || "Unknown"}</div>
                <div className="flex gap-2 mt-0.5 text-gray-600">
                  {cand.bpm && <span>{cand.bpm.toFixed(0)} BPM</span>}
                  {cand.key_display && <span>{cand.key_display}</span>}
                  {cand.energy != null && <span>E{cand.energy}</span>}
                </div>
              </div>
            ))}
            {detail.candidates.length === 0 && (
              <p className="px-3 py-4 text-xs text-gray-700 text-center">No candidates</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
