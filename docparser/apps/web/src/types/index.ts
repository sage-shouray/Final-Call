// ─────────────────────────────────────────────────────────────────────────────
// Enums
// ─────────────────────────────────────────────────────────────────────────────

export enum DocumentStatus {
  UPLOADED   = 'uploaded',
  EXTRACTING = 'extracting',
  EXTRACTED  = 'extracted',
  VALIDATING = 'validating',
  VALIDATED  = 'validated',
  GR_POSTING = 'gr_posting',
  GR_POSTED  = 'gr_posted',
  POSTING    = 'posting',
  POSTED     = 'posted',
  FAILED     = 'failed',
}

export enum DocumentType {
  VENDOR_INVOICE  = 'vendor_invoice',
  SALES_ORDER     = 'sales_order',
  PAYMENT_ADVICE  = 'payment_advice',
  GOODS_RECEIPT   = 'goods_receipt',
  FREIGHT_INVOICE = 'freight_invoice',
}

export enum TCode {
  MIRO = 'MIRO',
  FB60 = 'FB60',
  VA01 = 'VA01',
  F28  = 'F-28',
  MIGO = 'MIGO',
}

export enum InvoiceSubtype {
  PO         = 'po',
  SERVICE_PO = 'service_po',
  FREIGHT_PO = 'freight_po',
  NON_PO     = 'non_po',
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
  line_number:    string;
  material_code:  string;
  hsn_code:       string;
  description:    string;
  quantity:       string;
  uom:            string;
  unit_rate:      string;
  discount:       string;
  taxable_amount: string;
  cgst_rate:      string;
  cgst_amount:    string;
  sgst_rate:      string;
  sgst_amount:    string;
  igst_rate:      string;
  igst_amount:    string;
  cess_rate:      string;
  cess_amount:    string;
  tax_code:       string;
  tax_amount:     string;
  amount:         string;
  grn_reference:  string;
}

export interface ExtractedData {
  // Invoice header
  invoice_no:               string;
  invoice_date:             string;
  due_date:                 string;
  po_number:                string;
  delivery_note:            string;
  dispatch_doc_no:          string;
  dispatched_through:       string;
  destination:              string;
  invoice_type:             string;
  reverse_charge_applicable: string;
  place_of_supply:          string;

  // e-Invoice / e-Way Bill
  irn_number:               string;
  eway_bill_no:             string;
  eway_bill_date:           string;
  eway_bill_valid_upto:     string;

  // Vendor
  vendor_id:                string;
  vendor_name:              string;
  vendor_gstin:             string;
  vendor_pan:               string;
  vendor_address:           string;
  vendor_state:             string;
  vendor_state_code:        string;
  vendor_email:             string;
  vendor_phone:             string;

  // Buyer / Bill-to
  bill_to_name:             string;
  bill_to_gstin:            string;
  bill_to_address:          string;
  bill_to_state:            string;
  bill_to_state_code:       string;

  // Ship-to
  ship_to_name:             string;
  ship_to_gstin:            string;
  ship_to_address:          string;
  ship_to_state:            string;
  ship_to_state_code:       string;

  // Financials
  currency:                 string;
  taxable_amount:           string;
  cgst_rate:                string;
  cgst_amount:              string;
  sgst_rate:                string;
  sgst_amount:              string;
  igst_rate:                string;
  igst_amount:              string;
  cess_amount:              string;
  tds_amount:               string;
  tcs_amount:               string;
  discount_amount:          string;
  freight_charges:          string;
  packing_charges:          string;
  insurance_charges:        string;
  other_charges:            string;
  round_off:                string;
  tax_amount:               string;
  gross_amount:             string;
  net_amount:               string;

  // Payment & Bank
  payment_terms:            string;
  bank_name:                string;
  bank_account_no:          string;
  bank_ifsc:                string;
  bank_branch:              string;
  bank_details:             string;

  // Transport / Logistics
  vehicle_no:               string;
  lr_no:                    string;
  lr_date:                  string;
  transport_name:           string;
  mode_of_transport:        string;
  terms_of_delivery:        string;

  // Other
  declaration:              string;
  notes:                    string;
  reference_doc:            string;

  // AI metadata
  confidence_score:         number;
  line_items:               LineItem[];
  raw_ocr_response:         Record<string, unknown>;
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

export interface GRNPosting {
  posted_at:    string;
  payload_sent: Record<string, unknown>;
  grn_number:   string;
  sap_response: Record<string, unknown>;
  status:       'success' | 'failed' | 'pending';
  already_done: boolean;
  message:      string;
}

export interface FB60InvoiceItem {
  line_no:        number;
  gl:             string;
  amount:         number;
  tax_code:       string;
  business_place: string;
  value_date:     string;
  assignment_no:  string;
  text:           string;
  cost_center:    string;
  profit_center:  string;
  special_gl:     string;
  baseline_date:  string;
  wht_tax:        string;
}

export interface FB60FormData {
  invoice_doc_date: string;
  document_type:    string;
  company_code:     string;
  posting_date:     string;
  currency:         string;
  reference:        string;
  header_text:      string;
  vendor:           string;
  invoice_items:    FB60InvoiceItem[];
}

export interface FB60Posting {
  posted_at:    string;
  payload_sent: Record<string, unknown>;
  fb60_number:  string;
  sap_response: Record<string, unknown>;
  status:       'success' | 'failed';
  message:      string;
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
  id:               string;
  document_id:      string;
  type:             DocumentType;
  tcode:            TCode;
  invoice_subtype:  InvoiceSubtype | null;
  status:           DocumentStatus;
  uploaded_by:    string;
  uploaded_at:    string;
  file:           FileMetadata;
  extracted:      ExtractedData | null;
  sap_validation: SAPValidation | null;
  grn_posting:    GRNPosting | null;
  miro_posting:   MIROPosting | null;
  fb60_posting:   FB60Posting | null;
  so_simulation:  Record<string, unknown> | null;
  so_posting:     Record<string, unknown> | null;
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
  invoice_subtype:  string;
  grn_number:       string;
  miro_number:      string;
  fb60_number:      string;
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
