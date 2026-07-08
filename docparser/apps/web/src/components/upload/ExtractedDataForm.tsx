import { useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import type { ExtractedData, LineItem } from '@/types';
import { cn } from '@/lib/cn';

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmtAmt(v: string): string {
  const n = parseFloat(v);
  if (!v || isNaN(n) || n === 0) return '—';
  return '₹ ' + n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtNum(v: string): string {
  const n = parseFloat(v);
  if (!v || isNaN(n) || n === 0) return '—';
  return n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function nonZero(v: string) { const n = parseFloat(v); return !!v && !isNaN(n) && n !== 0; }

// ─── Sidebar field ────────────────────────────────────────────────────────────

function SideField({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="space-y-0.5">
      <p className="text-[10px] font-bold uppercase tracking-[0.08em] text-slate-500">{label}</p>
      <p className={cn(
        'text-[13px] leading-snug break-words',
        value ? 'text-slate-200' : 'text-slate-600',
        mono && 'font-mono',
      )}>
        {value || '—'}
      </p>
    </div>
  );
}

// ─── Sidebar section ──────────────────────────────────────────────────────────

function SideSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2.5">
      <div className="flex items-center gap-2">
        <div className="h-px flex-1 bg-slate-700/60" />
        <p className="text-[10px] font-bold uppercase tracking-[0.1em] text-indigo-400">{title}</p>
        <div className="h-px flex-1 bg-slate-700/60" />
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-2.5">{children}</div>
    </div>
  );
}

// ─── KPI tile ─────────────────────────────────────────────────────────────────

function KpiTile({
  label, value, sub, accent,
}: {
  label: string; value: string; sub?: string | undefined; accent: string;
}) {
  const num = parseFloat(value);
  const display = !value || isNaN(num) || num === 0
    ? '—'
    : '₹ ' + num.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  return (
    <div className={cn(
      'relative overflow-hidden rounded-xl border bg-white p-4 dark:bg-slate-800',
      accent,
    )}>
      <p className="text-[11px] font-bold uppercase tracking-widest text-neutral-400 dark:text-slate-500">{label}</p>
      <p className="mt-1.5 font-mono text-xl font-bold leading-none tabular-nums text-neutral-900 dark:text-slate-100 truncate" title={display}>
        {display}
      </p>
      {sub && <p className="mt-1 text-xs text-neutral-400 dark:text-slate-500">{sub}</p>}
    </div>
  );
}


// ─── Tax row ──────────────────────────────────────────────────────────────────

function TaxRow({ label, rate, amount, bold, dimmed }: {
  label: string; rate?: string; amount: string; bold?: boolean; dimmed?: boolean;
}) {
  const amt = fmtAmt(amount);
  const empty = amt === '—';
  return (
    <div className={cn(
      'flex items-baseline justify-between gap-2 py-1',
      dimmed && empty && 'opacity-30',
    )}>
      <div className="flex items-baseline gap-1.5 min-w-0">
        <span className={cn('text-sm truncate', bold ? 'font-semibold text-neutral-800 dark:text-slate-200' : 'text-neutral-500 dark:text-slate-400')}>{label}</span>
        {rate && nonZero(rate) && (
          <span className="shrink-0 rounded bg-neutral-100 dark:bg-slate-700 px-1.5 py-px text-[10px] font-bold text-neutral-500 dark:text-slate-400 tabular-nums">
            {parseFloat(rate)}%
          </span>
        )}
      </div>
      <span className={cn(
        'shrink-0 font-mono text-sm tabular-nums',
        empty ? 'text-neutral-300 dark:text-slate-600' :
        bold ? 'font-bold text-neutral-900 dark:text-slate-100' :
        'text-neutral-700 dark:text-slate-300',
      )}>{amt}</span>
    </div>
  );
}

// ─── Confidence ring ──────────────────────────────────────────────────────────

function ConfRing({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const r = 16; const circ = 2 * Math.PI * r;
  const dash = (pct / 100) * circ;
  const clr = pct >= 85 ? '#10b981' : pct >= 60 ? '#f59e0b' : '#ef4444';
  return (
    <div className="flex items-center gap-2">
      <svg width={40} height={40} viewBox="0 0 40 40">
        <circle cx={20} cy={20} r={r} fill="none" stroke="#334155" strokeWidth={3} />
        <circle cx={20} cy={20} r={r} fill="none" stroke={clr} strokeWidth={3}
          strokeDasharray={`${dash} ${circ}`} strokeLinecap="round"
          transform="rotate(-90 20 20)" style={{ transition: 'stroke-dasharray .8s ease' }} />
        <text x={20} y={24} textAnchor="middle" fontSize={10} fontWeight={800} fill={clr} fontFamily="ui-monospace,monospace">{pct}%</text>
      </svg>
      <div>
        <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Confidence</p>
        <p className="text-sm font-bold" style={{ color: clr }}>{pct >= 85 ? 'High' : pct >= 60 ? 'Medium' : 'Low'}</p>
      </div>
    </div>
  );
}

// ─── Line items table ─────────────────────────────────────────────────────────

function LineTable({ items }: { items: LineItem[] }) {
  type Col = { key: keyof LineItem; label: string; right?: boolean; mono?: boolean; dim?: boolean };
  const cols: Col[] = [
    { key: 'line_number',    label: '#'           },
    { key: 'hsn_code',       label: 'HSN/SAC', mono: true },
    { key: 'material_code',  label: 'Material',   mono: true },
    { key: 'description',    label: 'Description' },
    { key: 'quantity',       label: 'Qty',    right: true },
    { key: 'uom',            label: 'UOM'         },
    { key: 'unit_rate',      label: 'Rate',   right: true, mono: true },
    { key: 'taxable_amount', label: 'Taxable',right: true, mono: true },
    { key: 'cgst_rate',      label: 'C%',     right: true, dim: true },
    { key: 'cgst_amount',    label: 'CGST',   right: true, mono: true },
    { key: 'sgst_rate',      label: 'S%',     right: true, dim: true },
    { key: 'sgst_amount',    label: 'SGST',   right: true, mono: true },
    { key: 'igst_rate',      label: 'I%',     right: true, dim: true },
    { key: 'igst_amount',    label: 'IGST',   right: true, mono: true },
    { key: 'tax_amount',     label: 'Tax ₹',  right: true, mono: true },
    { key: 'amount',         label: 'Total',  right: true, mono: true },
  ];

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[900px]">
        <thead>
          <tr className="border-b border-neutral-100 dark:border-slate-700/60">
            {cols.map(c => (
              <th key={c.key} className={cn(
                'whitespace-nowrap px-3 py-2 text-[11px] font-bold uppercase tracking-wider',
                c.right ? 'text-right' : 'text-left',
                c.dim ? 'text-neutral-300 dark:text-slate-600' : 'text-neutral-400 dark:text-slate-500',
              )}>{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {items.map((item, i) => (
            <tr key={i} className={cn(
              'border-b border-neutral-50 dark:border-slate-800 transition-colors',
              'hover:bg-indigo-50/30 dark:hover:bg-indigo-950/20',
            )}>
              {cols.map(c => {
                const val = item[c.key] as string;
                const empty = !val || val === '0' || val === '0.00';
                return (
                  <td key={c.key} className={cn(
                    'px-3 py-2.5',
                    c.right && 'text-right',
                    c.mono && 'font-mono text-xs tabular-nums',
                    empty ? 'text-neutral-300 dark:text-slate-600' : 'text-neutral-700 dark:text-slate-300',
                    c.key === 'amount' && !empty && 'font-semibold text-neutral-900 dark:text-slate-100',
                  )}>
                    {empty ? '—' : val}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

interface ExtractedDataFormProps {
  data:           ExtractedData;
  onDataChange:   (updated: ExtractedData) => void;
  onValidate:     () => void;
  isValidating:   boolean;
  validateLabel?: string;
}

export function ExtractedDataForm({
  data, onDataChange, onValidate, isValidating, validateLabel = 'Validate with SAP',
}: ExtractedDataFormProps) {
  const [lineOpen, setLineOpen] = useState(false);

  function set<K extends keyof ExtractedData>(key: K, val: ExtractedData[K]) {
    onDataChange({ ...data, [key]: val });
  }

  const hasAdjustments = [
    data.discount_amount, data.freight_charges, data.packing_charges,
    data.insurance_charges, data.other_charges, data.round_off, data.tds_amount, data.tcs_amount,
  ].some(nonZero);

  return (
    <div className="flex h-[calc(100vh-232px)] min-h-[600px] overflow-hidden rounded-xl border border-neutral-200 bg-white dark:border-slate-700 dark:bg-slate-900 shadow-sm">

      {/* ══ LEFT SIDEBAR — dark, scrollable ═══════════════════════════════ */}
      <aside className="flex w-72 shrink-0 flex-col overflow-hidden border-r border-slate-700/60 bg-slate-900">

        {/* Identity hero */}
        <div className="shrink-0 border-b border-slate-700/60 bg-gradient-to-b from-indigo-950/80 to-slate-900 px-5 py-5 space-y-3">
          <ConfRing score={data.confidence_score} />
          <div>
            <p className="font-mono text-lg font-black leading-tight tracking-tight text-white">
              {data.invoice_no || 'No Invoice No.'}
            </p>
            <p className="mt-0.5 text-sm font-medium text-slate-300 truncate">{data.vendor_name || '—'}</p>
            <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5">
              {data.invoice_date && (
                <span className="text-[11px] text-slate-400">{data.invoice_date}</span>
              )}
              {data.po_number && (
                <span className="font-mono text-[11px] text-indigo-400">PO {data.po_number}</span>
              )}
            </div>
          </div>
        </div>

        {/* Scrollable sections */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">

          <SideSection title="Supplier">
            <div className="col-span-2"><SideField label="Name"    value={data.vendor_name} /></div>
            <SideField label="GSTIN"      value={data.vendor_gstin}    mono />
            <SideField label="PAN"        value={data.vendor_pan}      mono />
            <SideField label="State"      value={data.vendor_state} />
            <SideField label="State Code" value={data.vendor_state_code} />
            <SideField label="Email"      value={data.vendor_email} />
            <SideField label="Phone"      value={data.vendor_phone} />
            <div className="col-span-2"><SideField label="Address" value={data.vendor_address} /></div>
          </SideSection>

          <SideSection title="Buyer / Bill-to">
            <div className="col-span-2"><SideField label="Name"    value={data.bill_to_name} /></div>
            <SideField label="GSTIN"      value={data.bill_to_gstin}   mono />
            <SideField label="State"      value={data.bill_to_state} />
            <SideField label="State Code" value={data.bill_to_state_code} />
            <div className="col-span-2"><SideField label="Address" value={data.bill_to_address} /></div>
          </SideSection>

          {(data.ship_to_name || data.ship_to_address) && (
            <SideSection title="Ship-to">
              <div className="col-span-2"><SideField label="Name"    value={data.ship_to_name} /></div>
              <SideField label="GSTIN"    value={data.ship_to_gstin}   mono />
              <SideField label="State"    value={data.ship_to_state} />
              <div className="col-span-2"><SideField label="Address" value={data.ship_to_address} /></div>
            </SideSection>
          )}

          <SideSection title="Invoice Info">
            <SideField label="Type"           value={data.invoice_type} />
            <SideField label="Place of Supply" value={data.place_of_supply} />
            <SideField label="Due Date"        value={data.due_date} />
            <SideField label="Currency"        value={data.currency} />
            <SideField label="Payment Terms"   value={data.payment_terms} />
            <SideField label="Reverse Charge"  value={data.reverse_charge_applicable} />
            <SideField label="Delivery Note"   value={data.delivery_note} />
            <SideField label="Dispatch Doc"    value={data.dispatch_doc_no} />
          </SideSection>

          {(data.irn_number || data.eway_bill_no) && (
            <SideSection title="e-Invoice / EWB">
              {data.irn_number && <div className="col-span-2"><SideField label="IRN" value={data.irn_number} mono /></div>}
              <SideField label="e-Way Bill No"  value={data.eway_bill_no}        mono />
              <SideField label="EWB Date"       value={data.eway_bill_date} />
              <SideField label="Valid Upto"     value={data.eway_bill_valid_upto} />
            </SideSection>
          )}

          {(data.bank_name || data.bank_account_no) && (
            <SideSection title="Bank">
              <div className="col-span-2"><SideField label="Bank Name" value={data.bank_name} /></div>
              <SideField label="Account No" value={data.bank_account_no} mono />
              <SideField label="IFSC"       value={data.bank_ifsc}       mono />
              <SideField label="Branch"     value={data.bank_branch} />
            </SideSection>
          )}

          {(data.vehicle_no || data.transport_name) && (
            <SideSection title="Transport">
              <SideField label="Vehicle No"  value={data.vehicle_no}       mono />
              <SideField label="LR No"       value={data.lr_no}            mono />
              <SideField label="LR Date"     value={data.lr_date} />
              <SideField label="Transport"   value={data.transport_name} />
              <SideField label="Mode"        value={data.mode_of_transport} />
              <SideField label="Destination" value={data.destination} />
            </SideSection>
          )}

          {data.notes && (
            <SideSection title="Notes">
              <div className="col-span-2">
                <p className="text-sm leading-relaxed text-slate-400">{data.notes}</p>
              </div>
            </SideSection>
          )}
        </div>
      </aside>

      {/* ══ RIGHT PANEL — light, flex column ══════════════════════════════ */}
      <div className="flex flex-1 flex-col overflow-hidden bg-neutral-50 dark:bg-slate-800/30">

        {/* KPI strip */}
        <div className="shrink-0 grid grid-cols-4 gap-3 border-b border-neutral-100 dark:border-slate-700/60 bg-white dark:bg-slate-900/50 px-5 py-4">
          <KpiTile label="Taxable Amount" value={data.taxable_amount}
            accent="border-neutral-200 dark:border-slate-700" />
          <KpiTile label="Total Tax"      value={data.tax_amount}
            sub={[
              nonZero(data.cgst_amount) && `CGST ${fmtNum(data.cgst_amount)}`,
              nonZero(data.sgst_amount) && `SGST ${fmtNum(data.sgst_amount)}`,
              nonZero(data.igst_amount) && `IGST ${fmtNum(data.igst_amount)}`,
            ].filter(Boolean).join(' · ') || undefined}
            accent="border-amber-200 dark:border-amber-900/40" />
          <KpiTile label="Gross Amount"   value={data.gross_amount}
            accent="border-indigo-200 dark:border-indigo-900/40" />
          <KpiTile label="Net Payable"    value={data.net_amount}
            accent="border-emerald-200 dark:border-emerald-900/40" />
        </div>

        {/* Scrollable content */}
        <div className="flex-1 overflow-y-auto">

          {/* Middle: Tax breakdown + Editable fields */}
          <div className="grid grid-cols-[1fr_1fr] gap-0 divide-x divide-neutral-100 dark:divide-slate-700/60">

            {/* Tax breakdown */}
            <div className="px-5 py-4 space-y-0.5">
              <p className="mb-3 text-[11px] font-bold uppercase tracking-[0.1em] text-indigo-500">Tax Breakdown</p>

              <TaxRow label="Taxable Amount"  amount={data.taxable_amount} bold />

              <div className="my-1 border-t border-dashed border-neutral-100 dark:border-slate-700/40" />

              <TaxRow label="CGST" rate={data.cgst_rate} amount={data.cgst_amount} dimmed />
              <TaxRow label="SGST" rate={data.sgst_rate} amount={data.sgst_amount} dimmed />
              <TaxRow label="IGST" rate={data.igst_rate} amount={data.igst_amount} dimmed />
              <TaxRow label="Cess"            amount={data.cess_amount}    dimmed />
              <TaxRow label="Total Tax"       amount={data.tax_amount}     bold />

              {hasAdjustments && (
                <>
                  <div className="my-1 border-t border-dashed border-neutral-100 dark:border-slate-700/40" />
                  <TaxRow label="Discount"      amount={data.discount_amount}   dimmed />
                  <TaxRow label="Freight"       amount={data.freight_charges}   dimmed />
                  <TaxRow label="Packing"       amount={data.packing_charges}   dimmed />
                  <TaxRow label="Insurance"     amount={data.insurance_charges} dimmed />
                  <TaxRow label="Other Charges" amount={data.other_charges}     dimmed />
                  <TaxRow label="Round Off"     amount={data.round_off}         dimmed />
                  <TaxRow label="TDS"           amount={data.tds_amount}        dimmed />
                  <TaxRow label="TCS"           amount={data.tcs_amount}        dimmed />
                </>
              )}

              <div className="my-1.5 border-t-2 border-neutral-200 dark:border-slate-600" />
              <TaxRow label="Gross Amount" amount={data.gross_amount} bold />
              <TaxRow label="Net Payable"  amount={data.net_amount}   bold />
            </div>

            {/* Info + extra reference */}
            <div className="px-5 py-4 space-y-4">
              {/* Key fields — read only */}
              <div className="rounded-lg border border-neutral-100 bg-white dark:border-slate-700 dark:bg-slate-800/50 p-3.5 space-y-2">
                <p className="text-[11px] font-bold uppercase tracking-[0.1em] text-indigo-500">Invoice Details</p>
                <div className="grid grid-cols-2 gap-x-4 gap-y-2">
                  {[
                    { label: 'Invoice No',   value: data.invoice_no },
                    { label: 'Invoice Date', value: data.invoice_date },
                    { label: 'PO Number',    value: data.po_number },
                    { label: 'Vendor ID',    value: data.vendor_id },
                  ].map(({ label, value }) => (
                    <div key={label} className="space-y-0.5">
                      <p className="text-[10px] font-bold uppercase tracking-wider text-neutral-400">{label}</p>
                      <p className="text-sm font-medium text-neutral-800 dark:text-slate-200">{value || '—'}</p>
                    </div>
                  ))}
                </div>
              </div>

              {/* Quick reference */}
              <div className="rounded-lg border border-neutral-100 bg-white dark:border-slate-700 dark:bg-slate-800/50 p-3.5 space-y-2">
                <p className="text-[11px] font-bold uppercase tracking-[0.1em] text-indigo-500">Reference</p>
                <div className="grid grid-cols-2 gap-x-4 gap-y-2">
                  {[
                    { label: 'Invoice Type',    value: data.invoice_type },
                    { label: 'Place of Supply', value: data.place_of_supply },
                    { label: 'Due Date',        value: data.due_date },
                    { label: 'Payment Terms',   value: data.payment_terms },
                    { label: 'Reverse Charge',  value: data.reverse_charge_applicable },
                    { label: 'Currency',        value: data.currency },
                  ].map(({ label, value }) => (
                    <div key={label} className="space-y-0.5">
                      <p className="text-[10px] font-bold uppercase tracking-wider text-neutral-400">{label}</p>
                      <p className="text-sm text-neutral-700 dark:text-slate-300">{value || '—'}</p>
                    </div>
                  ))}
                </div>
              </div>

              {/* e-Invoice quick view */}
              {(data.irn_number || data.eway_bill_no) && (
                <div className="rounded-lg border border-indigo-100 bg-indigo-50/50 dark:border-indigo-900/40 dark:bg-indigo-950/20 p-3.5 space-y-2">
                  <p className="text-[11px] font-bold uppercase tracking-[0.1em] text-indigo-500">e-Invoice</p>
                  <div className="space-y-1.5">
                    {data.irn_number && (
                      <div>
                        <p className="text-[10px] font-bold uppercase tracking-wider text-indigo-400">IRN</p>
                        <p className="font-mono text-xs break-all text-indigo-700 dark:text-indigo-300">{data.irn_number}</p>
                      </div>
                    )}
                    {data.eway_bill_no && (
                      <div className="grid grid-cols-2 gap-3">
                        <div>
                          <p className="text-[10px] font-bold uppercase tracking-wider text-indigo-400">EWB No</p>
                          <p className="font-mono text-sm text-indigo-700 dark:text-indigo-300">{data.eway_bill_no}</p>
                        </div>
                        <div>
                          <p className="text-[10px] font-bold uppercase tracking-wider text-indigo-400">Valid Upto</p>
                          <p className="text-sm text-indigo-700 dark:text-indigo-300">{data.eway_bill_valid_upto || '—'}</p>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Line items drawer */}
          <div className="border-t border-neutral-100 dark:border-slate-700/60 bg-white dark:bg-slate-900/30">
            <button
              type="button"
              onClick={() => setLineOpen(o => !o)}
              className="flex w-full items-center justify-between px-5 py-3 hover:bg-neutral-50 dark:hover:bg-slate-800/40 transition-colors"
            >
              <div className="flex items-center gap-2.5">
                <p className="text-[11px] font-bold uppercase tracking-[0.1em] text-indigo-500">Line Items</p>
                {(data.line_items?.length ?? 0) > 0 && (
                  <span className="rounded-full bg-indigo-100 dark:bg-indigo-950 px-2 py-0.5 text-[11px] font-bold text-indigo-600 dark:text-indigo-400">
                    {data.line_items.length}
                  </span>
                )}
              </div>
              {lineOpen
                ? <ChevronUp className="h-3.5 w-3.5 text-neutral-400" />
                : <ChevronDown className="h-3.5 w-3.5 text-neutral-400" />}
            </button>

            {lineOpen && (
              <div className="border-t border-neutral-50 dark:border-slate-800 bg-white dark:bg-slate-900/50">
                {(data.line_items?.length ?? 0) > 0
                  ? <LineTable items={data.line_items} />
                  : <p className="px-5 py-8 text-center text-xs text-neutral-400">No line items extracted</p>}
              </div>
            )}
          </div>
        </div>

        {/* Action bar */}
        <div className="shrink-0 flex items-center justify-between border-t border-neutral-200 dark:border-slate-700 bg-white dark:bg-slate-900/80 px-5 py-3.5">
          <p className="text-xs text-neutral-500 dark:text-slate-400">
            <span className="font-semibold text-neutral-700 dark:text-slate-300">PO {data.po_number || '—'}</span>
            {' '}· will be validated against SAP
          </p>
          <button
            type="button"
            onClick={onValidate}
            disabled={isValidating}
            className={cn(
              'inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-2 text-sm font-semibold text-white',
              'hover:bg-indigo-700 active:bg-indigo-800 transition-colors shadow-sm',
              'disabled:opacity-60 disabled:pointer-events-none',
            )}
          >
            {isValidating
              ? <><span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />Validating…</>
              : validateLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
