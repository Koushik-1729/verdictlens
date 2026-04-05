import clsx from 'clsx';
import type { ReactNode } from 'react';

interface Props {
  label: string;
  value: string | number;
  icon?: ReactNode;
  sub?: string;
  accent?: 'blue' | 'green' | 'yellow' | 'red' | 'cyan' | 'purple';
  className?: string;
}

const ACCENT_MAP = {
  blue: 'text-accent',
  green: 'text-success',
  yellow: 'text-warning',
  red: 'text-danger',
  cyan: 'text-accent',
  purple: 'text-accent',
} as const;

const ACCENT_BORDER = {
  blue: 'border-border',
  green: 'border-border',
  yellow: 'border-border',
  red: 'border-border',
  cyan: 'border-border',
  purple: 'border-border',
} as const;

export default function MetricCard({ label, value, icon, sub, accent, className }: Props) {
  const accentColor = accent ? ACCENT_MAP[accent] : 'text-text-muted';
  const borderColor = accent ? ACCENT_BORDER[accent] : 'border-border';

  return (
    <div
      className={clsx(
        'rounded-lg border bg-surface-900 p-4 flex flex-col gap-1.5',
        borderColor,
        className
      )}
    >
      <div
        className={clsx(
          'section-label flex items-center gap-1.5',
          accentColor
        )}
      >
        {icon}
        {label}
      </div>
      <div className="text-[24px] font-semibold text-text-primary tabular-nums">{value}</div>
      {sub && <div className="text-[12px] text-text-secondary">{sub}</div>}
    </div>
  );
}
