import { useEffect, useState } from 'react';
import {
  TrendingUp, CheckCircle2, Clock, XCircle,
  Download, RefreshCw, IndianRupee,
} from 'lucide-react';
import { useDashboardMetrics } from '@/hooks/useDashboardMetrics';
import { useDocuments }        from '@/hooks/useDocuments';
import { Topbar }     from '@/components/layout/Topbar';
import { Button }     from '@/components/ui/Button';
import { Skeleton }   from '@/components/ui/Skeleton';
import { toINR }      from '@/lib/currency';
import { formatDate } from '@/lib/dates';
import { cn }         from '@/lib/cn';
import { DocumentStatus, type DocumentListItem } from '@/types';
import { DOC_TYPE_LABEL } from '@/utils/constants';

// ─── Helpers ──────────────────────────────────────────────────────────────────

function pct(part: number, total: number) {
  return total > 0 ? Math.round((part / total) * 100) : 0;
}

// ─── KPI Card ─────────────────────────────────────────────────────────────────

function KpiCard({
  label, value, sub, icon: Icon, accent, loading,
}: {
  label:   string;
  value:   string | number;
  sub?:    string;
  icon:    React.ElementType;
  accent:  string;
  loading: boolean;
}) {
  return (
    <div className={cn(
      'rounded-xl border-l-4 bg-white ring-1 ring-neutral-200/60 shadow-soft px-5 py-4',
      'dark:bg-neutral-800 dark:ring-neutral-700/60 dark:shadow-none',
      accent,
    )}>
      <div className="flex items-start justify-between gap-2">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-neutral-400 dark:text-neutral-500">
          {label}
        </p>
        <Icon className="h-4 w-4 shrink-0 text-neutral-300 dark:text-neutral-600" />
      </div>
      {loading
        ? <Skeleton className="mt-2 h-8 w-24" />
        : <p className="mt-2 text-xl font-bold tabular-nums text-neutral-900 dark:text-neutral-100 truncate" title={String(value)}>{value}</p>
      }
      {sub && !loading && (
        <p className="mt-1 text-xs text-neutral-400 dark:text-neutral-500">{sub}</p>
      )}
    </div>
  );
}

// ─── Bar chart row ────────────────────────────────────────────────────────────

function BarRow({
  label, count, percentage, color, loading,
}: {
  label: string; count: number; percentage: number; color: string; loading: boolean;
}) {
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const id = setTimeout(() => setWidth(loading ? 0 : percentage), 120);
    return () => clearTimeout(id);
  }, [percentage, loading]);

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-xs">
        <span className="font-medium text-neutral-700 dark:text-neutral-300 capitalize">{label}</span>
        <span className="tabular-nums text-neutral-400 dark:text-neutral-500">
          {loading ? '—' : `${count} · ${percentage.toFixed(0)}%`}
        </span>
      </div>
      <div className="h-[7px] w-full rounded-full bg-neutral-100 dark:bg-neutral-700">
        <div
          className={cn('h-full rounded-full transition-all duration-700 ease-out', color)}
          style={{ width: `${width}%` }}
        />
      </div>
    </div>
  );
}

// ─── Section card ─────────────────────────────────────────────────────────────

function Section({ title, children, action }: {
  title: string; children: React.ReactNode; action?: React.ReactNode;
}) {
  return (
    <div className="rounded-xl bg-white ring-1 ring-neutral-200/60 shadow-soft overflow-hidden dark:bg-neutral-800 dark:ring-neutral-700/60 dark:shadow-none">
      <div className="flex items-center justify-between border-b border-neutral-100 px-5 py-3.5 dark:border-neutral-700">
        <h2 className="text-sm font-semibold text-neutral-800 dark:text-neutral-200">{title}</h2>
        {action}
      </div>
      <div className="px-5 py-4">{children}</div>
    </div>
  );
}

// ─── Trend sparkline (CSS bars) ───────────────────────────────────────────────

function TrendBars({ data, loading }: {
  data: { date: string; count: number }[];
  loading: boolean;
}) {
  if (loading) {
    return (
      <div className="flex items-end gap-1 h-20">
        {Array.from({ length: 14 }, (_, i) => (
          <div key={i} className="flex-1 animate-pulse rounded-sm bg-neutral-200 dark:bg-neutral-700"
            style={{ height: `${20 + Math.random() * 60}%` }} />
        ))}
      </div>
    );
  }

  if (!data.length) {
    return <p className="text-xs text-neutral-400 dark:text-neutral-500 py-4">No trend data yet</p>;
  }

  const max = Math.max(...data.map(d => d.count), 1);

  return (
    <div className="flex items-end gap-1 h-20">
      {data.map((d) => (
        <div key={d.date} className="group relative flex-1 flex flex-col justify-end" title={`${d.date}: ${d.count}`}>
          <div
            className="rounded-sm bg-indigo-500 dark:bg-indigo-400 transition-all duration-500 hover:bg-indigo-400 dark:hover:bg-indigo-300"
            style={{ height: `${Math.max(4, (d.count / max) * 100)}%` }}
          />
          <span className="absolute -top-5 left-1/2 -translate-x-1/2 hidden group-hover:block whitespace-nowrap rounded bg-neutral-800 dark:bg-neutral-200 px-1.5 py-0.5 text-[10px] text-white dark:text-neutral-900 z-10">
            {d.count}
          </span>
        </div>
      ))}
    </div>
  );
}

// ─── CSV Export ───────────────────────────────────────────────────────────────

function exportCSV(docs: DocumentListItem[]) {
  const header = 'Document ID,Type,Vendor,T-Code,Amount (INR),Status,Confidence,Uploaded At,Posted Number';
  const rows = docs.map(d => [
    d.document_id,
    DOC_TYPE_LABEL[d.type as keyof typeof DOC_TYPE_LABEL] ?? d.type,
    d.vendor_name ?? '',
    d.tcode,
    d.amount ?? '',
    d.status,
    d.confidence_score != null ? `${Math.round(d.confidence_score * 100)}%` : '',
    d.uploaded_at,
    d.miro_number ?? d.grn_number ?? '',
  ].map(v => `"${String(v).replace(/"/g, '""')}"`).join(','));

  const blob = new Blob([[header, ...rows].join('\n')], { type: 'text/csv' });
  const url  = URL.createObjectURL(blob);
  const a    = Object.assign(document.createElement('a'), {
    href: url, download: `uvira-report-${new Date().toISOString().slice(0,10)}.csv`,
  });
  a.click();
  URL.revokeObjectURL(url);
}

// ─── Main page ────────────────────────────────────────────────────────────────

const STATUS_COLORS: Record<string, string> = {
  posted:    'bg-green-500',
  validated: 'bg-indigo-400',
  extracted: 'bg-indigo-300',
  failed:    'bg-red-400',
  uploading: 'bg-neutral-400',
};

const TCODE_COLORS = ['bg-indigo-500', 'bg-cyan-500', 'bg-violet-500', 'bg-teal-500', 'bg-amber-500'];

export default function ReportsPage() {
  const { data: metrics, isLoading, refetch, isFetching } = useDashboardMetrics();
  const { data: docsData, isLoading: docsLoading } = useDocuments({ limit: 500, page: 1 });

  useEffect(() => {
    document.title = 'Reports · Uvira.ai';
    return () => { document.title = 'Uvira.ai'; };
  }, []);

  const docs    = docsData?.documents ?? [];
  const total   = metrics?.total_processed ?? 0;
  const posted  = metrics?.posted_to_sap   ?? 0;
  const pending = metrics?.pending_review  ?? 0;
  const failed  = metrics?.failed          ?? 0;
  const value   = Number(metrics?.total_value_inr ?? 0);
  const successRate = pct(posted, total);

  // Recent docs sorted newest first, limited to 10
  const recentPosted = docs
    .filter(d => d.status === DocumentStatus.POSTED)
    .slice(0, 10);

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <Topbar title="Reports" subtitle="Processing analytics and document history">
        <Button
          size="sm"
          variant="secondary"
          icon={<RefreshCw className={cn('h-3.5 w-3.5', isFetching && 'animate-spin')} />}
          onClick={() => refetch()}
          disabled={isFetching}
        >
          Refresh
        </Button>
        <Button
          size="sm"
          icon={<Download className="h-3.5 w-3.5" />}
          onClick={() => exportCSV(docs)}
          disabled={docs.length === 0}
        >
          Export CSV
        </Button>
      </Topbar>

      <div className="flex-1 overflow-y-auto p-6 space-y-6">

        {/* ── KPI strip ──────────────────────────────────────────────────────── */}
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
          <KpiCard label="Total Processed" value={total.toLocaleString('en-IN')}
            sub="All time" icon={TrendingUp} accent="border-l-indigo-500" loading={isLoading} />
          <KpiCard label="Posted to SAP" value={posted.toLocaleString('en-IN')}
            sub={`${successRate}% success rate`} icon={CheckCircle2} accent="border-l-green-500" loading={isLoading} />
          <KpiCard label="Pending Review" value={pending.toLocaleString('en-IN')}
            sub="Awaiting action" icon={Clock} accent="border-l-amber-500" loading={isLoading} />
          <KpiCard label="Failed" value={failed.toLocaleString('en-IN')}
            sub={`${pct(failed, total)}% failure rate`} icon={XCircle} accent="border-l-red-500" loading={isLoading} />
          <KpiCard label="Total Value" value={toINR(value)}
            sub="Across all invoices" icon={IndianRupee} accent="border-l-slate-400" loading={isLoading} />
        </div>

        {/* ── Row 2: Trend + By Type ─────────────────────────────────────────── */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_320px]">

          {/* Trend */}
          <Section title={`Daily Volume · Last ${metrics?.recent_trend.length ?? 14} Days`}>
            <TrendBars data={metrics?.recent_trend ?? []} loading={isLoading} />
            {!isLoading && metrics?.recent_trend.length ? (
              <div className="mt-2 flex justify-between text-[10px] text-neutral-400 dark:text-neutral-600">
                <span>{metrics.recent_trend[0]?.date}</span>
                <span>{metrics.recent_trend[metrics.recent_trend.length - 1]?.date}</span>
              </div>
            ) : null}
          </Section>

          {/* By Document Type */}
          <Section title="By Document Type">
            <div className="space-y-4">
              {isLoading
                ? Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-8 w-full" />)
                : (metrics?.by_type ?? []).length
                  ? metrics!.by_type.map((t, i) => (
                      <BarRow
                        key={t.type}
                        label={DOC_TYPE_LABEL[t.type as keyof typeof DOC_TYPE_LABEL] ?? t.type}
                        count={t.count}
                        percentage={pct(t.count, total)}
                        color={TCODE_COLORS[i % TCODE_COLORS.length]}
                        loading={false}
                      />
                    ))
                  : <p className="text-xs text-neutral-400 dark:text-neutral-500">No data yet</p>
              }
            </div>
          </Section>
        </div>

        {/* ── Row 3: By T-Code + By Status ──────────────────────────────────── */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">

          <Section title="By T-Code">
            <div className="space-y-4">
              {isLoading
                ? Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-8 w-full" />)
                : (metrics?.by_tcode ?? []).map((t, i) => (
                    <BarRow key={t.tcode} label={t.tcode} count={t.count}
                      percentage={t.percentage} color={TCODE_COLORS[i % TCODE_COLORS.length]} loading={false} />
                  ))
              }
            </div>
          </Section>

          <Section title="By Processing Status">
            <div className="space-y-4">
              {isLoading
                ? Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-8 w-full" />)
                : (metrics?.by_status ?? []).map(s => (
                    <BarRow key={s.status} label={s.status.replace('_', ' ')} count={s.count}
                      percentage={s.percentage}
                      color={STATUS_COLORS[s.status] ?? 'bg-neutral-400'}
                      loading={false} />
                  ))
              }
            </div>
          </Section>
        </div>

        {/* ── Row 4: Recently Posted ─────────────────────────────────────────── */}
        <Section
          title="Recently Posted to SAP"
          action={
            <span className="text-xs text-neutral-400 dark:text-neutral-500">
              Last {recentPosted.length} records
            </span>
          }
        >
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-neutral-100 dark:border-neutral-700">
                  {['Document ID', 'Vendor', 'Type', 'Amount', 'Posted No.', 'Date'].map(h => (
                    <th key={h} className="pb-2.5 text-left text-[11px] font-semibold uppercase tracking-wider text-neutral-400 dark:text-neutral-500 pr-4">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-50 dark:divide-neutral-800">
                {docsLoading
                  ? Array.from({ length: 5 }, (_, i) => (
                      <tr key={i}>
                        <td colSpan={6} className="py-2"><Skeleton className="h-5 w-full" /></td>
                      </tr>
                    ))
                  : recentPosted.length === 0
                    ? (
                      <tr>
                        <td colSpan={6} className="py-8 text-center text-xs text-neutral-400 dark:text-neutral-500">
                          No documents posted to SAP yet
                        </td>
                      </tr>
                    )
                    : recentPosted.map((doc: DocumentListItem) => (
                        <tr key={doc.id} className="hover:bg-neutral-50/60 dark:hover:bg-neutral-700/40">
                          <td className="py-2.5 pr-4 font-mono text-xs text-neutral-500 dark:text-neutral-400">
                            {doc.document_id.slice(0, 10)}…
                          </td>
                          <td className="py-2.5 pr-4 text-xs font-medium text-neutral-800 dark:text-neutral-200 max-w-[140px] truncate">
                            {doc.vendor_name || '—'}
                          </td>
                          <td className="py-2.5 pr-4 text-xs text-neutral-500 dark:text-neutral-400">
                            {DOC_TYPE_LABEL[doc.type as keyof typeof DOC_TYPE_LABEL] ?? doc.type}
                          </td>
                          <td className="py-2.5 pr-4 font-mono text-xs tabular-nums text-neutral-700 dark:text-neutral-300">
                            {doc.amount ? toINR(Number(doc.amount)) : '—'}
                          </td>
                          <td className="py-2.5 pr-4 font-mono text-xs font-semibold text-green-700 dark:text-green-400">
                            {doc.miro_number || doc.grn_number || '—'}
                          </td>
                          <td className="py-2.5 text-xs text-neutral-400 dark:text-neutral-500">
                            {formatDate(doc.uploaded_at)}
                          </td>
                        </tr>
                      ))
                }
              </tbody>
            </table>
          </div>
        </Section>

      </div>
    </div>
  );
}
