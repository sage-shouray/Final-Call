import { useEffect, useRef, useCallback, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { RotateCcw } from 'lucide-react';
import toast from 'react-hot-toast';
import api from '@/lib/api';
import { useDocumentStore }    from '@/store/documentStore';
import { useDocumentWebSocket } from '@/hooks/useDocumentWebSocket';
import { Topbar }          from '@/components/layout/Topbar';
import { StepIndicator }   from '@/components/upload/StepIndicator';
import { DocTypePicker }   from '@/components/upload/DocTypePicker';
import { FileDropzone }    from '@/components/upload/FileDropzone';
import { Skeleton }        from '@/components/ui/Skeleton';
import { ExtractedDataForm } from '@/components/upload/ExtractedDataForm';
import { ValidationPanel, ValidationLoading } from '@/components/upload/ValidationPanel';
import { SuccessPanel, PostingLoading }        from '@/components/upload/SuccessPanel';
import { DocumentType, DocumentStatus, type ExtractedData } from '@/types';
import type { Document } from '@/types';

// ─── Types ────────────────────────────────────────────────────────────────────

type WizardStep =
  | 'upload'
  | 'extracting'
  | 'extracted'
  | 'validating'
  | 'validated'
  | 'posting'
  | 'complete';

interface WizardState {
  step:         WizardStep;
  documentId:   string | null;
  document:     Document | null;
  file:         File | null;
  selectedType: DocumentType;
  editedData:   ExtractedData | null;
}

const INITIAL: WizardState = {
  step:         'upload',
  documentId:   null,
  document:     null,
  file:         null,
  selectedType: DocumentType.VENDOR_INVOICE,
  editedData:   null,
};

// ─── Step config ──────────────────────────────────────────────────────────────

const WIZARD_STEPS = [
  { label: 'Upload' },
  { label: 'Extracting' },
  { label: 'Review' },
  { label: 'Validation' },
  { label: 'Complete' },
];

function stepToIndex(step: WizardStep): number {
  const map: Record<WizardStep, number> = {
    upload:     0,
    extracting: 1,
    extracted:  2,
    validating: 3,
    validated:  3,
    posting:    4,
    complete:   4,
  };
  return map[step];
}

function stepToTabTitle(step: WizardStep): string {
  const labels: Record<WizardStep, string> = {
    upload:     'Step 1/5 - Upload · DocParser',
    extracting: 'Step 2/5 - Extracting · DocParser',
    extracted:  'Step 3/5 - Review · DocParser',
    validating: 'Step 4/5 - Validating · DocParser',
    validated:  'Step 4/5 - Review Validation · DocParser',
    posting:    'Step 5/5 - Posting · DocParser',
    complete:   'Complete · DocParser',
  };
  return labels[step];
}

// ─── Extraction skeleton ──────────────────────────────────────────────────────

function ExtractionSkeleton({ fileName, fileSize }: { fileName: string; fileSize: number }) {
  const kb = (fileSize / 1024).toFixed(1);
  return (
    <div className="rounded-xl border border-neutral-200 bg-white">
      <div className="flex items-center justify-between border-b border-neutral-100 px-5 py-3.5">
        <div>
          <h3 className="text-sm font-semibold text-neutral-800">Gemini AI · OCR Extraction</h3>
          <p className="mt-0.5 text-xs text-neutral-400">Usually takes 8–15 seconds</p>
        </div>
        <div className="text-right">
          <p className="text-xs font-medium text-neutral-600 truncate max-w-[160px]">{fileName}</p>
          <p className="text-xs text-neutral-400">{kb} KB</p>
        </div>
      </div>
      <div className="p-5 space-y-6">
        {/* 9-field skeleton grid */}
        <div className="grid grid-cols-3 gap-4">
          {Array.from({ length: 9 }, (_, i) => (
            <div key={i} className="space-y-1.5">
              <Skeleton className="h-3 w-16" />
              <Skeleton className="h-9 w-full" />
            </div>
          ))}
        </div>
        {/* Line items skeleton */}
        <div className="space-y-1.5">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-10 w-full" />
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={i} className="h-9 w-full" />
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── Main wizard page ─────────────────────────────────────────────────────────

export default function UploadPage() {
  const [searchParams]  = useSearchParams();
  const uploadProgress  = useDocumentStore((s) => s.uploadProgress);
  const setProgress     = useDocumentStore((s) => s.setProgress);

  const [state,  setState]  = useState<WizardState>(() => ({
    ...INITIAL,
    selectedType: (searchParams.get('type') as DocumentType) ?? DocumentType.VENDOR_INVOICE,
  }));
  const [uploadError, setUploadError] = useState<string | null>(null);
  const pollRef                       = useRef<ReturnType<typeof setInterval>>();

  // Tab title
  useEffect(() => {
    document.title = stepToTabTitle(state.step);
    return () => { document.title = 'DocParser'; };
  }, [state.step]);

  // Warn on navigation away mid-flow
  useEffect(() => {
    if (state.step === 'upload' || state.step === 'complete') return;
    const handler = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [state.step]);

  // Live WebSocket updates
  const { event } = useDocumentWebSocket(state.documentId ?? undefined);
  useEffect(() => {
    if (!event || !state.documentId) return;
    if (event.event !== 'STATUS_CHANGED') return;
    const status = event.data?.status as DocumentStatus | undefined;
    if (!status) return;
    if (status === DocumentStatus.EXTRACTED && state.step === 'extracting') {
      fetchDocumentAndAdvance(state.documentId, 'extracted');
    }
    if (status === DocumentStatus.VALIDATED && state.step === 'validating') {
      fetchDocumentAndAdvance(state.documentId, 'validated');
    }
    if (status === DocumentStatus.POSTED && state.step === 'posting') {
      fetchDocumentAndAdvance(state.documentId, 'complete');
    }
    if (status === DocumentStatus.FAILED) {
      toast.error('Processing failed. Please try again.');
      setState((s) => ({ ...s, step: 'upload' }));
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [event]);

  async function fetchDocumentAndAdvance(docId: string, nextStep: WizardStep) {
    try {
      const resp = await api.get<Document>(`/documents/${docId}`);
      const doc  = resp.data;
      setState((s) => ({
        ...s,
        step:       nextStep,
        document:   doc,
        editedData: nextStep === 'extracted' ? (doc.extracted ?? null) : s.editedData,
      }));
    } catch {
      toast.error('Failed to fetch document. Retrying…');
    }
  }

  // Polling fallback (every 2 s for extracting, 3 s for validating/posting)
  useEffect(() => {
    const active = ['extracting', 'validating', 'posting'];
    if (!active.includes(state.step) || !state.documentId) {
      clearInterval(pollRef.current);
      return;
    }
    const interval = state.step === 'extracting' ? 2_000 : 3_000;
    pollRef.current = setInterval(async () => {
      if (!state.documentId) return;
      try {
        const resp = await api.get<Document>(`/documents/${state.documentId}`);
        const doc  = resp.data;
        const s    = doc.status as DocumentStatus;
        if (s === DocumentStatus.EXTRACTED  && state.step === 'extracting') {
          clearInterval(pollRef.current);
          setState((prev) => ({ ...prev, step: 'extracted', document: doc, editedData: doc.extracted ?? null }));
        } else if (s === DocumentStatus.VALIDATED && state.step === 'validating') {
          clearInterval(pollRef.current);
          setState((prev) => ({ ...prev, step: 'validated', document: doc }));
        } else if (s === DocumentStatus.POSTED && state.step === 'posting') {
          clearInterval(pollRef.current);
          setState((prev) => ({ ...prev, step: 'complete', document: doc }));
        } else if (s === DocumentStatus.FAILED) {
          clearInterval(pollRef.current);
          toast.error('Processing failed. Please try again.');
          setState((prev) => ({ ...prev, step: 'upload' }));
        }
      } catch { /* ignore transient errors */ }
    }, interval);
    return () => clearInterval(pollRef.current);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.step, state.documentId]);

  // ── Upload ──────────────────────────────────────────────────────────────────

  const handleFileSelect = useCallback(async (file: File) => {
    setState((s) => ({ ...s, file }));
    setUploadError(null);
    setProgress(0);

    const formData = new FormData();
    formData.append('file', file);
    formData.append('tcode', 'MIRO');
    formData.append('document_type', state.selectedType);

    try {
      const resp = await api.post<{ document_id: string }>(
        '/documents/upload',
        formData,
        {
          headers: { 'Content-Type': 'multipart/form-data' },
          onUploadProgress: (e) => {
            if (e.total) setProgress(Math.round((e.loaded / e.total) * 100));
          },
        },
      );
      setProgress(100);
      const docId = resp.data.document_id;
      setState((s) => ({ ...s, documentId: docId, step: 'extracting' }));
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Upload failed';
      setUploadError(msg);
      toast.error(msg);
      setProgress(0);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.selectedType]);

  // ── Validate ────────────────────────────────────────────────────────────────

  async function handleValidate() {
    if (!state.documentId) return;
    setState((s) => ({ ...s, step: 'validating' }));
    try {
      await api.post(`/documents/${state.documentId}/validate`);
    } catch {
      toast.error('Failed to trigger validation. Retrying…', {
        id: 'validate-err',
        duration: 4000,
      });
      setState((s) => ({ ...s, step: 'extracted' }));
    }
  }

  // ── Post MIRO ───────────────────────────────────────────────────────────────

  async function handlePostMiro() {
    if (!state.documentId) return;
    setState((s) => ({ ...s, step: 'posting' }));
    try {
      await api.post(`/documents/${state.documentId}/post-miro`);
    } catch {
      toast.error('Failed to trigger MIRO posting. Retrying…');
      setState((s) => ({ ...s, step: 'validated' }));
    }
  }

  // ── Reset ────────────────────────────────────────────────────────────────────

  function reset() {
    clearInterval(pollRef.current);
    setProgress(0);
    setUploadError(null);
    setState(INITIAL);
  }

  // ── Render ───────────────────────────────────────────────────────────────────

  const isUploading = state.step === 'upload' && uploadProgress > 0 && uploadProgress < 100;
  const doc         = state.document;

  return (
    <>
      <Topbar
        title="Upload & Process"
        subtitle={
          state.step === 'complete'
            ? 'Processing complete'
            : 'Follow the steps to post your document to SAP'
        }
      />

      <div className="mx-auto max-w-3xl space-y-6 p-6">

        {/* Step indicator */}
        <StepIndicator steps={WIZARD_STEPS} currentStep={stepToIndex(state.step)} />

        {/* ── Step 1: Upload ─────────────────────────────────────────────── */}
        {state.step === 'upload' && (
          <div className="space-y-5">
            <div className="rounded-xl border border-neutral-200 bg-white p-5 space-y-4">
              <h2 className="text-sm font-semibold text-neutral-800">Select Document Type</h2>
              <DocTypePicker
                value={state.selectedType}
                onChange={(type) => setState((s) => ({ ...s, selectedType: type }))}
              />
            </div>

            <div className="rounded-xl border border-neutral-200 bg-white p-5 space-y-3">
              <h2 className="text-sm font-semibold text-neutral-800">Upload File</h2>
              <FileDropzone
                file={state.file}
                progress={uploadProgress}
                uploading={isUploading}
                error={uploadError}
                onFileSelect={handleFileSelect}
                onClear={() => { setState((s) => ({ ...s, file: null })); setUploadError(null); }}
              />
            </div>
          </div>
        )}

        {/* ── Step 2: Extracting ─────────────────────────────────────────── */}
        {state.step === 'extracting' && state.file && (
          <ExtractionSkeleton
            fileName={state.file.name}
            fileSize={state.file.size}
          />
        )}

        {/* ── Step 3: Review extracted data ──────────────────────────────── */}
        {state.step === 'extracted' && state.editedData && (
          <ExtractedDataForm
            data={state.editedData}
            onDataChange={(updated) => setState((s) => ({ ...s, editedData: updated }))}
            onValidate={handleValidate}
            isValidating={false}
          />
        )}

        {/* ── Step 4a: Validating loading ────────────────────────────────── */}
        {state.step === 'validating' && (
          <div className="rounded-xl border border-neutral-200 bg-white p-8">
            <ValidationLoading />
          </div>
        )}

        {/* ── Step 4b: Validation results ────────────────────────────────── */}
        {state.step === 'validated' && doc?.sap_validation && (
          <ValidationPanel
            validation={doc.sap_validation}
            onPost={handlePostMiro}
            isPosting={false}
          />
        )}

        {/* ── Step 5a: Posting loading ───────────────────────────────────── */}
        {state.step === 'posting' && (
          <div className="rounded-xl border border-neutral-200 bg-white p-8">
            <PostingLoading lineItemCount={state.editedData?.line_items?.length ?? 0} />
          </div>
        )}

        {/* ── Step 5b: Complete ──────────────────────────────────────────── */}
        {state.step === 'complete' && doc?.miro_posting && (
          <div className="rounded-xl border border-neutral-200 bg-white p-6">
            <SuccessPanel
              miro={doc.miro_posting}
              extracted={doc.extracted}
              onReset={reset}
            />
          </div>
        )}

        {/* Start over */}
        {state.step !== 'upload' && state.step !== 'complete' && (
          <div className="flex justify-center">
            <button
              type="button"
              onClick={() => {
                if (window.confirm('Start over? Current progress will be lost.')) reset();
              }}
              className="flex items-center gap-1.5 text-xs text-neutral-400 hover:text-neutral-600 transition-colors"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              Start over
            </button>
          </div>
        )}
      </div>
    </>
  );
}
