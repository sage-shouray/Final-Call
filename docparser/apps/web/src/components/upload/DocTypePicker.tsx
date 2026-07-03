import { useEffect, useRef } from 'react';
import { FileText, ClipboardList, FileCheck, Package, Truck } from 'lucide-react';
import { DocumentType, TCode } from '@/types';
import { cn } from '@/lib/cn';

interface DocTypeOption {
  type:        DocumentType;
  label:       string;
  tcode:       TCode;
  tcodeLabel?: string;
  icon:        React.ElementType;
  active:      boolean;
}

const OPTIONS: DocTypeOption[] = [
  { type: DocumentType.VENDOR_INVOICE,  label: 'Vendor Invoice',  tcode: TCode.MIRO, icon: FileText,  active: true,  tcodeLabel: 'PO / Non-PO' },
  { type: DocumentType.SALES_ORDER,     label: 'Sales Order',     tcode: TCode.VA01, icon: ClipboardList, active: true  },
  { type: DocumentType.PAYMENT_ADVICE,  label: 'Payment Advice',  tcode: TCode.F28,  icon: FileCheck, active: false },
  { type: DocumentType.GOODS_RECEIPT,   label: 'Goods Receipt',   tcode: TCode.MIGO, icon: Package,   active: true  },
  { type: DocumentType.FREIGHT_INVOICE, label: 'Freight Invoice', tcode: TCode.MIRO, icon: Truck,     active: true  },
];

interface DocTypePickerProps {
  value:    DocumentType;
  onChange: (type: DocumentType) => void;
}

export function DocTypePicker({ value, onChange }: DocTypePickerProps) {
  const listRef  = useRef<HTMLDivElement>(null);
  const activeOptions = OPTIONS.filter((o) => o.active);

  function handleKeyDown(e: React.KeyboardEvent, currentType: DocumentType) {
    const activeIdx = activeOptions.findIndex((o) => o.type === currentType);
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
      e.preventDefault();
      const next = activeOptions[(activeIdx + 1) % activeOptions.length];
      onChange(next.type);
    }
    if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
      e.preventDefault();
      const prev = activeOptions[(activeIdx - 1 + activeOptions.length) % activeOptions.length];
      onChange(prev.type);
    }
  }

  // Keep focused card when selection changes via keyboard
  const focusRef = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    focusRef.current?.focus({ preventScroll: true });
  }, [value]);

  return (
    <div ref={listRef} className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      {OPTIONS.map((opt) => {
        const selected = value === opt.type;
        const Icon     = opt.icon;

        if (!opt.active) {
          return (
            <div
              key={opt.type}
              className="relative flex cursor-not-allowed flex-col items-center gap-2.5 rounded-xl border border-neutral-200 bg-white p-4 text-center opacity-40"
              title={`${opt.label} — coming soon`}
            >
              <span className="absolute right-2 top-2 rounded-full bg-neutral-100 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-neutral-400">
                Soon
              </span>
              <div className="flex h-[38px] w-[38px] items-center justify-center rounded-lg bg-neutral-100">
                <Icon className="h-5 w-5 text-neutral-400" />
              </div>
              <div>
                <p className="text-xs font-semibold text-neutral-600">{opt.label}</p>
                <p className="mt-0.5 font-mono text-[10px] text-neutral-400">{opt.tcodeLabel ?? opt.tcode}</p>
              </div>
            </div>
          );
        }

        return (
          <button
            key={opt.type}
            ref={selected ? focusRef : undefined}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => onChange(opt.type)}
            onKeyDown={(e) => handleKeyDown(e, opt.type)}
            className={cn(
              'relative flex flex-col items-center gap-2.5 rounded-xl border-2 p-4 text-center',
              'transition-all duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 focus-visible:ring-offset-2',
              selected
                ? 'border-indigo-500 bg-indigo-50/60'
                : 'border-neutral-200 bg-white hover:border-indigo-200 hover:bg-indigo-50/30',
            )}
          >
            <div className={cn(
              'flex h-[38px] w-[38px] items-center justify-center rounded-lg transition-colors duration-150',
              selected ? 'bg-indigo-100' : 'bg-neutral-100',
            )}>
              <Icon className={cn('h-5 w-5 transition-colors duration-150', selected ? 'text-indigo-600' : 'text-neutral-400')} />
            </div>
            <div>
              <p className={cn('text-xs font-semibold', selected ? 'text-indigo-700' : 'text-neutral-700')}>
                {opt.label}
              </p>
              <p className="mt-0.5 font-mono text-[10px] text-neutral-400">{opt.tcodeLabel ?? opt.tcode}</p>
            </div>
          </button>
        );
      })}
    </div>
  );
}
