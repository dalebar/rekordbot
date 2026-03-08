import { useCallback, useState, type DragEvent } from "react";
import { postIngest, type IngestResponse } from "./api/client";

interface DropZoneProps {
  onBatchStarted: (response: IngestResponse) => void;
}

export default function DropZone({ onBatchStarted }: DropZoneProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const startIngest = useCallback(
    async (paths: string[]) => {
      setError(null);
      try {
        const response = await postIngest({ paths });
        if (response.total_files === 0) {
          setError(response.message);
        } else {
          onBatchStarted(response);
        }
      } catch (err) {
        setError(String(err));
      }
    },
    [onBatchStarted],
  );

  const handleDrop = useCallback(
    async (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setIsDragging(false);

      const items = e.dataTransfer.items;
      const paths: string[] = [];

      for (let i = 0; i < items.length; i++) {
        const item = items[i];
        if (item.kind === "file") {
          const file = item.getAsFile();
          if (file) {
            // In Tauri, file.path contains the real path
            paths.push((file as File & { path?: string }).path ?? file.name);
          }
        }
      }

      if (paths.length === 0) {
        setError("No files detected. Try using the folder selector button.");
        return;
      }

      await startIngest(paths);
    },
    [startIngest],
  );

  const handleDragOver = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setIsDragging(false);
  }, []);

  const handleFolderSelect = useCallback(async () => {
    setError(null);
    try {
      // Tauri v2 dialog plugin — dynamically imported so the app works in browser too
      const { open } = await import("@tauri-apps/plugin-dialog");
      const result = await open({
        directory: true,
        multiple: true,
        title: "Select music folders",
      });
      if (!result) return;
      const paths = Array.isArray(result) ? result : [result];
      await startIngest(paths);
    } catch {
      setError("Folder dialog requires the Tauri desktop app. Use drag-and-drop in the browser.");
    }
  }, [startIngest]);

  return (
    <div className="flex flex-col gap-4">
      <div
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        className={`flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-12 transition-colors ${
          isDragging
            ? "border-emerald-400 bg-emerald-400/10"
            : "border-gray-700 hover:border-gray-600"
        }`}
      >
        <p className="text-lg text-gray-400">
          {isDragging ? "Drop files here" : "Drag audio files or folders here"}
        </p>
        <p className="mt-2 text-sm text-gray-600">WAV, FLAC, AIFF, MP3, M4A</p>
      </div>

      <button
        onClick={handleFolderSelect}
        className="rounded-lg bg-gray-800 px-4 py-2 text-sm text-gray-300 transition-colors hover:bg-gray-700"
      >
        Select Folder...
      </button>

      {error && <p className="text-sm text-red-400">{error}</p>}
    </div>
  );
}
