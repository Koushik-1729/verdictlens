import { format, formatDistanceToNowStrict, parseISO } from 'date-fns';

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  try {
    return format(parseISO(iso), 'HH:mm:ss.SSS');
  } catch {
    return iso;
  }
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  try {
    return format(parseISO(iso), 'MMM d, HH:mm');
  } catch {
    return iso;
  }
}

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return '—';
  try {
    return formatDistanceToNowStrict(parseISO(iso), { addSuffix: true });
  } catch {
    return iso;
  }
}

export function formatMs(ms: number | null | undefined): string {
  if (ms == null) return '—';
  if (ms < 1) return '<1ms';
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

export function formatCost(usd: number | null | undefined): string {
  if (usd == null) return '—';
  if (usd === 0) return '$0.00';
  if (usd < 0.001) return '< $0.001';
  if (usd < 1) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}

export function formatTokens(n: number | null | undefined): string {
  if (n == null) return '—';
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}k`;
  return `${(n / 1_000_000).toFixed(2)}M`;
}

export function formatPct(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '—';
  return `${Math.round(value * 100)}%`;
}

export function latencyTone(ms: number | null | undefined): 'success' | 'warning' | 'error' | 'unknown' {
  if (ms == null) return 'unknown';
  if (ms < 500) return 'success';
  if (ms < 2000) return 'warning';
  return 'error';
}

export function timeSinceMs(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const ms = Date.now() - new Date(iso).getTime();
  return Number.isNaN(ms) ? null : ms;
}

export function statusColor(status: string): string {
  return status === 'error'
    ? 'text-danger'
    : 'text-success';
}

export function spanTypeColor(type: string): string {
  const map: Record<string, string> = {
    llm: 'bg-[var(--badge-propagator-bg)] text-[var(--badge-propagator-text)]',
    agent: 'bg-[var(--badge-agent-bg)] text-[var(--badge-agent-text)]',
    tool: 'bg-[var(--badge-tool-bg)] text-[var(--badge-tool-text)]',
    chain: 'bg-[var(--badge-chain-bg)] text-[var(--badge-chain-text)]',
    retrieval: 'bg-[var(--badge-clean-bg)] text-[var(--badge-clean-text)]',
  };
  return map[type] ?? 'bg-surface-500/20 text-text-secondary';
}
