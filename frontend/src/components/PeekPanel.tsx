import { useEffect, useRef, useState } from 'react';
import { X, Clock, DollarSign, Zap } from 'lucide-react';
import { fetchTrace, fetchBlame, type TraceDetail, type BlameResult, formatError } from '../lib/api';
import { formatMs, formatCost, formatTokens, timeAgo } from '../lib/utils';
import SpanTree from './SpanTree';
import JsonViewer from './JsonViewer';
import StatusBadge from './StatusBadge';

interface Props {
  traceId: string;
  onClose: () => void;
}

type Tab = 'spans' | 'blame' | 'input' | 'output';

export default function PeekPanel({ traceId, onClose }: Props) {
  const panelRef = useRef<HTMLDivElement>(null);
  const [trace, setTrace] = useState<TraceDetail | null>(null);
  const [blame, setBlame] = useState<BlameResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<Tab>('spans');

  useEffect(() => {
    setLoading(true);
    setTrace(null);
    setBlame(null);
    setTab('spans');

    fetchTrace(traceId)
      .then((t) => {
        setTrace(t);
        if (t.status === 'error') {
          fetchBlame(traceId).then(setBlame).catch(() => {});
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [traceId]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    function onClick(e: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) onClose();
    }
    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onClick);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onClick);
    };
  }, [onClose]);

  const tabs: { key: Tab; label: string }[] = [
    { key: 'spans', label: 'Spans' },
    ...(trace?.status === 'error' ? [{ key: 'blame' as Tab, label: 'Blame' }] : []),
    { key: 'input', label: 'Input' },
    { key: 'output', label: 'Output' },
  ];

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/20" />
      <div
        ref={panelRef}
        className="relative w-full min-w-[480px] max-w-[46%] overflow-y-auto border-l border-border bg-surface-900 shadow-[0_12px_48px_rgba(15,23,42,0.12)] animate-slide-in"
        style={{ animation: 'slideIn 200ms ease-out' }}
      >
        {/* Header */}
        <div className="sticky top-0 z-10 border-b border-border bg-surface-900 px-5 py-4">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-3">
              {trace && <StatusBadge status={trace.status} />}
              <span className="text-sm font-semibold text-text-primary">{trace?.name ?? 'Loading...'}</span>
            </div>
            <button onClick={onClose} className="text-text-muted hover:text-text-primary transition-colors">
              <X className="h-4 w-4" />
            </button>
          </div>
          {trace && (
            <div className="flex items-center gap-4 text-xs text-text-secondary">
              <span className="flex items-center gap-1"><Clock className="h-3 w-3" />{formatMs(trace.latency_ms)}</span>
              <span className="flex items-center gap-1"><DollarSign className="h-3 w-3" />{formatCost(trace.cost_usd)}</span>
              <span className="flex items-center gap-1"><Zap className="h-3 w-3" />{formatTokens(trace.token_usage?.total_tokens)}</span>
              <span className="text-text-muted">{timeAgo(trace.start_time)}</span>
            </div>
          )}
        </div>

        {/* Error banner */}
        {trace?.error && (
          <div className="mx-5 mt-3 rounded-lg border border-danger/20 bg-danger/5 px-3 py-2 font-mono text-xs text-danger">
            {formatError(trace.error)}
          </div>
        )}

        {/* Tabs */}
        <div className="mt-3 flex items-center gap-0 border-b border-border px-5">
          {tabs.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`px-3 py-2 text-xs font-medium border-b-2 transition-colors ${
                tab === t.key
                  ? t.key === 'blame' ? 'border-danger text-danger' : 'border-accent text-accent'
                  : 'border-transparent text-text-muted hover:text-text-secondary'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="p-5">
          {loading ? (
            <div className="text-xs text-text-muted animate-pulse py-8 text-center">Loading trace...</div>
          ) : !trace ? (
            <div className="text-xs text-text-muted py-8 text-center">Failed to load trace</div>
          ) : (
            <>
              {tab === 'spans' && (
                <SpanTree spans={trace.spans} highlightSpanId={blame?.originators[0]?.span_id} traceId={trace.trace_id} />
              )}
              {tab === 'blame' && blame && (
                <div className="space-y-4">
                  <div className="rounded-r-lg border-l-[3px] border-l-danger bg-[rgb(var(--error-surface))] p-4">
                    <div className="text-[10px] text-text-muted uppercase tracking-wider mb-1">Root cause identified</div>
                    <div className="text-base font-bold text-text-primary">{blame.originators[0]?.span_name ?? '—'}</div>
                    <div className="text-xs text-accent font-medium mt-0.5">
                      Blame score: {blame.originators[0]?.blame_score != null ? `${Math.round(blame.originators[0].blame_score * 100)}%` : '—'}
                    </div>
                    <div className="text-xs text-text-secondary mt-2">{blame.originators[0]?.reason ?? ''}</div>
                  </div>
                  <div className="space-y-2">
                    {(blame.propagation_chain ?? []).map((step, i) => (
                      <div key={i} className="flex items-start gap-2">
                        <div className="mt-1 w-1.5 h-1.5 rounded-full bg-danger shrink-0" />
                        <span className="text-xs text-text-secondary">{step}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {tab === 'blame' && !blame && (
                <div className="text-xs text-text-muted py-8 text-center animate-pulse">Running blame analysis...</div>
              )}
              {tab === 'input' && <JsonViewer data={trace.input} defaultOpen />}
              {tab === 'output' && <JsonViewer data={trace.output} defaultOpen />}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
