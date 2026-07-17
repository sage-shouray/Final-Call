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
import { NonPOInvoiceForm }  from '@/components/upload/NonPOInvoiceForm';
import { SalesOrderForm }    from '@/components/upload/SalesOrderForm';
import { ValidationPanel, ValidationLoading } from '@/components/upload/ValidationPanel';
import { SuccessPanel, PostingLoading }        from '@/components/upload/SuccessPanel';
import { DocumentType, DocumentStatus, InvoiceSubtype, type ExtractedData, type FB60FormData } from '@/types';
import type { Document } from '@/types';

// ─── Types ────────────────────────────────────────────────────────────────────

type WizardStep =
  | 'upload'
  | 'extracting'
  | 'extracted'
  | 'validating'
  | 'validated'
  | 'gr_posting'
  | 'gr_posted'
  | 'posting'
  | 'complete';

interface WizardState {
  step:             WizardStep;
  documentId:       string | null;
  document:         Document | null;
  file:             File | null;
  selectedType:     DocumentType;
  parentInvoiceType: 'po' | 'non_po' | null;
  invoiceSubtype:   InvoiceSubtype | null;
  editedData:       ExtractedData | null;
}

const INITIAL: WizardState = {
  step:              'upload',
  documentId:        null,
  document:          null,
  file:              null,
  selectedType:      DocumentType.VENDOR_INVOICE,
  parentInvoiceType: null,
  invoiceSubtype:    null,
  editedData:        null,
};

// ─── Step config ──────────────────────────────────────────────────────────────

const MIRO_STEPS = [
  { label: 'Upload' },
  { label: 'Extracting' },
  { label: 'Review' },
  { label: 'Validation' },
  { label: 'Complete' },
];

const MIGO_STEPS = [
  { label: 'Upload' },
  { label: 'Extracting' },
  { label: 'Post GR' },
  { label: 'Post Invoice' },
  { label: 'Complete' },
];

function stepToIndex(step: WizardStep, isMigo: boolean): number {
  if (isMigo) {
    const map: Record<WizardStep, number> = {
      upload:     0,
      extracting: 1,
      extracted:  2,
      gr_posting: 2,
      gr_posted:  3,
      validating: 3,
      validated:  3,
      posting:    4,
      complete:   4,
    };
    return map[step];
  }
  const map: Record<WizardStep, number> = {
    upload:     0,
    extracting: 1,
    extracted:  2,
    validating: 3,
    validated:  3,
    gr_posting: 3,
    gr_posted:  3,
    posting:    4,
    complete:   4,
  };
  return map[step];
}

function stepToTabTitle(step: WizardStep): string {
  const labels: Record<WizardStep, string> = {
    upload:     'Step 1 - Upload · Uvira.ai',
    extracting: 'Step 2 - Extracting · Uvira.ai',
    extracted:  'Step 3 - Review · Uvira.ai',
    gr_posting: 'Step 3 - Posting GR · Uvira.ai',
    gr_posted:  'Step 4 - GR Posted · Uvira.ai',
    validating: 'Step 4 - Validating · Uvira.ai',
    validated:  'Step 4 - Review Validation · Uvira.ai',
    posting:    'Step 5 - Posting · Uvira.ai',
    complete:   'Complete · Uvira.ai',
  };
  return labels[step];
}

// ─── Extraction skeleton ──────────────────────────────────────────────────────

function ExtractionSkeleton({ fileName, fileSize }: { fileName: string; fileSize: number }) {
  const kb = (fileSize / 1024).toFixed(1);
  return (
    <div className="rounded-xl border border-neutral-200 bg-white dark:border-neutral-700 dark:bg-neutral-900">
      <div className="flex items-center justify-between border-b border-neutral-100 px-5 py-3.5 dark:border-neutral-700">
        <div>
          <h3 className="text-sm font-semibold text-neutral-800 dark:text-neutral-200">Gemini AI · OCR Extraction</h3>
          <p className="mt-0.5 text-xs text-neutral-400 dark:text-neutral-500">Usually takes 8–15 seconds</p>
        </div>
        <div className="text-right">
          <p className="text-xs font-medium text-neutral-600 dark:text-neutral-400 truncate max-w-[160px]">{fileName}</p>
          <p className="text-xs text-neutral-400 dark:text-neutral-500">{kb} KB</p>
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
    return () => { document.title = 'Uvira.ai'; };
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

  // Polling fallback
  useEffect(() => {
    const active = ['extracting', 'validating', 'gr_posting', 'posting'];
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
        if (s === DocumentStatus.EXTRACTED && state.step === 'extracting') {
          clearInterval(pollRef.current);
          setState((prev) => ({ ...prev, step: 'extracted', document: doc, editedData: doc.extracted ?? null }));
        } else if (s === DocumentStatus.GR_POSTED && state.step === 'gr_posting') {
          clearInterval(pollRef.current);
          setState((prev) => ({ ...prev, step: 'gr_posted', document: doc }));
        } else if (s === DocumentStatus.VALIDATED && state.step === 'validating') {
          clearInterval(pollRef.current);
          setState((prev) => ({ ...prev, step: 'validated', document: doc }));
        } else if (s === DocumentStatus.POSTED && state.step === 'posting') {
          clearInterval(pollRef.current);
          setState((prev) => ({ ...prev, step: 'complete', document: doc }));
        } else if (s === DocumentStatus.EXTRACTED && state.step === 'posting') {
          // FB60 failed — worker reverted status back to EXTRACTED
          clearInterval(pollRef.current);
          const errMsg = doc.fb60_posting?.message || 'SAP rejected the posting. Fix the errors and retry.';
          toast.error(errMsg, { duration: 8000 });
          setState((prev) => ({ ...prev, step: 'extracted', document: doc }));
        } else if (s === DocumentStatus.VALIDATED && state.step === 'posting') {
          // MIRO failed — worker reverted status back to VALIDATED
          clearInterval(pollRef.current);
          toast.error('SAP posting failed. Please retry.');
          setState((prev) => ({ ...prev, step: 'validated', document: doc }));
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
    formData.append('document_type', state.selectedType);
    if (state.invoiceSubtype) formData.append('invoice_subtype', state.invoiceSubtype);

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
  }, [state.selectedType, state.invoiceSubtype]);

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

  // ── Post GRN (MIGO) ─────────────────────────────────────────────────────────

  async function handlePostGrn() {
    if (!state.documentId) return;
    setState((s) => ({ ...s, step: 'gr_posting' }));
    try {
      await api.post(`/documents/${state.documentId}/post-grn`);
    } catch {
      toast.error('Failed to trigger GR posting. Please retry.');
      setState((s) => ({ ...s, step: 'extracted' }));
    }
  }

  // ── Post FB60 (Non-PO Invoice) ───────────────────────────────────────────────

  async function handlePostFB60(formData: FB60FormData) {
    if (!state.documentId) return;
    setState((s) => ({ ...s, step: 'posting' }));
    try {
      await api.post(`/documents/${state.documentId}/post-fb60`, formData);
    } catch {
      toast.error('Failed to post to SAP FB60. Please retry.');
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
      setState((s) => ({ ...s, step: isMigo ? 'gr_posted' : 'validated' }));
    }
  }

  async function handleSimulate(customerId: string) {
    if (!state.documentId) return;
    setState((s) => ({ ...s, step: 'validating' }));
    try {
      await api.post(`/documents/${state.documentId}/so-simulate`, { customer_id: customerId });
      toast.success('Simulation started — waiting for SAP response…');
    } catch {
      toast.error('Simulation failed. Please try again.');
      setState((s) => ({ ...s, step: 'extracted' }));
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

  const isUploading   = state.step === 'upload' && uploadProgress > 0 && uploadProgress < 100;
  const doc           = state.document;
  const isMigo        = state.selectedType === DocumentType.GOODS_RECEIPT;
  const isVendorInv   = state.selectedType === DocumentType.VENDOR_INVOICE;
  const isFreightInv  = state.selectedType === DocumentType.FREIGHT_INVOICE;
  const isSalesOrder  = state.selectedType === DocumentType.SALES_ORDER;
  const isNonPO       = isVendorInv && state.invoiceSubtype === InvoiceSubtype.NON_PO;
  const isServicePO   = isVendorInv && state.invoiceSubtype === InvoiceSubtype.SERVICE_PO;
  const needsSubtype  = isVendorInv && state.invoiceSubtype === null;

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

      <div className="space-y-6 p-6">

        {/* Step indicator */}
        <div className="mx-auto max-w-3xl">
          <StepIndicator steps={isMigo ? MIGO_STEPS : MIRO_STEPS} currentStep={stepToIndex(state.step, isMigo)} />
        </div>

        {/* ── Step 1: Upload ─────────────────────────────────────────────── */}
        {state.step === 'upload' && (
          <div className="mx-auto max-w-3xl space-y-5">
            <div className="rounded-xl border border-neutral-200 bg-white p-5 space-y-4 dark:border-neutral-700 dark:bg-neutral-900">
              <h2 className="text-sm font-semibold text-neutral-800 dark:text-neutral-200">Select Document Type</h2>
              <DocTypePicker
                value={state.selectedType}
                onChange={(type) => setState((s) => ({
                  ...s,
                  selectedType: type,
                  parentInvoiceType: null,
                  invoiceSubtype: type === DocumentType.FREIGHT_INVOICE ? InvoiceSubtype.FREIGHT_PO : null,
                }))}
              />
            </div>

            {/* Invoice sub-type selector — only for Vendor Invoice (not Freight Invoice, which auto-routes) */}
            {isVendorInv && (
              <div className="rounded-xl border border-neutral-200 bg-white p-5 space-y-4 dark:border-neutral-700 dark:bg-neutral-900">
                <h2 className="text-sm font-semibold text-neutral-800 dark:text-neutral-200">Invoice Type</h2>

                {/* Level 1: PO / Non-PO */}
                <div className="grid grid-cols-2 gap-3">
                  {([
                    { value: 'po'     as const, label: 'PO Invoice',     desc: 'Invoice linked to a Purchase Order' },
                    { value: 'non_po' as const, label: 'Non-PO Invoice', desc: 'Direct GL posting — no Purchase Order' },
                  ]).map(opt => (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => setState(s => ({
                        ...s,
                        parentInvoiceType: opt.value,
                        invoiceSubtype: opt.value === 'non_po' ? InvoiceSubtype.NON_PO : null,
                      }))}
                      className={`rounded-xl border-2 p-4 text-left transition-all ${
                        state.parentInvoiceType === opt.value
                          ? 'border-primary-500 bg-primary-50 dark:bg-indigo-950/50 dark:border-indigo-500'
                          : 'border-neutral-200 bg-white hover:border-neutral-300 dark:border-neutral-700 dark:bg-neutral-800 dark:hover:border-neutral-500'
                      }`}
                    >
                      <p className={`text-sm font-semibold ${state.parentInvoiceType === opt.value ? 'text-primary-700 dark:text-indigo-300' : 'text-neutral-800 dark:text-neutral-200'}`}>
                        {opt.label}
                      </p>
                      <p className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">{opt.desc}</p>
                    </button>
                  ))}
                </div>

                {/* Level 2: Material PO / Service PO — only when PO selected */}
                {state.parentInvoiceType === 'po' && (
                  <div>
                    <p className="mb-2 text-xs text-neutral-500 font-medium dark:text-neutral-400">Select PO type:</p>
                    <div className="grid grid-cols-2 gap-3">
                      {([
                        { value: InvoiceSubtype.PO,         label: 'Material PO', desc: 'Physical goods — GR (MIGO) then invoice (MIRO)' },
                        { value: InvoiceSubtype.SERVICE_PO,  label: 'Service PO',  desc: 'Services — validate SES then invoice (MIRO)' },
                      ] as const).map(opt => (
                        <button
                          key={opt.value}
                          type="button"
                          onClick={() => setState(s => ({ ...s, invoiceSubtype: opt.value }))}
                          className={`rounded-xl border-2 p-4 text-left transition-all ${
                            state.invoiceSubtype === opt.value
                              ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-950/50 dark:border-indigo-500'
                              : 'border-neutral-200 bg-white hover:border-neutral-300 dark:border-neutral-700 dark:bg-neutral-800 dark:hover:border-neutral-500'
                          }`}
                        >
                          <p className={`text-sm font-semibold ${state.invoiceSubtype === opt.value ? 'text-indigo-700 dark:text-indigo-300' : 'text-neutral-800 dark:text-neutral-200'}`}>
                            {opt.label}
                          </p>
                          <p className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">{opt.desc}</p>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            <div className={`rounded-xl border border-neutral-200 bg-white p-5 space-y-3 dark:border-neutral-700 dark:bg-neutral-900 ${needsSubtype ? 'opacity-40 pointer-events-none' : ''}`}>
              <h2 className="text-sm font-semibold text-neutral-800 dark:text-neutral-200">Upload File</h2>
              {needsSubtype && (
                <p className="text-xs text-amber-600 dark:text-amber-400">Please select an invoice type above first.</p>
              )}
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
          <div className="mx-auto max-w-3xl">
            <ExtractionSkeleton
              fileName={state.file.name}
              fileSize={state.file.size}
            />
          </div>
        )}

        {/* ── Service PO / Freight Invoice flow: validate → MIRO ───────── */}
        {(isServicePO || isFreightInv) && state.step === 'extracted' && state.editedData && (
          <div className="space-y-3">
            <div className="rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-2.5 text-xs text-indigo-700 font-medium dark:border-indigo-800 dark:bg-indigo-950/30 dark:text-indigo-400">
              {isFreightInv
                ? 'Freight Invoice — validates GR against SAP PO, then posts to MIRO (no MIGO step required)'
                : 'Service PO — validates invoice details against SAP, then posts to MIRO (no MIGO required)'}
            </div>
            <ExtractedDataForm
              data={state.editedData}
              onDataChange={(updated) => setState((s) => ({ ...s, editedData: updated }))}
              onValidate={handleValidate}
              isValidating={false}
              validateLabel={isFreightInv ? 'Validate Freight Invoice' : 'Validate Service PO'}
            />
          </div>
        )}
        {(isServicePO || isFreightInv) && state.step === 'validating' && (
          <div className="rounded-xl border border-neutral-200 bg-white p-8 dark:border-neutral-700 dark:bg-neutral-900">
            <ValidationLoading />
          </div>
        )}
        {(isServicePO || isFreightInv) && state.step === 'validated' && doc?.sap_validation && (
          <ValidationPanel
            validation={doc.sap_validation}
            onPost={handlePostMiro}
            isPosting={false}
          />
        )}

        {/* ── Sales Order flow: Step 3 Customer Search + Simulate ─────────── */}
        {isSalesOrder && state.step === 'extracted' && state.editedData && (
          <div className="space-y-3">
            <div className="rounded-lg border border-violet-200 bg-violet-50 px-4 py-2.5 text-xs text-violet-700 font-medium dark:border-violet-800 dark:bg-violet-950/30 dark:text-violet-400">
              Sales Order (VA01) — search and confirm customer, review line items, then simulate via SAP
            </div>
            <SalesOrderForm
              extracted={state.editedData}
              onSimulate={handleSimulate}
              isSimulating={false}
            />
          </div>
        )}
        {isSalesOrder && state.step === 'validating' && (
          <div className="rounded-xl border border-neutral-200 bg-white p-8 dark:border-neutral-700 dark:bg-neutral-900">
            <div className="flex flex-col items-center gap-3 text-center">
              <div className="h-10 w-10 rounded-full bg-violet-100 flex items-center justify-center dark:bg-violet-900/40">
                <div className="h-5 w-5 animate-spin rounded-full border-2 border-violet-500 border-t-transparent" />
              </div>
              <p className="text-sm font-semibold text-neutral-800 dark:text-neutral-200">Simulating Sales Order…</p>
              <p className="text-xs text-neutral-400 dark:text-neutral-500">Sending to SAP ZDATA_HOLD/DATA_SIMULATE</p>
            </div>
          </div>
        )}
        {isSalesOrder && state.step === 'validated' && doc && (() => {
          const sim = doc.so_simulation as Record<string, unknown> | null;
          const sapResp = (sim?.sap_response ?? {}) as Record<string, unknown>;
          const isSuccess = (sim?.status === 'success') || String(sapResp?.STATUS ?? '').toUpperCase() === 'SUCCESS';
          const sapMessage = String(sapResp?.MESSAGE ?? sapResp?.message ?? '');
          return (
            <div className={`rounded-xl border p-5 space-y-3 ${isSuccess ? 'border-green-200 bg-green-50 dark:border-green-800 dark:bg-green-950/30' : 'border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950/30'}`}>
              <div className="flex items-center gap-2">
                <div className={`h-8 w-8 rounded-full flex items-center justify-center ${isSuccess ? 'bg-green-100 dark:bg-green-900' : 'bg-red-100 dark:bg-red-900'}`}>
                  {isSuccess
                    ? <svg className="h-4 w-4 text-green-600 dark:text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" /></svg>
                    : <svg className="h-4 w-4 text-red-500 dark:text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
                  }
                </div>
                <div>
                  <p className={`text-sm font-semibold ${isSuccess ? 'text-green-800 dark:text-green-300' : 'text-red-700 dark:text-red-300'}`}>
                    {isSuccess ? 'Simulation Successful' : 'Simulation Failed'}
                  </p>
                  <p className={`text-xs mt-0.5 ${isSuccess ? 'text-green-600 dark:text-green-400' : 'text-red-500 dark:text-red-400'}`}>{sapMessage}</p>
                </div>
              </div>
              <div className={`rounded-lg bg-white border p-3 text-xs text-neutral-600 dark:bg-neutral-900 dark:text-neutral-400 ${isSuccess ? 'border-green-100 dark:border-green-900' : 'border-red-100 dark:border-red-900'}`}>
                <pre className="whitespace-pre-wrap break-all">{JSON.stringify(sapResp, null, 2)}</pre>
              </div>
              {isSuccess && (
                <button
                  type="button"
                  onClick={async () => {
                    const sim = doc.so_simulation as Record<string, unknown> | null;
                    const payload = sim?.payload_sent as Record<string, unknown> | null;
                    const custId = (payload?.partners as {partn_numb: string}[] | null)?.[0]?.partn_numb ?? '';
                    if (!custId || !state.documentId) return;
                    setState(s => ({ ...s, step: 'posting' }));
                    try {
                      await api.post(`/documents/${state.documentId}/so-create`, { customer_id: custId });
                      toast.success('Sales Order creation started…');
                    } catch {
                      toast.error('Failed to create Sales Order.');
                      setState(s => ({ ...s, step: 'validated' }));
                    }
                  }}
                  className="w-full rounded-lg bg-indigo-600 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 transition-colors"
                >
                  Create Sales Order
                </button>
              )}
            </div>
          );
        })()}

        {/* ── Sales Order: posting spinner ───────────────────────────────── */}
        {isSalesOrder && state.step === 'posting' && (
          <div className="rounded-xl border border-neutral-200 bg-white p-8 dark:border-neutral-700 dark:bg-neutral-900">
            <div className="flex flex-col items-center gap-3 text-center">
              <div className="h-10 w-10 rounded-full bg-indigo-100 flex items-center justify-center dark:bg-indigo-900/40">
                <div className="h-5 w-5 animate-spin rounded-full border-2 border-indigo-500 border-t-transparent" />
              </div>
              <p className="text-sm font-semibold text-neutral-800 dark:text-neutral-200">Creating Sales Order in SAP…</p>
              <p className="text-xs text-neutral-400 dark:text-neutral-500">Sending to ZCREATE_SALESOR/SALESORDER_CREATE</p>
            </div>
          </div>
        )}
        {/* ── Sales Order: created result ─────────────────────────────────── */}
        {isSalesOrder && state.step === 'complete' && doc && (() => {
          const posting = doc.so_posting as Record<string, unknown> | null;
          const isSuccess = posting?.status === 'success';
          const soNumber  = String(posting?.sales_order_number ?? '');
          const returnMsgs = (posting?.return_messages ?? []) as {TYPE: string; MESSAGE: string}[];
          const errors   = returnMsgs.filter(m => m.TYPE === 'E');
          const warnings = returnMsgs.filter(m => m.TYPE === 'W');
          const successes = returnMsgs.filter(m => m.TYPE === 'S');
          return (
            <div className={`rounded-xl border p-5 space-y-4 ${isSuccess ? 'border-green-200 bg-green-50 dark:border-green-800 dark:bg-green-950/30' : 'border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950/30'}`}>
              <div className="flex items-center gap-3">
                <div className={`h-9 w-9 rounded-full flex items-center justify-center ${isSuccess ? 'bg-green-100 dark:bg-green-900' : 'bg-red-100 dark:bg-red-900'}`}>
                  {isSuccess
                    ? <svg className="h-5 w-5 text-green-600 dark:text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" /></svg>
                    : <svg className="h-5 w-5 text-red-500 dark:text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
                  }
                </div>
                <div>
                  <p className={`text-sm font-semibold ${isSuccess ? 'text-green-800 dark:text-green-300' : 'text-red-700 dark:text-red-300'}`}>
                    {isSuccess ? `Sales Order Created — ${soNumber}` : 'Sales Order Creation Failed'}
                  </p>
                  {isSuccess && <p className="text-xs text-green-600 dark:text-green-400 mt-0.5">Order number: <span className="font-bold">{soNumber}</span></p>}
                </div>
              </div>
              {/* SAP RETURN messages */}
              <div className="space-y-1.5">
                {successes.map((m, i) => (
                  <div key={i} className="flex items-start gap-2 text-xs text-green-700 bg-green-100 rounded px-2.5 py-1.5 dark:text-green-400 dark:bg-green-950">
                    <span className="font-bold shrink-0">S</span><span>{m.MESSAGE}</span>
                  </div>
                ))}
                {warnings.map((m, i) => (
                  <div key={i} className="flex items-start gap-2 text-xs text-amber-700 bg-amber-50 rounded px-2.5 py-1.5 dark:text-amber-400 dark:bg-amber-950">
                    <span className="font-bold shrink-0">W</span><span>{m.MESSAGE}</span>
                  </div>
                ))}
                {errors.map((m, i) => (
                  <div key={i} className="flex items-start gap-2 text-xs text-red-700 bg-red-100 rounded px-2.5 py-1.5 dark:text-red-400 dark:bg-red-950">
                    <span className="font-bold shrink-0">E</span><span>{m.MESSAGE}</span>
                  </div>
                ))}
              </div>
            </div>
          );
        })()}

        {/* ── Material PO flow: Step 3 Review / Step 4 Validate ──────────── */}
        {!isMigo && !isNonPO && !isServicePO && !isFreightInv && !isSalesOrder && state.step === 'extracted' && state.editedData && (
          <ExtractedDataForm
            data={state.editedData}
            onDataChange={(updated) => setState((s) => ({ ...s, editedData: updated }))}
            onValidate={handleValidate}
            isValidating={false}
          />
        )}
        {!isMigo && !isNonPO && !isServicePO && !isFreightInv && !isSalesOrder && state.step === 'validating' && (
          <div className="rounded-xl border border-neutral-200 bg-white p-8 dark:border-neutral-700 dark:bg-neutral-900">
            <ValidationLoading />
          </div>
        )}
        {!isMigo && !isNonPO && !isServicePO && !isFreightInv && !isSalesOrder && state.step === 'validated' && doc?.sap_validation && (
          <ValidationPanel
            validation={doc.sap_validation}
            onPost={handlePostMiro}
            isPosting={false}
          />
        )}

        {/* ── Non-PO Invoice flow: Step 3 FB60 Form ──────────────────────── */}
        {isNonPO && state.step === 'extracted' && (
          <>
            {doc?.fb60_posting?.status === 'failed' && doc.fb60_posting.message && (
              <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-400">
                <p className="font-semibold mb-1">SAP rejected the previous posting:</p>
                <ul className="list-disc list-inside space-y-0.5">
                  {doc.fb60_posting.message.split(' | ').map((msg, i) => (
                    <li key={i}>{msg}</li>
                  ))}
                </ul>
                <p className="mt-2 text-xs text-red-500 dark:text-red-400">Correct the fields below and try again.</p>
              </div>
            )}
            <NonPOInvoiceForm
              extracted={state.editedData}
              isPosting={false}
              onPost={handlePostFB60}
            />
          </>
        )}

        {/* ── MIGO flow: Step 3 Post GR ──────────────────────────────────── */}
        {isMigo && state.step === 'extracted' && state.editedData && (
          <div className="rounded-xl border border-neutral-200 bg-white p-6 space-y-4 dark:border-neutral-700 dark:bg-neutral-900">
            <div>
              <h2 className="text-sm font-semibold text-neutral-800 dark:text-neutral-200">Extracted Data Ready</h2>
              <p className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">Review the extracted fields below, then post the Goods Receipt to SAP.</p>
            </div>
            <ExtractedDataForm
              data={state.editedData}
              onDataChange={(updated) => setState((s) => ({ ...s, editedData: updated }))}
              onValidate={handlePostGrn}
              isValidating={false}
              validateLabel="Post to MIGO"
            />
          </div>
        )}
        {isMigo && state.step === 'gr_posting' && (
          <div className="rounded-xl border border-teal-200 bg-teal-50 p-8 flex flex-col items-center gap-3 dark:border-teal-800 dark:bg-teal-950/30">
            <div className="h-8 w-8 rounded-full border-2 border-teal-400 border-t-transparent animate-spin" />
            <p className="text-sm font-medium text-teal-800 dark:text-teal-300">Posting Goods Receipt to SAP…</p>
            <p className="text-xs text-teal-600 dark:text-teal-500">This may take up to 60 seconds</p>
          </div>
        )}
        {isMigo && state.step === 'gr_posted' && doc?.grn_posting && (
          <div className="space-y-4">
            {/* GRN result table */}
            <div className="rounded-xl border border-teal-200 overflow-hidden dark:border-teal-800">
              <div className="flex items-center justify-between px-5 py-4 bg-teal-50 dark:bg-teal-950/40">
                <div>
                  <p className="text-sm font-semibold text-teal-900 dark:text-teal-200">
                    {doc.grn_posting.already_done
                      ? 'MIGO Already Done — GR Previously Posted'
                      : 'Goods Receipt Posted Successfully'}
                  </p>
                  <p className="text-xs text-teal-600 dark:text-teal-400">
                    {doc.grn_posting.already_done
                      ? 'Quantities already received in SAP — you can proceed to post the invoice'
                      : String(doc.grn_posting.posted_at ?? '')}
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-[10px] font-semibold uppercase tracking-widest text-teal-500 dark:text-teal-400">GRN Number</p>
                  <p className="font-mono text-xl font-bold text-teal-900 dark:text-teal-200">{doc.grn_posting.grn_number}</p>
                </div>
              </div>
              {Array.isArray((doc.grn_posting.payload_sent as Record<string, unknown>)?.po_items) && (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-teal-100/60 dark:bg-teal-900/30">
                      <tr>
                        <th className="px-4 py-2.5 text-left text-[11px] font-semibold uppercase tracking-wider text-teal-700 dark:text-teal-400">PO Item</th>
                        <th className="px-4 py-2.5 text-left text-[11px] font-semibold uppercase tracking-wider text-teal-700 dark:text-teal-400">Material</th>
                        <th className="px-4 py-2.5 text-right text-[11px] font-semibold uppercase tracking-wider text-teal-700 dark:text-teal-400">Quantity</th>
                        <th className="px-4 py-2.5 text-center text-[11px] font-semibold uppercase tracking-wider text-teal-700 dark:text-teal-400">Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-teal-100 bg-white dark:divide-teal-900 dark:bg-neutral-900">
                      {((doc.grn_posting.payload_sent as Record<string, unknown>).po_items as { po_item: string; material: string; quantity: string }[]).map((item, idx) => (
                        <tr key={idx}>
                          <td className="px-4 py-3 font-mono text-xs text-neutral-700 dark:text-neutral-300">{item.po_item}</td>
                          <td className="px-4 py-3 font-mono text-xs text-neutral-700 dark:text-neutral-300">{item.material}</td>
                          <td className="px-4 py-3 text-right font-medium text-neutral-800 dark:text-neutral-200">{item.quantity}</td>
                          <td className="px-4 py-3 text-center">
                            <span className="inline-flex items-center gap-1 rounded-full bg-teal-100 px-2.5 py-0.5 text-[11px] font-medium text-teal-700 dark:bg-teal-950 dark:text-teal-400">Posted</span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
            {/* Post Invoice button */}
            <div className="flex justify-end">
              <button
                type="button"
                onClick={handlePostMiro}
                className="inline-flex items-center gap-2 rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 transition-colors"
              >
                Post Invoice to SAP
              </button>
            </div>
          </div>
        )}

        {/* ── Step 5a: Posting loading ───────────────────────────────────── */}
        {state.step === 'posting' && (
          <div className="rounded-xl border border-neutral-200 bg-white p-8 dark:border-neutral-700 dark:bg-neutral-800">
            <PostingLoading
              lineItemCount={state.editedData?.line_items?.length ?? 0}
              target={isNonPO ? 'FB60' : isMigo ? 'MIRO (via MIGO)' : isServicePO ? 'MIRO (Service PO)' : 'MIRO'}
            />
          </div>
        )}

        {/* ── Step 5b: Complete ──────────────────────────────────────────── */}
        {state.step === 'complete' && (doc?.miro_posting || doc?.fb60_posting) && (
          <div className="rounded-xl border border-neutral-200 bg-white p-6 dark:border-neutral-700 dark:bg-neutral-800">
            <SuccessPanel
              miro={doc.miro_posting}
              fb60={doc.fb60_posting}
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
              className="flex items-center gap-1.5 text-xs text-neutral-400 hover:text-neutral-600 dark:hover:text-neutral-300 transition-colors"
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
