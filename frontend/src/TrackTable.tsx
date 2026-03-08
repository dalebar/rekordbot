import { useCallback, useEffect, useMemo, useState } from "react";
import {
  bpmMultiply,
  getCrate,
  getTracks,
  updateTrack,
  type ProposalResponse,
  type Track,
  type TrackUpdate,
} from "./api/client";
import AnalysisControls, { type FilterMode } from "./AnalysisControls";
import ColumnMenu, { type ColumnConfig } from "./ColumnMenu";
import ExportControls from "./ExportControls";
import OrganiseControls, { type OrganiseFilterMode } from "./OrganiseControls";
import PreferenceRulesPanel from "./PreferenceRulesPanel";
import ReviewQueue from "./ReviewQueue";
import TrackDetailPanel from "./TrackDetailPanel";

interface TrackTableProps {
  refreshTrigger: number;
  crateId?: number | null;
}

type SortField = string;
type SortDir = "asc" | "desc";

const DEFAULT_COLUMNS: ColumnConfig[] = [
  { id: "title", label: "Title", visible: true, defaultVisible: true },
  { id: "artist", label: "Artist", visible: true, defaultVisible: true },
  { id: "album", label: "Album", visible: true, defaultVisible: true },
  { id: "genre", label: "Genre", visible: true, defaultVisible: true },
  { id: "bpm", label: "BPM", visible: true, defaultVisible: true },
  { id: "key", label: "Key", visible: true, defaultVisible: true },
  { id: "duration", label: "Duration", visible: true, defaultVisible: true },
  { id: "bitrate", label: "Bitrate", visible: true, defaultVisible: true },
  { id: "quality", label: "Quality", visible: true, defaultVisible: true },
  { id: "date_added", label: "Date Added", visible: true, defaultVisible: true },
  { id: "album_artist", label: "Album Artist", visible: false, defaultVisible: false },
  { id: "year", label: "Year", visible: false, defaultVisible: false },
  { id: "label", label: "Label", visible: false, defaultVisible: false },
  { id: "track_number", label: "Track #", visible: false, defaultVisible: false },
  { id: "rating", label: "Rating", visible: false, defaultVisible: false },
  { id: "comment", label: "Comment", visible: false, defaultVisible: false },
  { id: "source_format", label: "Source Format", visible: false, defaultVisible: false },
  { id: "conversion_action", label: "Action", visible: false, defaultVisible: false },
  { id: "bpm_confidence", label: "BPM Conf.", visible: false, defaultVisible: false },
  { id: "key_confidence", label: "Key Conf.", visible: false, defaultVisible: false },
  { id: "analysis_status", label: "Status", visible: false, defaultVisible: false },
  { id: "subgenre", label: "Subgenre", visible: false, defaultVisible: false },
  { id: "mood", label: "Mood", visible: true, defaultVisible: true },
  { id: "energy", label: "Energy", visible: true, defaultVisible: true },
  { id: "ai_confidence", label: "AI Conf.", visible: false, defaultVisible: false },
  { id: "ai_status", label: "AI Status", visible: false, defaultVisible: false },
  { id: "organisation_status", label: "Org Status", visible: false, defaultVisible: false },
];

const CONFIDENCE_THRESHOLD = 0.6;

export default function TrackTable({ refreshTrigger, crateId }: TrackTableProps) {
  const [tracks, setTracks] = useState<Track[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [columns, setColumns] = useState<ColumnConfig[]>(DEFAULT_COLUMNS);
  const [sortField, setSortField] = useState<SortField>("title");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [detailTrack, setDetailTrack] = useState<Track | null>(null);
  const [columnMenuPos, setColumnMenuPos] = useState<{ x: number; y: number } | null>(null);
  const [filter, setFilter] = useState<FilterMode>("all");
  const [organiseFilter, setOrganiseFilter] = useState<OrganiseFilterMode>("all");
  const [proposal, setProposal] = useState<ProposalResponse | null>(null);
  const [editingCell, setEditingCell] = useState<{ trackId: number; field: string } | null>(null);
  const [editValue, setEditValue] = useState("");
  const [crateTrackIds, setCrateTrackIds] = useState<Set<number> | null>(null);

  const loadTracks = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getTracks(500, 0);
      setTracks(data.tracks);
      setTotal(data.total);

      // Load crate track IDs if a crate is selected
      if (crateId) {
        const crateDetail = await getCrate(crateId);
        setCrateTrackIds(new Set(crateDetail.track_ids));
      } else {
        setCrateTrackIds(null);
      }
    } catch {
      // Backend may not be ready
    } finally {
      setLoading(false);
    }
  }, [crateId]);

  useEffect(() => {
    loadTracks();
  }, [loadTracks, refreshTrigger, crateId]);

  // Filter tracks
  const filteredTracks = useMemo(() => {
    return tracks.filter((t) => {
      // Crate filter: only show tracks in selected crate
      if (crateTrackIds && !crateTrackIds.has(t.id)) return false;

      // Analysis filters
      if (filter === "unanalysed") return t.analysis_status === "unanalysed";
      if (filter === "low_confidence") {
        return (
          (t.bpm_confidence !== null && t.bpm_confidence < CONFIDENCE_THRESHOLD) ||
          (t.key_confidence !== null && t.key_confidence < CONFIDENCE_THRESHOLD)
        );
      }
      if (filter === "conflicts") return t.has_bpm_conflict || t.has_key_conflict;
      if (filter === "ai_tagged") return t.ai_status === "ai_tagged" || t.ai_status === "ai_tags_written";
      if (filter === "not_ai_tagged") return t.ai_status === "untagged";

      // Organisation filters
      if (organiseFilter === "unorganised") return t.organisation_status === "unorganised";
      if (organiseFilter === "proposed") return t.organisation_status === "proposed";
      if (organiseFilter === "review_needed") return t.organisation_status === "review_needed";
      if (organiseFilter === "organised") return t.organisation_status === "organised";

      return true;
    });
  }, [tracks, filter, organiseFilter, crateTrackIds]);

  // Sort tracks
  const sortedTracks = useMemo(() => {
    const sorted = [...filteredTracks];
    sorted.sort((a, b) => {
      const aVal = getFieldValue(a, sortField);
      const bVal = getFieldValue(b, sortField);
      if (aVal === null || aVal === undefined) return 1;
      if (bVal === null || bVal === undefined) return -1;
      if (typeof aVal === "number" && typeof bVal === "number") {
        return sortDir === "asc" ? aVal - bVal : bVal - aVal;
      }
      const aStr = String(aVal).toLowerCase();
      const bStr = String(bVal).toLowerCase();
      return sortDir === "asc" ? aStr.localeCompare(bStr) : bStr.localeCompare(aStr);
    });
    return sorted;
  }, [filteredTracks, sortField, sortDir]);

  const visibleColumns = useMemo(() => columns.filter((c) => c.visible), [columns]);

  const handleSort = useCallback(
    (field: string) => {
      if (sortField === field) {
        setSortDir((d) => (d === "asc" ? "desc" : "asc"));
      } else {
        setSortField(field);
        setSortDir("asc");
      }
    },
    [sortField],
  );

  const handleHeaderContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setColumnMenuPos({ x: e.clientX, y: e.clientY });
  }, []);

  const handleToggleColumn = useCallback((columnId: string) => {
    setColumns((prev) => prev.map((c) => (c.id === columnId ? { ...c, visible: !c.visible } : c)));
  }, []);

  const handleResetColumns = useCallback(() => {
    setColumns(DEFAULT_COLUMNS.map((c) => ({ ...c, visible: c.defaultVisible })));
  }, []);

  const handleRowClick = useCallback(
    (track: Track, e: React.MouseEvent) => {
      if (e.metaKey || e.ctrlKey) {
        setSelectedIds((prev) => {
          const next = new Set(prev);
          if (next.has(track.id)) next.delete(track.id);
          else next.add(track.id);
          return next;
        });
      } else if (e.shiftKey && selectedIds.size > 0) {
        const ids = sortedTracks.map((t) => t.id);
        const lastSelected = [...selectedIds].pop()!;
        const lastIdx = ids.indexOf(lastSelected);
        const currentIdx = ids.indexOf(track.id);
        const [start, end] = lastIdx < currentIdx ? [lastIdx, currentIdx] : [currentIdx, lastIdx];
        const rangeIds = ids.slice(start, end + 1);
        setSelectedIds(new Set([...selectedIds, ...rangeIds]));
      } else {
        setSelectedIds(new Set([track.id]));
        setDetailTrack(track);
      }
    },
    [selectedIds, sortedTracks],
  );

  const handleCellDoubleClick = useCallback(
    (trackId: number, field: string, currentValue: string) => {
      setEditingCell({ trackId, field });
      setEditValue(currentValue);
    },
    [],
  );

  const handleCellSave = useCallback(async () => {
    if (!editingCell) return;
    const { trackId, field } = editingCell;

    const update: TrackUpdate = {};
    if (field === "bpm") {
      update.bpm = parseFloat(editValue);
    } else if (field === "key") {
      update.key = parseInt(editValue, 10);
    } else if (field === "year") {
      update.year = parseInt(editValue, 10);
    } else if (field === "energy") {
      update.energy = parseInt(editValue, 10);
    } else {
      (update as Record<string, string>)[field] = editValue;
    }

    try {
      const updated = await updateTrack(trackId, update);
      setTracks((prev) => prev.map((t) => (t.id === updated.id ? updated : t)));
      if (detailTrack?.id === updated.id) setDetailTrack(updated);
    } catch {
      // Error
    }
    setEditingCell(null);
  }, [editingCell, editValue, detailTrack]);

  const handleBpmMultiply = useCallback(
    async (trackId: number, factor: 2 | 0.5) => {
      try {
        const updated = await bpmMultiply(trackId, factor);
        setTracks((prev) => prev.map((t) => (t.id === updated.id ? updated : t)));
        if (detailTrack?.id === updated.id) setDetailTrack(updated);
      } catch {
        // Error
      }
    },
    [detailTrack],
  );

  const handleTrackUpdated = useCallback((updated: Track) => {
    setTracks((prev) => prev.map((t) => (t.id === updated.id ? updated : t)));
    setDetailTrack(updated);
  }, []);

  if (loading && tracks.length === 0) {
    return <p className="text-sm text-gray-600">Loading tracks...</p>;
  }

  if (tracks.length === 0 && !crateId) {
    return (
      <p className="text-sm text-gray-600">
        No tracks yet. Drop some audio files above to get started.
      </p>
    );
  }

  return (
    <div className="flex flex-1 flex-col gap-3">
      {/* Analysis toolbar */}
      <AnalysisControls
        selectedTrackIds={[...selectedIds]}
        onRefresh={loadTracks}
        filter={filter}
        onFilterChange={(f) => {
          setFilter(f);
          if (f !== "all") setOrganiseFilter("all");
        }}
      />

      {/* Organisation toolbar */}
      <OrganiseControls
        selectedTrackIds={[...selectedIds]}
        onRefresh={loadTracks}
        filter={organiseFilter}
        onFilterChange={(f) => {
          setOrganiseFilter(f);
          if (f !== "all") setFilter("all");
        }}
        onProposalReady={setProposal}
      />

      {/* Export toolbar */}
      <ExportControls trackCount={total} onRefresh={loadTracks} />

      {/* Review queue (shown when proposal has items needing review) */}
      {proposal && (
        <ReviewQueue
          proposal={proposal}
          onClose={() => setProposal(null)}
          onRefresh={loadTracks}
        />
      )}

      {/* Track count */}
      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-500">
          {filteredTracks.length} of {total} tracks
          {selectedIds.size > 0 && ` (${selectedIds.size} selected)`}
        </span>
        <button onClick={loadTracks} className="text-xs text-gray-500 hover:text-gray-300">
          Refresh
        </button>
      </div>

      {/* Table + detail panel layout */}
      <div className="flex flex-1 overflow-hidden">
        {/* Table */}
        <div className="flex-1 overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr
                className="border-b border-gray-800 text-gray-500"
                onContextMenu={handleHeaderContextMenu}
              >
                {visibleColumns.map((col) => (
                  <th
                    key={col.id}
                    className="cursor-pointer select-none whitespace-nowrap py-2 pr-3 hover:text-gray-300"
                    onClick={() => handleSort(col.id)}
                  >
                    {col.label}
                    {sortField === col.id && (
                      <span className="ml-1">{sortDir === "asc" ? "\u25B2" : "\u25BC"}</span>
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sortedTracks.map((track) => (
                <tr
                  key={track.id}
                  className={`cursor-pointer border-b border-gray-800/50 ${
                    selectedIds.has(track.id) ? "bg-blue-900/30 text-gray-200" : "text-gray-400"
                  } hover:bg-gray-800/50`}
                  onClick={(e) => handleRowClick(track, e)}
                >
                  {visibleColumns.map((col) => (
                    <td key={col.id} className="whitespace-nowrap py-1.5 pr-3">
                      {renderCell(
                        track,
                        col.id,
                        editingCell,
                        editValue,
                        setEditValue,
                        handleCellDoubleClick,
                        handleCellSave,
                        handleBpmMultiply,
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Detail panel */}
        {detailTrack && (
          <div className="w-72 shrink-0">
            <TrackDetailPanel
              track={detailTrack}
              onClose={() => setDetailTrack(null)}
              onTrackUpdated={handleTrackUpdated}
            />
          </div>
        )}
      </div>

      {/* Preference rules panel */}
      <PreferenceRulesPanel />

      {/* Column visibility menu */}
      {columnMenuPos && (
        <ColumnMenu
          columns={columns}
          onToggle={handleToggleColumn}
          onResetDefaults={handleResetColumns}
          onClose={() => setColumnMenuPos(null)}
          position={columnMenuPos}
        />
      )}
    </div>
  );
}

function getFieldValue(track: Track, field: string): string | number | boolean | null {
  switch (field) {
    case "title":
      return track.title;
    case "artist":
      return track.artist;
    case "album":
      return track.album;
    case "genre":
      return track.genre;
    case "bpm":
      return track.bpm;
    case "key":
      return track.key_display;
    case "duration":
      return track.duration;
    case "bitrate":
      return track.source_bitrate;
    case "quality":
      return track.quality_warning ? 1 : 0;
    case "date_added":
      return track.imported_at;
    case "year":
      return track.year;
    case "label":
      return track.label;
    case "track_number":
      return track.track_number;
    case "rating":
      return track.rating;
    case "comment":
      return track.comment;
    case "source_format":
      return track.source_format;
    case "conversion_action":
      return track.conversion_action;
    case "bpm_confidence":
      return track.bpm_confidence;
    case "key_confidence":
      return track.key_confidence;
    case "analysis_status":
      return track.analysis_status;
    case "subgenre":
      return track.subgenre;
    case "mood":
      return track.mood;
    case "energy":
      return track.energy;
    case "ai_confidence":
      return track.ai_confidence;
    case "ai_status":
      return track.ai_status;
    case "organisation_status":
      return track.organisation_status;
    default:
      return null;
  }
}

function renderCell(
  track: Track,
  field: string,
  editingCell: { trackId: number; field: string } | null,
  editValue: string,
  setEditValue: (v: string) => void,
  onDoubleClick: (trackId: number, field: string, currentValue: string) => void,
  onSave: () => void,
  onBpmMultiply: (trackId: number, factor: 2 | 0.5) => void,
): React.ReactNode {
  const isEditing = editingCell?.trackId === track.id && editingCell?.field === field;
  // Inline editing
  if (isEditing) {
    return (
      <input
        autoFocus
        type={field === "bpm" || field === "year" || field === "energy" ? "number" : "text"}
        step={field === "bpm" ? "0.01" : undefined}
        value={editValue}
        onChange={(e) => setEditValue(e.target.value)}
        onBlur={onSave}
        onKeyDown={(e) => {
          if (e.key === "Enter") onSave();
          if (e.key === "Escape") onSave();
        }}
        className="w-full rounded border border-blue-500 bg-gray-800 px-1 py-0.5 text-xs text-gray-200 outline-none"
        onClick={(e) => e.stopPropagation()}
      />
    );
  }

  switch (field) {
    case "title":
    case "artist":
    case "album":
    case "label":
    case "comment": {
      const value = getFieldValue(track, field) as string | null;
      return (
        <span
          className="max-w-48 truncate"
          title={value ?? ""}
          onDoubleClick={(e) => {
            e.stopPropagation();
            onDoubleClick(track.id, field, value ?? "");
          }}
        >
          {value ?? "—"}
        </span>
      );
    }

    case "genre": {
      const genreValue = track.genre;
      const tooltip =
        track.ai_reasoning && track.ai_status !== "untagged"
          ? `${genreValue ?? ""}\n\nAI: ${track.ai_reasoning}`
          : (genreValue ?? "");
      return (
        <span
          className="max-w-48 truncate"
          title={tooltip}
          onDoubleClick={(e) => {
            e.stopPropagation();
            onDoubleClick(track.id, "genre", genreValue ?? "");
          }}
        >
          {genreValue ?? "—"}
        </span>
      );
    }

    case "bpm": {
      const isLowConf = track.bpm_confidence !== null && track.bpm_confidence < 0.6;
      return (
        <span
          className={`group inline-flex items-center gap-1 ${isLowConf ? "text-amber-400" : ""} ${track.has_bpm_conflict ? "underline decoration-amber-400 decoration-dotted" : ""}`}
          onDoubleClick={(e) => {
            e.stopPropagation();
            onDoubleClick(track.id, "bpm", track.bpm?.toFixed(2) ?? "");
          }}
        >
          {track.bpm !== null ? track.bpm.toFixed(2) : "—"}
          {track.bpm !== null && (
            <span className="hidden gap-0.5 group-hover:inline-flex">
              <button
                className="rounded bg-gray-700 px-1 text-gray-400 hover:text-gray-200"
                onClick={(e) => {
                  e.stopPropagation();
                  onBpmMultiply(track.id, 0.5);
                }}
                title="Halve BPM"
              >
                /2
              </button>
              <button
                className="rounded bg-gray-700 px-1 text-gray-400 hover:text-gray-200"
                onClick={(e) => {
                  e.stopPropagation();
                  onBpmMultiply(track.id, 2);
                }}
                title="Double BPM"
              >
                x2
              </button>
            </span>
          )}
        </span>
      );
    }

    case "key": {
      const isLowConf = track.key_confidence !== null && track.key_confidence < 0.6;
      return (
        <span
          className={`${isLowConf ? "text-amber-400" : ""} ${track.has_key_conflict ? "underline decoration-amber-400 decoration-dotted" : ""}`}
        >
          {track.key_display ?? "—"}
        </span>
      );
    }

    case "duration":
      return track.duration ? formatDuration(track.duration) : "—";

    case "bitrate":
      return track.source_bitrate ? `${track.source_bitrate}` : "—";

    case "quality":
      return track.quality_warning ? (
        <span className="text-yellow-400">!</span>
      ) : (
        <span className="text-gray-600">OK</span>
      );

    case "date_added":
      return track.imported_at ? formatDate(track.imported_at) : "—";

    case "year":
      return (
        <span
          onDoubleClick={(e) => {
            e.stopPropagation();
            onDoubleClick(track.id, "year", String(track.year ?? ""));
          }}
        >
          {track.year ?? "—"}
        </span>
      );

    case "track_number":
      return track.track_number ?? "—";

    case "rating":
      return track.rating > 0 ? track.rating : "—";

    case "source_format":
      return track.source_codec ?? track.source_format ?? "—";

    case "conversion_action":
      return formatAction(track.conversion_action);

    case "bpm_confidence":
      return track.bpm_confidence !== null ? `${(track.bpm_confidence * 100).toFixed(0)}%` : "—";

    case "key_confidence":
      return track.key_confidence !== null ? `${(track.key_confidence * 100).toFixed(0)}%` : "—";

    case "analysis_status":
      return (
        <span
          className={`${
            track.analysis_status === "analysed"
              ? "text-emerald-400"
              : track.analysis_status === "tags_written"
                ? "text-blue-400"
                : "text-gray-500"
          }`}
        >
          {track.analysis_status}
        </span>
      );

    case "subgenre":
    case "mood": {
      const aiTextValue = getFieldValue(track, field) as string | null;
      return (
        <span
          className="max-w-48 truncate"
          title={aiTextValue ?? ""}
          onDoubleClick={(e) => {
            e.stopPropagation();
            onDoubleClick(track.id, field, aiTextValue ?? "");
          }}
        >
          {aiTextValue ?? "—"}
        </span>
      );
    }

    case "energy": {
      if (track.energy === null) return <span>—</span>;
      const energyColor =
        track.energy <= 3
          ? "text-blue-400"
          : track.energy <= 6
            ? "text-gray-300"
            : track.energy <= 8
              ? "text-amber-400"
              : "text-red-400";
      return (
        <span
          className={energyColor}
          onDoubleClick={(e) => {
            e.stopPropagation();
            onDoubleClick(track.id, "energy", String(track.energy ?? ""));
          }}
        >
          {track.energy}
        </span>
      );
    }

    case "ai_confidence": {
      if (!track.ai_confidence) return <span>—</span>;
      const confColor =
        track.ai_confidence === "high"
          ? "text-emerald-400"
          : track.ai_confidence === "medium"
            ? "text-amber-400"
            : "text-red-400";
      return <span className={confColor}>{track.ai_confidence}</span>;
    }

    case "ai_status":
      return (
        <span
          className={`${
            track.ai_status === "ai_tagged"
              ? "text-emerald-400"
              : track.ai_status === "ai_tags_written"
                ? "text-blue-400"
                : track.ai_status === "ai_failed"
                  ? "text-red-400"
                  : "text-gray-500"
          }`}
        >
          {track.ai_status}
        </span>
      );

    case "organisation_status":
      return (
        <span
          className={`${
            track.organisation_status === "organised"
              ? "text-emerald-400"
              : track.organisation_status === "proposed"
                ? "text-blue-400"
                : track.organisation_status === "review_needed"
                  ? "text-amber-400"
                  : "text-gray-500"
          }`}
        >
          {track.organisation_status}
        </span>
      );

    default:
      return "—";
  }
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString();
  } catch {
    return iso;
  }
}

function formatAction(action: string | null): string {
  if (!action) return "—";
  return action.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
