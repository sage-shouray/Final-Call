import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Activity, Search } from 'lucide-react';
import { api } from '@/lib/api';
import { cn } from '@/lib/cn';

interface ActivityDoc {
  document_id: string; company_name: string; type: string; tcode: string;
  status: string; page_count: number; uploaded_at: string; uploaded_by: string;
}

async function fetchActivity(search: string) {
  const r = await api.get('/admin/activity', { params: { q: search || undefined, limit: 100 } });
  return r.data as { documents: ActivityDoc[]; total: number };
}

const STATUS_COLOR: Record<string, string> = {
  posted:    'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-400',
  validated: 'bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-400',
  simulated: 'bg-cyan-100 text-cyan-700 dark:bg-cyan-950 dark:text-cyan-400',
  failed:    'bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-400',
  extracted: 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-400',
  uploaded:  'bg-neutral-100 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-400',
};

export default function AdminActivityPage() {
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');

  const { data, isLoading } = useQuery({
    queryKey: ['admin-activity', debouncedSearch],
    queryFn: () => fetchActivity(debouncedSearch),
    refetchInterval: 30000,
  });

  const docs = data?.documents ?? [];

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-neutral-900 dark:text-white">Activity Monitor</h1>
          <p className="text-sm text-neutral-500 mt-0.5">All documents across all companies · auto-refreshes every 30s</p>
        </div>
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-neutral-400 pointer-events-none" />
          <input
            value={search}
            onChange={e => {
              setSearch(e.target.value);
              clearTimeout((window as any).__activityTimer);
              (window as any).__activityTimer = setTimeout(() => setDebouncedSearch(e.target.value), 400);
            }}
            placeholder="Search company, doc ID, type…"
            className="pl-9 pr-4 py-2 rounded-lg border border-neutral-200 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500 dark:border-neutral-700 dark:bg-neutral-800 dark:text-white w-64"
          />
        </div>
      </div>

      <div className="rounded-xl border border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900">
        <div className="border-b border-neutral-100 dark:border-neutral-800 px-6 py-4 flex items-center gap-2">
          <Activity className="h-4 w-4 text-violet-600" />
          <h2 className="text-base font-semibold text-neutral-900 dark:text-white">
            Live Feed {data ? `· ${data.total} total` : ''}
          </h2>
        </div>

        {isLoading ? (
          <p className="text-center text-neutral-400 py-16 text-sm">Loading…</p>
        ) : docs.length === 0 ? (
          <p className="text-center text-neutral-400 py-16 text-sm">No documents found.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-neutral-100 dark:border-neutral-800">
                  {['Company', 'Document ID', 'Type', 'TCode', 'Pages', 'Status', 'Uploaded By', 'Date'].map(h => (
                    <th key={h} className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wide text-neutral-400">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100 dark:divide-neutral-800">
                {docs.map(d => (
                  <tr key={d.document_id} className="hover:bg-neutral-50 dark:hover:bg-neutral-800/30">
                    <td className="px-5 py-3 font-medium text-neutral-800 dark:text-white">{d.company_name}</td>
                    <td className="px-5 py-3 font-mono text-xs text-neutral-500">{d.document_id}</td>
                    <td className="px-5 py-3 capitalize text-neutral-600 dark:text-neutral-400">{d.type.replace('_', ' ')}</td>
                    <td className="px-5 py-3"><span className="rounded bg-neutral-100 px-1.5 py-0.5 text-xs font-mono dark:bg-neutral-800">{d.tcode}</span></td>
                    <td className="px-5 py-3 tabular-nums text-neutral-500">{d.page_count || '—'}</td>
                    <td className="px-5 py-3">
                      <span className={cn('rounded-full px-2 py-0.5 text-xs font-medium capitalize', STATUS_COLOR[d.status] ?? STATUS_COLOR.uploaded)}>
                        {d.status}
                      </span>
                    </td>
                    <td className="px-5 py-3 text-xs text-neutral-400">{d.uploaded_by}</td>
                    <td className="px-5 py-3 text-xs text-neutral-400">{new Date(d.uploaded_at).toLocaleString('en-IN')}</td>
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
