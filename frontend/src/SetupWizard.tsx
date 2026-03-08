import { useCallback, useState } from "react";
import {
  updateSettings,
  validateApiKey,
  validateDirectory,
} from "./api/client";
import { useToast } from "./ToastProvider";

interface SetupWizardProps {
  onComplete: () => void;
}

type Step = "welcome" | "config" | "done";

export default function SetupWizard({ onComplete }: SetupWizardProps) {
  const { addToast } = useToast();
  const [step, setStep] = useState<Step>("welcome");

  // Config form state
  const [outputDir, setOutputDir] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [dirValid, setDirValid] = useState<boolean | null>(null);
  const [dirError, setDirError] = useState("");
  const [keyValid, setKeyValid] = useState<boolean | null>(null);
  const [keyTesting, setKeyTesting] = useState(false);
  const [saving, setSaving] = useState(false);

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

  const handleTestKey = useCallback(async () => {
    if (!apiKey) return;
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
      const { open } = await import("@tauri-apps/plugin-dialog");
      const selected = await open({ directory: true, multiple: false });
      if (selected) {
        setOutputDir(selected as string);
        setDirValid(null);
        setDirError("");
      }
    } catch {
      // Tauri not available
    }
  }, []);

  const handleContinue = useCallback(async () => {
    // Validate directory first
    if (!outputDir) {
      setDirError("Output directory is required");
      setDirValid(false);
      return;
    }

    const dirResult = await validateDirectory(outputDir);
    if (!dirResult.valid) {
      setDirError(dirResult.error);
      setDirValid(false);
      return;
    }

    setSaving(true);
    try {
      const settingsUpdate: Record<string, string | boolean> = {
        output_directory: outputDir,
      };
      if (apiKey) {
        settingsUpdate.anthropic_api_key = apiKey;
      }
      await updateSettings(settingsUpdate);
      setStep("done");
    } catch {
      addToast("error", "Failed to save settings");
    }
    setSaving(false);
  }, [outputDir, apiKey, addToast]);

  if (step === "welcome") {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-950 text-gray-100">
        <div className="text-center max-w-md">
          <h1 className="text-3xl font-bold mb-2">rekordbot</h1>
          <p className="text-gray-400 mb-8">
            Organise your DJ library with AI-powered tagging and crate building
          </p>
          <button
            className="px-6 py-2.5 bg-purple-600 hover:bg-purple-500 rounded font-medium"
            onClick={() => setStep("config")}
          >
            Get Started
          </button>
        </div>
      </div>
    );
  }

  if (step === "done") {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-950 text-gray-100">
        <div className="text-center max-w-md">
          <h1 className="text-2xl font-bold mb-2">You&apos;re ready to go</h1>
          <p className="text-gray-400 mb-8">
            Drop some files in to get started.
          </p>
          <div className="flex gap-3 justify-center">
            <button
              className="px-6 py-2.5 bg-purple-600 hover:bg-purple-500 rounded font-medium"
              onClick={onComplete}
            >
              Start
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Config step
  return (
    <div className="flex h-screen items-center justify-center bg-gray-950 text-gray-100">
      <div className="w-full max-w-lg p-8">
        <h2 className="text-xl font-semibold mb-6">Essential Configuration</h2>

        {/* Output Directory */}
        <div className="mb-6">
          <label className="block text-sm font-medium text-gray-300 mb-1">
            Output Directory <span className="text-red-400">*</span>
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
              onBlur={handleValidateDir}
              className="flex-1 bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200"
              placeholder="/Users/you/Music/rekordbot"
            />
            <button
              className="px-3 py-2 text-sm bg-gray-800 border border-gray-700 rounded hover:bg-gray-700"
              onClick={handleBrowseDir}
            >
              Browse
            </button>
          </div>
          {dirValid === true && (
            <p className="text-xs text-emerald-400 mt-1">Directory is valid</p>
          )}
          {dirError && <p className="text-xs text-red-400 mt-1">{dirError}</p>}
          <p className="text-xs text-gray-500 mt-1">
            Where rekordbot will store your converted and organised files
          </p>
        </div>

        {/* API Key */}
        <div className="mb-8">
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
            Required for AI tagging, crate building, and set planning. You can add this later in Settings.
          </p>
        </div>

        {/* Continue button */}
        <button
          className="w-full px-4 py-2.5 bg-purple-600 hover:bg-purple-500 rounded font-medium disabled:opacity-50"
          onClick={handleContinue}
          disabled={saving || !outputDir}
        >
          {saving ? "Saving..." : "Continue"}
        </button>
      </div>
    </div>
  );
}
