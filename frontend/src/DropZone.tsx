import { useCallback, useEffect, useState, type DragEvent } from "react";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import type { UnlistenFn } from "@tauri-apps/api/event";
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

  // Tauri v2 delivers real filesystem paths via the webview's drag-drop event,
  // not via the browser DragEvent. In v1, `file.path` on the DataTransfer item
  // contained the absolute path; in v2 it is undefined. The Tauri native shell
  // also intercepts OS-level file drags before they reach the browser's DOM
  // event loop, so browser-level dragover/dragleave handlers do not fire for
  // file drags and cannot drive the visual highlight either. Both path
  // delivery AND visual feedback go through this single subscription.
  //
  // The 'enter'/'leave' events fire at the webview boundary (window-scoped,
  // not drop-zone-scoped), so the dashed border highlights whenever the user
  // hovers files anywhere over the window. 'over' fires continuously while
  // hovering and is ignored to avoid render churn.
  //
  // In plain-browser dev mode (`npm run dev` at http://localhost:1420),
  // getCurrentWebview() will throw because the Tauri IPC bridge isn't
  // available. We swallow that silently — the drop zone is non-functional in
  // a plain browser regardless, and the existing "Select Folder…" button's
  // fallback message already covers that case for the user.
  useEffect(() => {
    let unlisten: UnlistenFn | undefined;
    let cancelled = false;

    (async () => {
      try {
        const fn = await getCurrentWebview().onDragDropEvent((event) => {
          if (event.payload.type === "enter") {
            setIsDragging(true);
          } else if (event.payload.type === "leave") {
            setIsDragging(false);
          } else if (event.payload.type === "drop") {
            setIsDragging(false);
            void startIngest(event.payload.paths);
          }
          // 'over' fires continuously while hovering; ignored.
        });
        if (cancelled) {
          fn();
        } else {
          unlisten = fn;
        }
      } catch {
        // Not running inside Tauri — drag-and-drop is unavailable.
      }
    })();

    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, [startIngest]);

  // handleDrop's e.preventDefault() guards against the edge case where a file
  // drag escapes the Tauri interception (extremely rare, but the default
  // browser behaviour would be to navigate to the dropped file). Path delivery
  // and visual feedback are handled by the Tauri webview listener above.
  const handleDrop = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
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
    <div className="flex items-center gap-3">
      <div
        onDrop={handleDrop}
        className={`flex items-center gap-2 rounded-lg border-2 border-dashed px-6 py-4 transition-colors ${
          isDragging
            ? "border-emerald-400 bg-emerald-400/10"
            : "border-gray-700 hover:border-gray-600"
        }`}
      >
        <p className="text-sm text-gray-400">
          {isDragging ? "Drop files here" : "Drag audio files or folders here"}
        </p>
        <p className="text-xs text-gray-600">WAV, FLAC, AIFF, MP3, M4A</p>
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
