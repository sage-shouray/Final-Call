import { TCode } from '@/types';
import { cn } from '@/lib/cn';

const tCodeColors: Record<TCode, string> = {
  [TCode.MIRO]: 'bg-indigo-50 text-indigo-700 ring-indigo-200',
  [TCode.FB60]: 'bg-purple-50 text-purple-700 ring-purple-200',
  [TCode.FF67]: 'bg-violet-50 text-violet-700 ring-violet-200',
  [TCode.F28]:  'bg-sky-50    text-sky-700    ring-sky-200',
  [TCode.MIGO]: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
};

interface TCodeChipProps {
  tcode:      TCode | string;
  className?: string;
}

export function TCodeChip({ tcode, className }: TCodeChipProps) {
  const colorCls = tCodeColors[tcode as TCode] ?? 'bg-neutral-50 text-neutral-600 ring-neutral-200';

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
