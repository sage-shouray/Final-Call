import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  Mail, CheckCircle2, Clock, AlertTriangle, XCircle, Loader2,
  Inbox, ShieldCheck, ShieldAlert,
} from 'lucide-react';
import api from '@/lib/api';
import { cn } from '@/lib/cn';
import { Topbar } from '@/components/layout/Topbar';
import { formatDateTime } from '@/lib/dates';
import { toINR } from '@/lib/currency';

/**
 * What the mailbox brought in, and what became of it.
 *
 * The history page answers "what have we processed". This answers the question
 * people actually ask — a vendor says they emailed an invoice, did it arrive and
 * did it land — so every row carries the mail it came from, what OCR read, where
 * SAP sent it, and the resulting document number.
 */

interface MailDocument {
  document_id: string;
  status: string;
  received_at: string;
  sender: string;
  subject: string;
  mailbox: string;
  sender_trusted: boolean | null;
  attachment: string;
  invoice_no: string;
  vendor_name: string;
  gross_amount: string;
  confidence: number | null;
  line_items: number;
  po_number: string;
  route: string;
  invoice_subtype: string | null;
  tcode: string;
  reason: string;
  outcome: 'posted' | 'awaiting' | 'held' | 'failed' | 'processing';
  action: string;
  decision: string;
  failed_gates: string[];
  grn_number: string;
  miro_number: string;
}

const OUTCOME = {
  posted:     { icon: CheckCircle2,  cls: 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300' },
  awaiting:   { icon: Clock,         cls: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300' },
  held:       { icon: AlertTriangle, cls: 'bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300' },
  failed:     { icon: XCircle,       cls: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300' },
  processing: { icon: Loader2,       cls: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300' },
} as const;

const FILTERS = [
  { key: '',          label: 'All' },
  { key: 'posted',    label: 'Posted' },
  { key: 'awaiting',  label: 'Awaiting approval' },
  { key: 'held',      label: 'Needs attention' },
  { key: 'failed',    label: 'Failed' },
] as const;

function OutcomeBadge({ doc }: { doc: MailDocument }) {
  const style = OUTCOME[doc.outcome] ?? OUTCOME.processing;
  const Icon = style.icon;
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold', style.cls)}>
      <Icon className={cn('h-3 w-3', doc.outcome === 'processing' && 'animate-spin')} />
      {doc.action}
    </span>
  );
}

export default function MailInboxPage() {
  const [filter, setFilter] = useState<string>('');

  const { data, isLoading } = useQuery<{ documents: MailDocument[]; total: number }>({
    queryKey: ['mail-inbox', filter],
    queryFn: async () => {
      // Typed on the call so the response is not an `any` flowing outward.
      const { data } = await api.get<{ documents: MailDocument[]; total: number }>(
        '/documents/from-mail',
        { params: { limit: 100, ...(filter ? { outcome: filter } : {}) } },
      );
      return data;
    },
    // Documents arriving by mail change on their own, so the view refreshes
    // without anyone pressing anything.
    refetchInterval: 10_000,
  });

  const docs = data?.documents ?? [];

  return (
    <>
      <Topbar title="Mail Inbox" subtitle="Invoices received by email" />

      <div className="space-y-4 p-6">
        <div className="flex flex-wrap items-center gap-2">
          {FILTERS.map(f => (
            <button
              key={f.key}
              type="button"
              onClick={() => setFilter(f.key)}
              className={cn(
                'rounded-lg px-3 py-1.5 text-xs font-medium transition-colors',
                filter === f.key
                  ? 'bg-primary-600 text-white'
                  : 'bg-neutral-100 text-neutral-600 hover:bg-neutral-200 dark:bg-neutral-800 dark:text-neutral-300 dark:hover:bg-neutral-700',
              )}
            >
              {f.label}
            </button>
          ))}
          <span className="ml-auto text-xs text-neutral-400">
            {data?.total ?? 0} received by email
          </span>
        </div>

        {isLoading && (
          <p className="py-12 text-center text-sm text-neutral-400">Loading…</p>
        )}

        {!isLoading && docs.length === 0 && (
          <div className="rounded-xl border border-dashed border-neutral-300 py-16 text-center dark:border-neutral-700">
            <Inbox className="mx-auto mb-3 h-8 w-8 text-neutral-300 dark:text-neutral-600" />
            <p className="text-sm text-neutral-500 dark:text-neutral-400">
              Nothing has arrived by email yet.
            </p>
            <p className="mt-1 text-xs text-neutral-400">
              Configure a mailbox under Admin → company → Mailboxes.
            </p>
          </div>
        )}

        <div className="space-y-3">
          {docs.map(doc => (
            <Link
              key={doc.document_id}
              to={`/documents/${doc.document_id}`}
              className="block rounded-xl border border-neutral-200 bg-white p-4 transition-colors hover:border-primary-300 dark:border-neutral-800 dark:bg-neutral-900 dark:hover:border-primary-700"
            >
              {/* The mail it came from */}
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="flex items-center gap-2 text-sm font-semibold text-neutral-900 dark:text-white">
                    <Mail className="h-4 w-4 shrink-0 text-neutral-400" />
                    <span className="truncate">{doc.subject || '(no subject)'}</span>
                  </p>
                  <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-neutral-500 dark:text-neutral-400">
                    <span>from {doc.sender}</span>
                    {doc.sender_trusted === true && (
                      <span className="inline-flex items-center gap-0.5 text-green-600 dark:text-green-400">
                        <ShieldCheck className="h-3 w-3" /> allowlisted
                      </span>
                    )}
                    {doc.sender_trusted === false && (
                      <span className="inline-flex items-center gap-0.5 text-amber-600 dark:text-amber-400">
                        <ShieldAlert className="h-3 w-3" /> unrecognised sender
                      </span>
                    )}
                    <span>· {formatDateTime(doc.received_at)}</span>
                  </p>
                </div>
                <OutcomeBadge doc={doc} />
              </div>

              {/* What OCR read, and where SAP sent it */}
              <div className="mt-3 grid gap-3 border-t border-neutral-100 pt-3 text-xs dark:border-neutral-800 sm:grid-cols-4">
                <div>
                  <p className="mb-0.5 text-[10px] uppercase tracking-wider text-neutral-400">Extracted</p>
                  <p className="font-medium text-neutral-800 dark:text-neutral-200">{doc.invoice_no || '—'}</p>
                  <p className="text-neutral-500 dark:text-neutral-400">{doc.vendor_name || '—'}</p>
                  {doc.confidence != null && (
                    <p className="text-neutral-400">
                      {Math.round(doc.confidence * 100)}% · {doc.line_items} line{doc.line_items === 1 ? '' : 's'}
                    </p>
                  )}
                </div>
                <div>
                  <p className="mb-0.5 text-[10px] uppercase tracking-wider text-neutral-400">Amount</p>
                  <p className="font-medium tabular-nums text-neutral-800 dark:text-neutral-200">
                    {doc.gross_amount ? toINR(doc.gross_amount) : '—'}
                  </p>
                </div>
                <div>
                  <p className="mb-0.5 text-[10px] uppercase tracking-wider text-neutral-400">Routed</p>
                  <p className="font-mono text-neutral-800 dark:text-neutral-200">{doc.po_number || 'no PO'}</p>
                  <p className="text-neutral-500 dark:text-neutral-400">
                    {doc.tcode}{doc.invoice_subtype ? ` · ${doc.invoice_subtype}` : ''}
                  </p>
                </div>
                <div>
                  <p className="mb-0.5 text-[10px] uppercase tracking-wider text-neutral-400">SAP document</p>
                  {doc.miro_number
                    ? <p className="font-mono font-medium text-green-700 dark:text-green-400">{doc.miro_number}</p>
                    : <p className="text-neutral-400">—</p>}
                  {doc.grn_number && (
                    <p className="font-mono text-neutral-500 dark:text-neutral-400">GR {doc.grn_number}</p>
                  )}
                </div>
              </div>

              {/* Only shown when someone has to do something about it. */}
              {(doc.outcome === 'held' || doc.outcome === 'awaiting') && (doc.reason || doc.failed_gates.length > 0) && (
                <p className="mt-2 border-t border-neutral-100 pt-2 text-xs text-amber-700 dark:border-neutral-800 dark:text-amber-400">
                  {doc.reason || `Waiting on: ${doc.failed_gates.join(', ')}`}
                </p>
              )}
            </Link>
          ))}
        </div>
      </div>
    </>
  );
}
