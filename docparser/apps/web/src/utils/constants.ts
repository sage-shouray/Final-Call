import {
  FileText, Landmark, FileCheck, Package, Truck,
  type LucideIcon,
} from 'lucide-react';
import { DocumentStatus, DocumentType, TCode } from '@/types';

// ─── Document types ───────────────────────────────────────────────────────────

export interface DocTypeConfig {
  label:  string;
  tcode:  TCode;
  icon:   LucideIcon;
  active: boolean;
}

export const DOC_TYPE_CONFIG: Record<DocumentType, DocTypeConfig> = {
  [DocumentType.VENDOR_INVOICE]:  { label: 'Vendor Invoice',  tcode: TCode.MIRO, icon: FileText,  active: true  },
  [DocumentType.BANK_STATEMENT]:  { label: 'Bank Statement',  tcode: TCode.FF67, icon: Landmark,  active: false },
  [DocumentType.PAYMENT_ADVICE]:  { label: 'Payment Advice',  tcode: TCode.F28,  icon: FileCheck, active: false },
  [DocumentType.GOODS_RECEIPT]:   { label: 'Goods Receipt',   tcode: TCode.MIGO, icon: Package,   active: false },
  [DocumentType.FREIGHT_INVOICE]: { label: 'Freight Invoice', tcode: TCode.MIRO, icon: Truck,     active: false },
};

export const DOC_TYPE_LABEL = Object.fromEntries(
  Object.entries(DOC_TYPE_CONFIG).map(([k, v]) => [k, v.label]),
) as Record<DocumentType, string>;

// ─── Document status ──────────────────────────────────────────────────────────

export interface StatusConfig {
  label:      string;
  badgeColor: string;
  step:       number;
}

export const STATUS_CONFIG: Record<DocumentStatus, StatusConfig> = {
  [DocumentStatus.UPLOADED]:   { label: 'Uploaded',   badgeColor: 'neutral',  step: 1 },
  [DocumentStatus.EXTRACTING]: { label: 'Extracting', badgeColor: 'info',     step: 2 },
  [DocumentStatus.EXTRACTED]:  { label: 'Extracted',  badgeColor: 'info',     step: 3 },
  [DocumentStatus.VALIDATING]: { label: 'Validating', badgeColor: 'warning',  step: 4 },
  [DocumentStatus.VALIDATED]:  { label: 'Validated',  badgeColor: 'success',  step: 5 },
  [DocumentStatus.POSTING]:    { label: 'Posting',    badgeColor: 'warning',  step: 6 },
  [DocumentStatus.POSTED]:     { label: 'Posted',     badgeColor: 'success',  step: 7 },
  [DocumentStatus.FAILED]:     { label: 'Failed',     badgeColor: 'error',    step: 0 },
};

// ─── T-Code labels ────────────────────────────────────────────────────────────

export const TCODE_LABEL: Record<TCode, string> = {
  [TCode.MIRO]: 'Invoice Verification',
  [TCode.FF67]: 'Bank Statement',
  [TCode.F28]:  'Payment Posting',
  [TCode.MIGO]: 'Goods Movement',
};

// ─── API endpoints ────────────────────────────────────────────────────────────

export const API = {
  AUTH: {
    LOGIN:   '/auth/login',
    LOGOUT:  '/auth/logout',
    REFRESH: '/auth/refresh',
    ME:      '/auth/me',
  },
  DOCUMENTS: {
    LIST:      '/documents',
    UPLOAD:    '/documents/upload',
    BY_ID:     (id: string) => `/documents/${id}`,
    VALIDATE:  (id: string) => `/documents/${id}/validate`,
    VALIDATION:(id: string) => `/documents/${id}/validation`,
    POST_MIRO: (id: string) => `/documents/${id}/post-miro`,
    AUDIT:     (id: string) => `/documents/${id}/audit`,
  },
  DASHBOARD: {
    METRICS: '/dashboard/metrics',
  },
} as const;

// ─── Misc ─────────────────────────────────────────────────────────────────────

export const APP_NAME    = 'DocParser';
export const APP_VERSION = '1.0';
export const APP_COMPANY = 'SSDN Technologies';

export const PAGE_SIZE_OPTIONS = [20, 50, 100] as const;
export const DEFAULT_PAGE_SIZE = 20;
export const MAX_UPLOAD_SIZE   = 20 * 1024 * 1024; // 20 MB
