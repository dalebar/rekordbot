import { useEffect, useState } from "react";
import { connectProgress, postIngestCancel, type FileProgressEvent } from "./api/client";

interface BatchSummary {
  total: number;
  succeeded: number;
  failed: number;
  duplicates: number;
}

interface ProcessingQueueProps {
  batchId: string;
  totalFiles: number;
  onComplete: () => void;
}

export default function ProcessingQueue({ batchId, totalFiles, onComplete }: ProcessingQueueProps) {
  const [files, setFiles] = useState<Map<string, FileProgressEvent>>(new Map());
  const [summary, setSummary] = useState<BatchSummary | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    const es = connectProgress(
      (event) => {
        setFiles((prev) => new Map(prev).set(event.file_path, event));
      },
      (data) => {
        setSummary(data);
        setCollapsed(true);
        onComplete();
      },
    );

    return () => es.close();
  }, [batchId, onComplete]);

  const handleCancel = async () => {
    setCancelling(true);
    await postIngestCancel();
  };

  const fileList = Array.from(files.values());
  const completedCount = fileList.filter(
    (f) => f.status === "complete" || f.status === "failed" || f.status === "skipped",
  ).length;

  return (
    <div className="flex flex-col gap-4">
      {/* Progress header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-medium text-gray-300">
            Processing {completedCount} / {totalFiles} files
          </h3>
          {summary && (
            <p className="text-xs text-gray-500">
              {summary.succeeded} succeeded, {summary.failed} failed, {summary.duplicates}{" "}
              duplicates
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          {summary && (
            <button
              onClick={() => setCollapsed((c) => !c)}
              className="text-xs text-gray-500 hover:text-gray-300"
            >
              {collapsed ? "Show" : "Hide"}
            </button>
          )}
          {!summary && (
            <button
              onClick={handleCancel}
              disabled={cancelling}
              className="rounded bg-red-900/50 px-3 py-1 text-xs text-red-300 transition-colors hover:bg-red-900/80 disabled:opacity-50"
            >
              {cancelling ? "Cancelling..." : "Cancel"}
            </button>
          )}
        </div>
      </div>

      {!collapsed && (
        <>
          {/* Progress bar */}
          <div className="h-1.5 overflow-hidden rounded-full bg-gray-800">
            <div
              className="h-full rounded-full bg-emerald-500 transition-all"
              style={{
                width: `${totalFiles > 0 ? (completedCount / totalFiles) * 100 : 0}%`,
              }}
            />
          </div>

          {/* File list */}
          <div className="max-h-48 overflow-y-auto">
            {fileList.map((file) => (
              <div
                key={file.file_path}
                className="flex items-center justify-between border-b border-gray-800/50 py-1.5 text-xs"
              >
                <span className="truncate text-gray-400" title={file.file_path}>
                  {file.file_path.split("/").pop()}
                </span>
                <StatusBadge status={file.status} />
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    queued: "text-gray-500",
    processing: "text-blue-400",
    complete: "text-emerald-400",
    failed: "text-red-400",
    skipped: "text-yellow-400",
  };

  return <span className={`ml-2 shrink-0 ${styles[status] ?? "text-gray-500"}`}>{status}</span>;
}
