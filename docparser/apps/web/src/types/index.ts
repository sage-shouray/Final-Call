// ─────────────────────────────────────────────────────────────────────────────
// Enums
// ─────────────────────────────────────────────────────────────────────────────

export enum DocumentStatus {
  UPLOADED    = 'uploaded',
  EXTRACTING  = 'extracting',
  EXTRACTED   = 'extracted',
  VALIDATING  = 'validating',
  VALIDATED   = 'validated',
  GR_POSTING  = 'gr_posting',
  GR_POSTED   = 'gr_posted',
  SIMULATING  = 'simulating',
  SIMULATED   = 'simulated',
  POSTING     = 'posting',
  POSTED      = 'posted',
  PARKED      = 'parked',
  FAILED      = 'failed',
}

export enum DocumentType {
  VENDOR_INVOICE  = 'vendor_invoice',
  SALES_ORDER     = 'sales_order',
  PAYMENT_ADVICE  = 'payment_advice',
  GOODS_RECEIPT   = 'goods_receipt',
  FREIGHT_INVOICE = 'freight_invoice',
  CREDIT_NOTE     = 'credit_note',
}

export enum TCode {
  MIRO   = 'MIRO',
  FB60   = 'FB60',
  VA01   = 'VA01',
  F28    = 'F-28',
  MIGO   = 'MIGO',
  CREDIT = 'CREDIT',
}

export enum CreditCase {
  CREDIT_MEMO       = 'credit_memo',
  SUBSEQUENT_CREDIT = 'subsequent_credit',
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

// ── Service PO ───────────────────────────────────────────────────────────────
// 'full'     — the PO line's value is now fully consumed
// 'partial'  — value remains on the line for a later invoice
// 'rejected' — SAP refused it, or validation passed but the MIRO was not created
export type ServicePOCase = 'full' | 'partial' | 'rejected';

/** One line's outcome from ZSPO_VALD/SERV_PO_VAL, which validates *and* posts. */
export interface ServicePOLineCheck {
  po_item:           string;
  validation_status: string;
  miro_status:       string;
  message:           string;
  case:              ServicePOCase;
  posted:            boolean;
  miro_number:       string;
  fiscal_year?:      number;
  /** True when a retry skipped this line because it was already posted. */
  skipped?:          boolean;
  invoice_qty:       number;
  invoice_amount:    number;
  total_qty:         number;
  total_net:         number;
  consumed_qty:      number;
  consumed_net:      number;
  available_qty:     number;
  available_net:     number;
  remaining_qty:     number;
  remaining_net:     number;
  blocking_reason:   string;
}

/** Result of the Service PO posting step — lives on miro_posting.sap_response. */
export interface ServicePOPosting {
  posted_at:        string;
  lines:            ServicePOLineCheck[];
  case:             ServicePOCase | 'none';
  blocking_reasons: string[];
  miro_numbers:     string[];
  miro_number:      string;
  all_posted:       boolean;
}

/**
 * Gates checked at validation time. Availability against prior invoices is NOT
 * among them: the only endpoint reporting it also posts the MIRO, so SAP performs
 * that check during posting instead.
 */
export interface ServicePOGates {
  ses_present:    boolean;
  within_po_line: boolean;
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
  // Service PO only
  gates?: ServicePOGates;
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

export interface F26FormData {
  company_code:  string;
  customer:      string;
  invoice:       string;
  fiscal_year:   string;
  document_date: string;
  posting_date:  string;
  currency:      string;
  amount:        string;
  bank_gl:       string;
  value_date:    string;
  reference:     string;
  header_text:   string;
  item_text:     string;
}

export interface F26Simulation {
  simulated_at: string;
  payload_sent: Record<string, unknown>;
  status:       string;
  message:      string;
  success:      boolean;
  sap_response: Record<string, unknown>;
}

export interface F26Posting {
  posted_at:       string;
  payload_sent:    Record<string, unknown>;
  document_number: string;
  message:         string;
  status:          'success' | 'failed';
  sap_response:    Record<string, unknown>;
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

export interface MIROParking {
  parked_at:    string;
  payload_sent: Record<string, unknown>;
  park_number:  string;
  sap_response: Record<string, unknown>;
  message:      string;
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
  miro_parking:   MIROParking | null;
  fb60_posting:   FB60Posting | null;
  so_simulation:  Record<string, unknown> | null;
  so_posting:     Record<string, unknown> | null;
  f26_simulation: F26Simulation | null;
  f26_posting:    F26Posting | null;
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
  park_number:      string;
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
// Credit Note comparison (extracted invoice vs. originally posted MIRO)
// ─────────────────────────────────────────────────────────────────────────────

export interface CreditLineDiff {
  line_number:        string;
  po_item:             string;
  material_code:       string;
  extracted_quantity:  number;
  miro_quantity:       number;
  quantity_changed:    boolean;
  extracted_price:     number;
  miro_price:          number;
  price_changed:       boolean;
  extracted_amount:    number;
  miro_amount:         number;
  extracted_tax:       number;
  miro_tax:            number;
  matched:             boolean;
}

export interface CreditComparisonResult {
  document_id:  string;
  po_number:    string;
  miro_posted:  boolean;
  miro_message: string;
  credit_case:  CreditCase | null;
  reason:       string;
  line_diffs:   CreditLineDiff[];
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
