import { useCallback, useEffect, useState } from "react";
import {
  deleteCrate,
  listCrates,
  listSets,
  refreshCrate,
  updateCrate,
  type CrateSummary,
  type SetSummary,
} from "./api/client";

interface CrateSidebarProps {
  onCrateSelect: (crateId: number | null) => void;
  selectedCrateId: number | null;
  onNewCrate: () => void;
  refreshTrigger: number;
  onSetSelect?: (setId: number) => void;
  onNewSet?: () => void;
  setRefreshTrigger?: number;
  onOpenSettings?: () => void;
}

export default function CrateSidebar({
  onCrateSelect,
  selectedCrateId,
  onNewCrate,
  refreshTrigger,
  onSetSelect,
  onNewSet,
  setRefreshTrigger,
  onOpenSettings,
}: CrateSidebarProps) {
  const [crates, setCrates] = useState<CrateSummary[]>([]);
  const [sets, setSets] = useState<SetSummary[]>([]);
  const [contextMenu, setContextMenu] = useState<{
    crateId: number;
    x: number;
    y: number;
  } | null>(null);

  const loadCrates = useCallback(() => {
    listCrates()
      .then(setCrates)
      .catch(() => {});
  }, []);

  const loadSets = useCallback(() => {
    listSets()
      .then(setSets)
      .catch(() => {});
  }, []);

  useEffect(() => {
    loadCrates();
  }, [loadCrates, refreshTrigger]);

  useEffect(() => {
    loadSets();
  }, [loadSets, setRefreshTrigger]);

  const handleContextMenu = useCallback((e: React.MouseEvent, crateId: number) => {
    e.preventDefault();
    setContextMenu({ crateId, x: e.clientX, y: e.clientY });
  }, []);

  const closeContextMenu = useCallback(() => {
    setContextMenu(null);
  }, []);

  const handleRefresh = useCallback(
    async (crateId: number) => {
      closeContextMenu();
      await refreshCrate(crateId);
      loadCrates();
    },
    [closeContextMenu, loadCrates],
  );

  const handleDelete = useCallback(
    async (crateId: number) => {
      closeContextMenu();
      await deleteCrate(crateId);
      if (selectedCrateId === crateId) {
        onCrateSelect(null);
      }
      loadCrates();
    },
    [closeContextMenu, loadCrates, selectedCrateId, onCrateSelect],
  );

  const handleToggleAutoRefresh = useCallback(
    async (crate: CrateSummary) => {
      closeContextMenu();
      await updateCrate(crate.id, { auto_refresh: !crate.auto_refresh });
      loadCrates();
    },
    [closeContextMenu, loadCrates],
  );

  // Close context menu on click outside
  useEffect(() => {
    if (contextMenu) {
      const handler = () => setContextMenu(null);
      window.addEventListener("click", handler);
      return () => window.removeEventListener("click", handler);
    }
  }, [contextMenu]);

  return (
    <aside className="w-60 border-r border-gray-800 flex flex-col">
      <div className="p-4">
        <h2 className="text-lg font-semibold tracking-tight">rekordbot</h2>
      </div>

      {/* Library link */}
      <button
        className={`mx-2 px-3 py-1.5 text-sm text-left rounded ${
          selectedCrateId === null
            ? "bg-gray-800 text-white"
            : "text-gray-400 hover:text-gray-200 hover:bg-gray-800/50"
        }`}
        onClick={() => onCrateSelect(null)}
      >
        All Tracks
      </button>

      {/* Crates section */}
      <div className="mt-4 px-4 flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wider text-gray-500">Crates</span>
        <button className="text-xs text-purple-400 hover:text-purple-300" onClick={onNewCrate}>
          + New
        </button>
      </div>

      <div className="mt-1 flex-1 overflow-y-auto">
        {crates.map((crate) => (
          <button
            key={crate.id}
            className={`mx-2 px-3 py-1.5 text-sm text-left rounded w-[calc(100%-1rem)] flex items-center justify-between ${
              selectedCrateId === crate.id
                ? "bg-gray-800 text-white"
                : "text-gray-400 hover:text-gray-200 hover:bg-gray-800/50"
            }`}
            onClick={() => onCrateSelect(crate.id)}
            onContextMenu={(e) => handleContextMenu(e, crate.id)}
          >
            <span className="truncate">{crate.name}</span>
            <span className="ml-2 text-xs text-gray-600">{crate.track_count}</span>
          </button>
        ))}

        {crates.length === 0 && <p className="px-4 py-2 text-xs text-gray-600">No crates yet</p>}
      </div>

      {/* Sets section */}
      {onSetSelect && (
        <>
          <div className="mt-4 px-4 flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-gray-500">
              Sets
            </span>
            {onNewSet && (
              <button className="text-xs text-blue-400 hover:text-blue-300" onClick={onNewSet}>
                + New
              </button>
            )}
          </div>

          <div className="mt-1 mb-2">
            {sets.map((set) => (
              <button
                key={set.id}
                className="mx-2 px-3 py-1.5 text-sm text-left rounded w-[calc(100%-1rem)] flex items-center justify-between text-gray-400 hover:text-gray-200 hover:bg-gray-800/50"
                onClick={() => onSetSelect(set.id)}
              >
                <span className="truncate">{set.name}</span>
                <span className="ml-2 text-xs text-gray-600">{set.track_count}</span>
              </button>
            ))}
            {sets.length === 0 && <p className="px-4 py-2 text-xs text-gray-600">No sets yet</p>}
          </div>
        </>
      )}

      {/* Settings button */}
      {onOpenSettings && (
        <div className="border-t border-gray-800 p-2">
          <button
            className="w-full px-3 py-1.5 text-sm text-left text-gray-400 hover:text-gray-200 hover:bg-gray-800/50 rounded"
            onClick={onOpenSettings}
          >
            Settings
          </button>
        </div>
      )}

      {/* Context menu */}
      {contextMenu && (
        <div
          className="fixed z-50 bg-gray-900 border border-gray-700 rounded shadow-lg py-1 text-sm"
          style={{ left: contextMenu.x, top: contextMenu.y }}
        >
          <button
            className="w-full px-4 py-1.5 text-left text-gray-300 hover:bg-gray-800"
            onClick={() => handleRefresh(contextMenu.crateId)}
          >
            Refresh
          </button>
          <button
            className="w-full px-4 py-1.5 text-left text-gray-300 hover:bg-gray-800"
            onClick={() => {
              const crate = crates.find((c) => c.id === contextMenu.crateId);
              if (crate) handleToggleAutoRefresh(crate);
            }}
          >
            {crates.find((c) => c.id === contextMenu.crateId)?.auto_refresh
              ? "Disable Auto-refresh"
              : "Enable Auto-refresh"}
          </button>
          <button
            className="w-full px-4 py-1.5 text-left text-red-400 hover:bg-gray-800"
            onClick={() => handleDelete(contextMenu.crateId)}
          >
            Delete
          </button>
        </div>
      )}
    </aside>
  );
}
