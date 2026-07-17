import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';

interface DividerProps {
  label?:    ReactNode;
  className?: string;
}

export function Divider({ label, className }: DividerProps) {
  if (!label) {
    return <hr className={cn('border-neutral-200 dark:border-neutral-700', className)} />;
  }

  return (
    <div className={cn('flex items-center gap-3', className)}>
      <span className="flex-1 border-t border-neutral-200 dark:border-neutral-700" aria-hidden />
      <span className="shrink-0 text-xs font-medium text-neutral-400 dark:text-neutral-500">{label}</span>
      <span className="flex-1 border-t border-neutral-200 dark:border-neutral-700" aria-hidden />
    </div>
  );
}
