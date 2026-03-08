import { useCallback, useEffect, useState } from "react";
import { getHealth, type HealthResponse, type IngestResponse } from "./api/client";
import CrateCreateDialog from "./CrateCreateDialog";
import CrateSidebar from "./CrateSidebar";
import DropZone from "./DropZone";
import ProcessingQueue from "./ProcessingQueue";
import TrackTable from "./TrackTable";

function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [batch, setBatch] = useState<IngestResponse | null>(null);
  const [refreshTrigger, setRefreshTrigger] = useState(0);
  const [selectedCrateId, setSelectedCrateId] = useState<number | null>(null);
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [crateRefreshTrigger, setCrateRefreshTrigger] = useState(0);

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

  const handleCrateCreated = useCallback(() => {
    setCrateRefreshTrigger((prev) => prev + 1);
  }, []);

  return (
    <div className="flex h-screen bg-gray-950 text-gray-100">
      {/* Crate sidebar */}
      <CrateSidebar
        onCrateSelect={setSelectedCrateId}
        selectedCrateId={selectedCrateId}
        onNewCrate={() => setShowCreateDialog(true)}
        refreshTrigger={crateRefreshTrigger}
      />

      {/* Main content */}
      <div className="flex flex-1 flex-col">
        {/* Header */}
        <header className="flex items-center justify-between border-b border-gray-800 px-6 py-3">
          <h1 className="text-sm font-medium text-gray-400">
            {selectedCrateId ? "Crate" : "Library"}
          </h1>
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
        <main className="flex flex-1 flex-col overflow-hidden p-6">
          {/* Drop zone (collapsible) */}
          <div className="mb-4">
            <DropZone onBatchStarted={handleBatchStarted} />
          </div>

          {/* Processing queue (shown when a batch is active) */}
          {batch && batch.total_files > 0 && (
            <div className="mb-4">
              <ProcessingQueue
                batchId={batch.batch_id}
                totalFiles={batch.total_files}
                onComplete={handleBatchComplete}
              />
            </div>
          )}

          {/* Track table */}
          <TrackTable
            refreshTrigger={refreshTrigger}
            crateId={selectedCrateId}
          />
        </main>
      </div>

      {/* Create crate dialog */}
      {showCreateDialog && (
        <CrateCreateDialog
          onClose={() => setShowCreateDialog(false)}
          onCreated={handleCrateCreated}
        />
      )}
    </div>
  );
}

export default App;
