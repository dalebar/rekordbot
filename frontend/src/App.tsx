import { useEffect, useState } from "react";
import { getHealth, type HealthResponse } from "./api/client";

function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch(() => setError("Backend unavailable"));
  }, []);

  return (
    <div className="flex h-screen bg-gray-950 text-gray-100">
      {/* Sidebar placeholder */}
      <aside className="w-60 border-r border-gray-800 p-4">
        <h2 className="text-lg font-semibold tracking-tight">rekordbot</h2>
        <p className="mt-2 text-sm text-gray-500">Sidebar placeholder</p>
      </aside>

      {/* Main content */}
      <div className="flex flex-1 flex-col">
        {/* Header */}
        <header className="flex items-center justify-between border-b border-gray-800 px-6 py-3">
          <h1 className="text-sm font-medium text-gray-400">Dashboard</h1>
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
        <main className="flex flex-1 items-center justify-center">
          <p className="text-gray-600">Ready for Phase 1</p>
        </main>
      </div>
    </div>
  );
}

export default App;
