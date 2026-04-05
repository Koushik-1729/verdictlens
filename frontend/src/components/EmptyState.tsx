import type { ReactNode } from 'react';

interface Props {
  icon: ReactNode;
  title: string;
  description: string;
  action?: ReactNode;
}

export default function EmptyState({ icon, title, description, action }: Props) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border bg-surface-900 px-6 py-14 text-center">
      <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-full bg-surface-800 text-text-muted">
        {icon}
      </div>
      <h3 className="text-[16px] font-semibold text-text-primary">{title}</h3>
      <p className="mt-1 max-w-sm text-[14px] leading-relaxed text-text-secondary">{description}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
