import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';

type TooltipSide = 'top' | 'bottom' | 'left' | 'right';

interface TooltipProps {
  content:    string;
  children:   ReactNode;
  side?:      TooltipSide;
  className?: string;
}

const sideClasses: Record<TooltipSide, { container: string; tip: string }> = {
  top: {
    container: 'bottom-full left-1/2 -translate-x-1/2 mb-2',
    tip:       'top-full left-1/2 -translate-x-1/2 border-t-neutral-800 border-t-4 border-x-4 border-x-transparent',
  },
  bottom: {
    container: 'top-full left-1/2 -translate-x-1/2 mt-2',
    tip:       'bottom-full left-1/2 -translate-x-1/2 border-b-neutral-800 border-b-4 border-x-4 border-x-transparent',
  },
  left: {
    container: 'right-full top-1/2 -translate-y-1/2 mr-2',
    tip:       'left-full top-1/2 -translate-y-1/2 border-l-neutral-800 border-l-4 border-y-4 border-y-transparent',
  },
  right: {
    container: 'left-full top-1/2 -translate-y-1/2 ml-2',
    tip:       'right-full top-1/2 -translate-y-1/2 border-r-neutral-800 border-r-4 border-y-4 border-y-transparent',
  },
};

export function Tooltip({ content, children, side = 'top', className }: TooltipProps) {
  const { container, tip } = sideClasses[side];

  return (
    <span className="group relative inline-flex">
      {children}
      <span
        role="tooltip"
        className={cn(
          'pointer-events-none absolute z-50 whitespace-nowrap rounded-md',
          'bg-neutral-800 px-2.5 py-1.5 text-xs font-medium text-white shadow-lg',
          'opacity-0 transition-opacity duration-150 group-hover:opacity-100',
          container,
          className,
        )}
      >
        {content}
        <span className={cn('absolute h-0 w-0 border-solid', tip)} aria-hidden />
      </span>
    </span>
  );
}
