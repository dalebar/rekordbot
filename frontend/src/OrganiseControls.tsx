import { useCallback, useState } from "react";
import {
  connectOrganiseProgress,
  getOrganiseProposal,
  postOrganiseApprove,
  postOrganiseCancel,
  postOrganisePropose,
  type ApproveResponse,
  type OrganiseProgressEvent,
  type ProposalResponse,
} from "./api/client";

export type OrganiseFilterMode = "all" | "unorganised" | "proposed" | "review_needed" | "organised";

interface OrganiseControlsProps {
  selectedTrackIds: number[];
  onRefresh: () => void;
  filter: OrganiseFilterMode;
  onFilterChange: (filter: OrganiseFilterMode) => void;
  onProposalReady: (proposal: ProposalResponse) => void;
}

export default function OrganiseControls({
  selectedTrackIds,
  onRefresh,
  filter,
  onFilterChange,
  onProposalReady,
}: OrganiseControlsProps) {
  const [proposing, setProposing] = useState(false);
  const [progress, setProgress] = useState({ processed: 0, total: 0 });
  const [approving, setApproving] = useState(false);
  const [approveResult, setApproveResult] = useState<ApproveResponse | null>(null);

  const handlePropose = useCallback(async () => {
    try {
      setApproveResult(null);
      const body =
        selectedTrackIds.length > 0
          ? { track_ids: selectedTrackIds, options: { skip_if_organised: false } }
          : {};
      const response = await postOrganisePropose(body);
      if (response.total_tracks === 0) return;

      setProposing(true);
      setProgress({ processed: 0, total: response.total_tracks });

      connectOrganiseProgress(
        (event: OrganiseProgressEvent) => {
          setProgress({ processed: event.tracks_processed, total: event.tracks_total });
        },
        async () => {
          setProposing(false);
          onRefresh();
          // Fetch and display the proposal
          try {
            const proposal = await getOrganiseProposal();
            onProposalReady(proposal);
          } catch {
            // Ignore
          }
        },
      );
    } catch {
      // Error handled by API client
    }
  }, [selectedTrackIds, onRefresh, onProposalReady]);

  const handleCancel = useCallback(async () => {
    try {
      await postOrganiseCancel();
    } catch {
      // Ignore
    }
  }, []);

  const handleApprove = useCallback(
    async (mode: "auto_approved" | "all") => {
      setApproving(true);
      try {
        const result = await postOrganiseApprove({ mode });
        setApproveResult(result);
        onRefresh();
      } catch {
        // Error handled by API client
      } finally {
        setApproving(false);
      }
    },
    [onRefresh],
  );

  const progressPct = progress.total > 0 ? (progress.processed / progress.total) * 100 : 0;

  const filterLabels: Record<OrganiseFilterMode, string> = {
    all: "All",
    unorganised: "Unorganised",
    proposed: "Proposed",
    review_needed: "Needs Review",
    organised: "Organised",
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-3">
        {/* Propose button */}
        <button
          onClick={handlePropose}
          disabled={proposing}
          className="rounded bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
        >
          {proposing
            ? "Previewing..."
            : selectedTrackIds.length > 0
              ? `Preview Organisation (${selectedTrackIds.length})`
              : "Preview Organisation"}
        </button>

        {/* Cancel */}
        {proposing && (
          <button
            onClick={handleCancel}
            className="rounded border border-gray-700 px-3 py-1.5 text-xs text-gray-400 hover:text-gray-200"
          >
            Cancel
          </button>
        )}

        {/* Approve auto-approved */}
        <button
          onClick={() => handleApprove("auto_approved")}
          disabled={approving || proposing}
          className="rounded border border-emerald-700 px-3 py-1.5 text-xs text-emerald-400 hover:text-emerald-300 disabled:opacity-50"
        >
          {approving ? "Moving..." : "Approve Auto"}
        </button>

        {/* Approve all */}
        <button
          onClick={() => handleApprove("all")}
          disabled={approving || proposing}
          className="rounded border border-gray-700 px-3 py-1.5 text-xs text-gray-400 hover:text-gray-200 disabled:opacity-50"
        >
          Approve All
        </button>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Filter buttons */}
        <div className="flex flex-wrap items-center gap-1 text-xs">
          {(["all", "unorganised", "proposed", "review_needed", "organised"] as const).map((f) => (
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

      {/* Proposal progress bar */}
      {proposing && (
        <div className="flex items-center gap-2">
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-gray-800">
            <div
              className="h-full rounded-full bg-emerald-500 transition-all duration-300"
              style={{ width: `${progressPct}%` }}
            />
          </div>
          <span className="text-xs text-gray-500">
            {progress.processed}/{progress.total}
          </span>
        </div>
      )}

      {/* Approve result summary */}
      {approveResult && (
        <div className="flex items-center gap-3 text-xs text-gray-500">
          <span>
            Moved: {approveResult.total_moved}
            {approveResult.skipped > 0 && `, ${approveResult.skipped} already in place`}
            {approveResult.failed > 0 && `, ${approveResult.failed} failed`}
            {approveResult.dirs_cleaned > 0 && `, ${approveResult.dirs_cleaned} empty dirs cleaned`}
          </span>
          <button
            onClick={() => setApproveResult(null)}
            className="text-gray-600 hover:text-gray-400"
          >
            Dismiss
          </button>
        </div>
      )}
    </div>
  );
}
