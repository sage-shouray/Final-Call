import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  Building2, FileText, BookOpen, Users,
  IndianRupee, ChevronRight, Plus, CheckCircle2, XCircle, Clock,
} from 'lucide-react';
import { api } from '@/lib/api';
import { cn } from '@/lib/cn';

// ── API calls ────────────────────────────────────────────────────────────────

async function fetchOverview() {
  const r = await api.get('/admin/overview');
  return r.data as {
    total_companies: number; total_users: number;
    total_documents: number; total_pages: number;
    revenue_this_month: number;
  };
}

async function fetchCompanies() {
  const r = await api.get('/admin/companies');
  return r.data as Array<{
    id: string; name: string; slug: string; status: string;
    doc_count: number; page_count: number; user_count: number;
    last_activity: string | null; total_billed: number;
  }>;
}

// ── Stat card ─────────────────────────────────────────────────────────────────

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

// ── Status badge ──────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { label: string; cls: string; icon: React.ElementType }> = {
    active:    { label: 'Active',    cls: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-400', icon: CheckCircle2 },
    suspended: { label: 'Suspended', cls: 'bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-400',                 icon: XCircle },
    trial:     { label: 'Trial',     cls: 'bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-400',         icon: Clock },
  };
  const cfg = map[status] ?? map.active;
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium', cfg.cls)}>
      <cfg.icon className="h-3 w-3" />
      {cfg.label}
    </span>
  );
}

function fmt(n: number) {
  return n.toLocaleString('en-IN');
}

function fmtCurrency(n: number) {
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(n);
}

function timeAgo(iso: string | null) {
  if (!iso) return '—';
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 2)   return 'Just now';
  if (mins < 60)  return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24)   return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function AdminPage() {
  const navigate = useNavigate();

  const { data: overview, isLoading: ovLoading } = useQuery({ queryKey: ['admin-overview'], queryFn: fetchOverview, refetchInterval: 30000 });
  const { data: companies = [], isLoading: coLoading } = useQuery({ queryKey: ['admin-companies'], queryFn: fetchCompanies, refetchInterval: 30000 });

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-neutral-900 dark:text-white">Super Admin Dashboard</h1>
          <p className="text-sm text-neutral-500 dark:text-neutral-400 mt-0.5">Monitor all companies, documents, and revenue</p>
        </div>
        <button
          onClick={() => navigate('/admin/companies/new')}
          className="flex items-center gap-2 rounded-lg bg-violet-600 px-4 py-2 text-sm font-semibold text-white hover:bg-violet-700 transition-colors"
        >
          <Plus className="h-4 w-4" />
          Add Company
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <StatCard label="Companies"        value={ovLoading ? '…' : fmt(overview?.total_companies ?? 0)}    icon={Building2}     color="bg-violet-100 text-violet-700 dark:bg-violet-900 dark:text-violet-300" />
        <StatCard label="Total Documents"  value={ovLoading ? '…' : fmt(overview?.total_documents ?? 0)}   icon={FileText}      color="bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300" />
        <StatCard label="Pages Scanned"    value={ovLoading ? '…' : fmt(overview?.total_pages ?? 0)}       icon={BookOpen}      color="bg-cyan-100 text-cyan-700 dark:bg-cyan-900 dark:text-cyan-300" />
        <StatCard label="Active Users"     value={ovLoading ? '…' : fmt(overview?.total_users ?? 0)}       icon={Users}         color="bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300" />
        <StatCard label="Revenue (Month)"  value={ovLoading ? '…' : fmtCurrency(overview?.revenue_this_month ?? 0)} icon={IndianRupee} color="bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300" />
      </div>

      {/* Companies table */}
      <div className="rounded-xl border border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900">
        <div className="flex items-center justify-between border-b border-neutral-100 px-6 py-4 dark:border-neutral-800">
          <h2 className="text-base font-semibold text-neutral-900 dark:text-white">All Companies</h2>
          <span className="text-sm text-neutral-400 dark:text-neutral-500">{companies.length} total</span>
        </div>

        {coLoading ? (
          <div className="flex items-center justify-center py-16 text-neutral-400 dark:text-neutral-500">Loading…</div>
        ) : companies.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-3 py-16 text-neutral-400 dark:text-neutral-500">
            <Building2 className="h-10 w-10 opacity-30" />
            <p className="text-sm">No companies yet. Add your first one.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-neutral-100 dark:border-neutral-800">
                  {['Company', 'Status', 'Documents', 'Pages', 'Users', 'Billed (Total)', 'Last Activity', ''].map(h => (
                    <th key={h} className="px-6 py-3 text-left text-xs font-semibold uppercase tracking-wide text-neutral-400 dark:text-neutral-500">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100 dark:divide-neutral-800">
                {companies.map(c => (
                  <tr
                    key={c.id}
                    className="hover:bg-neutral-50 dark:hover:bg-neutral-800/50 cursor-pointer transition-colors"
                    onClick={() => navigate(`/admin/companies/${c.id}`)}
                  >
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-3">
                        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-violet-100 dark:bg-violet-900">
                          <Building2 className="h-4 w-4 text-violet-600 dark:text-violet-400" />
                        </div>
                        <div>
                          <p className="font-medium text-neutral-900 dark:text-white">{c.name}</p>
                          <p className="text-xs text-neutral-400 dark:text-neutral-500">{c.slug}</p>
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4"><StatusBadge status={c.status} /></td>
                    <td className="px-6 py-4 tabular-nums font-medium text-neutral-700 dark:text-neutral-300">{fmt(c.doc_count)}</td>
                    <td className="px-6 py-4 tabular-nums text-neutral-600 dark:text-neutral-400">{fmt(c.page_count)}</td>
                    <td className="px-6 py-4 tabular-nums text-neutral-600 dark:text-neutral-400">{c.user_count}</td>
                    <td className="px-6 py-4 tabular-nums font-medium text-emerald-700 dark:text-emerald-400">{fmtCurrency(c.total_billed)}</td>
                    <td className="px-6 py-4 text-neutral-400 dark:text-neutral-500 text-xs">{timeAgo(c.last_activity)}</td>
                    <td className="px-6 py-4">
                      <ChevronRight className="h-4 w-4 text-neutral-300 dark:text-neutral-600" />
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
