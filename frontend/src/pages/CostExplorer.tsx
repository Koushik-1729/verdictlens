import { useEffect, useRef, useState } from 'react';
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { Download } from 'lucide-react';
import clsx from 'clsx';
import { CostSkeleton } from '../components/Skeleton';
import { OutlineButton, SectionLabel } from '../components/ui';
import { fetchMetrics, type Metrics } from '../lib/api';
import { downloadCsv, downloadJson } from '../lib/export';
import { formatCost, formatTokens } from '../lib/utils';

const HOURS_MAP: Record<string, number> = {
  '1h': 1, '6h': 6, '24h': 24, '7d': 168, '30d': 720, '90d': 2160, '180d': 4320, '1y': 8760,
};

export default function CostExplorer() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [range, setRange] = useState('24h');
  const [loading, setLoading] = useState(true);
  const [exportOpen, setExportOpen] = useState(false);
  const exportRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (exportRef.current && !exportRef.current.contains(e.target as Node)) setExportOpen(false);
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  useEffect(() => {
    setLoading(true);
    fetchMetrics(HOURS_MAP[range] ?? 24)
      .then(setMetrics)
      .catch(() => setMetrics(null))
      .finally(() => setLoading(false));
  }, [range]);

  if (loading) {
    return (
      <div className="flex h-full flex-col">
        <CostSkeleton />
      </div>
    );
  }
  if (!metrics) {
    return (
      <div className="flex h-full items-center justify-center text-danger">
        Failed to load cost explorer.
      </div>
    );
  }

  const costByModel = Object.entries(metrics.cost_by_model)
    .map(([model, cost]) => ({ model, cost }))
    .sort((a, b) => b.cost - a.cost);
  const avgCost = metrics.total_traces > 0 ? metrics.total_cost_usd / metrics.total_traces : 0;
  const topModel = costByModel[0]?.model ?? '—';
  const dailyCost = metrics.hourly_trace_counts.map((point) => ({
    date: point.hour,
    cost: metrics.total_traces > 0 ? (point.count / metrics.total_traces) * metrics.total_cost_usd : 0,
  }));
  const byAgent = Object.entries(metrics.traces_by_framework).map(([name, traces]) => ({
    agent: name,
    traces,
    tokens: Math.round((traces / Math.max(metrics.total_traces, 1)) * metrics.total_tokens),
    cost: (traces / Math.max(metrics.total_traces, 1)) * metrics.total_cost_usd,
    pct: traces / Math.max(metrics.total_traces, 1),
  }));
  const tokenByModel = Object.entries(metrics.token_breakdown_by_model ?? {}).length > 0
    ? Object.entries(metrics.token_breakdown_by_model).map(([model, toks]) => ({
        model,
        prompt: toks.prompt,
        completion: toks.completion,
      }))
    : Object.entries(metrics.traces_by_model).map(([model, traces]) => {
        const total = Math.round((traces / Math.max(metrics.total_traces, 1)) * metrics.total_tokens);
        return { model, prompt: Math.round(total * 0.6), completion: Math.round(total * 0.4) };
      });

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-6 py-3.5">
        <h1 className="text-[15px] font-semibold text-text-primary">Cost Explorer</h1>
        <div className="flex items-center gap-2">
          {/* Range picker */}
          <div className="flex items-center rounded-md border border-border bg-surface-800 p-0.5">
            {Object.keys(HOURS_MAP).map((key) => (
              <button
                key={key}
                onClick={() => setRange(key)}
                className={clsx(
                  'rounded-md px-2.5 py-1 text-[12px] font-medium transition-colors',
                  range === key
                    ? 'bg-surface-600 text-text-primary shadow-sm'
                    : 'text-text-muted hover:text-text-secondary'
                )}
              >
                {key}
              </button>
            ))}
          </div>
          {/* Export */}
          <div className="relative" ref={exportRef}>
            <OutlineButton onClick={() => setExportOpen((value) => !value)}>
              <Download className="h-3.5 w-3.5" />
              Export
            </OutlineButton>
            {exportOpen && (
              <div className="absolute right-0 top-full z-10 mt-1 min-w-[120px] rounded-md border border-border bg-surface-900 py-1 shadow-xl">
                <button
                  onClick={() => { downloadCsv(costByModel.map((c) => ({ model: c.model, cost_usd: c.cost })), 'cost_by_model.csv'); setExportOpen(false); }}
                  className="w-full px-3 py-1.5 text-left text-[12px] text-text-secondary hover:bg-surface-800 hover:text-text-primary"
                >
                  Export CSV
                </button>
                <button
                  onClick={() => { downloadJson(metrics, 'cost_report.json'); setExportOpen(false); }}
                  className="w-full px-3 py-1.5 text-left text-[12px] text-text-secondary hover:bg-surface-800 hover:text-text-primary"
                >
                  Export JSON
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Compact stat strip */}
      <div className="border-b border-border px-6 py-2 flex items-center gap-6">
        <span className="text-[11px] text-text-muted">
          Total Cost <span className="font-mono text-text-primary ml-1">{formatCost(metrics.total_cost_usd)}</span>
        </span>
        <span className="text-text-muted/40 text-[11px]">|</span>
        <span className="text-[11px] text-text-muted">
          Avg / Trace <span className="font-mono text-text-primary ml-1">{formatCost(avgCost)}</span>
        </span>
        <span className="text-text-muted/40 text-[11px]">|</span>
        <span className="text-[11px] text-text-muted">
          Top Model <span className="font-mono text-text-primary ml-1">{topModel}</span>
        </span>
        <span className="text-text-muted/40 text-[11px]">|</span>
        <span className="text-[11px] text-text-muted">
          Total Tokens <span className="font-mono text-text-primary ml-1">{formatTokens(metrics.total_tokens)}</span>
        </span>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="ui-card p-4">
            <SectionLabel>Cost By Model</SectionLabel>
            <div className="mt-4 h-[260px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={costByModel} margin={{ left: 8, right: 8, top: 8 }}>
                  <CartesianGrid stroke="var(--chart-grid)" horizontal vertical={false} />
                  <XAxis type="number" tick={{ fontSize: 11, fill: 'var(--axis-tick)' }} axisLine={false} tickLine={false} />
                  <YAxis type="category" dataKey="model" tick={{ fontSize: 11, fill: 'var(--axis-tick-alt)' }} axisLine={false} tickLine={false} width={110} />
                  <Tooltip contentStyle={{ backgroundColor: 'var(--tooltip-bg)', border: '1px solid var(--tooltip-border)', borderRadius: '8px', fontSize: 12 }} />
                  <Bar dataKey="cost" fill="#2563eb" radius={[6, 6, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="ui-card p-4">
            <SectionLabel>Daily Cost</SectionLabel>
            <div className="mt-4 h-[260px]">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={dailyCost}>
                  <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
                  <XAxis dataKey="date" tick={{ fontSize: 11, fill: 'var(--axis-tick)' }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 11, fill: 'var(--axis-tick)' }} axisLine={false} tickLine={false} />
                  <Tooltip contentStyle={{ backgroundColor: 'var(--tooltip-bg)', border: '1px solid var(--tooltip-border)', borderRadius: '8px', fontSize: 12 }} />
                  <Area type="monotone" dataKey="cost" stroke="#2563eb" fill="#dbeafe" strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <div className="table-shell">
            <div className="table-header grid-cols-[minmax(0,1.2fr)_70px_90px_90px_90px]">
              <span>Agent</span>
              <span>Traces</span>
              <span>Tokens</span>
              <span>Cost</span>
              <span>% of total</span>
            </div>
            {byAgent.map((row) => (
              <div key={row.agent} className="data-row grid-cols-[minmax(0,1.2fr)_70px_90px_90px_90px] text-[12px]">
                <span className="truncate font-mono text-text-primary">{row.agent}</span>
                <span className="text-text-secondary">{row.traces}</span>
                <span className="text-text-secondary">{formatTokens(row.tokens)}</span>
                <span className="text-text-secondary">{formatCost(row.cost)}</span>
                <span className="text-text-secondary">{Math.round(row.pct * 100)}%</span>
              </div>
            ))}
          </div>

          <div className="ui-card p-4">
            <SectionLabel>Token Breakdown</SectionLabel>
            <div className="mt-4 h-[260px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={tokenByModel}>
                  <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
                  <XAxis dataKey="model" tick={{ fontSize: 11, fill: 'var(--axis-tick)' }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 11, fill: 'var(--axis-tick)' }} axisLine={false} tickLine={false} />
                  <Tooltip contentStyle={{ backgroundColor: 'var(--tooltip-bg)', border: '1px solid var(--tooltip-border)', borderRadius: '8px', fontSize: 12 }} />
                  <Bar dataKey="prompt" stackId="tokens" fill="#93c5fd" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="completion" stackId="tokens" fill="#2563eb" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
