import { useState } from 'react';
import { CheckCircle2, Copy, ChevronDown, ChevronUp, ArrowLeft, RefreshCw } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import type { MIROPosting, ExtractedData } from '@/types';
import { toINR } from '@/lib/currency';
import { cn } from '@/lib/cn';

// ─── Posting loading state ─────────────────────────────────────────────────────

export function PostingLoading({ lineItemCount }: { lineItemCount: number }) {
  return (
    <div className="flex flex-col items-center gap-6 py-14">
      <div className="relative flex h-16 w-16 items-center justify-center rounded-full bg-green-100">
        <div className="absolute inset-0 animate-ping rounded-full bg-green-200 opacity-50" />
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-green-200 border-t-green-600" />
      </div>
      <div className="text-center">
        <p className="text-base font-semibold text-neutral-800">
          Posting {lineItemCount} line item{lineItemCount !== 1 ? 's' : ''} to MIRO
        </p>
        <p className="mt-1 text-sm text-neutral-400">This usually takes a few seconds…</p>
      </div>
    </div>
  );
}

// ─── Success state ─────────────────────────────────────────────────────────────

interface SuccessPanelProps {
  miro:      MIROPosting;
  extracted: ExtractedData | null;
  onReset:   () => void;
}

export function SuccessPanel({ miro, extracted, onReset }: SuccessPanelProps) {
  const navigate          = useNavigate();
  const [showPayload, setShowPayload] = useState(false);
  const [copied, setCopied]           = useState(false);

  function copyMiro() {
    navigator.clipboard.writeText(miro.miro_number).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  const payload = JSON.stringify(miro.payload_sent, null, 2);

  return (
    <div className="flex flex-col items-center gap-6 py-4">
      {/* Green check */}
      <div className="flex h-16 w-16 items-center justify-center rounded-full bg-green-100">
        <CheckCircle2 className="h-9 w-9 text-green-600" strokeWidth={2} />
      </div>

      {/* Heading */}
      <div className="text-center">
        <h2 className="text-xl font-bold text-neutral-900">Document posted successfully</h2>
        <p className="mt-1 text-sm text-neutral-400">SAP MIRO entry has been created</p>
      </div>

      {/* MIRO number */}
      <div className="w-full max-w-sm rounded-xl border border-green-200 bg-green-50 px-6 py-5 text-center">
        <p className="text-xs font-semibold uppercase tracking-widest text-green-600">
          MIRO Transaction Number
        </p>
        <p className="mt-2 font-mono text-3xl font-bold tracking-wider text-neutral-900">
          {miro.miro_number}
        </p>
      </div>

      {/* Document summary */}
      {extracted && (
        <div className="flex flex-wrap items-center justify-center gap-2 text-sm text-neutral-500">
          <span className="font-mono text-xs">{extracted.invoice_no}</span>
          <span className="text-neutral-200">·</span>
          <span>{extracted.vendor_name}</span>
          <span className="text-neutral-200">·</span>
          <span className="font-medium text-neutral-700">{toINR(Number(extracted.gross_amount) || 0)}</span>
        </div>
      )}

      {/* Collapsible payload */}
      <div className="w-full max-w-2xl rounded-xl border border-neutral-200">
        <button
          type="button"
          onClick={() => setShowPayload((v) => !v)}
          className="flex w-full items-center justify-between px-4 py-3 text-sm font-medium text-neutral-600 hover:bg-neutral-50 transition-colors rounded-xl"
        >
          View payload sent
          {showPayload ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </button>
        {showPayload && (
          <div className="border-t border-neutral-100 px-4 pb-4">
            <pre className="max-h-56 overflow-y-auto rounded-lg bg-neutral-900 p-4 text-xs text-green-300 font-mono scrollbar-thin">
              {payload}
            </pre>
          </div>
        )}
      </div>

      {/* Action buttons */}
      <div className="flex flex-wrap justify-center gap-3">
        <button
          type="button"
          onClick={() => navigate('/dashboard')}
          className="inline-flex items-center gap-2 rounded-lg border border-neutral-200 bg-white px-4 py-2 text-sm font-medium text-neutral-700 shadow-soft-sm hover:bg-neutral-50 transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to dashboard
        </button>

        <button
          type="button"
          onClick={copyMiro}
          className={cn(
            'inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors',
            copied
              ? 'bg-green-100 text-green-700'
              : 'border border-neutral-200 bg-white text-neutral-700 shadow-soft-sm hover:bg-neutral-50',
          )}
        >
          <Copy className="h-4 w-4" />
          {copied ? 'Copied!' : 'Copy MIRO number'}
        </button>

        <button
          type="button"
          onClick={onReset}
          className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-soft-sm hover:bg-indigo-700 transition-colors"
        >
          <RefreshCw className="h-4 w-4" />
          Process another
        </button>
      </div>
    </div>
  );
}
