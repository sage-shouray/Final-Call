import { cn } from '@/lib/cn';

export type SpinnerSize = 'sm' | 'md' | 'lg';

const sizeCls: Record<SpinnerSize, string> = {
  sm: 'h-3.5 w-3.5 border-[1.5px]',
  md: 'h-5   w-5   border-2',
  lg: 'h-8   w-8   border-[2.5px]',
};

interface SpinnerProps {
  size?:      SpinnerSize;
  className?: string;
}

export function Spinner({ size = 'md', className }: SpinnerProps) {
  return (
    <span
      role="status"
      aria-label="Loading"
      className={cn(
        'inline-block animate-spin rounded-full border-current border-r-transparent',
        sizeCls[size],
        className,
      )}
    />
  );
}
