import type { ReactNode } from 'react';
import clsx from 'clsx';

export type BadgeVariant =
  | 'originator' | 'victim' | 'propagator' | 'clean'
  | 'high' | 'medium' | 'ambiguous'
  | 'llm' | 'chain' | 'agent' | 'tool' | 'retrieval' | 'default';

const BADGE_STYLES: Record<BadgeVariant, string> = {
  originator: 'bg-[var(--badge-originator-bg)] text-[var(--badge-originator-text)] border-[rgba(239,68,68,0.2)]',
  victim:     'bg-[var(--badge-victim-bg)] text-[var(--badge-victim-text)] border-[rgba(245,158,11,0.2)]',
  propagator: 'bg-[var(--badge-propagator-bg)] text-[var(--badge-propagator-text)] border-transparent',
  clean:      'bg-[var(--badge-clean-bg)] text-[var(--badge-clean-text)] border-[rgba(34,197,94,0.2)]',
  high:       'bg-[var(--badge-clean-bg)] text-[var(--badge-clean-text)] border-[rgba(34,197,94,0.2)]',
  medium:     'bg-[var(--badge-ambiguous-bg)] text-[var(--badge-ambiguous-text)] border-[rgba(245,158,11,0.2)]',
  ambiguous:  'bg-[var(--badge-propagator-bg)] text-text-muted border-transparent',
  llm:        'bg-[var(--badge-propagator-bg)] text-[var(--badge-propagator-text)] border-transparent',
  chain:      'bg-[var(--badge-chain-bg)] text-[var(--badge-chain-text)] border-[rgba(99,102,241,0.2)]',
  agent:      'bg-[var(--badge-agent-bg)] text-[var(--badge-agent-text)] border-[rgba(167,139,250,0.2)]',
  tool:       'bg-[var(--badge-tool-bg)] text-[var(--badge-tool-text)] border-transparent',
  retrieval:  'bg-[var(--badge-clean-bg)] text-[var(--badge-clean-text)] border-[rgba(34,197,94,0.2)]',
  default:    'bg-surface-700 text-text-secondary border-[rgb(var(--border))]',
};

export function badgeVariantForSpanType(type: string | null | undefined): BadgeVariant {
  switch (type) {
    case 'llm':       return 'llm';
    case 'chain':     return 'chain';
    case 'agent':     return 'agent';
    case 'tool':      return 'tool';
    case 'retrieval': return 'retrieval';
    default:          return 'default';
  }
}

export function confidenceVariant(
  confidence: string | null | undefined,
  score?: number | null,
): BadgeVariant {
  if (confidence === 'high')      return 'high';
  if (confidence === 'medium')    return 'medium';
  if (confidence === 'ambiguous') return 'ambiguous';
  if (score != null) {
    if (score >= 0.8) return 'high';
    if (score >= 0.4) return 'medium';
  }
  return 'ambiguous';
}

export function Badge({
  variant = 'default',
  children,
  className,
}: {
  variant?: BadgeVariant;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={clsx(
        'inline-flex items-center rounded border px-1.5 py-0.5 font-mono text-[10.5px] font-medium',
        BADGE_STYLES[variant],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function StatusDot({
  status,
  pulse = false,
  className,
}: {
  status: 'success' | 'error' | 'warning' | 'unknown';
  pulse?: boolean;
  className?: string;
}) {
  const color =
    status === 'success' ? 'bg-success' :
    status === 'error'   ? 'bg-danger' :
    status === 'warning' ? 'bg-warning' :
    'bg-text-faint';

  return (
    <span
      className={clsx(
        'inline-block h-[7px] w-[7px] rounded-full shrink-0',
        color,
        pulse && 'animate-live-pulse',
        className,
      )}
    />
  );
}

export function SectionLabel({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={clsx('section-label', className)}>{children}</div>;
}

export function LatencyBar({ ms, width = 64 }: { ms: number | null | undefined; width?: number }) {
  let fill = 'bg-text-faint/40';
  let pct = 10;

  if (ms != null) {
    fill = ms < 500 ? 'bg-success/60' : ms < 2000 ? 'bg-warning/60' : 'bg-danger/60';
    pct = Math.max(8, Math.min(100, (ms / 2000) * 100));
  }

  return (
    <span
      className="inline-flex h-1 rounded-full bg-surface-600 align-middle overflow-hidden"
      style={{ width }}
    >
      <span className={clsx('h-full rounded-full', fill)} style={{ width: `${pct}%` }} />
    </span>
  );
}

export function OutlineButton({
  children,
  className,
  onClick,
  type = 'button',
  disabled = false,
}: {
  children: ReactNode;
  className?: string;
  onClick?: React.MouseEventHandler<HTMLButtonElement>;
  type?: 'button' | 'submit' | 'reset';
  disabled?: boolean;
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={clsx(
        'inline-flex h-7 items-center gap-1.5 rounded-md border border-[rgb(var(--border))]',
        'bg-surface-800 px-2.5 text-[12px] font-medium text-text-secondary',
        'transition-all duration-100',
        'hover:border-[rgb(var(--surface-500))] hover:bg-surface-700/60 hover:text-text-primary',
        'focus:outline-none focus:ring-2 focus:ring-accent/20',
        'disabled:pointer-events-none disabled:opacity-40',
        className,
      )}
    >
      {children}
    </button>
  );
}

export function PrimaryButton({
  children,
  className,
  onClick,
  type = 'button',
  disabled = false,
}: {
  children: ReactNode;
  className?: string;
  onClick?: React.MouseEventHandler<HTMLButtonElement>;
  type?: 'button' | 'submit' | 'reset';
  disabled?: boolean;
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={clsx(
        'inline-flex h-7 items-center justify-center gap-1.5 rounded-md',
        'bg-accent px-2.5 text-[12px] font-medium text-white',
        'shadow-sm shadow-accent/20',
        'transition-all duration-100',
        'hover:bg-accent-hover',
        'focus:outline-none focus:ring-2 focus:ring-accent/30',
        'disabled:pointer-events-none disabled:opacity-40',
        className,
      )}
    >
      {children}
    </button>
  );
}

export function PageHeader({
  title,
  right,
  subtitle,
}: {
  title: string;
  right?: ReactNode;
  subtitle?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-[18px] font-semibold text-text-primary tracking-tight">{title}</h1>
        {subtitle && <div className="mt-1 text-[13px] text-text-muted">{subtitle}</div>}
      </div>
      {right}
    </div>
  );
}

export function AccentRow({
  tone,
  className,
  children,
}: {
  tone: 'error' | 'warning' | 'clean';
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={clsx(
        'border-b border-[rgb(var(--border))] bg-[rgb(var(--surface-800))]',
        tone === 'error'   && 'border-l-[2px] border-l-danger',
        tone === 'warning' && 'border-l-[2px] border-l-warning',
        tone === 'clean'   && 'border-l-[2px] border-l-transparent',
        className,
      )}
    >
      {children}
    </div>
  );
}

export function ConfidenceBadge({
  confidence,
  score,
}: {
  confidence: string | null | undefined;
  score?: number | null;
}) {
  const variant = confidenceVariant(confidence, score);
  const color =
    variant === 'high'   ? 'success' :
    variant === 'medium' ? 'warning' : 'unknown';

  return (
    <span className="inline-flex items-center gap-1.5 text-[11.5px] font-medium text-text-secondary">
      <StatusDot status={color} />
      <span
        className={clsx(
          'capitalize',
          variant === 'high'      && 'text-success',
          variant === 'medium'    && 'text-warning',
          variant === 'ambiguous' && 'text-text-muted',
        )}
      >
        {confidence ?? 'unknown'}
      </span>
    </span>
  );
}
