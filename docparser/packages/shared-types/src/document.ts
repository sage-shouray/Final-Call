export type DocumentStatus =
  | 'pending'
  | 'uploading'
  | 'processing'
  | 'extracting'
  | 'validating'
  | 'completed'
  | 'failed'
  | 'cancelled';

export type DocumentType =
  | 'invoice'
  | 'purchase_order'
  | 'goods_receipt'
  | 'delivery_note'
  | 'credit_memo'
  | 'unknown';

export interface Document {
  id: string;
  filename: string;
  originalName: string;
  mimeType: string;
  sizeBytes: number;
  status: DocumentStatus;
  documentType: DocumentType;
  uploadedAt: string;
  processedAt?: string;
  extractedData?: Record<string, unknown>;
  sapDocumentNumber?: string;
  sapPostingDate?: string;
  errorMessage?: string;
  tags: string[];
  createdBy: string;
}

export interface DocumentUploadRequest {
  file: File;
  documentType?: DocumentType;
  tags?: string[];
}

export interface DocumentFilters {
  status?: DocumentStatus;
  documentType?: DocumentType;
  dateFrom?: string;
  dateTo?: string;
  search?: string;
  tags?: string[];
  page?: number;
  pageSize?: number;
}
