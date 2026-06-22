import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  FileText, Landmark, FileCheck, Package, Truck,
  Upload, AlertCircle, ArrowRight,
} from 'lucide-react';
import { useDashboardMetrics } from '@/hooks/useDashboardMetrics';
import { useDocuments }        from '@/hooks/useDocuments';
import { Topbar }     from '@/components/layout/Topbar';
import { Button }     from '@/components/ui/Button';
import { Badge }      from '@/components/ui/Badge';
import { StatusPill } from '@/components/ui/StatusPill';
import { TCodeChip }  from '@/components/ui/TCodeChip';
import { SkeletonRow } from '@/components/ui/Skeleton';
import { formatDate }  from '@/lib/dates';
import { toINR }       from '@/lib/currency';
import { DocumentStatus, type DocumentListItem } from '@/types';
import { cn } from '@/lib/cn';

// ─── Animated counter ─────────────────────────────────────────────────────────

function useCountUp(target: number, duration = 900) {
  const [value, setValue] = useState(0);
  const raf = useRef<number>(0);

  useEffect(() => {
    if (target === 0) { setValue(0); return; }
    const start = performance.now();
    function tick(now: number) {
      const t = Math.min((now - start) / duration, 1);
      // ease-out cubic
      const eased = 1 - (1 - t) ** 3;
      setValue(Math.round(eased * target));
      if (t < 1) raf.current = requestAnimationFrame(tick);
    }
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [target, duration]);

  return value;
}

// ─── Metric card ─────────────────────────────────────────────────────────────

interface MetricCardProps {
  label:      string;
  value:      number | string;
  rawValue?:  number | undefined;
  footer?:    string | undefined;
  accent:     string;
  alert?:     boolean | undefined;
}

function MetricCard({ label, value, rawValue, footer, accent, alert }: MetricCardProps) {
  const animValue = useCountUp(typeof rawValue === 'number' ? rawValue : 0);
  const display   = typeof value === 'string' ? value : animValue.toLocaleString('en-IN');

  return (
    <div className={cn('relative overflow-hidden rounded-xl bg-white ring-1 ring-neutral-200/70 shadow-soft', `border-l-[3px] ${accent}`)}>
      <div className="px-5 py-4">
        <div className="flex items-start justify-between gap-2">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-neutral-400">{label}</p>
          {alert && <AlertCircle className="h-4 w-4 shrink-0 text-amber-500" />}
        </div>
        <p className="mt-2 font-display text-3xl font-semibold text-neutral-900 tabular-nums"
           style={{ fontFamily: 'var(--ff-display)' }}>
          {display}
        </p>
        {footer && <p className="mt-1.5 text-xs text-neutral-400">{footer}</p>}
      </div>
    </div>
  );
}

// ─── Status → row border colour ───────────────────────────────────────────────

function statusBorderCls(status: DocumentStatus | string): string {
  switch (status) {
    case DocumentStatus.POSTED:      return 'border-l-green-400';
    case DocumentStatus.VALIDATED:   return 'border-l-indigo-400';
    case DocumentStatus.EXTRACTED:   return 'border-l-indigo-300';
    case DocumentStatus.EXTRACTING:  return 'border-l-indigo-300';
    case DocumentStatus.VALIDATING:  return 'border-l-amber-400';
    case DocumentStatus.GR_POSTING:  return 'border-l-amber-400';
    case DocumentStatus.GR_POSTED:   return 'border-l-teal-400';
    case DocumentStatus.POSTING:     return 'border-l-amber-400';
    case DocumentStatus.FAILED:      return 'border-l-red-400';
    default:                        return 'border-l-neutral-200';
  }
}

// ─── Horizontal bar ───────────────────────────────────────────────────────────

interface BarRowProps {
  label:      string;
  count:      number;
  total:      number;
  pct:        number;
  color:      string;
  delay:      number;
}

function BarRow({ label, count, total, pct, color, delay }: BarRowProps) {
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const id = setTimeout(() => setWidth(total > 0 ? pct : 0), delay);
    return () => clearTimeout(id);
  }, [pct, total, delay]);

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="font-medium text-neutral-700">{label}</span>
        <span className="tabular-nums text-neutral-400">{count} <span className="text-neutral-300">·</span> {pct.toFixed(0)}%</span>
      </div>
      <div className="h-[6px] w-full rounded-none bg-neutral-100">
        <div
          className={cn('h-full rounded-none transition-all duration-700 ease-out', color)}
          style={{ width: `${width}%` }}
        />
      </div>
    </div>
  );
}

// ─── Quick action card ────────────────────────────────────────────────────────

interface QuickActionProps {
  label:       string;
  tcode:       string;
  icon:        React.ElementType;
  active:      boolean;
  uploadType?: string;
}

function QuickAction({ label, tcode, icon: Icon, active, uploadType }: QuickActionProps) {
  const navigate = useNavigate();

  return (
    <div className={cn(
      'relative flex flex-col items-center gap-3 rounded-xl border border-neutral-200 bg-white p-5 text-center shadow-soft',
      !active && 'opacity-50',
    )}>
      <div className={cn(
        'flex h-10 w-10 items-center justify-center rounded-lg',
        active ? 'bg-indigo-50' : 'bg-neutral-100',
      )}>
        <Icon className={cn('h-5 w-5', active ? 'text-indigo-600' : 'text-neutral-400')} />
      </div>
      <div>
        <p className="text-sm font-semibold text-neutral-800">{label}</p>
        <p className="mt-0.5 font-mono text-xs text-neutral-400">{tcode}</p>
      </div>
      {active ? (
        <Button
          size="sm"
          onClick={() => navigate(`/upload${uploadType ? `?type=${uploadType}` : ''}`)}
          icon={<Upload className="h-3 w-3" />}
        >
          Upload
        </Button>
      ) : (
        <Badge variant="neutral">Coming soon</Badge>
      )}
    </div>
  );
}

// ─── Main dashboard page ──────────────────────────────────────────────────────

export default function DashboardPage() {
  const navigate = useNavigate();

  const { data: metrics, isLoading: metricsLoading } = useDashboardMetrics();
  const { data: recent,  isLoading: docsLoading }    = useDocuments({ limit: 6, page: 1 });

  // Tab title with pending count
  useEffect(() => {
    const pending = metrics?.pending_review ?? 0;
    document.title = pending > 0
      ? `(${pending}) DocParser — Dashboard`
      : 'DocParser — Dashboard';
    return () => { document.title = 'DocParser'; };
  }, [metrics?.pending_review]);

  const totalValue   = metrics?.total_value_inr ?? '0';
  const pendingAlert = (metrics?.pending_review ?? 0) > 10;

  // By-tcode bars
  const tcodeTotal = metrics?.by_tcode.reduce((s, t) => s + t.count, 0) ?? 0;

  // By-status bars — only terminal/notable statuses
  const statusOrder = ['posted', 'validated', 'extracted', 'failed', 'uploading'];
  const statusColors: Record<string, string> = {
    posted:    'bg-green-500',
    validated: 'bg-indigo-400',
    extracted: 'bg-indigo-300',
    failed:    'bg-red-400',
    uploading: 'bg-neutral-300',
  };
  const statusTotal = metrics?.by_status.reduce((s, t) => s + t.count, 0) ?? 0;
  const sortedStatuses = [...(metrics?.by_status ?? [])].sort(
    (a, b) => statusOrder.indexOf(a.status) - statusOrder.indexOf(b.status),
  );

  return (
    <>
      <Topbar
        title="Dashboard"
        subtitle="Overview of document processing activity"
      >
        <Button
          size="sm"
          variant="secondary"
          icon={<Upload className="h-3.5 w-3.5" />}
          onClick={() => navigate('/upload')}
        >
          Upload
        </Button>
      </Topbar>

      <div className="space-y-6 p-6">

        {/* ── Metric strip ─────────────────────────────────────────────────── */}
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <MetricCard
            label="Total Processed"
            value={metrics?.total_processed ?? 0}
            rawValue={metrics?.total_processed}
            footer="All time"
            accent="border-l-indigo-500"
          />
          <MetricCard
            label="Posted to SAP"
            value={metrics?.posted_to_sap ?? 0}
            rawValue={metrics?.posted_to_sap}
            footer={metrics ? `${((metrics.posted_to_sap / Math.max(metrics.total_processed, 1)) * 100).toFixed(0)}% success rate` : ''}
            accent="border-l-green-500"
          />
          <MetricCard
            label="Pending Review"
            value={metrics?.pending_review ?? 0}
            rawValue={metrics?.pending_review}
            footer="Awaiting validation"
            accent="border-l-amber-500"
            alert={pendingAlert}
          />
          <MetricCard
            label="Total Value INR"
            value={toINR(Number(totalValue))}
            footer="Across all invoices"
            accent="border-l-slate-400"
          />
        </div>

        {/* ── Two-column layout ─────────────────────────────────────────────── */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_300px]">

          {/* LEFT — Recent documents table */}
          <div className="rounded-xl bg-white shadow-soft ring-1 ring-neutral-200/70 overflow-hidden">
            <div className="flex items-center justify-between border-b border-neutral-100 px-5 py-3.5">
              <h2 className="text-sm font-semibold text-neutral-800">Recent Documents</h2>
              <button
                type="button"
                onClick={() => navigate('/documents')}
                className="flex items-center gap-1 text-xs text-indigo-600 hover:text-indigo-800 transition-colors"
              >
                View all <ArrowRight className="h-3 w-3" />
              </button>
            </div>

            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-neutral-100 bg-neutral-50">
                  <th className="px-5 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-neutral-400">Document</th>
                  <th className="px-3 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-neutral-400">T-Code</th>
                  <th className="px-3 py-3 text-right text-[11px] font-semibold uppercase tracking-wider text-neutral-400">Amount</th>
                  <th className="px-3 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-neutral-400">GRN / MIRO No.</th>
                  <th className="px-3 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-neutral-400">Status</th>
                  <th className="px-5 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-neutral-400">Date</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100">
                {docsLoading
                  ? Array.from({ length: 5 }, (_, i) => (
                      <tr key={i}><td colSpan={5} className="p-0"><SkeletonRow /></td></tr>
                    ))
                  : !recent?.documents.length
                    ? (
                      <tr>
                        <td colSpan={5} className="py-16 text-center">
                          <div className="flex flex-col items-center gap-3">
                            <div className="rounded-full bg-neutral-100 p-4">
                              <FileText className="h-8 w-8 text-neutral-300" />
                            </div>
                            <div>
                              <p className="text-sm font-medium text-neutral-500">No documents yet</p>
                              <p className="mt-0.5 text-xs text-neutral-400">Upload your first invoice to get started</p>
                            </div>
                            <Button size="sm" icon={<Upload className="h-3.5 w-3.5" />} onClick={() => navigate('/upload')}>
                              Upload document
                            </Button>
                          </div>
                        </td>
                      </tr>
                    )
                    : recent.documents.map((doc: DocumentListItem) => (
                        <tr
                          key={doc.id}
                          className={cn(
                            'cursor-pointer border-l-[3px] transition-colors hover:bg-neutral-50',
                            statusBorderCls(doc.status),
                          )}
                          onClick={() => navigate(`/documents/${doc.document_id}`)}
                        >
                          <td className="px-5 py-3.5">
                            <p className="font-medium text-neutral-800 font-mono text-xs">
                              {doc.document_id.slice(0, 12)}…
                            </p>
                            <p className="mt-0.5 text-xs text-neutral-400 truncate max-w-[180px]">
                              {doc.vendor_name ?? '—'}
                            </p>
                          </td>
                          <td className="px-3 py-3.5">
                            <TCodeChip tcode={doc.tcode} />
                          </td>
                          <td className="px-3 py-3.5 text-right">
                            <span className="font-mono text-xs tabular-nums text-neutral-700">
                              {doc.amount ? toINR(Number(doc.amount)) : '—'}
                            </span>
                          </td>
                          <td className="px-3 py-3.5">
                            <div className="flex flex-col gap-0.5">
                              {doc.grn_number && (
                                <span className="font-mono text-xs font-semibold text-teal-700">GRN: {doc.grn_number}</span>
                              )}
                              {doc.miro_number && (
                                <span className="font-mono text-xs font-semibold text-green-700">MIRO: {doc.miro_number}</span>
                              )}
                              {!doc.grn_number && !doc.miro_number && (
                                <span className="text-xs text-neutral-300">—</span>
                              )}
                            </div>
                          </td>
                          <td className="px-3 py-3.5">
                            <StatusPill status={doc.status as DocumentStatus} />
                          </td>
                          <td className="px-5 py-3.5 text-xs text-neutral-400">
                            {formatDate(doc.uploaded_at)}
                          </td>
                        </tr>
                      ))
                }
              </tbody>
            </table>
          </div>

          {/* RIGHT — Chart cards */}
          <div className="space-y-4">

            {/* By T-Code */}
            <div className="rounded-xl bg-white shadow-soft ring-1 ring-neutral-200/70 p-5">
              <h2 className="mb-4 text-sm font-semibold text-neutral-800">By T-Code</h2>
              {metricsLoading
                ? <div className="space-y-3">{[1,2,3,4].map(i => <div key={i} className="h-6 animate-pulse rounded bg-neutral-100" />)}</div>
                : metrics?.by_tcode.length
                  ? (
                    <div className="space-y-3">
                      {metrics.by_tcode.map((t, i) => (
                        <BarRow
                          key={t.tcode}
                          label={t.tcode}
                          count={t.count}
                          total={tcodeTotal}
                          pct={t.percentage}
                          color="bg-indigo-500"
                          delay={i * 80}
                        />
                      ))}
                    </div>
                  )
                  : <p className="text-xs text-neutral-400">No data</p>
              }
            </div>

            {/* By Status */}
            <div className="rounded-xl bg-white shadow-soft ring-1 ring-neutral-200/70 p-5">
              <h2 className="mb-4 text-sm font-semibold text-neutral-800">By Status</h2>
              {metricsLoading
                ? <div className="space-y-3">{[1,2,3].map(i => <div key={i} className="h-6 animate-pulse rounded bg-neutral-100" />)}</div>
                : sortedStatuses.length
                  ? (
                    <div className="space-y-3">
                      {sortedStatuses.map((s, i) => (
                        <BarRow
                          key={s.status}
                          label={s.status.charAt(0).toUpperCase() + s.status.slice(1)}
                          count={s.count}
                          total={statusTotal}
                          pct={s.percentage}
                          color={statusColors[s.status] ?? 'bg-neutral-400'}
                          delay={i * 80}
                        />
                      ))}
                    </div>
                  )
                  : <p className="text-xs text-neutral-400">No data</p>
              }
            </div>
          </div>
        </div>

        {/* ── Quick actions ─────────────────────────────────────────────────── */}
        <div>
          <h2 className="mb-3 text-sm font-semibold text-neutral-700">Quick Actions</h2>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
            <QuickAction label="Vendor Invoice"  tcode="MIRO" icon={FileText}  active uploadType="vendor_invoice" />
            <QuickAction label="Bank Statement"  tcode="FF67" icon={Landmark}  active={false} />
            <QuickAction label="Payment Advice"  tcode="F-28" icon={FileCheck} active={false} />
            <QuickAction label="Goods Receipt"   tcode="MIGO" icon={Package}   active uploadType="goods_receipt" />
            <QuickAction label="Freight Invoice" tcode="MIRO" icon={Truck}     active={false} />
          </div>
        </div>

      </div>
    </>
  );
}
