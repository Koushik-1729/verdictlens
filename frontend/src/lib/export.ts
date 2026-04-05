import type { TraceSummary } from './api';

export function downloadJson(data: unknown, filename: string) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  triggerDownload(blob, filename);
}

export function downloadCsv(rows: Record<string, unknown>[], filename: string) {
  if (rows.length === 0) return;
  const headers = Object.keys(rows[0]);
  const csvRows = [
    headers.join(','),
    ...rows.map((row) =>
      headers.map((h) => {
        const val = row[h];
        const str = val == null ? '' : String(val);
        return str.includes(',') || str.includes('"') || str.includes('\n')
          ? `"${str.replace(/"/g, '""')}"`
          : str;
      }).join(',')
    ),
  ];
  const blob = new Blob([csvRows.join('\n')], { type: 'text/csv' });
  triggerDownload(blob, filename);
}

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function tracesToCsvRows(traces: TraceSummary[]) {
  return traces.map((t) => ({
    trace_id: t.trace_id,
    name: t.name,
    status: t.status,
    latency_ms: t.latency_ms ?? '',
    cost_usd: t.cost_usd ?? '',
    total_tokens: t.total_tokens ?? '',
    span_count: t.span_count ?? '',
    model: t.model ?? '',
    framework: t.framework ?? '',
    start_time: t.start_time,
  }));
}
