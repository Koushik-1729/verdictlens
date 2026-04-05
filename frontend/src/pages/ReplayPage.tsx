import { useEffect, useMemo, useState } from 'react';
import { Play, RotateCcw, Search, ChevronDown, ChevronRight } from 'lucide-react';
import EmptyState from '../components/EmptyState';
import { Badge, SectionLabel } from '../components/ui';
import {
  fetchReplays,
  fetchTrace,
  fetchTraces,
  submitReplay,
  type ParentContextEntry,
  type ReplayResult,
  type ReplaySummary,
  type Span,
  type TraceDetail,
  type TraceSummary,
} from '../lib/api';
import { formatCost, formatMs, formatTokens, timeAgo } from '../lib/utils';

function isReplayable(span: Span) {
  return span.span_type === 'llm';
}

// ---------------------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------------------

const STATUS_CFG = {
  improved:  { label: 'Improved',  cls: 'bg-[var(--badge-clean-bg)] text-[var(--badge-clean-text)]' },
  degraded:  { label: 'Degraded',  cls: 'bg-[var(--badge-originator-bg)] text-[var(--badge-originator-text)]' },
  same:      { label: 'Same',      cls: 'bg-[var(--badge-ambiguous-bg)] text-[var(--badge-ambiguous-text)]' },
  different: { label: 'Different', cls: 'bg-[var(--badge-ambiguous-bg)] text-[var(--badge-ambiguous-text)]' },
} as const;

function StatusBadge({ status, label }: { status: ReplaySummary['status']; label?: string }) {
  const cfg = STATUS_CFG[status] ?? STATUS_CFG.different;
  return (
    <span className={`inline-flex rounded px-2 py-1 text-[11px] font-medium capitalize ${cfg.cls}`}>
      {label ?? cfg.label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Improvement score with tooltip
// ---------------------------------------------------------------------------

function ImprovementScore({ score }: { score: number | null }) {
  if (score === null) return null;
  const pct = Math.round(score * 100);
  const color = pct >= 75 ? 'text-[var(--badge-clean-text)]' : pct <= 25 ? 'text-danger' : 'text-text-secondary';
  return (
    <div className="group relative inline-flex flex-col items-center">
      <div className={`text-2xl font-bold tabular-nums ${color}`}>{pct}%</div>
      <div className="text-[10px] uppercase tracking-wide text-text-muted">Score</div>
      <div className="pointer-events-none absolute bottom-full mb-2 hidden w-56 rounded-lg border border-border bg-surface-800 p-3 text-[11px] text-text-secondary shadow-xl group-hover:block">
        <div className="font-semibold text-text-primary mb-1">How this is calculated</div>
        <div className="space-y-1">
          <div>• Error fixed (original failed → replay succeeded): <span className="text-text-primary">+75%</span></div>
          <div>• Latency improved: <span className="text-text-primary">+15%</span></div>
          <div>• Cost reduced: <span className="text-text-primary">+10%</span></div>
        </div>
        <div className="mt-2 text-text-muted">50% = same, 0% = degraded, 100% = fixed error with lower latency and cost.</div>
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
    <div className="rounded-lg border border-border bg-surface-900">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-4 py-3 text-left"
      >
        <span className="text-[12px] font-medium text-text-secondary">
          Parent Context — {chain.length} ancestor{chain.length !== 1 ? 's' : ''} injected into replay
        </span>
        {open ? <ChevronDown className="h-3.5 w-3.5 text-text-muted" /> : <ChevronRight className="h-3.5 w-3.5 text-text-muted" />}
      </button>
      {open && (
        <div className="border-t border-border divide-y divide-border">
          {chain.map((entry, i) => (
            <div key={entry.span_id} className="px-4 py-3 space-y-1">
              <div className="flex items-center gap-2">
                <span className="text-[10px] text-text-muted">#{i + 1}</span>
                <span className="font-mono text-[12px] text-text-primary">{entry.name}</span>
                <Badge variant={entry.span_type === 'llm' ? 'llm' : entry.span_type === 'agent' ? 'agent' : 'default'}>
                  {entry.span_type}
                </Badge>
                {entry.decision && (
                  <span className="text-[11px] text-text-muted">decision: {entry.decision}</span>
                )}
              </div>
              {entry.output_summary && (
                <pre className="mt-1 max-h-20 overflow-auto rounded bg-[rgb(var(--code-surface))] p-2 font-mono text-[11px] text-text-secondary">
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
// Side-by-side result cards
// ---------------------------------------------------------------------------

function MetricRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between py-1 text-[12px]">
      <span className="text-text-muted">{label}</span>
      <span className="font-medium text-text-primary">{value}</span>
    </div>
  );
}

function ResultCard({
  title,
  latency,
  cost,
  tokens,
  output,
  hasError,
  highlight,
}: {
  title: string;
  latency: number;
  cost: number;
  tokens: number;
  output: unknown;
  hasError: boolean;
  highlight?: boolean;
}) {
  return (
    <div className={`rounded-lg border p-4 ${highlight ? 'border-[var(--badge-clean-text)]/30 bg-[var(--badge-clean-bg)]/10' : 'border-border bg-surface-900'}`}>
      <div className="flex items-center justify-between mb-3">
        <span className="text-[13px] font-semibold text-text-primary">{title}</span>
        {hasError
          ? <span className="rounded px-2 py-0.5 text-[11px] bg-danger/15 text-danger">error</span>
          : <span className="rounded px-2 py-0.5 text-[11px] bg-[var(--badge-clean-bg)] text-[var(--badge-clean-text)]">success</span>
        }
      </div>
      <div className="divide-y divide-border rounded-md border border-border">
        <div className="px-3"><MetricRow label="Latency" value={formatMs(latency)} /></div>
        <div className="px-3"><MetricRow label="Cost" value={formatCost(cost)} /></div>
        <div className="px-3"><MetricRow label="Tokens" value={formatTokens(tokens)} /></div>
      </div>
      <div className="mt-3">
        <div className="text-[10px] uppercase tracking-wide text-text-muted mb-1">Output</div>
        <pre className="max-h-40 overflow-auto rounded border border-border bg-[rgb(var(--code-surface))] p-3 font-mono text-[11px] text-white whitespace-pre-wrap">
          {output == null ? '(null)' : JSON.stringify(output, null, 2)}
        </pre>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Output diff
// ---------------------------------------------------------------------------

function OutputDiff({ lines }: { lines: string[] }) {
  if (!lines.length) return null;
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wide text-text-muted mb-2">Output Diff</div>
      <pre className="overflow-auto rounded-lg border border-border bg-[rgb(var(--code-surface))] p-3 font-mono text-[11px] max-h-56">
        {lines.map((line, i) => (
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
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function ReplayPage() {
  const [traces, setTraces] = useState<TraceSummary[]>([]);
  const [search, setSearch] = useState('');
  const [traceDetail, setTraceDetail] = useState<TraceDetail | null>(null);
  const [selectedTraceId, setSelectedTraceId] = useState<string>('');
  const [selectedSpanId, setSelectedSpanId] = useState<string>('');
  const [inputText, setInputText] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<ReplayResult | null>(null);
  const [history, setHistory] = useState<ReplaySummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchTraces({ page_size: 60, status: 'error' })
      .then((res) => setTraces(res.traces))
      .catch(() => setTraces([]))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selectedTraceId) { setTraceDetail(null); setSelectedSpanId(''); return; }
    fetchTrace(selectedTraceId)
      .then((d) => { setTraceDetail(d); fetchReplays(selectedTraceId).then(setHistory).catch(() => {}); })
      .catch(() => { setTraceDetail(null); setHistory([]); });
  }, [selectedTraceId]);

  useEffect(() => {
    if (!selectedSpanId || !traceDetail) return;
    const span = traceDetail.spans.find((s) => s.span_id === selectedSpanId);
    if (!span) return;
    setInputText(
      typeof span.input === 'object' && span.input !== null
        ? JSON.stringify(span.input, null, 2)
        : JSON.stringify(span.input ?? {}, null, 2),
    );
    setResult(null);
    setError(null);
  }, [selectedSpanId, traceDetail]);

  // Auto-select first replayable span from first matching error trace
  useEffect(() => {
    if (!traces.length || selectedTraceId) return;
    const preload = async () => {
      for (const t of traces.slice(0, 5)) {
        try {
          const d = await fetchTrace(t.trace_id);
          const first = d.spans.find(isReplayable);
          if (first) {
            setTraceDetail(d); setSelectedTraceId(d.trace_id); setSelectedSpanId(first.span_id);
            fetchReplays(d.trace_id).then(setHistory).catch(() => {});
            return;
          }
        } catch { continue; }
      }
    };
    preload();
  }, [selectedTraceId, traces]);

  const selectedSpan = traceDetail?.spans.find((s) => s.span_id === selectedSpanId) ?? null;
  const replayableSpans = useMemo(() => traceDetail?.spans.filter(isReplayable) ?? [], [traceDetail]);
  const filteredTraces = useMemo(
    () => traces.filter((t) => !search || t.name.toLowerCase().includes(search.toLowerCase())),
    [traces, search],
  );

  async function runReplay() {
    if (!traceDetail || !selectedSpan) return;
    setRunning(true); setError(null);
    try {
      const parsed = JSON.parse(inputText);
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed))
        throw new Error('Replay input must be a JSON object {}');
      const r = await submitReplay(traceDetail.trace_id, selectedSpan.span_id, parsed);
      setResult(r);
      fetchReplays(traceDetail.trace_id).then(setHistory).catch(() => {});
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between border-b border-[rgb(var(--border))] px-6 py-3.5">
        <div className="flex items-center gap-2">
          <h1 className="text-[15px] font-semibold text-text-primary">Replay</h1>
          {selectedSpan && traceDetail && (
            <button
              onClick={() => { setSelectedTraceId(''); setSelectedSpanId(''); setResult(null); setError(null); }}
              className="flex items-center gap-1 text-[12px] text-text-muted hover:text-text-primary"
            >
              <RotateCcw className="h-3 w-3" /> Change trace
            </button>
          )}
        </div>
        <p className="text-[12px] text-text-muted">Re-run a broken span with edited input and compare side by side.</p>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
      {/* ── Span not yet selected — show searchable trace list ── */}
      {!selectedSpan && !loading && (
        <section className="space-y-3">
          <div className="flex items-center gap-3">
            <SectionLabel>Error Traces</SectionLabel>
            <div className="relative flex-1 max-w-xs">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-muted" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search by name…"
                className="h-8 w-full rounded-md border border-border bg-surface-900 pl-8 pr-3 text-[12px] text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-1 focus:ring-accent"
              />
            </div>
          </div>
          {filteredTraces.length === 0 ? (
            <EmptyState
              icon={<Badge variant="llm">llm</Badge>}
              title="No replayable spans yet"
              description="Errored LLM spans will appear here once a trace with an LLM call has failed."
            />
          ) : (
            <div className="ui-card overflow-hidden">
              <div className="divide-y divide-border">
                {filteredTraces.slice(0, 20).map((t) => (
                  <button
                    key={t.trace_id}
                    onClick={() => setSelectedTraceId(t.trace_id)}
                    className="grid w-full grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_100px_90px_80px] items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-surface-800"
                  >
                    <span className="truncate font-mono text-[12px] text-text-primary">{t.name}</span>
                    <span className="truncate text-[12px] text-text-muted">{timeAgo(t.start_time)}</span>
                    <span>{t.model ? <Badge variant="llm">{t.model}</Badge> : null}</span>
                    <span className="text-[12px] text-text-secondary">{formatMs(t.latency_ms)}</span>
                    <span className="text-right text-[12px] text-accent">Replay →</span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </section>
      )}

      {/* ── Span selected — editor + result ── */}
      {selectedSpan && traceDetail && (
        <>
          <div className="flex flex-wrap items-center gap-2 text-[12px] text-text-secondary">
            <Badge variant="llm">{selectedSpan.model ?? 'llm'}</Badge>
            <span className="font-mono text-text-primary">{selectedSpan.name}</span>
            <span className="text-text-muted">·</span>
            <span>{timeAgo(traceDetail.start_time)}</span>
          </div>

          <div className="grid gap-5 lg:grid-cols-[1fr_1fr]">
            {/* Left: input editor + history */}
            <div className="space-y-5">
              <div className="ui-card p-4 space-y-3">
                <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-text-muted">
                  Edit Input
                </div>
                <textarea
                  value={inputText}
                  onChange={(e) => setInputText(e.target.value)}
                  spellCheck={false}
                  className="h-72 w-full rounded-md border border-border bg-[rgb(var(--code-surface))] p-3 font-mono text-[12px] text-white caret-white focus:outline-none focus:ring-1 focus:ring-accent resize-none"
                />
                <button
                  onClick={runReplay}
                  disabled={running}
                  className="flex w-full items-center justify-center gap-2 rounded-md bg-accent px-4 py-2 text-[13px] font-medium text-white transition-colors hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {running ? (
                    <>
                      <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
                      </svg>
                      Running replay…
                    </>
                  ) : (
                    <><Play className="h-4 w-4" /> Run Replay</>
                  )}
                </button>
                {error && (
                  <div className="rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-[12px] text-danger">
                    {error}
                  </div>
                )}
              </div>

              {/* Previous replays */}
              <div className="space-y-2">
                <SectionLabel>Previous Replays</SectionLabel>
                <div className="ui-card overflow-hidden">
                  {history.length === 0 ? (
                    <div className="px-4 py-5 text-[12px] text-text-muted">No replays yet for this trace.</div>
                  ) : (
                    <div className="divide-y divide-border">
                      {history.map((item) => (
                        <div key={item.replay_span_id} className="grid grid-cols-[140px_90px_minmax(0,1fr)] items-center gap-3 px-4 py-3 text-[12px]">
                          <span className="text-text-muted">{timeAgo(item.created_at)}</span>
                          <StatusBadge status={item.status} />
                          <span className="truncate text-text-secondary">{item.note ?? item.original_span_name}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Right: span switcher + result */}
            <div className="space-y-5">
              {/* Replayable span selector */}
              <div className="space-y-2">
                <SectionLabel>Replayable Spans</SectionLabel>
                <div className="ui-card overflow-hidden">
                  {replayableSpans.map((span) => (
                    <button
                      key={span.span_id}
                      onClick={() => setSelectedSpanId(span.span_id)}
                      className={`flex w-full items-center justify-between gap-3 border-b border-border px-4 py-3 text-left transition-colors last:border-b-0 ${
                        span.span_id === selectedSpanId
                          ? 'bg-accent/10'
                          : 'hover:bg-surface-800'
                      }`}
                    >
                      <span className="min-w-0 truncate font-mono text-[12px] text-text-primary">{span.name}</span>
                      <Badge variant="llm">{span.model ?? 'llm'}</Badge>
                    </button>
                  ))}
                </div>
              </div>

              {/* Result */}
              {result && (
                <div className="space-y-4">
                  {/* Status + score */}
                  <div className={`flex items-center justify-between gap-4 rounded-lg border px-4 py-3 ${STATUS_CFG[result.status].cls} border-border`}>
                    <div>
                      <div className="text-[13px] font-bold uppercase tracking-wide">{STATUS_CFG[result.status].label}</div>
                      <div className="mt-0.5 text-[11px] opacity-80">
                        {result.status === 'improved' && 'New input fixed the failure.'}
                        {result.status === 'degraded' && 'New input introduced a new error.'}
                        {result.status === 'same' && 'Output is identical to the original.'}
                        {result.status === 'different' && 'Output changed — review the diff below.'}
                      </div>
                    </div>
                    <ImprovementScore score={result.improvement_score} />
                  </div>

                  {/* Side-by-side cards */}
                  <div className="grid grid-cols-2 gap-3">
                    <ResultCard
                      title="Original"
                      latency={result.original_latency_ms}
                      cost={result.original_cost_usd}
                      tokens={result.original_tokens}
                      output={result.original_output}
                      hasError={result.original_output == null}
                    />
                    <ResultCard
                      title="Replay"
                      latency={result.new_latency_ms}
                      cost={result.new_cost_usd}
                      tokens={result.new_tokens}
                      output={result.new_output}
                      hasError={result.new_output == null}
                      highlight={result.status === 'improved'}
                    />
                  </div>

                  {/* Parent context chain */}
                  {result.parent_context?.chain?.length ? (
                    <ParentContextPanel chain={result.parent_context.chain} />
                  ) : null}

                  {/* Output diff */}
                  <OutputDiff lines={result.output_diff} />

                  {result.note && (
                    <p className="text-[12px] italic text-text-muted">Note: {result.note}</p>
                  )}
                </div>
              )}

              {/* Placeholder before first run */}
              {!result && (
                <div className="flex h-40 items-center justify-center rounded-lg border border-dashed border-border text-[13px] text-text-muted">
                  Run a replay to see the comparison here.
                </div>
              )}
            </div>
          </div>
        </>
      )}
      </div>
    </div>
  );
}
