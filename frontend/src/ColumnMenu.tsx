import { useEffect, useRef } from "react";

export interface ColumnConfig {
  id: string;
  label: string;
  visible: boolean;
  defaultVisible: boolean;
}

interface ColumnMenuProps {
  columns: ColumnConfig[];
  onToggle: (columnId: string) => void;
  onResetDefaults: () => void;
  onClose: () => void;
  position: { x: number; y: number };
}

export default function ColumnMenu({
  columns,
  onToggle,
  onResetDefaults,
  onClose,
  position,
}: ColumnMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose();
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [onClose]);

  return (
    <div
      ref={menuRef}
      className="fixed z-50 min-w-48 rounded border border-gray-700 bg-gray-900 py-1 shadow-lg"
      style={{ left: position.x, top: position.y }}
    >
      <div className="border-b border-gray-800 px-3 py-1.5 text-xs font-medium text-gray-400">
        Show/Hide Columns
      </div>
      {columns.map((col) => (
        <label
          key={col.id}
          className="flex cursor-pointer items-center gap-2 px-3 py-1 text-xs text-gray-300 hover:bg-gray-800"
        >
          <input
            type="checkbox"
            checked={col.visible}
            onChange={() => onToggle(col.id)}
            className="accent-blue-500"
          />
          {col.label}
        </label>
      ))}
      <div className="border-t border-gray-800 px-3 py-1.5">
        <button onClick={onResetDefaults} className="text-xs text-gray-500 hover:text-gray-300">
          Reset to Default
        </button>
      </div>
    </div>
  );
}
