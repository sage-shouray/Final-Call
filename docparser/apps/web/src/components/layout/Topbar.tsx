import type { ReactNode } from 'react';

interface TopbarProps {
  title:     string;
  subtitle?: string;
  children?: ReactNode;
}

export function Topbar({ title, subtitle, children }: TopbarProps) {
  return (
    <header className="sticky top-0 z-20 flex h-14 shrink-0 items-center justify-between bg-white px-6 shadow-[0_1px_0_0_rgba(15,23,42,0.06)] dark:bg-neutral-900 dark:shadow-[0_1px_0_0_rgba(255,255,255,0.06)]">
      <div className="min-w-0">
        <h1
          className="truncate text-[17px] font-semibold leading-tight text-slate-900 dark:text-white"
          style={{ fontFamily: 'var(--ff-display)' }}
        >
          {title}
        </h1>
        {subtitle && (
          <p className="truncate text-xs text-slate-400 dark:text-neutral-500">{subtitle}</p>
        )}
      </div>

      {children && (
        <div className="ml-4 flex shrink-0 items-center gap-2">{children}</div>
      )}
    </header>
  );
}
