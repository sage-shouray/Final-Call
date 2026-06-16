import type { HTMLAttributes, TdHTMLAttributes, ThHTMLAttributes, ReactNode } from 'react';
import { cn } from '@/lib/cn';

export function Table({ className, children, ...rest }: HTMLAttributes<HTMLTableElement>) {
  return (
    <div className="w-full overflow-x-auto">
      <table
        className={cn('w-full border-collapse text-sm', className)}
        {...rest}
      >
        {children}
      </table>
    </div>
  );
}

export function TableHead({ className, children, ...rest }: HTMLAttributes<HTMLTableSectionElement>) {
  return (
    <thead className={cn('bg-neutral-50 border-b border-neutral-200', className)} {...rest}>
      {children}
    </thead>
  );
}

export function TableBody({ className, children, ...rest }: HTMLAttributes<HTMLTableSectionElement>) {
  return (
    <tbody
      className={cn('divide-y divide-neutral-100', className)}
      {...rest}
    >
      {children}
    </tbody>
  );
}

export function TableRow({ className, children, ...rest }: HTMLAttributes<HTMLTableRowElement>) {
  return (
    <tr
      className={cn('transition-colors hover:bg-neutral-50/70', className)}
      {...rest}
    >
      {children}
    </tr>
  );
}

export function TableHeaderCell({
  className,
  children,
  ...rest
}: ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      className={cn(
        'px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-neutral-500',
        className,
      )}
      {...rest}
    >
      {children}
    </th>
  );
}

export function TableCell({
  className,
  children,
  ...rest
}: TdHTMLAttributes<HTMLTableCellElement>) {
  return (
    <td
      className={cn('px-4 py-3.5 text-neutral-700', className)}
      {...rest}
    >
      {children}
    </td>
  );
}

interface TableEmptyProps {
  colSpan: number;
  message?: string;
  icon?:    ReactNode;
}

export function TableEmpty({ colSpan, message = 'No records found', icon }: TableEmptyProps) {
  return (
    <tr>
      <td colSpan={colSpan} className="px-4 py-12 text-center">
        {icon && <div className="mb-3 flex justify-center text-neutral-300">{icon}</div>}
        <p className="text-sm text-neutral-400">{message}</p>
      </td>
    </tr>
  );
}
