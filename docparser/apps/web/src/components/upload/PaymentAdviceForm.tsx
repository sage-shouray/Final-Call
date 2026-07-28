import { useState } from 'react';
import { AlertCircle, Loader2 } from 'lucide-react';
import { cn } from '@/lib/cn';
import type { ExtractedData, F26FormData } from '@/types';

interface Props {
  extracted:   ExtractedData | null;
  isSimulating: boolean;
  onSimulate:  (data: F26FormData) => void;
}

function toDotDate(dateStr: string): string {
  if (!dateStr) return '';
  return dateStr.replace(/\//g, '.').replace(/-/g, '.');
}

function Field({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-medium text-neutral-600 dark:text-neutral-400">
        {label}{required && <span className="ml-0.5 text-red-500">*</span>}
      </label>
      {children}
    </div>
  );
}

const inputCls = (error?: boolean) => cn(
  'h-9 w-full rounded-lg border px-3 text-sm text-neutral-800 placeholder:text-neutral-400 dark:placeholder:text-neutral-500 focus:outline-none focus:ring-2 focus:ring-primary-200 transition-colors',
  'dark:text-neutral-100 dark:placeholder:text-neutral-600',
  error
    ? 'border-red-300 bg-red-50 dark:border-red-700 dark:bg-red-950/40'
    : 'border-neutral-200 bg-white hover:border-neutral-300 dark:border-neutral-700 dark:bg-neutral-800 dark:hover:border-neutral-500',
);

export function PaymentAdviceForm({ extracted, isSimulating, onSimulate }: Props) {
  const todayDot = toDotDate(extracted?.invoice_date || '') || '';

  const [form, setForm] = useState<F26FormData>({
    company_code:  '',
    customer:      '',
    invoice:       extracted?.invoice_no || '',
    fiscal_year:   '',
    document_date: todayDot,
    posting_date:  todayDot,
    currency:      extracted?.currency || 'INR',
    amount:        extracted?.gross_amount ? String(extracted.gross_amount) : '',
    bank_gl:       '',
    value_date:    todayDot,
    reference:     extracted?.invoice_no || '',
    header_text:   'Customer Payment',
    item_text:     'Payment against Invoice',
  });

  const [errors, setErrors] = useState<Record<string, boolean>>({});

  function setField<K extends keyof F26FormData>(k: K, v: string) {
    setForm(f => ({ ...f, [k]: v }));
    if (errors[k]) setErrors(e => ({ ...e, [k]: false }));
  }

  function validate(): boolean {
    const req: (keyof F26FormData)[] = [
      'company_code', 'customer', 'invoice', 'fiscal_year',
      'document_date', 'posting_date', 'amount', 'bank_gl',
    ];
    const newErrors: Record<string, boolean> = {};
    req.forEach((k) => { if (!String(form[k]).trim()) newErrors[k] = true; });
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  }

  function handleSubmit() {
    if (!validate()) return;
    onSimulate(form);
  }

  const hasErrors = Object.values(errors).some(Boolean);

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-neutral-200 bg-white overflow-hidden dark:border-neutral-700 dark:bg-neutral-900">
        <div className="border-b border-neutral-100 px-5 py-3.5 dark:border-neutral-700">
          <h3 className="text-sm font-semibold text-neutral-800 dark:text-neutral-200">Customer Payment (F-26)</h3>
          <p className="mt-0.5 text-xs text-neutral-400 dark:text-neutral-500">Fill in the SAP fields, then simulate before posting</p>
        </div>
        <div className="grid grid-cols-2 gap-4 p-5 sm:grid-cols-4">
          <Field label="Company Code" required>
            <input className={inputCls(errors.company_code)} value={form.company_code}
              onChange={e => setField('company_code', e.target.value)} placeholder="1000" />
          </Field>
          <Field label="Customer" required>
            <input className={inputCls(errors.customer)} value={form.customer}
              onChange={e => setField('customer', e.target.value)} placeholder="1000" />
          </Field>
          <Field label="Invoice" required>
            <input className={inputCls(errors.invoice)} value={form.invoice}
              onChange={e => setField('invoice', e.target.value)} placeholder="100000000" />
          </Field>
          <Field label="Fiscal Year" required>
            <input className={inputCls(errors.fiscal_year)} value={form.fiscal_year}
              onChange={e => setField('fiscal_year', e.target.value)} placeholder="2026" />
          </Field>
          <Field label="Document Date" required>
            <input className={inputCls(errors.document_date)} value={form.document_date}
              onChange={e => setField('document_date', e.target.value)} placeholder="DD.MM.YYYY" />
          </Field>
          <Field label="Posting Date" required>
            <input className={inputCls(errors.posting_date)} value={form.posting_date}
              onChange={e => setField('posting_date', e.target.value)} placeholder="DD.MM.YYYY" />
          </Field>
          <Field label="Value Date">
            <input className={inputCls()} value={form.value_date}
              onChange={e => setField('value_date', e.target.value)} placeholder="DD.MM.YYYY" />
          </Field>
          <Field label="Currency">
            <input className={inputCls()} value={form.currency}
              onChange={e => setField('currency', e.target.value)} placeholder="INR" />
          </Field>
          <Field label="Amount" required>
            <input className={inputCls(errors.amount)} value={form.amount}
              onChange={e => setField('amount', e.target.value)} placeholder="10000" />
          </Field>
          <Field label="Bank GL" required>
            <input className={inputCls(errors.bank_gl)} value={form.bank_gl}
              onChange={e => setField('bank_gl', e.target.value)} placeholder="110009" />
          </Field>
          <Field label="Reference">
            <input className={inputCls()} value={form.reference}
              onChange={e => setField('reference', e.target.value)} placeholder="PAYT-2026-0001" />
          </Field>
          <Field label="Header Text">
            <input className={inputCls()} value={form.header_text}
              onChange={e => setField('header_text', e.target.value)} />
          </Field>
          <Field label="Item Text">
            <input className={inputCls()} value={form.item_text}
              onChange={e => setField('item_text', e.target.value)} />
          </Field>
        </div>
      </div>

      {hasErrors && (
        <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-400">
          <AlertCircle className="h-4 w-4 shrink-0" />
          Please fill in all required fields (marked with *) before simulating.
        </div>
      )}

      <div className="flex justify-end">
        <button type="button" onClick={handleSubmit} disabled={isSimulating}
          className="inline-flex items-center gap-2 rounded-lg bg-violet-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-violet-700 disabled:opacity-60 transition-colors">
          {isSimulating
            ? <><Loader2 className="h-4 w-4 animate-spin" /> Simulating…</>
            : 'Simulate F-26 Payment'}
        </button>
      </div>
    </div>
  );
}
