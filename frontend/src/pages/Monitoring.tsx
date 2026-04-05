import { useEffect, useState } from 'react';
import { format } from 'date-fns';
import clsx from 'clsx';
import {
  AreaChart, Area, LineChart, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts';
import {
  fetchMonitoringTraces,
  fetchMonitoringLLM,
  fetchMonitoringCostTokens,
  fetchMonitoringTools,
  fetchMonitoringRunTypes,
  type MonitoringTraces,
  type MonitoringLLM,
  type MonitoringCostTokens,
  type MonitoringTools,
  type MonitoringRunTypes,
  type TimeSeriesPoint,
  type LatencyPercentilesPoint,
  type GroupedCount,
} from '../lib/api';

const TABS = ['Traces', 'LLM Calls', 'Cost & Tokens', 'Tools', 'Run Types'] as const;
type Tab = (typeof TABS)[number];

const RANGES = [
  { label: '6h', hours: 6 },
  { label: '24h', hours: 24 },
  { label: '7d', hours: 168 },
  { label: '30d', hours: 720 },
] as const;

function fmtTs(ts: string): string {
  try {
    return format(new Date(ts), 'MMM d, HH:mm');
  } catch {
    return ts;
  }
}

function EmptyChart({ label }: { label: string }) {
  return (
    <div className="flex h-[220px] items-center justify-center rounded-lg border border-border bg-surface-900/30">
      <div className="text-center text-text-muted text-sm">
        <div className="mb-1 text-lg opacity-40">○</div>
        No data available for {label}
      </div>
    </div>
  );
}

function ChartCard({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-surface-800 p-5">
      <div className="mb-4">
        <h3 className="text-sm font-semibold text-text-primary">{title}</h3>
        {subtitle && <p className="text-xs text-text-muted mt-0.5">{subtitle}</p>}
      </div>
      {children}
    </div>
  );
}

function TSAreaChart({ data, dataKey, color, label }: { data: TimeSeriesPoint[]; dataKey?: string; color: string; label: string }) {
  if (!data.length) return <EmptyChart label={label} />;
  const mapped = data.map(d => ({ ts: fmtTs(d.ts), value: d.value, success: d.value - (d.value2 ?? 0), errors: d.value2 ?? 0 }));
  return (
    <ResponsiveContainer width="100%" height={220}>
      <AreaChart data={mapped}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis dataKey="ts" tick={{ fontSize: 11 }} stroke="var(--text-muted)" />
        <YAxis tick={{ fontSize: 11 }} stroke="var(--text-muted)" />
        <Tooltip contentStyle={{ background: 'var(--tooltip-bg)', border: '1px solid var(--tooltip-border)', borderRadius: 6, fontSize: 11, color: '#e6e6f8' }} />
        {dataKey === 'stacked' ? (
          <>
            <Area type="monotone" dataKey="success" stackId="1" stroke="#34d399" fill="#34d399" fillOpacity={0.25} name="Success" />
            <Area type="monotone" dataKey="errors" stackId="1" stroke="#f85050" fill="#f85050" fillOpacity={0.35} name="Errors" />
            <Legend wrapperStyle={{ fontSize: 11 }} />
          </>
        ) : (
          <Area type="monotone" dataKey="value" stroke={color} fill={color} fillOpacity={0.2} name={label} />
        )}
      </AreaChart>
    </ResponsiveContainer>
  );
}

function LatencyChart({ data, label }: { data: LatencyPercentilesPoint[]; label: string }) {
  if (!data.length) return <EmptyChart label={label} />;
  const mapped = data.map(d => ({ ts: fmtTs(d.ts), p50: d.p50, p95: d.p95, p99: d.p99 }));
  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={mapped}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis dataKey="ts" tick={{ fontSize: 11 }} stroke="var(--text-muted)" />
        <YAxis tick={{ fontSize: 11 }} stroke="var(--text-muted)" unit="ms" />
        <Tooltip contentStyle={{ background: 'var(--tooltip-bg)', border: '1px solid var(--tooltip-border)', borderRadius: 6, fontSize: 11, color: '#e6e6f8' }} />
        <Line type="monotone" dataKey="p50" stroke="#7c5aff" strokeWidth={2} dot={false} name="p50" />
        <Line type="monotone" dataKey="p95" stroke="#fbbf24" strokeWidth={2} dot={false} name="p95" />
        <Line type="monotone" dataKey="p99" stroke="#f85050" strokeWidth={2} dot={false} name="p99" />
        <Legend wrapperStyle={{ fontSize: 11 }} />
      </LineChart>
    </ResponsiveContainer>
  );
}

function SimpleAreaChart({ data, color, label, unit }: { data: TimeSeriesPoint[]; color: string; label: string; unit?: string }) {
  if (!data.length) return <EmptyChart label={label} />;
  const mapped = data.map(d => ({ ts: fmtTs(d.ts), value: d.value }));
  return (
    <ResponsiveContainer width="100%" height={220}>
      <AreaChart data={mapped}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis dataKey="ts" tick={{ fontSize: 11 }} stroke="var(--text-muted)" />
        <YAxis tick={{ fontSize: 11 }} stroke="var(--text-muted)" unit={unit} />
        <Tooltip contentStyle={{ background: 'var(--tooltip-bg)', border: '1px solid var(--tooltip-border)', borderRadius: 6, fontSize: 11, color: '#e6e6f8' }} />
        <Area type="monotone" dataKey="value" stroke={color} fill={color} fillOpacity={0.2} name={label} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

function GroupTable({ data, label }: { data: GroupedCount[]; label: string }) {
  if (!data.length) return <EmptyChart label={label} />;
  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border bg-surface-900/40">
            <th className="px-4 py-2.5 text-left font-medium text-text-secondary">Name</th>
            <th className="px-4 py-2.5 text-right font-medium text-text-secondary">Count</th>
            <th className="px-4 py-2.5 text-right font-medium text-text-secondary">Errors</th>
            <th className="px-4 py-2.5 text-right font-medium text-text-secondary">Error Rate</th>
            <th className="px-4 py-2.5 text-right font-medium text-text-secondary">Avg Latency</th>
            <th className="px-4 py-2.5 text-right font-medium text-text-secondary">Tokens</th>
          </tr>
        </thead>
        <tbody>
          {data.map((r) => (
            <tr key={r.name} className="border-b border-border last:border-0 transition-colors hover:bg-surface-900/20">
              <td className="px-4 py-2.5 font-mono text-xs text-text-primary">{r.name}</td>
              <td className="px-4 py-2.5 text-right text-text-primary">{r.count.toLocaleString()}</td>
              <td className="px-4 py-2.5 text-right">
                <span className={r.error_count > 0 ? 'text-danger' : 'text-text-muted'}>{r.error_count}</span>
              </td>
              <td className="px-4 py-2.5 text-right">
                <span className={r.error_rate > 0.1 ? 'text-danger' : 'text-text-muted'}>
                  {(r.error_rate * 100).toFixed(1)}%
                </span>
              </td>
              <td className="px-4 py-2.5 text-right text-text-secondary">{r.avg_latency_ms.toFixed(0)}ms</td>
              <td className="px-4 py-2.5 text-right text-text-secondary">{r.total_tokens.toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}


export default function Monitoring() {
  const [tab, setTab] = useState<Tab>('Traces');
  const [hours, setHours] = useState(168);
  const [loading, setLoading] = useState(true);

  const [traces, setTraces] = useState<MonitoringTraces | null>(null);
  const [llm, setLlm] = useState<MonitoringLLM | null>(null);
  const [costTokens, setCostTokens] = useState<MonitoringCostTokens | null>(null);
  const [tools, setTools] = useState<MonitoringTools | null>(null);
  const [runTypes, setRunTypes] = useState<MonitoringRunTypes | null>(null);

  useEffect(() => {
    setLoading(true);
    const load = async () => {
      try {
        const [t, l, c, to, rt] = await Promise.all([
          fetchMonitoringTraces(hours),
          fetchMonitoringLLM(hours),
          fetchMonitoringCostTokens(hours),
          fetchMonitoringTools(hours),
          fetchMonitoringRunTypes(hours),
        ]);
        setTraces(t);
        setLlm(l);
        setCostTokens(c);
        setTools(to);
        setRunTypes(rt);
      } catch (e) {
        console.error('Monitoring fetch failed', e);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [hours]);

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-6 py-3.5">
        <h1 className="text-[15px] font-semibold text-text-primary">Monitoring</h1>
        <div className="flex items-center rounded-md border border-border bg-surface-800 p-0.5">
          {RANGES.map((r) => (
            <button
              key={r.hours}
              onClick={() => setHours(r.hours)}
              className={clsx(
                'rounded-md px-2.5 py-1 text-[12px] font-medium transition-colors',
                hours === r.hours
                  ? 'bg-surface-600 text-text-primary shadow-sm'
                  : 'text-text-muted hover:text-text-secondary'
              )}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tabs row */}
      <div className="flex items-center gap-1 border-b border-border px-6">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={clsx(
              'px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px',
              tab === t
                ? 'border-accent text-accent'
                : 'border-transparent text-text-secondary hover:text-text-primary'
            )}
          >
            {t}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {loading && (
          <div className="flex-1 flex items-center justify-center h-64">
            <div className="text-center text-text-muted">
              <div className="animate-spin h-6 w-6 border-2 border-accent border-t-transparent rounded-full mx-auto mb-3" />
              Loading monitoring data...
            </div>
          </div>
        )}

        {!loading && tab === 'Traces' && traces && (
          <div className="space-y-6">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <ChartCard title="Trace Count" subtitle="Total number of traces over time">
                <TSAreaChart data={traces.trace_counts} dataKey="stacked" color="#7c5aff" label="Traces" />
              </ChartCard>
              <ChartCard title="Trace Error Rate" subtitle="Percent of traces that errored over time">
                <SimpleAreaChart data={traces.error_rate} color="#f85050" label="Error Rate" />
              </ChartCard>
            </div>
            <ChartCard title="Trace Latency" subtitle="Trace latency percentiles over time">
              <LatencyChart data={traces.latency_percentiles} label="latency" />
            </ChartCard>
          </div>
        )}

        {!loading && tab === 'LLM Calls' && llm && (
          <div className="space-y-6">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <ChartCard title="LLM Count" subtitle="Number of LLM calls over time">
                <TSAreaChart data={llm.call_counts} dataKey="stacked" color="#7c5aff" label="LLM Calls" />
              </ChartCard>
              <ChartCard title="LLM Latency" subtitle="LLM call latency percentiles over time">
                <LatencyChart data={llm.latency_percentiles} label="LLM latency" />
              </ChartCard>
            </div>
          </div>
        )}

        {!loading && tab === 'Cost & Tokens' && costTokens && (
          <div className="space-y-6">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <ChartCard title="Total Cost" subtitle="Total cost over time">
                <SimpleAreaChart data={costTokens.total_cost} color="#34d399" label="Cost ($)" unit="$" />
              </ChartCard>
              <ChartCard title="Cost per Trace" subtitle="Median cost per trace">
                <SimpleAreaChart data={costTokens.cost_per_trace} color="#38bdf8" label="Avg Cost ($)" unit="$" />
              </ChartCard>
              <ChartCard title="Output Tokens" subtitle="Total output tokens over time">
                <SimpleAreaChart data={costTokens.output_tokens} color="#fbbf24" label="Output" />
              </ChartCard>
              <ChartCard title="Output Tokens per Trace" subtitle="Output tokens used per trace over time">
                <SimpleAreaChart data={costTokens.output_tokens_per_trace} color="#f97316" label="Avg Output" />
              </ChartCard>
              <ChartCard title="Input Tokens" subtitle="Total input tokens over time">
                <SimpleAreaChart data={costTokens.input_tokens} color="#7c5aff" label="Input" />
              </ChartCard>
              <ChartCard title="Input Tokens per Trace" subtitle="Input tokens used per trace over time">
                <SimpleAreaChart data={costTokens.input_tokens_per_trace} color="#9876ff" label="Avg Input" />
              </ChartCard>
            </div>
          </div>
        )}

        {!loading && tab === 'Tools' && tools && (
          <div className="space-y-6">
            <ChartCard title="Run Count by Tool" subtitle="Tool call counts over time">
              <SimpleAreaChart data={tools.tool_counts} color="#7c5aff" label="Tool Calls" />
            </ChartCard>
            <ChartCard title="Tool Breakdown" subtitle="Metrics by tool name">
              <GroupTable data={tools.by_tool} label="tools" />
            </ChartCard>
          </div>
        )}

        {!loading && tab === 'Run Types' && runTypes && (
          <div className="space-y-6">
            <ChartCard title="Run Count by Name (depth=1)" subtitle="Run counts by name over time, filtered to runs that occur at depth 1">
              <GroupTable data={runTypes.by_name} label="run types" />
            </ChartCard>
          </div>
        )}
      </div>
    </div>
  );
}
