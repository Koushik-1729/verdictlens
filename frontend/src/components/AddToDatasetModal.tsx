import { useEffect, useState } from 'react';
import { X, Database, Plus, Check, Loader2 } from 'lucide-react';
import {
  fetchDatasets,
  createDataset,
  traceToDataset,
  type Dataset,
  type DatasetExample,
} from '../lib/api';

interface Props {
  traceId: string;
  spanId?: string;
  onClose: () => void;
  onComplete?: (example: DatasetExample) => void;
}

export default function AddToDatasetModal({ traceId, spanId, onClose, onComplete }: Props) {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [showNewForm, setShowNewForm] = useState(false);

  useEffect(() => {
    fetchDatasets()
      .then((ds) => {
        setDatasets(ds);
        if (ds.length > 0) setSelectedId(ds[0].id);
      })
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, []);

  async function handleCreateDataset() {
    if (!newName.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const ds = await createDataset({ name: newName.trim(), description: newDesc.trim() });
      setDatasets((prev) => [ds, ...prev]);
      setSelectedId(ds.id);
      setShowNewForm(false);
      setNewName('');
      setNewDesc('');
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setCreating(false);
    }
  }

  async function handleSubmit() {
    if (!selectedId) return;
    setSubmitting(true);
    setError(null);
    try {
      const example = await traceToDataset(traceId, {
        dataset_id: selectedId,
        span_id: spanId,
      });
      setDone(true);
      onComplete?.(example);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-lg rounded-xl border border-border bg-surface-900 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <div className="flex items-center gap-2.5">
            <Database className="h-5 w-5 text-accent" />
            <h2 className="text-base font-semibold text-text-primary">Add to Dataset</h2>
          </div>
          <button onClick={onClose} className="rounded p-1 text-text-muted hover:bg-surface-700 hover:text-text-primary transition-colors">
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-4 space-y-4">
          {done ? (
            <div className="flex flex-col items-center gap-3 py-6">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-success/10">
                <Check className="h-6 w-6 text-success" />
              </div>
              <p className="text-sm text-text-primary font-medium">Example added successfully</p>
              <p className="text-xs text-text-muted">
                {spanId ? 'Span' : 'Trace'} saved to dataset
              </p>
            </div>
          ) : (
            <>
              <p className="text-sm text-text-secondary">
                Save this {spanId ? 'span' : 'trace'} as a labeled example for evaluations.
              </p>

              {loading ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="h-5 w-5 animate-spin text-text-muted" />
                </div>
              ) : (
                <>
                  {/* Dataset selector */}
                  <div>
                    <label className="block text-xs font-medium text-text-secondary mb-1.5">
                      Select Dataset
                    </label>
                    {datasets.length > 0 ? (
                      <div className="space-y-1 max-h-48 overflow-y-auto rounded-lg border border-border bg-surface-800 p-1">
                        {datasets.map((ds) => (
                          <button
                            key={ds.id}
                            onClick={() => setSelectedId(ds.id)}
                            className={`w-full text-left rounded-md px-3 py-2 text-sm transition-colors ${
                              selectedId === ds.id
                                ? 'bg-accent/10 text-accent border border-accent/30'
                                : 'text-text-primary hover:bg-surface-700 border border-transparent'
                            }`}
                          >
                            <div className="font-medium">{ds.name}</div>
                            <div className="text-xs text-text-muted mt-0.5">
                              {ds.example_count} example{ds.example_count !== 1 ? 's' : ''}
                              {ds.description ? ` · ${ds.description}` : ''}
                            </div>
                          </button>
                        ))}
                      </div>
                    ) : (
                      <p className="text-xs text-text-muted py-3 text-center">
                        No datasets yet. Create one below.
                      </p>
                    )}
                  </div>

                  {/* Create new dataset */}
                  {showNewForm ? (
                    <div className="rounded-lg border border-border bg-surface-800 p-3 space-y-2.5">
                      <input
                        type="text"
                        placeholder="Dataset name"
                        value={newName}
                        onChange={(e) => setNewName(e.target.value)}
                        className="w-full rounded-md border border-border bg-surface-900 px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
                        autoFocus
                      />
                      <input
                        type="text"
                        placeholder="Description (optional)"
                        value={newDesc}
                        onChange={(e) => setNewDesc(e.target.value)}
                        className="w-full rounded-md border border-border bg-surface-900 px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
                      />
                      <div className="flex justify-end gap-2">
                        <button
                          onClick={() => setShowNewForm(false)}
                          className="rounded-md px-3 py-1.5 text-xs text-text-muted hover:text-text-primary transition-colors"
                        >
                          Cancel
                        </button>
                        <button
                          onClick={handleCreateDataset}
                          disabled={creating || !newName.trim()}
                          className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent/90 transition-colors disabled:opacity-50"
                        >
                          {creating ? 'Creating…' : 'Create'}
                        </button>
                      </div>
                    </div>
                  ) : (
                    <button
                      onClick={() => setShowNewForm(true)}
                      className="flex items-center gap-1.5 text-xs text-accent hover:text-accent/80 transition-colors"
                    >
                      <Plus className="h-3.5 w-3.5" />
                      Create new dataset
                    </button>
                  )}
                </>
              )}

              {error && (
                <div className="rounded-md bg-danger/10 px-3 py-2 text-xs text-danger">
                  {error}
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 border-t border-border px-5 py-3">
          {done ? (
            <button
              onClick={onClose}
              className="rounded-md bg-surface-700 px-4 py-1.5 text-sm font-medium text-text-primary hover:bg-surface-600 transition-colors"
            >
              Close
            </button>
          ) : (
            <>
              <button
                onClick={onClose}
                className="rounded-md px-4 py-1.5 text-sm text-text-muted hover:text-text-primary transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleSubmit}
                disabled={submitting || !selectedId || loading}
                className="rounded-md bg-accent px-4 py-1.5 text-sm font-medium text-white hover:bg-accent/90 transition-colors disabled:opacity-50"
              >
                {submitting ? (
                  <span className="flex items-center gap-1.5">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    Saving…
                  </span>
                ) : (
                  'Add Example'
                )}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
