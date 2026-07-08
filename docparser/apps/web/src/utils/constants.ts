import {
  FileText, ClipboardList, FileCheck, Package, Truck,
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
  [DocumentType.VENDOR_INVOICE]:  { label: 'Vendor Invoice',  tcode: TCode.MIRO, icon: FileText,       active: true  },
  [DocumentType.SALES_ORDER]:     { label: 'Sales Order',     tcode: TCode.VA01, icon: ClipboardList,  active: true  },
  [DocumentType.PAYMENT_ADVICE]:  { label: 'Payment Advice',  tcode: TCode.F28,  icon: FileCheck,      active: true  },
  [DocumentType.GOODS_RECEIPT]:   { label: 'Goods Receipt',   tcode: TCode.MIGO, icon: Package,        active: true  },
  [DocumentType.FREIGHT_INVOICE]: { label: 'Freight Invoice', tcode: TCode.MIRO, icon: Truck,          active: true  },
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
  [DocumentStatus.VALIDATED]:  { label: 'Validated',   badgeColor: 'success',  step: 5 },
  [DocumentStatus.GR_POSTING]: { label: 'GR Posting',  badgeColor: 'warning',  step: 6 },
  [DocumentStatus.GR_POSTED]:  { label: 'GR Posted',   badgeColor: 'success',  step: 7 },
  [DocumentStatus.POSTING]:    { label: 'Posting',     badgeColor: 'warning',  step: 8 },
  [DocumentStatus.POSTED]:     { label: 'Posted',      badgeColor: 'success',  step: 9 },
  [DocumentStatus.FAILED]:     { label: 'Failed',     badgeColor: 'error',    step: 0 },
};

// ─── T-Code labels ────────────────────────────────────────────────────────────

export const TCODE_LABEL: Record<TCode, string> = {
  [TCode.MIRO]: 'Invoice Verification',
  [TCode.FB60]: 'Non-PO Invoice',
  [TCode.VA01]: 'Sales Order',
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

export const APP_NAME    = 'Uvira.ai';
export const APP_VERSION = '1.0';
export const APP_COMPANY = 'SSDN Technologies';

export const PAGE_SIZE_OPTIONS = [20, 50, 100] as const;
export const DEFAULT_PAGE_SIZE = 20;
export const MAX_UPLOAD_SIZE   = 20 * 1024 * 1024; // 20 MB
