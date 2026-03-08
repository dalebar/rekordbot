import { useCallback, useEffect, useState } from "react";
import {
  getSettings,
  updateSettings,
  validateApiKey,
  validateDirectory,
  type SettingsResponse,
} from "./api/client";
import { useToast } from "./ToastProvider";

interface SettingsPanelProps {
  onClose: () => void;
}

export default function SettingsPanel({ onClose }: SettingsPanelProps) {
  const { addToast } = useToast();
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Form state
  const [apiKey, setApiKey] = useState("");
  const [outputDir, setOutputDir] = useState("");
  const [keyNotation, setKeyNotation] = useState("camelot");
  const [folderTemplate, setFolderTemplate] = useState("{artist}/{album}/{title}");
  const [convertAac, setConvertAac] = useState(false);
  const [bpmMin, setBpmMin] = useState(70);
  const [bpmMax, setBpmMax] = useState(180);
  const [confidence, setConfidence] = useState(0.6);
  const [trackDuration, setTrackDuration] = useState(7);
  const [maxTracks, setMaxTracks] = useState(50);

  // Validation state
  const [keyValid, setKeyValid] = useState<boolean | null>(null);
  const [keyTesting, setKeyTesting] = useState(false);
  const [dirValid, setDirValid] = useState<boolean | null>(null);
  const [dirError, setDirError] = useState("");

  useEffect(() => {
    getSettings()
      .then((s) => {
        setSettings(s);
        setApiKey(s.anthropic_api_key);
        setOutputDir(s.output_directory);
        setKeyNotation(s.default_key_notation);
        setFolderTemplate(s.folder_template);
        setConvertAac(s.convert_aac_to_mp3);
        setBpmMin(s.bpm_range_min);
        setBpmMax(s.bpm_range_max);
        setConfidence(s.confidence_threshold);
        setTrackDuration(s.set_track_duration_minutes);
        setMaxTracks(s.set_max_tracks);
        setLoading(false);
      })
      .catch(() => {
        setLoading(false);
      });
  }, []);

  const handleTestKey = useCallback(async () => {
    setKeyTesting(true);
    try {
      const result = await validateApiKey(apiKey);
      setKeyValid(result.valid);
      if (!result.valid) {
        addToast("warning", result.error || "Invalid API key");
      }
    } catch {
      setKeyValid(false);
    }
    setKeyTesting(false);
  }, [apiKey, addToast]);

  const handleBrowseDir = useCallback(async () => {
    try {
      // Use Tauri dialog if available, otherwise prompt
      const { open } = await import("@tauri-apps/plugin-dialog");
      const selected = await open({ directory: true, multiple: false });
      if (selected) {
        setOutputDir(selected as string);
        setDirValid(null);
      }
    } catch {
      // Tauri not available (dev mode) — user types manually
    }
  }, []);

  const handleValidateDir = useCallback(async () => {
    if (!outputDir) {
      setDirValid(false);
      setDirError("Output directory is required");
      return;
    }
    try {
      const result = await validateDirectory(outputDir);
      setDirValid(result.valid);
      setDirError(result.error);
    } catch {
      setDirValid(false);
      setDirError("Validation failed");
    }
  }, [outputDir]);

  // Validate directory on blur
  useEffect(() => {
    if (outputDir && outputDir !== settings?.output_directory) {
      const timer = setTimeout(handleValidateDir, 500);
      return () => clearTimeout(timer);
    }
  }, [outputDir, settings?.output_directory, handleValidateDir]);

  const handleSave = useCallback(async () => {
    if (bpmMin >= bpmMax) {
      addToast("error", "BPM range min must be less than max");
      return;
    }

    setSaving(true);
    try {
      await updateSettings({
        anthropic_api_key: apiKey,
        output_directory: outputDir,
        default_key_notation: keyNotation,
        folder_template: folderTemplate,
        convert_aac_to_mp3: convertAac,
        bpm_range_min: bpmMin,
        bpm_range_max: bpmMax,
        confidence_threshold: confidence,
        set_track_duration_minutes: trackDuration,
        set_max_tracks: maxTracks,
      });
      addToast("success", "Settings saved");
    } catch {
      // Error toast handled by global handler
    }
    setSaving(false);
  }, [
    apiKey,
    outputDir,
    keyNotation,
    folderTemplate,
    convertAac,
    bpmMin,
    bpmMax,
    confidence,
    trackDuration,
    maxTracks,
    addToast,
  ]);

  // Folder template preview
  const templatePreview = folderTemplate
    .replace("{artist}", "Calibre")
    .replace("{album}", "Shelflife 6")
    .replace("{title}", "Falls to You")
    .replace("{genre}", "Drum & Bass")
    .replace("{year}", "2020")
    .replace("{label}", "Signature");

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-500">
        Loading settings...
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="max-w-2xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-lg font-semibold">Settings</h2>
          <button
            className="text-sm text-gray-400 hover:text-gray-200"
            onClick={onClose}
          >
            Close
          </button>
        </div>

        {/* Main settings */}
        <div className="space-y-5">
          {/* API Key */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">
              Anthropic API Key
            </label>
            <div className="flex gap-2">
              <input
                type="password"
                value={apiKey}
                onChange={(e) => {
                  setApiKey(e.target.value);
                  setKeyValid(null);
                }}
                className="flex-1 bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200"
                placeholder="sk-ant-..."
              />
              <button
                className="px-3 py-2 text-sm bg-gray-800 border border-gray-700 rounded hover:bg-gray-700 disabled:opacity-50"
                onClick={handleTestKey}
                disabled={keyTesting || !apiKey}
              >
                {keyTesting ? "Testing..." : "Test"}
              </button>
              {keyValid === true && <span className="self-center text-emerald-400">✓</span>}
              {keyValid === false && <span className="self-center text-red-400">✗</span>}
            </div>
            <p className="text-xs text-gray-500 mt-1">
              Required for AI tagging, crate building, and set planning
            </p>
          </div>

          {/* Output Directory */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">
              Output Directory
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                value={outputDir}
                onChange={(e) => {
                  setOutputDir(e.target.value);
                  setDirValid(null);
                  setDirError("");
                }}
                className="flex-1 bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200"
                placeholder="/Users/you/Music/rekordbot"
              />
              <button
                className="px-3 py-2 text-sm bg-gray-800 border border-gray-700 rounded hover:bg-gray-700"
                onClick={handleBrowseDir}
              >
                Browse
              </button>
              {dirValid === true && <span className="self-center text-emerald-400">✓</span>}
              {dirValid === false && <span className="self-center text-red-400">✗</span>}
            </div>
            {dirError && <p className="text-xs text-red-400 mt-1">{dirError}</p>}
          </div>

          {/* Key Notation */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">
              Key Notation
            </label>
            <select
              value={keyNotation}
              onChange={(e) => setKeyNotation(e.target.value)}
              className="bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200"
            >
              <option value="camelot">Camelot (8A, 11B)</option>
              <option value="open_key">Open Key (1m, 4d)</option>
              <option value="classical">Classical (Am, C)</option>
            </select>
          </div>

          {/* Folder Template */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">
              Folder Template
            </label>
            <input
              type="text"
              value={folderTemplate}
              onChange={(e) => setFolderTemplate(e.target.value)}
              className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200"
              placeholder="{artist}/{album}/{title}"
            />
            <p className="text-xs text-gray-500 mt-1">
              Preview: {templatePreview}
            </p>
          </div>

          {/* Convert AAC to MP3 */}
          <div className="flex items-center gap-3">
            <input
              type="checkbox"
              id="convert-aac"
              checked={convertAac}
              onChange={(e) => setConvertAac(e.target.checked)}
              className="rounded border-gray-700"
            />
            <label htmlFor="convert-aac" className="text-sm text-gray-300">
              Convert AAC to MP3
            </label>
            <span className="text-xs text-gray-500">
              (lossy-to-lossy transcoding — only if you need MP3 specifically)
            </span>
          </div>
        </div>

        {/* Advanced section */}
        <div className="mt-8">
          <button
            className="text-sm text-gray-400 hover:text-gray-200"
            onClick={() => setShowAdvanced(!showAdvanced)}
          >
            {showAdvanced ? "▼" : "▶"} Advanced Settings
          </button>

          {showAdvanced && (
            <div className="mt-4 space-y-4 pl-4 border-l border-gray-800">
              {/* BPM Range */}
              <div className="flex gap-4">
                <div>
                  <label className="block text-xs text-gray-400 mb-1">BPM Min</label>
                  <input
                    type="number"
                    value={bpmMin}
                    onChange={(e) => setBpmMin(Number(e.target.value))}
                    className="w-24 bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-200"
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-400 mb-1">BPM Max</label>
                  <input
                    type="number"
                    value={bpmMax}
                    onChange={(e) => setBpmMax(Number(e.target.value))}
                    className="w-24 bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-200"
                  />
                </div>
              </div>

              {/* Confidence Threshold */}
              <div>
                <label className="block text-xs text-gray-400 mb-1">
                  Confidence Threshold (0.0–1.0)
                </label>
                <input
                  type="number"
                  step="0.1"
                  min="0"
                  max="1"
                  value={confidence}
                  onChange={(e) => setConfidence(Number(e.target.value))}
                  className="w-24 bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-200"
                />
              </div>

              {/* Track Duration */}
              <div>
                <label className="block text-xs text-gray-400 mb-1">
                  Set Track Duration (minutes)
                </label>
                <input
                  type="number"
                  min="1"
                  value={trackDuration}
                  onChange={(e) => setTrackDuration(Number(e.target.value))}
                  className="w-24 bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-200"
                />
              </div>

              {/* Max Tracks Per Set */}
              <div>
                <label className="block text-xs text-gray-400 mb-1">
                  Max Tracks Per Set
                </label>
                <input
                  type="number"
                  min="1"
                  value={maxTracks}
                  onChange={(e) => setMaxTracks(Number(e.target.value))}
                  className="w-24 bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-200"
                />
              </div>
            </div>
          )}
        </div>

        {/* Save button */}
        <div className="mt-8 flex gap-3">
          <button
            className="px-4 py-2 text-sm bg-purple-600 hover:bg-purple-500 rounded font-medium disabled:opacity-50"
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? "Saving..." : "Save Settings"}
          </button>
          <button
            className="px-4 py-2 text-sm text-gray-400 hover:text-gray-200"
            onClick={onClose}
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
