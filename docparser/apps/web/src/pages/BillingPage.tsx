import { useQuery } from '@tanstack/react-query';
import { IndianRupee, FileText, Layers } from 'lucide-react';
import { api } from '@/lib/api';
import { cn } from '@/lib/cn';

interface LineItem {
  tcode: string; label: string; doc_count: number; price_each: number; amount: number;
}
interface HistoryRecord {
  id: string; period_month: number; period_year: number; tcode: string;
  doc_count: number; price_each: number; total_amount: number; status: string;
}
interface Billing {
  period_month: number; period_year: number; period_label: string;
  line_items: LineItem[]; total_documents: number; total_pages: number;
  total_due: number; history: HistoryRecord[];
}

const MONTH_NAMES = ['', 'January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

async function fetchBilling() {
  const r = await api.get('/auth/billing');
  return r.data as Billing;
}

function fmtINR(n: number) {
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(n);
}

function StatCard({ label, value, icon: Icon, color }: {
  label: string; value: string | number; icon: React.ElementType; color: string;
}) {
  return (
    <div className="rounded-xl border border-neutral-200 bg-white p-5 dark:border-neutral-800 dark:bg-neutral-900">
      <div className="flex items-center justify-between">
        <p className="text-sm text-neutral-500 dark:text-neutral-400">{label}</p>
        <span className={cn('flex h-8 w-8 items-center justify-center rounded-lg', color)}>
          <Icon className="h-4 w-4" />
        </span>
      </div>
      <p className="mt-2 text-2xl font-bold text-neutral-900 dark:text-white tabular-nums">{value}</p>
    </div>
  );
}

export default function BillingPage() {
  const { data, isLoading } = useQuery({ queryKey: ['billing'], queryFn: fetchBilling });

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-neutral-900 dark:text-white">Billing</h1>
        <p className="text-sm text-neutral-500 dark:text-neutral-400 mt-0.5">
          Documents processed and cost owed for {isLoading ? '…' : data?.period_label}
        </p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-4">
        <StatCard
          label="Amount Due"
          value={isLoading ? '…' : fmtINR(data?.total_due ?? 0)}
          icon={IndianRupee}
          color="bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300"
        />
        <StatCard
          label="Documents Processed"
          value={isLoading ? '…' : (data?.total_documents ?? 0).toLocaleString('en-IN')}
          icon={FileText}
          color="bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300"
        />
        <StatCard
          label="Pages Scanned"
          value={isLoading ? '…' : (data?.total_pages ?? 0).toLocaleString('en-IN')}
          icon={Layers}
          color="bg-violet-100 text-violet-700 dark:bg-violet-900 dark:text-violet-300"
        />
      </div>

      {/* Current month breakdown */}
      <div className="rounded-xl border border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900">
        <div className="flex items-center justify-between border-b border-neutral-100 px-6 py-4 dark:border-neutral-800">
          <h2 className="text-base font-semibold text-neutral-900 dark:text-white">
            {isLoading ? 'This Month' : data?.period_label}
          </h2>
          <span className="text-sm text-neutral-400 dark:text-neutral-500">Cost is calculated from documents successfully posted this month</span>
        </div>

        {isLoading ? (
          <p className="text-center text-sm text-neutral-400 dark:text-neutral-500 py-16">Loading…</p>
        ) : !data || data.line_items.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-3 py-16 text-neutral-400 dark:text-neutral-500">
            <FileText className="h-10 w-10 opacity-30" />
            <p className="text-sm">No billable documents processed yet this month.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-neutral-100 dark:border-neutral-800">
                  {['Workflow', 'TCode', 'Documents', 'Price Each', 'Amount'].map(h => (
                    <th key={h} className="px-6 py-3 text-left text-xs font-semibold uppercase tracking-wide text-neutral-400 dark:text-neutral-500">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100 dark:divide-neutral-800">
                {data.line_items.map(li => (
                  <tr key={li.tcode} className="hover:bg-neutral-50 dark:hover:bg-neutral-800/40">
                    <td className="px-6 py-4 font-medium text-neutral-900 dark:text-white">{li.label}</td>
                    <td className="px-6 py-4"><span className="rounded bg-neutral-100 px-1.5 py-0.5 text-xs font-mono dark:bg-neutral-800">{li.tcode}</span></td>
                    <td className="px-6 py-4 tabular-nums text-neutral-600 dark:text-neutral-400">{li.doc_count}</td>
                    <td className="px-6 py-4 tabular-nums text-neutral-500 dark:text-neutral-400">{fmtINR(li.price_each)}</td>
                    <td className="px-6 py-4 tabular-nums font-semibold text-neutral-900 dark:text-white">{fmtINR(li.amount)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t-2 border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800/50">
                  <td colSpan={4} className="px-6 py-3 font-semibold text-neutral-700 dark:text-neutral-300">Total due this month</td>
                  <td className="px-6 py-3 font-bold text-emerald-700 dark:text-emerald-400 tabular-nums">{fmtINR(data.total_due)}</td>
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </div>

      {/* History */}
      {!isLoading && data && data.history.length > 0 && (
        <div className="rounded-xl border border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900">
          <div className="border-b border-neutral-100 px-6 py-4 dark:border-neutral-800">
            <h2 className="text-base font-semibold text-neutral-900 dark:text-white">Billing History</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-neutral-100 dark:border-neutral-800">
                  {['Period', 'TCode', 'Documents', 'Amount', 'Status'].map(h => (
                    <th key={h} className="px-6 py-3 text-left text-xs font-semibold uppercase tracking-wide text-neutral-400 dark:text-neutral-500">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100 dark:divide-neutral-800">
                {data.history.map(h => (
                  <tr key={h.id} className="hover:bg-neutral-50 dark:hover:bg-neutral-800/40">
                    <td className="px-6 py-4 text-neutral-600 dark:text-neutral-400">{MONTH_NAMES[h.period_month]} {h.period_year}</td>
                    <td className="px-6 py-4"><span className="rounded bg-neutral-100 px-1.5 py-0.5 text-xs font-mono dark:bg-neutral-800">{h.tcode}</span></td>
                    <td className="px-6 py-4 tabular-nums text-neutral-500 dark:text-neutral-400">{h.doc_count}</td>
                    <td className="px-6 py-4 tabular-nums font-semibold text-neutral-900 dark:text-white">{fmtINR(h.total_amount)}</td>
                    <td className="px-6 py-4">
                      <span className={cn('rounded-full px-2.5 py-0.5 text-xs font-medium capitalize',
                        h.status === 'paid'
                          ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-400'
                          : 'bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-400')}>
                        {h.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
