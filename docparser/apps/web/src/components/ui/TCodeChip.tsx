import { TCode } from '@/types';
import { cn } from '@/lib/cn';

const tCodeColors: Record<TCode, string> = {
  [TCode.MIRO]: 'bg-indigo-50 text-indigo-700 ring-indigo-200 dark:bg-indigo-950 dark:text-indigo-400 dark:ring-indigo-800',
  [TCode.FB60]: 'bg-purple-50 text-purple-700 ring-purple-200 dark:bg-purple-950 dark:text-purple-400 dark:ring-purple-800',
  [TCode.VA01]: 'bg-violet-50 text-violet-700 ring-violet-200 dark:bg-violet-950 dark:text-violet-400 dark:ring-violet-800',
  [TCode.F28]:  'bg-sky-50    text-sky-700    ring-sky-200 dark:bg-sky-950 dark:text-sky-400 dark:ring-sky-800',
  [TCode.MIGO]: 'bg-emerald-50 text-emerald-700 ring-emerald-200 dark:bg-emerald-950 dark:text-emerald-400 dark:ring-emerald-800',
};

interface TCodeChipProps {
  tcode:      TCode | string;
  className?: string;
}

export function TCodeChip({ tcode, className }: TCodeChipProps) {
  const colorCls = tCodeColors[tcode as TCode] ?? 'bg-neutral-50 text-neutral-600 ring-neutral-200 dark:bg-neutral-800 dark:text-neutral-400 dark:ring-neutral-700';

  return (
    <span
      className={cn(
        'inline-flex items-center rounded px-2 py-0.5',
        'font-mono text-xs font-semibold ring-1',
        colorCls,
        className,
      )}
    >
      {tcode}
    </span>
  );
}
