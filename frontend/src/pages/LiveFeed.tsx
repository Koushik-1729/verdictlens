import { useEffect, useState, type ReactNode } from 'react';
import { Pause, Play, Trash2, TrendingDown, TrendingUp } from 'lucide-react';
import PeekPanel from '../components/PeekPanel';
import EmptyState from '../components/EmptyState';
import { Badge, OutlineButton, SectionLabel, StatusDot } from '../components/ui';
import { useLiveTraces } from '../lib/useWebSocket';
import { formatCost, formatMs, formatTime, timeSinceMs } from '../lib/utils';

export default function LiveFeed() {
  const { traces, connected, clear } = useLiveTraces(500);
  const [paused, setPaused] = useState(false);
  const [peekId, setPeekId] = useState<string | null>(null);
  const [pauseSnapshot, setPauseSnapshot] = useState<typeof traces>([]);
  const [newCount, setNewCount] = useState(0);

  useEffect(() => {
    if (paused) setNewCount((count) => count + 1);
  }, [paused, traces.length]);

  const displayed = paused ? pauseSnapshot : traces;
  const recentWindow = displayed.slice(0, 30);
  const rollingCost = recentWindow.reduce((sum, trace) => sum + (trace.cost_usd ?? 0), 0);
  const errorRate = recentWindow.length ? recentWindow.filter((trace) => trace.status === 'error').length / recentWindow.length : 0;
  const tracesPerMinute = recentWindow.length;
  const mostActiveAgent = recentWindow[0]?.name ?? '—';

  function togglePause() {
    if (!paused) {
      setPauseSnapshot([...traces]);
      setNewCount(0);
    } else {
      setNewCount(0);
    }
    setPaused((value) => !value);
  }

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between border-b border-[rgb(var(--border))] px-6 py-3.5">
        <div className="flex items-center gap-3">
          <h1 className="text-[15px] font-semibold text-text-primary">Live Feed</h1>
          <Badge variant="llm">live</Badge>
          <StatusDot status={connected ? 'success' : 'error'} pulse={connected} />
          <span className="text-[12px] text-text-secondary">{connected ? 'Connected' : 'Disconnected'}</span>
        </div>
        <div className="flex items-center gap-2">
          <OutlineButton onClick={togglePause}>
            {paused ? <Play className="h-3.5 w-3.5" /> : <Pause className="h-3.5 w-3.5" />}
            {paused ? 'Resume' : 'Pause'}
          </OutlineButton>
          <OutlineButton onClick={clear}>
            <Trash2 className="h-3.5 w-3.5" />
            Clear
          </OutlineButton>
        </div>
      </div>

      {/* Body */}
      <div className="flex min-h-0 flex-1">
        {/* Feed */}
        <div className="min-w-0 flex-1 overflow-y-auto p-5 space-y-4">
          {paused && newCount > 0 && (
            <button
              onClick={togglePause}
              className="w-full rounded-md border border-warning/40 bg-warning/[0.06] px-4 py-2 text-left text-[12px] text-[var(--badge-victim-text)]"
            >
              {newCount} new traces queued while paused. Resume to see the latest entries.
            </button>
          )}

          <div className="table-shell">
            {displayed.length === 0 ? (
              <div className="flex min-h-[420px] items-center justify-center p-6">
                <EmptyState
                  icon={<span className="h-3 w-3 rounded-full bg-accent animate-pulse" />}
                  title="Waiting for traces"
                  description="Leave this page open while your agents run. New traces will stream in here with status, duration, cost, and blame context."
                />
              </div>
            ) : (
              <div>
                <div className="table-header grid-cols-[120px_24px_minmax(0,1.2fr)_90px_90px_minmax(0,180px)]">
                  <span>Time</span>
                  <span />
                  <span>Name</span>
                  <span>Latency</span>
                  <span>Cost</span>
                  <span>Status</span>
                </div>
                {displayed.map((trace, index) => {
                  const isFresh = (timeSinceMs(trace.start_time) ?? Infinity) < 2000;
                  return (
                    <button
                      key={`${trace.trace_id}-${index}`}
                      onClick={() => setPeekId(trace.trace_id)}
                      className="data-row animate-feed-enter grid w-full grid-cols-[120px_24px_minmax(0,1.2fr)_90px_90px_minmax(0,180px)] text-left"
                    >
                      <span className="font-mono text-[11px] text-text-muted">{formatTime(trace.start_time)}</span>
                      <StatusDot status={trace.status === 'error' ? 'error' : 'success'} pulse={isFresh} />
                      <span className="truncate font-mono text-[12px] text-text-primary">{trace.name}</span>
                      <span className="text-[12px] text-text-secondary">{formatMs(trace.latency_ms)}</span>
                      <span className="font-mono text-[12px] text-text-secondary">{formatCost(trace.cost_usd)}</span>
                      <span className="truncate text-[12px] text-text-secondary">
                        {trace.status === 'error' ? <span className="text-danger">Error</span> : 'Success'}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* Sidebar */}
        <aside className="w-[240px] shrink-0 border-l border-[rgb(var(--border))] px-4 py-5">
          <SectionLabel>Live Summary</SectionLabel>
          <div className="mt-4 space-y-3">
            <SidebarMetric label="Rolling cost (1h)" value={formatCost(rollingCost)} trend={<TrendingUp className="h-3.5 w-3.5 text-cyan" />} />
            <SidebarMetric label="Error rate (1h)" value={`${Math.round(errorRate * 100)}%`} trend={<TrendingDown className="h-3.5 w-3.5 text-text-muted" />} />
            <SidebarMetric label="Traces/min" value={String(tracesPerMinute)} />
            <SidebarMetric label="Most active agent" value={mostActiveAgent} mono />
          </div>
        </aside>
      </div>

      {peekId && <PeekPanel traceId={peekId} onClose={() => setPeekId(null)} />}
    </div>
  );
}

function SidebarMetric({
  label,
  value,
  trend,
  mono = false,
}: {
  label: string;
  value: string;
  trend?: ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="rounded-md border border-[rgb(var(--border))] bg-[rgb(var(--surface-800))] px-3 py-3">
      <div className="section-label flex items-center justify-between">
        <span>{label}</span>
        {trend}
      </div>
      <div className={mono ? 'mt-1.5 font-mono text-[18px] font-semibold text-text-primary' : 'mt-1.5 text-[22px] font-semibold text-text-primary'}>
        {value}
      </div>
    </div>
  );
}
