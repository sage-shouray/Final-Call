import { AlertTriangle } from 'lucide-react';
import { Modal } from '@/components/ui/Modal';

interface PostingFailureModalProps {
  open:   boolean;
  onClose: () => void;
  /** e.g. "MIRO Posting Failed", "Goods Receipt Failed" */
  title:   string;
  /** The reason, already joined into plain text — see extractSapMessage(). */
  reason:  string;
  documentId?: string;
}

/**
 * The blocking failure dialog for a posting attempt.
 *
 * Before this, a failed MIRO/GRN/FB60/F-26 posting surfaced as a toast in the
 * corner — easy to miss, and gone in a few seconds with no record on screen.
 * A posting failure means SAP refused the document; the person reviewing it
 * needs to actually read why, not glimpse it. So this blocks the screen and
 * stays up until they dismiss it.
 */
export function PostingFailureModal({ open, onClose, title, reason, documentId }: PostingFailureModalProps) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      size="sm"
      closeOnBackdrop={false}
      footer={
        <button
          type="button"
          onClick={onClose}
          autoFocus
          className="rounded-lg bg-red-600 px-5 py-2 text-sm font-semibold text-white hover:bg-red-700 transition-colors focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2"
        >
          Okay
        </button>
      }
    >
      <div className="flex flex-col items-center text-center gap-3 py-1">
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-red-100 dark:bg-red-900/40">
          <AlertTriangle className="h-6 w-6 text-red-600 dark:text-red-400" />
        </div>
        <h3 className="text-base font-semibold text-neutral-900 dark:text-neutral-100">{title}</h3>
        <p className="text-sm text-neutral-600 dark:text-neutral-300 whitespace-pre-wrap break-words">
          {reason}
        </p>
        {documentId && (
          <p className="text-xs text-neutral-400 dark:text-neutral-500 font-mono">{documentId}</p>
        )}
      </div>
    </Modal>
  );
}

/** SAP's own error shape: {"MESSAGE": [{"MSG": "..."}]} or a plain string. Both
 * the detail page and this dialog need the same join, so it lives once here. */
export function extractSapMessage(sapResponse: unknown, fallback: string): string {
  const msg = (sapResponse as { MESSAGE?: unknown } | null | undefined)?.MESSAGE;
  if (Array.isArray(msg)) {
    const joined = (msg as { MSG?: string }[]).map((m) => m.MSG ?? '').filter(Boolean).join('\n');
    return joined || fallback;
  }
  if (typeof msg === 'string' && msg.trim()) return msg;
  return fallback;
}
