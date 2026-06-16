import { useState } from 'react';
import { CheckCircle2, XCircle, AlertTriangle, FileText, Database } from 'lucide-react';
import type { SAPValidation, MismatchEntry, GRStatusEntry } from '@/types';
import { Tooltip } from '@/components/ui/Tooltip';
import { cn } from '@/lib/cn';

// ─── SVG confidence ring ──────────────────────────────────────────────────────

function ConfidenceRing({ score }: { score: number }) {
  const pct      = Math.round(score * 100);
  const radius   = 36;
  const stroke   = 6;
  const circ     = 2 * Math.PI * radius;
  const dash     = (pct / 100) * circ;
  const color    = pct >= 75 ? '#16a34a' : pct >= 50 ? '#d97706' : '#dc2626';
  const label    = pct >= 75 ? 'Valid' : pct >= 50 ? 'Review' : 'Invalid';
  const labelClr = pct >= 75 ? 'text-green-600' : pct >= 50 ? 'text-amber-600' : 'text-red-600';

  return (
    <div className="flex flex-col items-center gap-1">
      <svg width={88} height={88} viewBox="0 0 88 88">
        <circle cx={44} cy={44} r={radius} stroke="#e5e7eb" strokeWidth={stroke} fill="none" />
        <circle
          cx={44} cy={44} r={radius}
          stroke={color} strokeWidth={stroke} fill="none"
          strokeDasharray={`${dash} ${circ}`}
          strokeLinecap="butt"
          transform="rotate(-90 44 44)"
          style={{ transition: 'stroke-dasharray 0.8s ease-out' }}
        />
        <text x={44} y={40} textAnchor="middle" dominantBaseline="middle"
          fontSize={16} fontWeight={700} fill="#111827" fontFamily="var(--ff-display)">
          {pct}%
        </text>
        <text x={44} y={58} textAnchor="middle" dominantBaseline="middle"
          fontSize={9} fill="#6b7280" fontFamily="var(--ff-body)">
          Overall
        </text>
      </svg>
      <span className={cn('text-xs font-semibold', labelClr)}>{label}</span>
    </div>
  );
}

// ─── Loading animation ────────────────────────────────────────────────────────

export function ValidationLoading() {
  return (
    <div className="flex flex-col items-center gap-8 py-12">
      <div className="flex items-center gap-6">
        <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-indigo-100">
          <FileText className="h-7 w-7 text-indigo-600" />
        </div>

        {/* Animated connecting line */}
        <div className="relative h-1 w-24 overflow-hidden rounded-full bg-neutral-100">
          <div className="absolute inset-0 -translate-x-full animate-[slide_1.2s_ease-in-out_infinite] bg-gradient-to-r from-transparent via-indigo-500 to-transparent" />
        </div>

        <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-green-100">
          <Database className="h-7 w-7 text-green-600" />
        </div>
      </div>

      <div className="text-center">
        <p className="text-sm font-semibold text-neutral-800">Validating against SAP</p>
        <p className="mt-1 text-xs text-neutral-400">Fetching PO data and comparing line items…</p>
      </div>
    </div>
  );
}

// ─── Tab switcher ─────────────────────────────────────────────────────────────

type Tab = 'header' | 'lines' | 'gr';

function TabBar({ active, onChange }: { active: Tab; onChange: (t: Tab) => void }) {
  const tabs: { key: Tab; label: string }[] = [
    { key: 'header', label: 'Header' },
    { key: 'lines',  label: 'Line Items' },
    { key: 'gr',     label: 'GR Status' },
  ];
  return (
    <div className="inline-flex rounded-lg bg-neutral-100 p-1 gap-1">
      {tabs.map((t) => (
        <button
          key={t.key}
          type="button"
          onClick={() => onChange(t.key)}
          className={cn(
            'rounded-md px-4 py-1.5 text-xs font-semibold transition-colors',
            active === t.key
              ? 'bg-white text-neutral-900 shadow-soft-sm'
              : 'text-neutral-500 hover:text-neutral-700',
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

// ─── Header comparison table ──────────────────────────────────────────────────

function HeaderTab({ mismatches }: { mismatches: MismatchEntry[] }) {
  const rows = mismatches.length === 0
    ? [{ field: '—', extracted: '—', sap: '—', match: true }]
    : mismatches.map((m) => ({
        field:     m.field,
        extracted: m.extracted_value,
        sap:       m.sap_value,
        match:     false,
      }));

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-neutral-100 bg-neutral-50 text-xs">
            <th className="px-4 py-2.5 text-left font-semibold uppercase tracking-wider text-neutral-400">Field</th>
            <th className="px-4 py-2.5 text-left font-semibold uppercase tracking-wider text-neutral-400">From Invoice</th>
            <th className="px-4 py-2.5 text-left font-semibold uppercase tracking-wider text-neutral-400">From SAP</th>
            <th className="px-4 py-2.5 text-center font-semibold uppercase tracking-wider text-neutral-400">Match</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr
              key={i}
              className={cn(
                'border-b border-neutral-100 text-sm',
                !r.match && 'bg-red-50/60',
              )}
            >
              <td className="px-4 py-3 font-medium text-neutral-700">{r.field}</td>
              <td className="px-4 py-3 text-neutral-600">{r.extracted}</td>
              <td className="px-4 py-3 text-neutral-600">{r.sap}</td>
              <td className="px-4 py-3 text-center">
                {r.match
                  ? <CheckCircle2 className="mx-auto h-4 w-4 text-green-500" />
                  : <XCircle      className="mx-auto h-4 w-4 text-red-500" />
                }
              </td>
            </tr>
          ))}
          {mismatches.length === 0 && (
            <tr>
              <td colSpan={4} className="px-4 py-6 text-center text-sm text-neutral-400">
                No header mismatches — all fields match SAP data.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

// ─── Line items tab ───────────────────────────────────────────────────────────

function LinesTab({ mismatches }: { mismatches: MismatchEntry[] }) {
  const lineRejected = mismatches.filter((m) => m.severity === 'error');
  const lineWarning  = mismatches.filter((m) => m.severity === 'warning');

  if (lineRejected.length === 0 && lineWarning.length === 0) {
    return (
      <div className="py-8 text-center text-sm text-neutral-400">
        All line items match SAP purchase order data.
      </div>
    );
  }

  return (
    <div className="divide-y divide-neutral-100">
      {[...lineRejected, ...lineWarning].map((m, i) => (
        <div
          key={i}
          className={cn(
            'flex items-start gap-3 px-4 py-3',
            m.severity === 'error' ? 'bg-red-50/50' : 'bg-amber-50/50',
          )}
        >
          <AlertTriangle className={cn('mt-0.5 h-4 w-4 shrink-0', m.severity === 'error' ? 'text-red-500' : 'text-amber-500')} />
          <div className="flex-1 text-sm">
            <span className="font-medium text-neutral-800">{m.field}</span>
            <Tooltip content={`Invoice: ${m.extracted_value} vs SAP: ${m.sap_value}`} side="right">
              <span className="ml-2 cursor-help text-xs text-neutral-400 underline decoration-dotted">
                See difference
              </span>
            </Tooltip>
          </div>
          <span className={cn('shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase', m.severity === 'error' ? 'bg-red-100 text-red-600' : 'bg-amber-100 text-amber-600')}>
            {m.severity}
          </span>
        </div>
      ))}
    </div>
  );
}

// ─── GR status tab ────────────────────────────────────────────────────────────

const GR_STATUS_CLS: Record<string, string> = {
  complete: 'bg-green-100 text-green-700',
  partial:  'bg-amber-100 text-amber-700',
  missing:  'bg-red-100   text-red-700',
};

function GRTab({ grStatus }: { grStatus: GRStatusEntry[] }) {
  if (!grStatus.length) {
    return <div className="py-8 text-center text-sm text-neutral-400">No GR data available.</div>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-neutral-100 bg-neutral-50 text-xs">
            <th className="px-4 py-2.5 text-left font-semibold uppercase tracking-wider text-neutral-400">Line</th>
            <th className="px-4 py-2.5 text-left font-semibold uppercase tracking-wider text-neutral-400">GR Documents</th>
            <th className="px-4 py-2.5 text-right font-semibold uppercase tracking-wider text-neutral-400">GR Qty</th>
            <th className="px-4 py-2.5 text-right font-semibold uppercase tracking-wider text-neutral-400">Invoice Qty</th>
            <th className="px-4 py-2.5 text-center font-semibold uppercase tracking-wider text-neutral-400">Status</th>
          </tr>
        </thead>
        <tbody>
          {grStatus.map((g, i) => (
            <tr key={i} className="border-b border-neutral-100 hover:bg-neutral-50">
              <td className="px-4 py-3 font-mono text-xs text-neutral-600">{g.line_number}</td>
              <td className="px-4 py-3">
                {g.gr_documents.length
                  ? g.gr_documents.map((d) => (
                      <span key={d} className="mr-1 block font-mono text-[10px] text-neutral-600">{d}</span>
                    ))
                  : <span className="text-neutral-300">—</span>
                }
              </td>
              <td className="px-4 py-3 text-right font-mono text-xs tabular-nums">{g.total_gr_qty}</td>
              <td className="px-4 py-3 text-right font-mono text-xs tabular-nums">{g.invoice_qty}</td>
              <td className="px-4 py-3 text-center">
                <span className={cn('rounded-full px-2.5 py-0.5 text-xs font-semibold capitalize', GR_STATUS_CLS[g.status] ?? 'bg-neutral-100 text-neutral-600')}>
                  {g.status}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Main results panel ───────────────────────────────────────────────────────

interface ValidationPanelProps {
  validation:  SAPValidation;
  onPost:      () => void;
  isPosting:   boolean;
}

export function ValidationPanel({ validation, onPost, isPosting }: ValidationPanelProps) {
  const [tab, setTab] = useState<Tab>('header');
  const pct = Math.round(validation.overall_confidence * 100);
  const isLow = pct < 75;

  return (
    <div className="space-y-5">
      {/* Score + sub-scores */}
      <div className="flex flex-wrap items-center gap-6 rounded-xl border border-neutral-200 bg-white p-5">
        <ConfidenceRing score={validation.overall_confidence} />
        <div className="flex-1 grid grid-cols-3 gap-4 min-w-0">
          {[
            { label: 'Header',     score: validation.header_confidence },
            { label: 'Line Items', score: validation.line_item_confidence },
            { label: 'GR Status',  score: validation.gr_confidence },
          ].map(({ label, score }) => {
            const p   = Math.round(score * 100);
            const cls = p >= 75 ? 'text-green-600' : p >= 50 ? 'text-amber-600' : 'text-red-600';
            return (
              <div key={label} className="space-y-1 text-center">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-neutral-400">{label}</p>
                <p className={cn('font-display text-xl font-bold tabular-nums', cls)} style={{ fontFamily: 'var(--ff-display)' }}>
                  {p}%
                </p>
              </div>
            );
          })}
        </div>
      </div>

      {/* Tabs + detail */}
      <div className="rounded-xl border border-neutral-200 bg-white overflow-hidden">
        <div className="flex items-center gap-4 border-b border-neutral-100 px-5 py-3.5">
          <TabBar active={tab} onChange={setTab} />
          <span className="ml-auto text-xs text-neutral-400">
            {validation.mismatches.length} mismatch{validation.mismatches.length !== 1 ? 'es' : ''} found
          </span>
        </div>

        {tab === 'header' && <HeaderTab mismatches={validation.mismatches} />}
        {tab === 'lines'  && <LinesTab  mismatches={validation.mismatches} />}
        {tab === 'gr'     && <GRTab     grStatus={validation.gr_status} />}
      </div>

      {/* Action bar */}
      <div className="sticky bottom-0 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-neutral-200 bg-white px-5 py-3.5 shadow-lg">
        <div>
          {isLow ? (
            <div className="flex items-center gap-2 text-sm text-amber-700">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              Score below threshold — manual review recommended
            </div>
          ) : (
            <p className="text-sm text-green-700 font-medium">
              Validation passed — ready to post to MIRO
            </p>
          )}
          {validation.recommendation && (
            <p className="mt-0.5 text-xs text-neutral-400">{validation.recommendation}</p>
          )}
        </div>

        <button
          type="button"
          onClick={onPost}
          disabled={isPosting}
          className={cn(
            'inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold text-white shadow-soft-sm transition-colors',
            'disabled:opacity-60 disabled:pointer-events-none',
            isLow
              ? 'bg-amber-500 hover:bg-amber-600 active:bg-amber-700'
              : 'bg-green-600 hover:bg-green-700 active:bg-green-800',
          )}
        >
          {isPosting ? (
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
          ) : null}
          {isLow ? 'Post anyway' : 'Post to SAP MIRO'}
        </button>
      </div>
    </div>
  );
}
