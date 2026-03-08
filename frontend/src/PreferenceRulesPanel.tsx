import { useCallback, useEffect, useState } from "react";
import {
  deletePreference,
  getPreferences,
  postPreference,
  type PreferenceRule,
} from "./api/client";

export default function PreferenceRulesPanel() {
  const [rules, setRules] = useState<PreferenceRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [newRule, setNewRule] = useState({ rule_type: "artist_folder", key: "", value: "" });

  const loadRules = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getPreferences();
      setRules(data);
    } catch {
      // Ignore
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadRules();
  }, [loadRules]);

  const handleCreate = useCallback(async () => {
    if (!newRule.key.trim() || !newRule.value.trim()) return;
    try {
      await postPreference(newRule);
      setNewRule({ rule_type: "artist_folder", key: "", value: "" });
      setShowForm(false);
      loadRules();
    } catch {
      // Ignore
    }
  }, [newRule, loadRules]);

  const handleDelete = useCallback(
    async (ruleId: number) => {
      try {
        await deletePreference(ruleId);
        loadRules();
      } catch {
        // Ignore
      }
    },
    [loadRules],
  );

  return (
    <div className="rounded border border-gray-800 bg-gray-900/50 p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-medium text-gray-300">Preference Rules</h3>
        <button
          onClick={() => setShowForm(!showForm)}
          className="text-xs text-gray-500 hover:text-gray-300"
        >
          {showForm ? "Cancel" : "+ Add Rule"}
        </button>
      </div>

      {/* Add rule form */}
      {showForm && (
        <div className="mb-3 flex flex-wrap items-end gap-2 text-xs">
          <label className="flex flex-col gap-1">
            <span className="text-gray-500">Type</span>
            <select
              value={newRule.rule_type}
              onChange={(e) => setNewRule({ ...newRule, rule_type: e.target.value })}
              className="rounded border border-gray-700 bg-gray-800 px-2 py-1 text-gray-300"
            >
              <option value="artist_folder">Artist Folder</option>
              <option value="va_handling">VA Handling</option>
              <option value="custom_path">Custom Path</option>
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-gray-500">Key (e.g. artist name)</span>
            <input
              type="text"
              value={newRule.key}
              onChange={(e) => setNewRule({ ...newRule, key: e.target.value })}
              className="rounded border border-gray-700 bg-gray-800 px-2 py-1 text-gray-300 outline-none"
              placeholder="Artist name..."
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-gray-500">Value (e.g. folder name)</span>
            <input
              type="text"
              value={newRule.value}
              onChange={(e) => setNewRule({ ...newRule, value: e.target.value })}
              className="rounded border border-gray-700 bg-gray-800 px-2 py-1 text-gray-300 outline-none"
              placeholder="Folder name..."
            />
          </label>
          <button
            onClick={handleCreate}
            className="rounded bg-emerald-700 px-3 py-1 text-emerald-200 hover:bg-emerald-600"
          >
            Save
          </button>
        </div>
      )}

      {/* Rules list */}
      {loading ? (
        <p className="text-xs text-gray-600">Loading...</p>
      ) : rules.length === 0 ? (
        <p className="text-xs text-gray-600">
          No preference rules yet. Rules are learned from your organisation decisions.
        </p>
      ) : (
        <div className="space-y-1">
          {rules.map((rule) => (
            <div
              key={rule.id}
              className="flex items-center justify-between rounded bg-gray-900 px-2 py-1 text-xs"
            >
              <div className="flex gap-3">
                <span className="text-gray-500">{formatRuleType(rule.rule_type)}</span>
                <span className="text-gray-400">{rule.key}</span>
                <span className="text-gray-300">{rule.value}</span>
              </div>
              <button
                onClick={() => handleDelete(rule.id)}
                className="text-gray-600 hover:text-red-400"
              >
                Delete
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function formatRuleType(type: string): string {
  return type.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
