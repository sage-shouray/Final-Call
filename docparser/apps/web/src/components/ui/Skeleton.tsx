import { cn } from '@/lib/cn';

interface SkeletonProps {
  className?: string;
  lines?:     number;
  circle?:    boolean;
}

export function Skeleton({ className, lines, circle = false }: SkeletonProps) {
  if (lines && lines > 1) {
    return (
      <div className="space-y-2.5">
        {Array.from({ length: lines }, (_, i) => (
          <div
            key={i}
            className={cn(
              'animate-pulse rounded-md bg-neutral-200/80 dark:bg-neutral-700/80',
              i === lines - 1 ? 'w-3/4' : 'w-full',
              'h-4',
            )}
          />
        ))}
      </div>
    );
  }

  return (
    <div
      className={cn(
        'animate-pulse bg-neutral-200/80 dark:bg-neutral-700/80',
        circle ? 'rounded-full' : 'rounded-md',
        className,
      )}
    />
  );
}

export function SkeletonCard() {
  return (
    <div className="rounded-xl bg-white shadow-soft ring-1 ring-neutral-200/60 p-6 space-y-4 dark:bg-neutral-800 dark:ring-neutral-700/60">
      <div className="flex items-center gap-3">
        <Skeleton circle className="h-10 w-10 shrink-0" />
        <div className="flex-1 space-y-2">
          <Skeleton className="h-4 w-1/2" />
          <Skeleton className="h-3 w-1/3" />
        </div>
      </div>
      <Skeleton lines={3} />
      <div className="flex gap-2">
        <Skeleton className="h-7 w-16 rounded-full" />
        <Skeleton className="h-7 w-16 rounded-full" />
      </div>
    </div>
  );
}

export function SkeletonRow() {
  return (
    <div className="flex items-center gap-4 px-4 py-3.5 border-b border-neutral-100 last:border-0 dark:border-neutral-800">
      <Skeleton className="h-4 w-24 shrink-0" />
      <Skeleton className="h-4 flex-1" />
      <Skeleton className="h-6 w-16 rounded-full shrink-0" />
      <Skeleton className="h-4 w-20 shrink-0" />
    </div>
  );
}
