import { useCallback, useEffect, useState } from "react";
import { deleteSet, listSets, type SetSummary } from "./api/client";

interface SetListPanelProps {
  onSetSelect: (setId: number) => void;
  onNewSet: () => void;
  refreshTrigger: number;
}

export default function SetListPanel({ onSetSelect, onNewSet, refreshTrigger }: SetListPanelProps) {
  const [sets, setSets] = useState<SetSummary[]>([]);

  const loadSets = useCallback(() => {
    listSets()
      .then(setSets)
      .catch(() => {});
  }, []);

  useEffect(() => {
    loadSets();
  }, [loadSets, refreshTrigger]);

  const handleDelete = useCallback(
    async (e: React.MouseEvent, setId: number) => {
      e.stopPropagation();
      await deleteSet(setId);
      loadSets();
    },
    [loadSets],
  );

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
        <h2 className="text-sm font-semibold text-gray-300">Sets</h2>
        <button
          className="px-3 py-1 text-xs bg-blue-600 hover:bg-blue-500 text-white rounded"
          onClick={onNewSet}
        >
          + New Set
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {sets.map((set) => (
          <button
            key={set.id}
            className="w-full px-4 py-3 text-left border-b border-gray-800/50 hover:bg-gray-800/50 transition-colors"
            onClick={() => onSetSelect(set.id)}
          >
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-gray-200 truncate">{set.name}</span>
              <div className="flex items-center gap-2">
                <span
                  className={`text-xs px-1.5 py-0.5 rounded ${
                    set.status === "complete"
                      ? "bg-emerald-900/50 text-emerald-400"
                      : set.status === "planning"
                        ? "bg-blue-900/50 text-blue-400"
                        : "bg-gray-800 text-gray-500"
                  }`}
                >
                  {set.status}
                </span>
                <button
                  className="text-gray-600 hover:text-red-400 text-xs"
                  onClick={(e) => handleDelete(e, set.id)}
                  title="Delete set"
                >
                  &times;
                </button>
              </div>
            </div>
            <p className="text-xs text-gray-500 truncate mt-0.5">{set.description}</p>
            <div className="flex gap-3 mt-1 text-xs text-gray-600">
              <span>{set.track_count} tracks</span>
              <span>{set.candidate_count} candidates</span>
            </div>
          </button>
        ))}

        {sets.length === 0 && (
          <div className="px-4 py-8 text-center">
            <p className="text-sm text-gray-600">No sets yet</p>
            <p className="text-xs text-gray-700 mt-1">
              Create a set to plan your DJ performance
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
