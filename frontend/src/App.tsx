import { useCallback, useEffect, useState } from "react";
import {
  getHealth,
  getSettingsStatus,
  setApiErrorHandler,
  clearApiErrorHandler,
  type HealthResponse,
  type IngestResponse,
} from "./api/client";
import { useToast } from "./ToastProvider";
import ConflictReviewPanel from "./ConflictReviewPanel";
import DropZone from "./DropZone";
import ImportControls from "./ImportControls";
import ProcessingQueue from "./ProcessingQueue";
import SettingsPanel from "./SettingsPanel";
import SetupWizard from "./SetupWizard";
import TrackTable from "./TrackTable";

function App() {
  const { addToast } = useToast();
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showWizard, setShowWizard] = useState<boolean | null>(null);

  // Register global API error handler for toast notifications
  useEffect(() => {
    setApiErrorHandler((err) => {
      addToast("error", err.detail || err.error || "An unexpected error occurred");
    });
    return () => clearApiErrorHandler();
  }, [addToast]);

  const [batch, setBatch] = useState<IngestResponse | null>(null);
  const [refreshTrigger, setRefreshTrigger] = useState(0);
  const [showSettings, setShowSettings] = useState(false);
  const [showConflicts, setShowConflicts] = useState(false);
  const [conflictCount, setConflictCount] = useState(0);

  // Poll for backend readiness. In dev mode the backend is already running
  // so the first attempt succeeds. In production the sidecar takes ~2s to
  // start, so we retry every 500ms for up to 20 attempts (10s).
  useEffect(() => {
    let cancelled = false;

    const pollBackend = async () => {
      const maxAttempts = 20;
      for (let i = 0; i < maxAttempts; i++) {
        if (cancelled) return;
        try {
          const h = await getHealth();
          if (cancelled) return;
          setHealth(h);
          setError(null);
          // Backend is up — check first-run status
          try {
            const status = await getSettingsStatus();
            if (!cancelled) setShowWizard(!status.configured);
          } catch {
            if (!cancelled) setShowWizard(false);
          }
          return;
        } catch {
          // Backend not ready yet — wait and retry
          await new Promise((r) => setTimeout(r, 500));
        }
      }
      // All attempts exhausted
      if (!cancelled) {
        setError("Backend unavailable");
        setShowWizard(false);
      }
    };

    pollBackend();

    return () => {
      cancelled = true;
    };
  }, []);

  const handleBatchStarted = useCallback((response: IngestResponse) => {
    setBatch(response);
  }, []);

  const handleBatchComplete = useCallback(() => {
    setRefreshTrigger((prev) => prev + 1);
  }, []);

  // Show wizard on first run
  if (showWizard === true) {
    return <SetupWizard onComplete={() => setShowWizard(false)} />;
  }

  // Still loading status check
  if (showWizard === null) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-950 text-gray-500">
        Loading...
      </div>
    );
  }

  return (
    <div className="flex h-screen flex-col bg-gray-950 text-gray-100">
      {/* Header */}
      <header className="flex items-center justify-between border-b border-gray-800 px-6 py-3">
        <h1 className="text-sm font-medium text-gray-400">Library</h1>
        <div className="flex items-center gap-4 text-sm">
          {health ? (
            <span className="text-emerald-400">
              Connected to rekordbot backend v{health.version}
            </span>
          ) : error ? (
            <span className="text-red-400">{error}</span>
          ) : (
            <span className="text-gray-500">Connecting...</span>
          )}
          <button
            onClick={() => setShowSettings(true)}
            className="rounded border border-gray-700 px-2 py-1 text-xs text-gray-400 hover:text-gray-200"
          >
            Settings
          </button>
        </div>
      </header>

      {/* Content area */}
      <div className="relative flex flex-1 flex-col overflow-hidden">
        {showConflicts ? (
          <ConflictReviewPanel
            onClose={() => setShowConflicts(false)}
            onRefresh={() => setRefreshTrigger((prev) => prev + 1)}
          />
        ) : (
          <main className="flex flex-1 flex-col overflow-hidden p-6">
            {/* Drop zone and import controls */}
            <div className="mb-4 flex shrink-0 items-start gap-4">
              <DropZone onBatchStarted={handleBatchStarted} />
              <ImportControls
                onRefresh={() => setRefreshTrigger((prev) => prev + 1)}
                onConflicts={(count) => {
                  setConflictCount(count);
                  setShowConflicts(true);
                }}
              />
              {conflictCount > 0 && !showConflicts && (
                <button
                  onClick={() => setShowConflicts(true)}
                  className="rounded bg-amber-700 px-3 py-1.5 text-xs text-white hover:bg-amber-600"
                >
                  Review Conflicts ({conflictCount})
                </button>
              )}
            </div>

            {/* Processing queue (shown when a batch is active) */}
            {batch && batch.total_files > 0 && (
              <div className="mb-4 shrink-0">
                <ProcessingQueue
                  batchId={batch.batch_id}
                  totalFiles={batch.total_files}
                  onComplete={handleBatchComplete}
                  onDismiss={() => setBatch(null)}
                />
              </div>
            )}

            {/* Track table */}
            <div className="flex min-h-0 flex-1 flex-col">
              <TrackTable refreshTrigger={refreshTrigger} crateId={null} />
            </div>
          </main>
        )}
        {showSettings && <SettingsPanel onClose={() => setShowSettings(false)} />}
      </div>
    </div>
  );
}

export default App;
