import { useState } from 'react';
import { ChevronDown, ChevronRight, CheckCircle2, XCircle } from 'lucide-react';
import type { EvalResult } from '../lib/api';
import { formatMs, formatCost } from '../lib/utils';

interface Props {
  results: EvalResult[];
}

export default function EvalResultsTable({ results }: Props) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  if (results.length === 0) {
    return (
      <div className="py-8 text-center text-sm text-text-muted">
        No results yet.
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-border">
      {/* Header */}
      <div className="grid grid-cols-[1fr_80px_80px_90px_80px] gap-2 border-b border-border bg-surface-800 px-4 py-2.5 text-xs font-medium uppercase tracking-wider text-text-muted">
        <span>Example</span>
        <span className="text-center">Score</span>
        <span className="text-center">Result</span>
        <span className="text-right">Latency</span>
        <span className="text-right">Cost</span>
      </div>

      {/* Rows */}
      {results.map((r) => {
        const expanded = expandedId === r.id;
        return (
          <div key={r.id} className="border-b border-border last:border-b-0">
            <button
              onClick={() => setExpandedId(expanded ? null : r.id)}
              className="grid w-full grid-cols-[1fr_80px_80px_90px_80px] gap-2 px-4 py-2.5 text-left text-sm transition-colors hover:bg-surface-800/50"
            >
              <div className="flex items-center gap-2 min-w-0">
                {expanded
                  ? <ChevronDown className="h-3.5 w-3.5 text-text-muted flex-shrink-0" />
                  : <ChevronRight className="h-3.5 w-3.5 text-text-muted flex-shrink-0" />
                }
                <span className="truncate font-mono text-xs text-text-secondary">
                  {r.example_id.slice(0, 12)}…
                </span>
              </div>

              <div className="flex items-center justify-center">
                <ScoreBar score={r.score} />
              </div>

              <div className="flex items-center justify-center">
                {r.passed ? (
                  <span className="flex items-center gap-1 text-xs text-success">
                    <CheckCircle2 className="h-3.5 w-3.5" />
                    Pass
                  </span>
                ) : (
                  <span className="flex items-center gap-1 text-xs text-danger">
                    <XCircle className="h-3.5 w-3.5" />
                    Fail
                  </span>
                )}
              </div>

              <div className="text-right text-xs text-text-muted">
                {formatMs(r.latency_ms)}
              </div>

              <div className="text-right text-xs text-text-muted">
                {formatCost(r.cost_usd)}
              </div>
            </button>

            {expanded && (
              <div className="border-t border-border bg-surface-800/30 px-5 py-3 space-y-2">
                <div>
                  <span className="text-[10px] uppercase tracking-wider text-text-muted">Output</span>
                  <pre className="mt-1 max-h-48 overflow-auto rounded-md bg-surface-900 p-3 text-xs text-text-secondary font-mono">
                    {typeof r.output === 'string' ? r.output : JSON.stringify(r.output, null, 2)}
                  </pre>
                </div>
                <div className="flex gap-6 text-xs text-text-muted">
                  <span>Score: <span className="text-text-primary font-medium">{r.score.toFixed(4)}</span></span>
                  <span>Latency: <span className="text-text-primary font-medium">{formatMs(r.latency_ms)}</span></span>
                  <span>Cost: <span className="text-text-primary font-medium">{formatCost(r.cost_usd)}</span></span>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function ScoreBar({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const color =
    score >= 0.8 ? 'bg-success' :
    score >= 0.5 ? 'bg-warning' :
    'bg-danger';

  return (
    <div className="flex items-center gap-1.5 w-full">
      <div className="h-1.5 flex-1 rounded-full bg-surface-700 overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[11px] font-mono text-text-secondary w-8 text-right">{pct}%</span>
    </div>
  );
}
