import { useCallback, useEffect, useState } from "react";
import { getHealth, type HealthResponse, type IngestResponse } from "./api/client";
import CrateCreateDialog from "./CrateCreateDialog";
import CrateSidebar from "./CrateSidebar";
import DropZone from "./DropZone";
import ProcessingQueue from "./ProcessingQueue";
import SetCreateDialog from "./SetCreateDialog";
import SetPlannerView from "./SetPlannerView";
import TrackTable from "./TrackTable";

function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [batch, setBatch] = useState<IngestResponse | null>(null);
  const [refreshTrigger, setRefreshTrigger] = useState(0);
  const [selectedCrateId, setSelectedCrateId] = useState<number | null>(null);
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [crateRefreshTrigger, setCrateRefreshTrigger] = useState(0);
  const [activeSetId, setActiveSetId] = useState<number | null>(null);
  const [showSetCreateDialog, setShowSetCreateDialog] = useState(false);
  const [setsRefreshTrigger, setSetsRefreshTrigger] = useState(0);

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

  const handleSetCreated = useCallback((setId: number) => {
    setSetsRefreshTrigger((prev) => prev + 1);
    setActiveSetId(setId);
    setShowSetCreateDialog(false);
  }, []);

  const handleSetSelect = useCallback((setId: number) => {
    setActiveSetId(setId);
    setSelectedCrateId(null);
  }, []);

  const handleBackToLibrary = useCallback(() => {
    setActiveSetId(null);
  }, []);

  return (
    <div className="flex h-screen bg-gray-950 text-gray-100">
      {/* Crate sidebar */}
      <CrateSidebar
        onCrateSelect={setSelectedCrateId}
        selectedCrateId={selectedCrateId}
        onNewCrate={() => setShowCreateDialog(true)}
        refreshTrigger={crateRefreshTrigger}
        onSetSelect={handleSetSelect}
        onNewSet={() => setShowSetCreateDialog(true)}
        setRefreshTrigger={setsRefreshTrigger}
      />

      {/* Main content */}
      <div className="flex flex-1 flex-col">
        {/* Header */}
        <header className="flex items-center justify-between border-b border-gray-800 px-6 py-3">
          <h1 className="text-sm font-medium text-gray-400">
            {activeSetId ? "Set Planner" : selectedCrateId ? "Crate" : "Library"}
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
        {activeSetId ? (
          <SetPlannerView setId={activeSetId} onBack={handleBackToLibrary} />
        ) : (
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
        )}
      </div>

      {/* Create crate dialog */}
      {showCreateDialog && (
        <CrateCreateDialog
          onClose={() => setShowCreateDialog(false)}
          onCreated={handleCrateCreated}
        />
      )}

      {/* Create set dialog */}
      {showSetCreateDialog && (
        <SetCreateDialog
          onClose={() => setShowSetCreateDialog(false)}
          onCreated={handleSetCreated}
        />
      )}
    </div>
  );
}

export default App;
