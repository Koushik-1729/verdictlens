import { useEffect, useMemo, useRef, useState } from 'react';
import clsx from 'clsx';
import {
  Database,
  Plus,
  Trash2,
  Loader2,
  Search,
  X,
  ArrowUpRight,
  CheckCircle2,
  Upload,
} from 'lucide-react';
import EmptyState from '../components/EmptyState';
import { Badge, OutlineButton, PrimaryButton } from '../components/ui';
import {
  fetchDatasets,
  createDataset,
  deleteDataset,
  fetchExamples,
  deleteExample,
  fetchTraces,
  traceToDataset,
  importExamples,
  type Dataset,
  type DatasetExample,
  type TraceSummary,
} from '../lib/api';
import { timeAgo } from '../lib/utils';

const DATASET_GRID = 'grid-cols-[minmax(0,2fr)_minmax(0,1.5fr)_100px_160px_120px_48px]';

export default function Datasets() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');

  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [creating, setCreating] = useState(false);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [examples, setExamples] = useState<DatasetExample[]>([]);
  const [examplesLoading, setExamplesLoading] = useState(false);
  const [expandedExId, setExpandedExId] = useState<string | null>(null);

  const [showAddFromTrace, setShowAddFromTrace] = useState(false);
  const [traceSearch, setTraceSearch] = useState('');
  const [traces, setTraces] = useState<TraceSummary[]>([]);
  const [tracesLoading, setTracesLoading] = useState(false);
  const [addingTraceId, setAddingTraceId] = useState<string | null>(null);
  const [addTargetDatasetId, setAddTargetDatasetId] = useState<string>('');
  const [importing, setImporting] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [importDatasetId, setImportDatasetId] = useState<string>('');
  const [importResult, setImportResult] = useState<{ imported: number } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    loadDatasets();
  }, []);

  async function loadDatasets() {
    setLoading(true);
    try {
      const ds = await fetchDatasets();
      setDatasets(ds);
    } catch {
      setDatasets([]);
    } finally {
      setLoading(false);
    }
  }

  async function handleCreate() {
    if (!newName.trim()) return;
    setCreating(true);
    try {
      const ds = await createDataset({ name: newName.trim(), description: newDesc.trim() });
      setDatasets((prev) => [ds, ...prev]);
      setShowCreate(false);
      setNewName('');
      setNewDesc('');
    } finally {
      setCreating(false);
    }
  }

  async function handleDelete(id: string) {
    if (!confirm('Delete this dataset and all its examples?')) return;
    await deleteDataset(id);
    setDatasets((prev) => prev.filter((d) => d.id !== id));
    if (selectedId === id) {
      setSelectedId(null);
      setExamples([]);
      setExpandedExId(null);
    }
  }

  async function openDataset(id: string) {
    setSelectedId(id);
    setExamplesLoading(true);
    setExpandedExId(null);
    try {
      const ex = await fetchExamples(id);
      setExamples(ex);
    } catch {
      setExamples([]);
    } finally {
      setExamplesLoading(false);
    }
  }

  async function openAddFromTrace() {
    setShowAddFromTrace(true);
    setAddTargetDatasetId(selectedId ?? (datasets[0]?.id ?? ''));
    setTracesLoading(true);
    try {
      const resp = await fetchTraces({ page_size: 50 });
      setTraces(resp.traces);
    } catch {
      setTraces([]);
    } finally {
      setTracesLoading(false);
    }
  }

  async function handleTraceSearch(q: string) {
    setTraceSearch(q);
    setTracesLoading(true);
    try {
      const resp = await fetchTraces({ name: q || undefined, page_size: 50 });
      setTraces(resp.traces);
    } catch {
      setTraces([]);
    } finally {
      setTracesLoading(false);
    }
  }

  async function handleAddTrace(traceId: string) {
    if (!addTargetDatasetId) return;
    setAddingTraceId(traceId);
    try {
      await traceToDataset(traceId, { dataset_id: addTargetDatasetId });
      setDatasets((prev) =>
        prev.map((d) =>
          d.id === addTargetDatasetId ? { ...d, example_count: d.example_count + 1 } : d,
        ),
      );
      if (selectedId === addTargetDatasetId) {
        const ex = await fetchExamples(addTargetDatasetId);
        setExamples(ex);
      }
    } finally {
      setAddingTraceId(null);
    }
  }

  async function handleDeleteExample(datasetId: string, exampleId: string) {
    await deleteExample(datasetId, exampleId);
    setExamples((prev) => prev.filter((e) => e.id !== exampleId));
    setDatasets((prev) =>
      prev.map((d) => (d.id === datasetId ? { ...d, example_count: Math.max(0, d.example_count - 1) } : d)),
    );
  }

  function openImportModal() {
    setImportDatasetId(selectedId ?? datasets[0]?.id ?? '');
    setImportResult(null);
    setShowImport(true);
  }

  async function handleFileImport(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    const targetId = importDatasetId || selectedId;
    if (!file || !targetId) return;
    setImporting(true);
    setImportResult(null);
    try {
      const result = await importExamples(targetId, file);
      setImportResult(result);
      // Refresh examples if this dataset is open in the drawer
      if (selectedId === targetId) {
        const ex = await fetchExamples(targetId);
        setExamples(ex);
      }
      setDatasets((prev) =>
        prev.map((d) => (d.id === targetId ? { ...d, example_count: d.example_count + result.imported } : d)),
      );
    } finally {
      setImporting(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  }

  const filtered = useMemo(
    () => datasets.filter((d) => !search || d.name.toLowerCase().includes(search.toLowerCase())),
    [datasets, search],
  );


  const selectedDataset = datasets.find((d) => d.id === selectedId) ?? null;

  return (
    <div className="flex h-full flex-col">
      {/* Page header */}
      <div className="flex items-center justify-between border-b border-border px-6 py-3.5">
        <div className="flex items-center gap-3">
          <h1 className="text-[15px] font-semibold text-text-primary">Datasets</h1>
          {!loading && (
            <span className="rounded-full bg-surface-700 px-2 py-0.5 text-[11px] font-medium text-text-muted">
              {datasets.length}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-48 items-center gap-2 rounded-md border border-border bg-surface-800 px-2.5">
            <Search className="h-3.5 w-3.5 shrink-0 text-text-muted" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search datasets…"
              className="h-full w-full border-0 bg-transparent text-[12px] text-text-primary outline-none placeholder:text-text-muted"
            />
          </div>
          <OutlineButton onClick={() => void openAddFromTrace()} disabled={datasets.length === 0} className="h-7 px-2.5 text-[12px]">
            <ArrowUpRight className="h-3.5 w-3.5" />
            Add from trace
          </OutlineButton>
          <OutlineButton
            onClick={openImportModal}
            disabled={datasets.length === 0}
            className="h-7 px-2.5 text-[12px]"
          >
            <Upload className="h-3.5 w-3.5" />
            Import CSV/JSONL
          </OutlineButton>
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,.json,.jsonl,.ndjson"
            className="hidden"
            onChange={(e) => void handleFileImport(e)}
          />
          <PrimaryButton onClick={() => setShowCreate(true)} className="h-7 px-2.5 text-[12px]">
            <Plus className="h-3.5 w-3.5" />
            New dataset
          </PrimaryButton>
        </div>
      </div>

      {/* Table area */}
      <div className="flex-1 overflow-auto">

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="h-6 w-6 animate-spin text-text-muted" />
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={<Database className="h-5 w-5" />}
          title={datasets.length === 0 ? 'No datasets yet' : 'No matching datasets'}
          description={
            datasets.length === 0
              ? 'Create a dataset to start collecting labeled examples for evaluations.'
              : 'Try a different search or create a new dataset for the examples you want to evaluate.'
          }
          action={(
            <PrimaryButton onClick={() => setShowCreate(true)}>
              <Plus className="h-3.5 w-3.5" />
              Create Dataset
            </PrimaryButton>
          )}
        />
      ) : (
        <div className="table-shell">
          <div className={clsx('table-header', DATASET_GRID)}>
            <span>Name</span>
            <span>Description</span>
            <span>Examples</span>
            <span>Workspace</span>
            <span>Created</span>
            <span />
          </div>

          <div>
            {filtered.map((dataset) => (
              <button
                key={dataset.id}
                onClick={() => void openDataset(dataset.id)}
                className={clsx(
                  'data-row min-h-[68px] w-full items-center text-left transition-all duration-100',
                  DATASET_GRID,
                  selectedId === dataset.id
                    ? 'bg-accent/[0.08] ring-1 ring-inset ring-accent/20'
                    : 'hover:bg-accent/[0.04]',
                )}
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <Database className="h-4 w-4 shrink-0 text-text-muted" />
                    <span className="truncate text-[14px] font-semibold text-text-primary">{dataset.name}</span>
                  </div>
                  <div className="mt-1 font-mono text-[11px] text-text-muted">{dataset.id.slice(0, 12)}...</div>
                </div>

                <div className="min-w-0 text-[13px] text-text-secondary">
                  <span className="block truncate">{dataset.description || 'No description yet'}</span>
                </div>

                <div className="font-mono text-[12px] text-text-secondary">{dataset.example_count}</div>

                <div className="min-w-0">
                  <Badge variant="default" className="max-w-full rounded-full px-2.5 py-1 font-mono">
                    <span className="truncate">{dataset.workspace_id}</span>
                  </Badge>
                  {dataset.project_name && (
                    <div className="mt-1 truncate text-[11px] text-text-muted">{dataset.project_name}</div>
                  )}
                </div>

                <div className="text-[12px] text-text-muted">{timeAgo(dataset.created_at)}</div>

                <div className="flex justify-end">
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      void handleDelete(dataset.id);
                    }}
                    className="rounded-md p-1.5 text-text-muted transition-colors hover:bg-danger/5 hover:text-danger"
                    title="Delete dataset"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      </div>{/* end flex-1 */}

      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-start justify-center bg-slate-950/18 px-4 py-20">
          <div className="ui-card w-full max-w-[560px] p-6">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-[18px] font-semibold text-text-primary">Create dataset</h2>
                <p className="mt-1 text-[14px] text-text-secondary">
                  Start with an empty dataset, then add examples from traces and replay workflows.
                </p>
              </div>
              <button
                onClick={() => {
                  setShowCreate(false);
                  setNewName('');
                  setNewDesc('');
                }}
                className="rounded-md p-1.5 text-text-muted transition-colors hover:bg-surface-800 hover:text-text-primary"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="mt-5 grid gap-4">
              <div>
                <label className="mb-1.5 block text-[12px] font-medium text-text-secondary">Dataset name</label>
                <input
                  type="text"
                  placeholder="Customer support regression set"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  className="input-base h-10 w-full"
                  autoFocus
                />
              </div>

              <div>
                <label className="mb-1.5 block text-[12px] font-medium text-text-secondary">Description</label>
                <textarea
                  placeholder="Short note about what this dataset is meant to validate."
                  value={newDesc}
                  onChange={(e) => setNewDesc(e.target.value)}
                  className="min-h-[96px] w-full rounded-lg border border-border bg-surface-900 px-3 py-2.5 text-[14px] text-text-primary outline-none transition-shadow placeholder:text-text-muted focus:border-accent focus:ring-4 focus:ring-accent/10"
                />
              </div>
            </div>

            <div className="mt-6 flex items-center justify-end gap-2">
              <OutlineButton
                onClick={() => {
                  setShowCreate(false);
                  setNewName('');
                  setNewDesc('');
                }}
              >
                Cancel
              </OutlineButton>
              <PrimaryButton onClick={() => void handleCreate()} className={clsx((creating || !newName.trim()) && 'pointer-events-none opacity-60')}>
                {creating ? 'Creating…' : 'Create'}
              </PrimaryButton>
            </div>
          </div>
        </div>
      )}

      {showImport && (
        <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 backdrop-blur-sm px-4 py-20">
          <div className="w-full max-w-md rounded-xl border border-border bg-surface-800 shadow-2xl overflow-hidden">
            <div className="flex items-center justify-between px-5 py-4 border-b border-border">
              <div>
                <div className="text-[15px] font-semibold text-text-primary">Import Examples</div>
                <div className="text-[12px] text-text-muted mt-0.5">Upload a CSV or JSONL file into a dataset</div>
              </div>
              <button onClick={() => setShowImport(false)} className="text-text-muted hover:text-text-primary transition-colors">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="px-5 py-4 space-y-4">
              <div>
                <label className="text-[11px] font-medium uppercase tracking-wider text-text-muted mb-1.5 block">Import into dataset</label>
                <select
                  value={importDatasetId}
                  onChange={(e) => setImportDatasetId(e.target.value)}
                  className="input-base w-full text-[13px]"
                >
                  {datasets.map((d) => (
                    <option key={d.id} value={d.id}>{d.name} ({d.example_count} examples)</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-[11px] font-medium uppercase tracking-wider text-text-muted mb-1.5 block">File (CSV or JSONL)</label>
                <button
                  onClick={() => fileInputRef.current?.click()}
                  disabled={importing}
                  className="flex w-full items-center justify-center gap-2 rounded-lg border-2 border-dashed border-border bg-surface-900 px-4 py-6 text-[13px] text-text-muted transition-colors hover:border-accent/40 hover:text-text-primary disabled:opacity-50"
                >
                  {importing
                    ? <><Loader2 className="h-4 w-4 animate-spin" /> Importing…</>
                    : <><Upload className="h-4 w-4" /> Click to select .csv or .jsonl file</>
                  }
                </button>
              </div>
              {importResult && (
                <div className="rounded-lg bg-success/10 border border-success/20 px-4 py-3 text-[13px] text-success">
                  ✓ Imported {importResult.imported} example{importResult.imported !== 1 ? 's' : ''} successfully
                </div>
              )}
              <div className="rounded-lg bg-surface-900 px-4 py-3 text-[11px] text-text-muted space-y-1">
                <div className="font-medium text-text-secondary mb-1">Expected format:</div>
                <div>JSONL: <code className="font-mono text-accent">{'{"inputs": {"q": "..."}, "expected": {"a": "..."}}'}</code></div>
                <div>CSV: columns named <code className="font-mono text-accent">inputs, outputs, expected</code></div>
              </div>
            </div>
            <div className="px-5 py-3 border-t border-border flex justify-end">
              <OutlineButton onClick={() => setShowImport(false)}>Close</OutlineButton>
            </div>
          </div>
        </div>
      )}

      {showAddFromTrace && (
        <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 backdrop-blur-sm px-4 py-16">
          <div className="w-full max-w-lg rounded-xl border border-border bg-surface-800 shadow-2xl overflow-hidden">
            <div className="flex items-center justify-between px-5 py-4 border-b border-border">
              <div>
                <div className="text-[15px] font-semibold text-text-primary">Add from Trace</div>
                <div className="text-[12px] text-text-muted mt-0.5">Pick a trace to add as a dataset example</div>
              </div>
              <button onClick={() => setShowAddFromTrace(false)} className="text-text-muted hover:text-text-primary transition-colors">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="px-5 py-3 border-b border-border space-y-3">
              <div>
                <label className="text-[11px] font-medium uppercase tracking-wider text-text-muted mb-1.5 block">Add to dataset</label>
                <select
                  value={addTargetDatasetId}
                  onChange={(e) => setAddTargetDatasetId(e.target.value)}
                  className="input-base w-full text-[13px]"
                >
                  {datasets.map((d) => (
                    <option key={d.id} value={d.id}>{d.name}</option>
                  ))}
                </select>
              </div>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-text-muted" />
                <input
                  type="text"
                  value={traceSearch}
                  onChange={(e) => void handleTraceSearch(e.target.value)}
                  placeholder="Search traces by name..."
                  className="input-base w-full pl-9 text-[13px]"
                />
              </div>
            </div>
            <div className="max-h-80 overflow-y-auto">
              {tracesLoading ? (
                <div className="flex items-center justify-center py-12">
                  <Loader2 className="h-5 w-5 animate-spin text-text-muted" />
                </div>
              ) : traces.length === 0 ? (
                <div className="py-12 text-center text-[13px] text-text-muted">No traces found</div>
              ) : (
                traces.map((t) => (
                  <div key={t.trace_id} className="flex items-center justify-between gap-3 px-5 py-3 border-b border-border hover:bg-surface-700 transition-colors">
                    <div className="min-w-0 flex-1">
                      <div className="text-[13px] font-medium text-text-primary truncate">{t.name}</div>
                      <div className="flex items-center gap-2 mt-0.5 text-[11px] text-text-muted">
                        <span className={t.status === 'error' ? 'text-danger' : 'text-success'}>{t.status}</span>
                        <span>·</span>
                        <span>{timeAgo(t.start_time ?? '')}</span>
                        {t.model && <><span>·</span><span className="font-mono">{t.model}</span></>}
                      </div>
                    </div>
                    <button
                      onClick={() => void handleAddTrace(t.trace_id)}
                      disabled={addingTraceId === t.trace_id}
                      className="flex items-center gap-1.5 rounded-md border border-border bg-surface-700 px-3 py-1.5 text-[11px] font-medium text-text-secondary hover:bg-accent/10 hover:text-accent hover:border-accent/30 disabled:opacity-50 transition-colors"
                    >
                      {addingTraceId === t.trace_id ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <CheckCircle2 className="h-3 w-3" />
                      )}
                      Add
                    </button>
                  </div>
                ))
              )}
            </div>
            <div className="px-5 py-3 border-t border-border flex justify-end">
              <OutlineButton onClick={() => setShowAddFromTrace(false)}>Done</OutlineButton>
            </div>
          </div>
        </div>
      )}

      {selectedDataset && (
        <div className="fixed inset-0 z-40 flex justify-end bg-slate-950/12">
          <button className="flex-1" aria-label="Close dataset detail" onClick={() => setSelectedId(null)} />
          <div className="relative h-full w-full max-w-[560px] overflow-y-auto border-l border-border bg-surface-900 shadow-[0_12px_48px_rgba(15,23,42,0.12)]">
            <div className="sticky top-0 z-10 border-b border-border bg-surface-900 px-5 py-4">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2">
                    <Database className="h-4 w-4 text-text-muted" />
                    <h3 className="text-[18px] font-semibold text-text-primary">{selectedDataset.name}</h3>
                  </div>
                  <p className="mt-1 text-[13px] text-text-secondary">
                    {selectedDataset.description || 'No description yet'}
                  </p>
                </div>
                <button
                  onClick={() => setSelectedId(null)}
                  className="rounded-md p-1.5 text-text-muted transition-colors hover:bg-surface-800 hover:text-text-primary"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>

              <div className="mt-4 grid grid-cols-3 gap-3">
                <DatasetStat label="Examples" value={String(selectedDataset.example_count)} />
                <DatasetStat label="Workspace" value={selectedDataset.workspace_id} mono />
                <DatasetStat label="Created" value={timeAgo(selectedDataset.created_at)} />
              </div>
            </div>

            <div className="p-5">
              {examplesLoading ? (
                <div className="flex items-center justify-center py-20">
                  <Loader2 className="h-5 w-5 animate-spin text-text-muted" />
                </div>
              ) : examples.length === 0 ? (
                <EmptyState
                  icon={<Database className="h-5 w-5" />}
                  title="No examples yet"
                  description='Add examples from Trace Detail using "Add to Dataset" to populate this dataset.'
                />
              ) : (
                <div className="space-y-3">
                  {examples.map((example) => {
                    const expanded = expandedExId === example.id;
                    return (
                      <div key={example.id} className="ui-card overflow-hidden">
                        <button
                          onClick={() => setExpandedExId(expanded ? null : example.id)}
                          className="flex w-full items-center justify-between px-4 py-3 text-left transition-colors hover:bg-accent/[0.03]"
                        >
                          <div className="min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="font-mono text-[12px] font-medium text-text-primary">
                                {example.id.slice(0, 12)}...
                              </span>
                              <span className="rounded px-1.5 py-0.5 text-[10px] font-mono bg-surface-700 text-text-muted">
                                {example.split || 'train'}
                              </span>
                            </div>
                            <div className="mt-1 flex items-center gap-2 text-[11px] text-text-muted">
                              {example.source_trace_id && (
                                <span>trace {example.source_trace_id.slice(0, 8)}</span>
                              )}
                              <span>{timeAgo(example.created_at)}</span>
                            </div>
                          </div>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              void handleDeleteExample(example.dataset_id, example.id);
                            }}
                            className="rounded-md p-1.5 text-text-muted transition-colors hover:bg-danger/5 hover:text-danger"
                            title="Delete example"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </button>

                        {expanded && (
                          <div className="border-t border-border bg-surface-800 px-4 py-4">
                            <div className="space-y-4">
                              <FieldBlock label="Inputs" value={example.inputs} />
                              <FieldBlock label="Outputs" value={example.outputs} />
                              {hasData(example.expected) && <FieldBlock label="Expected" value={example.expected} />}
                              {hasData(example.metadata) && <FieldBlock label="Metadata" value={example.metadata} />}
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function DatasetStat({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="rounded-xl border border-border bg-surface-800 px-3 py-3">
      <div className="text-[11px] font-medium text-text-muted">{label}</div>
      <div className={clsx('mt-1 text-[13px] font-semibold text-text-primary', mono && 'font-mono text-[12px]')}>
        {value}
      </div>
    </div>
  );
}

function hasData(value: unknown) {
  if (value == null) return false;
  if (typeof value === 'string') return value.trim().length > 0;
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === 'object') return Object.keys(value as Record<string, unknown>).length > 0;
  return true;
}

function FieldBlock({ label, value }: { label: string; value: unknown }) {
  const text = typeof value === 'string' ? value : JSON.stringify(value, null, 2);

  return (
    <div>
      <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">{label}</div>
      <pre className="mt-2 overflow-auto rounded-xl bg-slate-950 px-4 py-3 font-mono text-[12px] leading-6 text-slate-100">
        {text || '—'}
      </pre>
    </div>
  );
}
