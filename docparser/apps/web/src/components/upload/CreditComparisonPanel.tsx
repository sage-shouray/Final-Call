import { AlertTriangle, CheckCircle2, FileWarning, Receipt } from 'lucide-react';
import toast from 'react-hot-toast';
import { CreditCase, type CreditComparisonResult, type CreditLineDiff } from '@/types';
import { cn } from '@/lib/cn';

// ─── Loading state ─────────────────────────────────────────────────────────────

export function CreditCompareLoading() {
  return (
    <div className="flex flex-col items-center gap-3 py-12 text-center">
      <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-indigo-100 dark:bg-indigo-900/40">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-indigo-500 border-t-transparent" />
      </div>
      <p className="text-sm font-semibold text-neutral-800 dark:text-neutral-200">Checking MIRO status…</p>
      <p className="text-xs text-neutral-400 dark:text-neutral-500">
        Fetching the originally posted line items for this PO and comparing against the extracted invoice
      </p>
    </div>
  );
}

// ─── Case badge ────────────────────────────────────────────────────────────────

function CaseBadge({ creditCase }: { creditCase: CreditCase | null }) {
  if (creditCase === CreditCase.CREDIT_MEMO) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-red-100 px-3 py-1 text-xs font-semibold text-red-700 dark:bg-red-950 dark:text-red-400">
        <FileWarning className="h-3.5 w-3.5" /> Credit Memo
      </span>
    );
  }
  if (creditCase === CreditCase.SUBSEQUENT_CREDIT) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-700 dark:bg-amber-950 dark:text-amber-400">
        <AlertTriangle className="h-3.5 w-3.5" /> Subsequent Credit
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-neutral-100 px-3 py-1 text-xs font-semibold text-neutral-600 dark:bg-neutral-800 dark:text-neutral-400">
      <CheckCircle2 className="h-3.5 w-3.5" /> No Difference
    </span>
  );
}

// ─── Line diff row ─────────────────────────────────────────────────────────────

function fmtNum(n: number): string {
  return n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function DiffCell({ extracted, original, changed }: { extracted: number; original: number; changed: boolean }) {
  return (
    <td className="px-4 py-3 text-right font-mono text-xs tabular-nums">
      <span className={cn('text-neutral-700 dark:text-neutral-300', changed && 'font-semibold text-red-600 dark:text-red-400')}>
        {fmtNum(extracted)}
      </span>
      {changed && (
        <span className="ml-1.5 text-neutral-400 dark:text-neutral-500">
          (was {fmtNum(original)})
        </span>
      )}
    </td>
  );
}

function LineDiffRow({ diff }: { diff: CreditLineDiff }) {
  if (!diff.matched) {
    return (
      <tr className="border-b border-neutral-100 bg-amber-50/50 dark:border-neutral-800 dark:bg-amber-950/20">
        <td className="px-4 py-3 font-mono text-xs text-neutral-600 dark:text-neutral-400">{diff.line_number}</td>
        <td className="px-4 py-3 text-xs text-neutral-600 dark:text-neutral-400">{diff.material_code || '—'}</td>
        <td colSpan={2} className="px-4 py-3 text-xs text-amber-700 dark:text-amber-400">
          No matching MIRO line found for this item
        </td>
      </tr>
    );
  }

  const anyChange = diff.quantity_changed || diff.price_changed;

  return (
    <tr className={cn('border-b border-neutral-100 dark:border-neutral-800', anyChange && 'bg-red-50/40 dark:bg-red-950/20')}>
      <td className="px-4 py-3 font-mono text-xs text-neutral-600 dark:text-neutral-400">{diff.line_number}</td>
      <td className="px-4 py-3 text-xs text-neutral-700 dark:text-neutral-300">{diff.material_code || '—'}</td>
      <DiffCell extracted={diff.extracted_quantity} original={diff.miro_quantity} changed={diff.quantity_changed} />
      <DiffCell extracted={diff.extracted_price}    original={diff.miro_price}    changed={diff.price_changed} />
      <td className="px-4 py-3 text-right font-mono text-xs tabular-nums text-neutral-700 dark:text-neutral-300">
        {fmtNum(diff.extracted_amount)}
      </td>
      <td className="px-4 py-3 text-right font-mono text-xs tabular-nums text-neutral-700 dark:text-neutral-300">
        {fmtNum(diff.extracted_tax)}
      </td>
    </tr>
  );
}

// ─── Main panel ────────────────────────────────────────────────────────────────

interface CreditComparisonPanelProps {
  comparison: CreditComparisonResult;
  onPost:     () => void;
  isPosting:  boolean;
}

export function CreditComparisonPanel({ comparison, onPost, isPosting }: CreditComparisonPanelProps) {
  const { miro_posted, miro_message, credit_case, reason, line_diffs, po_number } = comparison;

  if (!miro_posted) {
    return (
      <div className="rounded-xl border border-amber-200 bg-amber-50 p-6 text-center dark:border-amber-900 dark:bg-amber-950/30">
        <FileWarning className="mx-auto h-8 w-8 text-amber-500 dark:text-amber-400" />
        <p className="mt-3 text-sm font-semibold text-amber-800 dark:text-amber-300">No MIRO Posted Against This PO</p>
        <p className="mt-1 text-xs text-amber-600 dark:text-amber-400">
          {miro_message || `PO ${po_number} has no invoice posted yet — nothing to compare this credit note against.`}
        </p>
      </div>
    );
  }

  const canPost = credit_case !== null;

  return (
    <div className="space-y-5">
      {/* Decision banner */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-neutral-200 bg-white p-5 dark:border-neutral-700 dark:bg-neutral-900">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-indigo-100 dark:bg-indigo-900/40">
            <Receipt className="h-5 w-5 text-indigo-600 dark:text-indigo-400" />
          </div>
          <div>
            <p className="text-sm font-semibold text-neutral-800 dark:text-neutral-200">
              PO {po_number} — MIRO already posted
            </p>
            <p className="mt-0.5 text-xs text-neutral-500 dark:text-neutral-400">{reason}</p>
          </div>
        </div>
        <CaseBadge creditCase={credit_case as CreditCase | null} />
      </div>

      {/* Line-by-line diff table */}
      <div className="rounded-xl border border-neutral-200 bg-white overflow-hidden dark:border-neutral-700 dark:bg-neutral-900">
        <div className="border-b border-neutral-100 px-5 py-3.5 dark:border-neutral-700">
          <h3 className="text-sm font-semibold text-neutral-800 dark:text-neutral-200">Line Item Comparison</h3>
          <p className="mt-0.5 text-xs text-neutral-400 dark:text-neutral-500">
            Extracted invoice values vs. what was originally posted to MIRO — changed values shown in red
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-neutral-100 bg-neutral-50 text-xs dark:border-neutral-700 dark:bg-neutral-800/80">
                <th className="px-4 py-2.5 text-left font-semibold uppercase tracking-wider text-neutral-400 dark:text-neutral-500">Line</th>
                <th className="px-4 py-2.5 text-left font-semibold uppercase tracking-wider text-neutral-400 dark:text-neutral-500">Material</th>
                <th className="px-4 py-2.5 text-right font-semibold uppercase tracking-wider text-neutral-400 dark:text-neutral-500">Quantity</th>
                <th className="px-4 py-2.5 text-right font-semibold uppercase tracking-wider text-neutral-400 dark:text-neutral-500">Unit Price</th>
                <th className="px-4 py-2.5 text-right font-semibold uppercase tracking-wider text-neutral-400 dark:text-neutral-500">Amount</th>
                <th className="px-4 py-2.5 text-right font-semibold uppercase tracking-wider text-neutral-400 dark:text-neutral-500">Tax</th>
              </tr>
            </thead>
            <tbody>
              {line_diffs.map((diff, i) => <LineDiffRow key={i} diff={diff} />)}
              {line_diffs.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-center text-sm text-neutral-400 dark:text-neutral-500">
                    No line items found in the extracted invoice.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Action bar */}
      <div className="sticky bottom-0 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-neutral-200 bg-white px-5 py-3.5 shadow-lg dark:border-neutral-700 dark:bg-neutral-900">
        <div>
          {canPost ? (
            <p className="text-sm font-medium text-neutral-700 dark:text-neutral-300">
              System determined this is a <span className="font-semibold">{credit_case === CreditCase.CREDIT_MEMO ? 'Credit Memo' : 'Subsequent Credit'}</span> case
            </p>
          ) : (
            <p className="text-sm text-neutral-500 dark:text-neutral-400">No postable difference found — nothing to post.</p>
          )}
        </div>
        <button
          type="button"
          onClick={() => {
            if (!canPost) return;
            toast('Posting is not wired up yet — coming once the SAP posting API is confirmed.', { icon: '🚧' });
            onPost();
          }}
          disabled={!canPost || isPosting}
          className={cn(
            'inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold text-white shadow-soft-sm transition-colors',
            'disabled:opacity-50 disabled:pointer-events-none',
            !canPost
              ? 'bg-neutral-400 dark:bg-neutral-600'
              : credit_case === CreditCase.CREDIT_MEMO
                ? 'bg-red-600 hover:bg-red-700 active:bg-red-800'
                : 'bg-amber-500 hover:bg-amber-600 active:bg-amber-700',
          )}
        >
          {isPosting ? <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" /> : null}
          {!canPost
            ? 'Nothing to Post'
            : credit_case === CreditCase.CREDIT_MEMO ? 'Post as Credit Memo' : 'Post as Subsequent Credit'}
        </button>
      </div>
    </div>
  );
}
