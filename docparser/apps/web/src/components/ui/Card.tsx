import type { HTMLAttributes, ReactNode } from 'react';
import { cn } from '@/lib/cn';

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
}

export function Card({ className, children, ...rest }: CardProps) {
  return (
    <div
      className={cn('rounded-xl bg-white shadow-soft ring-1 ring-neutral-200/60 dark:bg-neutral-800 dark:ring-neutral-700/60 dark:shadow-none', className)}
      {...rest}
    >
      {children}
    </div>
  );
}

export function CardHeader({ className, children, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('flex items-center justify-between px-6 py-4 border-b border-neutral-100 dark:border-neutral-700', className)}
      {...rest}
    >
      {children}
    </div>
  );
}

export function CardBody({ className, children, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn('px-6 py-5', className)} {...rest}>
      {children}
    </div>
  );
}

export function CardFooter({ className, children, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('flex items-center px-6 py-4 border-t border-neutral-100 bg-neutral-50/50 rounded-b-xl dark:border-neutral-700 dark:bg-neutral-900/50', className)}
      {...rest}
    >
      {children}
    </div>
  );
}
