import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import FailureCard from '../components/FailureCard';
import { DashboardSkeleton } from '../components/Skeleton';
import { LatencyBar, OutlineButton, SectionLabel, StatusDot } from '../components/ui';
import {
  fetchBlame,
  fetchMetrics,
  fetchTraces,
  type BlameResult,
  type Metrics,
  type TraceSummary,
} from '../lib/api';
import { formatCost, formatMs, formatPct, timeAgo } from '../lib/utils';

export default function MonitoringOverview() {
  const navigate = useNavigate();
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [recent, setRecent] = useState<TraceSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [blameResults, setBlameResults] = useState<Record<string, BlameResult | null>>({});

  useEffect(() => {
    setLoading(true);
    Promise.all([fetchMetrics(1), fetchTraces({ page_size: 30 })])
      .then(([metricData, traceData]) => {
        setMetrics(metricData);
        setRecent(traceData.traces);
        traceData.traces.slice(0, 15).forEach((trace) => {
          fetchBlame(trace.trace_id)
            .then((blame) => setBlameResults((prev) => ({ ...prev, [trace.trace_id]: blame })))
            .catch(() => setBlameResults((prev) => ({ ...prev, [trace.trace_id]: null })));
        });
      })
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, []);

  const issueTraces = useMemo(
    () =>
      recent.filter(
        (trace) => trace.status === 'error' || (blameResults[trace.trace_id]?.originators?.length ?? 0) > 0,
      ),
    [recent, blameResults],
  );

  if (loading) return <DashboardSkeleton />;
  if (error || !metrics) {
    return (
      <div className="flex h-full items-center justify-center text-[13px] text-danger">
        {error ?? 'Failed to load monitoring overview'}
      </div>
    );
  }

  const blamedCount = issueTraces.filter((trace) => blameResults[trace.trace_id]?.originators?.length).length;
  const avgConfidence = issueTraces.length
    ? issueTraces.reduce((sum, trace) => sum + (blameResults[trace.trace_id]?.originators?.[0]?.blame_score ?? 0), 0) / issueTraces.length
    : 0;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <p className="text-[12px] text-text-muted">Blame-first snapshot of failures, traces, and replay opportunities.</p>
        <OutlineButton onClick={() => navigate('/traces')}>View all traces</OutlineButton>
      </div>

      {issueTraces.length > 0 && (
        <div className="flex items-center justify-between rounded-lg border border-danger/20 bg-danger/[0.06] px-4 py-2.5 text-[13px] text-danger">
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-danger animate-pulse" />
            <span className="font-medium">{issueTraces.length} issue{issueTraces.length !== 1 ? 's' : ''}</span>
            <span className="text-danger/70">need attention</span>
          </div>
          <button onClick={() => navigate('/blame')} className="font-medium transition-colors hover:text-text-primary hover:underline">
            Open blame analysis →
          </button>
        </div>
      )}

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <div className="ui-card group relative overflow-hidden p-5 transition-colors hover:border-accent/30">
          <div className="text-[11px] font-medium uppercase tracking-wider text-text-muted">Total traces</div>
          <div className="mt-2 text-[28px] font-bold tabular-nums text-text-primary">{metrics.total_traces.toLocaleString()}</div>
          <div className="absolute -right-3 -top-3 h-16 w-16 rounded-full bg-accent/[0.04] transition-transform group-hover:scale-125" />
        </div>
        <div className="ui-card group relative overflow-hidden p-5 transition-colors hover:border-danger/30">
          <div className="text-[11px] font-medium uppercase tracking-wider text-text-muted">Issues detected</div>
          <div className="mt-2 text-[28px] font-bold tabular-nums text-danger">{issueTraces.length}</div>
          <div className="absolute -right-3 -top-3 h-16 w-16 rounded-full bg-danger/[0.06] transition-transform group-hover:scale-125" />
        </div>
        <div className="ui-card group relative overflow-hidden p-5 transition-colors hover:border-success/30">
          <div className="text-[11px] font-medium uppercase tracking-wider text-text-muted">Blame assigned</div>
          <div className="mt-2 text-[28px] font-bold tabular-nums text-text-primary">
            {blamedCount}<span className="text-[16px] font-normal text-text-muted"> / {issueTraces.length}</span>
          </div>
          <div className="absolute -right-3 -top-3 h-16 w-16 rounded-full bg-success/[0.04] transition-transform group-hover:scale-125" />
        </div>
        <div className="ui-card group relative overflow-hidden p-5 transition-colors hover:border-warning/30">
          <div className="text-[11px] font-medium uppercase tracking-wider text-text-muted">Avg confidence</div>
          <div className="mt-2 text-[28px] font-bold tabular-nums text-text-primary">{formatPct(avgConfidence)}</div>
          <div className="absolute -right-3 -top-3 h-16 w-16 rounded-full bg-warning/[0.04] transition-transform group-hover:scale-125" />
        </div>
      </section>

      <section className="ui-card overflow-hidden">
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <span className="text-[12px] font-semibold uppercase tracking-wider text-text-muted">Active issues</span>
          {issueTraces.length > 5 && (
            <button onClick={() => navigate('/blame')} className="text-[11px] text-accent transition-colors hover:text-accent-hover">
              View all →
            </button>
          )}
        </div>
        {issueTraces.length === 0 ? (
          <div className="px-5 py-10 text-center">
            <div className="text-[14px] font-medium text-text-primary">All clear</div>
            <div className="mt-1 text-[12px] text-text-secondary">
              No failures or degraded traces detected. New issues will appear here automatically.
            </div>
          </div>
        ) : (
          <div className="divide-y divide-border">
            {issueTraces.slice(0, 5).map((trace) => (
              <FailureCard
                key={trace.trace_id}
                trace={trace}
                blame={blameResults[trace.trace_id]}
                blameLoading={!(trace.trace_id in blameResults)}
              />
            ))}
          </div>
        )}
      </section>

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <SectionLabel>Recent Traces</SectionLabel>
          <button
            onClick={() => navigate('/traces')}
            className="text-[12px] text-text-secondary transition-colors hover:text-text-primary"
          >
            View all traces →
          </button>
        </div>

        <div className="table-shell">
          <div className="table-header grid w-full grid-cols-[minmax(0,1.8fr)_140px_60px_90px_80px_90px]">
            <span>Name</span>
            <span>Model</span>
            <span>Spans</span>
            <span>Latency</span>
            <span>Cost</span>
            <span>Time</span>
          </div>
          {recent.slice(0, 8).map((trace) => {
            const traceBlame = blameResults[trace.trace_id];
            const hasIssue = trace.status === 'error' || (traceBlame?.originators?.length ?? 0) > 0;

            return (
              <button
                key={trace.trace_id}
                onClick={() => navigate(`/traces/${trace.trace_id}`)}
                className={`data-row grid w-full grid-cols-[minmax(0,1.8fr)_140px_60px_90px_80px_90px] items-center text-left transition-all duration-100 hover:bg-accent/[0.04] ${hasIssue ? 'border-l-[3px] border-l-danger' : ''}`}
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <StatusDot status={trace.status === 'error' ? 'error' : hasIssue ? 'warning' : 'success'} />
                    <span className="truncate font-mono text-[13px] font-medium text-text-primary">{trace.name}</span>
                  </div>
                  {trace.error && (
                    <div className="mt-1 truncate text-[11px] text-danger">
                      {String(typeof trace.error === 'string' ? trace.error : trace.error.message)}
                    </div>
                  )}
                </div>
                <div className="min-w-0">
                  {trace.model ? (
                    <span className="inline-flex max-w-[130px] items-center rounded border border-border/60 bg-surface-800/80 px-2 py-0.5 font-mono text-[10px] text-text-secondary">
                      <span className="truncate">{trace.model}</span>
                    </span>
                  ) : (
                    <span className="text-[11px] text-text-faint">—</span>
                  )}
                </div>
                <span className="font-mono text-[12px] text-text-secondary tabular-nums">{trace.span_count}</span>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[12px] text-text-secondary tabular-nums">{formatMs(trace.latency_ms)}</span>
                  <LatencyBar ms={trace.latency_ms} width={40} />
                </div>
                <span className="font-mono text-[12px] text-text-secondary tabular-nums">{formatCost(trace.cost_usd)}</span>
                <span className="text-[11px] text-text-muted">{timeAgo(trace.start_time)}</span>
              </button>
            );
          })}
        </div>
      </section>
    </div>
  );
}
