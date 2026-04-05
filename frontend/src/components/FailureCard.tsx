import { useNavigate } from 'react-router-dom';
import { RotateCcw, Target } from 'lucide-react';
import { formatError, type TraceSummary, type BlameResult } from '../lib/api';
import { timeAgo, formatPct } from '../lib/utils';
import { AccentRow, Badge, ConfidenceBadge, OutlineButton, StatusDot, badgeVariantForSpanType } from './ui';

interface Props {
  trace: TraceSummary;
  blame?: BlameResult | null;
  blameLoading?: boolean;
}

export default function FailureCard({ trace, blame, blameLoading }: Props) {
  const navigate = useNavigate();
  const rc = blame?.originators[0];
  const tone = rc ? 'error' : blame && !rc ? 'warning' : 'error';

  return (
    <AccentRow tone={tone} className="px-4 py-4 transition-colors hover:bg-surface-800/70">
      <div
        className="cursor-pointer"
        onClick={() => navigate(`/traces/${trace.trace_id}`)}
      >
        <div className="flex items-start gap-3">
          <StatusDot status="error" className="mt-[6px]" />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="truncate font-mono text-[13px] font-medium text-text-primary">{trace.name}</span>
              {trace.framework && <Badge variant={badgeVariantForSpanType(trace.framework)}>{trace.framework}</Badge>}
              <span className="ml-auto text-[11px] text-text-muted">{timeAgo(trace.start_time)}</span>
            </div>

            <div className="mt-1 truncate font-mono text-[12px] text-text-secondary">
              {blameLoading ? (
                'Analyzing blame chain...'
              ) : rc ? (
                <>
                  <span className="text-text-primary">{rc.span_name}</span>
                  <span className="mx-1 text-text-muted">→</span>
                  <Badge variant="originator" className="align-middle">root cause</Badge>
                  <span className="ml-2">{rc.reason}</span>
                </>
              ) : (
                formatError(trace.error)
              )}
            </div>

            <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-text-muted">
              {blame && <ConfidenceBadge confidence={blame.confidence} score={rc?.blame_score} />}
              {rc?.blame_score != null && <span>{formatPct(rc.blame_score)} confidence</span>}
              {blame?.propagation_chain?.length ? (
                <span className="truncate">{blame.propagation_chain.slice(0, 2).join(' → ')}</span>
              ) : null}
            </div>
          </div>
        </div>
      </div>

      <div className="mt-3 flex items-center gap-2">
        <OutlineButton onClick={() => navigate(`/traces/${trace.trace_id}`)}>
          <Target className="h-3 w-3" />
          View blame
        </OutlineButton>
        <OutlineButton onClick={() => navigate(`/traces/${trace.trace_id}`)}>
          <RotateCcw className="h-3 w-3" />
          Replay
        </OutlineButton>
      </div>
    </AccentRow>
  );
}
