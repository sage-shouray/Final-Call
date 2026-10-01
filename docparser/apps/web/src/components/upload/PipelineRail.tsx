import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  CheckCircle2, XCircle, Loader2, Circle, AlertTriangle,
  FileSearch, Route as RouteIcon, ScanText, ShieldCheck, Clock, Wrench,
} from 'lucide-react';
import api from '@/lib/api';
import { cn } from '@/lib/cn';
import type { DocumentPipeline, PipelineRoute, RoutingConfirmationLine } from '@/types';

/**
 * The fast track, made visible.
 *
 * Identity and SAP routing resolve in about a second while OCR is still running,
 * so the rail deliberately shows elapsed time per stage: the point is that the
 * destination of a document is known long before its contents are.
 */

const ROUTE_LABEL: Record<PipelineRoute, string> = {
  miro_direct:    'Invoice → MIRO',
  migo_then_miro: 'Goods receipt → then MIRO',
  fb60:           'Non-PO → FB60',
  hold:           'Needs attention',
};

const ROUTE_STYLE: Record<PipelineRoute, string> = {
  miro_direct:    'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300',
  migo_then_miro: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
  fb60:           'bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300',
  hold:           'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
};

const SUBTYPE_LABEL: Record<string, string> = {
  po:         'Material PO',
  service_po: 'Service PO',
  freight_po: 'Freight PO',
  non_po:     'Non-PO',
};

const ms = (v?: number) =>
  v == null ? null : v < 1000 ? `${Math.round(v)} ms` : `${(v / 1000).toFixed(1)} s`;

type StageState = 'done' | 'active' | 'failed' | 'pending';

function StageIcon({ state, Icon }: { state: StageState; Icon: typeof Circle }) {
  if (state === 'active') return <Loader2 className="h-4 w-4 shrink-0 animate-spin text-primary-500" />;
  if (state === 'failed') return <XCircle className="h-4 w-4 shrink-0 text-red-500" />;
  if (state === 'done')   return <Icon className="h-4 w-4 shrink-0 text-green-600 dark:text-green-400" />;
  return <Circle className="h-4 w-4 shrink-0 text-neutral-300 dark:text-neutral-600" />;
}

function Stage({
  state, Icon, label, timing, children,
}: {
  state: StageState;
  Icon: typeof Circle;
  label: string;
  timing?: string | null;
  children?: React.ReactNode;
}) {
  return (
    <div className="relative pl-7 pb-4 last:pb-0">
      <span className="absolute left-[7px] top-6 bottom-0 w-px bg-neutral-200 dark:bg-neutral-700" />
      <span className="absolute left-0 top-0.5"><StageIcon state={state} Icon={Icon} /></span>
      <div className="flex items-baseline justify-between gap-2">
        <p className={cn(
          'text-xs font-semibold',
          state === 'pending'
            ? 'text-neutral-400 dark:text-neutral-500'
            : 'text-neutral-800 dark:text-neutral-100',
        )}>
          {label}
        </p>
        {timing && (
          <span className="shrink-0 font-mono text-[10px] tabular-nums text-neutral-400 dark:text-neutral-500">
            {timing}
          </span>
        )}
      </div>
      {children && <div className="mt-1 space-y-1">{children}</div>}
    </div>
  );
}

function Chip({ children, tone = 'neutral' }: { children: React.ReactNode; tone?: 'neutral' | 'good' | 'bad' }) {
  return (
    <span className={cn(
      'inline-block rounded px-1.5 py-0.5 font-mono text-[10px]',
      tone === 'good' && 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300',
      tone === 'bad' && 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
      tone === 'neutral' && 'bg-neutral-100 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300',
    )}>
      {children}
    </span>
  );
}

function ConfirmationLines({ lines }: { lines: RoutingConfirmationLine[] }) {
  return (
    <>
      {lines.map((l) => (
        <p key={l.po_item} className="text-[11px] text-neutral-500 dark:text-neutral-400">
          Line {l.po_item}:{' '}
          {l.confirmed
            ? <Chip tone="good">{l.kind} {l.documents.join(', ')}</Chip>
            : <Chip tone="bad">no {l.kind}</Chip>}
        </p>
      ))}
    </>
  );
}

/**
 * Correcting a wrong PO number in place.
 *
 * The commonest hold is a PO number the scan misread or that was mistyped on
 * the invoice. Re-routing is read-only against SAP, so it is safe to retry;
 * without this the only remedy was to fix the PDF and upload it again.
 */
function FixPoNumber({ documentId, suggested }: { documentId: string; suggested?: string | undefined }) {
  const [value, setValue] = useState(suggested ?? '');
  const qc = useQueryClient();

  const reroute = useMutation({
    mutationFn: () => api.post(`/documents/${documentId}/reroute`, { po_number: value.trim() }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['document', documentId] }),
  });

  const error = reroute.error as { response?: { data?: { error?: { message?: string } } } } | null;

  return (
    <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 p-2.5 dark:border-amber-900 dark:bg-amber-950/30">
      <p className="mb-1.5 flex items-center gap-1 text-[11px] font-medium text-amber-800 dark:text-amber-300">
        <Wrench className="h-3 w-3" /> Correct the PO number
      </p>
      <div className="flex gap-1.5">
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="4500022773"
          className="min-w-0 flex-1 rounded border border-neutral-300 bg-white px-2 py-1 font-mono text-[11px] dark:border-neutral-600 dark:bg-neutral-800 dark:text-neutral-100"
        />
        <button
          type="button"
          onClick={() => reroute.mutate()}
          disabled={reroute.isPending || value.trim().length < 4}
          className="shrink-0 rounded bg-amber-600 px-2 py-1 text-[11px] font-medium text-white hover:bg-amber-700 disabled:opacity-50"
        >
          {reroute.isPending ? 'Checking…' : 'Re-check'}
        </button>
      </div>
      {error && (
        <p className="mt-1 text-[10px] text-red-600 dark:text-red-400">
          {error.response?.data?.error?.message ?? 'Could not re-route.'}
        </p>
      )}
    </div>
  );
}

export function PipelineRail({
  pipeline,
  extracted,
  failed = false,
  documentId,
}: {
  pipeline: DocumentPipeline | null | undefined;
  extracted: boolean;
  failed?: boolean;
  /** When given, a held document offers an inline PO-number correction. */
  documentId?: string;
}) {
  if (!pipeline) return null;

  const { identity, routing, autopost } = pipeline;
  const done = Boolean(pipeline.completed_at);

  // Extraction is the long pole: active until it yields data or fails.
  const ocrState: StageState = extracted ? 'done' : failed ? 'failed' : 'active';
  const checksState: StageState =
    autopost ? 'done' : pipeline.skipped_reason ? 'failed' : extracted ? 'active' : 'pending';

  const route = routing?.route;
  const subtype = routing?.invoice_subtype;

  return (
    <div className="rounded-xl border border-neutral-200 bg-white p-5 dark:border-neutral-700 dark:bg-neutral-900">
      <div className="mb-4 flex items-center gap-2">
        <h3 className="text-sm font-semibold text-neutral-800 dark:text-neutral-100">Processing pipeline</h3>
        {done && (
          <span className="flex items-center gap-1 text-[10px] text-neutral-400 dark:text-neutral-500">
            <Clock className="h-3 w-3" /> complete
          </span>
        )}
      </div>

      <Stage state="done" Icon={CheckCircle2} label="Uploaded" />

      <Stage
        state={identity ? 'done' : 'active'}
        Icon={FileSearch}
        label="Identified"
        timing={ms(identity?.elapsed_ms)}
      >
        {identity && (
          <>
            {identity.po_number
              ? (
                <p className="text-[11px] text-neutral-500 dark:text-neutral-400">
                  PO <Chip>{identity.po_number}</Chip>
                </p>
              )
              : (
                <p className="text-[11px] text-neutral-500 dark:text-neutral-400">
                  No PO number found on the document
                </p>
              )}
            {identity.invoice_no && (
              <p className="text-[11px] text-neutral-500 dark:text-neutral-400">
                Invoice <Chip>{identity.invoice_no}</Chip>
              </p>
            )}
            {!identity.has_text_layer && (
              <p className="flex items-start gap-1 text-[11px] text-amber-600 dark:text-amber-400">
                <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
                Scanned PDF, no text layer &mdash; routing waits for extraction.
              </p>
            )}
          </>
        )}
      </Stage>

      <Stage
        state={routing ? (routing.resolved ? 'done' : 'failed') : 'active'}
        Icon={RouteIcon}
        label="Routed by SAP"
        timing={ms(routing?.elapsed_ms)}
      >
        {routing && (
          <>
            {route && (
              <div className="flex flex-wrap items-center gap-1.5">
                <span className={cn('rounded-full px-2 py-0.5 text-[10px] font-semibold', ROUTE_STYLE[route])}>
                  {ROUTE_LABEL[route]}
                </span>
                {subtype && SUBTYPE_LABEL[subtype] && (
                  <span className="rounded-full bg-neutral-100 px-2 py-0.5 text-[10px] font-medium text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300">
                    {SUBTYPE_LABEL[subtype]}
                  </span>
                )}
              </div>
            )}
            <p className="text-[11px] text-neutral-500 dark:text-neutral-400">{routing.reason}</p>
            {routing.confirmation?.lines?.length
              ? <ConfirmationLines lines={routing.confirmation.lines} />
              : null}
            {routing.retryable && (
              <p className="text-[11px] text-amber-600 dark:text-amber-400">
                Transient &mdash; this resolves once SAP is reachable.
              </p>
            )}
            {/* Only when SAP answered and rejected the number: a transient
                outage needs a retry, not a different PO. */}
            {documentId && route === 'hold' && !routing.retryable && (
              <FixPoNumber documentId={documentId} suggested={routing.po_number || identity?.po_number} />
            )}
          </>
        )}
      </Stage>

      <Stage
        state={ocrState}
        Icon={ScanText}
        label={ocrState === 'active' ? 'Extracting fields…' : 'Fields extracted'}
      >
        {ocrState === 'active' && (
          <p className="text-[11px] text-neutral-500 dark:text-neutral-400">
            Reading the full invoice &mdash; routing above is already settled.
          </p>
        )}
        {ocrState === 'failed' && (
          <p className="text-[11px] text-red-600 dark:text-red-400">
            Extraction failed &mdash; see the error log below.
          </p>
        )}
      </Stage>

      <Stage state={checksState} Icon={ShieldCheck} label="Checks">
        {pipeline.skipped_reason && (
          <p className="text-[11px] text-neutral-500 dark:text-neutral-400">{pipeline.skipped_reason}</p>
        )}
        {autopost && (
          <>
            <p className={cn(
              'text-[11px] font-medium',
              autopost.auto_post
                ? 'text-green-700 dark:text-green-400'
                : 'text-amber-700 dark:text-amber-400',
            )}>
              {autopost.summary}
            </p>
            <div className="mt-1 space-y-0.5">
              {autopost.gates.map((g) => (
                <p key={g.gate} className="flex items-start gap-1.5 text-[11px]">
                  {g.passed
                    ? <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0 text-green-600 dark:text-green-400" />
                    : <XCircle className="mt-0.5 h-3 w-3 shrink-0 text-red-500" />}
                  <span className={g.passed
                    ? 'text-neutral-500 dark:text-neutral-400'
                    : 'text-red-600 dark:text-red-400'}>
                    {g.detail}
                  </span>
                </p>
              ))}
            </div>
          </>
        )}
      </Stage>
    </div>
  );
}
