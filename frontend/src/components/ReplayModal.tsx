import { useState } from 'react';
import { X, Play, AlertCircle, CheckCircle, ArrowRight, Minus, ChevronDown, ChevronRight } from 'lucide-react';
import { submitReplay, type ParentContextEntry, type Span, type ReplayResult } from '../lib/api';
import { formatMs, formatCost, formatTokens } from '../lib/utils';

interface Props {
  span: Span;
  traceId: string;
  onClose: () => void;
  onReplayComplete?: () => void;
}

const STATUS_CONFIG = {
  same:      { label: 'SAME',      color: 'text-text-muted',   bg: 'bg-surface-700',     icon: Minus },
  improved:  { label: 'IMPROVED',  color: 'text-[var(--badge-clean-text)]',  bg: 'bg-[var(--badge-clean-bg)]',  icon: CheckCircle },
  degraded:  { label: 'DEGRADED',  color: 'text-danger',       bg: 'bg-danger/10',        icon: AlertCircle },
  different: { label: 'DIFFERENT', color: 'text-yellow-400',   bg: 'bg-yellow-500/10',    icon: ArrowRight },
} as const;

// ---------------------------------------------------------------------------
// Improvement score tooltip
// ---------------------------------------------------------------------------

function ImprovementScore({ score }: { score: number | null }) {
  if (score === null) return null;
  const pct = Math.round(score * 100);
  const color = pct >= 75 ? 'text-[var(--badge-clean-text)]' : pct <= 25 ? 'text-danger' : 'text-text-primary';
  return (
    <div className="group relative ml-auto flex flex-col items-end">
      <div className={`text-2xl font-bold tabular-nums ${color}`}>{pct}%</div>
      <div className="text-[10px] uppercase tracking-wide text-text-muted">Score</div>
      <div className="pointer-events-none absolute right-0 top-full mt-2 hidden w-56 rounded-lg border border-border bg-surface-800 p-3 text-[11px] text-text-secondary shadow-xl group-hover:block z-10">
        <div className="font-semibold text-text-primary mb-1">How this is calculated</div>
        <div className="space-y-1">
          <div>• Error fixed: <span className="text-text-primary">+75%</span></div>
          <div>• Latency improved: <span className="text-text-primary">+15%</span></div>
          <div>• Cost reduced: <span className="text-text-primary">+10%</span></div>
        </div>
        <div className="mt-2 text-text-muted">50% = same output, 0% = degraded, 100% = fixed with lower latency &amp; cost.</div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Parent context chain
// ---------------------------------------------------------------------------

function ParentContextPanel({ chain }: { chain: ParentContextEntry[] }) {
  const [open, setOpen] = useState(false);
  if (!chain.length) return null;
  return (
    <div className="rounded-lg border border-border bg-surface-900 text-[12px]">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-3 py-2.5 text-left"
      >
        <span className="text-text-secondary">
          Parent Context — {chain.length} ancestor{chain.length !== 1 ? 's' : ''} injected
        </span>
        {open ? <ChevronDown className="h-3.5 w-3.5 text-text-muted" /> : <ChevronRight className="h-3.5 w-3.5 text-text-muted" />}
      </button>
      {open && (
        <div className="border-t border-border divide-y divide-border">
          {chain.map((entry, i) => (
            <div key={entry.span_id} className="px-3 py-2.5 space-y-1">
              <div className="flex items-center gap-2">
                <span className="text-[10px] text-text-muted">#{i + 1}</span>
                <span className="font-mono text-text-primary">{entry.name}</span>
                <span className="rounded px-1.5 py-0.5 text-[10px] bg-surface-700 text-text-muted">{entry.span_type}</span>
              </div>
              {entry.output_summary && (
                <pre className="max-h-16 overflow-auto rounded bg-[rgb(var(--code-surface))] p-2 font-mono text-[10px] text-text-muted">
                  {entry.output_summary}
                </pre>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Diff view
// ---------------------------------------------------------------------------

function ReplayDiffView({ result }: { result: ReplayResult }) {
  const cfg = STATUS_CONFIG[result.status];
  const StatusIcon = cfg.icon;

  return (
    <div className="space-y-4">
      {/* Status banner */}
      <div className={`flex items-center gap-3 rounded-xl border border-border p-4 ${cfg.bg}`}>
        <StatusIcon className={`h-5 w-5 flex-shrink-0 ${cfg.color}`} />
        <div className="flex-1 min-w-0">
          <div className={`text-sm font-bold ${cfg.color}`}>{cfg.label}</div>
          <div className="text-xs text-text-muted mt-0.5">
            {result.status === 'improved'  && 'New input produced successful output where original failed.'}
            {result.status === 'degraded'  && 'New input caused an error — original was successful.'}
            {result.status === 'same'      && 'LLM returned identical output to the original.'}
            {result.status === 'different' && 'LLM returned different output — review the diff below.'}
          </div>
        </div>
        <ImprovementScore score={result.improvement_score} />
      </div>

      {/* Side-by-side metrics + output */}
      <div className="grid grid-cols-2 gap-3">
        {[
          {
            title: 'Original',
            latency: result.original_latency_ms,
            cost: result.original_cost_usd,
            tokens: result.original_tokens,
            input: result.original_input,
            output: result.original_output,
          },
          {
            title: 'Replay',
            latency: result.new_latency_ms,
            cost: result.new_cost_usd,
            tokens: result.new_tokens,
            input: result.new_input,
            output: result.new_output,
          },
        ].map((side) => (
          <div key={side.title} className="rounded-lg border border-border bg-surface-800 p-3 space-y-2">
            <div className="text-[11px] font-semibold uppercase text-text-muted">{side.title}</div>
            <div className="divide-y divide-border rounded border border-border text-[11px]">
              <div className="flex justify-between px-2 py-1">
                <span className="text-text-muted">Latency</span>
                <span className="text-text-primary">{formatMs(side.latency)}</span>
              </div>
              <div className="flex justify-between px-2 py-1">
                <span className="text-text-muted">Cost</span>
                <span className="text-text-primary">{formatCost(side.cost)}</span>
              </div>
              <div className="flex justify-between px-2 py-1">
                <span className="text-text-muted">Tokens</span>
                <span className="text-text-primary">{formatTokens(side.tokens)}</span>
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase text-text-muted mb-1">Output</div>
              <pre className="max-h-28 overflow-auto rounded bg-[rgb(var(--code-surface))] p-2 font-mono text-[10px] text-white">
                {side.output == null ? '(null)' : JSON.stringify(side.output, null, 2)}
              </pre>
            </div>
          </div>
        ))}
      </div>

      {/* Parent context */}
      {result.parent_context?.chain?.length ? (
        <ParentContextPanel chain={result.parent_context.chain} />
      ) : null}

      {/* Output diff */}
      {result.output_diff.length > 0 && (
        <div>
          <div className="text-[10px] uppercase text-text-muted font-semibold mb-1.5">Output Diff</div>
          <pre className="max-h-40 overflow-auto rounded-lg border border-border bg-[rgb(var(--code-surface))] p-3 font-mono text-[11px]">
            {result.output_diff.map((line, i) => (
              <div
                key={i}
                className={
                  line.startsWith('+') ? 'text-[var(--badge-clean-text)]' :
                  line.startsWith('-') ? 'text-danger' :
                  line.startsWith('@@') ? 'text-text-muted' :
                  'text-text-secondary'
                }
              >
                {line}
              </div>
            ))}
          </pre>
        </div>
      )}

      {result.note && (
        <p className="text-xs italic text-text-muted">Note: {result.note}</p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main modal
// ---------------------------------------------------------------------------

export default function ReplayModal({ span, traceId, onClose, onReplayComplete }: Props) {
  const initialInput =
    typeof span.input === 'object' && span.input !== null
      ? JSON.stringify(span.input, null, 2)
      : JSON.stringify(span.input ?? {}, null, 2);

  const [inputText, setInputText] = useState(initialInput);
  const [note, setNote] = useState('');
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ReplayResult | null>(null);

  function validateJson(text: string): Record<string, unknown> | null {
    try {
      const parsed = JSON.parse(text);
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        setJsonError('Input must be a JSON object {}');
        return null;
      }
      setJsonError(null);
      return parsed;
    } catch (e) {
      setJsonError(`Invalid JSON: ${(e as Error).message}`);
      return null;
    }
  }

  async function handleSubmit() {
    const parsed = validateJson(inputText);
    if (!parsed) return;
    setLoading(true); setError(null);
    try {
      const res = await submitReplay(traceId, span.span_id, parsed, note || undefined);
      setResult(res);
      onReplayComplete?.();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-surface-900 border border-border rounded-xl shadow-2xl w-full max-w-3xl max-h-[90vh] overflow-hidden flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border flex-shrink-0">
          <div>
            <h2 className="text-base font-semibold text-text-primary">
              {result ? 'Replay Result' : 'Replay Span'}
            </h2>
            <p className="text-xs text-text-muted mt-0.5">{span.name}</p>
          </div>
          <button onClick={onClose} className="text-text-muted hover:text-text-primary transition-colors">
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {!result ? (
            <>
              <div>
                <label className="block text-xs font-semibold uppercase text-text-muted mb-2">
                  Edit Input
                </label>
                <textarea
                  value={inputText}
                  onChange={(e) => { setInputText(e.target.value); if (jsonError) validateJson(e.target.value); }}
                  className="w-full h-48 rounded-lg border border-border bg-[rgb(var(--code-surface))] p-3 text-sm font-mono text-white caret-white focus:outline-none focus:ring-2 focus:ring-accent/50 resize-y"
                  spellCheck={false}
                />
                {jsonError && (
                  <p className="text-xs text-danger mt-1 flex items-center gap-1">
                    <AlertCircle className="h-3 w-3 flex-shrink-0" /> {jsonError}
                  </p>
                )}
              </div>

              <div>
                <label className="block text-xs font-semibold uppercase text-text-muted mb-2">
                  Note <span className="font-normal normal-case">(optional)</span>
                </label>
                <input
                  type="text"
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="What are you testing?"
                  className="w-full rounded-lg border border-border bg-surface-800 px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-accent/50"
                />
              </div>

              {error && (
                <div className="text-sm text-danger bg-danger/10 border border-danger/30 rounded-lg p-3">
                  {error}
                </div>
              )}
            </>
          ) : (
            <ReplayDiffView result={result} />
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-5 py-4 border-t border-border flex-shrink-0">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-text-muted hover:text-text-primary transition-colors"
          >
            {result ? 'Close' : 'Cancel'}
          </button>
          {!result && (
            <button
              onClick={handleSubmit}
              disabled={loading || !!jsonError}
              className="flex items-center gap-2 px-4 py-2 text-sm font-medium bg-accent text-white rounded-lg hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? (
                <>
                  <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
                  </svg>
                  Running…
                </>
              ) : (
                <><Play className="h-3.5 w-3.5" /> Run Replay</>
              )}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
