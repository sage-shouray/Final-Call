import { forwardRef } from 'react';
import type { InputHTMLAttributes, ReactNode } from 'react';
import { cn } from '@/lib/cn';

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?:    string;
  error?:    string;
  hint?:     string;
  icon?:     ReactNode;
  iconRight?: ReactNode;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, hint, icon, iconRight, className, id, ...rest }, ref) => {
    const inputId = id ?? label?.toLowerCase().replace(/\s+/g, '-');

    return (
      <div className="w-full">
        {label && (
          <label
            htmlFor={inputId}
            className="mb-1.5 block text-sm font-medium text-neutral-700 dark:text-neutral-300"
          >
            {label}
          </label>
        )}

        <div className="relative">
          {icon && (
            <span className="pointer-events-none absolute inset-y-0 left-3.5 flex items-center text-neutral-400">
              {icon}
            </span>
          )}

          <input
            ref={ref}
            id={inputId}
            className={cn(
              'block w-full rounded-lg border bg-white px-3.5 py-2.5 text-sm text-neutral-900 dark:bg-neutral-800 dark:text-neutral-100',
              'placeholder:text-neutral-400 dark:placeholder:text-neutral-600 shadow-inner-soft transition-colors',
              'focus:outline-none focus:ring-2',
              error
                ? 'border-danger-400 focus:border-danger-400 focus:ring-danger-200'
                : 'border-neutral-200 focus:border-primary-400 focus:ring-primary-200 dark:border-neutral-700 dark:focus:border-primary-500',
              'disabled:cursor-not-allowed disabled:bg-neutral-50 disabled:text-neutral-500 dark:disabled:bg-neutral-900 dark:disabled:text-neutral-600',
              icon      && 'pl-10',
              iconRight && 'pr-10',
              className,
            )}
            aria-invalid={!!error}
            aria-describedby={error ? `${inputId}-error` : hint ? `${inputId}-hint` : undefined}
            {...rest}
          />

          {iconRight && (
            <span className="pointer-events-none absolute inset-y-0 right-3.5 flex items-center text-neutral-400">
              {iconRight}
            </span>
          )}
        </div>

        {error && (
          <p id={`${inputId}-error`} className="mt-1.5 text-xs text-danger-600">
            {error}
          </p>
        )}
        {!error && hint && (
          <p id={`${inputId}-hint`} className="mt-1.5 text-xs text-neutral-500">
            {hint}
          </p>
        )}
      </div>
    );
  },
);
Input.displayName = 'Input';
