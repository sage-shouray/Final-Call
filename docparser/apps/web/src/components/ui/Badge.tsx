import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';

export type BadgeVariant = 'success' | 'warning' | 'error' | 'info' | 'neutral';

interface BadgeProps {
  variant?:   BadgeVariant;
  dot?:       boolean;
  children:   ReactNode;
  className?: string;
}

const variantCls: Record<BadgeVariant, string> = {
  success: 'bg-success-100  text-success-700  dark:bg-success-900 dark:text-success-300',
  warning: 'bg-warning-100  text-warning-700  dark:bg-warning-900 dark:text-warning-300',
  error:   'bg-danger-100   text-danger-700   dark:bg-danger-900 dark:text-danger-300',
  info:    'bg-primary-100  text-primary-700  dark:bg-primary-950 dark:text-primary-300',
  neutral: 'bg-neutral-100  text-neutral-600  dark:bg-neutral-800 dark:text-neutral-400',
};

const dotCls: Record<BadgeVariant, string> = {
  success: 'bg-success-500',
  warning: 'bg-warning-500',
  error:   'bg-danger-500',
  info:    'bg-primary-500',
  neutral: 'bg-neutral-400',
};

export function Badge({ variant = 'neutral', dot = false, children, className }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium',
        variantCls[variant],
        className,
      )}
    >
      {dot && (
        <span
          className={cn('h-1.5 w-1.5 shrink-0 rounded-full', dotCls[variant])}
          aria-hidden
        />
      )}
      {children}
    </span>
  );
}
