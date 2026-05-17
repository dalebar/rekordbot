import { useCallback, useEffect, useState } from "react";
import {
  connectSetProgress,
  createSet,
  listCrates,
  type CrateSummary,
  type SetCreateResponse,
} from "./api/client";

interface SetCreateDialogProps {
  onClose: () => void;
  onCreated: (setId: number) => void;
}

const ENERGY_ARC_OPTIONS = [
  { value: "", label: "None" },
  { value: "slow build", label: "Slow Build" },
  { value: "peak-valley-peak", label: "Peak-Valley-Peak" },
  { value: "constant high", label: "Constant High" },
  { value: "wind down", label: "Wind Down" },
  { value: "custom", label: "Custom..." },
];

export default function SetCreateDialog({ onClose, onCreated }: SetCreateDialogProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [durationMinutes, setDurationMinutes] = useState<string>("");
  const [targetBpmStart, setTargetBpmStart] = useState<string>("");
  const [targetBpmEnd, setTargetBpmEnd] = useState<string>("");
  const [energyArc, setEnergyArc] = useState("");
  const [customEnergyArc, setCustomEnergyArc] = useState("");
  const [sourceType, setSourceType] = useState<"library" | "crates">("library");
  const [selectedCrateIds, setSelectedCrateIds] = useState<number[]>([]);
  const [harmonicMixing, setHarmonicMixing] = useState(false);
  const [creating, setCreating] = useState(false);
  const [progressMessage, setProgressMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [crates, setCrates] = useState<CrateSummary[]>([]);

  useEffect(() => {
    listCrates()
      .then(setCrates)
      .catch(() => {});
  }, []);

  const handleCreate = useCallback(async () => {
    if (!name.trim() || !description.trim()) return;

    setCreating(true);
    setError(null);
    setProgressMessage("Creating set...");

    try {
      const resolvedArc = energyArc === "custom" ? customEnergyArc : energyArc;
      const response: SetCreateResponse = await createSet({
        name: name.trim(),
        description: description.trim(),
        source_type: sourceType === "crates" ? "crates" : "library",
        source_crate_ids: sourceType === "crates" ? selectedCrateIds : undefined,
        duration_minutes: durationMinutes ? parseInt(durationMinutes) : undefined,
        target_bpm_start: targetBpmStart ? parseFloat(targetBpmStart) : undefined,
        target_bpm_end: targetBpmEnd ? parseFloat(targetBpmEnd) : undefined,
        energy_arc: resolvedArc || undefined,
        harmonic_mixing: harmonicMixing,
      });

      // Connect to progress SSE
      connectSetProgress(
        response.id,
        (eventType, data) => {
          setProgressMessage(data || eventType.replace(/_/g, " "));
        },
        () => {
          setCreating(false);
          onCreated(response.id);
        },
      );
    } catch (err) {
      const msg =
        err && typeof err === "object" && "detail" in err
          ? (err as { detail: string }).detail
          : "Failed to create set";
      setError(msg);
      setCreating(false);
    }
  }, [
    name,
    description,
    durationMinutes,
    targetBpmStart,
    targetBpmEnd,
    energyArc,
    customEnergyArc,
    sourceType,
    selectedCrateIds,
    harmonicMixing,
    onCreated,
  ]);

  const toggleCrate = useCallback((crateId: number) => {
    setSelectedCrateIds((prev) =>
      prev.includes(crateId) ? prev.filter((id) => id !== crateId) : [...prev, crateId],
    );
  }, []);

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/50">
      <div className="w-full max-w-lg bg-gray-900 border border-gray-700 rounded-lg shadow-xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-700">
          <h3 className="text-lg font-semibold">New Set</h3>
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
              className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-sm text-gray-100 focus:outline-none focus:border-blue-500"
              placeholder="Friday Warm-Up"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={creating}
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1">Description</label>
            <textarea
              className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-sm text-gray-100 focus:outline-none focus:border-blue-500 h-24 resize-none"
              placeholder="Deep minimal techno warm-up, gradually building from 120 to 128 BPM. Start atmospheric and hypnotic, build energy through the set..."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              disabled={creating}
            />
          </div>

          {/* Duration */}
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1">
              Duration (minutes)
            </label>
            <input
              type="number"
              className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-sm text-gray-100 focus:outline-none focus:border-blue-500"
              placeholder="60"
              value={durationMinutes}
              onChange={(e) => setDurationMinutes(e.target.value)}
              disabled={creating}
              min={1}
            />
          </div>

          {/* Target BPM range */}
          <div className="flex gap-4">
            <div className="flex-1">
              <label className="block text-sm font-medium text-gray-400 mb-1">BPM Start</label>
              <input
                type="number"
                className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-sm text-gray-100 focus:outline-none focus:border-blue-500"
                placeholder="120"
                value={targetBpmStart}
                onChange={(e) => setTargetBpmStart(e.target.value)}
                disabled={creating}
                min={60}
                max={200}
              />
            </div>
            <div className="flex-1">
              <label className="block text-sm font-medium text-gray-400 mb-1">BPM End</label>
              <input
                type="number"
                className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-sm text-gray-100 focus:outline-none focus:border-blue-500"
                placeholder="128"
                value={targetBpmEnd}
                onChange={(e) => setTargetBpmEnd(e.target.value)}
                disabled={creating}
                min={60}
                max={200}
              />
            </div>
          </div>

          {/* Energy Arc */}
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1">Energy Arc</label>
            <select
              className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-sm text-gray-100 focus:outline-none focus:border-blue-500"
              value={energyArc}
              onChange={(e) => setEnergyArc(e.target.value)}
              disabled={creating}
            >
              {ENERGY_ARC_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
            {energyArc === "custom" && (
              <input
                type="text"
                className="w-full mt-2 px-3 py-2 bg-gray-800 border border-gray-700 rounded text-sm text-gray-100 focus:outline-none focus:border-blue-500"
                placeholder="Describe the energy arc..."
                value={customEnergyArc}
                onChange={(e) => setCustomEnergyArc(e.target.value)}
                disabled={creating}
              />
            )}
          </div>

          {/* Source */}
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1">Source</label>
            <div className="flex gap-4">
              <label className="flex items-center gap-2 text-sm text-gray-400 cursor-pointer">
                <input
                  type="radio"
                  name="sourceType"
                  checked={sourceType === "library"}
                  onChange={() => setSourceType("library")}
                  disabled={creating}
                />
                All Library
              </label>
              <label className="flex items-center gap-2 text-sm text-gray-400 cursor-pointer">
                <input
                  type="radio"
                  name="sourceType"
                  checked={sourceType === "crates"}
                  onChange={() => setSourceType("crates")}
                  disabled={creating}
                />
                From Crates
              </label>
            </div>
            {sourceType === "crates" && (
              <div className="mt-2 max-h-32 overflow-y-auto bg-gray-800 border border-gray-700 rounded p-2 space-y-1">
                {crates.map((crate) => (
                  <label
                    key={crate.id}
                    className="flex items-center gap-2 text-sm text-gray-400 cursor-pointer"
                  >
                    <input
                      type="checkbox"
                      checked={selectedCrateIds.includes(crate.id)}
                      onChange={() => toggleCrate(crate.id)}
                      disabled={creating}
                    />
                    {crate.name} ({crate.track_count})
                  </label>
                ))}
                {crates.length === 0 && (
                  <p className="text-xs text-gray-600">No crates available</p>
                )}
              </div>
            )}
          </div>

          {/* Harmonic mixing */}
          <label className="flex items-center gap-2 text-sm text-gray-400 cursor-pointer">
            <input
              type="checkbox"
              className="rounded bg-gray-800 border-gray-700"
              checked={harmonicMixing}
              onChange={(e) => setHarmonicMixing(e.target.checked)}
              disabled={creating}
            />
            Prefer harmonic mixing (Camelot wheel compatibility)
          </label>

          {/* Progress */}
          {creating && progressMessage && (
            <div className="bg-gray-800 rounded p-3">
              <p className="text-sm text-blue-400">{progressMessage}</p>
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
            Cancel
          </button>
          <button
            className="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-500 text-white rounded disabled:opacity-50"
            onClick={handleCreate}
            disabled={creating || !name.trim() || !description.trim()}
          >
            {creating ? "Planning..." : "Create Set"}
          </button>
        </div>
      </div>
    </div>
  );
}
