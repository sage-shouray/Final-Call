import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import {
  ArrowLeft, ChevronDown, ChevronUp,
  CheckCircle2, Clock, AlertCircle, Loader2,
  FileText, X, ClipboardList,
} from 'lucide-react';
import { useDocument }          from '@/hooks/useDocument';
import { useDocumentWebSocket } from '@/hooks/useDocumentWebSocket';
import { StatusPill }    from '@/components/ui/StatusPill';
import { TCodeChip }     from '@/components/ui/TCodeChip';
import { Badge }         from '@/components/ui/Badge';
import { Skeleton }      from '@/components/ui/Skeleton';
import { Topbar }        from '@/components/layout/Topbar';
import { formatDateTime, formatDate } from '@/lib/dates';
import { toINR }          from '@/lib/currency';
import { cn }             from '@/lib/cn';
import api from '@/lib/api';
import { DocumentStatus, type Document } from '@/types';

// ─── Types ────────────────────────────────────────────────────────────────────

interface AuditEntry {
  id?:        string;
  timestamp:  string;
  action:     string;
  user?:      string | undefined;
  stage?:     string | undefined;
  message?:   string | undefined;
  detail?:    string | undefined;
}

// ─── Row helper ───────────────────────────────────────────────────────────────

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2 border-b border-neutral-50 last:border-0">
      <span className="shrink-0 text-xs text-neutral-500 min-w-[120px]">{label}</span>
      <span className="text-right text-xs font-medium text-neutral-800">{value}</span>
    </div>
  );
}

// ─── Collapsible section ──────────────────────────────────────────────────────

function Collapsible({
  title, defaultOpen = true, children,
}: {
  title: string; defaultOpen?: boolean; children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-xl border border-neutral-200 bg-white overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-5 py-3.5 text-sm font-semibold text-neutral-800 hover:bg-neutral-50 transition-colors"
      >
        {title}
        {open
          ? <ChevronUp   className="h-4 w-4 text-neutral-400" />
          : <ChevronDown className="h-4 w-4 text-neutral-400" />
        }
      </button>
      {open && <div className="border-t border-neutral-100 px-5 py-4">{children}</div>}
    </div>
  );
}

// ─── Timeline ─────────────────────────────────────────────────────────────────

interface TimelineStep {
  key:         string;
  label:       string;
  description: string;
  timestamp:   string | null | undefined;
  done:        boolean;
  active:      boolean;
  failed:      boolean;
}

function getTimeline(doc: Document): TimelineStep[] {
  const status = doc.status as DocumentStatus;
  const isFailed = status === DocumentStatus.FAILED;

  const ORDER: DocumentStatus[] = [
    DocumentStatus.UPLOADED,
    DocumentStatus.EXTRACTED,
    DocumentStatus.VALIDATED,
    DocumentStatus.POSTED,
  ];
  const currentIdx = ORDER.indexOf(
    isFailed ? DocumentStatus.UPLOADED : status as DocumentStatus,
  );

  return [
    {
      key:         'uploaded',
      label:       'Document Uploaded',
      description: doc.file?.original_name ?? 'File received',
      timestamp:   doc.uploaded_at,
      done:        true,
      active:      false,
      failed:      false,
    },
    {
      key:         'extracted',
      label:       'OCR Extraction',
      description: doc.extracted
        ? `${doc.extracted.line_items?.length ?? 0} line item${doc.extracted.line_items?.length === 1 ? '' : 's'} extracted`
        : status === DocumentStatus.EXTRACTING
          ? 'Processing with Gemini AI…'
          : 'Pending',
      timestamp:   doc.extracted ? doc.updated_at : null,
      done:        !!doc.extracted,
      active:      status === DocumentStatus.EXTRACTING,
      failed:      isFailed && currentIdx < 1,
    },
    {
      key:         'validated',
      label:       'SAP Validation',
      description: doc.sap_validation
        ? `Score: ${Math.round(doc.sap_validation.overall_confidence * 100)}%`
        : status === DocumentStatus.VALIDATING
          ? 'Validating against SAP…'
          : 'Pending',
      timestamp:   doc.sap_validation?.fetched_at,
      done:        !!doc.sap_validation,
      active:      status === DocumentStatus.VALIDATING,
      failed:      isFailed && currentIdx < 2,
    },
    {
      key:         'posted',
      label:       'MIRO Posting',
      description: doc.miro_posting
        ? `MIRO: ${doc.miro_posting.miro_number}`
        : status === DocumentStatus.POSTING
          ? 'Posting to SAP MIRO…'
          : 'Pending',
      timestamp:   doc.miro_posting?.posted_at,
      done:        !!doc.miro_posting,
      active:      status === DocumentStatus.POSTING,
      failed:      isFailed && currentIdx < 3,
    },
  ];
}

function Timeline({ doc }: { doc: Document }) {
  const steps = getTimeline(doc);
  return (
    <div className="space-y-0">
      {steps.map((step, i) => (
        <div key={step.key} className="relative flex gap-3">
          {/* Connector line */}
          {i < steps.length - 1 && (
            <div className={cn(
              'absolute left-[13px] top-7 bottom-0 w-0.5 transition-colors',
              step.done ? 'bg-green-200' : 'bg-neutral-100',
            )} />
          )}

          {/* Icon */}
          <div className="relative z-10 mt-0.5 shrink-0">
            {step.done && (
              <div className="flex h-7 w-7 items-center justify-center rounded-full bg-green-100">
                <CheckCircle2 className="h-4 w-4 text-green-600" />
              </div>
            )}
            {step.active && (
              <div className="flex h-7 w-7 items-center justify-center rounded-full bg-indigo-100">
                <Loader2 className="h-4 w-4 animate-spin text-indigo-600" />
              </div>
            )}
            {step.failed && (
              <div className="flex h-7 w-7 items-center justify-center rounded-full bg-red-100">
                <AlertCircle className="h-4 w-4 text-red-600" />
              </div>
            )}
            {!step.done && !step.active && !step.failed && (
              <div className="flex h-7 w-7 items-center justify-center rounded-full bg-neutral-100">
                <Clock className="h-3.5 w-3.5 text-neutral-400" />
              </div>
            )}
          </div>

          {/* Content */}
          <div className="min-w-0 flex-1 pb-5">
            <p className={cn(
              'text-xs font-semibold',
              step.done   ? 'text-neutral-800'
              : step.active ? 'text-indigo-700'
              : step.failed ? 'text-red-700'
              : 'text-neutral-400',
            )}>
              {step.label}
            </p>
            <p className="mt-0.5 text-xs text-neutral-400">{step.description}</p>
            {step.timestamp && (
              <p className="mt-0.5 text-[10px] text-neutral-300 font-mono">
                {formatDateTime(step.timestamp)}
              </p>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── Audit log drawer ─────────────────────────────────────────────────────────

function AuditDrawer({ docId, open, onClose }: { docId: string; open: boolean; onClose: () => void }) {
  const { data: entries, isLoading } = useQuery<AuditEntry[]>({
    queryKey: ['audit', docId],
    queryFn:  async () => {
      const resp = await api.get<AuditEntry[]>(`/documents/${docId}/audit`);
      return resp.data;
    },
    enabled: open && !!docId,
  });

  return (
    <>
      <div
        className={cn(
          'fixed inset-0 z-30 bg-black/20 transition-opacity',
          open ? 'opacity-100' : 'pointer-events-none opacity-0',
        )}
        onClick={onClose}
      />
      <div
        className={cn(
          'fixed inset-y-0 right-0 z-40 flex w-96 flex-col bg-white shadow-xl transition-transform duration-300',
          open ? 'translate-x-0' : 'translate-x-full',
        )}
      >
        <div className="flex items-center justify-between border-b border-neutral-100 px-5 py-4">
          <h3 className="text-sm font-semibold text-neutral-900">Audit Log</h3>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1 text-neutral-400 hover:bg-neutral-100 transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5">
          {isLoading && (
            <div className="space-y-3">
              {Array.from({ length: 5 }, (_, i) => (
                <div key={i} className="space-y-1">
                  <Skeleton className="h-3 w-24" />
                  <Skeleton className="h-8 w-full" />
                </div>
              ))}
            </div>
          )}

          {!isLoading && (!entries || entries.length === 0) && (
            <p className="text-center text-sm text-neutral-400 py-8">No audit entries found.</p>
          )}

          {!isLoading && entries && entries.length > 0 && (
            <div className="space-y-3">
              {entries.map((e, i) => (
                <div key={e.id ?? i} className="rounded-lg border border-neutral-100 bg-neutral-50 p-3">
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-xs font-semibold text-neutral-800">
                      {e.action ?? e.stage ?? 'Event'}
                    </span>
                    <span className="shrink-0 text-[10px] font-mono text-neutral-400">
                      {formatDateTime(e.timestamp)}
                    </span>
                  </div>
                  {(e.message ?? e.detail) && (
                    <p className="mt-1 text-xs text-neutral-500">{e.message ?? e.detail}</p>
                  )}
                  {e.user && (
                    <p className="mt-1 text-[10px] text-neutral-300">by {e.user}</p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  );
}

// ─── Summary strip ────────────────────────────────────────────────────────────

function SummaryStrip({ doc }: { doc: Document }) {
  const extracted = doc.extracted;
  const miro      = doc.miro_posting;

  return (
    <div className="grid grid-cols-1 gap-px rounded-xl border border-neutral-200 bg-neutral-200 overflow-hidden sm:grid-cols-3">
      {/* Vendor & invoice */}
      <div className="bg-white px-5 py-4">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-neutral-400">Vendor</p>
        <p className="mt-1 truncate text-sm font-semibold text-neutral-900">
          {extracted?.vendor_name || '—'}
        </p>
        <p className="mt-0.5 font-mono text-xs text-neutral-500">
          {extracted?.invoice_no || doc.document_id.slice(0, 8) + '…'}
        </p>
      </div>

      {/* Status & type */}
      <div className="bg-white px-5 py-4">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-neutral-400">Status</p>
        <div className="mt-1.5 flex items-center gap-2 flex-wrap">
          <StatusPill status={doc.status as DocumentStatus} />
          <TCodeChip tcode={doc.tcode} />
        </div>
        <p className="mt-1 text-xs text-neutral-400">{formatDate(doc.uploaded_at)}</p>
      </div>

      {/* Amount & MIRO */}
      <div className="bg-white px-5 py-4">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-neutral-400">Amount</p>
        <p className="mt-1 text-sm font-bold text-neutral-900 tabular-nums">
          {extracted?.gross_amount ? toINR(Number(extracted.gross_amount)) : '—'}
        </p>
        {miro?.miro_number && (
          <p className="mt-0.5 font-mono text-xs text-green-700">
            MIRO: {miro.miro_number}
          </p>
        )}
      </div>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function DocumentDetailPage() {
  const { id }    = useParams<{ id: string }>();
  const navigate  = useNavigate();
  const qc        = useQueryClient();
  const [auditOpen, setAuditOpen] = useState(false);

  const { data: doc, isLoading, isError } = useDocument(id);

  const validateMutation = useMutation({
    mutationFn: () => api.post(`/documents/${id}/validate`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['document', id] }),
  });

  const retryMutation = useMutation({
    mutationFn: () => api.post(`/documents/${id}/retry`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['document', id] }),
  });

  const miroMutation = useMutation({
    mutationFn: () => api.post(`/documents/${id}/post-miro`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['document', id] }),
  });

  const { event } = useDocumentWebSocket(id);
  useEffect(() => {
    if (event) qc.invalidateQueries({ queryKey: ['document', id] });
  }, [event, id, qc]);

  // ── Loading ────────────────────────────────────────────────────────────────

  if (isLoading) {
    return (
      <>
        <Topbar title="Document" />
        <div className="space-y-5 p-6">
          <Skeleton className="h-6 w-48" />
          <div className="grid gap-px rounded-xl border border-neutral-200 bg-neutral-200 sm:grid-cols-3">
            {[1,2,3].map((i) => (
              <div key={i} className="bg-white p-5"><Skeleton lines={3} /></div>
            ))}
          </div>
          <div className="grid gap-5 lg:grid-cols-3">
            <div className="lg:col-span-2 space-y-4">
              <Skeleton className="h-48 w-full rounded-xl" />
              <Skeleton className="h-48 w-full rounded-xl" />
            </div>
            <div><Skeleton className="h-64 w-full rounded-xl" /></div>
          </div>
        </div>
      </>
    );
  }

  // ── Error ──────────────────────────────────────────────────────────────────

  if (isError || !doc) {
    return (
      <>
        <Topbar title="Document" />
        <div className="flex h-64 flex-col items-center justify-center gap-3 p-6">
          <AlertCircle className="h-8 w-8 text-neutral-300" />
          <p className="text-sm text-neutral-400">Document not found or could not be loaded.</p>
          <button
            type="button"
            onClick={() => navigate('/documents')}
            className="text-xs text-primary-600 underline"
          >
            Back to documents
          </button>
        </div>
      </>
    );
  }

  const extracted  = doc.extracted;
  const validation = doc.sap_validation;
  const miro       = doc.miro_posting;
  const status     = doc.status as DocumentStatus;

  return (
    <>
      <Topbar
        title={extracted?.vendor_name || 'Document Detail'}
        subtitle={doc.document_id}
      >
        {status === DocumentStatus.FAILED && (
          <button
            type="button"
            onClick={() => retryMutation.mutate()}
            disabled={retryMutation.isPending}
            className="inline-flex items-center gap-1.5 rounded-lg bg-amber-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-600 disabled:opacity-60 transition-colors"
          >
            {retryMutation.isPending
              ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
              : <AlertCircle className="h-3.5 w-3.5" />}
            Retry OCR
          </button>
        )}
        {status === DocumentStatus.EXTRACTED && (
          <button
            type="button"
            onClick={() => validateMutation.mutate()}
            disabled={validateMutation.isPending}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-60 transition-colors"
          >
            {validateMutation.isPending
              ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
              : <CheckCircle2 className="h-3.5 w-3.5" />}
            Validate with SAP
          </button>
        )}
        {status === DocumentStatus.VALIDATED && (
          <button
            type="button"
            onClick={() => miroMutation.mutate()}
            disabled={miroMutation.isPending}
            className="inline-flex items-center gap-1.5 rounded-lg bg-green-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-green-700 disabled:opacity-60 transition-colors"
          >
            {miroMutation.isPending
              ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
              : <CheckCircle2 className="h-3.5 w-3.5" />}
            Post to MIRO
          </button>
        )}
        <button
          type="button"
          onClick={() => setAuditOpen(true)}
          className="inline-flex items-center gap-1.5 rounded-lg border border-neutral-200 bg-white px-3 py-1.5 text-xs font-medium text-neutral-600 hover:bg-neutral-50 transition-colors"
        >
          <ClipboardList className="h-3.5 w-3.5" />
          Audit Log
        </button>
      </Topbar>

      <div className="space-y-5 p-6">

        {/* Back */}
        <button
          type="button"
          onClick={() => navigate(-1)}
          className="inline-flex items-center gap-1.5 text-sm text-neutral-500 hover:text-neutral-800 transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          Back
        </button>

        {/* 3-column summary strip */}
        <SummaryStrip doc={doc} />

        {/* Main layout */}
        <div className="grid gap-5 lg:grid-cols-3">

          {/* Left: collapsible sections */}
          <div className="lg:col-span-2 space-y-4">

            {/* File info */}
            <Collapsible title="File Information">
              <div className="space-y-0">
                <Row label="File name"    value={doc.file?.original_name ?? '—'} />
                <Row label="Document type" value={doc.type ?? '—'} />
                <Row label="T-Code"       value={<TCodeChip tcode={doc.tcode} />} />
                <Row label="File size"    value={doc.file?.size_bytes != null ? `${(doc.file.size_bytes / 1024).toFixed(1)} KB` : '—'} />
                <Row label="MIME type"    value={doc.file?.mime_type ?? '—'} />
                <Row label="Uploaded at"  value={formatDateTime(doc.uploaded_at)} />
                <Row label="Uploaded by"  value={doc.uploaded_by ?? '—'} />
              </div>
            </Collapsible>

            {/* Extracted data */}
            {extracted && (
              <Collapsible title="Extracted Data">
                <div className="space-y-0">
                  <Row label="Invoice #"      value={extracted.invoice_no ?? '—'} />
                  <Row label="Invoice date"   value={extracted.invoice_date ?? '—'} />
                  <Row label="PO number"      value={extracted.po_number ?? '—'} />
                  <Row label="Vendor ID"      value={extracted.vendor_id ?? '—'} />
                  <Row label="Vendor name"    value={extracted.vendor_name ?? '—'} />
                  <Row label="Vendor GSTIN"   value={extracted.vendor_gstin ?? '—'} />
                  <Row label="Currency"       value={extracted.currency ?? '—'} />
                  <Row label="Gross amount"   value={toINR(Number(extracted.gross_amount) || 0)} />
                  <Row label="Tax amount"     value={toINR(Number(extracted.tax_amount) || 0)} />
                  <Row label="Net amount"     value={toINR(Number(extracted.net_amount) || 0)} />
                  <Row label="Payment terms"  value={extracted.payment_terms ?? '—'} />
                  <Row label="Confidence"     value={
                    <span className={cn(
                      'rounded-full px-2 py-0.5 text-xs font-semibold',
                      extracted.confidence_score >= 0.75 ? 'bg-green-100 text-green-700'
                      : extracted.confidence_score >= 0.5 ? 'bg-amber-100 text-amber-700'
                      : 'bg-red-100 text-red-700',
                    )}>
                      {Math.round(extracted.confidence_score * 100)}%
                    </span>
                  } />
                </div>

                {/* Line items mini-table */}
                {extracted.line_items && extracted.line_items.length > 0 && (
                  <div className="mt-4">
                    <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-neutral-400">
                      Line Items ({extracted.line_items.length})
                    </p>
                    <div className="overflow-x-auto rounded-lg border border-neutral-100">
                      <table className="w-full text-xs">
                        <thead className="bg-neutral-50">
                          <tr className="border-b border-neutral-100">
                            {['#', 'Material', 'Description', 'Qty', 'UOM', 'Rate', 'Amount'].map((h) => (
                              <th key={h} className="px-3 py-2 text-left font-semibold uppercase tracking-wider text-neutral-400">{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {extracted.line_items.map((li, i) => (
                            <tr key={i} className="border-b border-neutral-50 last:border-0 hover:bg-neutral-50">
                              <td className="px-3 py-2 font-mono text-neutral-500">{li.line_number}</td>
                              <td className="px-3 py-2 font-mono text-neutral-600">{li.material_code}</td>
                              <td className="px-3 py-2 text-neutral-700 max-w-[200px] truncate">{li.description}</td>
                              <td className="px-3 py-2 tabular-nums">{li.quantity}</td>
                              <td className="px-3 py-2">{li.uom}</td>
                              <td className="px-3 py-2 tabular-nums">{li.unit_rate}</td>
                              <td className="px-3 py-2 tabular-nums font-medium">{li.amount}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </Collapsible>
            )}

            {/* SAP Validation */}
            {validation && (
              <Collapsible title="SAP Validation">
                <div className="space-y-0 mb-4">
                  <Row label="Valid"            value={
                    <Badge variant={validation.is_valid ? 'success' : 'error'} dot>
                      {validation.is_valid ? 'Yes' : 'No'}
                    </Badge>
                  } />
                  <Row label="Overall"          value={`${Math.round(validation.overall_confidence * 100)}%`} />
                  <Row label="Header"           value={`${Math.round(validation.header_confidence * 100)}%`} />
                  <Row label="Line items"       value={`${Math.round(validation.line_item_confidence * 100)}%`} />
                  <Row label="GR coverage"      value={`${Math.round(validation.gr_confidence * 100)}%`} />
                  <Row label="Recommendation"   value={validation.recommendation ?? '—'} />
                </div>

                {validation.mismatches.length > 0 && (
                  <div>
                    <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-neutral-400">
                      Mismatches ({validation.mismatches.length})
                    </p>
                    <div className="divide-y divide-neutral-100 rounded-lg border border-neutral-100 overflow-hidden">
                      {validation.mismatches.map((m, i) => (
                        <div key={i} className={cn(
                          'flex items-start gap-3 px-3 py-2.5 text-xs',
                          m.severity === 'error' ? 'bg-red-50/50' : 'bg-amber-50/50',
                        )}>
                          <span className={cn(
                            'shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-semibold uppercase',
                            m.severity === 'error' ? 'bg-red-100 text-red-600' : 'bg-amber-100 text-amber-600',
                          )}>{m.severity}</span>
                          <div className="flex-1">
                            <span className="font-medium text-neutral-800">{m.field}</span>
                            <span className="ml-2 text-neutral-400">
                              Invoice: {m.extracted_value} · SAP: {m.sap_value}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </Collapsible>
            )}

            {/* MIRO result */}
            {miro && (
              <div className={cn(
                'rounded-xl border p-5',
                miro.status === 'success' ? 'border-green-200 bg-green-50' : 'border-red-200 bg-red-50',
              )}>
                <div className="flex items-center gap-3 mb-4">
                  <div className={cn(
                    'flex h-9 w-9 items-center justify-center rounded-full',
                    miro.status === 'success' ? 'bg-green-100' : 'bg-red-100',
                  )}>
                    {miro.status === 'success'
                      ? <CheckCircle2 className="h-5 w-5 text-green-600" />
                      : <AlertCircle className="h-5 w-5 text-red-600" />}
                  </div>
                  <div>
                    <p className={cn('text-sm font-semibold', miro.status === 'success' ? 'text-green-900' : 'text-red-900')}>
                      {miro.status === 'success' ? 'Posted to SAP MIRO' : 'MIRO Posting Failed'}
                    </p>
                    <p className={cn('text-xs', miro.status === 'success' ? 'text-green-600' : 'text-red-500')}>
                      {formatDateTime(miro.posted_at)}
                    </p>
                  </div>
                  {miro.miro_number && (
                    <div className="ml-auto text-right">
                      <p className="text-[10px] font-semibold uppercase tracking-widest text-green-500">MIRO Number</p>
                      <p className="font-mono text-lg font-bold tracking-wide text-green-900">{miro.miro_number}</p>
                    </div>
                  )}
                </div>
                <Badge variant={miro.status === 'success' ? 'success' : 'error'} dot className="text-xs">
                  {miro.status === 'success' ? 'Success' : 'Failed'}
                </Badge>
                {miro.sap_response?.MESSAGE && (
                  <p className="mt-2 text-xs text-red-700 break-words">
                    {Array.isArray(miro.sap_response.MESSAGE)
                      ? miro.sap_response.MESSAGE.map((m: { MSG?: string }) => m.MSG).join(' | ')
                      : String(miro.sap_response.MESSAGE)}
                  </p>
                )}
              </div>
            )}

            {/* Error log */}
            {doc.error_log && doc.error_log.length > 0 && (
              <Collapsible title={`Error Log (${doc.error_log.length})`} defaultOpen={status === DocumentStatus.FAILED}>
                <div className="divide-y divide-neutral-100 rounded-lg border border-neutral-100 overflow-hidden">
                  {doc.error_log.map((e, i) => (
                    <div key={i} className="bg-red-50/40 px-3 py-2.5 text-xs">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-semibold text-red-700">{e.stage}</span>
                        <span className="font-mono text-[10px] text-neutral-400">{formatDateTime(e.timestamp)}</span>
                      </div>
                      <p className="mt-0.5 text-neutral-700">{e.message}</p>
                      {e.detail && <p className="mt-0.5 font-mono text-[10px] text-neutral-400">{e.detail}</p>}
                    </div>
                  ))}
                </div>
              </Collapsible>
            )}
          </div>

          {/* Right: timeline */}
          <div className="space-y-4">
            <div className="rounded-xl border border-neutral-200 bg-white p-5">
              <div className="mb-4 flex items-center gap-2">
                <FileText className="h-4 w-4 text-neutral-400" />
                <h3 className="text-sm font-semibold text-neutral-800">Processing Timeline</h3>
              </div>
              <Timeline doc={doc} />
            </div>

            {/* Retry count */}
            {doc.retry_count > 0 && (
              <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
                <p className="text-xs font-semibold text-amber-700">
                  {doc.retry_count} retry{doc.retry_count > 1 ? 's' : ''} attempted
                </p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Audit log drawer */}
      <AuditDrawer
        docId={id ?? ''}
        open={auditOpen}
        onClose={() => setAuditOpen(false)}
      />
    </>
  );
}
