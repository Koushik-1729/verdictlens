import clsx from 'clsx';

interface SkeletonProps {
  className?: string;
  style?: React.CSSProperties;
}

export function Skeleton({ className, style }: SkeletonProps) {
  return (
    <div
      className={clsx(
        'animate-pulse rounded bg-surface-700/80',
        className
      )}
      style={style}
    />
  );
}

export function SkeletonCard() {
  return (
    <div className="rounded-lg border border-border bg-surface-900 p-4 flex flex-col gap-2">
      <Skeleton className="h-3 w-20" />
      <Skeleton className="h-7 w-24" />
      <Skeleton className="h-3 w-16" />
    </div>
  );
}

export function SkeletonChart({ height = 200 }: { height?: number }) {
  return (
    <div className="bg-surface-900 border border-border rounded-lg p-4">
      <Skeleton className="h-3 w-28 mb-4" />
      <div className="flex items-end gap-1" style={{ height }}>
        {Array.from({ length: 12 }).map((_, i) => (
          <Skeleton
            key={i}
            className="flex-1 rounded-t"
            style={{ height: `${20 + Math.random() * 70}%` }}
          />
        ))}
      </div>
    </div>
  );
}

export function SkeletonRow() {
  return (
    <div className="flex items-center gap-3 px-4 py-3">
      <Skeleton className="w-2.5 h-2.5 rounded-full shrink-0" />
      <Skeleton className="h-3 w-20" />
      <Skeleton className="h-3 flex-1 max-w-[180px]" />
      <Skeleton className="h-3 w-12 ml-auto" />
      <Skeleton className="h-3 w-16" />
    </div>
  );
}

export function SkeletonTableRows({ rows = 8 }: { rows?: number }) {
  return (
    <div className="divide-y divide-border/30">
      {Array.from({ length: rows }).map((_, i) => (
        <SkeletonRow key={i} />
      ))}
    </div>
  );
}

export function DashboardSkeleton() {
  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <Skeleton className="h-6 w-40" />
        <Skeleton className="h-8 w-56 rounded-lg" />
      </div>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
        {Array.from({ length: 5 }).map((_, i) => (
          <SkeletonCard key={i} />
        ))}
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        <div className="lg:col-span-5">
          <SkeletonChart height={200} />
        </div>
        <div className="lg:col-span-4 bg-surface-900 border border-border rounded-lg p-4">
          <Skeleton className="h-3 w-24 mb-4" />
          {Array.from({ length: 7 }).map((_, i) => (
            <div key={i} className="flex items-center gap-2 py-2">
              <Skeleton className="w-2 h-2 rounded-full" />
              <Skeleton className="h-3 flex-1" />
              <Skeleton className="h-3 w-12" />
            </div>
          ))}
        </div>
        <div className="lg:col-span-3 bg-surface-900 border border-border rounded-lg p-4">
          <Skeleton className="h-3 w-24 mb-4" />
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="bg-surface-700/60 rounded-md p-3 mb-2">
              <Skeleton className="h-3 w-full mb-2" />
              <Skeleton className="h-2 w-3/4" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function TracesSkeleton() {
  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <Skeleton className="h-6 w-32" />
        <Skeleton className="h-8 w-56 rounded-lg" />
      </div>
      <div className="flex items-center justify-between">
        <Skeleton className="h-8 w-64 rounded-lg" />
        <Skeleton className="h-5 w-20 rounded" />
      </div>
      <div className="bg-surface-900 border border-border rounded-lg overflow-hidden">
        <div className="px-4 py-3 border-b border-border">
          <Skeleton className="h-3 w-24" />
        </div>
        <SkeletonTableRows rows={10} />
      </div>
    </div>
  );
}

export function CostSkeleton() {
  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <Skeleton className="h-6 w-32" />
        <Skeleton className="h-8 w-56 rounded-lg" />
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <SkeletonCard key={i} />
        ))}
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <SkeletonChart height={240} />
        <SkeletonChart height={240} />
      </div>
    </div>
  );
}
