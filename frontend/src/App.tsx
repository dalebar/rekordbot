import { useCallback, useEffect, useState } from "react";
import { getHealth, type HealthResponse, type IngestResponse } from "./api/client";
import DropZone from "./DropZone";
import ProcessingQueue from "./ProcessingQueue";
import TrackList from "./TrackList";

function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [batch, setBatch] = useState<IngestResponse | null>(null);
  const [refreshTrigger, setRefreshTrigger] = useState(0);

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch(() => setError("Backend unavailable"));
  }, []);

  const handleBatchStarted = useCallback((response: IngestResponse) => {
    setBatch(response);
  }, []);

  const handleBatchComplete = useCallback(() => {
    setRefreshTrigger((prev) => prev + 1);
  }, []);

  return (
    <div className="flex h-screen bg-gray-950 text-gray-100">
      {/* Sidebar placeholder */}
      <aside className="w-60 border-r border-gray-800 p-4">
        <h2 className="text-lg font-semibold tracking-tight">rekordbot</h2>
        <p className="mt-2 text-sm text-gray-500">Phase 1</p>
      </aside>

      {/* Main content */}
      <div className="flex flex-1 flex-col">
        {/* Header */}
        <header className="flex items-center justify-between border-b border-gray-800 px-6 py-3">
          <h1 className="text-sm font-medium text-gray-400">File Ingestion</h1>
          <div className="text-sm">
            {health ? (
              <span className="text-emerald-400">
                Connected to rekordbot backend v{health.version}
              </span>
            ) : error ? (
              <span className="text-red-400">{error}</span>
            ) : (
              <span className="text-gray-500">Connecting...</span>
            )}
          </div>
        </header>

        {/* Content area */}
        <main className="flex-1 overflow-y-auto p-6">
          <div className="mx-auto flex max-w-3xl flex-col gap-8">
            {/* Drop zone */}
            <DropZone onBatchStarted={handleBatchStarted} />

            {/* Processing queue (shown when a batch is active) */}
            {batch && batch.total_files > 0 && (
              <ProcessingQueue
                batchId={batch.batch_id}
                totalFiles={batch.total_files}
                onComplete={handleBatchComplete}
              />
            )}

            {/* Track list */}
            <TrackList refreshTrigger={refreshTrigger} />
          </div>
        </main>
      </div>
    </div>
  );
}

export default App;
