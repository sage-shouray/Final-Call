import { useState, useRef, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Search, SlidersHorizontal, Download, X,
  ChevronUp, ChevronDown, ChevronsUpDown,
  Upload, CheckCircle2, Loader2, AlertCircle, ArrowRight,
} from 'lucide-react';
import { api } from '@/lib/api';
import { useDocuments }  from '@/hooks/useDocuments';
import { StatusPill }    from '@/components/ui/StatusPill';
import { TCodeChip }     from '@/components/ui/TCodeChip';
import { SkeletonRow }   from '@/components/ui/Skeleton';
import { Button }        from '@/components/ui/Button';
import {
  Table, TableHead, TableBody, TableRow,
  TableHeaderCell, TableCell,
} from '@/components/ui/Table';
import { Topbar }        from '@/components/layout/Topbar';
import { formatDate }    from '@/lib/dates';
import { toINR }         from '@/lib/currency';
import { cn }            from '@/lib/cn';
import {
  DocumentStatus, DocumentType, TCode,
  type DocumentFilters, type DocumentListItem,
} from '@/types';
import { DOC_TYPE_LABEL, PAGE_SIZE_OPTIONS, DEFAULT_PAGE_SIZE } from '@/utils/constants';

// ─── Inline action button per row ─────────────────────────────────────────────

function RowAction({ doc }: { doc: DocumentListItem }) {
  const qc       = useQueryClient();
  const navigate = useNavigate();
  const isMigo   = doc.tcode === 'MIGO' || doc.type === 'goods_receipt';
  const isNonPO  = doc.tcode === 'FB60' || doc.invoice_subtype === 'non_po';

  const validateMut = useMutation({
    mutationFn: () => api.post(`/documents/${doc.document_id}/validate`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['documents'] }),
  });
  const miroMut = useMutation({
    mutationFn: () => api.post(`/documents/${doc.document_id}/post-miro`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['documents'] }),
  });
  const grnMut = useMutation({
    mutationFn: () => api.post(`/documents/${doc.document_id}/post-grn`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['documents'] }),
  });
  const retryMut = useMutation({
    mutationFn: () => api.post(`/documents/${doc.document_id}/retry`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['documents'] }),
  });

  const stop = (e: React.MouseEvent) => e.stopPropagation();

  if (doc.status === DocumentStatus.EXTRACTED && !isMigo && !isNonPO) {
    return (
      <button onClick={(e) => { stop(e); validateMut.mutate(); }} disabled={validateMut.isPending}
        className="inline-flex items-center gap-1 rounded-md bg-primary-50 px-2.5 py-1 text-xs font-medium text-primary-700 hover:bg-primary-100 disabled:opacity-50 border border-primary-200 transition-colors whitespace-nowrap">
        {validateMut.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <CheckCircle2 className="h-3 w-3" />}
        {doc.invoice_subtype === 'freight_po' ? 'Validate Freight' : doc.invoice_subtype === 'service_po' ? 'Validate Service' : 'Validate with SAP'}
      </button>
    );
  }
  if (doc.status === DocumentStatus.EXTRACTED && isMigo) {
    return (
      <button onClick={(e) => { stop(e); grnMut.mutate(); }} disabled={grnMut.isPending}
        className="inline-flex items-center gap-1 rounded-md bg-teal-50 px-2.5 py-1 text-xs font-medium text-teal-700 hover:bg-teal-100 disabled:opacity-50 border border-teal-200 transition-colors whitespace-nowrap">
        {grnMut.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <ArrowRight className="h-3 w-3" />}
        Post to MIGO
      </button>
    );
  }
  if (doc.status === DocumentStatus.VALIDATED && !isMigo) {
    return (
      <button onClick={(e) => { stop(e); miroMut.mutate(); }} disabled={miroMut.isPending}
        className="inline-flex items-center gap-1 rounded-md bg-green-50 px-2.5 py-1 text-xs font-medium text-green-700 hover:bg-green-100 disabled:opacity-50 border border-green-200 transition-colors whitespace-nowrap">
        {miroMut.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <ArrowRight className="h-3 w-3" />}
        Post to MIRO
      </button>
    );
  }
  if (doc.status === DocumentStatus.GR_POSTED) {
    return (
      <button onClick={(e) => { stop(e); miroMut.mutate(); }} disabled={miroMut.isPending}
        className="inline-flex items-center gap-1 rounded-md bg-green-50 px-2.5 py-1 text-xs font-medium text-green-700 hover:bg-green-100 disabled:opacity-50 border border-green-200 transition-colors whitespace-nowrap">
        {miroMut.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <ArrowRight className="h-3 w-3" />}
        Post to MIRO
      </button>
    );
  }
  if (doc.status === DocumentStatus.FAILED) {
    return (
      <button onClick={(e) => { stop(e); retryMut.mutate(); }} disabled={retryMut.isPending}
        className="inline-flex items-center gap-1 rounded-md bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-700 hover:bg-amber-100 disabled:opacity-50 border border-amber-200 transition-colors whitespace-nowrap">
        {retryMut.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <AlertCircle className="h-3 w-3" />}
        Retry OCR
      </button>
    );
  }
  if (doc.status === DocumentStatus.POSTED) {
    return <span className="text-xs text-green-600 font-medium">✓ Complete</span>;
  }
  return (
    <button onClick={(e) => { stop(e); navigate(`/documents/${doc.document_id}`); }}
      className="inline-flex items-center gap-1 text-xs text-neutral-400 hover:text-neutral-600 transition-colors">
      <ArrowRight className="h-3 w-3" /> View
    </button>
  );
}

// ─── Sort helpers ─────────────────────────────────────────────────────────────

type SortField = 'uploaded_at' | 'amount' | 'confidence_score';
type SortDir   = 'asc' | 'desc';

function sortDocs(
  docs: DocumentListItem[],
  field: SortField,
  dir: SortDir,
): DocumentListItem[] {
  return [...docs].sort((a, b) => {
    let av: number;
    let bv: number;
    if (field === 'uploaded_at') {
      av = new Date(a.uploaded_at).getTime();
      bv = new Date(b.uploaded_at).getTime();
    } else if (field === 'amount') {
      av = Number(a.amount) || 0;
      bv = Number(b.amount) || 0;
    } else {
      av = a.confidence_score ?? -1;
      bv = b.confidence_score ?? -1;
    }
    return dir === 'asc' ? av - bv : bv - av;
  });
}

// ─── Confidence cell ──────────────────────────────────────────────────────────

function ConfidenceCell({ score }: { score: number | undefined }) {
  if (score == null) return <span className="text-neutral-300">—</span>;
  const pct = Math.round(score * 100);
  const cls =
    pct >= 75 ? 'text-green-700 bg-green-50'
    : pct >= 50 ? 'text-amber-700 bg-amber-50'
    : 'text-red-700 bg-red-50';
  return (
    <span className={cn('inline-block rounded-full px-2 py-0.5 text-xs font-semibold tabular-nums', cls)}>
      {pct}%
    </span>
  );
}

// ─── Sortable header ──────────────────────────────────────────────────────────

function SortHeader({
  label, field, current, dir, onSort,
}: {
  label:  string;
  field:  SortField;
  current: SortField | null;
  dir:    SortDir;
  onSort: (f: SortField) => void;
}) {
  const active = current === field;
  return (
    <button
      type="button"
      onClick={() => onSort(field)}
      className="inline-flex items-center gap-1 text-xs font-semibold uppercase tracking-wider text-neutral-400 hover:text-neutral-600 transition-colors"
    >
      {label}
      {active
        ? dir === 'asc'
          ? <ChevronUp   className="h-3 w-3 text-primary-500" />
          : <ChevronDown className="h-3 w-3 text-primary-500" />
        : <ChevronsUpDown className="h-3 w-3 opacity-40" />
      }
    </button>
  );
}

// ─── Filter panel ─────────────────────────────────────────────────────────────

interface FilterState {
  status: DocumentStatus | '';
  type:   DocumentType | '';
  tcode:  TCode | '';
}

const EMPTY_FILTER: FilterState = { status: '', type: '', tcode: '' };

const STATUS_LABELS: Record<DocumentStatus, string> = {
  [DocumentStatus.UPLOADED]:   'Uploaded',
  [DocumentStatus.EXTRACTING]: 'Extracting',
  [DocumentStatus.EXTRACTED]:  'Extracted',
  [DocumentStatus.VALIDATING]: 'Validating',
  [DocumentStatus.VALIDATED]:  'Validated',
  [DocumentStatus.GR_POSTING]: 'GR Posting',
  [DocumentStatus.GR_POSTED]:  'GR Posted',
  [DocumentStatus.POSTING]:    'Posting',
  [DocumentStatus.POSTED]:     'Posted',
  [DocumentStatus.FAILED]:     'Failed',
};

interface FilterPanelProps {
  open:     boolean;
  draft:    FilterState;
  onChange: (f: FilterState) => void;
  onApply:  () => void;
  onReset:  () => void;
  onClose:  () => void;
}

function FilterPanel({ open, draft, onChange, onApply, onReset, onClose }: FilterPanelProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handle(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    }
    document.addEventListener('mousedown', handle);
    return () => document.removeEventListener('mousedown', handle);
  }, [open, onClose]);

  return (
    <>
      {/* Backdrop */}
      <div
        className={cn(
          'fixed inset-0 z-30 bg-black/20 transition-opacity',
          open ? 'opacity-100' : 'pointer-events-none opacity-0',
        )}
      />

      {/* Panel */}
      <div
        ref={ref}
        className={cn(
          'fixed inset-y-0 right-0 z-40 flex w-80 flex-col bg-white shadow-xl transition-transform duration-300 dark:bg-neutral-800',
          open ? 'translate-x-0' : 'translate-x-full',
        )}
      >
        <div className="flex items-center justify-between border-b border-neutral-100 px-5 py-4 dark:border-neutral-700">
          <h3 className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">Filter Documents</h3>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1 text-neutral-400 hover:bg-neutral-100 hover:text-neutral-600 transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-6">
          {/* Status */}
          <FilterSection label="Status">
            <RadioGroup
              options={[
                { value: '', label: 'All statuses' },
                ...Object.values(DocumentStatus).map((s) => ({
                  value: s,
                  label: STATUS_LABELS[s] ?? s,
                })),
              ]}
              value={draft.status}
              onChange={(v) => onChange({ ...draft, status: v as DocumentStatus | '' })}
            />
          </FilterSection>

          {/* Type */}
          <FilterSection label="Document Type">
            <RadioGroup
              options={[
                { value: '', label: 'All types' },
                ...Object.values(DocumentType).map((t) => ({
                  value: t,
                  label: DOC_TYPE_LABEL[t],
                })),
              ]}
              value={draft.type}
              onChange={(v) => onChange({ ...draft, type: v as DocumentType | '' })}
            />
          </FilterSection>

          {/* TCode */}
          <FilterSection label="T-Code">
            <RadioGroup
              options={[
                { value: '', label: 'All T-Codes' },
                ...Object.values(TCode).map((t) => ({ value: t, label: t })),
              ]}
              value={draft.tcode}
              onChange={(v) => onChange({ ...draft, tcode: v as TCode | '' })}
            />
          </FilterSection>
        </div>

        <div className="border-t border-neutral-100 px-5 py-4 flex gap-3 dark:border-neutral-700">
          <button
            type="button"
            onClick={onReset}
            className="flex-1 rounded-lg border border-neutral-200 py-2 text-sm font-medium text-neutral-600 hover:bg-neutral-50 transition-colors dark:border-neutral-700 dark:text-neutral-300 dark:hover:bg-neutral-700"
          >
            Reset
          </button>
          <button
            type="button"
            onClick={onApply}
            className="flex-1 rounded-lg bg-primary-600 py-2 text-sm font-semibold text-white hover:bg-primary-700 transition-colors"
          >
            Apply filters
          </button>
        </div>
      </div>
    </>
  );
}

function FilterSection({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-2.5 text-xs font-semibold uppercase tracking-wider text-neutral-400 dark:text-neutral-500">{label}</p>
      {children}
    </div>
  );
}

function RadioGroup({
  options, value, onChange,
}: {
  options: { value: string; label: string }[];
  value:   string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="space-y-2">
      {options.map((opt) => (
        <label key={opt.value} className="flex cursor-pointer items-center gap-2.5">
          <input
            type="radio"
            name="filter"
            value={opt.value}
            checked={value === opt.value}
            onChange={() => onChange(opt.value)}
            className="h-4 w-4 border-neutral-300 text-primary-600 focus:ring-primary-200"
          />
          <span className="text-sm text-neutral-700 dark:text-neutral-300">{opt.label}</span>
        </label>
      ))}
    </div>
  );
}

// ─── Active filter count ──────────────────────────────────────────────────────

function activeCount(f: FilterState): number {
  return [f.status, f.type, f.tcode].filter(Boolean).length;
}

// ─── Export helper ────────────────────────────────────────────────────────────

function exportCSV(docs: DocumentListItem[]) {
  const header = 'Document ID,Vendor,T-Code,Amount,Status,Confidence,Uploaded,MIRO #';
  const rows = docs.map((d) =>
    [
      d.document_id,
      d.vendor_name,
      d.tcode,
      d.amount,
      d.status,
      d.confidence_score != null ? `${Math.round(d.confidence_score * 100)}%` : '',
      d.uploaded_at,
      d.miro_number,
    ]
      .map((v) => `"${String(v ?? '').replace(/"/g, '""')}"`)
      .join(','),
  );
  const csv  = [header, ...rows].join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const url  = URL.createObjectURL(blob);
  const a    = Object.assign(document.createElement('a'), { href: url, download: 'documents.csv' });
  a.click();
  URL.revokeObjectURL(url);
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function DocumentsPage() {
  const navigate = useNavigate();

  // API filters (drives the query)
  const [filters, setFilters] = useState<DocumentFilters>({
    page: 1, limit: DEFAULT_PAGE_SIZE,
  });

  // Local UI state
  const [searchInput,   setSearchInput]   = useState('');
  const [searchExpanded, setSearchExpanded] = useState(false);
  const [panelOpen,     setPanelOpen]     = useState(false);
  const [draft,         setDraft]         = useState<FilterState>(EMPTY_FILTER);
  const [applied,       setApplied]       = useState<FilterState>(EMPTY_FILTER);
  const [sortField,     setSortField]     = useState<SortField | null>(null);
  const [sortDir,       setSortDir]       = useState<SortDir>('desc');

  const { data, isLoading } = useDocuments(filters);

  // Search debounce
  useEffect(() => {
    const id = setTimeout(() => {
      setFilters((f) => {
        const next = { ...f, page: 1 };
        if (searchInput) { next.search = searchInput; } else { delete next.search; }
        return next;
      });
    }, 300);
    return () => clearTimeout(id);
  }, [searchInput]);

  const toggleSort = useCallback((field: SortField) => {
    setSortField((prev) => {
      if (prev === field) {
        setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'));
        return field;
      }
      setSortDir('desc');
      return field;
    });
  }, []);

  function applyFilters() {
    setApplied(draft);
    setFilters((f) => {
      const next = { ...f, page: 1 };
      if (draft.status) { next.status = draft.status; } else { delete next.status; }
      if (draft.type)   { next.type   = draft.type;   } else { delete next.type;   }
      if (draft.tcode)  { next.tcode  = draft.tcode;  } else { delete next.tcode;  }
      return next;
    });
    setPanelOpen(false);
  }

  function resetFilters() {
    setDraft(EMPTY_FILTER);
    setApplied(EMPTY_FILTER);
    setFilters((f) => {
      const next = { ...f, page: 1 };
      delete next.status;
      delete next.type;
      delete next.tcode;
      return next;
    });
    setPanelOpen(false);
  }

  function clearAllFilters() {
    setSearchInput('');
    resetFilters();
  }

  function setPageSize(size: number) {
    setFilters((f) => ({ ...f, page: 1, limit: size }));
  }

  const rawDocs = data?.documents ?? [];
  const docs    = sortField ? sortDocs(rawDocs, sortField, sortDir) : rawDocs;
  const badge   = activeCount(applied);
  const page    = filters.page ?? 1;
  const limit   = filters.limit ?? DEFAULT_PAGE_SIZE;
  const total   = data?.total ?? 0;
  const pages   = data?.pages ?? 1;

  return (
    <>
      <Topbar title="Documents" subtitle={total > 0 ? `${total} total` : 'All processed documents'}>
        <Button variant="secondary" size="sm" onClick={() => exportCSV(docs)}
          disabled={docs.length === 0}>
          <Download className="h-4 w-4" />
          Export
        </Button>
        <Button size="sm" onClick={() => navigate('/upload')}>
          <Upload className="h-4 w-4" />
          Upload New
        </Button>
      </Topbar>

      <div className="space-y-4 p-6">

        {/* Filter bar */}
        <div className="flex flex-wrap items-center gap-2">

          {/* Search */}
          <div className={cn(
            'flex items-center gap-2 rounded-lg border border-neutral-200 bg-white px-3 transition-all duration-200 dark:border-neutral-700 dark:bg-neutral-800',
            searchExpanded ? 'w-64' : 'w-9',
          )}>
            <button
              type="button"
              onClick={() => setSearchExpanded((v) => !v)}
              className="shrink-0 text-neutral-400 hover:text-neutral-600 transition-colors"
              aria-label="Toggle search"
            >
              <Search className="h-4 w-4" />
            </button>
            {searchExpanded && (
              <input
                autoFocus
                type="text"
                placeholder="Search vendor, PO…"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                className="w-full bg-transparent py-2 text-sm text-neutral-800 placeholder:text-neutral-400 focus:outline-none dark:text-neutral-200 dark:placeholder:text-neutral-600"
              />
            )}
            {searchExpanded && searchInput && (
              <button
                type="button"
                onClick={() => setSearchInput('')}
                className="shrink-0 text-neutral-300 hover:text-neutral-500"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>

          {/* Filter toggle */}
          <button
            type="button"
            onClick={() => { setDraft(applied); setPanelOpen(true); }}
            className={cn(
              'relative inline-flex items-center gap-1.5 rounded-lg border px-3 py-[7px] text-sm font-medium transition-colors',
              badge > 0
                ? 'border-primary-300 bg-primary-50 text-primary-700 hover:bg-primary-100'
                : 'border-neutral-200 bg-white text-neutral-600 hover:bg-neutral-50',
            )}
          >
            <SlidersHorizontal className="h-4 w-4" />
            Filters
            {badge > 0 && (
              <span className="flex h-4 w-4 items-center justify-center rounded-full bg-primary-600 text-[10px] font-bold text-white">
                {badge}
              </span>
            )}
          </button>

          {/* Clear filters */}
          {(badge > 0 || searchInput) && (
            <button
              type="button"
              onClick={clearAllFilters}
              className="inline-flex items-center gap-1 text-xs text-neutral-400 hover:text-neutral-600 transition-colors"
            >
              <X className="h-3 w-3" />
              Clear
            </button>
          )}

          {/* Page size */}
          <div className="ml-auto flex items-center gap-2 text-sm text-neutral-500">
            <span className="text-xs">Show</span>
            <div className="flex rounded-lg border border-neutral-200 bg-white overflow-hidden dark:border-neutral-700 dark:bg-neutral-800">
              {PAGE_SIZE_OPTIONS.map((n) => (
                <button
                  key={n}
                  type="button"
                  onClick={() => setPageSize(n)}
                  className={cn(
                    'px-3 py-1.5 text-xs font-medium transition-colors',
                    limit === n
                      ? 'bg-neutral-900 text-white dark:bg-neutral-100 dark:text-neutral-900'
                      : 'text-neutral-500 hover:bg-neutral-50 dark:text-neutral-400 dark:hover:bg-neutral-700',
                  )}
                >
                  {n}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Table */}
        <div className="overflow-hidden rounded-xl bg-white ring-1 ring-neutral-200/60 shadow-soft dark:bg-neutral-800 dark:ring-neutral-700/60 dark:shadow-none">
          <Table>
            <TableHead>
              <TableRow>
                <TableHeaderCell>Document ID</TableHeaderCell>
                <TableHeaderCell>Vendor</TableHeaderCell>
                <TableHeaderCell>T-Code</TableHeaderCell>
                <TableHeaderCell>
                  <SortHeader label="Amount" field="amount" current={sortField} dir={sortDir} onSort={toggleSort} />
                </TableHeaderCell>
                <TableHeaderCell>
                  <SortHeader label="Confidence" field="confidence_score" current={sortField} dir={sortDir} onSort={toggleSort} />
                </TableHeaderCell>
                <TableHeaderCell>Status</TableHeaderCell>
                <TableHeaderCell>Uploaded By</TableHeaderCell>
                <TableHeaderCell>
                  <SortHeader label="Date" field="uploaded_at" current={sortField} dir={sortDir} onSort={toggleSort} />
                </TableHeaderCell>
                <TableHeaderCell>MIRO #</TableHeaderCell>
                <TableHeaderCell>Action</TableHeaderCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {isLoading
                ? Array.from({ length: 8 }, (_, i) => (
                    <TableRow key={i}>
                      <TableCell colSpan={10} className="p-0">
                        <SkeletonRow />
                      </TableCell>
                    </TableRow>
                  ))
                : docs.length === 0
                  ? (
                      <TableRow>
                        <TableCell colSpan={10}>
                          <div className="flex flex-col items-center gap-3 py-16 text-center">
                            <p className="text-sm font-medium text-neutral-500">No documents match your filters</p>
                            {(badge > 0 || searchInput) && (
                              <button
                                type="button"
                                onClick={clearAllFilters}
                                className="text-xs text-primary-600 underline hover:no-underline"
                              >
                                Clear filters
                              </button>
                            )}
                          </div>
                        </TableCell>
                      </TableRow>
                    )
                  : docs.map((doc) => (
                      <TableRow
                        key={doc.id}
                        className="cursor-pointer"
                        onClick={() => navigate(`/documents/${doc.document_id}`)}
                      >
                        <TableCell className="font-mono text-xs text-neutral-500">
                          {doc.document_id.slice(0, 8)}…
                        </TableCell>
                        <TableCell className="font-medium">{doc.vendor_name || '—'}</TableCell>
                        <TableCell><TCodeChip tcode={doc.tcode} /></TableCell>
                        <TableCell className="tabular-nums">{doc.amount != null ? toINR(Number(doc.amount)) : '—'}</TableCell>
                        <TableCell><ConfidenceCell score={doc.confidence_score} /></TableCell>
                        <TableCell><StatusPill status={doc.status} /></TableCell>
                        <TableCell className="text-neutral-500 text-xs">{doc.uploaded_by ?? '—'}</TableCell>
                        <TableCell className="text-neutral-500">{formatDate(doc.uploaded_at)}</TableCell>
                        <TableCell className="font-mono text-xs">{doc.miro_number || '—'}</TableCell>
                        <TableCell onClick={(e) => e.stopPropagation()}>
                          <RowAction doc={doc} />
                        </TableCell>
                      </TableRow>
                    ))
              }
            </TableBody>
          </Table>
        </div>

        {/* Pagination */}
        {pages > 1 && (
          <div className="flex items-center justify-between text-sm text-neutral-500">
            <span className="text-xs">
              Showing {(page - 1) * limit + 1}–{Math.min(page * limit, total)} of {total}
            </span>
            <div className="flex items-center gap-1">
              <Button
                variant="secondary" size="sm"
                disabled={page === 1}
                onClick={() => setFilters((f) => ({ ...f, page: (f.page ?? 1) - 1 }))}
              >
                Previous
              </Button>
              {Array.from({ length: Math.min(pages, 5) }, (_, i) => {
                const p = page <= 3 ? i + 1 : page - 2 + i;
                if (p < 1 || p > pages) return null;
                return (
                  <button
                    key={p}
                    type="button"
                    onClick={() => setFilters((f) => ({ ...f, page: p }))}
                    className={cn(
                      'h-8 w-8 rounded-lg text-xs font-medium transition-colors',
                      p === page
                        ? 'bg-neutral-900 text-white dark:bg-neutral-100 dark:text-neutral-900'
                        : 'border border-neutral-200 bg-white text-neutral-600 hover:bg-neutral-50 dark:border-neutral-700 dark:bg-neutral-800 dark:text-neutral-300 dark:hover:bg-neutral-700',
                    )}
                  >
                    {p}
                  </button>
                );
              })}
              <Button
                variant="secondary" size="sm"
                disabled={page === pages}
                onClick={() => setFilters((f) => ({ ...f, page: (f.page ?? 1) + 1 }))}
              >
                Next
              </Button>
            </div>
          </div>
        )}
      </div>

      {/* Slide-in filter panel */}
      <FilterPanel
        open={panelOpen}
        draft={draft}
        onChange={setDraft}
        onApply={applyFilters}
        onReset={resetFilters}
        onClose={() => setPanelOpen(false)}
      />
    </>
  );
}
