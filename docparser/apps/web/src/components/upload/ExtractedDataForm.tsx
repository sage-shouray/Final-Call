import type { ExtractedData, LineItem } from '@/types';
import { cn } from '@/lib/cn';

// ─── Confidence badge ─────────────────────────────────────────────────────────

function ConfidenceBadge({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const cls =
    pct >= 85 ? 'bg-green-100 text-green-700' :
    pct >= 60 ? 'bg-amber-100 text-amber-700' :
                'bg-red-100   text-red-700';
  return (
    <span className={cn('inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold', cls)}>
      {pct}% confidence
    </span>
  );
}

// ─── Field row ────────────────────────────────────────────────────────────────

interface FieldProps {
  label:    string;
  value:    string;
  editable?: boolean;
  onChange?: (v: string) => void;
}

function Field({ label, value, editable, onChange }: FieldProps) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <label className="text-[11px] font-semibold uppercase tracking-wider text-neutral-400">
          {label}
        </label>
        {editable && (
          <span className="text-[10px] font-medium text-indigo-500">Editable</span>
        )}
      </div>
      {editable ? (
        <input
          type="text"
          value={value}
          onChange={(e) => onChange?.(e.target.value)}
          className={cn(
            'block w-full rounded-md border px-2.5 py-1.5 text-sm text-neutral-900',
            'border-indigo-300 bg-white',
            'focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200',
            'transition-colors',
          )}
        />
      ) : (
        <p className="rounded-md bg-neutral-50 px-2.5 py-1.5 text-sm text-neutral-700 ring-1 ring-neutral-100">
          {value || <span className="text-neutral-300">—</span>}
        </p>
      )}
    </div>
  );
}

// ─── Line items table ─────────────────────────────────────────────────────────

function LineItemsTable({ items }: { items: LineItem[] }) {
  const cols: { key: keyof LineItem; label: string; mono?: boolean; right?: boolean }[] = [
    { key: 'line_number',   label: 'Line'       },
    { key: 'material_code', label: 'Material',  mono: true },
    { key: 'description',   label: 'Description' },
    { key: 'quantity',      label: 'Qty',       right: true },
    { key: 'uom',           label: 'UOM'        },
    { key: 'unit_rate',     label: 'Unit Rate', mono: true, right: true },
    { key: 'amount',        label: 'Amount',    mono: true, right: true },
    { key: 'tax_code',      label: 'Tax Code'   },
    { key: 'tax_amount',    label: 'Tax Amt',   mono: true, right: true },
  ];

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[700px] text-xs">
        <thead className="sticky top-0 z-10 bg-neutral-50">
          <tr className="border-b border-neutral-200">
            {cols.map((c) => (
              <th
                key={c.key}
                className={cn(
                  'px-3 py-2 text-[10px] font-semibold uppercase tracking-wider text-neutral-400',
                  c.right ? 'text-right' : 'text-left',
                )}
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {items.map((item, i) => (
            <tr
              key={i}
              className="border-b border-neutral-100 transition-colors hover:bg-neutral-50/70"
            >
              {cols.map((c) => (
                <td
                  key={c.key}
                  className={cn(
                    'px-3 py-2.5 text-neutral-700',
                    c.right && 'text-right',
                    c.mono  && 'font-mono text-[10px] tabular-nums',
                  )}
                >
                  {item[c.key] || '—'}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

interface ExtractedDataFormProps {
  data:        ExtractedData;
  onDataChange: (updated: ExtractedData) => void;
  onValidate:  () => void;
  isValidating: boolean;
}

export function ExtractedDataForm({
  data, onDataChange, onValidate, isValidating,
}: ExtractedDataFormProps) {
  function set<K extends keyof ExtractedData>(key: K, val: ExtractedData[K]) {
    onDataChange({ ...data, [key]: val });
  }

  return (
    <div className="space-y-6">
      {/* Header section */}
      <div className="rounded-xl border border-neutral-200 bg-white">
        <div className="flex items-center justify-between border-b border-neutral-100 px-5 py-3.5">
          <h3 className="text-sm font-semibold text-neutral-800">Header Fields</h3>
          <ConfidenceBadge score={data.confidence_score} />
        </div>
        <div className="grid grid-cols-1 gap-4 p-5 sm:grid-cols-2 lg:grid-cols-3">
          {/* Editable */}
          <Field label="Invoice No"    value={data.invoice_no}    editable onChange={(v) => set('invoice_no', v)} />
          <Field label="Invoice Date"  value={data.invoice_date}  editable onChange={(v) => set('invoice_date', v)} />
          <Field label="PO Number"     value={data.po_number}     editable onChange={(v) => set('po_number', v)} />
          {/* Read-only */}
          <Field label="Vendor Name"   value={data.vendor_name}   />
          <Field label="Vendor GSTIN"  value={data.vendor_gstin}  />
          <Field label="Vendor ID"     value={data.vendor_id}     />
          <Field label="Gross Amount"  value={data.gross_amount}  />
          <Field label="Tax Amount"    value={data.tax_amount}    />
          <Field label="Net Amount"    value={data.net_amount}    />
          <Field label="Currency"      value={data.currency}      />
          <Field label="Payment Terms" value={data.payment_terms} />
          <Field label="Ship To"       value={data.ship_to_name}  />
        </div>
      </div>

      {/* Line items section */}
      {data.line_items?.length > 0 && (
        <div className="overflow-hidden rounded-xl border border-neutral-200 bg-white">
          <div className="border-b border-neutral-100 px-5 py-3.5">
            <h3 className="text-sm font-semibold text-neutral-800">
              Line Items
              <span className="ml-2 rounded-full bg-neutral-100 px-2 py-0.5 text-xs font-medium text-neutral-500">
                {data.line_items.length}
              </span>
            </h3>
          </div>
          <LineItemsTable items={data.line_items} />
        </div>
      )}

      {/* Action bar */}
      <div className="sticky bottom-0 flex items-center justify-between rounded-xl border border-neutral-200 bg-white px-5 py-3.5 shadow-lg ring-1 ring-neutral-200/60">
        <p className="text-sm text-neutral-500">
          <span className="font-medium text-neutral-700">PO {data.po_number || '—'}</span>
          {' '}will be validated against SAP
        </p>
        <button
          type="button"
          onClick={onValidate}
          disabled={isValidating}
          className={cn(
            'inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-soft-sm',
            'hover:bg-indigo-700 active:bg-indigo-800 transition-colors',
            'disabled:opacity-60 disabled:pointer-events-none',
          )}
        >
          {isValidating ? (
            <>
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
              Validating…
            </>
          ) : 'Validate with SAP'}
        </button>
      </div>
    </div>
  );
}
