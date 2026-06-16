import { forwardRef } from 'react';
import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { cn } from '@/lib/cn';
import { Spinner } from './Spinner';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
export type ButtonSize    = 'sm' | 'md' | 'lg';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?:  ButtonVariant;
  size?:     ButtonSize;
  loading?:  boolean;
  icon?:     ReactNode;
  iconRight?: ReactNode;
}

const variantCls: Record<ButtonVariant, string> = {
  primary:   'bg-primary-600 text-white shadow-soft-sm hover:bg-primary-700 active:bg-primary-800 focus-visible:outline-primary-500',
  secondary: 'bg-white text-neutral-700 shadow-soft-sm ring-1 ring-neutral-200 hover:bg-neutral-50 active:bg-neutral-100 focus-visible:outline-primary-500',
  ghost:     'text-neutral-600 hover:bg-neutral-100 active:bg-neutral-200 focus-visible:outline-primary-500',
  danger:    'bg-danger-600 text-white shadow-soft-sm hover:bg-danger-700 active:bg-danger-800 focus-visible:outline-danger-500',
};

const sizeCls: Record<ButtonSize, string> = {
  sm: 'h-8  px-3   text-xs  gap-1.5',
  md: 'h-9  px-4   text-sm  gap-2',
  lg: 'h-11 px-5   text-base gap-2',
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      variant  = 'primary',
      size     = 'md',
      loading  = false,
      icon,
      iconRight,
      disabled,
      className,
      children,
      ...rest
    },
    ref,
  ) => (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cn(
        'inline-flex items-center justify-center rounded-lg font-medium transition-all duration-150',
        'focus-visible:outline-2 focus-visible:outline-offset-2',
        'disabled:pointer-events-none disabled:opacity-50 select-none',
        variantCls[variant],
        sizeCls[size],
        className,
      )}
      {...rest}
    >
      {loading ? (
        <Spinner size="sm" className="shrink-0" />
      ) : (
        icon && <span className="shrink-0">{icon}</span>
      )}
      {children}
      {!loading && iconRight && <span className="shrink-0">{iconRight}</span>}
    </button>
  ),
);
Button.displayName = 'Button';
