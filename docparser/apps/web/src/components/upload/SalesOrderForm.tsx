import { useState, useEffect } from 'react';
import { Loader2, CheckCircle2, User, Package, FileText, AlertCircle } from 'lucide-react';
import api from '@/lib/api';
import { cn } from '@/lib/cn';
import type { ExtractedData } from '@/types';

interface Customer {
  CUSTOMER: string;
  CUSTOMER_NAME: string;
  CITY: string;
  REGION: string;
  STREET: string;
  SALES_ORGANIZATION: string;
  DISTRIBUTION_CHANNEL: string;
  DIVISION: string;
  COMPANY_CODE: string;
  EMAIL_ADDRESS: string;
  TELEPHONE: string;
}

interface SalesOrderFormProps {
  extracted:    ExtractedData;
  onSimulate:   (customerId: string) => void;
  isSimulating: boolean;
}

export function SalesOrderForm({ extracted, onSimulate, isSimulating }: SalesOrderFormProps) {
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [matches,  setMatches]  = useState<Customer[]>([]);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState('');

  // On mount: auto-search customer using OCR-extracted name
  // Backend tries MongoDB first, falls back to live SAP if MongoDB is empty
  useEffect(() => {
    const name = extracted.bill_to_name || extracted.ship_to_name || '';
    if (!name) {
      setLoading(false);
      setError('No customer name found in the extracted PDF data.');
      return;
    }

    api.get(`/customers/search?q=${encodeURIComponent(name)}&limit=10`, { timeout: 180_000 })
      .then(res => {
        const list: Customer[] = res.data.customers || [];
        if (list.length === 0) {
          setError(`No customer found in SAP matching "${name}".`);
        } else if (list.length === 1) {
          setCustomer(list[0]);
        } else {
          setMatches(list);
        }
      })
      .catch(() => setError('Failed to fetch customer. Check SAP/API connectivity.'))
      .finally(() => setLoading(false));
  }, []);

  // ── States ──────────────────────────────────────────────────────────────────

  if (loading) return (
    <div className="rounded-xl border border-neutral-200 bg-white p-10 flex flex-col items-center gap-3">
      <Loader2 className="h-6 w-6 animate-spin text-indigo-500" />
      <p className="text-sm font-medium text-neutral-600">Fetching customer details from SAP…</p>
      <p className="text-xs text-neutral-400">First lookup may take up to 60 seconds</p>
    </div>
  );

  if (error) return (
    <div className="rounded-xl border border-red-200 bg-red-50 p-5 flex items-start gap-3">
      <AlertCircle className="h-5 w-5 text-red-500 mt-0.5 shrink-0" />
      <div>
        <p className="text-sm font-semibold text-red-700">Customer Not Found</p>
        <p className="text-xs text-red-500 mt-1">{error}</p>
        <p className="text-xs text-neutral-500 mt-2">
          Ensure the customer name on the PDF matches the SAP customer master data.
        </p>
      </div>
    </div>
  );

  // Multiple matches — let user pick one
  if (matches.length > 0 && !customer) return (
    <div className="rounded-xl border border-neutral-200 bg-white p-5 space-y-3">
      <p className="text-sm font-semibold text-neutral-800">
        Multiple customers found — select the correct one:
      </p>
      <div className="space-y-2">
        {matches.map(c => (
          <button
            key={c.CUSTOMER}
            type="button"
            onClick={() => { setCustomer(c); setMatches([]); }}
            className="w-full text-left rounded-lg border border-neutral-200 px-4 py-3 hover:border-indigo-300 hover:bg-indigo-50 transition-colors"
          >
            <p className="text-sm font-semibold text-neutral-800">{c.CUSTOMER_NAME || '—'}</p>
            <p className="text-xs text-neutral-400 mt-0.5">
              ID: {c.CUSTOMER} · {c.CITY} · {c.SALES_ORGANIZATION} / {c.DISTRIBUTION_CHANNEL} / {c.DIVISION}
            </p>
          </button>
        ))}
      </div>
    </div>
  );

  const lineItems = extracted.line_items || [];

  // ── Main layout: customer + OCR data + line items + button ─────────────────

  return (
    <div className="space-y-4">

      {/* Customer Details — fetched from SAP */}
      <div className="rounded-xl border border-neutral-200 bg-white p-5 space-y-3">
        <div className="flex items-center gap-2 pb-3 border-b border-neutral-100">
          <User className="h-4 w-4 text-indigo-500" />
          <h3 className="text-sm font-semibold text-neutral-800">Customer Details</h3>
          <span className="ml-auto text-xs font-medium text-green-700 bg-green-50 px-2 py-0.5 rounded-full">
            Fetched from SAP
          </span>
        </div>
        <div className="grid grid-cols-2 gap-x-6 gap-y-3 text-xs">
          <div>
            <p className="text-neutral-400 mb-0.5">Customer ID</p>
            <p className="font-semibold text-neutral-800">{customer!.CUSTOMER}</p>
          </div>
          <div>
            <p className="text-neutral-400 mb-0.5">Customer Name</p>
            <p className="font-semibold text-neutral-800">{customer!.CUSTOMER_NAME || '—'}</p>
          </div>
          <div>
            <p className="text-neutral-400 mb-0.5">City</p>
            <p className="font-semibold text-neutral-800">{customer!.CITY || '—'}</p>
          </div>
          <div>
            <p className="text-neutral-400 mb-0.5">Street</p>
            <p className="font-semibold text-neutral-800">{customer!.STREET || '—'}</p>
          </div>
          <div>
            <p className="text-neutral-400 mb-0.5">Sales Org</p>
            <p className="font-semibold text-indigo-700">{customer!.SALES_ORGANIZATION}</p>
          </div>
          <div>
            <p className="text-neutral-400 mb-0.5">Distribution Channel</p>
            <p className="font-semibold text-indigo-700">{customer!.DISTRIBUTION_CHANNEL}</p>
          </div>
          <div>
            <p className="text-neutral-400 mb-0.5">Division</p>
            <p className="font-semibold text-indigo-700">{customer!.DIVISION}</p>
          </div>
          <div>
            <p className="text-neutral-400 mb-0.5">Company Code</p>
            <p className="font-semibold text-neutral-800">{customer!.COMPANY_CODE || '—'}</p>
          </div>
        </div>
        <div className="rounded-lg bg-indigo-50 border border-indigo-100 px-3 py-2 text-xs text-indigo-700">
          All 4 partner roles (AG / WE / RE / RG) → <span className="font-bold">{customer!.CUSTOMER}</span>
        </div>
      </div>

      {/* Order Details — extracted from PDF */}
      <div className="rounded-xl border border-neutral-200 bg-white p-5 space-y-3">
        <div className="flex items-center gap-2 pb-3 border-b border-neutral-100">
          <FileText className="h-4 w-4 text-amber-500" />
          <h3 className="text-sm font-semibold text-neutral-800">Order Details</h3>
          <span className="ml-auto text-xs font-medium text-amber-700 bg-amber-50 px-2 py-0.5 rounded-full">
            Extracted from PDF
          </span>
        </div>
        <div className="grid grid-cols-2 gap-x-6 gap-y-3 text-xs">
          <div>
            <p className="text-neutral-400 mb-0.5">Customer PO Number</p>
            <p className="font-semibold text-neutral-800">{extracted.po_number || extracted.invoice_no || '—'}</p>
          </div>
          <div>
            <p className="text-neutral-400 mb-0.5">PO Date</p>
            <p className="font-semibold text-neutral-800">{extracted.invoice_date || '—'}</p>
          </div>
          <div>
            <p className="text-neutral-400 mb-0.5">Doc Type</p>
            <p className="font-semibold text-neutral-800">TA</p>
          </div>
          <div>
            <p className="text-neutral-400 mb-0.5">Currency</p>
            <p className="font-semibold text-neutral-800">{extracted.currency || 'INR'}</p>
          </div>
          <div>
            <p className="text-neutral-400 mb-0.5">Total Amount</p>
            <p className="font-semibold text-neutral-800">{extracted.gross_amount || '—'}</p>
          </div>
          <div>
            <p className="text-neutral-400 mb-0.5">Payment Terms</p>
            <p className="font-semibold text-neutral-800">{extracted.payment_terms || '—'}</p>
          </div>
        </div>
      </div>

      {/* Line Items — extracted from PDF */}
      <div className="rounded-xl border border-neutral-200 bg-white p-5 space-y-3">
        <div className="flex items-center gap-2 pb-3 border-b border-neutral-100">
          <Package className="h-4 w-4 text-amber-500" />
          <h3 className="text-sm font-semibold text-neutral-800">Line Items</h3>
          <span className="ml-auto text-xs font-medium text-amber-700 bg-amber-50 px-2 py-0.5 rounded-full">
            {lineItems.length} item{lineItems.length !== 1 ? 's' : ''} from PDF
          </span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-neutral-100">
                <th className="pb-2 text-left font-medium text-neutral-400 w-20">Item No</th>
                <th className="pb-2 text-left font-medium text-neutral-400 w-28">Material</th>
                <th className="pb-2 text-left font-medium text-neutral-400">Description</th>
                <th className="pb-2 text-left font-medium text-neutral-400 w-16">Qty</th>
                <th className="pb-2 text-left font-medium text-neutral-400 w-14">UOM</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-50">
              {lineItems.map((li, idx) => (
                <tr key={idx}>
                  <td className="py-2 text-neutral-400">{String((idx + 1) * 10).padStart(6, '0')}</td>
                  <td className="py-2 font-mono text-neutral-700">{li.material_code || '—'}</td>
                  <td className="py-2 text-neutral-700">{li.description || '—'}</td>
                  <td className="py-2 text-neutral-700">{li.quantity || '0'}</td>
                  <td className="py-2 text-neutral-700">{li.uom || 'ST'}</td>
                </tr>
              ))}
              {lineItems.length === 0 && (
                <tr>
                  <td colSpan={5} className="py-6 text-center text-neutral-400">
                    No line items extracted from PDF
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Simulate Button */}
      <button
        type="button"
        onClick={() => onSimulate(customer!.CUSTOMER)}
        disabled={isSimulating || lineItems.length === 0}
        className={cn(
          'w-full rounded-xl py-3.5 text-sm font-semibold transition-all flex items-center justify-center gap-2',
          !isSimulating && lineItems.length > 0
            ? 'bg-indigo-600 text-white hover:bg-indigo-700 shadow-sm'
            : 'bg-neutral-100 text-neutral-400 cursor-not-allowed',
        )}
      >
        {isSimulating
          ? <><Loader2 className="h-4 w-4 animate-spin" /> Simulating Sales Order…</>
          : <><CheckCircle2 className="h-4 w-4" /> Simulate Sales Order</>
        }
      </button>

    </div>
  );
}
