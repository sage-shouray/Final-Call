import { useState } from 'react';
import { Plus, Trash2, AlertCircle, Loader2 } from 'lucide-react';
import { cn } from '@/lib/cn';
import type { ExtractedData, FB60FormData, FB60InvoiceItem } from '@/types';

interface Props {
  extracted:    ExtractedData | null;
  isPosting:    boolean;
  onPost:       (data: FB60FormData) => void;
}

function toYYYYMMDD(dateStr: string): string {
  if (!dateStr) return '';
  // Handle DD-MM-YYYY or DD/MM/YYYY → YYYYMMDD
  const parts = dateStr.replace(/\//g, '-').split('-');
  if (parts.length === 3 && parts[0].length === 2) {
    return `${parts[2]}${parts[1].padStart(2,'0')}${parts[0].padStart(2,'0')}`;
  }
  // Already YYYYMMDD or other format — strip dashes
  return dateStr.replace(/-/g, '');
}

function todayYYYYMMDD(): string {
  const d = new Date();
  return `${d.getFullYear()}${String(d.getMonth()+1).padStart(2,'0')}${String(d.getDate()).padStart(2,'0')}`;
}

const EMPTY_ITEM = (): FB60InvoiceItem => ({
  line_no:        1,
  gl:             '',
  amount:         0,
  tax_code:       '',
  business_place: '',
  value_date:     todayYYYYMMDD(),
  assignment_no:  '',
  text:           '',
  cost_center:    '',
  profit_center:  '',
  special_gl:     '',
  baseline_date:  todayYYYYMMDD(),
  wht_tax:        '',
});

function Field({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-medium text-neutral-600">
        {label}{required && <span className="ml-0.5 text-red-500">*</span>}
      </label>
      {children}
    </div>
  );
}

const inputCls = (error?: boolean) => cn(
  'h-9 w-full rounded-lg border px-3 text-sm text-neutral-800 placeholder:text-neutral-400 focus:outline-none focus:ring-2 focus:ring-primary-200 transition-colors',
  error ? 'border-red-300 bg-red-50' : 'border-neutral-200 bg-white hover:border-neutral-300',
);

export function NonPOInvoiceForm({ extracted, isPosting, onPost }: Props) {
  const today = todayYYYYMMDD();

  const [form, setForm] = useState<Omit<FB60FormData, 'invoice_items'>>({
    invoice_doc_date: extracted?.invoice_date ? toYYYYMMDD(extracted.invoice_date) : today,
    document_type:    'KR',
    company_code:     '',
    posting_date:     today,
    currency:         extracted?.currency || 'INR',
    reference:        extracted?.invoice_no || '',
    header_text:      extracted?.vendor_name || '',
    vendor:           extracted?.vendor_id || '',
  });

  const [items, setItems] = useState<FB60InvoiceItem[]>(() => {
    // Pre-fill first item from OCR gross amount if available
    const gross = extracted?.gross_amount ? parseFloat(String(extracted.gross_amount)) : 0;
    const item = EMPTY_ITEM();
    item.amount = gross;
    item.text = extracted?.vendor_name || '';
    return [item];
  });

  const [errors, setErrors] = useState<Record<string, boolean>>({});

  function setHeader<K extends keyof typeof form>(k: K, v: string) {
    setForm(f => ({ ...f, [k]: v }));
    if (errors[k]) setErrors(e => ({ ...e, [k]: false }));
  }

  function setItem(idx: number, key: keyof FB60InvoiceItem, val: string | number) {
    setItems(prev => prev.map((item, i) =>
      i === idx ? { ...item, [key]: val } : item
    ));
    if (errors[`item_${idx}_${key}`]) {
      setErrors(e => ({ ...e, [`item_${idx}_${key}`]: false }));
    }
  }

  function addItem() {
    setItems(prev => [...prev, { ...EMPTY_ITEM(), line_no: prev.length + 1 }]);
  }

  function removeItem(idx: number) {
    setItems(prev => prev.filter((_, i) => i !== idx).map((item, i) => ({ ...item, line_no: i + 1 })));
  }

  function validate(): boolean {
    const newErrors: Record<string, boolean> = {};
    if (!form.company_code.trim()) newErrors.company_code = true;
    if (!form.vendor.trim())       newErrors.vendor = true;
    if (!form.invoice_doc_date)    newErrors.invoice_doc_date = true;
    if (!form.posting_date)        newErrors.posting_date = true;
    if (!form.document_type.trim()) newErrors.document_type = true;

    items.forEach((item, idx) => {
      if (!item.gl.trim())           newErrors[`item_${idx}_gl`] = true;
      if (!item.baseline_date)       newErrors[`item_${idx}_baseline_date`] = true;
      if (item.amount === 0)         newErrors[`item_${idx}_amount`] = true;
    });

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  }

  function handleSubmit() {
    if (!validate()) return;
    onPost({ ...form, invoice_items: items });
  }

  const hasErrors = Object.values(errors).some(Boolean);

  return (
    <div className="space-y-5">
      {/* Header Section */}
      <div className="rounded-xl border border-neutral-200 bg-white overflow-hidden">
        <div className="border-b border-neutral-100 px-5 py-3.5">
          <h3 className="text-sm font-semibold text-neutral-800">Invoice Header</h3>
        </div>
        <div className="grid grid-cols-2 gap-4 p-5 sm:grid-cols-4">
          <Field label="Document Type" required>
            <input className={inputCls(errors.document_type)} value={form.document_type}
              onChange={e => setHeader('document_type', e.target.value)} placeholder="KR" />
          </Field>
          <Field label="Company Code" required>
            <input className={inputCls(errors.company_code)} value={form.company_code}
              onChange={e => setHeader('company_code', e.target.value)} placeholder="SSDN" />
          </Field>
          <Field label="Vendor ID" required>
            <input className={inputCls(errors.vendor)} value={form.vendor}
              onChange={e => setHeader('vendor', e.target.value)} placeholder="1120250000" />
          </Field>
          <Field label="Currency">
            <input className={inputCls()} value={form.currency}
              onChange={e => setHeader('currency', e.target.value)} placeholder="INR" />
          </Field>
          <Field label="Invoice Doc Date" required>
            <input className={inputCls(errors.invoice_doc_date)} value={form.invoice_doc_date}
              onChange={e => setHeader('invoice_doc_date', e.target.value)} placeholder="YYYYMMDD" />
          </Field>
          <Field label="Posting Date" required>
            <input className={inputCls(errors.posting_date)} value={form.posting_date}
              onChange={e => setHeader('posting_date', e.target.value)} placeholder="YYYYMMDD" />
          </Field>
          <Field label="Reference">
            <input className={inputCls()} value={form.reference}
              onChange={e => setHeader('reference', e.target.value)} placeholder="Invoice No." />
          </Field>
          <Field label="Header Text">
            <input className={inputCls()} value={form.header_text}
              onChange={e => setHeader('header_text', e.target.value)} placeholder="Description" />
          </Field>
        </div>
      </div>

      {/* Line Items Section */}
      <div className="rounded-xl border border-neutral-200 bg-white overflow-hidden">
        <div className="flex items-center justify-between border-b border-neutral-100 px-5 py-3.5">
          <h3 className="text-sm font-semibold text-neutral-800">Invoice Line Items</h3>
          <button type="button" onClick={addItem}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary-50 px-3 py-1.5 text-xs font-medium text-primary-700 hover:bg-primary-100 transition-colors">
            <Plus className="h-3.5 w-3.5" /> Add Line
          </button>
        </div>

        <div className="divide-y divide-neutral-100">
          {items.map((item, idx) => (
            <div key={idx} className="p-5 space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-neutral-500">Line {item.line_no}</span>
                {items.length > 1 && (
                  <button type="button" onClick={() => removeItem(idx)}
                    className="text-red-400 hover:text-red-600 transition-colors">
                    <Trash2 className="h-4 w-4" />
                  </button>
                )}
              </div>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Field label="GL Account" required>
                  <input className={inputCls(errors[`item_${idx}_gl`])} value={item.gl}
                    onChange={e => setItem(idx, 'gl', e.target.value)} placeholder="e.g. 20001" />
                </Field>
                <Field label="Amount" required>
                  <input type="number" className={inputCls(errors[`item_${idx}_amount`])} value={item.amount}
                    onChange={e => setItem(idx, 'amount', parseFloat(e.target.value) || 0)} />
                </Field>
                <Field label="Tax Code">
                  <input className={inputCls()} value={item.tax_code}
                    onChange={e => setItem(idx, 'tax_code', e.target.value)} placeholder="e.g. I1" />
                </Field>
                <Field label="WHT Tax">
                  <input className={inputCls()} value={item.wht_tax}
                    onChange={e => setItem(idx, 'wht_tax', e.target.value)} placeholder="From vendor master" />
                </Field>
                <Field label="Baseline Date" required>
                  <input className={inputCls(errors[`item_${idx}_baseline_date`])} value={item.baseline_date}
                    onChange={e => setItem(idx, 'baseline_date', e.target.value)} placeholder="YYYYMMDD" />
                </Field>
                <Field label="Value Date">
                  <input className={inputCls()} value={item.value_date}
                    onChange={e => setItem(idx, 'value_date', e.target.value)} placeholder="YYYYMMDD" />
                </Field>
                <Field label="Business Place">
                  <input className={inputCls()} value={item.business_place}
                    onChange={e => setItem(idx, 'business_place', e.target.value)} placeholder="e.g. SSDN" />
                </Field>
                <Field label="Assignment No">
                  <input className={inputCls()} value={item.assignment_no}
                    onChange={e => setItem(idx, 'assignment_no', e.target.value)} />
                </Field>
                <Field label="Cost Center">
                  <input className={inputCls()} value={item.cost_center}
                    onChange={e => setItem(idx, 'cost_center', e.target.value)} placeholder="e.g. CC001" />
                </Field>
                <Field label="Profit Center">
                  <input className={inputCls()} value={item.profit_center}
                    onChange={e => setItem(idx, 'profit_center', e.target.value)} placeholder="e.g. PC001" />
                </Field>
                <Field label="Special GL">
                  <input className={inputCls()} value={item.special_gl}
                    onChange={e => setItem(idx, 'special_gl', e.target.value)} />
                </Field>
                <Field label="Text / Description">
                  <input className={inputCls()} value={item.text}
                    onChange={e => setItem(idx, 'text', e.target.value)} placeholder="Line description" />
                </Field>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Validation error banner */}
      {hasErrors && (
        <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertCircle className="h-4 w-4 shrink-0" />
          Please fill in all required fields (marked with *) before posting.
        </div>
      )}

      {/* Submit */}
      <div className="flex justify-end">
        <button type="button" onClick={handleSubmit} disabled={isPosting}
          className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-60 transition-colors">
          {isPosting
            ? <><Loader2 className="h-4 w-4 animate-spin" /> Posting to SAP…</>
            : 'Post to SAP (FB60)'}
        </button>
      </div>
    </div>
  );
}
