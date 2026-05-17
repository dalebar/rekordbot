import { useCallback, useState } from "react";
import { postOrganiseResolve, type ProposalResponse, type ProposalTrack } from "./api/client";

interface ReviewQueueProps {
  proposal: ProposalResponse;
  onClose: () => void;
  onRefresh: () => void;
}

export default function ReviewQueue({ proposal, onClose, onRefresh }: ReviewQueueProps) {
  const [reviewTracks, setReviewTracks] = useState<ProposalTrack[]>(proposal.needs_review);
  const [resolving, setResolving] = useState<number | null>(null);
  const [customPath, setCustomPath] = useState("");

  const handleResolve = useCallback(
    async (trackId: number, action: "accept" | "skip") => {
      setResolving(trackId);
      try {
        await postOrganiseResolve(trackId, { action });
        setReviewTracks((prev) => prev.filter((t) => t.track_id !== trackId));
        onRefresh();
      } catch {
        // Error handled by API client
      } finally {
        setResolving(null);
      }
    },
    [onRefresh],
  );

  const handleCustomPath = useCallback(
    async (trackId: number) => {
      if (!customPath.trim()) return;
      setResolving(trackId);
      try {
        await postOrganiseResolve(trackId, { action: "custom", custom_path: customPath.trim() });
        setReviewTracks((prev) => prev.filter((t) => t.track_id !== trackId));
        setCustomPath("");
        onRefresh();
      } catch {
        // Error handled by API client
      } finally {
        setResolving(null);
      }
    },
    [customPath, onRefresh],
  );

  if (reviewTracks.length === 0 && proposal.auto_approved.length === 0) {
    return null;
  }

  return (
    <div className="rounded border border-gray-800 bg-gray-900/50 p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-medium text-gray-300">Organisation Proposal</h3>
        <button onClick={onClose} className="text-xs text-gray-600 hover:text-gray-400">
          Close
        </button>
      </div>

      {/* Summary */}
      <div className="mb-3 flex gap-4 text-xs text-gray-500">
        <span className="text-emerald-400">{proposal.summary.auto_approved} auto-approved</span>
        <span className="text-amber-400">{proposal.summary.needs_review} need review</span>
        {proposal.summary.failed > 0 && (
          <span className="text-red-400">{proposal.summary.failed} failed</span>
        )}
      </div>

      {/* Review items */}
      {reviewTracks.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-xs font-medium text-amber-400">Needs Review</h4>
          {reviewTracks.map((track) => (
            <div
              key={track.track_id}
              className="flex items-start gap-3 rounded border border-gray-800 bg-gray-900 p-2 text-xs"
            >
              <div className="flex-1">
                <div className="text-gray-300">
                  {track.artist ?? "Unknown"} — {track.title ?? "Untitled"}
                </div>
                <div className="mt-0.5 text-gray-400" title={track.proposed_path ?? ""}>
                  {track.proposed_path ? truncatePath(track.proposed_path) : "No proposed path"}
                </div>
                {track.reasoning && (
                  <div className="mt-0.5 text-gray-400 italic">{track.reasoning}</div>
                )}
                {track.confidence !== null && (
                  <span className={`${track.confidence < 0.5 ? "text-red-400" : "text-amber-400"}`}>
                    Confidence: {(track.confidence * 100).toFixed(0)}%
                  </span>
                )}
              </div>
              <div className="flex flex-col gap-1">
                <button
                  onClick={() => handleResolve(track.track_id, "accept")}
                  disabled={resolving === track.track_id}
                  className="rounded bg-emerald-700 px-2 py-0.5 text-emerald-200 hover:bg-emerald-600 disabled:opacity-50"
                >
                  Accept
                </button>
                <button
                  onClick={() => handleResolve(track.track_id, "skip")}
                  disabled={resolving === track.track_id}
                  className="rounded bg-gray-700 px-2 py-0.5 text-gray-300 hover:bg-gray-600 disabled:opacity-50"
                >
                  Skip
                </button>
                <div className="flex gap-1">
                  <input
                    type="text"
                    placeholder="Custom path..."
                    value={resolving === track.track_id ? customPath : ""}
                    onChange={(e) => {
                      setCustomPath(e.target.value);
                    }}
                    onFocus={() => setCustomPath("")}
                    className="w-28 rounded border border-gray-700 bg-gray-800 px-1 py-0.5 text-gray-300 outline-none"
                  />
                  <button
                    onClick={() => handleCustomPath(track.track_id)}
                    disabled={resolving === track.track_id}
                    className="rounded bg-gray-700 px-1.5 py-0.5 text-gray-300 hover:bg-gray-600 disabled:opacity-50"
                  >
                    Set
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Auto-approved list (collapsed by default) */}
      {proposal.auto_approved.length > 0 && <AutoApprovedList tracks={proposal.auto_approved} />}
    </div>
  );
}

function AutoApprovedList({ tracks }: { tracks: ProposalTrack[] }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="mt-3">
      <button
        onClick={() => setExpanded(!expanded)}
        className="text-xs text-gray-500 hover:text-gray-300"
      >
        {expanded ? "Hide" : "Show"} {tracks.length} auto-approved tracks
      </button>
      {expanded && (
        <div className="mt-2 max-h-48 space-y-1 overflow-y-auto">
          {tracks.map((track) => (
            <div key={track.track_id} className="flex gap-2 text-xs text-gray-400">
              <span className="text-gray-400">
                {track.artist ?? "?"} — {track.title ?? "?"}
              </span>
              <span title={track.proposed_path ?? ""}>
                {track.proposed_path ? truncatePath(track.proposed_path) : "—"}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function truncatePath(path: string): string {
  const parts = path.split("/");
  if (parts.length <= 3) return path;
  return ".../" + parts.slice(-3).join("/");
}
