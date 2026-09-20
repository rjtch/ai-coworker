import { useEffect, useMemo, useState } from "react";
import {
  deletePrompt,
  getPromptsAdminToken,
  listPrompts,
  reloadPrompts,
  resetPrompt,
  setPromptsAdminToken,
  updatePrompt,
  type PromptRecord,
} from "./api";

type Props = {
  onBack: () => void;
};

export default function PromptsPanel({ onBack }: Props) {
  const [prompts, setPrompts] = useState<PromptRecord[]>([]);
  const [catalogVersion, setCatalogVersion] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [adminToken, setAdminToken] = useState(getPromptsAdminToken);
  const [filter, setFilter] = useState("");

  const selected = useMemo(
    () => prompts.find((p) => p.id === selectedId) ?? null,
    [prompts, selectedId],
  );

  const dirty = selected != null && draft !== selected.text;

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return prompts;
    return prompts.filter(
      (p) =>
        p.id.toLowerCase().includes(q) ||
        p.description.toLowerCase().includes(q) ||
        p.role.toLowerCase().includes(q),
    );
  }, [prompts, filter]);

  async function loadCatalog(preferId?: string | null) {
    setLoading(true);
    setError(null);
    try {
      const data = await listPrompts();
      setPrompts(data.prompts);
      setCatalogVersion(data.catalog_version);
      const nextId =
        preferId && data.prompts.some((p) => p.id === preferId)
          ? preferId
          : (data.prompts[0]?.id ?? null);
      setSelectedId(nextId);
      const rec = data.prompts.find((p) => p.id === nextId);
      setDraft(rec?.text ?? "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load prompts");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadCatalog();
  }, []);

  function selectPrompt(id: string) {
    if (dirty && !window.confirm("Discard unsaved changes?")) return;
    const rec = prompts.find((p) => p.id === id);
    setSelectedId(id);
    setDraft(rec?.text ?? "");
    setStatus(null);
    setError(null);
  }

  async function handleSave() {
    if (!selected || !dirty) return;
    setSaving(true);
    setError(null);
    setStatus(null);
    try {
      const updated = await updatePrompt(selected.id, draft);
      setPrompts((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
      setDraft(updated.text);
      setStatus("Saved");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!selected) return;
    if (!window.confirm(`Delete “${selected.id}”? This cannot be undone.`)) {
      return;
    }
    setSaving(true);
    setError(null);
    setStatus(null);
    try {
      await deletePrompt(selected.id);
      const remaining = prompts.filter((p) => p.id !== selected.id);
      setPrompts(remaining);
      const next = remaining[0] ?? null;
      setSelectedId(next?.id ?? null);
      setDraft(next?.text ?? "");
      setStatus("Deleted");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setSaving(false);
    }
  }

  async function handleReset() {
    if (!selected) return;
    if (
      !window.confirm(
        `Reset “${selected.id}” to the bundled default? Your edits will be lost.`,
      )
    ) {
      return;
    }
    setSaving(true);
    setError(null);
    setStatus(null);
    try {
      const updated = await resetPrompt(selected.id);
      setPrompts((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
      setDraft(updated.text);
      setStatus("Reset to default");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reset failed");
    } finally {
      setSaving(false);
    }
  }

  async function handleReload() {
    if (dirty && !window.confirm("Discard unsaved changes and reset all prompts to defaults?")) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await reloadPrompts();
      await loadCatalog(selectedId);
      setStatus("Catalog reset to defaults");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reload failed");
    } finally {
      setSaving(false);
    }
  }

  function handleTokenBlur() {
    setPromptsAdminToken(adminToken);
  }

  return (
    <div className="prompts">
      <div className="prompts-toolbar">
        <div className="prompts-toolbar-left">
          <button type="button" className="ghost" onClick={onBack}>
            ← Chat
          </button>
          <div>
            <h1 className="prompts-title">Prompts</h1>
            <p className="prompts-sub">Catalog v{catalogVersion}</p>
          </div>
        </div>
        <div className="prompts-toolbar-right">
          <label className="token-field">
            Admin token
            <input
              type="password"
              value={adminToken}
              placeholder="optional"
              onChange={(e) => setAdminToken(e.target.value)}
              onBlur={handleTokenBlur}
              autoComplete="off"
            />
          </label>
          <button type="button" className="ghost" disabled={saving || loading} onClick={() => void handleReload()}>
            Reset all
          </button>
        </div>
      </div>

      {error ? <p className="error">{error}</p> : null}
      {status ? <p className="prompts-status">{status}</p> : null}

      {loading ? (
        <p className="prompts-empty">Loading prompts…</p>
      ) : (
        <div className="prompts-layout">
          <aside className="prompts-list" aria-label="Prompt catalog">
            <input
              className="prompts-filter"
              type="search"
              placeholder="Filter by id, role…"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
            <ul>
              {filtered.map((p) => (
                <li key={p.id}>
                  <button
                    type="button"
                    className={`prompt-item ${p.id === selectedId ? "active" : ""}`}
                    onClick={() => selectPrompt(p.id)}
                  >
                    <span className="prompt-item-id">{p.id}</span>
                    <span className="prompt-item-meta">
                      <span className="intent">{p.role}</span>
                    </span>
                    <span className="prompt-item-desc">{p.description || "—"}</span>
                  </button>
                </li>
              ))}
            </ul>
            {filtered.length === 0 ? (
              <p className="prompts-empty">No prompts match.</p>
            ) : null}
          </aside>

          <section className="prompts-editor" aria-label="Prompt editor">
            {selected ? (
              <>
                <div className="prompts-editor-head">
                  <div>
                    <h2>{selected.id}</h2>
                    <p>
                      {selected.description || "No description"}
                      {selected.variables.length > 0
                        ? ` · vars: {${selected.variables.join("}, {")}}`
                        : ""}
                    </p>
                  </div>
                  <div className="prompts-editor-actions">
                    <button
                      type="button"
                      className="danger"
                      disabled={saving}
                      onClick={() => void handleDelete()}
                      title="Permanently remove this prompt"
                    >
                      Delete
                    </button>
                    <button
                      type="button"
                      className="ghost"
                      disabled={saving}
                      onClick={() => void handleReset()}
                      title="Reset to bundled default"
                    >
                      Reset
                    </button>
                    <button
                      type="button"
                      className="primary"
                      disabled={saving || !dirty || !draft.trim()}
                      onClick={() => void handleSave()}
                    >
                      {saving ? "Saving…" : dirty ? "Save" : "Saved"}
                    </button>
                  </div>
                </div>
                <textarea
                  className="prompts-textarea"
                  value={draft}
                  onChange={(e) => {
                    setDraft(e.target.value);
                    setStatus(null);
                  }}
                  spellCheck={false}
                  disabled={saving}
                />
                {selected.updated_at ? (
                  <p className="thread">updated {selected.updated_at}</p>
                ) : (
                  <p className="thread">default</p>
                )}
              </>
            ) : (
              <p className="prompts-empty">Select a prompt to edit, or reset all to restore defaults.</p>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
