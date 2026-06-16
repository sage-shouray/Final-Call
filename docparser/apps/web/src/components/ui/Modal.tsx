import { useEffect, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { cn } from '@/lib/cn';

export type ModalSize = 'sm' | 'md' | 'lg' | 'xl';

interface ModalProps {
  open:           boolean;
  onClose:        () => void;
  title?:         ReactNode;
  children:       ReactNode;
  footer?:        ReactNode;
  size?:          ModalSize;
  closeOnBackdrop?: boolean;
  className?:     string;
}

const sizeMap: Record<ModalSize, string> = {
  sm: 'max-w-sm',
  md: 'max-w-lg',
  lg: 'max-w-2xl',
  xl: 'max-w-4xl',
};

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])';

export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  size = 'md',
  closeOnBackdrop = true,
  className,
}: ModalProps) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const panel = panelRef.current;
    if (!panel) return;

    const focusable = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE));
    if (focusable.length) focusable[0].focus();

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') { onClose(); return; }
      if (e.key !== 'Tab') return;
      const first = focusable[0];
      const last  = focusable[focusable.length - 1];
      if (e.shiftKey) {
        if (document.activeElement === first) { e.preventDefault(); last?.focus(); }
      } else {
        if (document.activeElement === last) { e.preventDefault(); first?.focus(); }
      }
    }

    document.addEventListener('keydown', onKeyDown);
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = '';
    };
  }, [open, onClose]);

  if (!open) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
    >
      <div
        className="absolute inset-0 bg-neutral-900/50 backdrop-blur-sm"
        onClick={closeOnBackdrop ? onClose : undefined}
        aria-hidden
      />

      <div
        ref={panelRef}
        className={cn(
          'relative z-10 w-full rounded-2xl bg-white shadow-2xl ring-1 ring-neutral-200/50',
          'flex flex-col max-h-[90vh]',
          sizeMap[size],
          className,
        )}
      >
        {title && (
          <div className="flex shrink-0 items-center justify-between px-6 py-4 border-b border-neutral-100">
            <h2 className="text-base font-semibold text-neutral-900">{title}</h2>
            <button
              type="button"
              onClick={onClose}
              className="rounded-md p-1 text-neutral-400 hover:bg-neutral-100 hover:text-neutral-600 transition-colors"
              aria-label="Close"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        )}

        <div className="flex-1 overflow-y-auto px-6 py-5">{children}</div>

        {footer && (
          <div className="shrink-0 flex items-center justify-end gap-2 border-t border-neutral-100 px-6 py-4 bg-neutral-50/50 rounded-b-2xl">
            {footer}
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}
