import { AlertTriangle, CheckCircle2, TrendingUp } from 'lucide-react';
import clsx from 'clsx';
import { StatusDot } from './ui';

export type SystemState = 'healthy' | 'error' | 'warning';

interface Props {
  state: SystemState;
  message: string;
  detail?: string;
}

const STYLES: Record<SystemState, { bg: string; border: string; icon: typeof CheckCircle2; iconColor: string; dot: string }> = {
  healthy: {
    bg: 'bg-surface-800',
    border: 'border-border',
    icon: CheckCircle2,
    iconColor: 'text-success',
    dot: 'success',
  },
  error: {
    bg: 'bg-danger/[0.03]',
    border: 'border-danger/40',
    icon: AlertTriangle,
    iconColor: 'text-danger',
    dot: 'error',
  },
  warning: {
    bg: 'bg-warning/[0.04]',
    border: 'border-warning/40',
    icon: TrendingUp,
    iconColor: 'text-warning',
    dot: 'warning',
  },
};

export default function SystemStatusBar({ state, message, detail }: Props) {
  const s = STYLES[state];
  const Icon = s.icon;

  return (
    <div className={clsx('flex items-center gap-3 rounded-lg border px-5 py-3', s.bg, s.border)}>
      <Icon className={clsx('h-4 w-4 shrink-0', s.iconColor)} />
      <StatusDot status={s.dot as 'success' | 'error' | 'warning'} />
      <span className="text-[13px] font-medium text-text-primary">{message}</span>
      {detail && <span className="ml-1 text-[12px] text-text-secondary">{detail}</span>}
    </div>
  );
}
