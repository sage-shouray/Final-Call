// ─────────────────────────────────────────────────────────────────────────────
// Enums
// ─────────────────────────────────────────────────────────────────────────────

export enum DocumentStatus {
  UPLOADED   = 'uploaded',
  EXTRACTING = 'extracting',
  EXTRACTED  = 'extracted',
  VALIDATING = 'validating',
  VALIDATED  = 'validated',
  POSTING    = 'posting',
  POSTED     = 'posted',
  FAILED     = 'failed',
}

export enum DocumentType {
  VENDOR_INVOICE  = 'vendor_invoice',
  BANK_STATEMENT  = 'bank_statement',
  PAYMENT_ADVICE  = 'payment_advice',
  GOODS_RECEIPT   = 'goods_receipt',
  FREIGHT_INVOICE = 'freight_invoice',
}

export enum TCode {
  MIRO = 'MIRO',
  FF67 = 'FF67',
  F28  = 'F-28',
  MIGO = 'MIGO',
}

export enum UserRole {
  ADMIN    = 'admin',
  MANAGER  = 'manager',
  OPERATOR = 'operator',
}

// ─────────────────────────────────────────────────────────────────────────────
// Domain models (mirror backend Pydantic schemas)
// ─────────────────────────────────────────────────────────────────────────────

export interface LineItem {
  line_number:   string;
  material_code: string;
  description:   string;
  quantity:      string;
  uom:           string;
  unit_rate:     string;
  amount:        string;
  tax_code:      string;
  tax_amount:    string;
  hsn_code:      string;
  grn_reference: string;
}

export interface ExtractedData {
  invoice_no:       string;
  invoice_date:     string;
  po_number:        string;
  vendor_id:        string;
  vendor_name:      string;
  vendor_gstin:     string;
  vendor_address:   string;
  bill_to_name:     string;
  bill_to_address:  string;
  ship_to_name:     string;
  ship_to_address:  string;
  currency:         string;
  gross_amount:     string;
  tax_amount:       string;
  net_amount:       string;
  payment_terms:    string;
  bank_details:     string;
  reference_doc:    string;
  confidence_score: number;
  line_items:       LineItem[];
  raw_ocr_response: Record<string, unknown>;
}

export interface MismatchEntry {
  field:           string;
  extracted_value: string;
  sap_value:       string;
  severity:        'error' | 'warning';
}

export interface GRStatusEntry {
  line_number:    string;
  po_item:        string;
  gr_documents:   string[];
  total_gr_qty:   number;
  invoice_qty:    number;
  status:         'complete' | 'partial' | 'missing';
}

export interface SAPValidation {
  fetched_at:          string;
  po_data:             Record<string, unknown>;
  header_confidence:   number;
  line_item_confidence: number;
  gr_confidence:       number;
  overall_confidence:  number;
  mismatches:          MismatchEntry[];
  gr_status:           GRStatusEntry[];
  is_valid:            boolean;
  recommendation:      string;
}

export interface MIROPosting {
  posted_at:    string;
  payload_sent: Record<string, unknown>;
  miro_number:  string;
  sap_response: Record<string, unknown>;
  status:       'success' | 'failed';
}

export interface ErrorEntry {
  timestamp: string;
  stage:     string;
  message:   string;
  detail:    string;
}

export interface FileMetadata {
  original_name: string;
  s3_key:        string;
  size_bytes:    number;
  mime_type:     string;
}

export interface Document {
  id:             string;
  document_id:    string;
  type:           DocumentType;
  tcode:          TCode;
  status:         DocumentStatus;
  uploaded_by:    string;
  uploaded_at:    string;
  file:           FileMetadata;
  extracted:      ExtractedData | null;
  sap_validation: SAPValidation | null;
  miro_posting:   MIROPosting | null;
  retry_count:    number;
  error_log:      ErrorEntry[];
  created_at:     string;
  updated_at:     string;
}

export interface DocumentListItem {
  id:               string;
  document_id:      string;
  type:             string;
  tcode:            string;
  status:           DocumentStatus;
  uploaded_at:      string;
  vendor_name:      string;
  amount:           string;
  miro_number:      string;
  confidence_score?: number | undefined;
  uploaded_by?:     string | undefined;
}

export interface ValidationResult {
  document_id:          string;
  overall_confidence:   number;
  header_confidence:    number;
  line_item_confidence: number;
  gr_confidence:        number;
  mismatches:           MismatchEntry[];
  gr_status:            GRStatusEntry[];
  is_valid:             boolean;
  recommendation:       string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Auth
// ─────────────────────────────────────────────────────────────────────────────

export interface User {
  id:        string;
  email:     string;
  name:      string;
  role:      UserRole;
  is_active: boolean;
}

export interface AuthTokens {
  access_token:  string;
  refresh_token: string;
  token_type:    string;
  expires_in:    number;
}

export interface LoginCredentials {
  email:    string;
  password: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Dashboard
// ─────────────────────────────────────────────────────────────────────────────

export interface TCodeStat {
  tcode:      string;
  count:      number;
  percentage: number;
}

export interface StatusStat {
  status:     string;
  count:      number;
  percentage: number;
}

export interface TypeStat {
  type:  string;
  count: number;
}

export interface TrendPoint {
  date:  string;
  count: number;
}

export interface DashboardMetrics {
  total_processed: number;
  posted_to_sap:   number;
  pending_review:  number;
  failed:          number;
  total_value_inr: string;
  by_tcode:        TCodeStat[];
  by_status:       StatusStat[];
  by_type:         TypeStat[];
  recent_trend:    TrendPoint[];
}

// ─────────────────────────────────────────────────────────────────────────────
// WebSocket events
// ─────────────────────────────────────────────────────────────────────────────

export type WebSocketEventType =
  | 'INITIAL_STATE'
  | 'STATUS_CHANGED'
  | 'OCR_COMPLETE'
  | 'VALIDATION_COMPLETE'
  | 'MIRO_POSTED'
  | 'ERROR'
  | 'PING';

export interface WebSocketEventData {
  step:             number;
  label:            string;
  extracted_fields?: number;
  confidence?:      number;
  [key: string]:    unknown;
}

export interface WebSocketEvent {
  event:       WebSocketEventType;
  document_id: string;
  status:      DocumentStatus;
  timestamp:   string;
  data:        WebSocketEventData;
}

// ─────────────────────────────────────────────────────────────────────────────
// API response envelopes
// ─────────────────────────────────────────────────────────────────────────────

export interface APIError {
  code:       string;
  message:    string;
  details:    Record<string, unknown>;
  request_id: string;
  timestamp:  string;
}

export interface APIResponse<T> {
  data: T;
}

export interface PaginatedResponse<T> {
  documents: T[];
  total:     number;
  page:      number;
  limit:     number;
  pages:     number;
}

export interface DocumentFilters {
  status?: DocumentStatus;
  type?:   DocumentType;
  tcode?:  TCode;
  search?: string;
  page?:   number;
  limit?:  number;
}
