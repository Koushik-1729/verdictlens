import { useEffect, useRef, useState, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ChevronLeft, ChevronRight, Download, Filter, Search, SlidersHorizontal } from 'lucide-react';
import clsx from 'clsx';
import EmptyState from '../components/EmptyState';
import PeekPanel from '../components/PeekPanel';
import { TracesSkeleton } from '../components/Skeleton';
import { Badge, LatencyBar, OutlineButton, StatusDot } from '../components/ui';
import { downloadCsv, downloadJson, tracesToCsvRows } from '../lib/export';
import { fetchBlame, fetchTraces, searchTraces, formatError, type BlameResult, type TraceListResponse } from '../lib/api';
import { formatCost, formatMs, timeAgo } from '../lib/utils';

const STATUS_TABS = ['all', 'error', 'success'] as const;
type StatusTab = typeof STATUS_TABS[number];

const TRACE_GRID = 'grid-cols-[minmax(0,2.2fr)_160px_60px_140px_100px_110px]';

export default function Traces() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState<TraceListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [nameFilter, setNameFilter] = useState(searchParams.get('name') ?? '');
  const [statusTab, setStatusTab] = useState<StatusTab>((searchParams.get('status') as StatusTab) ?? 'all');
  const [exportOpen, setExportOpen] = useState(false);
  const [peekId, setPeekId] = useState<string | null>(null);
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);
  const [blameCache, setBlameCache] = useState<Record<string, BlameResult | null>>({});
  const exportRef = useRef<HTMLDivElement>(null);
  const page = Number(searchParams.get('page') ?? '1');

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (exportRef.current && !exportRef.current.contains(e.target as Node)) setExportOpen(false);
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const activeQuery = searchParams.get('name') ?? '';
  const isFullTextSearch = activeQuery.length > 2;

  useEffect(() => {
    setLoading(true);
    const statusParam = statusTab === 'all' ? undefined : statusTab === 'success' ? 'ok' : 'error';
    const fetchPromise = isFullTextSearch
      ? searchTraces(activeQuery, page, 50)
      : fetchTraces({
          page,
          page_size: 50,
          name: activeQuery || undefined,
          status: statusParam,
          framework: searchParams.get('framework') || undefined,
          model: searchParams.get('model') || undefined,
        });
    fetchPromise
      .then((res) => {
        setData(res);
        res.traces.forEach((trace) => {
          if (!(trace.trace_id in blameCache)) {
            fetchBlame(trace.trace_id)
              .then((blame) => setBlameCache((prev) => ({ ...prev, [trace.trace_id]: blame })))
              .catch(() => setBlameCache((prev) => ({ ...prev, [trace.trace_id]: null })));
          }
        });
      })
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [searchParams, page, statusTab, isFullTextSearch]);

  const applyFilters = useCallback(() => {
    const p = new URLSearchParams();
    if (nameFilter) p.set('name', nameFilter);
    if (statusTab !== 'all') p.set('status', statusTab);
    p.set('page', '1');
    setSearchParams(p);
  }, [nameFilter, statusTab, setSearchParams]);

  const totalPages = data ? Math.ceil(data.total / data.page_size) : 0;
  const visibleTraces = data?.traces ?? [];

  return (
    <div className="flex h-full flex-col">
      {/* Page header */}
      <div className="flex items-center justify-between border-b border-border px-6 py-3.5">
        <div className="flex items-center gap-3">
          <h1 className="text-[15px] font-semibold text-text-primary">Traces</h1>
          {data && (
            <span className="rounded-full bg-surface-700 px-2 py-0.5 text-[11px] font-medium text-text-muted">
              {data.total.toLocaleString()}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {/* Status tabs */}
          <div className="flex items-center rounded-md border border-border bg-surface-800 p-0.5">
            {STATUS_TABS.map((tab) => (
              <button
                key={tab}
                onClick={() => { setStatusTab(tab); setTimeout(applyFilters, 0); }}
                className={clsx(
                  'rounded px-2.5 py-1 text-[11px] font-medium capitalize transition-colors',
                  statusTab === tab
                    ? 'bg-surface-600 text-text-primary shadow-sm'
                    : 'text-text-muted hover:text-text-secondary'
                )}
              >
                {tab === 'all' ? 'All' : tab}
              </button>
            ))}
          </div>

          {/* Search */}
          <div className="flex flex-col items-end gap-0.5">
            <div className="flex h-7 w-52 items-center gap-2 rounded-md border border-border bg-surface-800 px-2.5">
              <Search className="h-3.5 w-3.5 shrink-0 text-text-muted" />
              <input
                type="text"
                value={nameFilter}
                onChange={(e) => setNameFilter(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && applyFilters()}
                placeholder="Search traces…"
                className="h-full w-full border-0 bg-transparent text-[12px] text-text-primary outline-none placeholder:text-text-muted"
              />
            </div>
            {isFullTextSearch && (
              <span className="text-[10px] text-text-muted">Searching inputs/outputs</span>
            )}
          </div>

          {/* Filter button */}
          <OutlineButton onClick={applyFilters} className="h-7 px-2.5">
            <Filter className="h-3.5 w-3.5" />
          </OutlineButton>

          {/* Export */}
          {data && data.traces.length > 0 && (
            <div className="relative" ref={exportRef}>
              <OutlineButton onClick={() => setExportOpen((v) => !v)} className="h-7 px-2.5">
                <Download className="h-3.5 w-3.5" />
              </OutlineButton>
              {exportOpen && (
                <div className="absolute right-0 top-full z-10 mt-1 min-w-[120px] rounded-md border border-border bg-surface-800 py-1 shadow-xl">
                  <button
                    onClick={() => { downloadCsv(tracesToCsvRows(data.traces), 'traces.csv'); setExportOpen(false); }}
                    className="w-full px-3 py-1.5 text-left text-[12px] text-text-secondary hover:bg-surface-700 hover:text-text-primary"
                  >
                    Export CSV
                  </button>
                  <button
                    onClick={() => { downloadJson(data.traces, 'traces.json'); setExportOpen(false); }}
                    className="w-full px-3 py-1.5 text-left text-[12px] text-text-secondary hover:bg-surface-700 hover:text-text-primary"
                  >
                    Export JSON
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto">
        {/* Column headers */}
        <div className={clsx(
          'grid items-center border-b border-border bg-surface-800/50 px-4 py-2 text-[11px] font-medium uppercase tracking-wider text-text-faint',
          TRACE_GRID
        )}>
          <span>Name</span>
          <span>Model</span>
          <span>Spans</span>
          <span>Latency</span>
          <span>Cost</span>
          <span>When</span>
        </div>

        {loading ? (
          <TracesSkeleton />
        ) : !data || visibleTraces.length === 0 ? (
          <div className="flex items-center justify-center py-32">
            <EmptyState
              icon={<SlidersHorizontal className="h-5 w-5" />}
              title="No traces found"
              description="Run a pipeline or adjust filters to see traces here."
            />
          </div>
        ) : (
          visibleTraces.map((trace) => {
            const blame = blameCache[trace.trace_id];
            const rootCause = blame?.originators?.[0] ?? null;
            const isSelected = selectedTraceId === trace.trace_id;

            return (
              <button
                key={trace.trace_id}
                onClick={() => { setSelectedTraceId(trace.trace_id); setPeekId(trace.trace_id); }}
                className={clsx(
                  'grid w-full items-center border-b border-border/50 px-4 py-2.5 text-left transition-colors',
                  TRACE_GRID,
                  isSelected ? 'bg-accent/[0.06]' : 'hover:bg-surface-700/40',
                  trace.status === 'error' ? 'border-l-2 border-l-danger' : 'border-l-2 border-l-transparent'
                )}
              >
                {/* Name + metadata */}
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <StatusDot status={trace.status === 'error' ? 'error' : rootCause ? 'warning' : 'success'} />
                    <span className="truncate font-mono text-[12.5px] font-medium text-text-primary">{trace.name}</span>
                  </div>
                  {trace.error && (
                    <div className="mt-0.5 truncate pl-4 text-[11px] text-danger">{formatError(trace.error)}</div>
                  )}
                  {rootCause && !trace.error && (
                    <div className="mt-0.5 flex items-center gap-1.5 pl-4">
                      <Badge variant={rootCause.blame_score >= 0.7 ? 'originator' : 'ambiguous'} className="py-0 text-[10px]">
                        {Math.round(rootCause.blame_score * 100)}% blame
                      </Badge>
                      <span className="truncate font-mono text-[11px] text-text-muted">{rootCause.span_name}</span>
                    </div>
                  )}
                </div>

                {/* Model */}
                <div className="min-w-0">
                  {trace.model ? (
                    <span className="truncate font-mono text-[11px] text-text-muted">{trace.model}</span>
                  ) : (
                    <span className="text-[11px] text-text-faint">—</span>
                  )}
                </div>

                {/* Spans */}
                <span className="font-mono text-[12px] text-text-secondary tabular-nums">{trace.span_count}</span>

                {/* Latency */}
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[12px] text-text-secondary tabular-nums">{formatMs(trace.latency_ms)}</span>
                  <LatencyBar ms={trace.latency_ms} width={56} />
                </div>

                {/* Cost */}
                <span className="font-mono text-[12px] text-text-secondary">{formatCost(trace.cost_usd)}</span>

                {/* Time */}
                <span className="text-[11px] text-text-muted">{timeAgo(trace.start_time)}</span>
              </button>
            );
          })
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between border-t border-border px-6 py-2.5">
          <span className="text-[12px] text-text-muted">
            Page {page} of {totalPages} · {data!.total.toLocaleString()} traces
          </span>
          <div className="flex gap-1.5">
            <OutlineButton
              className="h-7 px-2"
              onClick={() => { const p = new URLSearchParams(searchParams); p.set('page', String(page - 1)); setSearchParams(p); }}
            >
              <ChevronLeft className="h-3.5 w-3.5" />
            </OutlineButton>
            <OutlineButton
              className="h-7 px-2"
              onClick={() => { const p = new URLSearchParams(searchParams); p.set('page', String(page + 1)); setSearchParams(p); }}
            >
              <ChevronRight className="h-3.5 w-3.5" />
            </OutlineButton>
          </div>
        </div>
      )}

      {peekId && <PeekPanel traceId={peekId} onClose={() => setPeekId(null)} />}
    </div>
  );
}
