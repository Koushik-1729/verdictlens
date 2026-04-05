import { useMemo, useState } from 'react';
import { ChevronDown, ChevronRight, RotateCcw } from 'lucide-react';
import clsx from 'clsx';
import { formatError, type Span } from '../lib/api';
import { formatMs } from '../lib/utils';
import JsonViewer from './JsonViewer';
import ReplayModal from './ReplayModal';
import { Badge, badgeVariantForSpanType, OutlineButton } from './ui';

interface Props {
  spans: Span[];
  highlightSpanId?: string | null;
  traceId?: string;
  onReplayComplete?: () => void;
  rowVariantBySpanId?: Record<string, 'originator' | 'victim' | 'ambiguous' | 'clean'>;
}

interface TreeNode {
  span: Span;
  children: TreeNode[];
}

function buildTree(spans: Span[]): TreeNode[] {
  const map = new Map<string, TreeNode>();
  const roots: TreeNode[] = [];
  for (const span of spans) map.set(span.span_id, { span, children: [] });
  for (const span of spans) {
    const node = map.get(span.span_id)!;
    if (span.parent_span_id && map.has(span.parent_span_id)) {
      map.get(span.parent_span_id)!.children.push(node);
    } else {
      roots.push(node);
    }
  }
  return roots;
}

function maxLatency(nodes: TreeNode[]): number {
  let max = 0;
  function walk(n: TreeNode) {
    if ((n.span.latency_ms ?? 0) > max) max = n.span.latency_ms ?? 0;
    n.children.forEach(walk);
  }
  nodes.forEach(walk);
  return max || 1;
}

// ── Row background by blame verdict ─────────────────────────────────────────
function rowBg(variant?: string, hasError?: boolean, highlighted?: boolean) {
  if (variant === 'originator' || highlighted)
    return 'bg-danger/[0.10] border-l-[3px] border-l-danger';
  if (variant === 'victim')
    return 'bg-warning/[0.08] border-l-[3px] border-l-warning';
  if (variant === 'ambiguous' || hasError)
    return 'bg-warning/[0.05] border-l-[3px] border-l-warning/60';
  return 'border-l-[3px] border-l-transparent';
}

// ── Status dot ────────────────────────────────────────────────────────────────
function StatusDot({ span }: { span: Span }) {
  const cls = span.error
    ? 'bg-danger ring-2 ring-danger/30'
    : span.output === null
    ? 'bg-warning ring-2 ring-warning/25'
    : 'bg-success/80';
  return <span className={clsx('inline-block h-2 w-2 shrink-0 rounded-full', cls)} />;
}

// ── Tree connector (vertical guide lines + elbow) ────────────────────────────
// `continuations[i]` = true means depth i still has more siblings → draw vertical line
function TreeGuides({
  continuations,
  isLast,
  depth,
}: {
  continuations: boolean[];
  isLast: boolean;
  depth: number;
}) {
  if (depth === 0) return null;
  return (
    <div className="relative flex shrink-0 self-stretch" style={{ width: depth * 20 }}>
      {/* Vertical guide lines for ancestor depths */}
      {continuations.slice(0, -1).map((cont, i) =>
        cont ? (
          <div
            key={i}
            className="absolute top-0 bottom-0 border-l border-border/30"
            style={{ left: i * 20 + 10 }}
          />
        ) : null,
      )}
      {/* Elbow connector for this node */}
      <div
        className="absolute border-l border-border/40"
        style={{
          left: (depth - 1) * 20 + 10,
          top: 0,
          bottom: isLast ? '50%' : 0,
        }}
      />
      <div
        className="absolute border-t border-border/40"
        style={{
          left: (depth - 1) * 20 + 10,
          width: 10,
          top: '50%',
        }}
      />
    </div>
  );
}

// ── Latency bar ───────────────────────────────────────────────────────────────
function LatencyBar({
  latency,
  maxLat,
  variant,
}: {
  latency: number | null;
  maxLat: number;
  variant?: string;
}) {
  const pct = latency != null ? Math.max(2, (latency / maxLat) * 100) : 0;
  const barColor =
    variant === 'originator'
      ? 'bg-danger/70'
      : variant === 'victim'
      ? 'bg-warning/60'
      : 'bg-accent/40';

  return (
    <div className="flex items-center gap-2 shrink-0">
      <div className="w-16 h-1.5 rounded-full bg-surface-600 overflow-hidden">
        <div className={clsx('h-full rounded-full transition-all', barColor)} style={{ width: `${pct}%` }} />
      </div>
      <span className="w-12 text-right font-mono text-[11px] text-text-muted tabular-nums">
        {formatMs(latency)}
      </span>
    </div>
  );
}

// ── Single span row ───────────────────────────────────────────────────────────
function SpanNode({
  node,
  depth,
  isLast,
  continuations,
  highlightSpanId,
  traceId,
  onReplayComplete,
  rowVariantBySpanId,
  maxLat,
}: {
  node: TreeNode;
  depth: number;
  isLast: boolean;
  continuations: boolean[];
  highlightSpanId?: string | null;
  traceId?: string;
  onReplayComplete?: () => void;
  rowVariantBySpanId?: Record<string, 'originator' | 'victim' | 'ambiguous' | 'clean'>;
  maxLat: number;
}) {
  const { span } = node;
  const [expanded, setExpanded] = useState(depth < 2);
  const [detailsOpen, setDetailsOpen] = useState(Boolean(span.error));
  const [replayOpen, setReplayOpen] = useState(false);

  const hasChildren = node.children.length > 0;
  const highlighted = span.span_id === highlightSpanId;
  const variant = rowVariantBySpanId?.[span.span_id];

  // Build continuations for children
  const childContinuations = [...continuations, !isLast];

  return (
    <div>
      {/* Main row */}
      <div
        className={clsx(
          'group flex min-h-[38px] cursor-pointer items-center gap-1.5 border-b border-border/40 pr-3 text-[12px] transition-colors hover:bg-accent/[0.05]',
          rowBg(variant, Boolean(span.error), highlighted),
        )}
        onClick={() => setDetailsOpen((v) => !v)}
      >
        {/* Tree guide lines */}
        <TreeGuides continuations={childContinuations} isLast={isLast} depth={depth} />

        {/* Expand/collapse toggle */}
        <div className="flex shrink-0 items-center pl-1.5">
          {hasChildren ? (
            <button
              onClick={(e) => { e.stopPropagation(); setExpanded((v) => !v); }}
              className="flex h-5 w-5 items-center justify-center rounded text-text-muted hover:bg-surface-600 hover:text-text-primary transition-colors"
            >
              {expanded
                ? <ChevronDown className="h-3.5 w-3.5" />
                : <ChevronRight className="h-3.5 w-3.5" />}
            </button>
          ) : (
            <span className="w-5" />
          )}
        </div>

        {/* Status dot */}
        <StatusDot span={span} />

        {/* Span name */}
        <span className={clsx(
          'min-w-0 flex-1 truncate font-mono text-[12px] font-medium',
          variant === 'originator' || highlighted ? 'text-danger' : 'text-text-primary',
        )}>
          {span.name}
        </span>

        {/* Type badge */}
        <Badge variant={badgeVariantForSpanType(span.span_type)}>{span.span_type}</Badge>

        {/* Blame verdict badges */}
        {variant === 'originator' && (
          <Badge variant="originator" className="font-semibold">root cause</Badge>
        )}
        {variant === 'victim' && (
          <Badge variant="victim">failure point</Badge>
        )}

        {/* Model chip */}
        {span.model && (
          <span className="hidden shrink-0 rounded border border-border/50 bg-surface-700/80 px-1.5 py-0.5 font-mono text-[10px] text-text-muted sm:inline-block truncate max-w-[120px]">
            {span.model}
          </span>
        )}

        {/* Replay button (on hover) */}
        {traceId && (
          <OutlineButton
            className="hidden group-hover:inline-flex h-7 text-[11px] shrink-0"
            onClick={(e) => { e.stopPropagation(); setReplayOpen(true); }}
          >
            <RotateCcw className="h-3 w-3" />
            Replay
          </OutlineButton>
        )}

        {/* Latency bar */}
        <LatencyBar latency={span.latency_ms} maxLat={maxLat} variant={variant} />
      </div>

      {/* Details panel */}
      {detailsOpen && (
        <div
          className="rounded-md border border-border bg-surface-800/60 px-4 py-3 space-y-3"
          style={{ marginLeft: depth * 20 + 44, marginTop: 4, marginBottom: 4 }}
        >
          {span.error && (
            <div className="rounded border border-danger/30 bg-danger/[0.07] px-3 py-2 font-mono text-[12px] text-[var(--badge-originator-text)]">
              {formatError(span.error)}
            </div>
          )}
          {span.input != null && (
            <div>
              <div className="section-label mb-1">Input</div>
              <JsonViewer data={span.input} defaultOpen />
            </div>
          )}
          {span.output != null && (
            <div>
              <div className="section-label mb-1">Output</div>
              <JsonViewer data={span.output} defaultOpen />
            </div>
          )}
          {span.token_usage && (
            <div className="flex flex-wrap gap-4 text-[11px] text-text-secondary">
              <span>Prompt: <span className="text-text-primary font-mono">{span.token_usage.prompt_tokens ?? '—'}</span></span>
              <span>Completion: <span className="text-text-primary font-mono">{span.token_usage.completion_tokens ?? '—'}</span></span>
              <span>Total: <span className="text-text-primary font-mono">{span.token_usage.total_tokens ?? '—'}</span></span>
            </div>
          )}
        </div>
      )}

      {/* Replay modal */}
      {replayOpen && traceId && (
        <ReplayModal
          span={span}
          traceId={traceId}
          onClose={() => setReplayOpen(false)}
          onReplayComplete={onReplayComplete}
        />
      )}

      {/* Children */}
      {expanded && node.children.map((child, i) => (
        <SpanNode
          key={child.span.span_id}
          node={child}
          depth={depth + 1}
          isLast={i === node.children.length - 1}
          continuations={childContinuations}
          highlightSpanId={highlightSpanId}
          traceId={traceId}
          onReplayComplete={onReplayComplete}
          rowVariantBySpanId={rowVariantBySpanId}
          maxLat={maxLat}
        />
      ))}
    </div>
  );
}

// ── Root export ───────────────────────────────────────────────────────────────
export default function SpanTree({
  spans,
  highlightSpanId,
  traceId,
  onReplayComplete,
  rowVariantBySpanId,
}: Props) {
  const tree = useMemo(() => buildTree(spans), [spans]);
  const maxLat = useMemo(() => maxLatency(tree), [tree]);

  if (tree.length === 0) {
    return <div className="px-4 py-6 text-[12px] text-text-muted">No spans recorded.</div>;
  }

  return (
    <div>
      {/* Column header */}
      <div className="flex items-center border-b border-border/50 px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-text-faint">
        <span className="flex-1">Span</span>
        <span className="mr-1">Latency</span>
      </div>
      <div>
        {tree.map((node, i) => (
          <SpanNode
            key={node.span.span_id}
            node={node}
            depth={0}
            isLast={i === tree.length - 1}
            continuations={[]}
            highlightSpanId={highlightSpanId}
            traceId={traceId}
            onReplayComplete={onReplayComplete}
            rowVariantBySpanId={rowVariantBySpanId}
            maxLat={maxLat}
          />
        ))}
      </div>
    </div>
  );
}
