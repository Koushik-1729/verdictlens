import { useEffect, useMemo, useState } from 'react';
import clsx from 'clsx';
import {
  ArrowLeftRight,
  BarChart3,
  CheckCircle2,
  FlaskConical,
  Loader2,
  Plus,
  Search,
  Trash2,
  X,
  XCircle,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import EmptyState from '../components/EmptyState';
import EvalResultsTable from '../components/EvalResultsTable';
import { OutlineButton, PrimaryButton } from '../components/ui';
import {
  compareEvaluations,
  createEvaluation,
  deleteEvaluation,
  fetchDatasets,
  fetchEvalResults,
  fetchEvaluations,
  type CompareResult,
  type Dataset,
  type Evaluation,
  type EvalResult,
  type ScorerConfig,
} from '../lib/api';
import { timeAgo } from '../lib/utils';

const EVAL_GRID = 'grid-cols-[minmax(0,1.5fr)_minmax(0,1.1fr)_80px_90px_90px_120px_48px]';

export default function Evaluations() {
  const navigate = useNavigate();
  const [evals, setEvals] = useState<Evaluation[]>([]);
  const [loading, setLoading] = useState(true);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [search, setSearch] = useState('');

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [results, setResults] = useState<EvalResult[]>([]);
  const [resultsLoading, setResultsLoading] = useState(false);

  const [showCreate, setShowCreate] = useState(false);
  const [formName, setFormName] = useState('');
  const [formDataset, setFormDataset] = useState('');
  const [formScorer, setFormScorer] = useState<ScorerConfig['type']>('exact_match');
  const [formScorerField, setFormScorerField] = useState('');
  const [formScorerThreshold, setFormScorerThreshold] = useState('0.8');
  const [formScorerModel, setFormScorerModel] = useState('llama-3.3-70b-versatile');
  const [formScorerPrompt, setFormScorerPrompt] = useState('');
  const [formMode, setFormMode] = useState<'replay' | 'live'>('replay');
  const [creating, setCreating] = useState(false);

  const [compareA, setCompareA] = useState<string>('');
  const [compareB, setCompareB] = useState<string>('');
  const [compareResult, setCompareResult] = useState<CompareResult | null>(null);
  const [comparing, setComparing] = useState(false);

  useEffect(() => {
    Promise.all([fetchEvaluations(), fetchDatasets()])
      .then(([loadedEvals, loadedDatasets]) => {
        setEvals(loadedEvals);
        setDatasets(loadedDatasets);
        if (loadedEvals.length > 0) {
          void selectEval(loadedEvals[0].id, loadedEvals);
        }
      })
      .finally(() => setLoading(false));
  }, []);

  async function handleCreate() {
    if (!formName.trim() || !formDataset) return;
    setCreating(true);
    try {
      const scorerConfig: ScorerConfig = { type: formScorer };
      if (formScorerField.trim()) scorerConfig.field = formScorerField.trim();
      if (formScorer === 'contains' && formScorerThreshold) scorerConfig.threshold = parseFloat(formScorerThreshold);
      if (formScorer === 'llm_judge') {
        scorerConfig.model = formScorerModel;
        if (formScorerPrompt.trim()) scorerConfig.prompt_template = formScorerPrompt.trim();
      }
      if (formScorer === 'regex' && formScorerField.trim()) {
        scorerConfig.field = formScorerField.trim();
      }
      if (formScorer === 'json_match' && formScorerField.trim()) {
        scorerConfig.field = formScorerField.trim();
      }
      const created = await createEvaluation({
        name: formName.trim(),
        dataset_id: formDataset,
        scorers: [scorerConfig],
        mode: formMode,
      });
      setEvals((prev) => [created, ...prev]);
      setShowCreate(false);
      setFormName('');
      setFormDataset('');
      setFormScorer('exact_match');
      setFormMode('replay');
      await selectEval(created.id, [created, ...evals]);
    } finally {
      setCreating(false);
    }
  }

  async function handleDelete(id: string) {
    if (!confirm('Delete this evaluation and all results?')) return;
    await deleteEvaluation(id);
    const remaining = evals.filter((item) => item.id !== id);
    setEvals(remaining);
    if (selectedId === id) {
      if (remaining.length > 0) {
        await selectEval(remaining[0].id, remaining);
      } else {
        setSelectedId(null);
        setResults([]);
      }
    }
  }

  async function selectEval(id: string, evalList = evals) {
    setSelectedId(id);
    setResultsLoading(true);
    setCompareResult(null);
    try {
      const loadedResults = await fetchEvalResults(id);
      setResults(loadedResults);
      if (!compareA && evalList.length > 1) {
        setCompareA(id);
      }
    } catch {
      setResults([]);
    } finally {
      setResultsLoading(false);
    }
  }

  async function handleCompare() {
    if (!compareA || !compareB || compareA === compareB) return;
    setComparing(true);
    try {
      const response = await compareEvaluations(compareA, compareB);
      setCompareResult(response);
    } finally {
      setComparing(false);
    }
  }

  const datasetById = useMemo(
    () => Object.fromEntries(datasets.map((dataset) => [dataset.id, dataset])),
    [datasets],
  );

  const filteredEvals = useMemo(
    () =>
      evals.filter((item) => {
        if (!search) return true;
        const query = search.toLowerCase();
        const datasetName = datasetById[item.dataset_id]?.name ?? '';
        return item.name.toLowerCase().includes(query) || datasetName.toLowerCase().includes(query);
      }),
    [datasetById, evals, search],
  );

  const selected = evals.find((item) => item.id === selectedId) ?? null;

  return (
    <div className="flex h-full flex-col">
      {/* Page header */}
      <div className="flex items-center justify-between border-b border-border px-6 py-3.5">
        <div className="flex items-center gap-3">
          <h1 className="text-[15px] font-semibold text-text-primary">Evaluations</h1>
          {!loading && (
            <span className="rounded-full bg-surface-700 px-2 py-0.5 text-[11px] font-medium text-text-muted">
              {evals.length}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-52 items-center gap-2 rounded-md border border-border bg-surface-800 px-2.5">
            <Search className="h-3.5 w-3.5 shrink-0 text-text-muted" />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search evaluations…"
              className="h-full w-full border-0 bg-transparent text-[12px] text-text-primary outline-none placeholder:text-text-muted"
            />
          </div>
          <OutlineButton onClick={() => navigate('/datasets')} className="h-7 px-2.5 text-[12px]">
            <FlaskConical className="h-3.5 w-3.5" />
            Datasets
          </OutlineButton>
          <PrimaryButton onClick={() => setShowCreate(true)} disabled={datasets.length === 0} className="h-7 px-2.5 text-[12px]">
            <Plus className="h-3.5 w-3.5" />
            Run Evaluation
          </PrimaryButton>
        </div>
      </div>

      {/* Content area */}
      <div className="flex-1 overflow-auto p-5 space-y-4">

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="h-6 w-6 animate-spin text-text-muted" />
        </div>
      ) : filteredEvals.length === 0 ? (
        <EmptyState
          icon={<FlaskConical className="h-5 w-5" />}
          title={evals.length === 0 ? 'No evaluations yet' : 'No matching evaluations'}
          description={
            evals.length === 0
              ? datasets.length === 0
                ? 'Create a dataset first, then run an evaluation to score your pipeline outputs.'
                : 'Run your first evaluation to compare prompt, replay, or live execution quality.'
              : 'Try a different search query or create a new evaluation run.'
          }
          action={
            datasets.length === 0 ? (
              <PrimaryButton onClick={() => navigate('/datasets')}>
                <FlaskConical className="h-3.5 w-3.5" />
                Create Dataset
              </PrimaryButton>
            ) : (
              <PrimaryButton onClick={() => setShowCreate(true)}>
                <Plus className="h-3.5 w-3.5" />
                Run Evaluation
              </PrimaryButton>
            )
          }
        />
      ) : (
        <>
          <div className="table-shell">
            <div className={clsx('table-header', EVAL_GRID)}>
              <span>Name</span>
              <span>Dataset</span>
              <span>Mode</span>
              <span>Status</span>
              <span>Score</span>
              <span>Created</span>
              <span />
            </div>

            <div>
              {filteredEvals.map((evaluation) => {
                const dataset = datasetById[evaluation.dataset_id];
                return (
                  <button
                    key={evaluation.id}
                    onClick={() => void selectEval(evaluation.id)}
                    className={clsx(
                      'data-row min-h-[70px] w-full items-center text-left transition-all duration-100',
                      EVAL_GRID,
                      selectedId === evaluation.id
                        ? 'bg-accent/[0.08] ring-1 ring-inset ring-accent/20'
                        : 'hover:bg-accent/[0.04]',
                    )}
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <StatusIcon status={evaluation.status} />
                        <span className="truncate text-[14px] font-semibold text-text-primary">{evaluation.name}</span>
                      </div>
                      <div className="mt-1 text-[12px] text-text-muted">
                        {evaluation.total} examples · {evaluation.passed} passed · {evaluation.failed} failed
                      </div>
                    </div>

                    <div className="min-w-0">
                      <div className="truncate text-[13px] font-medium text-text-secondary">
                        {dataset?.name ?? 'Dataset unavailable'}
                      </div>
                      <div className="mt-1 truncate font-mono text-[11px] text-text-muted">
                        {evaluation.dataset_id.slice(0, 12)}...
                      </div>
                    </div>

                    <div className="text-[12px] font-medium capitalize text-text-secondary">{evaluation.mode}</div>

                    <div className="text-[12px] capitalize text-text-secondary">{evaluation.status}</div>

                    <div className="font-mono text-[12px] text-text-secondary">
                      {Math.round(evaluation.average_score * 100)}%
                    </div>

                    <div className="text-[12px] text-text-muted">{timeAgo(evaluation.created_at)}</div>

                    <div className="flex justify-end">
                      <button
                        onClick={(event) => {
                          event.stopPropagation();
                          void handleDelete(evaluation.id);
                        }}
                        className="rounded-md p-1.5 text-text-muted transition-colors hover:bg-danger/5 hover:text-danger"
                        title="Delete evaluation"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
            <div className="space-y-4">
              {compareResult ? (
                <ComparePanel result={compareResult} onClose={() => setCompareResult(null)} />
              ) : null}

              {!selected ? (
                <div className="ui-card flex items-center justify-center py-20 text-sm text-text-muted">
                  Select an evaluation to view results.
                </div>
              ) : resultsLoading ? (
                <div className="ui-card flex items-center justify-center py-20">
                  <Loader2 className="h-5 w-5 animate-spin text-text-muted" />
                </div>
              ) : (
                <>
                  <StatsBar evaluation={selected} />
                  <div className="ui-card overflow-hidden">
                    <div className="border-b border-border px-5 py-4">
                      <div className="text-[16px] font-semibold text-text-primary">Results</div>
                      <div className="mt-1 text-[13px] text-text-secondary">
                        Per-example scoring and output inspection for the selected evaluation.
                      </div>
                    </div>
                    <div className="p-5">
                      <EvalResultsTable results={results} />
                    </div>
                  </div>
                </>
              )}
            </div>

            <div className="space-y-4">
              <div className="ui-card p-5">
                <div className="text-[16px] font-semibold text-text-primary">Compare Runs</div>
                <div className="mt-1 text-[13px] text-text-secondary">
                  Compare two evaluations to see score deltas and relative wins.
                </div>

                <div className="mt-4 space-y-3">
                  <select
                    value={compareA}
                    onChange={(event) => setCompareA(event.target.value)}
                    className="input-base w-full text-[13px]"
                  >
                    <option value="">Select evaluation A...</option>
                    {evals.map((evaluation) => (
                      <option key={evaluation.id} value={evaluation.id}>
                        {evaluation.name}
                      </option>
                    ))}
                  </select>

                  <select
                    value={compareB}
                    onChange={(event) => setCompareB(event.target.value)}
                    className="input-base w-full text-[13px]"
                  >
                    <option value="">Select evaluation B...</option>
                    {evals.map((evaluation) => (
                      <option key={evaluation.id} value={evaluation.id}>
                        {evaluation.name}
                      </option>
                    ))}
                  </select>

                  <PrimaryButton
                    onClick={handleCompare}
                    disabled={!compareA || !compareB || compareA === compareB || comparing}
                    className="w-full"
                  >
                    <ArrowLeftRight className="h-3.5 w-3.5" />
                    {comparing ? 'Comparing…' : 'Compare Evaluations'}
                  </PrimaryButton>
                </div>
              </div>

              {selected && (
                <div className="ui-card p-5">
                  <div className="text-[16px] font-semibold text-text-primary">Selected Run</div>
                  <div className="mt-3 space-y-2 text-[13px] text-text-secondary">
                    <div className="flex items-center justify-between gap-3">
                      <span>Name</span>
                      <span className="font-medium text-text-primary">{selected.name}</span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span>Mode</span>
                      <span className="font-medium capitalize text-text-primary">{selected.mode}</span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span>Status</span>
                      <span className="font-medium capitalize text-text-primary">{selected.status}</span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span>Dataset</span>
                      <span className="max-w-[180px] truncate font-medium text-text-primary">
                        {datasetById[selected.dataset_id]?.name ?? 'Unavailable'}
                      </span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span>Workspace</span>
                      <span className="truncate font-mono text-[12px] text-text-primary">{selected.workspace_id}</span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {showCreate && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/35 p-4 backdrop-blur-[2px]">
          <div className="w-full max-w-lg overflow-hidden rounded-2xl border border-border bg-surface-900 shadow-[0_20px_80px_rgba(15,23,42,0.12)]">
            <div className="flex items-start justify-between border-b border-border px-5 py-4">
              <div>
                <div className="text-[20px] font-semibold text-text-primary">Run Evaluation</div>
                <div className="mt-1 text-[13px] text-text-secondary">
                  Choose a dataset, scorer, and execution mode for this evaluation run.
                </div>
              </div>
              <button
                onClick={() => setShowCreate(false)}
                className="rounded-md p-1.5 text-text-muted transition-colors hover:bg-surface-800 hover:text-text-primary"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="space-y-4 px-5 py-5">
              <div className="space-y-1.5">
                <label className="text-[12px] font-medium uppercase tracking-wider text-text-muted">Name</label>
                <input
                  value={formName}
                  onChange={(event) => setFormName(event.target.value)}
                  placeholder="Release quality check"
                  className="input-base w-full text-[13px]"
                  autoFocus
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-[12px] font-medium uppercase tracking-wider text-text-muted">Dataset</label>
                <select
                  value={formDataset}
                  onChange={(event) => setFormDataset(event.target.value)}
                  className="input-base w-full text-[13px]"
                >
                  <option value="">Select dataset...</option>
                  {datasets.map((dataset) => (
                    <option key={dataset.id} value={dataset.id}>
                      {dataset.name} ({dataset.example_count} examples)
                    </option>
                  ))}
                </select>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <label className="text-[12px] font-medium uppercase tracking-wider text-text-muted">Scorer</label>
                  <select
                    value={formScorer}
                    onChange={(event) => setFormScorer(event.target.value as ScorerConfig['type'])}
                    className="input-base w-full text-[13px]"
                  >
                    <option value="exact_match">Exact match</option>
                    <option value="contains">Contains</option>
                    <option value="llm_judge">LLM judge</option>
                    <option value="regex">Regex match</option>
                    <option value="json_match">JSON field match</option>
                  </select>
                </div>

                <div className="space-y-1.5">
                  <label className="text-[12px] font-medium uppercase tracking-wider text-text-muted">Mode</label>
                  <select
                    value={formMode}
                    onChange={(event) => setFormMode(event.target.value as 'replay' | 'live')}
                    className="input-base w-full text-[13px]"
                  >
                    <option value="replay">Replay</option>
                    <option value="live">Live</option>
                  </select>
                </div>
              </div>

              {/* Scorer-specific config */}
              {(formScorer === 'exact_match' || formScorer === 'contains') && (
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="space-y-1.5">
                    <label className="text-[12px] font-medium uppercase tracking-wider text-text-muted">
                      Field <span className="normal-case font-normal">(optional)</span>
                    </label>
                    <input
                      value={formScorerField}
                      onChange={(e) => setFormScorerField(e.target.value)}
                      placeholder="e.g. answer"
                      className="input-base w-full text-[13px]"
                    />
                  </div>
                  {formScorer === 'contains' && (
                    <div className="space-y-1.5">
                      <label className="text-[12px] font-medium uppercase tracking-wider text-text-muted">Threshold</label>
                      <input
                        type="number"
                        min={0}
                        max={1}
                        step={0.05}
                        value={formScorerThreshold}
                        onChange={(e) => setFormScorerThreshold(e.target.value)}
                        className="input-base w-full text-[13px]"
                      />
                    </div>
                  )}
                </div>
              )}

              {formScorer === 'regex' && (
                <div className="space-y-1.5">
                  <label className="text-[12px] font-medium uppercase tracking-wider text-text-muted">
                    Pattern <span className="normal-case font-normal">(regex applied to output)</span>
                  </label>
                  <input
                    value={formScorerField}
                    onChange={(e) => setFormScorerField(e.target.value)}
                    placeholder="e.g. ^\d{4}-\d{2}-\d{2}$"
                    className="input-base w-full text-[13px] font-mono"
                  />
                </div>
              )}

              {formScorer === 'json_match' && (
                <div className="space-y-1.5">
                  <label className="text-[12px] font-medium uppercase tracking-wider text-text-muted">
                    Field path <span className="normal-case font-normal">(dot-notation, e.g. result.score)</span>
                  </label>
                  <input
                    value={formScorerField}
                    onChange={(e) => setFormScorerField(e.target.value)}
                    placeholder="e.g. answer.text"
                    className="input-base w-full text-[13px] font-mono"
                  />
                </div>
              )}

              {formScorer === 'llm_judge' && (
                <div className="space-y-3">
                  <div className="space-y-1.5">
                    <label className="text-[12px] font-medium uppercase tracking-wider text-text-muted">Judge model</label>
                    <select
                      value={formScorerModel}
                      onChange={(e) => setFormScorerModel(e.target.value)}
                      className="input-base w-full text-[13px]"
                    >
                      <option value="llama-3.3-70b-versatile">Llama 3.3 70B (Groq)</option>
                      <option value="gpt-4o">GPT-4o (OpenAI)</option>
                      <option value="gpt-4o-mini">GPT-4o Mini (OpenAI)</option>
                      <option value="claude-3-5-sonnet-20241022">Claude 3.5 Sonnet</option>
                    </select>
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-[12px] font-medium uppercase tracking-wider text-text-muted">
                      Judge prompt <span className="normal-case font-normal">(optional)</span>
                    </label>
                    <textarea
                      value={formScorerPrompt}
                      onChange={(e) => setFormScorerPrompt(e.target.value)}
                      placeholder="Rate the response quality from 0 to 1. Return JSON: {score: float, reason: string}"
                      rows={3}
                      className="w-full rounded-md border border-border bg-surface-900 px-3 py-2 text-xs font-mono text-text-primary placeholder:text-text-muted/50 focus:ring-1 focus:ring-accent focus:border-accent resize-none"
                    />
                  </div>
                </div>
              )}
            </div>

            <div className="flex items-center justify-end gap-2 border-t border-border px-5 py-4">
              <OutlineButton onClick={() => setShowCreate(false)}>Cancel</OutlineButton>
              <PrimaryButton onClick={handleCreate} disabled={creating || !formName.trim() || !formDataset}>
                {creating ? 'Running…' : 'Run Evaluation'}
              </PrimaryButton>
            </div>
          </div>
        </div>
      )}

      </div>{/* end flex-1 */}
    </div>
  );
}

function StatusIcon({ status }: { status: string }) {
  if (status === 'completed') return <CheckCircle2 className="h-3.5 w-3.5 text-success flex-shrink-0" />;
  if (status === 'failed') return <XCircle className="h-3.5 w-3.5 text-danger flex-shrink-0" />;
  if (status === 'running') return <Loader2 className="h-3.5 w-3.5 animate-spin text-accent flex-shrink-0" />;
  return <BarChart3 className="h-3.5 w-3.5 text-text-muted flex-shrink-0" />;
}

function StatsBar({ evaluation }: { evaluation: Evaluation }) {
  const passRate = evaluation.total > 0 ? Math.round((evaluation.passed / evaluation.total) * 100) : 0;
  return (
    <div className="grid gap-3 sm:grid-cols-4">
      {[
        { label: 'Total', value: String(evaluation.total), color: 'text-text-primary' },
        { label: 'Passed', value: String(evaluation.passed), color: 'text-success' },
        { label: 'Failed', value: String(evaluation.failed), color: 'text-danger' },
        {
          label: 'Avg Score',
          value: `${Math.round(evaluation.average_score * 100)}%`,
          color: passRate >= 80 ? 'text-success' : passRate >= 50 ? 'text-warning' : 'text-danger',
        },
      ].map((item) => (
        <div key={item.label} className="ui-card px-4 py-4 text-center">
          <div className={clsx('text-[24px] font-semibold font-mono', item.color)}>{item.value}</div>
          <div className="mt-1 text-[11px] uppercase tracking-wider text-text-muted">{item.label}</div>
        </div>
      ))}
    </div>
  );
}

function ComparePanel({ result, onClose }: { result: CompareResult; onClose: () => void }) {
  return (
    <div className="ui-card overflow-hidden">
      <div className="flex items-center justify-between border-b border-border px-5 py-4">
        <div>
          <div className="text-[16px] font-semibold text-text-primary">
            {result.eval_a_name} vs {result.eval_b_name}
          </div>
          <div className="mt-1 text-[13px] text-text-secondary">
            Side-by-side score comparison across overlapping dataset examples.
          </div>
        </div>
        <OutlineButton onClick={onClose}>Close</OutlineButton>
      </div>

      <div className="grid gap-3 p-5 sm:grid-cols-3">
        <CompareStat label="B Wins" value={String(result.wins)} tone="success" />
        <CompareStat label="Ties" value={String(result.ties)} tone="neutral" />
        <CompareStat label="A Wins" value={String(result.losses)} tone="danger" />
      </div>

      {result.diffs.length > 0 ? (
        <div className="table-shell border-x-0 border-b-0 rounded-none">
          <div className="table-header grid-cols-[1fr_80px_80px_80px]">
            <span>Example</span>
            <span className="text-right">Score A</span>
            <span className="text-right">Score B</span>
            <span className="text-right">Delta</span>
          </div>
          <div className="max-h-72 overflow-y-auto">
            {result.diffs.map((diff) => (
              <div key={diff.example_id} className="data-row grid-cols-[1fr_80px_80px_80px] text-[12px]">
                <span className="truncate font-mono text-text-secondary">{diff.example_id.slice(0, 14)}...</span>
                <span className="text-right text-text-secondary">{Math.round(diff.score_a * 100)}%</span>
                <span className="text-right text-text-secondary">{Math.round(diff.score_b * 100)}%</span>
                <span
                  className={clsx(
                    'text-right font-mono font-medium',
                    diff.delta > 0 && 'text-success',
                    diff.delta < 0 && 'text-danger',
                    diff.delta === 0 && 'text-text-muted',
                  )}
                >
                  {diff.delta > 0 ? '+' : ''}
                  {Math.round(diff.delta * 100)}%
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function CompareStat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: 'success' | 'neutral' | 'danger';
}) {
  return (
    <div
      className={clsx(
        'rounded-xl border px-4 py-4 text-center',
        tone === 'success' && 'border-success/20 bg-success/5',
        tone === 'danger' && 'border-danger/20 bg-danger/5',
        tone === 'neutral' && 'border-border bg-surface-800',
      )}
    >
      <div
        className={clsx(
          'text-[22px] font-semibold font-mono',
          tone === 'success' && 'text-success',
          tone === 'danger' && 'text-danger',
          tone === 'neutral' && 'text-text-primary',
        )}
      >
        {value}
      </div>
      <div className="mt-1 text-[11px] uppercase tracking-wider text-text-muted">{label}</div>
    </div>
  );
}
