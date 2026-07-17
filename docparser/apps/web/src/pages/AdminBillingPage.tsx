import { useQuery } from '@tanstack/react-query';
import { IndianRupee, TrendingUp, FileText, Building2 } from 'lucide-react';
import { api } from '@/lib/api';
import { cn } from '@/lib/cn';

interface BillingRow {
  tenant_id: string; company_name: string; month: string;
  total_documents: number; total_pages: number;
  total_amount: number; status: string;
}

async function fetchBilling() {
  const r = await api.get('/admin/billing');
  return r.data as { records: BillingRow[]; total_revenue: number; this_month: number };
}

function fmtINR(n: number) {
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(n);
}

export default function AdminBillingPage() {
  const { data, isLoading } = useQuery({ queryKey: ['admin-billing'], queryFn: fetchBilling, refetchInterval: 60000 });

  const records = data?.records ?? [];

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-neutral-900 dark:text-white">Billing & Revenue</h1>
        <p className="text-sm text-neutral-500 dark:text-neutral-400 mt-0.5">Monthly billing records across all companies</p>
      </div>

      <div className="grid grid-cols-3 gap-4">
        {[
          { label: 'Total Revenue', value: fmtINR(data?.total_revenue ?? 0), icon: IndianRupee, color: 'bg-violet-100 text-violet-700 dark:bg-violet-900 dark:text-violet-300' },
          { label: 'This Month', value: fmtINR(data?.this_month ?? 0), icon: TrendingUp, color: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300' },
          { label: 'Billing Records', value: records.length, icon: FileText, color: 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300' },
        ].map(s => (
          <div key={s.label} className="rounded-xl border border-neutral-200 bg-white p-5 dark:border-neutral-800 dark:bg-neutral-900">
            <div className="flex items-center justify-between">
              <p className="text-sm text-neutral-500 dark:text-neutral-400">{s.label}</p>
              <span className={cn('flex h-8 w-8 items-center justify-center rounded-lg', s.color)}>
                <s.icon className="h-4 w-4" />
              </span>
            </div>
            <p className="mt-2 text-2xl font-bold text-neutral-900 dark:text-white tabular-nums">{s.value}</p>
          </div>
        ))}
      </div>

      <div className="rounded-xl border border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900">
        <div className="border-b border-neutral-100 dark:border-neutral-800 px-6 py-4">
          <h2 className="text-base font-semibold text-neutral-900 dark:text-white">Billing Records</h2>
        </div>
        {isLoading ? (
          <p className="text-center text-neutral-400 dark:text-neutral-500 py-16 text-sm">Loading…</p>
        ) : records.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-3 py-16 text-neutral-400 dark:text-neutral-500">
            <Building2 className="h-10 w-10 opacity-30" />
            <p className="text-sm">No billing records yet.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-neutral-100 dark:border-neutral-800">
                  {['Company', 'Month', 'Documents', 'Pages', 'Amount', 'Status'].map(h => (
                    <th key={h} className="px-6 py-3 text-left text-xs font-semibold uppercase tracking-wide text-neutral-400 dark:text-neutral-500">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100 dark:divide-neutral-800">
                {records.map((r, i) => (
                  <tr key={i} className="hover:bg-neutral-50 dark:hover:bg-neutral-800/40">
                    <td className="px-6 py-3 font-medium text-neutral-800 dark:text-white">{r.company_name}</td>
                    <td className="px-6 py-3 text-neutral-500 dark:text-neutral-400">{r.month}</td>
                    <td className="px-6 py-3 tabular-nums text-neutral-600 dark:text-neutral-400">{r.total_documents.toLocaleString('en-IN')}</td>
                    <td className="px-6 py-3 tabular-nums text-neutral-600 dark:text-neutral-400">{r.total_pages.toLocaleString('en-IN')}</td>
                    <td className="px-6 py-3 tabular-nums font-semibold text-emerald-700 dark:text-emerald-400">{fmtINR(r.total_amount)}</td>
                    <td className="px-6 py-3">
                      <span className={cn('rounded-full px-2.5 py-0.5 text-xs font-medium capitalize',
                        r.status === 'paid'
                          ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-400'
                          : 'bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-400')}>
                        {r.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
