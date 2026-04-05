import clsx from 'clsx';
import { StatusDot } from './ui';

interface Props {
  status: string;
  className?: string;
}

export default function StatusBadge({ status, className }: Props) {
  const tone = status === 'error' ? 'error' : status === 'success' || status === 'ok' ? 'success' : 'unknown';
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[11px] font-medium capitalize',
        tone === 'error'
          ? 'border-danger/20 bg-[var(--badge-victim-bg)] text-[var(--badge-victim-text)]'
          : tone === 'success'
            ? 'border-success/20 bg-[var(--badge-clean-bg)] text-[var(--badge-clean-text)]'
            : 'border-border bg-[var(--badge-ambiguous-bg)] text-[var(--badge-ambiguous-text)]',
        className
      )}
    >
      <StatusDot status={tone} />
      {status}
    </span>
  );
}
