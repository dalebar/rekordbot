import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

/** Toast notification types. */
export type ToastType = "success" | "error" | "warning" | "info";

/** A single toast notification. */
export interface Toast {
  id: number;
  type: ToastType;
  message: string;
}

/** Toast context value. */
interface ToastContextValue {
  toasts: Toast[];
  addToast: (type: ToastType, message: string) => void;
  removeToast: (id: number) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

let nextId = 0;

/** Auto-dismiss duration in ms per type. */
const DISMISS_MS: Record<ToastType, number | null> = {
  success: 5000,
  info: 5000,
  warning: 8000,
  error: null, // sticky — user must dismiss
};

/** Colour classes per toast type. */
const TYPE_STYLES: Record<ToastType, string> = {
  success: "bg-emerald-900/90 border-emerald-700 text-emerald-200",
  error: "bg-red-900/90 border-red-700 text-red-200",
  warning: "bg-amber-900/90 border-amber-700 text-amber-200",
  info: "bg-blue-900/90 border-blue-700 text-blue-200",
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const removeToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const addToast = useCallback(
    (type: ToastType, message: string) => {
      const id = ++nextId;
      setToasts((prev) => [...prev, { id, type, message }]);

      const dismissMs = DISMISS_MS[type];
      if (dismissMs !== null) {
        setTimeout(() => removeToast(id), dismissMs);
      }
    },
    [removeToast],
  );

  return (
    <ToastContext.Provider value={{ toasts, addToast, removeToast }}>
      {children}

      {/* Toast container — fixed bottom-right */}
      <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`flex items-start gap-2 rounded border px-4 py-3 text-sm shadow-lg ${TYPE_STYLES[toast.type]}`}
          >
            <span className="flex-1">{toast.message}</span>
            <button
              className="ml-2 opacity-60 hover:opacity-100"
              onClick={() => removeToast(toast.id)}
            >
              ✕
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

/** Hook to access toast notifications. */
export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error("useToast must be used within a ToastProvider");
  }
  return context;
}
