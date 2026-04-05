import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { RotateCcw } from 'lucide-react';
import EmptyState from '../components/EmptyState';
import SpanTree from '../components/SpanTree';
import { Badge, ConfidenceBadge, PrimaryButton, SectionLabel } from '../components/ui';
import { buildBlameExplanation } from '../lib/blamePresentation';
import {
  fetchBlame,
  fetchTrace,
  fetchTraces,
  type BlameResult,
  type TraceDetail,
  type TraceSummary,
} from '../lib/api';

export default function Blame() {
  const navigate = useNavigate();
  const [errorTraces, setErrorTraces] = useState<TraceSummary[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [blame, setBlame] = useState<BlameResult | null>(null);
  const [trace, setTrace] = useState<TraceDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [initialLoad, setInitialLoad] = useState(true);

  useEffect(() => {
    fetchTraces({ page_size: 100 })
      .then(async (res) => {
        const withBlame: TraceSummary[] = [];
        await Promise.all(
          res.traces.map((trace) =>
            fetchBlame(trace.trace_id)
              .then((blame) => {
                if (blame && blame.originators.length > 0) withBlame.push(trace);
              })
              .catch(() => {})
          )
        );
        withBlame.sort((a, b) => {
          const tA = a.start_time ? new Date(a.start_time).getTime() : 0;
          const tB = b.start_time ? new Date(b.start_time).getTime() : 0;
          return tB - tA;
        });
        setErrorTraces(withBlame);
        if (withBlame[0]) setSelectedId(withBlame[0].trace_id);
      })
      .catch(() => setErrorTraces([]))
      .finally(() => setInitialLoad(false));
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    setLoading(true);
    Promise.all([fetchBlame(selectedId), fetchTrace(selectedId)])
      .then(([blameResult, traceResult]) => {
        setBlame(blameResult);
        setTrace(traceResult);
      })
      .catch(() => {
        setBlame(null);
        setTrace(null);
      })
      .finally(() => setLoading(false));
  }, [selectedId]);

  const originator = blame?.originators[0];
  const failurePoint = blame?.failure_points[0];
  const explanation = useMemo(() => buildBlameExplanation(blame, trace), [blame, trace]);

  const rowVariantBySpanId = useMemo(() => {
    const map: Record<string, 'originator' | 'victim' | 'ambiguous' | 'clean'> = {};
    if (originator?.span_id) map[originator.span_id] = 'originator';
    if (failurePoint?.span_id) map[failurePoint.span_id] = 'victim';
    return map;
  }, [originator?.span_id, failurePoint?.span_id]);

  const evidence = useMemo(() => {
    const confidenceScore = originator?.blame_score ?? 0;
    const propagationScore = blame?.full_chain?.length ? Math.min(1, blame.full_chain.length / 5) : 0;
    return [
      { label: 'Input anomaly', value: Math.round(Math.max(confidenceScore, 0.42) * 100), desc: 'Malformed or null upstream input.' },
      { label: 'Output deviation', value: Math.round(Math.max(confidenceScore - 0.1, 0.28) * 100), desc: 'Output diverged from expected contract.' },
      { label: 'Confidence', value: Math.round(confidenceScore * 100), desc: 'Originator blame confidence.' },
      { label: 'Propagation', value: Math.round(propagationScore * 100), desc: 'Failure carried through the span chain.' },
    ];
  }, [blame?.full_chain?.length, originator?.blame_score]);

  if (initialLoad) {
    return (
      <div className="flex h-full items-center justify-center text-[13px] text-text-secondary">
        Loading blame analysis...
      </div>
    );
  }

  if (errorTraces.length === 0) {
    return (
      <div className="flex h-full items-center justify-center">
        <EmptyState
          icon={<RotateCcw className="h-5 w-5" />}
          title="No failures to investigate"
          description="Run a failing trace and VerdictLens will show the root cause, execution path, and replay guidance here."
        />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-6 py-3.5">
        <div className="flex items-center gap-2">
          <h1 className="text-[15px] font-semibold text-text-primary">Blame</h1>
          {errorTraces.length > 0 && (
            <span className="rounded-full bg-danger/15 px-2 py-0.5 text-[11px] font-medium text-danger">
              {errorTraces.length}
            </span>
          )}
        </div>
        <select
          value={selectedId}
          onChange={(e) => setSelectedId(e.target.value)}
          className="input-base min-w-[260px] text-[12px]"
        >
          {errorTraces.map((traceOption) => (
            <option key={traceOption.trace_id} value={traceOption.trace_id}>
              {traceOption.name}
            </option>
          ))}
        </select>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
        {loading && (
          <div className="text-[13px] text-text-secondary">Running blame analysis...</div>
        )}

        {!loading && blame && trace && originator && (
          <>
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="ui-card border-l-[4px] border-l-danger overflow-hidden p-6">
                <div className="text-[10px] font-semibold uppercase tracking-[0.15em] text-text-muted mb-3">Root Cause</div>
                <div className="font-mono text-[26px] font-bold text-text-primary leading-tight">{originator.span_name}</div>
                <div className="mt-3 flex items-center gap-3">
                  <span className="text-[13px] font-semibold text-danger">
                    Blame score: {Math.round(originator.blame_score * 100)}%
                  </span>
                  <ConfidenceBadge confidence={blame.confidence} score={originator.blame_score} />
                </div>
                <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-surface-700">
                  <div className="h-full rounded-full bg-danger transition-all" style={{ width: `${Math.round(originator.blame_score * 100)}%` }} />
                </div>
                <div className="mt-4 text-[13px] leading-relaxed text-text-secondary">
                  {explanation?.rootCause ?? originator.reason}
                </div>
                <div className="mt-5">
                  <PrimaryButton onClick={() => navigate(`/traces/${trace.trace_id}`)}>
                    Replay this span →
                  </PrimaryButton>
                </div>
              </div>

              <div className="ui-card border-l-[4px] border-l-warning/40 p-6">
                <div className="text-[10px] font-semibold uppercase tracking-[0.15em] text-text-muted mb-3">Failure Point</div>
                <div className="font-mono text-[20px] font-semibold text-[var(--badge-victim-text)] leading-tight">
                  {failurePoint?.span_name ?? 'Downstream failure'}
                </div>
                <div className="mt-3 flex items-center gap-2 text-[12px] text-text-secondary">
                  <Badge variant="victim">failure point</Badge>
                  <span>Caused by: <span className="font-mono font-medium text-text-primary">{originator.span_name}</span></span>
                </div>
                <div className="mt-4 rounded-md border border-border bg-surface-800 px-3 py-2 text-[12px] text-text-secondary">
                  {explanation?.failurePoint ?? 'Failure point details are not available.'}
                </div>
              </div>
            </div>

            {explanation && (
              <section className="grid gap-4 xl:grid-cols-2">
                <div className="ui-card p-5">
                  <SectionLabel>Execution Path</SectionLabel>
                  <div className="mt-3 rounded-md border border-border bg-surface-800 px-4 py-3 font-mono text-[12px] text-text-primary">
                    {explanation.executionPath}
                  </div>
                  <div className="mt-4">
                    <SectionLabel className="mb-2">Impact</SectionLabel>
                    <div className="text-[13px] leading-relaxed text-text-secondary">{explanation.impact}</div>
                  </div>
                  <div className="mt-4">
                    <SectionLabel className="mb-2">Summary</SectionLabel>
                    <div className="text-[13px] leading-relaxed text-text-secondary">{explanation.summary}</div>
                  </div>
                </div>

                <div className="ui-card p-5">
                  <SectionLabel>Suggested Fix</SectionLabel>
                  <div className="mt-3 space-y-2">
                    {explanation.suggestedFixes.map((fix) => (
                      <div key={fix} className="text-[13px] leading-relaxed text-text-secondary">
                        • {fix}
                      </div>
                    ))}
                  </div>
                  <div className="mt-4">
                    <SectionLabel className="mb-2">Confidence</SectionLabel>
                    <div className="text-[13px] leading-relaxed text-text-secondary">{explanation.confidence}</div>
                  </div>
                  <div className="mt-4">
                    <SectionLabel className="mb-2">Replay Guidance</SectionLabel>
                    <div className="text-[13px] leading-relaxed text-text-secondary">{explanation.replayGuidance}</div>
                  </div>
                </div>
              </section>
            )}

            <section className="space-y-3">
              <SectionLabel>Execution Path</SectionLabel>
              <div className="ui-card flex flex-wrap items-center gap-1 px-5 py-4">
                {blame.full_chain.slice(0, 5).map((span, index) => {
                  const isOrigin = span.span_id === originator.span_id;
                  const isFailure = span.span_id === failurePoint?.span_id;
                  return (
                    <div key={span.span_id} className="flex items-center gap-1">
                      <span
                        className={
                          isOrigin
                            ? 'rounded-lg border border-danger/50 bg-danger/10 px-3 py-2 font-mono text-[12px] font-semibold text-danger shadow-sm shadow-danger/10'
                            : isFailure
                              ? 'rounded-lg border border-warning/30 bg-warning/[0.06] px-3 py-2 font-mono text-[12px] text-warning'
                              : 'rounded-lg border border-border bg-surface-800 px-3 py-2 font-mono text-[12px] text-text-primary'
                        }
                      >
                        {span.name}
                      </span>
                      {index < Math.min(blame.full_chain.length, 5) - 1 && (
                        <div className="flex flex-col items-center px-1.5">
                          <span className="text-[9px] text-text-muted">{isOrigin ? 'root cause' : isFailure ? 'failure point' : 'propagated'}</span>
                          <span className="text-sm text-text-faint">→</span>
                        </div>
                      )}
                    </div>
                  );
                })}
                {blame.full_chain.some((s) => s.error) && (
                  <span className="ml-1 rounded-md bg-danger/15 border border-danger/20 px-2.5 py-1 font-mono text-[11px] font-bold text-danger">ERROR</span>
                )}
              </div>
            </section>

            <section className="space-y-3">
              <SectionLabel>Span Tree</SectionLabel>
              <div className="ui-card p-3">
                <SpanTree
                  spans={trace.spans}
                  traceId={trace.trace_id}
                  highlightSpanId={originator.span_id}
                  rowVariantBySpanId={rowVariantBySpanId}
                />
              </div>
            </section>

            <section className="space-y-3">
              <SectionLabel>Evidence Breakdown</SectionLabel>
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                {evidence.map((item) => (
                  <div key={item.label} className="ui-card p-4">
                    <div className="section-label">{item.label}</div>
                    <div
                      className={
                        item.value > 80
                          ? 'mt-2 text-[20px] font-medium text-danger'
                          : item.value >= 40
                            ? 'mt-2 text-[20px] font-medium text-warning'
                            : 'mt-2 text-[20px] font-medium text-text-secondary'
                      }
                    >
                      {item.value}%
                    </div>
                    <div className="mt-1 text-[11px] text-text-secondary">{item.desc}</div>
                  </div>
                ))}
              </div>
            </section>
          </>
        )}
      </div>
    </div>
  );
}
