import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Clock, DollarSign, Zap, Target, RotateCcw, ChevronDown, ChevronRight, Database, FlaskConical, ThumbsUp, ThumbsDown, MessageSquare, Trash2 } from 'lucide-react';
import clsx from 'clsx';
import { fetchTrace, fetchBlame, fetchReplays, fetchAnnotations, createAnnotation, deleteAnnotation, formatError, type TraceDetail as TraceDetailType, type BlameResult, type ReplaySummary, type Span, type Annotation } from '../lib/api';
import StatusBadge from '../components/StatusBadge';
import SpanTree from '../components/SpanTree';
import JsonViewer from '../components/JsonViewer';
import AddToDatasetModal from '../components/AddToDatasetModal';
import { Skeleton } from '../components/Skeleton';
import { buildBlameExplanation } from '../lib/blamePresentation';
import { formatMs, formatCost, formatTokens, formatDate } from '../lib/utils';

type TabKey = 'spans' | 'input' | 'output' | 'blame' | 'replays' | 'annotations';

export default function TraceDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [trace, setTrace] = useState<TraceDetailType | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>('spans');
  const [blame, setBlame] = useState<BlameResult | null>(null);
  const [blameLoading, setBlameLoading] = useState(false);
  const [blameError, setBlameError] = useState<string | null>(null);
  const [replays, setReplays] = useState<ReplaySummary[]>([]);
  const [replaysLoading, setReplaysLoading] = useState(false);
  const [showDatasetModal, setShowDatasetModal] = useState(false);
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [annotationsLoading, setAnnotationsLoading] = useState(false);
  const [thumbs, setThumbs] = useState<'up' | 'down' | null>(null);
  const [label, setLabel] = useState('');
  const [note, setNote] = useState('');
  const [savingAnnotation, setSavingAnnotation] = useState(false);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    fetchTrace(id)
      .then(setTrace)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [id]);

  useEffect(() => {
    if (!id || !trace) return;
    setBlameLoading(true);
    fetchBlame(id)
      .then(setBlame)
      .catch(() => {
        setBlame(null);
        setBlameError(null);
      })
      .finally(() => setBlameLoading(false));
  }, [id, trace?.trace_id]);

  const loadReplays = () => {
    if (!id) return;
    setReplaysLoading(true);
    fetchReplays(id)
      .then(setReplays)
      .catch(() => {})
      .finally(() => setReplaysLoading(false));
  };

  useEffect(() => {
    if (activeTab !== 'annotations' || !id) return;
    setAnnotationsLoading(true);
    fetchAnnotations(id).then(setAnnotations).catch(() => {}).finally(() => setAnnotationsLoading(false));
  }, [activeTab, id]);

  useEffect(() => {
    if (id) loadReplays();
  }, [id]);

  if (loading) {
    return (
      <div className="flex h-full flex-col">
        <div className="p-6 max-w-7xl mx-auto space-y-5 w-full">
          <Skeleton className="h-4 w-48" />
          <Skeleton className="h-7 w-64" />
          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="bg-surface-800 border border-border rounded-lg p-3">
                <Skeleton className="h-2.5 w-16 mb-2" />
                <Skeleton className="h-5 w-20" />
              </div>
            ))}
          </div>
          <Skeleton className="h-8 w-full rounded-lg" />
          <Skeleton className="h-64 w-full rounded-lg" />
        </div>
      </div>
    );
  }
  if (error || !trace) {
    return (
      <div className="flex h-full items-center justify-center flex-col text-danger">
        <p>{error ?? 'Trace not found'}</p>
        <button onClick={() => navigate('/traces')} className="mt-3 text-sm text-accent hover:underline">
          Back to traces
        </button>
      </div>
    );
  }

  const isError = trace.status === 'error';
  const hasBlame = blame !== null && blame.originators.length > 0;
  const tabs: { key: TabKey; label: string }[] = [
    { key: 'spans', label: `Spans (${trace.spans.length})` },
    { key: 'input', label: 'Input' },
    { key: 'output', label: 'Output' },
    ...((isError || hasBlame) ? [{ key: 'blame' as TabKey, label: 'Blame Analysis' }] : []),
    { key: 'replays', label: `Replays${replays.length ? ` (${replays.length})` : ''}` },
    { key: 'annotations', label: `Annotations${annotations.length ? ` (${annotations.length})` : ''}` },
  ];

  async function saveAnnotation() {
    if (!id || (!thumbs && !label && !note.trim())) return;
    setSavingAnnotation(true);
    try {
      const ann = await createAnnotation(id, { thumbs: thumbs ?? undefined, label: label || undefined, note: note.trim() || undefined });
      setAnnotations((prev) => [ann, ...prev]);
      setThumbs(null); setLabel(''); setNote('');
    } catch { /* ignore */ } finally { setSavingAnnotation(false); }
  }

  const blameSpanId = blame?.originators[0]?.span_id ?? null;

  return (
    <div className="flex h-full flex-col">
      {/* Header bar */}
      <div className="flex items-center justify-between border-b border-border px-6 py-3.5">
        <div className="min-w-0 flex-1">
          <div className="font-mono text-[14px] text-text-primary truncate">{trace.name}</div>
          <div className="font-mono text-[11px] text-text-muted truncate">{trace.trace_id}</div>
        </div>
        <div className="flex items-center gap-2 ml-4 shrink-0">
          <button
            onClick={() => setShowDatasetModal(true)}
            className="flex items-center gap-1.5 rounded-md border border-border bg-surface-800 px-3 py-1.5 text-xs font-medium text-text-secondary hover:bg-surface-700 hover:text-text-primary transition-colors"
          >
            <Database className="h-3.5 w-3.5" />
            Add to Dataset
          </button>
          <button
            onClick={() => {
              const firstSpan = trace.spans?.[0];
              const input = firstSpan?.input || '';
              const inputStr = typeof input === 'string' ? input : JSON.stringify(input);
              navigate('/playground', { state: { prompt: inputStr, model: firstSpan?.model || 'gpt-4o-mini' } });
            }}
            className="flex items-center gap-1.5 rounded-md border border-border bg-surface-800 px-3 py-1.5 text-xs font-medium text-text-secondary hover:bg-surface-700 hover:text-text-primary transition-colors"
          >
            <FlaskConical className="h-3.5 w-3.5" />
            Open in Playground
          </button>
          <StatusBadge status={trace.status} className="text-sm" />
        </div>
      </div>

      {/* Compact stats row */}
      <div className="border-b border-border px-6 py-2 flex items-center gap-4 overflow-x-auto">
        <span className="shrink-0 flex items-center gap-1.5">
          <span className="text-[11px] text-text-muted flex items-center gap-1"><Clock className="h-3 w-3" />Latency</span>
          <span className="font-mono text-[12px] text-text-primary">{formatMs(trace.latency_ms)}</span>
        </span>
        <span className="text-text-muted/40 text-[11px] shrink-0">|</span>
        <span className="shrink-0 flex items-center gap-1.5">
          <span className="text-[11px] text-text-muted flex items-center gap-1"><DollarSign className="h-3 w-3" />Cost</span>
          <span className="font-mono text-[12px] text-text-primary">{formatCost(trace.cost_usd)}</span>
        </span>
        <span className="text-text-muted/40 text-[11px] shrink-0">|</span>
        <span className="shrink-0 flex items-center gap-1.5">
          <span className="text-[11px] text-text-muted flex items-center gap-1"><Zap className="h-3 w-3" />Tokens</span>
          <span className="font-mono text-[12px] text-text-primary">{formatTokens(trace.token_usage?.total_tokens)}</span>
        </span>
        <span className="text-text-muted/40 text-[11px] shrink-0">|</span>
        <span className="shrink-0 flex items-center gap-1.5">
          <span className="text-[11px] text-text-muted">Model</span>
          <span className="font-mono text-[12px] text-text-primary">{trace.model ?? '—'}</span>
        </span>
        <span className="text-text-muted/40 text-[11px] shrink-0">|</span>
        <span className="shrink-0 flex items-center gap-1.5">
          <span className="text-[11px] text-text-muted">Framework</span>
          <span className="font-mono text-[12px] text-text-primary">{trace.framework ?? '—'}</span>
        </span>
        <span className="text-text-muted/40 text-[11px] shrink-0">|</span>
        <span className="shrink-0 flex items-center gap-1.5">
          <span className="text-[11px] text-text-muted">Time</span>
          <span className="font-mono text-[12px] text-text-primary">{formatDate(trace.start_time)}</span>
        </span>
      </div>

      {showDatasetModal && (
        <AddToDatasetModal
          traceId={trace.trace_id}
          onClose={() => setShowDatasetModal(false)}
        />
      )}

      {trace.error && (
        <div className="mx-6 mt-3 bg-danger/10 border border-danger/30 rounded-lg p-4 text-sm text-danger">
          {formatError(trace.error)}
        </div>
      )}

      {/* Tabs */}
      <div className="border-b border-border px-6 py-0 flex gap-0 overflow-x-auto">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={clsx(
              'shrink-0 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors flex items-center gap-1.5',
              activeTab === tab.key
                ? tab.key === 'blame' ? 'border-danger text-danger' : 'border-accent text-accent'
                : 'border-transparent text-text-muted hover:text-text-primary'
            )}
          >
            {tab.key === 'blame' && <Target className="h-3.5 w-3.5" />}
            {tab.key === 'replays' && <RotateCcw className="h-3.5 w-3.5" />}
            {tab.key === 'annotations' && <MessageSquare className="h-3.5 w-3.5" />}
            {tab.label}
            {tab.key === 'blame' && hasBlame && activeTab !== 'blame' && (
              <span className="ml-1 h-2 w-2 rounded-full bg-danger animate-pulse" />
            )}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        <div className="px-6 py-4 min-h-[300px]">
          {activeTab === 'spans' && <SpanTree spans={trace.spans} highlightSpanId={blameSpanId} traceId={trace.trace_id} onReplayComplete={loadReplays} />}
          {activeTab === 'input' && <JsonViewer data={trace.input} defaultOpen />}
          {activeTab === 'output' && <JsonViewer data={trace.output} defaultOpen />}
          {activeTab === 'blame' && (
            <BlamePanel blame={blame} loading={blameLoading} error={blameError} allSpans={trace.spans} />
          )}
          {activeTab === 'replays' && (
            <ReplaysPanel replays={replays} loading={replaysLoading} />
          )}
          {activeTab === 'annotations' && (
            <AnnotationsPanel
              annotations={annotations}
              loading={annotationsLoading}
              thumbs={thumbs}
              setThumbs={setThumbs}
              label={label}
              setLabel={setLabel}
              note={note}
              setNote={setNote}
              saving={savingAnnotation}
              onSave={saveAnnotation}
              onDelete={async (annId) => {
                try {
                  await deleteAnnotation(annId);
                  setAnnotations((prev) => prev.filter((a) => a.id !== annId));
                } catch { /* ignore */ }
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
}

const REPLAY_STATUS_STYLE = {
  same: 'bg-surface-600 text-text-muted',
  improved: 'bg-green-500/20 text-green-400',
  degraded: 'bg-danger/20 text-danger',
  different: 'bg-yellow-500/20 text-yellow-400',
} as const;

function ReplaysPanel({ replays, loading }: { replays: ReplaySummary[]; loading: boolean }) {
  if (loading) return <div className="text-text-muted text-sm">Loading replays...</div>;
  if (replays.length === 0) {
    return (
      <div className="text-text-muted text-sm">
        No replays yet. Click the <span className="inline-flex items-center gap-1 text-accent"><RotateCcw className="h-3 w-3" /> Replay</span> button on any span to create one.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {replays.map((r) => (
        <div key={r.replay_span_id} className="flex items-center gap-3 px-4 py-3 bg-surface-700/50 border border-border rounded-lg">
          <RotateCcw className="h-4 w-4 text-accent shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="text-sm text-text-primary font-medium">{r.original_span_name}</div>
            {r.note && <div className="text-xs text-text-muted italic mt-0.5">{r.note}</div>}
          </div>
          <span className={`text-[10px] font-bold px-2 py-0.5 rounded ${REPLAY_STATUS_STYLE[r.status]}`}>
            {r.status.toUpperCase()}
          </span>
          <span className="text-xs text-text-muted tabular-nums">
            {new Date(r.created_at).toLocaleString()}
          </span>
        </div>
      ))}
    </div>
  );
}

function BlamePanel({ blame, loading, error, allSpans }: {
  blame: BlameResult | null; loading: boolean; error: string | null; allSpans?: Span[];
}) {
  const [showTechnical, setShowTechnical] = useState(false);

  if (loading) {
    return <div className="text-text-muted text-sm">Running blame analysis...</div>;
  }
  if (error) {
    return <div className="text-text-muted text-sm">{error}</div>;
  }
  if (!blame) {
    return <div className="text-text-muted text-sm">No blame data available.</div>;
  }

  const rc = blame.originators[0];
  if (!rc) {
    return <div className="text-text-muted text-sm">No primary root cause found in blame data.</div>;
  }

  const scorePct = Math.round(rc.blame_score * 100);
  const explanation = buildBlameExplanation(blame, null, allSpans);

  const chainSpanIds = new Set(blame.full_chain.map(s => s.span_id));
  const extraSpans = (allSpans ?? []).filter(s => !chainSpanIds.has(s.span_id));
  const allCascadeSpans = [...blame.full_chain, ...extraSpans];
  const totalSpanCount = allSpans?.length ?? blame.full_chain.length;

  return (
    <div className="space-y-6">
      <div className="border-l-[4px] border-l-danger bg-error-surface rounded-r-lg p-6">
        <div className="text-[10px] text-text-muted uppercase tracking-[0.15em] font-semibold mb-3">
          Root Cause
        </div>
        <div className="text-[26px] font-bold text-text-primary font-mono leading-tight">{rc.span_name}</div>
        <div className="mt-2 flex items-center gap-3">
          <span className="text-[13px] font-semibold text-danger">Blame score: {scorePct}%</span>
          <div className="h-1.5 w-24 overflow-hidden rounded-full bg-surface-700">
            <div className="h-full rounded-full bg-danger transition-all" style={{ width: `${scorePct}%` }} />
          </div>
        </div>
        <p className="mt-3 text-[13px] text-text-secondary leading-relaxed">{explanation?.rootCause ?? rc.reason}</p>
      </div>

      {explanation && (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="rounded-lg border border-border bg-surface-800 p-5">
            <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-3">
              Failure Point
            </h3>
            <div className="text-[13px] leading-relaxed text-text-secondary">{explanation.failurePoint}</div>

            <h3 className="mt-5 text-xs font-semibold text-text-muted uppercase tracking-wider mb-3">
              Execution Path
            </h3>
            <div className="rounded-md border border-border bg-surface-900 px-3 py-3 font-mono text-[12px] text-text-primary">
              {explanation.executionPath}
            </div>

            <h3 className="mt-5 text-xs font-semibold text-text-muted uppercase tracking-wider mb-3">
              Impact
            </h3>
            <div className="text-[13px] leading-relaxed text-text-secondary">{explanation.impact}</div>
          </div>

          <div className="rounded-lg border border-border bg-surface-800 p-5">
            <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-3">
              Summary
            </h3>
            <div className="text-[13px] leading-relaxed text-text-secondary">{explanation.summary}</div>

            <h3 className="mt-5 text-xs font-semibold text-text-muted uppercase tracking-wider mb-3">
              Suggested Fix
            </h3>
            <div className="space-y-2">
              {explanation.suggestedFixes.map((fix) => (
                <div key={fix} className="text-[13px] leading-relaxed text-text-secondary">
                  • {fix}
                </div>
              ))}
            </div>

            <h3 className="mt-5 text-xs font-semibold text-text-muted uppercase tracking-wider mb-3">
              Confidence
            </h3>
            <div className="text-[13px] leading-relaxed text-text-secondary">{explanation.confidence}</div>

            <h3 className="mt-5 text-xs font-semibold text-text-muted uppercase tracking-wider mb-3">
              Replay Guidance
            </h3>
            <div className="text-[13px] leading-relaxed text-text-secondary">{explanation.replayGuidance}</div>
          </div>
        </div>
      )}

      {/* Failure Cascade — expandable span cards for ALL spans */}
      <div>
        <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-4">
          Execution Path
        </h3>
        <div className="space-y-0">
          {allCascadeSpans.map((span, i) => {
            const isRoot = span.span_id === rc.span_id;
            const hasError = !!span.error;
            const inBlameChain = chainSpanIds.has(span.span_id);
            const nextLabel = i < allCascadeSpans.length - 1
              ? isRoot
                ? 'passed bad output to →'
                : hasError
                ? 'caused failure in →'
                : inBlameChain
                ? 'triggered →'
                : undefined
              : undefined;

            return (
              <BlameCascadeStep
                key={span.span_id}
                span={span}
                isRootCause={isRoot}
                isLast={i === allCascadeSpans.length - 1}
                hasError={hasError}
                inBlameChain={inBlameChain}
                nextLabel={nextLabel}
              />
            );
          })}
        </div>
      </div>

      {/* Evidence breakdown — matches standalone Blame page */}
      <div>
        <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-3">
          Evidence breakdown
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <BlameEvidenceCard label="Input anomaly" score={rc.blame_score > 0.5 ? 1.0 : 0.3} description="Input was null or malformed" />
          <BlameEvidenceCard label="Output deviation" score={rc.blame_score > 0.6 ? 1.0 : 0.5} description="Output was null when value expected" />
          <BlameEvidenceCard label="Confidence" score={1.0 - rc.blame_score} description="Agent confidence at decision time" isConfidence />
          <BlameEvidenceCard label="Propagation" score={blame.full_chain.filter(s => s.error).length > 1 ? 1.0 : 0.5} description="Output fed directly into error span" />
        </div>
      </div>

      {/* Technical details (collapsed) */}
      <div>
        <button
          onClick={() => setShowTechnical(!showTechnical)}
          className="text-[11px] text-text-muted hover:text-text-secondary transition-colors"
        >
          {showTechnical ? '▾' : '▸'} Technical details ({totalSpanCount} spans)
        </button>
        {showTechnical && (
          <div className="mt-2 bg-surface-800 border border-border rounded-md px-3 py-2 text-xs text-text-muted font-mono space-y-0.5">
            <div>root_cause_span: {rc.span_id}</div>
            <div>blame_score: {rc.blame_score.toFixed(4)}</div>
            <div>chain_length: {blame.full_chain.length}</div>
            <div>total_spans: {totalSpanCount}</div>
          </div>
        )}
      </div>
    </div>
  );
}

function BlameCascadeStep({ span, isRootCause, isLast, hasError, inBlameChain, nextLabel }: {
  span: Span; isRootCause: boolean; isLast: boolean; hasError: boolean; inBlameChain: boolean; nextLabel?: string;
}) {
  const [expanded, setExpanded] = useState(false);

  const badge = isRootCause ? 'ROOT CAUSE' : hasError ? 'FAILURE POINT' : !inBlameChain ? 'CLEAN' : 'PROPAGATED';
  const badgeColor = isRootCause
    ? 'bg-danger/20 text-danger border border-danger/30'
    : hasError
    ? 'bg-danger/10 text-danger'
    : !inBlameChain
    ? 'bg-surface-700 text-text-muted'
    : 'bg-warning/10 text-warning';

  return (
    <div>
      <div
        className={clsx(
          'rounded-lg p-4 cursor-pointer transition-all duration-100',
          isRootCause
            ? 'border border-danger/40 bg-error-surface hover:border-danger/60'
            : hasError
            ? 'border border-border bg-error-surface/50 hover:bg-error-surface'
            : 'border border-border bg-surface-800 hover:bg-surface-700/50'
        )}
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-2 mb-2">
          {expanded ? <ChevronDown className="h-3.5 w-3.5 text-text-muted" /> : <ChevronRight className="h-3.5 w-3.5 text-text-muted" />}
          <span className="text-sm font-semibold text-text-primary font-mono">{span.name}</span>
          <span className={clsx('text-[9px] font-bold px-2 py-0.5 rounded-md uppercase', badgeColor)}>{badge}</span>
          {span.model && (
            <span className="ml-auto rounded border border-border/50 bg-surface-900 px-1.5 py-0.5 text-[10px] font-mono text-text-muted">{span.model}</span>
          )}
        </div>

        {span.decision && (
          <div className="text-xs text-text-secondary mb-1 ml-5">
            Decision: "{span.decision}"
          </div>
        )}

        {span.output === null && (
          <div className="text-xs font-mono ml-5 mb-1">
            Output: <span className="text-danger font-semibold">null</span>
          </div>
        )}

        {span.error && (
          <div className="text-xs text-danger font-mono ml-5 mb-1 truncate max-w-lg">
            Error: {formatError(span.error)}
          </div>
        )}

        {span.confidence_score != null && (
          <div className="text-xs text-text-secondary ml-5">
            Confidence: <span className={span.confidence_score < 0.5 ? 'text-warning font-medium' : 'text-success'}>
              {span.confidence_score.toFixed(2)}
            </span>
            {span.confidence_score < 0.5 && <span className="text-warning text-[10px] ml-1">low confidence</span>}
          </div>
        )}

        {expanded && (
          <div className="mt-3 ml-5 space-y-2 border-t border-border pt-3">
            {span.input != null && (
              <div>
                <div className="text-[10px] text-text-muted uppercase tracking-wider mb-1">Input</div>
                <JsonViewer data={span.input} defaultOpen />
              </div>
            )}
            {span.output != null && (
              <div>
                <div className="text-[10px] text-text-muted uppercase tracking-wider mb-1">Output</div>
                <JsonViewer data={span.output} defaultOpen />
              </div>
            )}
          </div>
        )}
      </div>

      {!isLast && nextLabel && (
        <div className="flex items-center gap-2 py-2 pl-6">
          <div className="w-px h-4 bg-danger/30" />
          <span className="text-[10px] text-text-muted italic">{nextLabel}</span>
        </div>
      )}
      {!isLast && !nextLabel && (
        <div className="pl-6 py-1">
          <div className="w-px h-3 bg-border" />
        </div>
      )}
    </div>
  );
}

function BlameEvidenceCard({ label, score, description, isConfidence }: {
  label: string; score: number; description: string; isConfidence?: boolean;
}) {
  const pct = Math.round(score * 100);
  const color = isConfidence
    ? score > 0.6 ? 'text-success' : 'text-warning'
    : score > 0.7 ? 'text-danger' : score > 0.4 ? 'text-warning' : 'text-success';
  const barColor = isConfidence
    ? score > 0.6 ? 'bg-success' : 'bg-warning'
    : score > 0.7 ? 'bg-danger' : score > 0.4 ? 'bg-warning' : 'bg-success';

  return (
    <div className="group bg-surface-800 border border-border rounded-lg p-4 transition-colors hover:border-surface-500">
      <div className="text-[10px] font-semibold text-text-muted uppercase tracking-wider mb-2">{label}</div>
      <div className={clsx('text-[22px] font-bold tabular-nums', color)}>
        {isConfidence ? score.toFixed(2) : pct + '%'}
      </div>
      <div className="w-full h-1.5 bg-surface-700 rounded-full mt-2 mb-2 overflow-hidden">
        <div className={clsx('h-full rounded-full transition-all', barColor)} style={{ width: `${pct}%` }} />
      </div>
      <div className="text-[11px] text-text-muted leading-relaxed">{description}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Annotations Panel
// ---------------------------------------------------------------------------

const LABEL_OPTIONS = ['', 'correct', 'hallucination', 'needs_review', 'off_topic', 'unsafe'] as const;

const LABEL_STYLE: Record<string, string> = {
  correct: 'bg-green-500/20 text-green-400',
  hallucination: 'bg-danger/20 text-danger',
  needs_review: 'bg-yellow-500/20 text-yellow-400',
  off_topic: 'bg-surface-600 text-text-muted',
  unsafe: 'bg-red-700/30 text-red-400',
};

function AnnotationsPanel({
  annotations,
  loading,
  thumbs,
  setThumbs,
  label,
  setLabel,
  note,
  setNote,
  saving,
  onSave,
  onDelete,
}: {
  annotations: Annotation[];
  loading: boolean;
  thumbs: 'up' | 'down' | null;
  setThumbs: (v: 'up' | 'down' | null) => void;
  label: string;
  setLabel: (v: string) => void;
  note: string;
  setNote: (v: string) => void;
  saving: boolean;
  onSave: () => void;
  onDelete: (id: string) => void;
}) {
  const canSubmit = !saving && (!!thumbs || !!label || !!note.trim());

  return (
    <div className="space-y-6 max-w-2xl">
      {/* Form */}
      <div className="rounded-lg border border-border bg-surface-800 p-5 space-y-4">
        <div className="text-[10px] font-semibold text-text-muted uppercase tracking-wider">Add Annotation</div>

        {/* Thumbs toggle */}
        <div className="flex items-center gap-3">
          <button
            onClick={() => setThumbs(thumbs === 'up' ? null : 'up')}
            className={clsx(
              'flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors',
              thumbs === 'up'
                ? 'border-green-500 bg-green-500/20 text-green-400'
                : 'border-border bg-surface-700 text-text-muted hover:text-text-primary'
            )}
          >
            <ThumbsUp className="h-3.5 w-3.5" />
            Good
          </button>
          <button
            onClick={() => setThumbs(thumbs === 'down' ? null : 'down')}
            className={clsx(
              'flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors',
              thumbs === 'down'
                ? 'border-danger bg-danger/20 text-danger'
                : 'border-border bg-surface-700 text-text-muted hover:text-text-primary'
            )}
          >
            <ThumbsDown className="h-3.5 w-3.5" />
            Bad
          </button>
        </div>

        {/* Label dropdown */}
        <div>
          <label className="block text-[11px] text-text-muted mb-1">Label</label>
          <select
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            className="w-full rounded-md border border-border bg-surface-900 px-3 py-1.5 text-sm text-text-primary focus:outline-none focus:border-accent"
          >
            {LABEL_OPTIONS.map((opt) => (
              <option key={opt} value={opt}>{opt || '— none —'}</option>
            ))}
          </select>
        </div>

        {/* Note textarea */}
        <div>
          <label className="block text-[11px] text-text-muted mb-1">Note</label>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={3}
            placeholder="Add a note..."
            className="w-full rounded-md border border-border bg-surface-900 px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent resize-none"
          />
        </div>

        {/* Submit */}
        <button
          onClick={onSave}
          disabled={!canSubmit}
          className={clsx(
            'rounded-md px-4 py-1.5 text-sm font-medium transition-colors',
            canSubmit
              ? 'bg-accent text-white hover:bg-accent/80'
              : 'bg-surface-700 text-text-muted cursor-not-allowed'
          )}
        >
          {saving ? 'Saving\u2026' : 'Submit'}
        </button>
      </div>

      {/* Existing annotations */}
      {loading ? (
        <div className="text-text-muted text-sm">Loading annotations...</div>
      ) : annotations.length === 0 ? (
        <div className="text-text-muted text-sm">No annotations yet. Add one above.</div>
      ) : (
        <div className="space-y-2">
          {annotations.map((ann) => (
            <div key={ann.id} className="flex items-start gap-3 px-4 py-3 bg-surface-700/50 border border-border rounded-lg">
              <div className="shrink-0 mt-0.5">
                {ann.thumbs === 'up' && <ThumbsUp className="h-4 w-4 text-green-400" />}
                {ann.thumbs === 'down' && <ThumbsDown className="h-4 w-4 text-danger" />}
                {!ann.thumbs && <MessageSquare className="h-4 w-4 text-text-muted" />}
              </div>
              <div className="flex-1 min-w-0 space-y-1">
                <div className="flex items-center gap-2 flex-wrap">
                  {ann.label && (
                    <span className={clsx('text-[10px] font-bold px-2 py-0.5 rounded', LABEL_STYLE[ann.label] ?? 'bg-surface-600 text-text-muted')}>
                      {ann.label.replace(/_/g, ' ').toUpperCase()}
                    </span>
                  )}
                  <span className="text-[11px] text-text-muted tabular-nums">
                    {new Date(ann.created_at).toLocaleString()}
                  </span>
                </div>
                {ann.note && <div className="text-sm text-text-secondary">{ann.note}</div>}
              </div>
              <button
                onClick={() => onDelete(ann.id)}
                className="shrink-0 text-text-muted hover:text-danger transition-colors"
                title="Delete annotation"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
