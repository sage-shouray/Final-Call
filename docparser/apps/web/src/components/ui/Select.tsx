import { forwardRef } from 'react';
import type { SelectHTMLAttributes, ReactNode } from 'react';
import { ChevronDown } from 'lucide-react';
import { cn } from '@/lib/cn';

interface SelectOption {
  value: string;
  label: string;
}

interface SelectGroup {
  label:   string;
  options: SelectOption[];
}

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?:    string;
  error?:    string;
  hint?:     string;
  options?:  SelectOption[];
  groups?:   SelectGroup[];
  placeholder?: string;
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ label, error, hint, options, groups, placeholder, className, id, children, ...rest }, ref) => {
    const selectId = id ?? label?.toLowerCase().replace(/\s+/g, '-');

    function renderOptions(): ReactNode {
      if (children) return children;
      if (groups) {
        return groups.map((g) => (
          <optgroup key={g.label} label={g.label}>
            {g.options.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </optgroup>
        ));
      }
      return options?.map((o) => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ));
    }

    return (
      <div className="w-full">
        {label && (
          <label htmlFor={selectId} className="mb-1.5 block text-sm font-medium text-neutral-700 dark:text-neutral-300">
            {label}
          </label>
        )}

        <div className="relative">
          <select
            ref={ref}
            id={selectId}
            className={cn(
              'w-full appearance-none rounded-lg border bg-white px-3.5 py-2.5 pr-9 dark:bg-neutral-800',
              'text-sm text-neutral-900 shadow-inner-soft transition-colors dark:text-neutral-100',
              'focus:outline-none focus:ring-2 cursor-pointer',
              error
                ? 'border-danger-400 focus:border-danger-400 focus:ring-danger-200'
                : 'border-neutral-200 focus:border-primary-400 focus:ring-primary-200 dark:border-neutral-700 dark:focus:border-primary-500',
              'disabled:cursor-not-allowed disabled:bg-neutral-50 disabled:text-neutral-500 dark:disabled:bg-neutral-900 dark:disabled:text-neutral-600',
              className,
            )}
            aria-invalid={!!error}
            {...rest}
          >
            {placeholder && <option value="">{placeholder}</option>}
            {renderOptions()}
          </select>

          <ChevronDown
            className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-neutral-400 dark:text-neutral-500"
            aria-hidden
          />
        </div>

        {error && <p className="mt-1.5 text-xs text-danger-600">{error}</p>}
        {!error && hint && <p className="mt-1.5 text-xs text-neutral-500 dark:text-neutral-500">{hint}</p>}
      </div>
    );
  },
);
Select.displayName = 'Select';
