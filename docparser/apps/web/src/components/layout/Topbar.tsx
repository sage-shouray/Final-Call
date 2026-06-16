import type { ReactNode } from 'react';

interface TopbarProps {
  title:     string;
  subtitle?: string;
  children?: ReactNode;
}

export function Topbar({ title, subtitle, children }: TopbarProps) {
  return (
    <header className="sticky top-0 z-20 flex h-14 shrink-0 items-center justify-between border-b border-neutral-200 bg-white px-6">
      <div className="min-w-0">
        <h1
          className="truncate font-display text-[17px] font-semibold leading-tight text-neutral-900"
          style={{ fontFamily: 'var(--ff-display)' }}
        >
          {title}
        </h1>
        {subtitle && (
          <p className="truncate text-xs text-neutral-400">{subtitle}</p>
        )}
      </div>

      {children && (
        <div className="ml-4 flex shrink-0 items-center gap-2">{children}</div>
      )}
    </header>
  );
}
